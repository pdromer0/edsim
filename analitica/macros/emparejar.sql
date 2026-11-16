{#
    El emparejamiento por tiempo de una apertura y su cierre, dentro de cada episodio (D2 de la
    8.3; ver el bloque de documentación «emparejamiento» en models/plata/plata.md). Lo usan
    valoracion, ubicacion y prueba: las tres emparejan con la misma regla.

    Los eventos de la secuencia se ordenan por event_time, recorded_time y event_id, y cada uno
    mira a su vecino:
      - una apertura seguida de un cierre (o de una salida, si se pasan «salidas») es una
        pareja;
      - una apertura seguida de otra apertura queda sin cierre y con sin_pareja;
      - la última apertura sin cierre lleva sin_pareja si el episodio tiene salida (el cierre
        se olvidó) y no la lleva si sigue en curso;
      - un cierre sin una apertura justo antes da su propia fila, con sin_pareja;
      - una salida sin apertura justo antes no da fila: es la salida del episodio, no de la
        estancia (quien espera cama en el pasillo sale sin box).
    El tipo de la valoración no cuenta: las de un paciente no se solapan.

    Una fila por pareja o evento suelto, con las columnas de la apertura (ap_*) y del cierre
    (ci_*), vacías si falta, sin_pareja y n, el orden de la fila en su episodio por la hora de
    su primer evento. Lee del CTE «vigentes» del modelo que la llama.
#}
{% macro emparejar(aperturas, cierres, salidas=[]) -%}
    {%- set tipos = aperturas + cierres + salidas -%}
    with secuencia as (

        select
            run_id,
            episode_id,
            event_id,
            event_type,
            event_time,
            recorded_time,
            payload,
            case
                when event_type in ({{ lista_sql(aperturas) }}) then 'apertura'
                when event_type in ({{ lista_sql(cierres) }}) then 'cierre'
                else 'salida'
            end as papel
        from vigentes
        where event_type in ({{ lista_sql(tipos) }})

    ), vecinos as (

        select
            *,
            lag(papel) over orden_del_episodio as papel_anterior,
            lead(papel) over orden_del_episodio as papel_siguiente,
            lead(event_type) over orden_del_episodio as siguiente_event_type,
            lead(event_time) over orden_del_episodio as siguiente_event_time,
            lead(recorded_time) over orden_del_episodio as siguiente_recorded_time,
            lead(payload) over orden_del_episodio as siguiente_payload
        from secuencia
        window orden_del_episodio as (
            partition by run_id, episode_id
            order by event_time, recorded_time, event_id
        )

    ), con_salida as (

        select distinct run_id, episode_id
        from vigentes
        where event_type in ('patient_departed', 'patient_left_wbs')

    ), filas as (

        -- Cada apertura, con su cierre si es el evento siguiente.
        select
            v.run_id,
            v.episode_id,
            v.event_time as ap_event_time,
            v.recorded_time as ap_recorded_time,
            v.payload as ap_payload,
            case when v.papel_siguiente in ('cierre', 'salida') then v.siguiente_event_type end
                as ci_event_type,
            case when v.papel_siguiente in ('cierre', 'salida') then v.siguiente_event_time end
                as ci_event_time,
            case when v.papel_siguiente in ('cierre', 'salida') then v.siguiente_recorded_time end
                as ci_recorded_time,
            case when v.papel_siguiente in ('cierre', 'salida') then v.siguiente_payload end
                as ci_payload,
            case
                when v.papel_siguiente = 'apertura' then true
                when v.papel_siguiente is null then s.episode_id is not null
                else false
            end as sin_pareja,
            v.event_time as orden_event_time,
            v.recorded_time as orden_recorded_time,
            v.event_id as orden_event_id
        from vecinos as v
        left join con_salida as s
            on s.run_id = v.run_id
            and s.episode_id = v.episode_id
        where v.papel = 'apertura'

        union all

        -- Cada cierre suelto: no tiene una apertura justo antes.
        select
            run_id,
            episode_id,
            null::timestamptz,
            null::timestamptz,
            null::jsonb,
            event_type,
            event_time,
            recorded_time,
            payload,
            true,
            event_time,
            recorded_time,
            event_id
        from vecinos
        where papel = 'cierre'
            and papel_anterior is distinct from 'apertura'

    )

    select
        *,
        row_number() over (
            partition by run_id, episode_id
            order by orden_event_time, orden_recorded_time, orden_event_id
        ) as n
    from filas
{%- endmacro %}


{#- Una lista de Jinja como lista de literales de SQL: ['a', 'b'] da 'a', 'b'. #}
{% macro lista_sql(valores) -%}
    {%- for v in valores %}'{{ v }}'{% if not loop.last %}, {% endif %}{% endfor -%}
{%- endmacro %}
