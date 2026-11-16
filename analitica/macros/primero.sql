{#
    El primer registro de un tipo en cada grupo, por orden de anotación: el de menor
    recorded_time y, si empatan, el de menor event_id (docs/specs/hito-8.md, «Especificación:
    plata»; como compare.py). En la hoja del hospital ya no hay duplicados, así que el primero
    suele ser el único: la regla es una protección, no una limpieza.

    Lee del CTE «vigentes» del modelo que la llama, que es preparacion.registros_vigentes. El
    grupo, por defecto, es el episodio; paciente lo pide por paciente.
#}
{% macro primero(tipo, por=['run_id', 'episode_id']) -%}
    select *
    from (
        select
            *,
            row_number() over (
                partition by {{ por | join(', ') }}
                order by recorded_time, event_id
            ) as orden
        from vigentes
        where event_type = '{{ tipo }}'
    ) as del_tipo
    where orden = 1
{%- endmacro %}
