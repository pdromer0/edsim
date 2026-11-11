"""El motor del hito 5 con pacientes a mano: abandono, destinos, cama y pasillo (tarea 5.1).

Cada escenario de `engine/scenarios.py` se compara, episodio a episodio, con su lista
de eventos calculada a mano en el plan (llegada, más espera, más servicio, o llegada más
paciencia), escrita aquí con las funciones de abajo, sin el motor. Además, cada log pasa
todas las invariantes con el ground truth y los procesos vivos.

De los payloads se comparan los del flujo (nivel, box, tipo, espera, destino, circuito,
desalojo, interrumpida y servicio); los clínicos son fijos en estos pacientes y los
comprueba la invariante `clinical`.
"""

import dataclasses
from pathlib import Path

import pytest

from edsim.engine.analysis import OutcomeCounts, outcome_counts
from edsim.engine.center import load_center
from edsim.engine.events import OUTCOME_SCHEMA_VERSION
from edsim.engine.ground_truth import GroundTruth
from edsim.engine.invariants import InvariantContext, check_abandonment, check_invariants
from edsim.engine.report import format_outcome_counts
from edsim.engine.scenarios import (
    Scenario,
    abandonment,
    admission,
    bed_shift,
    destinations,
    late_triage,
    level1_waits,
    outcome_draws,
    run_scenario,
    seen_in_room,
    unseen_displacement,
    with_beds,
)

DATA = Path(__file__).parent / "data"
CLINICAL_KEYS = {"medio", "edad", "sexo", "motivo", "pool", "pruebas", "resultados"}


@pytest.fixture(scope="module")
def center():
    return load_center(DATA / "centro_ejemplo.toml")


def run(scenario: Scenario) -> list:
    """El log del escenario, después de comprobar que no viola ninguna invariante.

    Con el ground truth del escenario, con sus días (tarea 5.3): las invariantes comparan
    también cada abandono con la paciencia, cada destino con el sorteado y cada espera de
    cama con la base y los factores del centro, que lleva [camas].
    """
    result = run_scenario(scenario)
    assert scenario.center.has_beds and result.ground_truth.days
    violations = check_invariants(
        result.events, scenario.center, ground_truth=result.ground_truth, inside=result.run.inside
    )
    assert violations == []
    assert {e.schema_version for e in result.events} == {OUTCOME_SCHEMA_VERSION}
    return result.events


def trace(events, arrival_id: int) -> list:
    episode = f"EP-{arrival_id:06d}"
    return [
        (e.event_type, e.sim_time, {k: v for k, v in e.payload.items() if k not in CLINICAL_KEYS})
        for e in events
        if e.episode_id == episode
    ]


# --- Las listas a mano -------------------------------------------------------------------


def arrive(t):
    return [("patient_arrived", t, {}), ("patient_registered", t, {})]


def nurse(start, end, level):
    return [
        ("triage_started", start, {"circuito": "enfermeria"}),
        ("triage_completed", end, {"nivel": level}),
    ]


def door(t):
    return [
        ("triage_started", t, {"circuito": "puerta"}),
        ("triage_completed", t, {"nivel": 1}),
    ]


def box(t, number):
    return [("box_assigned", t, {"box": number})]


def assess(start, end, number, tipo="inicial"):
    return [
        ("assessment_started", start, {"tipo": tipo, "box": number}),
        ("assessment_ended", end, {"tipo": tipo, "interrumpida": False}),
    ]


def out(t, destino="alta"):
    return [
        ("disposition_decided", t, {"destino": destino}),
        ("patient_departed", t, {"destino": destino}),
    ]


def left(t, espera):
    return [("patient_left_wbs", t, {"espera": espera})]


def displaced(t, number, by):
    return [("patient_displaced", t, {"box": number, "desalojado_por": by})]


# --- Escenario M: los tres sitios del abandono y el empate ---------------------------

Q1 = [*arrive(0.0), *nurse(0.0, 5.0, 3), *box(5.0, 1), *assess(5.0, 45.0, 1), *out(45.0)]
Q4 = [*arrive(3.0), *left(3.0 + 1, "triaje")]  # plazo 3 + 1 = 4, esperando enfermera


def test_escenario_m(center):
    events = run(abandonment(center))
    assert trace(events, 0) == Q1
    # Q2: plazo 1 + 25 = 26, en el box 2 esperando al médico (lo tiene Q1 hasta 45).
    assert trace(events, 1) == [
        *arrive(1.0),
        *nurse(1.0, 6.0, 4),
        *box(6.0, 2),
        *left(26.0, "medico"),
    ]
    # Q3: enfermera en 5 (la libera Q1), box 2 en 26 (lo libera Q2) y médico en 45, el
    # instante de su plazo 2 + 43: empate, se queda. Valoración 45 + 20 = 65.
    assert trace(events, 2) == [
        *arrive(2.0),
        *nurse(5.0, 10.0, 4),
        *box(26.0, 2),
        *assess(45.0, 65.0, 2),
        *out(65.0),
    ]
    assert trace(events, 3) == Q4


def test_escenario_m_con_paciencia_42(center):
    events = run(abandonment(center, q3_patience=42))
    assert trace(events, 0) == Q1
    # Plazo 2 + 42 = 44, en el box 2 esperando al médico.
    assert trace(events, 2) == [
        *arrive(2.0),
        *nurse(5.0, 10.0, 4),
        *box(26.0, 2),
        *left(44.0, "medico"),
    ]
    assert trace(events, 3) == Q4


def test_escenario_m_con_un_box(center):
    events = run(abandonment(center, boxes=1))
    assert trace(events, 0) == Q1
    # Q2 espera box (Q1 tiene el único): plazo 26.
    assert trace(events, 1) == [*arrive(1.0), *nurse(1.0, 6.0, 4), *left(26.0, "box")]
    # Q3 recibe el box 1 y el médico en 45, cuando sale Q1, el instante de su plazo.
    assert trace(events, 2) == [
        *arrive(2.0),
        *nurse(5.0, 10.0, 4),
        *box(45.0, 1),
        *assess(45.0, 65.0, 1),
        *out(65.0),
    ]
    assert trace(events, 3) == Q4


# --- Escenario T: el plazo vence durante el triaje --------------------------------------

T0 = [*arrive(0.0), *nurse(0.0, 55.0, 3), *box(55.0, 1), *assess(55.0, 115.0, 1), *out(115.0)]


def test_plazo_vencido_en_el_triaje_sin_box(center):
    # T1: enfermera en 55 < plazo 61; triaje 55-62; el plazo vence en 61, durante el
    # triaje. En max(61, 62) = 62 no hay box: se va esperando box.
    events = run(late_triage(center))
    assert trace(events, 0) == T0
    assert trace(events, 1) == [*arrive(1.0), *nurse(55.0, 62.0, 5), *left(62.0, "box")]


def test_plazo_vencido_en_el_triaje_sin_medico(center):
    events = run(late_triage(center, boxes=2))
    assert trace(events, 0) == T0
    assert trace(events, 1) == [
        *arrive(1.0),
        *nurse(55.0, 62.0, 5),
        *box(62.0, 2),
        *left(62.0, "medico"),
    ]


def test_plazo_vencido_en_el_triaje_con_box_y_medico(center):
    # Recibe box y médico en el mismo instante en que acaba el triaje: se queda.
    events = run(late_triage(center, boxes=2, doctors=2))
    assert trace(events, 0) == T0
    assert trace(events, 1) == [
        *arrive(1.0),
        *nurse(55.0, 62.0, 5),
        *box(62.0, 2),
        *assess(62.0, 72.0, 2),
        *out(72.0),
    ]


# --- Escenario X: desalojo antes y después de ser visto ------------------------------

X1 = [*arrive(0.0), *nurse(0.0, 5.0, 3), *box(5.0, 1), *assess(5.0, 45.0, 1), *out(45.0)]


def test_desalojo_antes_de_ser_visto(center):
    events = run(unseen_displacement(center))
    assert trace(events, 0) == X1
    # X2: desalojada en 20 sin ser vista; espera box hasta su plazo 1 + 30 = 31.
    assert trace(events, 1) == [
        *arrive(1.0),
        *nurse(5.0, 10.0, 4),
        *box(10.0, 2),
        *displaced(20.0, 2, "EP-000002"),
        *left(31.0, "box"),
    ]
    # X3: box 2 en 20; médico en 45, cuando lo libera X1; valoración 45 + 10 = 55.
    assert trace(events, 2) == [
        *arrive(20.0),
        *door(20.0),
        *box(20.0, 2),
        *assess(45.0, 55.0, 2),
        *out(55.0),
    ]


def test_desalojo_despues_de_ser_visto(center):
    events = run(unseen_displacement(center, seen=True))
    assert trace(events, 0) == X1
    # X2: vista en 10; cortada en 20 (le quedan 30 - 10 = 20); box 2 en 30, cuando sale
    # X3; reanuda 30-50. Su plazo 1 + 15 = 16 venció, pero ya estaba vista.
    assert trace(events, 1) == [
        *arrive(1.0),
        *nurse(5.0, 10.0, 4),
        *box(10.0, 2),
        ("assessment_started", 10.0, {"tipo": "inicial", "box": 2}),
        ("assessment_ended", 20.0, {"tipo": "inicial", "interrumpida": True}),
        *displaced(20.0, 2, "EP-000002"),
        *box(30.0, 2),
        *assess(30.0, 50.0, 2),
        *out(50.0),
    ]
    assert trace(events, 2) == [
        *arrive(20.0),
        *door(20.0),
        *box(20.0, 2),
        *assess(20.0, 30.0, 2),
        *out(30.0),
    ]


# --- Nivel 1, visto, paciencia 0 --------------------------------------------------------


def test_un_nivel_1_con_paciencia_0_no_abandona(center):
    events = run(level1_waits(center))
    assert trace(events, 0) == [
        *arrive(0.0),
        *door(0.0),
        *box(0.0, 1),
        *assess(0.0, 30.0, 1),
        *out(30.0),
    ]
    # L1 no puede desalojar a otro nivel 1: espera el box hasta 30.
    assert trace(events, 1) == [
        *arrive(1.0),
        *door(1.0),
        *box(30.0, 1),
        *assess(30.0, 40.0, 1),
        *out(40.0),
    ]


def test_nadie_se_va_despues_de_ser_visto(center):
    events = run(seen_in_room(center))
    # P: valoración 20-30, a la sala; resultados en 30 + 60 = 90; box 2 (S tiene el 1);
    # espera médico hasta 105 (S, 75 + 30); reevaluación 105-115. Su plazo, 50.
    assert trace(events, 0) == [
        *arrive(0.0),
        *nurse(0.0, 20.0, 4),
        *box(20.0, 1),
        *assess(20.0, 30.0, 1),
        ("test_ordered", 30.0, {}),
        ("box_released", 30.0, {"box": 1, "espera": "resultados"}),
        ("test_resulted", 90.0, {}),
        *box(90.0, 2),
        *assess(105.0, 115.0, 2, tipo="reevaluacion"),
        *out(115.0),
    ]
    assert trace(events, 1) == [
        *arrive(70.0),
        *nurse(70.0, 75.0, 3),
        *box(75.0, 1),
        *assess(75.0, 105.0, 1),
        *out(105.0),
    ]


def test_paciencia_0_con_todo_libre(center):
    # Caso límite: la enfermera se concede al pedirla en 0 (empate) y el plazo vence en el
    # triaje; en 5 recibe box y médico en ese instante, así que se queda.
    # Con la verdad, es la excepción del triaje: visto en 5, después de su plazo (0), en
    # el instante en que acaba el triaje.
    small = dataclasses.replace(center, boxes=1, triage_nurses=(1, 1, 1), doctors=(1, 1, 1))
    scenario = Scenario(
        with_beds(small),
        ((0.0, outcome_draws(3, 5, 10, patience=0)),),
        schema_version=OUTCOME_SCHEMA_VERSION,
    )
    events = run(scenario)
    assert trace(events, 0) == [
        *arrive(0.0),
        *nurse(0.0, 5.0, 3),
        *box(5.0, 1),
        *assess(5.0, 15.0, 1),
        *out(15.0),
    ]


# --- Destinos, espera de cama y pasillo --------------------------------------------------


def bed_wait(t):
    return [
        ("bed_assigned", t, {"servicio": "planta"}),
        ("patient_departed", t, {"destino": "ingreso"}),
    ]


def admitted(t):
    return [
        ("disposition_decided", t, {"destino": "ingreso"}),
        ("bed_requested", t, {"servicio": "planta"}),
    ]


# R1: valoración 5-35; pide cama a las 0:35, de noche: 100 × 1,5 = 150; cama en 185.
R1_UNTIL_DECISION = [
    *arrive(0.0),
    *nurse(0.0, 5.0, 3),
    *box(5.0, 1),
    *assess(5.0, 35.0, 1),
    *admitted(35.0),
]


def test_escenario_c_el_ingresado_espera_la_cama_en_el_pasillo(center):
    events = run(admission(center))
    assert trace(events, 0) == [
        *R1_UNTIL_DECISION,
        *displaced(60.0, 1, "EP-000002"),
        *bed_wait(185.0),
    ]
    # R2 recibe el box cuando sale R3 (60 + 20 = 80), no cuando se va R1.
    assert trace(events, 1) == [
        *arrive(10.0),
        *nurse(10.0, 15.0, 4),
        *box(80.0, 1),
        *assess(80.0, 100.0, 1),
        *out(100.0),
    ]
    # R3: nivel 1 con paciencia 0; desaloja a R1 y no abandona.
    assert trace(events, 2) == [
        *arrive(60.0),
        *door(60.0),
        *box(60.0, 1),
        *assess(60.0, 80.0, 1),
        *out(80.0),
    ]


def test_escenario_c_sin_r3_el_box_queda_bloqueado(center):
    events = run(admission(center, r3_arrival=None))
    assert trace(events, 0) == [*R1_UNTIL_DECISION, *bed_wait(185.0)]
    # R2 recibe el box en 185, cuando R1 sale con su cama: 185 + 20 = 205.
    assert trace(events, 1) == [
        *arrive(10.0),
        *nurse(10.0, 15.0, 4),
        *box(185.0, 1),
        *assess(185.0, 205.0, 1),
        *out(205.0),
    ]


def test_un_nivel_1_en_el_instante_de_la_cama(center):
    # R3 llega en 185: su llegada (programada en 10) va antes que la cama (en 35), así que
    # desaloja a R1, que recoge la cama en el pasillo en ese instante; la concesión del
    # box de R3 (creada en 185) va después. bed_assigned y la salida, seguidos.
    events = run(admission(center, r3_arrival=185.0))
    assert trace(events, 0) == [
        *R1_UNTIL_DECISION,
        *displaced(185.0, 1, "EP-000002"),
        *bed_wait(185.0),
    ]
    types = [(e.episode_id, e.event_type) for e in events if e.sim_time == 185.0]
    i = types.index(("EP-000000", "bed_assigned"))
    assert types[i + 1] == ("EP-000000", "patient_departed")
    assert types[i + 2] == ("EP-000002", "box_assigned")
    assert trace(events, 2) == [
        *arrive(185.0),
        *door(185.0),
        *box(185.0, 1),
        *assess(185.0, 205.0, 1),
        *out(205.0),
    ]


def test_la_cama_usa_el_turno_del_pedido(center):
    # Llega a las 7:30 (noche), valoración 455-490 y pide cama a las 8:10 (mañana):
    # 100 × 0,8 = 80; cama en 490 + 80 = 570.
    events = run(bed_shift(center))
    assert trace(events, 0) == [
        *arrive(450.0),
        *nurse(450.0, 455.0, 3),
        *box(455.0, 1),
        *assess(455.0, 490.0, 1),
        *admitted(490.0),
        *bed_wait(570.0),
    ]


def test_traslado_exitus_y_alta_salen_al_decidirse(center):
    events = run(destinations(center))
    for i, destino in enumerate(("traslado", "exitus", "alta")):
        t = float(i)
        assert trace(events, i) == [
            *arrive(t),
            *nurse(t, t + 5, 3),
            *box(t + 5, i + 1),
            *assess(t + 5, t + 15, i + 1),
            *out(t + 15, destino),
        ]


def test_el_del_pasillo_sigue_dentro_en_el_horizonte(center):
    # Con cama base 1000, de noche 1500: la cama llegaría en 35 + 1500 = 1535 > 1440.
    base = admission(center)
    r1 = outcome_draws(3, 5, 30, destination="ingreso", bed_base=1000)
    scenario = dataclasses.replace(base, patients=((0.0, r1), *base.patients[1:]))
    result = run_scenario(scenario)
    assert result.run.inside == 1
    assert (
        check_invariants(result.events, scenario.center, ground_truth=result.ground_truth, inside=1)
        == []
    )
    assert trace(result.events, 0) == [*R1_UNTIL_DECISION, *displaced(60.0, 1, "EP-000002")]


# --- Las invariantes con la verdad del desenlace (tarea 5.3) ---------------------------------
#
# Cada perturbación cambia un valor de la verdad (o quita un evento del log) y espera
# exactamente las violaciones que da el cálculo a mano del plan.


def perturbed(result, episode: str, **changes) -> GroundTruth:
    """El ground truth del escenario con el desenlace de ``episode`` cambiado."""
    episodes = tuple(
        dataclasses.replace(e, outcome=dataclasses.replace(e.outcome, **changes))
        if e.episode_id == episode
        else e
        for e in result.ground_truth.episodes
    )
    return dataclasses.replace(result.ground_truth, episodes=episodes)


def violations_of(events, center, truth, check: str) -> list:
    return [v for v in check_invariants(events, center, ground_truth=truth) if v.check == check]


def test_la_paciencia_de_la_verdad_fija_el_instante_del_abandono(center):
    # Escenario M: Q2 (EP-000001) llega en 1 con paciencia 25 y se va en 26. Con 24 en la
    # verdad, lo esperado es 1 + 24 = 25 frente a 26: una violación.
    scenario = abandonment(center)
    result = run_scenario(scenario)
    found = violations_of(
        result.events, scenario.center, perturbed(result, "EP-000001", patience=24.0), "abandonment"
    )

    assert [(v.episode_id, v.sim_time) for v in found] == [("EP-000001", 26.0)]
    assert "left at 26.0" in found[0].message and "give 25.0" in found[0].message


def test_nadie_es_visto_despues_de_su_plazo(center):
    # Q3 (EP-000002) llega en 2 y es visto en 45, el instante de su plazo 2 + 43 (empate:
    # se queda). Con 42,5 en la verdad, el plazo es 44,5 y lo ven después: una violación.
    scenario = abandonment(center)
    result = run_scenario(scenario)
    found = violations_of(
        result.events, scenario.center, perturbed(result, "EP-000002", patience=42.5), "abandonment"
    )

    assert [(v.episode_id, v.sim_time) for v in found] == [("EP-000002", 45.0)]
    assert "after its deadline 44.5" in found[0].message


def without_left_wbs(events, episode: str) -> list:
    return [
        e for e in events if not (e.episode_id == episode and e.event_type == "patient_left_wbs")
    ]


def test_quien_sigue_esperando_con_el_plazo_vencido(center):
    # El log de M sin el patient_left_wbs de Q4 (EP-000003, llega en 3, paciencia 1): sin
    # terminal y sin triaje. Su plazo, 3 + 1 = 4, cae antes del horizonte 1 × 1440: una
    # violación. Con paciencia 1.000.000, el plazo 1.000.003 > 1440: ninguna.
    scenario = abandonment(center)
    result = run_scenario(scenario)
    events = without_left_wbs(result.events, "EP-000003")
    context = InvariantContext(scenario.center, ground_truth=result.ground_truth)
    late = InvariantContext(
        scenario.center, ground_truth=perturbed(result, "EP-000003", patience=1_000_000.0)
    )

    found = check_abandonment(events, context)
    assert [(v.episode_id, v.event_id) for v in found] == [("EP-000003", None)]
    assert "due at 4.0" in found[0].message
    assert check_abandonment(events, late) == []


def test_sin_los_dias_no_se_mira_quien_sigue_esperando(center):
    # Sin días no hay horizonte: la tercera regla no se comprueba (las otras dos, sí).
    scenario = abandonment(center)
    result = run_scenario(scenario)
    events = without_left_wbs(result.events, "EP-000003")
    no_days = dataclasses.replace(result.ground_truth, days=())

    assert check_abandonment(events, InvariantContext(scenario.center, ground_truth=no_days)) == []


def test_el_destino_de_la_decision_es_el_sorteado(center):
    # Q1 (EP-000000) recibe el alta en 45; con «traslado» en la verdad, una violación.
    scenario = abandonment(center)
    result = run_scenario(scenario)
    found = violations_of(
        result.events,
        scenario.center,
        perturbed(result, "EP-000000", destination="traslado"),
        "outcome",
    )

    assert [(v.episode_id, v.sim_time) for v in found] == [("EP-000000", 45.0)]
    assert "drawn destination is 'traslado'" in found[0].message


def test_la_espera_de_cama_es_la_base_por_los_factores_del_centro(center):
    # Escenario C: R1 (EP-000000) pide cama en 35 (0:35, noche, 1,5) con base 100: espera
    # 150, cama en 185. Con base 101 en la verdad, lo esperado es 151,5: una violación.
    scenario = admission(center)
    result = run_scenario(scenario)
    found = violations_of(
        result.events, scenario.center, perturbed(result, "EP-000000", bed_base=101.0), "outcome"
    )

    assert [(v.episode_id, v.sim_time) for v in found] == [("EP-000000", 185.0)]
    assert "waited 150.0" in found[0].message and "gives 151.5" in found[0].message
    # Sin [camas] en el centro, la espera no se compara: no hay factores con los que hacerlo.
    assert (
        violations_of(
            result.events, center, perturbed(result, "EP-000000", bed_base=101.0), "outcome"
        )
        == []
    )


# --- Recuentos del desenlace (tarea 5.3), con los escenarios a mano --------------------------


def test_recuentos_del_escenario_m(center):
    # Q4 se va en 3 + 1 = 4 (triaje), Q2 en 1 + 25 = 26 (médico); Q1 alta en 45 y Q3 alta
    # (empate en 45: se queda). 4 llegadas, 2 abandonos, 2 altas, nadie dentro.
    counts = outcome_counts(run_scenario(abandonment(center)).events, 0.0, 1440.0)

    assert counts == OutcomeCounts(arrivals=4, left=(1, 0, 1), departed=(2, 0, 0, 0), inside=0)
    assert counts.left_total == 2


def test_recuentos_del_escenario_c(center):
    # R1 ingresa (cama en 35 + 100 × 1,5 = 185); R2 y R3, alta.
    counts = outcome_counts(run_scenario(admission(center)).events, 0.0, 1440.0)

    assert counts == OutcomeCounts(arrivals=3, left=(0, 0, 0), departed=(2, 1, 0, 0), inside=0)


def test_los_recuentos_son_de_los_que_llegan_en_la_ventana(center):
    # [2, 1440): Q3 (llega en 2, alta) y Q4 (llega en 3, se va en el triaje); Q1 y Q2, fuera.
    counts = outcome_counts(run_scenario(abandonment(center)).events, 2.0, 1440.0)

    assert counts == OutcomeCounts(arrivals=2, left=(1, 0, 0), departed=(1, 0, 0, 0), inside=0)


def test_quien_sigue_en_el_pasillo_cuenta_dentro(center):
    # Con cama base 1000 (de noche, 1500), R1 sigue esperando cama en el horizonte.
    base = admission(center)
    r1 = outcome_draws(3, 5, 30, destination="ingreso", bed_base=1000)
    scenario = dataclasses.replace(base, patients=((0.0, r1), *base.patients[1:]))
    counts = outcome_counts(run_scenario(scenario).events, 0.0, 1440.0)

    assert counts == OutcomeCounts(arrivals=3, left=(0, 0, 0), departed=(2, 0, 0, 0), inside=1)


def test_recuentos_de_un_log_vacio():
    assert outcome_counts([], 0.0, 1440.0) == OutcomeCounts(0, (0, 0, 0), (0, 0, 0, 0), 0)


def test_el_texto_de_los_recuentos(center):
    # Los del escenario M: 2 de 4 se van, el 50,0 %; sin violaciones.
    counts = OutcomeCounts(arrivals=4, left=(1, 0, 1), departed=(2, 0, 0, 0), inside=0)

    assert format_outcome_counts(counts, []).splitlines() == [
        "Desenlace de los episodios que llegan en la ventana (modelo del hito 5)",
        "Llegadas: 4",
        "Se van sin ser vistos: 2 (50.0 %): triaje 1, box 0, médico 1",
        "Salidas: alta 2, ingreso 0, traslado 0, exitus 0",
        "Siguen dentro al final: 0",
        "",
        "Las métricas con abandono y espera de cama llegan con la tarea 5.4.",
        "",
        "Invariantes: 0 violaciones",
    ]
    # Sin llegadas, el porcentaje es 0 y no una división por cero.
    empty = format_outcome_counts(OutcomeCounts(0, (0, 0, 0), (0, 0, 0, 0), 0), [])
    assert "Se van sin ser vistos: 0 (0.0 %)" in empty


def test_un_plazo_vencido_antes_del_triaje_no_espera_a_su_fin(center):
    # Escenario T: T1 (EP-000001) llega en 1 y espera enfermera hasta 55. Con paciencia 50
    # en la verdad, el plazo 1 + 50 = 51 vence antes de empezar el triaje: debía irse en
    # 51 desde «triaje», no al acabarlo. Con un box se fue en 62: una violación (con la
    # regla max(plazo, fin del triaje) daría 62 y no la vería).
    scenario = late_triage(center)
    result = run_scenario(scenario)
    found = violations_of(
        result.events, scenario.center, perturbed(result, "EP-000001", patience=50.0), "abandonment"
    )

    assert [(v.episode_id, v.sim_time) for v in found] == [("EP-000001", 62.0)]
    assert "give 51.0" in found[0].message


def test_con_el_plazo_vencido_antes_del_triaje_no_hay_excepcion(center):
    # Con dos boxes y dos médicos, T1 recibe los dos en 62, al acabar el triaje. Con su
    # plazo en 61 (paciencia 60) es la excepción y se queda; con 51, venció antes de
    # empezar el triaje y la excepción no vale: visto después de su plazo, una violación.
    scenario = late_triage(center, boxes=2, doctors=2)
    result = run_scenario(scenario)
    found = violations_of(
        result.events, scenario.center, perturbed(result, "EP-000001", patience=50.0), "abandonment"
    )

    assert violations_of(result.events, scenario.center, result.ground_truth, "abandonment") == []
    assert [(v.episode_id, v.sim_time) for v in found] == [("EP-000001", 62.0)]
    assert "after its deadline 51.0" in found[0].message


def test_las_violaciones_con_la_verdad_van_detras(center):
    # Dentro de una invariante, primero las del log, en el orden del fichero, y después las
    # de la verdad. M con la espera de Q4 cambiada a «box» (en 4, del log) y la paciencia
    # de Q2 en 24 (en 26, de la verdad).
    scenario = abandonment(center)
    result = run_scenario(scenario)
    events = [
        dataclasses.replace(e, payload={"espera": "box"})
        if e.episode_id == "EP-000003" and e.event_type == "patient_left_wbs"
        else e
        for e in result.events
    ]
    found = violations_of(
        events, scenario.center, perturbed(result, "EP-000001", patience=24.0), "abandonment"
    )

    assert [(v.episode_id, v.sim_time) for v in found] == [("EP-000003", 4.0), ("EP-000001", 26.0)]
