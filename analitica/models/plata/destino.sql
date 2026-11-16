{#
    plata.destino: uno por episodio, (run_id, episode_id). Ver «destino» en plata.md.

    La decisión, la petición y la asignación de cama y la salida, el primero de cada tipo. Quien
    se va sin ser visto no tiene fila.
#}
with vigentes as (

    select * from {{ ref('registros_vigentes') }}

), decision as (

    {{ primero('disposition_decided') }}

), peticion as (

    {{ primero('bed_requested') }}

), asignacion as (

    {{ primero('bed_assigned') }}

), salida as (

    {{ primero('patient_departed') }}

)

select
    run_id,
    episode_id,
    d.payload ->> 'destino' as destino_decidido,
    d.event_time as decision,
    p.event_time as peticion_cama,
    a.event_time as asignacion_cama,
    coalesce(a.payload ->> 'servicio', p.payload ->> 'servicio') as servicio,
    s.payload ->> 'destino' as destino_real,
    least(d.event_time, p.event_time, a.event_time, s.event_time) as event_time,
    greatest(d.recorded_time, p.recorded_time, a.recorded_time, s.recorded_time) as recorded_time
from decision as d
full join peticion as p using (run_id, episode_id)
full join asignacion as a using (run_id, episode_id)
full join salida as s using (run_id, episode_id)
