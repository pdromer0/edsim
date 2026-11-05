"""Nivel 1 en la puerta (decisión candidata 39): escenario a mano con las enfermeras ocupadas.

Centro de ejemplo con 3 enfermeras y 4 médicos en todos los turnos y 30 boxes:

- A, B y C (nivel 4) llegan en 0: triaje 0-10, boxes 2, 3 y 4 en 10, valoración 10-30.
- D y E (nivel 3) llegan en 1 y 2: esperan enfermera hasta 10, triaje 10-15, boxes 5 y
  6 en 15, esperan médico hasta 30 (cuatro médicos: F y A, B, C) y se valoran 30-50.
- F (nivel 1) llega en 3, detrás de D y E, con las tres enfermeras ocupadas: se
  clasifica en la puerta en 3 (triaje de duración 0, circuito "puerta"), toma el box 1
  y se valora 3-33. Su triaje sorteado (5 minutos) no se usa.

Relojes (A / B / C): F 0 / 0 / 0; D 29 / 20 / 15; E 28 / 20 / 15; A 10 / 10 / 0.
"""

import dataclasses

import pytest
from test_patient import EXAMPLE, WITHOUT_TESTS, assert_valid, simulate, trace

from edsim.engine.analysis import busy_intervals, episode_table, step_curves
from edsim.engine.center import load_center
from edsim.engine.events import DOOR, NURSE

LEVEL_4 = dataclasses.replace(WITHOUT_TESTS, level=4, triage_time=10.0, admitted=False)
LEVEL_3 = dataclasses.replace(WITHOUT_TESTS, level=3, triage_time=5.0, admitted=False)
LEVEL_1 = dataclasses.replace(WITHOUT_TESTS, level=1, triage_time=5.0, assessment_time=30.0)

PATIENTS = [
    (0.0, LEVEL_4),  # A, EP-000000
    (0.0, LEVEL_4),  # B, EP-000001
    (0.0, LEVEL_4),  # C, EP-000002
    (1.0, LEVEL_3),  # D, EP-000003
    (2.0, LEVEL_3),  # E, EP-000004
    (3.0, LEVEL_1),  # F, EP-000005
]
F = 5

ALTA = {"destino": "alta"}
INGRESO = {"destino": "ingreso"}


def started(box: int) -> dict:
    return {"tipo": "inicial", "pool": "medicos", "box": box}


def ended() -> dict:
    return {"tipo": "inicial", "interrumpida": False}


@pytest.fixture(scope="module")
def door_run():
    small = dataclasses.replace(
        load_center(EXAMPLE), triage_nurses=(3, 3, 3), doctors=(4, 4, 4), boxes=30
    )
    events, run, _ = simulate(small, PATIENTS)
    return events, run, small


def test_el_escenario_tiene_un_nivel_1_con_las_enfermeras_llenas(door_run):
    # Lo que se prueba ocurre de verdad: hay un nivel 1 y, cuando llega, las tres
    # enfermeras de la plantilla vigente están ocupadas.
    events, _, _ = door_run
    levels = {
        e.episode_id: e.payload["nivel"] for e in events if e.event_type == "triage_completed"
    }
    assert levels["EP-000005"] == 1
    curves = step_curves(events, 1440.0)
    assert curves.value("nurses_busy", 3.0) == curves.value("nurses_staff", 3.0) == 3


def test_el_nivel_1_se_clasifica_en_la_puerta(door_run):
    events, _, _ = door_run
    assert trace(events, F) == [
        ("patient_arrived", 3.0, {}),
        ("patient_registered", 3.0, {}),
        ("triage_started", 3.0, {"circuito": DOOR}),
        ("triage_completed", 3.0, {"nivel": 1}),
        ("box_assigned", 3.0, {"box": 1}),
        ("assessment_started", 3.0, started(1)),
        ("assessment_ended", 33.0, ended()),
        ("disposition_decided", 33.0, INGRESO),
        ("patient_departed", 33.0, INGRESO),
    ]


def test_los_demas_siguen_en_la_cola_de_enfermeria(door_run):
    events, _, _ = door_run
    assert trace(events, 3) == [
        ("patient_arrived", 1.0, {}),
        ("patient_registered", 1.0, {}),
        ("triage_started", 10.0, {"circuito": NURSE}),
        ("triage_completed", 15.0, {"nivel": 3}),
        ("box_assigned", 15.0, {"box": 5}),
        ("assessment_started", 30.0, started(5)),
        ("assessment_ended", 50.0, ended()),
        ("disposition_decided", 50.0, ALTA),
        ("patient_departed", 50.0, ALTA),
    ]
    starts = {e.episode_id: e.sim_time for e in events if e.event_type == "triage_started"}
    assert starts == {
        "EP-000000": 0.0,
        "EP-000001": 0.0,
        "EP-000002": 0.0,
        "EP-000003": 10.0,
        "EP-000004": 10.0,
        "EP-000005": 3.0,
    }
    boxes = {e.episode_id: e.payload["box"] for e in events if e.event_type == "box_assigned"}
    assert boxes == {
        "EP-000005": 1,
        "EP-000000": 2,
        "EP-000001": 3,
        "EP-000002": 4,
        "EP-000003": 5,
        "EP-000004": 6,
    }


def test_tres_relojes_del_escenario(door_run):
    events, _, _ = door_run
    clocks = {
        e.episode_id: (
            e.triage_wait,
            e.door_to_doctor,
            e.triage_start_to_doctor,
            e.classified_to_doctor,
        )
        for e in episode_table(events)
    }
    assert clocks["EP-000005"] == (0.0, 0.0, 0.0, 0.0)  # F
    assert clocks["EP-000003"] == (9.0, 29.0, 20.0, 15.0)  # D
    assert clocks["EP-000004"] == (8.0, 28.0, 20.0, 15.0)  # E
    assert clocks["EP-000000"] == (0.0, 10.0, 10.0, 0.0)  # A


def test_sin_invariantes_violadas(door_run):
    # check_capacity no cuenta el triaje de puerta: con él serían 4 enfermeras ocupadas.
    events, run, small = door_run
    assert_valid(events, small, run)


def test_el_triaje_de_puerta_no_ocupa_enfermera(door_run):
    events, _, _ = door_run
    triages = busy_intervals(events, 1440.0)["enfermeria_triaje"]
    assert sorted(triages) == [(0.0, 10.0)] * 3 + [(10.0, 15.0)] * 2
