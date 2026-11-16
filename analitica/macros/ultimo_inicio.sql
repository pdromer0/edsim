{#
    El último mensaje inicio de cada ejecución en bronce.ejecuciones (run_id, mensaje): el que
    llegó el último a Kafka. Una ejecución publicada dos veces tiene dos inicio, y vale el
    último, aunque le falte algo: quien lo usa decide qué hace entonces (parametros no da fila
    sin fecha_inicio; tres_columnas, sin el bloque registro). Lo usan parametros y
    tres_columnas, para que las dos elijan el mismo.
#}
{% macro ultimo_inicio() -%}
    select run_id, mensaje
    from (
        select
            run_id,
            mensaje,
            row_number() over (
                partition by run_id
                order by ingest_time desc, kafka_offset desc
            ) as orden
        from {{ source('bronce', 'ejecuciones') }}
        where tipo = 'inicio'
    ) as inicios
    where orden = 1
{%- endmacro %}
