{#
    preparacion.registros: una fila por registro, con los tipos puestos y sin las columnas de
    Kafka (docs/specs/hito-8.md, «preparacion.registros»). Ver el bloque de documentación
    «registros» en preparacion.md.

    Una sola regla: una fila por (run_id, event_id), la de menor ingest_time. Una relectura de
    Kafka o una reemisión repetida dejan en bronce el mismo registro dos veces. La verdad no
    pasa por Kafka: en la hoja verdad no hay ingest_time ni relecturas que quitar.
#}
{{ config(materialized='view') }}

{%- set columnas = columnas_registro() %}

with numerados as (
    select
        {% for c in columnas %}{{ c }},
        {% endfor %}payload
        {%- if var('hoja') != 'verdad' %},
        row_number() over (
            partition by run_id, event_id
            order by ingest_time
        ) as llegada
        {%- endif %}
    from {{ fuente_registros() }}
)

select
    {% for c in columnas %}{{ c }},
    {% endfor %}payload
from numerados
{% if var('hoja') != 'verdad' -%}
where llegada = 1
{%- endif %}
