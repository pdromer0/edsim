{#
    oro.cohorte: una fila por episodio, (run_id, episode_id), con su hora y su turno de llegada.
    Ver el bloque de documentación «cohorte» en oro.md.

    La cohorte de llegada (decisión 106, H8-7): cada espera se apunta a la hora en que llegó el
    paciente. Quien llega a las 16:58 y se tria a las 17:04 cuenta en la hora de las 16.
    kpi_hora y kpi_turno agrupan por la hora y el turno de aquí.

    «El primero» de cada tipo, por orden de anotación, como en kpi_ejecucion, pero con todos
    los registros: la cohorte es de todos los episodios, también los del calentamiento y los
    que no tienen llegada (sin hora), porque calidad la usa para repartir los sin salida.

    Un episodio sin salida sigue dentro si su última anotación (recorded_time) es de las
    últimas margen_sin_salida_min de la ejecución; si no, su salida se olvidó. El ahora de la
    ejecución es su última anotación, sin pasar del horizonte.
#}
with vigentes as (

    select * from {{ ref('registros_vigentes') }}
    where episode_id is not null

), parametros as (

    select * from {{ ref('parametros') }}

), episodios as (

    select
        run_id,
        episode_id,
        max(recorded_time) as ultima_anotacion
    from vigentes
    group by run_id, episode_id

), ahora as (

    select
        p.run_id,
        least(p.fin_horizonte, max(v.recorded_time)) as ahora
    from parametros as p
    join vigentes as v using (run_id)
    group by p.run_id, p.fin_horizonte

), llegada as (

    {{ primero('patient_arrived') }}

), triaje as (

    {{ primero('triage_completed') }}

), medico as (

    {{ primero('assessment_started', donde="payload ->> 'tipo' = 'inicial'") }}

), salida as (

    {{ primero(['patient_departed', 'patient_left_wbs']) }}

), base as (

    select
        e.run_id,
        e.episode_id,
        p.origen,
        p.fecha_origen,
        l.event_time as llegada,
        t.event_time as triaje,
        m.event_time as medico,
        s.event_time as salida,
        s.event_type = 'patient_left_wbs' as abandono,
        e.ultima_anotacion,
        a.ahora,
        floor(extract(epoch from l.event_time - p.origen) / 3600)::bigint as k
    from episodios as e
    join parametros as p using (run_id)
    join ahora as a using (run_id)
    left join llegada as l using (run_id, episode_id)
    left join triaje as t using (run_id, episode_id)
    left join medico as m using (run_id, episode_id)
    left join salida as s using (run_id, episode_id)

)

select
    b.run_id,
    b.episode_id,
    b.k,
    b.origen + b.k * interval '1 hour' as hora_llegada,
    del_turno.fecha_turno,
    del_turno.turno,
    b.llegada,
    b.triaje,
    b.medico,
    b.salida,
    coalesce(b.abandono, false) as abandono,
    extract(epoch from b.triaje - b.llegada)::double precision / 60 as espera_triaje_min,
    extract(epoch from b.medico - b.llegada)::double precision / 60 as espera_medico_min,
    extract(epoch from b.salida - b.llegada)::double precision / 60 as estancia_min,
    b.ultima_anotacion,
    b.salida is null
        and b.ultima_anotacion >= b.ahora - {{ var('margen_sin_salida_min') }} * interval '1 minute'
        as sigue_dentro,
    b.salida is null
        and b.ultima_anotacion < b.ahora - {{ var('margen_sin_salida_min') }} * interval '1 minute'
        as salida_olvidada
from base as b
{{ turno_de('b.k', 'b.fecha_origen') }}
