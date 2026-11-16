{#
    El primer registro de un tipo en cada grupo, por orden de anotación: el de menor
    recorded_time y, si empatan, el de menor event_id (docs/specs/hito-8.md, «Especificación:
    plata»; como compare.py). En la hoja del hospital ya no hay duplicados, así que el primero
    suele ser el único: la regla es una protección, no una limpieza.

    «tipo» es un tipo o una lista de tipos, que compiten juntos: la primera salida es el primer
    patient_departed o patient_left_wbs, como en compare.py. «donde» añade una condición, como
    el tipo de la valoración.

    Lee del CTE «vigentes» del modelo que la llama, que es preparacion.registros_vigentes (o
    una parte suya). El grupo, por defecto, es el episodio; paciente lo pide por paciente.
#}
{% macro primero(tipo, por=['run_id', 'episode_id'], donde=none) -%}
    {%- set tipos = [tipo] if tipo is string else tipo -%}
    select *
    from (
        select
            *,
            row_number() over (
                partition by {{ por | join(', ') }}
                order by recorded_time, event_id
            ) as orden
        from vigentes
        where event_type in ({{ lista_sql(tipos) }})
            {%- if donde %}
            and ({{ donde }})
            {%- endif %}
    ) as del_tipo
    where orden = 1
{%- endmacro %}
