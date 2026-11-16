{#
    plata.triaje: uno por episodio, (run_id, episode_id). Ver «triaje» en plata.md.

    El primer triage_started y el primer triage_completed del episodio. tiempo_negativo: el fin
    antes de la llegada, que solo puede dar un reloj desajustado (con los perfiles de EDsim no
    salta: es una señal defensiva, para un HIS real).
#}
with vigentes as (

    select * from {{ ref('registros_vigentes') }}

), inicio as (

    {{ primero('triage_started') }}

), fin as (

    {{ primero('triage_completed') }}

), llegada as (

    {{ primero('patient_arrived') }}

)

select
    run_id,
    episode_id,
    i.event_time as inicio,
    f.event_time as fin,
    i.payload ->> 'circuito' as circuito,
    (f.payload ->> 'nivel')::int as nivel,
    f.payload ->> 'motivo' as motivo,
    coalesce(i.corregido, false) or coalesce(f.corregido, false) as corregido,
    coalesce(f.event_time < l.event_time, false) as tiempo_negativo,
    least(i.event_time, f.event_time) as event_time,
    greatest(i.recorded_time, f.recorded_time) as recorded_time
from inicio as i
full join fin as f using (run_id, episode_id)
left join llegada as l using (run_id, episode_id)
