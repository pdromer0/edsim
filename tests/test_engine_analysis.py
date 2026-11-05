"""Estado y métricas derivados del log: tabla de episodios, curvas, ventana, Little y utilización.

Los logs se construyen a mano con ``build`` de test_invariants (como test_analysis.py
reutiliza el ejemplo de test_mm1_metrics) y los valores esperados se calculan a mano en
los comentarios. Las funciones de análisis no comprueban que el log sea válido: eso es
cosa de las invariantes; aquí solo pliegan los eventos.
"""

import dataclasses
from pathlib import Path
from types import MappingProxyType

import numpy as np
import pytest
from test_invariants import build

from edsim.engine import analysis
from edsim.engine.analysis import (
    CURVES,
    MEASURES,
    StepCurves,
    analyze_run,
    busy_intervals,
    episode_table,
    little_laws,
    step_curves,
    utilization_identities,
    window_metrics,
)
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


def test_tres_relojes_hasta_el_medico(two_patients, displaced):
    # Reloj A desde la llegada, B desde el inicio del triaje y C desde la clasificación.
    # A: llega, empieza y termina el triaje en 100, 100 y 110; médico en 110.
    # B: 105, 110 y 120; médico en 130. P (desalojo): 0, 0 y 5; médico en 10.
    a, b = episode_table(two_patients)
    p, _ = episode_table(displaced)

    assert (a.door_to_doctor, a.triage_start_to_doctor, a.classified_to_doctor) == (10, 10, 0)
    assert (b.door_to_doctor, b.triage_start_to_doctor, b.classified_to_doctor) == (25, 20, 10)
    # La primera valoración, no la reanudación tras el desalojo (35).
    assert (p.door_to_doctor, p.triage_start_to_doctor, p.classified_to_doctor) == (10, 10, 5)


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
    # Los tres relojes esperan a la primera valoración, aunque haya triaje.
    assert t.triage_start_to_doctor is None and t.classified_to_doctor is None
    assert s.triage_start_to_doctor is None and s.classified_to_doctor is None


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


# --- Métricas en la ventana -------------------------------------------------------------


def quick(arrival_id: int, t0: float, assess: tuple[float, float], *, level: int = 3) -> list:
    """Episodio sin esperas de triaje ni de box: triaje t0 a t0+5, box en t0+5,
    valoración ``assess`` (inicio y fin) y salida al terminarla."""
    start, end = assess
    return rows(
        arrival_id,
        (t0, "patient_arrived", {}),
        (t0, "patient_registered", {}),
        (t0, "triage_started", {}),
        (t0 + 5, "triage_completed", {"nivel": level}),
        (t0 + 5, "box_assigned", {"box": arrival_id + 1}),
        assessment(start, arrival_id + 1),
        ended(end),
        *departure(end),
    )


def metrics_of(events, center, start, end, horizon):
    return window_metrics(episode_table(events), step_curves(events, horizon), center, start, end)


def test_medidas_por_episodio():
    assert MEASURES == (
        "triage_wait",
        "box_wait",
        "doctor_wait",
        "initial_doctor_wait",
        "door_to_doctor",
        "triage_start_to_doctor",
        "classified_to_doctor",
        "stay",
    )


def test_metricas_por_nivel_y_totales(two_patients, center):
    m = metrics_of(two_patients, center, 0.0, DAY, DAY)

    assert (m.start, m.end, m.arrivals) == (0.0, DAY, 2)
    assert m.throughput == 2 / DAY
    assert m.overall.level is None and m.overall.n == 2
    assert m.overall.mean["stay"] == 72.5  # (100 + 45) / 2
    assert m.overall.mean["triage_wait"] == 2.5
    assert m.overall.p90["triage_wait"] == pytest.approx(4.5)  # entre 0 y 5, interpolación lineal
    assert m.overall.mean["doctor_wait"] == 5.0
    assert m.overall.mean["door_to_doctor"] == 17.5  # (10 + 25) / 2
    assert m.overall.mean["triage_start_to_doctor"] == 15.0  # (10 + 20) / 2
    assert m.overall.mean["classified_to_doctor"] == 5.0  # (0 + 10) / 2

    by_level = {lm.level: lm for lm in m.by_level}
    assert sorted(by_level) == [1, 2, 3, 4, 5]
    assert (by_level[3].n, by_level[3].mean["stay"], by_level[3].p90["stay"]) == (1, 100, 100)
    assert (by_level[4].n, by_level[4].mean["doctor_wait"]) == (1, 10.0)
    assert by_level[1].n == 0 and by_level[1].mean["stay"] is None
    assert by_level[1].p90["stay"] is None


def test_medias_en_el_tiempo(two_patients, center):
    m = metrics_of(two_patients, center, 0.0, DAY, DAY)
    assert m.time_averages["census"] == pytest.approx(145 / DAY, rel=1e-15)
    assert m.time_averages["waiting_triage"] == pytest.approx(5 / DAY, rel=1e-15)
    assert m.time_averages["doctors_staff"] == 1.0
    assert set(m.time_averages) == set(CURVES)


# Ventana [1440, 2880]: D llega en 1400 y sale en 1500 (cruza el inicio); E de 1500 a 1560.
# Censo en la ventana: D 60 + E 60 = 120. Solo E llega dentro y termina: W = 60.
CROSSING = (quick(0, 1400.0, (1405.0, 1500.0)), quick(1, 1500.0, (1505.0, 1560.0)))


def test_la_ventana_recorta_areas_y_filtra_episodios(center):
    m = metrics_of(build(*CROSSING), center, DAY, 2 * DAY, 2 * DAY)

    assert m.arrivals == 1
    assert m.overall.n == 1 and m.overall.mean["stay"] == 60.0
    assert m.time_averages["census"] == pytest.approx(120 / DAY, rel=1e-15)


# --- Ocupación por turno ------------------------------------------------------------------
#
# Médicos: 1 desde el minuto 0 y 2 desde las 8:00 (480). Turnos 8, 15 y 22.
# X: triaje 440-445, box 445-500, valoración 450-500. Y: triaje 470-475, box 475-520,
# valoración 490-520.
#   Médicos  noche [0, 480) ∪ [1320, 1440): ocupados 30 (X 450-480); plantilla 480·1 + 120·2.
#            mañana [480, 900): ocupados 20 + 30; plantilla 420·2. Tarde: 0 de 840.
#   Enfermeras (1 todo el día): noche 10 de 600; mañana y tarde 0 de 420.
#   Boxes (30): noche X 35 + Y 5 = 40 de 30·600; mañana X 20 + Y 40 = 60 de 30·420.

SHIFT_CHANGE = [
    (480.0, None, "staffing_changed", {"recurso": "medicos", "anterior": 1, "nueva": 2})
]


def test_ocupacion_por_pool_y_turno_con_cambio_de_plantilla(center):
    events = build(SHIFT_CHANGE, quick(0, 440.0, (450.0, 500.0)), quick(1, 470.0, (490.0, 520.0)))

    m = metrics_of(events, center, 0.0, DAY, DAY)

    occ = {(o.pool, o.shift): (o.busy_area, o.staff_area) for o in m.occupancy}
    assert occ[("medicos", "night")] == (30.0, 720.0)
    assert occ[("medicos", "morning")] == (50.0, 840.0)
    assert occ[("medicos", "afternoon")] == (0.0, 840.0)
    assert occ[("enfermeria_triaje", "night")] == (10.0, 600.0)
    assert occ[("enfermeria_triaje", "morning")] == (0.0, 420.0)
    assert occ[("boxes", "night")] == (40.0, 30 * 600.0)
    assert occ[("boxes", "morning")] == (60.0, 30 * 420.0)
    ratio = {(o.pool, o.shift): o.ratio for o in m.occupancy}
    assert ratio[("medicos", "morning")] == 50 / 840
    assert len(m.occupancy) == 9


def test_ocupacion_por_turno_recorta_a_la_ventana(center):
    # Ventana [600, 1440]: la noche es solo [1320, 1440) y la mañana [600, 900).
    events = build(SHIFT_CHANGE, quick(0, 440.0, (450.0, 500.0)), quick(1, 470.0, (490.0, 700.0)))

    m = metrics_of(events, center, 600.0, DAY, DAY)

    occ = {(o.pool, o.shift): (o.busy_area, o.staff_area) for o in m.occupancy}
    assert occ[("medicos", "night")] == (0.0, 240.0)
    assert occ[("medicos", "morning")] == (100.0, 600.0)  # Y 600-700, plantilla 2·300


# --- Ley de Little ----------------------------------------------------------------------


def laws_of(events, start, end, horizon):
    table = episode_table(events)
    return {law.name: law for law in little_laws(table, step_curves(events, horizon), start, end)}


def test_little_exacta_sin_recortes(two_patients):
    # Todos llegan y salen dentro de [0, H]: L·T = suma de las estancias, sin bordes.
    laws = laws_of(two_patients, 0.0, DAY, DAY)

    assert set(laws) == {"system", "triage_queue", "box_queue"}
    system = laws["system"]
    assert (system.l, system.lam, system.w) == pytest.approx((145 / DAY, 2 / DAY, 72.5))
    assert system.relative_error < 1e-12
    assert laws["triage_queue"].w == 2.5
    assert laws["triage_queue"].relative_error < 1e-12
    assert laws["box_queue"].relative_error == 0.0  # nadie espera box: 0 frente a 0


def test_little_de_la_cola_de_box_necesita_las_vueltas(displaced):
    # P espera box de 15 a 35 tras el desalojo: área 20 = 20 + 0 de espera total.
    box = laws_of(displaced, 0.0, DAY, DAY)["box_queue"]
    assert box.w == 10.0
    assert box.relative_error < 1e-12


def test_little_con_recorte_no_es_exacta():
    # L = 120/1440 frente a λ̂·W = (1/1440)·60: los bordes de la ventana cuentan.
    system = laws_of(build(*CROSSING), DAY, 2 * DAY, 2 * DAY)["system"]
    assert system.relative_error == pytest.approx(0.5)


# --- Identidad de utilización -------------------------------------------------------------
#
# Ventana [1440, 2880] y horizonte 2880. U: triaje 1390-1395, box 1395-1500, médico
# 1400-1500. V: triaje 2840-2845, box desde 2845 y médico desde 2850, abiertos al final.
#   Médicos: 60 (U, de 1440 a 1500) + 30 (V, hasta el horizonte) = 90.
#   Boxes: 60 + 35 = 95. Enfermeras: 5 (V).

U_V = (
    quick(0, 1390.0, (1400.0, 1500.0)),
    rows(
        1,
        (2840.0, "patient_arrived", {}),
        (2840.0, "patient_registered", {}),
        (2840.0, "triage_started", {}),
        (2845.0, "triage_completed", {"nivel": 3}),
        (2845.0, "box_assigned", {"box": 2}),
        assessment(2850.0, 2),
    ),
)


def test_intervalos_de_servicio():
    intervals = busy_intervals(build(*U_V), horizon=2 * DAY)
    assert intervals["medicos"] == [(1400.0, 1500.0), (2850.0, 2 * DAY)]
    assert intervals["boxes"] == [(1395.0, 1500.0), (2845.0, 2 * DAY)]
    assert intervals["enfermeria_triaje"] == [(1390.0, 1395.0), (2840.0, 2845.0)]


def test_intervalos_de_box_con_desalojo(displaced):
    assert busy_intervals(displaced, horizon=DAY)["boxes"] == [
        (5.0, 15.0),
        (15.0, 35.0),
        (35.0, 50.0),
    ]


def identities_of(events, start, end, horizon):
    curves = step_curves(events, horizon)
    return {u.pool: u for u in utilization_identities(events, curves, start, end)}


def test_identidad_de_utilizacion_con_recortes():
    ids = identities_of(build(*U_V), DAY, 2 * DAY, 2 * DAY)

    assert (ids["medicos"].curve_area, ids["medicos"].interval_area) == (90.0, 90.0)
    assert (ids["boxes"].curve_area, ids["boxes"].interval_area) == (95.0, 95.0)
    assert (ids["enfermeria_triaje"].curve_area, ids["enfermeria_triaje"].interval_area) == (5, 5)
    assert all(u.relative_error == 0.0 for u in ids.values())


def test_identidad_detecta_un_recorte_mal_hecho(monkeypatch):
    # La versión incorrecta no recorta por la izquierda: U cuenta 100 en vez de 60.
    monkeypatch.setattr(
        analysis, "time_in_window", lambda start, end, w0, w1: max(0.0, min(end, w1) - start)
    )
    ids = identities_of(build(*U_V), DAY, 2 * DAY, 2 * DAY)
    assert (ids["medicos"].curve_area, ids["medicos"].interval_area) == (90.0, 130.0)
    assert ids["medicos"].relative_error > 0.3


# --- Todo junto ---------------------------------------------------------------------------


def test_analyze_run_usa_la_ventana_de_los_dias(center):
    run = analyze_run(build(*CROSSING), center, days=2, warmup_days=1)

    assert (run.metrics.start, run.metrics.end) == (DAY, 2 * DAY)
    assert run.curves.horizon == 2 * DAY
    assert len(run.table) == 2
    assert {law.name for law in run.little} == {"system", "triage_queue", "box_queue"}
    assert {u.pool for u in run.utilization} == {"enfermeria_triaje", "medicos", "boxes"}


@pytest.mark.parametrize(("start", "end"), [(-1.0, DAY), (DAY, DAY), (0.0, 2 * DAY)])
def test_ventana_invalida(two_patients, center, start, end):
    with pytest.raises(ValueError, match="start"):
        metrics_of(two_patients, center, start, end, DAY)


# --- Medias por hora y por día ----------------------------------------------------------


def staircase(values_by_hour, days):
    """Curvas a mano: el censo vale ``values_by_hour[h]`` en la hora h de cada día."""
    times = np.arange(days * 24, dtype=float) * 60
    census = np.tile(np.asarray(values_by_hour, dtype=np.int64), days)
    values = {name: np.zeros_like(census) for name in CURVES} | {"census": census}
    return StepCurves(times=times, values=MappingProxyType(values), horizon=days * DAY)


def test_medias_horarias_por_dia():
    hourly = list(range(24))
    curves = staircase(hourly, 3)
    means = analysis.hourly_means_by_day(curves, "census", DAY, 3 * DAY)
    assert means.shape == (2, 24)
    assert means.tolist() == [hourly, hourly]


def test_medias_horarias_con_un_cambio_dentro_de_la_hora():
    # Censo 0 hasta las 0:30 y 2 después: la hora 0 tiene media 1.
    values = {name: np.zeros(2, dtype=np.int64) for name in CURVES}
    values["census"] = np.array([0, 2])
    curves = StepCurves(np.array([0.0, 30.0]), MappingProxyType(values), DAY)
    means = analysis.hourly_means_by_day(curves, "census", 0.0, DAY)
    assert means[0, 0] == 1.0 and means[0, 1] == 2.0


def test_medias_horarias_exigen_dias_enteros():
    curves = staircase(range(24), 2)
    with pytest.raises(ValueError, match="whole days"):
        analysis.hourly_means_by_day(curves, "census", 60.0, DAY)


def test_medias_diarias():
    curves = staircase([0] * 12 + [4] * 12, 3)
    assert analysis.daily_means(curves, "census", 1, 3).tolist() == [2.0, 2.0]


# --- Esperas emparejadas ------------------------------------------------------------------


def test_esperas_emparejadas_por_episodio(two_patients):
    # La misma tabla con B sin espera de médico: diferencia 0 para A y -10 para B.
    base = episode_table(two_patients)
    better = (base[0], dataclasses.replace(base[1], doctor_wait=0.0))
    paired = analysis.paired_waits(base, better, "doctor_wait", 0.0, DAY)
    assert paired.episode_ids == ("EP-000000", "EP-000001")
    assert paired.levels.tolist() == [3, 4]
    assert paired.difference.tolist() == [0.0, -10.0]


def test_esperas_emparejadas_saltan_al_que_sigue_dentro(two_patients):
    # En la otra ejecución B sigue dentro: se empareja solo A, aunque B vaya primero.
    base = episode_table(two_patients)
    other = (dataclasses.replace(base[1], departure=None, doctor_wait=None), base[0])
    paired = analysis.paired_waits(base, other, "stay", 0.0, DAY)
    assert paired.episode_ids == ("EP-000000",)
    assert paired.base.tolist() == paired.other.tolist() == [100.0]


def test_esperas_emparejadas_cuando_el_primero_sigue_dentro(two_patients):
    # A sigue dentro en la base: B, el segundo de la base, se empareja con B y no con
    # el primero completado de la otra ejecución (que es A).
    base = episode_table(two_patients)
    first_inside = (dataclasses.replace(base[0], departure=None, doctor_wait=None), base[1])
    paired = analysis.paired_waits(first_inside, base, "stay", 0.0, DAY)
    assert paired.episode_ids == ("EP-000001",)
    assert paired.base.tolist() == paired.other.tolist() == [base[1].stay]


def test_esperas_emparejadas_exigen_los_mismos_pacientes(two_patients):
    base = episode_table(two_patients)
    moved = (base[0], dataclasses.replace(base[1], arrival=106.0))
    with pytest.raises(ValueError, match="same patients"):
        analysis.paired_waits(base, moved, "stay", 0.0, DAY)
    with pytest.raises(ValueError, match="measure"):
        analysis.paired_waits(base, base, "espera", 0.0, DAY)
