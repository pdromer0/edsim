{#
    oro.kpi_ejecucion: los cinco indicadores del hito 7 de cada ejecución, en su ventana,
    (run_id). Ver el bloque de documentación «kpi_ejecucion» en oro.md.

    Las definiciones son las de compare.py (_naive_indicators, decisión 96), con la ventana de
    D1 de la 8.5: un registro cuenta si su event_time es >= origen + W. Las llegadas, las
    medianas y el reparto por nivel salen de los registros de la ventana; el censo medio, de
    oro.censo, que usa todos. La prueba de punta a punta compara esta tabla, en las hojas verdad
    e ingenuo, con compare.py: los recuentos, exactos; las medianas, en milisegundos enteros.

    Las llegadas cuentan registros de registros_vigentes, no episodios: en la hoja ingenuo, un
    doble clic de la llegada cuenta dos veces, como en Python.
#}
with parametros as (

    select * from {{ ref('parametros') }}

), vigentes as (

    -- Solo los registros de la ventana: «el primero» de cada tipo se toma entre ellos.
    select v.*
    from {{ ref('registros_vigentes') }} as v
    join parametros as p using (run_id)
    where v.event_time >= p.inicio_ventana

), llegada as (

    {{ primero('patient_arrived') }}

), triaje as (

    {{ primero('triage_completed') }}

), medico as (

    {{ primero('assessment_started', donde="payload ->> 'tipo' = 'inicial'") }}

), esperas as (

    -- Milisegundos enteros: event_time lleva milisegundos y extract(epoch ...) es numeric.
    select
        l.run_id,
        (extract(epoch from t.event_time - l.event_time) * 1000)::bigint as triaje_ms,
        (extract(epoch from m.event_time - l.event_time) * 1000)::bigint as medico_ms
    from llegada as l
    left join triaje as t using (run_id, episode_id)
    left join medico as m using (run_id, episode_id)
    where l.episode_id is not null

), medianas as (

    -- percentile_cont(0.5) da la media de los dos centrales, como statistics.median: con
    -- milisegundos enteros, el resultado es exacto en double precision.
    select
        run_id,
        percentile_cont(0.5) within group (order by triaje_ms::double precision)
            / 60000 as mediana_triaje_min,
        percentile_cont(0.5) within group (order by medico_ms::double precision)
            / 60000 as mediana_medico_min
    from esperas
    group by run_id

), llegadas as (

    select run_id, count(*) as llegadas
    from vigentes
    where event_type = 'patient_arrived'
    group by run_id

), triajes as (

    -- Nivel legible: un número entero del 1 al 5, como el isinstance(int) de Python. Un 3.0 o
    -- un "3" no cuentan; un nivel vacío (null) tampoco.
    select
        run_id,
        payload ->> 'nivel' as nivel,
        jsonb_typeof(payload -> 'nivel') = 'number'
            and payload ->> 'nivel' in ('1', '2', '3', '4', '5') as legible
    from vigentes
    where event_type = 'triage_completed'

), niveles as (

    select
        run_id,
        count(*) filter (where legible) as total,
        {%- for n in range(1, 6) %}
        count(*) filter (where legible and nivel = '{{ n }}') as n{{ n }}{{ "," if not loop.last }}
        {%- endfor %}
    from triajes
    group by run_id

), censo as (

    -- La media de enteros, como sum / len en Python: los dos son la división IEEE de dos
    -- enteros exactos.
    select
        run_id,
        count(*) as horas,
        sum(censo)::double precision / count(*)::double precision as censo_medio
    from {{ ref('censo') }}
    group by run_id

)

select
    p.run_id,
    coalesce(l.llegadas, 0) as llegadas,
    c.censo_medio,
    m.mediana_triaje_min,
    m.mediana_medico_min,
    {%- for n in range(1, 6) %}
    (100 * n.n{{ n }})::double precision / nullif(n.total, 0)::double precision
        as pct_nivel_{{ n }},
    {%- endfor %}
    c.horas
from parametros as p
left join llegadas as l using (run_id)
left join censo as c using (run_id)
left join medianas as m using (run_id)
left join niveles as n using (run_id)
