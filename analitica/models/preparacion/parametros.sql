{#
    preparacion.parametros: una fila por ejecución, con su origen (el minuto 0), su ventana, su
    horizonte y el fin del dato. Ver el bloque de documentación «parametros» en preparacion.md.

    La ventana empieza en W (inicio_ventana = origen + W): oro cuenta en ella los cinco
    indicadores del hito 7 (D1 de la 8.5).

    El fin del dato (D1 de la 8.7) es hasta dónde llegan los datos de la ejecución: el sim_time
    de su fin si llegó después del último inicio (fuente_parametros); si no, un directo en
    marcha, su última anotación (recorded_time); nunca más allá del horizonte. Sin fin ni
    registros, es nulo: la ejecución no tiene horas en oro.censo.
#}
{{ config(materialized='table') }}

with fuente as (

    {{ fuente_parametros() }}

), ultima_anotacion as (

    select run_id, max(recorded_time) as ultima_anotacion
    from {{ ref('registros_vigentes') }}
    group by run_id

), con_fin as (

    select
        f.*,
        coalesce(
            f.fin_mensaje_min,
            (extract(epoch from a.ultima_anotacion - f.origen) / 60)::double precision
        ) as fin_sin_tope_min
    from fuente as f
    left join ultima_anotacion as a using (run_id)

), parametros as (

    select
        *,
        -- least ignora los nulos: sin la condición, una ejecución sin datos llegaría al horizonte.
        case
            when fin_sin_tope_min is not null then least(horizonte_min, fin_sin_tope_min)
        end as fin_dato_min
    from con_fin

)

select
    run_id,
    fecha_origen,
    origen,
    calentamiento_min,
    horizonte_min,
    origen + calentamiento_min * interval '1 minute' as inicio_ventana,
    origen + horizonte_min * interval '1 minute' as fin_horizonte,
    fin_dato_min,
    origen + fin_dato_min * interval '1 minute' as fin_dato,
    registrado
from parametros
