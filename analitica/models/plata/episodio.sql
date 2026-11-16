{#
    plata.episodio: uno por episodio, (run_id, episode_id), con su paciente. Ver «episodio» en
    plata.md.

    Sale de todos los episode_id de los eventos de pacientes (D1 de la 8.3): así ninguna tabla
    hija queda colgando. Se agrupa también por patient_id: si un episodio tuviera dos, saldría
    dos veces y el test de su clave lo cazaría.
#}
with vigentes as (

    select * from {{ ref('registros_vigentes') }}

), episodios as (

    select
        run_id,
        episode_id,
        patient_id,
        min(event_time) as event_time,
        max(recorded_time) as recorded_time
    from vigentes
    where episode_id is not null
    group by run_id, episode_id, patient_id

), llegada as (

    {{ primero('patient_arrived') }}

), registro as (

    {{ primero('patient_registered') }}

), salida as (

    {{ primero('patient_departed') }}

), abandono as (

    {{ primero('patient_left_wbs') }}

)

select
    e.run_id,
    e.episode_id,
    e.patient_id,
    l.event_time as llegada,
    l.payload ->> 'medio' as medio,
    r.event_time as registro,
    s.event_time as salida,
    a.event_time as abandono,
    a.payload ->> 'espera' as espera_abandono,
    l.event_id is null as sin_llegada,
    s.event_id is null and a.event_id is null as sin_salida,
    e.event_time,
    e.recorded_time
from episodios as e
left join llegada as l using (run_id, episode_id)
left join registro as r using (run_id, episode_id)
left join salida as s using (run_id, episode_id)
left join abandono as a using (run_id, episode_id)
