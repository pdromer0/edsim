{#
    plata.ubicacion: una por estancia en un box, (run_id, episode_id, n). Ver «emparejamiento»
    en plata.md.

    De box_assigned a su cierre, emparejados por tiempo como las valoraciones (D2 de la 8.3).
    Cuatro motivos de salida (D3): espera_resultados (box_released), desplazado
    (patient_displaced), salida (patient_departed) y abandono (patient_left_wbs desde el box,
    antes de verle el médico).
#}
with vigentes as (

    select * from {{ ref('registros_vigentes') }}

), estancias as (

    {{ emparejar(
        ['box_assigned'],
        ['box_released', 'patient_displaced'],
        salidas=['patient_departed', 'patient_left_wbs'],
    ) }}

)

select
    run_id,
    episode_id,
    n,
    coalesce((ap_payload ->> 'box')::int, (ci_payload ->> 'box')::int) as box,
    ap_event_time as entrada,
    ci_event_time as salida,
    case ci_event_type
        when 'box_released' then 'espera_resultados'
        when 'patient_displaced' then 'desplazado'
        when 'patient_departed' then 'salida'
        when 'patient_left_wbs' then 'abandono'
    end as motivo_salida,
    sin_pareja,
    least(ap_event_time, ci_event_time) as event_time,
    greatest(ap_recorded_time, ci_recorded_time) as recorded_time
from estancias
