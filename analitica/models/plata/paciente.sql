{#
    plata.paciente: uno por paciente, (run_id, patient_id). Ver «paciente» en plata.md.

    Sale de todos los patient_id de los eventos de pacientes (D1 de la 8.3), no solo de
    patient_registered: un olvido de admisión no deja huérfano a su episodio. La edad y el sexo
    salen del primer patient_registered, o quedan vacíos si se olvidó.
#}
with vigentes as (

    select * from {{ ref('registros_vigentes') }}

), pacientes as (

    select
        run_id,
        patient_id,
        min(event_time) as event_time,
        max(recorded_time) as recorded_time
    from vigentes
    where patient_id is not null
    group by run_id, patient_id

), registro as (

    {{ primero('patient_registered', por=['run_id', 'patient_id']) }}

)

select
    p.run_id,
    p.patient_id,
    (r.payload ->> 'edad')::int as edad,
    r.payload ->> 'sexo' as sexo,
    p.event_time,
    p.recorded_time
from pacientes as p
left join registro as r
    on r.run_id = p.run_id
    and r.patient_id = p.patient_id
