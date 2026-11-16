{#
    laboratorio.tres_columnas: cada KPI del hito 7 en la verdad, en lo registrado sin limpiar
    (ingenuo) y en lo limpiado (limpio), con las dos diferencias; una fila por (run_id de la
    verdad, perfil, semilla, kpi). Ver el bloque de documentación «tres_columnas» en
    laboratorio.md.

    Lee kpi_ejecucion de las tres hojas como fuentes. El run_id derivado de lo registrado se
    enlaza con el de la verdad por registro.origen del último mensaje inicio de
    bronce.ejecuciones, que trae también el perfil y la semilla. Una hoja que falte deja su
    columna vacía, pero no quita la fila.
#}
{%- if execute and var('hoja') != 'hospital' %}
    {{ exceptions.raise_compiler_error("laboratorio.tres_columnas se construye con la hoja hospital (dbt build --select tag:laboratorio), no con '" ~ var('hoja') ~ "': iría a otro esquema") }}
{%- endif %}

with inicios as (

    select
        run_id,
        mensaje,
        row_number() over (
            partition by run_id
            order by ingest_time desc, kafka_offset desc
        ) as orden
    from {{ source('bronce', 'ejecuciones') }}
    where tipo = 'inicio'
        and mensaje -> 'registro' is not null

), registrados as (

    select
        mensaje -> 'registro' ->> 'origen' as run_id,
        run_id as run_id_registrado,
        mensaje -> 'registro' ->> 'perfil' as perfil,
        (mensaje -> 'registro' ->> 'semilla')::bigint as semilla
    from inicios
    where orden = 1

), verdad as (

    {{ kpis_en_filas(source('verdad_oro', 'kpi_ejecucion')) }}

), ingenuo as (

    {{ kpis_en_filas(source('ingenuo_oro', 'kpi_ejecucion')) }}

), limpio as (

    {{ kpis_en_filas(source('oro', 'kpi_ejecucion')) }}

), filas as (

    -- Cada ejecución registrada, con los nueve KPI, aunque falte alguna hoja.
    select r.*, k.orden, k.kpi
    from registrados as r
    cross join (
        values
        {%- for kpi in kpis_ejecucion() %}
            ({{ loop.index }}, '{{ kpi }}'){{ "," if not loop.last }}
        {%- endfor %}
    ) as k (orden, kpi)

)

select
    f.run_id,
    f.run_id_registrado,
    f.perfil,
    f.semilla,
    f.orden,
    f.kpi,
    v.valor as verdad,
    i.valor as ingenuo,
    l.valor as limpio,
    i.valor - v.valor as ingenuo_menos_verdad,
    l.valor - v.valor as limpio_menos_verdad
from filas as f
left join verdad as v
    on v.run_id = f.run_id
    and v.kpi = f.kpi
left join ingenuo as i
    on i.run_id = f.run_id_registrado
    and i.kpi = f.kpi
left join limpio as l
    on l.run_id = f.run_id_registrado
    and l.kpi = f.kpi
