{#
    preparacion.registros_vigentes: la limpieza conservadora, en un solo modelo (decisiones 102
    y 103, H8-3 y H8-4). Las ocho tablas de plata leen de aquí. El porqué de cada regla y lo
    que no cubre están en el bloque de documentación «registros_vigentes» de preparacion.md.

    En las hojas hospital y verdad, tres reglas en este orden:
      1. los record_corrected no son hechos: solo sirven al paso 3;
      2. duplicados: por (run_id, episode_id, event_type, event_time, payload), se queda el de
         menor recorded_time y, si empatan, el de menor event_id;
      3. correcciones: la de mayor recorded_time (y, si empatan, la de mayor event_id) se
         aplica sobre el payload del registro al que apunta.
    En la hoja ingenuo, solo la regla 1.
#}
{{ config(materialized='table') }}

{#- Las columnas que pasan sin tocar; la verdad no lleva ingest_time. -#}
{%- set columnas = [
    'event_id', 'event_type', 'run_id', 'episode_id', 'patient_id', 'source_system',
    'event_time', 'recorded_time',
] + ([] if var('hoja') == 'verdad' else ['ingest_time']) -%}

with hechos as (

    -- Regla 1: las correcciones no son hechos.
    select * from {{ ref('registros') }}
    where event_type <> 'record_corrected'

)

{% if var('hoja') == 'ingenuo' %}

{#- Como los indicadores ingenuos del hito 7: ni se quitan duplicados ni se aplican
    correcciones. Las mismas columnas que en el hospital, con valores neutros. #}
select
    {% for c in columnas %}{{ c }},
    {% endfor %}payload,
    false as corregido,
    cast(0 as bigint) as duplicados_quitados
from hechos

{% else %}

, pacientes as (

    -- Regla 2. Solo los eventos de pacientes: en un PARTITION BY, los episode_id nulos de
    -- los eventos de recursos caerían todos en el mismo grupo.
    select
        *,
        row_number() over duplicados as orden,
        count(*) over duplicados - 1 as duplicados_quitados
    from hechos
    where episode_id is not null
    window duplicados as (
        partition by run_id, episode_id, event_type, event_time, payload
        order by recorded_time, event_id
        rows between unbounded preceding and unbounded following
    )

), sin_duplicados as (

    select
        {% for c in columnas %}{{ c }},
        {% endfor %}payload,
        duplicados_quitados
    from pacientes
    where orden = 1

    union all

    -- Los eventos de recursos (staffing_changed) pasan tal cual: no tienen despistes.
    select
        {% for c in columnas %}{{ c }},
        {% endfor %}payload,
        cast(0 as bigint) as duplicados_quitados
    from hechos
    where episode_id is null

), correcciones as (

    -- Regla 3: la última corrección de cada registro, por run_id y el event_id al que apunta.
    select
        run_id,
        payload ->> 'corrige' as corrige,
        payload -> 'campos' as campos,
        row_number() over (
            partition by run_id, payload ->> 'corrige'
            order by recorded_time desc, event_id desc
        ) as orden
    from {{ ref('registros') }}
    where event_type = 'record_corrected'

), ultima_correccion as (

    select run_id, corrige, campos
    from correcciones
    where orden = 1

)

-- Los campos corregibles (nivel, edad, motivo y destino) son de primer nivel en el payload:
-- «payload || campos» los sustituye. Una corrección que apunta a un registro que no está no
-- casa con ninguna fila y no aparece aquí; la cuenta oro.calidad (8.5).
select
    {% for c in columnas %}s.{{ c }},
    {% endfor %}s.payload || coalesce(u.campos, '{}'::jsonb) as payload,
    u.corrige is not null as corregido,
    s.duplicados_quitados
from sin_duplicados as s
left join ultima_correccion as u
    on u.run_id = s.run_id
    and u.corrige = s.event_id

{% endif %}
