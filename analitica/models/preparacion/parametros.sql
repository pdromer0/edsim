{#
    preparacion.parametros: una fila por ejecución, con su origen (el minuto 0), su ventana y
    su horizonte. Ver el bloque de documentación «parametros» en preparacion.md.

    La ventana empieza en W (inicio_ventana = origen + W): oro cuenta en ella los cinco
    indicadores del hito 7 (D1 de la 8.5).
#}
{{ config(materialized='table') }}

with fuente as (

    {{ fuente_parametros() }}

)

select
    run_id,
    fecha_origen,
    origen,
    calentamiento_min,
    horizonte_min,
    origen + calentamiento_min * interval '1 minute' as inicio_ventana,
    origen + horizonte_min * interval '1 minute' as fin_horizonte,
    registrado
from fuente
