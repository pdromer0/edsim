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

from edsim.engine.center import load_center
from edsim.engine.events import OUTCOME_SCHEMA_VERSION
from edsim.engine.ground_truth import GroundTruth
from edsim.engine.invariants import check_invariants
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
)

DATA = Path(__file__).parent / "data"
CLINICAL_KEYS = {"medio", "edad", "sexo", "motivo", "pool", "pruebas", "resultados"}


@pytest.fixture(scope="module")
def center():
    return load_center(DATA / "centro_ejemplo.toml")


def run(scenario: Scenario) -> list:
    """El log del escenario, después de comprobar que no viola ninguna invariante."""
    result = run_scenario(scenario)
    truth = GroundTruth(episodes=result.run.episodes, days=())
    violations = check_invariants(
        result.events, scenario.center, ground_truth=truth, inside=result.run.inside
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
    small = dataclasses.replace(center, boxes=1, triage_nurses=(1, 1, 1), doctors=(1, 1, 1))
    scenario = Scenario(
        small, ((0.0, outcome_draws(3, 5, 10, patience=0)),), schema_version=OUTCOME_SCHEMA_VERSION
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
    truth = GroundTruth(episodes=result.run.episodes, days=())
    assert result.run.inside == 1
    assert check_invariants(result.events, scenario.center, ground_truth=truth, inside=1) == []
    assert trace(result.events, 0) == [*R1_UNTIL_DECISION, *displaced(60.0, 1, "EP-000002")]
