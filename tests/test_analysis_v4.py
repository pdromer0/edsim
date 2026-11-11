"""El análisis del log con la versión 4: abandono, espera de cama y pasillo (tarea 5.4).

Los escenarios M (abandono) y C (cama y pasillo) de `engine/scenarios.py` dan logs cuyos
instantes se calcularon a mano en la 5.1. Aquí se comprueba lo que el análisis saca de
ellos, con los valores del plan de la 5.4 (sección E): la tabla de episodios, las curvas
en cuatro instantes, sus áreas y las leyes operacionales exactas.
"""

from pathlib import Path

import pytest

from edsim.engine.analysis import (
    CURVES,
    OUTCOME_CURVES,
    busy_intervals,
    completed_in_window,
    ended_in_window,
    episode_table,
    little_laws,
    step_curves,
    utilization_identities,
)
from edsim.engine.center import load_center
from edsim.engine.scenarios import abandonment, admission, run_scenario

DATA = Path(__file__).parent / "data"
HORIZON = 1440.0


@pytest.fixture(scope="module")
def center():
    return load_center(DATA / "centro_ejemplo.toml")


@pytest.fixture(scope="module")
def log_c(center):
    return run_scenario(admission(center)).events


@pytest.fixture(scope="module")
def log_m(center):
    return run_scenario(abandonment(center)).events


def by_id(table):
    return {e.episode_id: e for e in table}


# --- La tabla de episodios ----------------------------------------------------------


def test_el_ingresado_del_pasillo_en_la_tabla(log_c):
    r1, r2, r3 = (by_id(episode_table(log_c))[f"EP-00000{i}"] for i in range(3))
    # R1: pide cama en 35 (al decidir el ingreso), R3 la desaloja en 60 y la cama llega en
    # 35 + 100 × 1,5 = 185, de noche.
    assert (r1.bed_requested, r1.bed_assigned, r1.bed_wait) == (35.0, 185.0, 150.0)
    assert r1.hallway and r1.displacements == 1
    assert (r1.departure, r1.destination, r1.stay) == (185.0, "ingreso", 185.0)
    # En el pasillo no espera box: su espera de box es la del triaje al box 1, 0.
    assert r1.box_wait == 0.0
    # R2 espera el box de 15 a 80; R3, nivel 1, lo recibe al desalojar.
    assert r2.box_wait == 65.0 and not r2.hallway and r2.bed_requested is None
    assert r3.box_wait == 0.0 and r3.left is None


def test_los_que_se_van_en_la_tabla(log_m):
    table = by_id(episode_table(log_m))
    q2, q4 = table["EP-000001"], table["EP-000003"]
    # Q2: clasificada de 1 a 6, box 2 en 6, se va en 26 esperando al médico.
    assert (q2.left, q2.left_from, q2.time_to_leave, q2.end) == (26.0, "medico", 25.0, 26.0)
    assert q2.departure is None and q2.stay is None and q2.destination is None
    # Sus relojes quedan vacíos; sus esperas son definitivas al irse.
    assert (q2.door_to_doctor, q2.triage_start_to_doctor, q2.classified_to_doctor) == (
        None,
        None,
        None,
    )
    assert (q2.box_wait, q2.doctor_wait, q2.results_box_wait) == (0.0, 20.0, 0.0)
    # Q4: llega en 3 y se va en 4 esperando enfermera, sin triaje ni nivel.
    assert (q4.left, q4.left_from, q4.level, q4.triage_wait) == (4.0, "triaje", None, None)
    assert q4.box_wait == 0.0


def test_terminados_frente_a_completados(log_m):
    table = episode_table(log_m)
    ended = {e.episode_id for e in ended_in_window(table, 0.0, HORIZON)}
    done = {e.episode_id for e in completed_in_window(table, 0.0, HORIZON)}
    assert done == {"EP-000000", "EP-000002"}
    assert ended == done | {"EP-000001", "EP-000003"}


# --- Las curvas (plan, sección E) ----------------------------------------------------


@pytest.mark.parametrize(
    ("t", "expected"),
    [
        (40.0, (1, 1, 0, 1, 2)),
        (70.0, (1, 0, 1, 1, 3)),
        (120.0, (0, 0, 1, 0, 1)),
        (185.0, (0, 0, 0, 0, 0)),
    ],
)
def test_curvas_del_escenario_c_en_cuatro_instantes(log_c, t, expected):
    curves = step_curves(log_c, HORIZON)
    names = ("boxes_busy", "boxes_waiting_bed", "hallway", "waiting_box", "census")
    assert tuple(curves.value(name, t) for name in names) == expected


def test_areas_del_escenario_c(log_c):
    curves = step_curves(log_c, HORIZON)
    assert curves.area("boxes_waiting_bed", 0.0, HORIZON) == 25.0  # de 35 a 60
    assert curves.area("hallway", 0.0, HORIZON) == 125.0  # de 60 a 185
    assert curves.area("boxes_busy", 0.0, HORIZON) == 55.0 + 20.0 + 20.0
    assert curves.area("census", 0.0, HORIZON) == 10 + 50 * 2 + 20 * 3 + 20 * 2 + 85
    assert curves.area("waiting_box", 0.0, HORIZON) == 65.0
    for name in CURVES + OUTCOME_CURVES:
        assert curves[name].min() >= 0, name


def test_curvas_del_abandono(log_m):
    curves = step_curves(log_m, HORIZON)
    # En 3 esperan enfermera Q3 (desde 2: Q1 y Q2 tienen las dos) y Q4; Q4 se va en 4 y
    # sale del censo y de la cola de triaje; Q3 empieza su triaje en 5.
    assert [curves.value("waiting_triage", t) for t in (3.0, 4.0, 5.0)] == [2, 1, 0]
    assert curves.value("census", 3.0) == 4 and curves.value("census", 4.0) == 3
    assert curves.value("boxes_busy", 25.0) == 2 and curves.value("boxes_busy", 26.0) == 2
    # En 26, Q2 libera el box 2 y Q3 lo recibe: el mismo instante, el total no cambia.
    assert curves.value("census", 65.0) == 0
    for name in CURVES + OUTCOME_CURVES:
        assert curves[name].min() >= 0, name


def test_las_curvas_de_la_cama_valen_0_sin_ingresos(log_m):
    curves = step_curves(log_m, HORIZON)
    assert all(not curves[name].any() for name in OUTCOME_CURVES)


def test_intervalos_del_box_de_quien_se_va(log_m):
    boxes = busy_intervals(log_m, HORIZON)["boxes"]
    assert (6.0, 26.0) in boxes  # Q2, del box 2 a su abandono


# --- Leyes exactas: nadie dentro en los bordes de [0, 1440] ------------------------


@pytest.mark.parametrize("scenario", ["log_c", "log_m"])
def test_little_y_utilizacion_exactas(scenario, request):
    events = request.getfixturevalue(scenario)
    table = episode_table(events)
    curves = step_curves(events, HORIZON)
    for law in little_laws(table, curves, 0.0, HORIZON):
        assert law.relative_error < 1e-12, law
    for identity in utilization_identities(events, curves, 0.0, HORIZON):
        assert identity.relative_error < 1e-12, identity


def test_little_del_sistema_con_los_que_se_van(log_m):
    # W cuenta a los cuatro: Q1 45, Q2 25, Q3 63 y Q4 1, con su tiempo hasta irse.
    table = episode_table(log_m)
    system = little_laws(table, step_curves(log_m, HORIZON), 0.0, HORIZON)[0]
    assert system.name == "system"
    assert system.w == pytest.approx((45 + 25 + 63 + 1) / 4, abs=1e-12)
