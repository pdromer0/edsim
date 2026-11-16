{#
    plata.valoracion: una por valoración, (run_id, episode_id, n). Ver «emparejamiento» en
    plata.md.

    assessment_started con assessment_ended, emparejados por tiempo dentro del episodio y sin
    mirar el tipo (D2 de la 8.3, macro emparejar). El tipo sale del inicio o, si está vacío,
    del fin.
#}
with vigentes as (

    select * from {{ ref('registros_vigentes') }}

), pares as (

    {{ emparejar(['assessment_started'], ['assessment_ended']) }}

)

select
    run_id,
    episode_id,
    n,
    coalesce(ap_payload ->> 'tipo', ci_payload ->> 'tipo') as tipo,
    ap_payload ->> 'pool' as pool,
    (ap_payload ->> 'box')::int as box,
    ap_event_time as inicio,
    ci_event_time as fin,
    (ci_payload ->> 'interrumpida')::boolean as interrumpida,
    sin_pareja,
    least(ap_event_time, ci_event_time) as event_time,
    greatest(ap_recorded_time, ci_recorded_time) as recorded_time
from pares
