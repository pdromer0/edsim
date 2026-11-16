{#
    oro.calidad: los avisos de calidad del dato, una fila por ejecución, (run_id). Ver el bloque
    de documentación «calidad» en oro.md.

    Una fila por cada ejecución con registros, tenga o no parámetros: una ejecución sin inicio
    utilizable (el consumidor empezó tarde, o la retención del topic se llevó el inicio) no sale
    en el resto de oro, y aquí queda a la vista con sin_parametros.

    Sale de las señales de plata, de la cohorte (los sin salida, repartidos entre los que siguen
    dentro y las salidas olvidadas) y de la preparación: los campos vacíos, las correcciones
    aplicadas, las que no encontraron su registro y los duplicados quitados. Todo con la
    ejecución entera, no solo la ventana.
#}
with ejecuciones as (

    select distinct run_id from {{ ref('registros_vigentes') }}
    union
    select run_id from {{ ref('parametros') }}

), parametros as (

    select * from {{ ref('parametros') }}

), episodios as (

    select
        e.run_id,
        count(*) as episodios,
        count(*) filter (where e.sin_llegada) as sin_llegada,
        count(*) filter (where e.sin_salida) as sin_salida,
        count(*) filter (where c.salida_olvidada) as salidas_olvidadas,
        count(*) filter (where c.sigue_dentro) as siguen_dentro
    from {{ ref('episodio') }} as e
    left join {{ ref('cohorte') }} as c using (run_id, episode_id)
    group by e.run_id

), valoraciones as (

    select run_id, count(*) filter (where sin_pareja) as valoraciones_sin_pareja
    from {{ ref('valoracion') }}
    group by run_id

), ubicaciones as (

    select run_id, count(*) filter (where sin_pareja) as ubicaciones_sin_pareja
    from {{ ref('ubicacion') }}
    group by run_id

), triajes as (

    select run_id, count(*) filter (where tiempo_negativo) as triajes_tiempo_negativo
    from {{ ref('triaje') }}
    group by run_id

), vigentes as (

    select
        run_id,
        count(*) filter (where corregido) as registros_corregidos,
        sum(duplicados_quitados) as duplicados_quitados
    from {{ ref('registros_vigentes') }}
    group by run_id

), vacios_por_campo as (

    -- Un campo vacío llega como null en el payload (despiste 5 del hito 7).
    select v.run_id, campo.key as campo, count(*) as vacios
    from {{ ref('registros_vigentes') }} as v
    cross join lateral jsonb_each(v.payload) as campo
    where campo.value = 'null'::jsonb
    group by v.run_id, campo.key

), vacios as (

    select
        run_id,
        sum(vacios) as campos_vacios,
        jsonb_object_agg(campo, vacios order by campo) as campos_vacios_por_campo
    from vacios_por_campo
    group by run_id

), sin_registro as (

    -- Las correcciones cuyo registro no está en registros_vigentes (D3 de la 8.1): una
    -- corrección a un registro olvidado o a una copia que la limpieza quitó no se aplica, y aquí
    -- queda a la vista.
    select r.run_id, count(*) as correcciones_sin_registro
    from {{ ref('registros') }} as r
    where r.event_type = 'record_corrected'
        and not exists (
            select 1
            from {{ ref('registros_vigentes') }} as v
            where v.run_id = r.run_id
                and v.event_id = r.payload ->> 'corrige'
        )
    group by r.run_id

)

select
    x.run_id,
    p.run_id is null as sin_parametros,
    coalesce(e.episodios, 0) as episodios,
    coalesce(e.sin_llegada, 0) as sin_llegada,
    coalesce(e.sin_salida, 0) as sin_salida,
    coalesce(e.salidas_olvidadas, 0) as salidas_olvidadas,
    coalesce(e.siguen_dentro, 0) as siguen_dentro,
    coalesce(va.valoraciones_sin_pareja, 0) as valoraciones_sin_pareja,
    coalesce(u.ubicaciones_sin_pareja, 0) as ubicaciones_sin_pareja,
    coalesce(t.triajes_tiempo_negativo, 0) as triajes_tiempo_negativo,
    coalesce(vc.campos_vacios, 0) as campos_vacios,
    coalesce(vc.campos_vacios_por_campo, '{}'::jsonb) as campos_vacios_por_campo,
    coalesce(vi.registros_corregidos, 0) as registros_corregidos,
    coalesce(s.correcciones_sin_registro, 0) as correcciones_sin_registro,
    coalesce(vi.duplicados_quitados, 0) as duplicados_quitados
from ejecuciones as x
left join parametros as p using (run_id)
left join episodios as e using (run_id)
left join valoraciones as va using (run_id)
left join ubicaciones as u using (run_id)
left join triajes as t using (run_id)
left join vigentes as vi using (run_id)
left join vacios as vc using (run_id)
left join sin_registro as s using (run_id)
