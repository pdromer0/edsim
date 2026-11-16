{#
    preparacion.registros: una fila por registro, con los tipos puestos y sin las columnas de
    Kafka (docs/specs/hito-8.md, «preparacion.registros»). Ver el bloque de documentación
    «registros» en preparacion.md.

    Una sola regla: una fila por (run_id, event_id), la de menor ingest_time. Una relectura de
    Kafka o una reemisión repetida dejan en bronce el mismo registro dos veces.
#}
{{ config(materialized='view') }}

{% if var('hoja') == 'verdad' %}

{# La verdad no pasa por Kafka: ni ingest_time ni relecturas que quitar. #}
select
    event_id,
    event_type,
    run_id,
    episode_id,
    patient_id,
    source_system,
    event_time,
    recorded_time,
    payload
from {{ fuente_registros() }}

{% else %}

with numerados as (
    select
        event_id,
        event_type,
        run_id,
        episode_id,
        patient_id,
        source_system,
        event_time,
        recorded_time,
        payload,
        ingest_time,
        row_number() over (
            partition by run_id, event_id
            order by ingest_time
        ) as llegada
    from {{ fuente_registros() }}
)

select
    event_id,
    event_type,
    run_id,
    episode_id,
    patient_id,
    source_system,
    event_time,
    recorded_time,
    payload,
    ingest_time
from numerados
where llegada = 1

{% endif %}
