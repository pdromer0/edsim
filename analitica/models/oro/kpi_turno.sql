{#
    oro.kpi_turno: el informe por turno, una fila por (run_id, fecha, turno). Ver el bloque de
    documentación «kpi_turno» en oro.md.

    Los turnos empiezan a las horas de la semilla turnos (8, 15 y 22); la noche pertenece a la
    fecha en que empieza. Solo cuentan las horas de la ventana: el turno que corta W (la noche
    del día anterior al primero de la ventana) o el horizonte sale con menos horas y con
    completo falso.

    Lo que es de un instante o de un intervalo sale de kpi_hora (sumas y medias de sus horas);
    las medianas, de las filas de la cohorte y de las estancias del turno, no de las medianas de
    cada hora.
#}
with parametros as (

    select * from {{ ref('parametros') }}

), horas as (

    select h.*, del_turno.*, p.origen, p.fecha_origen
    from {{ ref('kpi_hora') }} as h
    join parametros as p using (run_id)
    {{ turno_de('h.k', 'p.fecha_origen') }}

), duraciones as (

    -- Las horas de cada turno: hasta el siguiente o, el último, hasta el primero del día después.
    select
        turno,
        coalesce(lead(inicio) over (order by inicio), min(inicio) over () + 24) - inicio
            as duracion
    from {{ ref('turnos') }}

), por_horas as (

    select
        run_id,
        fecha_turno,
        turno,
        min(origen + ((fecha_turno - fecha_origen) * 24 + inicio_turno) * interval '1 hour')
            as inicio,
        count(*) as horas,
        sum(llegadas) as llegadas,
        sum(censo)::double precision / count(*)::double precision as censo_medio,
        {%- for n in range(1, 6) %}
        sum(nivel_{{ n }}) as nivel_{{ n }},
        {%- endfor %}
        sum(sin_nivel) as sin_nivel,
        -- Las medias, con aritmética exacta: un avg de double precision depende del orden en
        -- que se suman las filas, y la misma ejecución en dos hojas podría diferir en el último
        -- bit (lo vio «oro limpio = oro verdad»). La ocupación, con enteros; la razón, en numeric.
        100 * sum(boxes_ocupados)::double precision
            / nullif(sum(boxes), 0)::double precision as ocupacion_media_pct,
        sum(desplazamientos) as desplazamientos,
        sum(salidas_espera_resultados) as salidas_espera_resultados,
        avg(censo::numeric / nullif(medicos, 0))::double precision as pacientes_por_medico_medio
    from horas
    group by run_id, fecha_turno, turno

), cohorte as (

    -- Los episodios llegados en las horas de la ventana, por el turno de su llegada.
    select
        c.run_id,
        c.fecha_turno,
        c.turno,
        percentile_cont(0.5) within group (order by c.espera_triaje_min) as mediana_triaje_min,
        count(*) filter (where c.triaje is null and c.sigue_dentro) as pendientes_triaje,
        percentile_cont(0.5) within group (order by c.espera_medico_min) as mediana_medico_min,
        count(*) filter (where c.medico is null and c.sigue_dentro) as pendientes_medico,
        count(*) filter (where c.abandono) as se_van_sin_ser_vistos,
        percentile_cont(0.5) within group (order by c.estancia_min) as mediana_estancia_min
    from {{ ref('cohorte') }} as c
    join horas as h using (run_id, k)
    group by c.run_id, c.fecha_turno, c.turno

), en_box as (

    -- Las estancias en los boxes del maestro, por el turno de su entrada.
    select
        e.run_id,
        del_turno.fecha_turno,
        del_turno.turno,
        percentile_cont(0.5) within group (
            order by extract(epoch from e.salida - e.entrada)::double precision / 60
        ) as mediana_tiempo_box_min
    from (
        select
            run_id,
            entrada,
            salida,
            fecha_origen,
            floor(extract(epoch from entrada - origen) / 3600)::bigint as k
        from ({{ estancias_en_boxes() }}) as estancias
        where salida is not null
    ) as e
    join horas as h using (run_id, k)
    {{ turno_de('e.k', 'e.fecha_origen') }}
    group by e.run_id, del_turno.fecha_turno, del_turno.turno

)

select
    t.run_id,
    t.fecha_turno as fecha,
    t.turno,
    t.inicio,
    t.horas,
    t.horas = d.duracion as completo,
    t.llegadas,
    t.censo_medio,
    c.mediana_triaje_min,
    coalesce(c.pendientes_triaje, 0) as pendientes_triaje,
    c.mediana_medico_min,
    coalesce(c.pendientes_medico, 0) as pendientes_medico,
    {%- for n in range(1, 6) %}
    t.nivel_{{ n }},
    {%- endfor %}
    t.sin_nivel,
    coalesce(c.se_van_sin_ser_vistos, 0) as se_van_sin_ser_vistos,
    c.mediana_estancia_min,
    t.ocupacion_media_pct,
    b.mediana_tiempo_box_min,
    t.desplazamientos,
    t.salidas_espera_resultados,
    t.pacientes_por_medico_medio
from por_horas as t
join duraciones as d using (turno)
left join cohorte as c using (run_id, fecha_turno, turno)
left join en_box as b using (run_id, fecha_turno, turno)
