{#
    oro.kpi_hora: las series de Grafana, una fila por hora en punto de la ventana, (run_id,
    hora). Ver el bloque de documentación «kpi_hora» en oro.md.

    Tres familias (decisión 106, H8-7), cada una apuntada a una hora:
      - la hora en punto (el instante): el censo, los boxes ocupados y los médicos;
      - la hora de llegada (la cohorte): las esperas con sus pendientes, los que se van sin
        ser vistos y la estancia;
      - la hora en que pasa (el intervalo [hora, hora + 1 h)): las llegadas (registros, como en
        kpi_ejecucion), los triajes por nivel, las estancias en box por su entrada y las que
        acaban desplazadas o liberadas para esperar resultados, por su salida.
#}
with parametros as (

    select * from {{ ref('parametros') }}

), horas as (

    select * from {{ ref('censo') }}

), vigentes as (

    -- Los registros de la llegada y del triaje, con su hora: floor de las horas desde el origen.
    select
        v.run_id,
        v.event_type,
        v.payload,
        floor(extract(epoch from v.event_time - p.origen) / 3600)::bigint as k
    from {{ ref('registros_vigentes') }} as v
    join parametros as p using (run_id)
    where v.event_type in ('patient_arrived', 'triage_completed')

), llegadas as (

    select run_id, k, count(*) as llegadas
    from vigentes
    where event_type = 'patient_arrived'
    group by run_id, k

), niveles as (

    -- Un nivel legible es un entero del 1 al 5, como en kpi_ejecucion; el resto, sin nivel.
    select
        run_id,
        k,
        {%- for n in range(1, 6) %}
        count(*) filter (
            where jsonb_typeof(payload -> 'nivel') = 'number' and payload ->> 'nivel' = '{{ n }}'
        ) as nivel_{{ n }},
        {%- endfor %}
        count(*) filter (
            where not coalesce(
                jsonb_typeof(payload -> 'nivel') = 'number'
                and payload ->> 'nivel' in ('1', '2', '3', '4', '5'),
                false
            )
        ) as sin_nivel
    from vigentes
    where event_type = 'triage_completed'
    group by run_id, k

), cohorte as (

    select
        run_id,
        k,
        percentile_cont(0.5) within group (order by espera_triaje_min) as mediana_triaje_min,
        count(*) filter (where triaje is null and sigue_dentro) as pendientes_triaje,
        percentile_cont(0.5) within group (order by espera_medico_min) as mediana_medico_min,
        count(*) filter (where medico is null and sigue_dentro) as pendientes_medico,
        count(*) filter (where abandono) as se_van_sin_ser_vistos,
        percentile_cont(0.5) within group (order by estancia_min) as mediana_estancia_min
    from {{ ref('cohorte') }}
    where k is not null
    group by run_id, k

), estancias as (

    -- Las estancias en los boxes del maestro. Una abierta con sin_pareja no cuenta como
    -- ocupada: su cierre se olvidó, y contaría para siempre.
    select
        u.run_id,
        u.box,
        u.entrada,
        u.salida,
        u.motivo_salida,
        p.origen
    from {{ ref('ubicacion') }} as u
    join {{ ref('maestro_boxes') }} as b using (box)
    join parametros as p using (run_id)
    where u.entrada is not null
        and not (u.salida is null and u.sin_pareja)

), ocupacion as (

    -- Los boxes distintos ocupados a cada hora en punto: entrada <= hora < salida, la misma
    -- regla que el censo. Cada estancia se despliega en sus horas, que son pocas; una abierta,
    -- hasta la última hora de la ventana. Con boxes distintos, dos estancias solapadas en el
    -- mismo box (un cierre anotado tarde) no pasan de los boxes del maestro.
    select
        e.run_id,
        k,
        count(distinct e.box) as boxes_ocupados
    from estancias as e
    join (
        select run_id, max(k) as ultima from horas group by run_id
    ) as fin using (run_id)
    cross join lateral generate_series(
        ceil(extract(epoch from e.entrada - e.origen) / 3600)::bigint,
        coalesce(ceil(extract(epoch from e.salida - e.origen) / 3600)::bigint - 1, fin.ultima)
    ) as k
    group by e.run_id, k

), en_box as (

    select
        run_id,
        floor(extract(epoch from entrada - origen) / 3600)::bigint as k,
        percentile_cont(0.5) within group (
            order by extract(epoch from salida - entrada)::double precision / 60
        ) as mediana_tiempo_box_min
    from estancias
    where salida is not null
    group by 1, 2

), finales as (

    select
        run_id,
        floor(extract(epoch from salida - origen) / 3600)::bigint as k,
        count(*) filter (where motivo_salida = 'desplazado') as desplazamientos,
        count(*) filter (where motivo_salida = 'espera_resultados') as salidas_espera_resultados
    from estancias
    where salida is not null
    group by 1, 2

), medicos as (

    -- El tramo de plantilla vigente a la hora en punto: el turno nuevo cuenta en su hora exacta.
    select
        h.run_id,
        h.k,
        max(t.numero) as medicos
    from horas as h
    join {{ ref('plantilla') }} as t
        on t.run_id = h.run_id
        and t.recurso = 'medicos'
        and t.desde <= h.hora
        and (t.hasta is null or t.hasta > h.hora)
    group by h.run_id, h.k

)

select
    h.run_id,
    h.hora,
    h.k,
    coalesce(l.llegadas, 0) as llegadas,
    h.censo,
    c.mediana_triaje_min,
    coalesce(c.pendientes_triaje, 0) as pendientes_triaje,
    c.mediana_medico_min,
    coalesce(c.pendientes_medico, 0) as pendientes_medico,
    {%- for n in range(1, 6) %}
    coalesce(n.nivel_{{ n }}, 0) as nivel_{{ n }},
    {%- endfor %}
    coalesce(n.sin_nivel, 0) as sin_nivel,
    coalesce(c.se_van_sin_ser_vistos, 0) as se_van_sin_ser_vistos,
    c.mediana_estancia_min,
    coalesce(o.boxes_ocupados, 0) as boxes_ocupados,
    (select count(*) from {{ ref('maestro_boxes') }}) as boxes,
    100 * coalesce(o.boxes_ocupados, 0)::double precision
        / nullif((select count(*) from {{ ref('maestro_boxes') }}), 0) as ocupacion_pct,
    b.mediana_tiempo_box_min,
    coalesce(f.desplazamientos, 0) as desplazamientos,
    coalesce(f.salidas_espera_resultados, 0) as salidas_espera_resultados,
    m.medicos,
    h.censo::double precision / nullif(m.medicos, 0) as pacientes_por_medico
from horas as h
left join llegadas as l using (run_id, k)
left join niveles as n using (run_id, k)
left join cohorte as c using (run_id, k)
left join ocupacion as o using (run_id, k)
left join en_box as b using (run_id, k)
left join finales as f using (run_id, k)
left join medicos as m using (run_id, k)
