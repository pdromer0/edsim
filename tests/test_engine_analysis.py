"""Estado y métricas derivados del log: tabla de episodios, curvas, ventana, Little y utilización.

Los logs se construyen a mano con ``build`` de test_invariants (como test_analysis.py
reutiliza el ejemplo de test_mm1_metrics) y los valores esperados se calculan a mano en
los comentarios. Las funciones de análisis no comprueban que el log sea válido: eso es
cosa de las invariantes; aquí solo pliegan los eventos.
"""

from pathlib import Path

import numpy as np
import pytest
from test_invariants import build

from edsim.engine.analysis import CURVES, episode_table, step_curves
from edsim.engine.center import load_center

EXAMPLE = Path(__file__).parent / "data" / "centro_ejemplo.toml"
DAY = 1440.0


@pytest.fixture(scope="module")
def center():
    return load_center(EXAMPLE)


def rows(arrival_id: int, *steps: tuple) -> list[tuple]:
    """Filas (instante, llegada, tipo, payload) de un episodio, en el orden dado."""
    return [(t, arrival_id, event_type, payload) for t, event_type, payload in steps]


def assessment(t: float, box: int, tipo: str = "inicial") -> tuple:
    return (t, "assessment_started", {"tipo": tipo, "pool": "medicos", "box": box})


def ended(t: float, tipo: str = "inicial", cut: bool = False) -> tuple:
    return (t, "assessment_ended", {"tipo": tipo, "interrumpida": cut})


def departure(t: float, destino: str = "alta") -> list[tuple]:
    return [
        (t, "disposition_decided", {"destino": destino}),
        (t, "patient_departed", {"destino": destino}),
    ]


# --- Escenario con esperas: una enfermera y un médico --------------------------------
#
# A (nivel 3, con pruebas): llega 100, triaje 100-110, box 1 en 110, médico 110-130,
#   pruebas 130-190, reevaluación 190-200, sale 200 (ingreso).
# B (nivel 4, sin pruebas): llega 105, espera la enfermera hasta 110, triaje 110-120,
#   box 2 en 120, espera médico hasta 130 (A lo suelta), valoración 130-150, sale 150.
#
# Esperas: A triaje 0, box 0, médico 0. B triaje 5, box 0, médico 10.
# Censo: 1 en 100, 2 en 105, 1 en 150, 0 en 200 → área 5 + 2·45 + 50 = 145 = 100 + 45.

A_ROWS = rows(
    0,
    (100.0, "patient_arrived", {}),
    (100.0, "patient_registered", {}),
    (100.0, "triage_started", {}),
    (110.0, "triage_completed", {"nivel": 3}),
    (110.0, "box_assigned", {"box": 1}),
    assessment(110.0, 1),
    ended(130.0),
    (130.0, "test_ordered", {}),
    (190.0, "test_resulted", {}),
    assessment(190.0, 1, "reevaluacion"),
    ended(200.0, "reevaluacion"),
    *departure(200.0, "ingreso"),
)
B_ROWS = rows(
    1,
    (105.0, "patient_arrived", {}),
    (105.0, "patient_registered", {}),
    (110.0, "triage_started", {}),
    (120.0, "triage_completed", {"nivel": 4}),
    (120.0, "box_assigned", {"box": 2}),
    assessment(130.0, 2),
    ended(150.0),
    *departure(150.0),
)


@pytest.fixture(scope="module")
def two_patients():
    return build(A_ROWS, B_ROWS)


# --- Escenario con desalojo (un box y un médico) ---------------------------------------
#
# P (nivel 3): llega 0, triaje 0-5, box 1 en 5, espera médico 5-10, valoración desde 10.
# Q (nivel 1): llega 10, triaje 10-15. En 15 desaloja a P: la valoración de P se corta
#   (le quedan 20 - 5 = 15 min), P sale del box y Q lo toma; Q 15-35 con el médico, sale 35.
# P recupera el box 1 en 35 y reanuda la valoración 35-50 (sin espera de médico), sale 50.
#
# P: espera de box 0 + (35 - 15) = 20; espera de médico 5 + 0 = 5; inicial 5;
#   puerta-médico 10; estancia 50; un desalojo.

P_ROWS = rows(
    0,
    (0.0, "patient_arrived", {}),
    (0.0, "patient_registered", {}),
    (0.0, "triage_started", {}),
    (5.0, "triage_completed", {"nivel": 3}),
    (5.0, "box_assigned", {"box": 1}),
    assessment(10.0, 1),
)
Q_ROWS = rows(
    1,
    (10.0, "patient_arrived", {}),
    (10.0, "patient_registered", {}),
    (10.0, "triage_started", {}),
    (15.0, "triage_completed", {"nivel": 1}),
)
DISPLACEMENT = [
    (15.0, 0, "assessment_ended", {"tipo": "inicial", "interrumpida": True}),
    (15.0, 0, "patient_displaced", {"box": 1, "desalojado_por": "EP-000001"}),
    (15.0, 1, "box_assigned", {"box": 1}),
    (15.0, 1, *assessment(15.0, 1)[1:]),
    (35.0, 1, *ended(35.0)[1:]),
    (35.0, 1, "disposition_decided", {"destino": "ingreso"}),
    (35.0, 1, "patient_departed", {"destino": "ingreso"}),
    (35.0, 0, "box_assigned", {"box": 1}),
    (35.0, 0, *assessment(35.0, 1)[1:]),
    (50.0, 0, *ended(50.0)[1:]),
    (50.0, 0, "disposition_decided", {"destino": "alta"}),
    (50.0, 0, "patient_departed", {"destino": "alta"}),
]


@pytest.fixture(scope="module")
def displaced():
    return build(P_ROWS, Q_ROWS, DISPLACEMENT)


# --- Tabla de episodios -------------------------------------------------------------


def test_tabla_instantes_y_esperas(two_patients):
    a, b = episode_table(two_patients)

    assert (a.episode_id, b.episode_id) == ("EP-000000", "EP-000001")
    assert (a.arrival, a.triage_start, a.triage_end) == (100.0, 100.0, 110.0)
    assert (a.first_box, a.first_assessment, a.decision, a.departure) == (110, 110, 200, 200)
    assert (a.level, a.destination, a.displacements) == (3, "ingreso", 0)
    assert (a.triage_wait, a.box_wait, a.doctor_wait) == (0.0, 0.0, 0.0)
    assert a.stay == 100.0

    assert (b.arrival, b.triage_start, b.first_box, b.first_assessment) == (105, 110, 120, 130)
    assert (b.level, b.destination) == (4, "alta")
    assert b.triage_wait == 5.0
    assert b.box_wait == 0.0
    assert b.doctor_wait == 10.0
    assert b.initial_doctor_wait == 10.0
    assert b.door_to_doctor == 25.0
    assert b.stay == 45.0


def test_tabla_con_desalojo_suma_las_vueltas(displaced):
    p, q = episode_table(displaced)

    assert p.displacements == 1
    assert p.first_box == 5.0  # el primero, no el de la vuelta
    assert p.first_assessment == 10.0
    assert p.box_wait == 20.0  # 0 + (35 - 15)
    assert p.doctor_wait == 5.0  # 5 antes del desalojo + 0 al volver
    assert p.initial_doctor_wait == 5.0
    assert p.door_to_doctor == 10.0
    assert p.stay == 50.0

    assert (q.level, q.displacements, q.box_wait, q.doctor_wait, q.stay) == (1, 0, 0.0, 0.0, 25.0)


def test_espera_de_medico_de_la_reevaluacion():
    # Como A, pero la reevaluación empieza en 195: espera 5 desde test_resulted (190).
    late = rows(
        0,
        (100.0, "patient_arrived", {}),
        (100.0, "patient_registered", {}),
        (100.0, "triage_started", {}),
        (110.0, "triage_completed", {"nivel": 3}),
        (110.0, "box_assigned", {"box": 1}),
        assessment(110.0, 1),
        ended(130.0),
        (130.0, "test_ordered", {}),
        (190.0, "test_resulted", {}),
        assessment(195.0, 1, "reevaluacion"),
        ended(205.0, "reevaluacion"),
        *departure(205.0),
    )

    (a,) = episode_table(build(late))

    assert a.doctor_wait == 5.0
    assert a.initial_doctor_wait == 0.0  # solo cuenta hasta la primera valoración
    assert a.door_to_doctor == 10.0


def test_resultados_mientras_espera_box_abren_la_espera_al_volver():
    # R tiene box 1 y espera pruebas; lo desalojan en 50; los resultados llegan en 60, sin
    # box; recupera el box en 70 y la reevaluación empieza en 74: espera de médico 4.
    log = build(
        rows(
            0,
            (0.0, "patient_arrived", {}),
            (0.0, "patient_registered", {}),
            (0.0, "triage_started", {}),
            (5.0, "triage_completed", {"nivel": 3}),
            (5.0, "box_assigned", {"box": 1}),
            assessment(5.0, 1),
            ended(25.0),
            (25.0, "test_ordered", {}),
            (50.0, "patient_displaced", {"box": 1, "desalojado_por": "EP-000001"}),
            (60.0, "test_resulted", {}),
            (70.0, "box_assigned", {"box": 1}),
            assessment(74.0, 1, "reevaluacion"),
            ended(84.0, "reevaluacion"),
            *departure(84.0),
        )
    )

    (r,) = episode_table(log)

    assert r.box_wait == 20.0  # 0 + (70 - 50)
    assert r.doctor_wait == 4.0
    assert r.displacements == 1


def test_lo_que_corta_el_horizonte_es_none():
    # S llega en 10 y sigue en triaje al final; T espera médico en su box al final.
    log = build(
        rows(0, (10.0, "patient_arrived", {}), (10.0, "patient_registered", {})),
        rows(
            1,
            (20.0, "patient_arrived", {}),
            (20.0, "patient_registered", {}),
            (20.0, "triage_started", {}),
            (25.0, "triage_completed", {"nivel": 2}),
            (25.0, "box_assigned", {"box": 1}),
        ),
    )

    s, t = episode_table(log)

    assert s.triage_start is None and s.triage_wait is None and s.level is None
    assert s.departure is None and s.stay is None and s.box_wait is None
    assert t.triage_wait == 0.0 and t.first_box == 25.0
    # Las esperas que suman toda la estancia solo son definitivas al salir.
    assert t.box_wait is None and t.doctor_wait is None
    assert t.first_assessment is None and t.initial_doctor_wait is None
    assert t.door_to_doctor is None


def test_tabla_en_orden_de_llegada(two_patients):
    table = episode_table(two_patients)
    assert [e.arrival for e in table] == sorted(e.arrival for e in table)


# --- Curvas escalonadas ---------------------------------------------------------------


def values_at(curves, name, instants):
    return [int(curves.value(name, t)) for t in instants]


def test_curvas_evento_a_evento(two_patients):
    curves = step_curves(two_patients, horizon=DAY)

    assert curves.times[0] == 0.0
    assert np.all(np.diff(curves.times) > 0)
    # Cada valor vale desde su instante, tras todos los eventos del instante.
    instants = [0, 100, 105, 110, 120, 130, 150, 190, 200]
    assert values_at(curves, "census", instants) == [0, 1, 2, 2, 2, 2, 1, 1, 0]
    assert values_at(curves, "waiting_triage", instants) == [0, 0, 1, 0, 0, 0, 0, 0, 0]
    assert values_at(curves, "nurses_busy", instants) == [0, 1, 1, 1, 0, 0, 0, 0, 0]
    assert values_at(curves, "doctors_busy", instants) == [0, 0, 0, 1, 1, 1, 0, 1, 0]
    assert values_at(curves, "boxes_busy", instants) == [0, 0, 0, 1, 2, 2, 1, 1, 0]
    assert values_at(curves, "waiting_box", instants) == [0] * 9
    assert values_at(curves, "nurses_staff", instants) == [1] * 9
    assert values_at(curves, "doctors_staff", instants) == [1] * 9


def test_curva_de_cola_de_box_con_desalojo(displaced):
    curves = step_curves(displaced, horizon=DAY)
    # P espera box de 15 a 35; Q no espera (triage_completed y box_assigned en 15).
    assert values_at(curves, "waiting_box", [0, 5, 15, 35]) == [0, 0, 1, 0]
    assert values_at(curves, "boxes_busy", [5, 15, 35, 50]) == [1, 1, 1, 0]


def test_area_de_las_curvas(two_patients):
    curves = step_curves(two_patients, horizon=DAY)
    assert curves.area("census", 0, DAY) == 145.0
    assert curves.area("waiting_triage", 0, DAY) == 5.0
    assert curves.area("doctors_busy", 0, DAY) == 20 + 20 + 10  # A, B y la reevaluación
    assert curves.area("census", 120, 160) == 2 * 30 + 10


def test_bordes_para_stairs(two_patients):
    curves = step_curves(two_patients, horizon=DAY)
    assert curves.edges[-1] == DAY
    assert len(curves.edges) == len(curves.times) + 1


def test_todas_las_curvas_tienen_nombre():
    assert set(CURVES) == {
        "census",
        "waiting_triage",
        "waiting_box",
        "nurses_busy",
        "doctors_busy",
        "boxes_busy",
        "nurses_staff",
        "doctors_staff",
    }


def test_evento_despues_del_horizonte_falla(two_patients):
    with pytest.raises(ValueError, match="horizon"):
        step_curves(two_patients, horizon=180.0)
