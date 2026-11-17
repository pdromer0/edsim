{#
    Los parámetros de cada ejecución según la hoja (notas del chat de la 8.5, punto 4): el
    origen (el minuto 0), el calentamiento W y el horizonte, en minutos.

    - hospital e ingenuo: del mensaje inicio de bronce.ejecuciones (fecha_inicio,
      inicio_directo y horizonte; edsim.live.messages). Una ejecución publicada dos veces tiene
      dos inicio: vale el último que llegó (macro ultimo_inicio). Si al último le falta
      fecha_inicio, la ejecución no da fila: no se recurre a uno anterior.
    - verdad: de verdad.dias. El día 0 es la fecha del minuto 0, y calentamiento y dias van en
      días. El hospital no lee la verdad: por eso cada hoja tiene su fuente.

    El origen es fecha_inicio a las 00:00 en +01:00, como event_time en el motor. Se escribe
    como texto ISO 8601 con su desfase: AT TIME ZONE '+01:00' lo leería con el signo POSIX
    (una hora al oeste).
#}
{% macro fuente_parametros() -%}
    {%- set hoja = var('hoja') -%}
    {%- if hoja in ('hospital', 'ingenuo') -%}
    select
        run_id,
        (mensaje ->> 'fecha_inicio')::date as fecha_origen,
        ((mensaje ->> 'fecha_inicio') || 'T00:00:00+01:00')::timestamptz as origen,
        (mensaje ->> 'inicio_directo')::double precision as calentamiento_min,
        (mensaje ->> 'horizonte')::double precision as horizonte_min
    from ({{ ultimo_inicio() }}) as ultimo
    where mensaje ->> 'fecha_inicio' is not null
    {%- elif hoja == 'verdad' -%}
    select
        run_id,
        fecha as fecha_origen,
        (fecha::text || 'T00:00:00+01:00')::timestamptz as origen,
        (1440 * calentamiento)::double precision as calentamiento_min,
        (1440 * dias)::double precision as horizonte_min
    from {{ source('verdad', 'dias') }}
    where dia = 0
    {%- else -%}
        {{ exceptions.raise_compiler_error("hoja desconocida: '" ~ hoja ~ "'; las válidas son hospital, verdad e ingenuo") }}
    {%- endif -%}
{%- endmacro %}
