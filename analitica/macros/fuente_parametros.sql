{#
    Los parámetros de cada ejecución según la hoja (notas del chat de la 8.5, punto 4): el
    origen (el minuto 0), el calentamiento W y el horizonte, en minutos.

    - hospital e ingenuo: del mensaje inicio de bronce.ejecuciones (fecha_inicio,
      inicio_directo y horizonte; edsim.live.messages). Una ejecución publicada dos veces tiene
      dos inicio: vale el último que llegó (macro ultimo_inicio). Si al último le falta
      fecha_inicio, la ejecución no da fila: no se recurre a uno anterior.
    - verdad: de verdad.dias. El día 0 es la fecha del minuto 0, y calentamiento y dias van en
      días. El hospital no lee la verdad: por eso cada hoja tiene su fuente.

    registrado (D2 de la 8.6): si el inicio trae el bloque registro, el mismo criterio que
    tres_columnas; el bloque solo aparece en lo registrado (edsim.live.messages). En la hoja
    verdad, falso: es la verdad, no lo registrado.

    El origen es fecha_inicio a las 00:00 en +01:00, como event_time en el motor. Se escribe
    como texto ISO 8601 con su desfase: AT TIME ZONE '+01:00' lo leería con el signo POSIX
    (una hora al oeste).

    fin_mensaje_min (D1 de la 8.7): dónde acaba la ejecución según su mensaje fin, en minutos.
    Solo vale un fin que llegó después del último inicio, es decir, si el último mensaje de
    ed.runs de la ejecución, en el orden de ultimo_inicio, es un fin (macro ultimo_fin): su
    sim_time (el horizonte, o donde paró si se interrumpió). Si no, es nulo: el directo sigue en
    marcha, y parametros usa la última anotación. En la verdad, que se carga entera, es el
    horizonte.
#}
{% macro fuente_parametros() -%}
    {%- set hoja = var('hoja') -%}
    {%- if hoja in ('hospital', 'ingenuo') -%}
    select
        run_id,
        (mensaje ->> 'fecha_inicio')::date as fecha_origen,
        ((mensaje ->> 'fecha_inicio') || 'T00:00:00+01:00')::timestamptz as origen,
        (mensaje ->> 'inicio_directo')::double precision as calentamiento_min,
        (mensaje ->> 'horizonte')::double precision as horizonte_min,
        fin.fin_mensaje_min,
        mensaje -> 'registro' is not null as registrado
    from ({{ ultimo_inicio() }}) as ultimo
    left join ({{ ultimo_fin() }}) as fin using (run_id)
    where mensaje ->> 'fecha_inicio' is not null
    {%- elif hoja == 'verdad' -%}
    select
        run_id,
        fecha as fecha_origen,
        (fecha::text || 'T00:00:00+01:00')::timestamptz as origen,
        (1440 * calentamiento)::double precision as calentamiento_min,
        (1440 * dias)::double precision as horizonte_min,
        (1440 * dias)::double precision as fin_mensaje_min,
        false as registrado
    from {{ source('verdad', 'dias') }}
    where dia = 0
    {%- else -%}
        {{ exceptions.raise_compiler_error("hoja desconocida: '" ~ hoja ~ "'; las válidas son hospital, verdad e ingenuo") }}
    {%- endif -%}
{%- endmacro %}
