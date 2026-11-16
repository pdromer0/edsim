{#
    plata.plantilla: un tramo por recurso, (run_id, recurso, desde). Ver «plantilla» en
    plata.md.

    Cada staffing_changed abre un tramo con la plantilla nueva, que dura hasta el cambio
    siguiente del mismo recurso; el último queda abierto. Viene del sistema rrhh, sin despistes.
#}
with vigentes as (

    select * from {{ ref('registros_vigentes') }}

)

select
    run_id,
    payload ->> 'recurso' as recurso,
    (payload ->> 'nueva')::int as numero,
    event_time as desde,
    lead(event_time) over (
        partition by run_id, payload ->> 'recurso'
        order by event_time, recorded_time, event_id
    ) as hasta,
    event_time,
    recorded_time
from vigentes
where event_type = 'staffing_changed'
