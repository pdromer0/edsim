{#
    El último mensaje de cada ejecución en bronce.ejecuciones entre los de tipo en «tipos»
    (run_id, tipo, mensaje): el que llegó el último a Kafka, por ingest_time (el LogAppendTime
    del broker) y, si empatan, por kafka_offset (ed.runs tiene una sola partición). Las dos
    macros de abajo lo usan con el mismo orden, para que no se separen.
#}
{% macro ultimo_mensaje(tipos) -%}
    select run_id, tipo, mensaje
    from (
        select
            run_id,
            tipo,
            mensaje,
            row_number() over (
                partition by run_id
                order by ingest_time desc, kafka_offset desc
            ) as orden
        from {{ source('bronce', 'ejecuciones') }}
        where tipo in ('{{ tipos | join("', '") }}')
    ) as mensajes
    where orden = 1
{%- endmacro %}

{#
    El último mensaje inicio de cada ejecución (run_id, mensaje). Una ejecución publicada dos
    veces tiene dos inicio, y vale el último, aunque le falte algo: quien lo usa decide qué hace
    entonces (parametros no da fila sin fecha_inicio; tres_columnas, sin el bloque registro). Lo
    usan parametros y tres_columnas, para que las dos elijan el mismo.
#}
{% macro ultimo_inicio() -%}
    select run_id, mensaje from ({{ ultimo_mensaje(['inicio']) }}) as inicios
{%- endmacro %}

{#
    El sim_time del fin de cada ejecución que lo tiene después de su último inicio (run_id,
    fin_mensaje_min): el de las ejecuciones cuyo último mensaje, entre inicio y fin, es un fin
    (D1 de la 8.7). Un fin anterior al último inicio es de otra publicación.
#}
{% macro ultimo_fin() -%}
    select run_id, (mensaje ->> 'sim_time')::double precision as fin_mensaje_min
    from ({{ ultimo_mensaje(['inicio', 'fin']) }}) as ultimos
    where tipo = 'fin'
{%- endmacro %}
