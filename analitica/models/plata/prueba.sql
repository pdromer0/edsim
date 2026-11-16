{#
    plata.prueba: una por prueba y ronda, (run_id, episode_id, ronda, prueba). Ver «prueba» en
    plata.md.

    Una ronda es un test_ordered con su test_resulted, emparejados por tiempo (macro emparejar);
    en EDsim hay como mucho una por episodio. Las pruebas salen de la lista pedida y de las
    claves del resultado, juntas (D4 de la 8.3): una lista vacía no hace desaparecer la ronda.
    Un campo vacío es un null de JSON, y jsonb_array_elements_text o jsonb_each_text fallan
    sobre un escalar: por eso se comprueba antes el tipo.
#}
with vigentes as (

    select * from {{ ref('registros_vigentes') }}

), rondas as (

    {{ emparejar(['test_ordered'], ['test_resulted']) }}

), pedidas as (

    select r.run_id, r.episode_id, r.n as ronda, p.prueba
    from rondas as r
    cross join lateral jsonb_array_elements_text(
        case
            when jsonb_typeof(r.ap_payload -> 'pruebas') = 'array' then r.ap_payload -> 'pruebas'
            else '[]'::jsonb
        end
    ) as p (prueba)

), resultados as (

    select r.run_id, r.episode_id, r.n as ronda, x.key as prueba, x.value as resultado
    from rondas as r
    cross join lateral jsonb_each_text(
        case
            when jsonb_typeof(r.ci_payload -> 'resultados') = 'object'
                then r.ci_payload -> 'resultados'
            else '{}'::jsonb
        end
    ) as x

), pruebas as (

    select
        run_id,
        episode_id,
        ronda,
        prueba,
        p.prueba is not null as en_la_peticion,
        x.resultado
    from pedidas as p
    full join resultados as x using (run_id, episode_id, ronda, prueba)

)

select
    t.run_id,
    t.episode_id,
    t.ronda,
    t.prueba,
    r.ap_event_time as pedida,
    t.resultado,
    r.ci_event_time as hora_resultado,
    t.resultado is null as sin_resultado,
    not t.en_la_peticion as sin_peticion,
    least(r.ap_event_time, r.ci_event_time) as event_time,
    greatest(r.ap_recorded_time, r.ci_recorded_time) as recorded_time
from pruebas as t
inner join rondas as r
    on r.run_id = t.run_id
    and r.episode_id = t.episode_id
    and r.n = t.ronda
