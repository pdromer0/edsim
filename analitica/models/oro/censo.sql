{#
    oro.censo: los pacientes dentro a cada hora en punto de la ventana, (run_id, hora). Ver el
    bloque de documentación «censo» en oro.md.

    Con las definiciones de compare.py (_naive_indicators): cada episodio está dentro desde su
    primera llegada hasta su primera salida (patient_departed o patient_left_wbs), por orden de
    anotación y con todos los registros, no solo los de la ventana. Quien llega justo a la hora
    en punto ya está; quien sale justo, ya no. Una salida anterior a la llegada (por los relojes)
    cuenta como salida en la llegada. Las horas son las k con W <= 60 k < horizonte.

    Se cuenta como un torniquete: cada llegada suma 1 en la primera hora en punto que la ve, y
    cada salida resta 1 en la primera hora en punto en la que ya no está; el censo es la suma
    acumulada. Cruzar cada hora con cada estancia daría lo mismo, pero con un año serían miles
    de millones de comparaciones.
#}
with vigentes as (

    select * from {{ ref('registros_vigentes') }}

), parametros as (

    select * from {{ ref('parametros') }}

), llegada as (

    {{ primero('patient_arrived') }}

), salida as (

    {{ primero(['patient_departed', 'patient_left_wbs']) }}

), estancias as (

    select
        l.run_id,
        l.event_time as llegada,
        -- greatest ignora los nulos: sin la condición, quien no tiene salida saldría al llegar.
        case
            when s.event_time is not null then greatest(s.event_time, l.event_time)
        end as fin
    from llegada as l
    left join salida as s using (run_id, episode_id)
    where l.episode_id is not null

), horas as (

    select
        run_id,
        k,
        origen + k * interval '1 hour' as hora
    from parametros
    cross join lateral generate_series(
        ceil(calentamiento_min / 60)::bigint,
        ceil(horizonte_min / 60)::bigint - 1
    ) as k

), movimientos as (

    -- La primera hora en punto k con origen + k h >= t: ceil de las horas desde el origen. Una
    -- llegada en t cuenta a partir de ella (llegada <= hora); una salida en t deja de contar a
    -- partir de ella (fin <= hora). extract(epoch ...) es numeric: la división es exacta.
    select
        e.run_id,
        ceil(extract(epoch from e.llegada - p.origen) / 3600)::bigint as k,
        1 as cambio
    from estancias as e
    join parametros as p using (run_id)

    union all

    select
        e.run_id,
        ceil(extract(epoch from e.fin - p.origen) / 3600)::bigint,
        -1
    from estancias as e
    join parametros as p using (run_id)
    where e.fin is not null

    union all

    select run_id, k, 0 from horas

), acumulado as (

    select
        run_id,
        k,
        sum(sum(cambio)) over (partition by run_id order by k) as censo
    from movimientos
    group by run_id, k

)

select
    h.run_id,
    h.hora,
    h.k,
    a.censo::bigint as censo
from horas as h
join acumulado as a using (run_id, k)
