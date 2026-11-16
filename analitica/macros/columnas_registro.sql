{#
    Las columnas de un registro que pasan sin tocar por la preparación, sin el payload, que
    cada modelo trata a su manera. Una sola lista para registros y registros_vigentes: si
    entra una columna, entra en los dos y en las tres hojas. La verdad no pasa por Kafka y no
    lleva ingest_time.
#}
{% macro columnas_registro() -%}
    {%- set columnas = [
        'event_id', 'event_type', 'run_id', 'episode_id', 'patient_id', 'source_system',
        'event_time', 'recorded_time',
    ] -%}
    {%- if var('hoja') != 'verdad' -%}
        {%- do columnas.append('ingest_time') -%}
    {%- endif -%}
    {{ return(columnas) }}
{%- endmacro %}
