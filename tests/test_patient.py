"""El paciente como proceso SimPy, con pools FIFO: escenarios a mano.

Llegadas fijas y un muestreador inyectado que devuelve sorteos elegidos a mano, así
que cada instante del log se calcula de antemano. Los pools son los del centro de
ejemplo (3 enfermeras, 12 médicos y 30 boxes) salvo donde se reducen a propósito.
"""

import dataclasses
from datetime import date
from pathlib import Path

import pytest
import simpy

from edsim.arrivals.thinning import ArrivalRecord
from edsim.engine.center import CenterConfig, load_center
from edsim.engine.clinical import PatientDraws
from edsim.engine.engine import EngineRun, run_engine
from edsim.engine.events import Event, EventLog, MemorySink
from edsim.engine.ground_truth import EpisodeTruth, GroundTruth
from edsim.engine.invariants import check_invariants
from edsim.engine.resources import BoxNumbers, make_pools

EXAMPLE = Path(__file__).parent / "data" / "centro_ejemplo.toml"
START = date(2026, 1, 5)

WITH_TESTS = PatientDraws(
    level=5,
    triage_time=5.0,
    assessment_time=20.0,
    reassessment_time=10.0,
    needs_tests=True,
    test_turnaround=60.0,
    admitted=False,
)
WITHOUT_TESTS = dataclasses.replace(WITH_TESTS, level=2, needs_tests=False, admitted=True)


@pytest.fixture(scope="module")
def center() -> CenterConfig:
    return load_center(EXAMPLE)


def simulate(
    center: CenterConfig, patients: list[tuple[float, PatientDraws]], days: int = 1
) -> tuple[list[Event], EngineRun, list[int]]:
    """Motor con llegadas fijas: eventos, resultado y llamadas al muestreador."""
    arrivals = [ArrivalRecord(i, t) for i, (t, _) in enumerate(patients)]
    calls: list[int] = []

    def sampler(arrival: ArrivalRecord) -> PatientDraws:
        calls.append(arrival.arrival_id)
        return patients[arrival.arrival_id][1]

    sink = MemorySink()
    run = run_engine(center, arrivals, sampler, EventLog("rtest", START, sink), days)
    return sink.events, run, calls


def trace(events: list[Event], arrival_id: int | None = None) -> list[tuple]:
    """(tipo, instante, payload) de los eventos, de un episodio o de todos."""
    episode = None if arrival_id is None else f"EP-{arrival_id:06d}"
    return [
        (e.event_type, e.sim_time, dict(e.payload))
        for e in events
        if episode is None or e.episode_id == episode
    ]


def assert_valid(events: list[Event], center: CenterConfig, run: EngineRun) -> None:
    truth = GroundTruth(episodes=run.episodes, days=())
    assert check_invariants(events, center, ground_truth=truth, inside=run.inside) == []


# --- Números de box ---------------------------------------------------------------


def test_box_mas_bajo_libre():
    boxes = BoxNumbers(3)

    assert [boxes.take(), boxes.take()] == [1, 2]
    boxes.give(1)
    assert boxes.take() == 1
    assert boxes.take() == 3


def test_box_devuelto_en_cualquier_orden():
    boxes = BoxNumbers(4)
    taken = [boxes.take() for _ in range(4)]
    for box in (3, 1, 4):
        boxes.give(box)

    assert taken == [1, 2, 3, 4]
    assert [boxes.take() for _ in range(3)] == [1, 3, 4]


def test_sin_boxes_libres():
    boxes = BoxNumbers(1)
    boxes.take()

    with pytest.raises(RuntimeError, match="no free box"):
        boxes.take()


@pytest.mark.parametrize("box", [0, 3, 1])
def test_devolver_un_box_no_ocupado(box):
    boxes = BoxNumbers(2)  # el 1 y el 2 están libres

    with pytest.raises(RuntimeError, match=f"box {box}"):
        boxes.give(box)


def test_pools_con_la_capacidad_maxima(center):
    pools = make_pools(simpy.Environment(), center)

    assert pools.nurses.capacity == 3
    assert pools.doctors.capacity == 12
    assert pools.boxes.capacity == 30
    assert [pools.box_numbers.take() for _ in range(30)] == list(range(1, 31))


# --- Un paciente solo ---------------------------------------------------------------


def test_paciente_con_pruebas(center):
    # Llega en el 10; triaje 10-15; box y valoración 15-35; pruebas 35-95;
    # reevaluación 95-105; decisión y salida en el 105.
    events, run, _ = simulate(center, [(10.0, WITH_TESTS)])

    assert trace(events) == [
        ("patient_arrived", 10.0, {}),
        ("patient_registered", 10.0, {}),
        ("triage_started", 10.0, {}),
        ("triage_completed", 15.0, {"nivel": 5}),
        ("box_assigned", 15.0, {"box": 1}),
        ("assessment_started", 15.0, {"tipo": "inicial", "pool": "medicos", "box": 1}),
        ("assessment_ended", 35.0, {"tipo": "inicial", "interrumpida": False}),
        ("test_ordered", 35.0, {}),
        ("test_resulted", 95.0, {}),
        ("assessment_started", 95.0, {"tipo": "reevaluacion", "pool": "medicos", "box": 1}),
        ("assessment_ended", 105.0, {"tipo": "reevaluacion", "interrumpida": False}),
        ("disposition_decided", 105.0, {"destino": "alta"}),
        ("patient_departed", 105.0, {"destino": "alta"}),
    ]
    assert {e.episode_id for e in events} == {"EP-000000"}
    assert run.inside == 0
    assert_valid(events, center, run)


def test_paciente_sin_pruebas(center):
    events, run, _ = simulate(center, [(10.0, WITHOUT_TESTS)])

    assert trace(events) == [
        ("patient_arrived", 10.0, {}),
        ("patient_registered", 10.0, {}),
        ("triage_started", 10.0, {}),
        ("triage_completed", 15.0, {"nivel": 2}),
        ("box_assigned", 15.0, {"box": 1}),
        ("assessment_started", 15.0, {"tipo": "inicial", "pool": "medicos", "box": 1}),
        ("assessment_ended", 35.0, {"tipo": "inicial", "interrumpida": False}),
        ("disposition_decided", 35.0, {"destino": "ingreso"}),
        ("patient_departed", 35.0, {"destino": "ingreso"}),
    ]
    assert_valid(events, center, run)


def test_ground_truth_y_muestreador_en_orden_de_llegada(center):
    patients = [(10.0, WITH_TESTS), (12.0, WITHOUT_TESTS), (12.0, WITH_TESTS)]

    _, run, calls = simulate(center, patients)

    assert calls == [0, 1, 2]
    assert run.episodes == tuple(
        EpisodeTruth.from_draws(ArrivalRecord(i, t), d) for i, (t, d) in enumerate(patients)
    )


# --- Recursos retenidos en tramos distintos ----------------------------------------


def test_dos_pacientes_y_un_solo_box(center):
    # A ocupa el box de 15 a 105. B termina el triaje en 17 y espera el box hasta 105:
    # lo recibe en el mismo instante en que sale A, y después en el log.
    one_box = dataclasses.replace(center, boxes=1)

    events, run, _ = simulate(one_box, [(10.0, WITH_TESTS), (12.0, WITHOUT_TESTS)])

    b = trace(events, 1)
    assert b[3] == ("triage_completed", 17.0, {"nivel": 2})
    assert b[4] == ("box_assigned", 105.0, {"box": 1})
    assert b[-1] == ("patient_departed", 125.0, {"destino": "ingreso"})
    types = [(e.episode_id, e.event_type) for e in events]
    assert types.index(("EP-000001", "box_assigned")) == (
        types.index(("EP-000000", "patient_departed")) + 1
    )
    assert_valid(events, one_box, run)


def test_medico_libre_durante_las_pruebas(center):
    # Un solo médico. A lo usa de 15 a 35 y espera pruebas hasta 95 en su box;
    # B llega en 40 y es valorado de 45 a 65 sin esperar, en el box 2.
    one_doctor = dataclasses.replace(center, doctors=(1, 1, 1))

    events, run, _ = simulate(one_doctor, [(10.0, WITH_TESTS), (40.0, WITHOUT_TESTS)])

    b = trace(events, 1)
    assert b[4] == ("box_assigned", 45.0, {"box": 2})
    assert b[5] == ("assessment_started", 45.0, {"tipo": "inicial", "pool": "medicos", "box": 2})
    assert b[-1][:2] == ("patient_departed", 65.0)
    assert trace(events, 0)[-1][:2] == ("patient_departed", 105.0)
    assert_valid(events, one_doctor, run)


def test_espera_de_medico_y_box_retenido(center):
    # Un médico y dos boxes. B llega en 12, tiene box en 17 y espera al médico
    # hasta que A termina su valoración en 35, sin soltar el box.
    one_doctor = dataclasses.replace(center, doctors=(1, 1, 1))

    events, run, _ = simulate(one_doctor, [(10.0, WITH_TESTS), (12.0, WITHOUT_TESTS)])

    b = trace(events, 1)
    assert b[4] == ("box_assigned", 17.0, {"box": 2})
    assert b[5][:2] == ("assessment_started", 35.0)
    # A pide la reevaluación en 95, con el médico libre desde 55.
    assert trace(events, 0)[9][:2] == ("assessment_started", 95.0)
    assert_valid(events, one_doctor, run)


def test_cola_de_triaje_fifo(center):
    # Una enfermera: B y C esperan por orden de llegada.
    one_nurse = dataclasses.replace(center, triage_nurses=(1, 1, 1))
    patients = [(10.0, WITHOUT_TESTS), (11.0, WITHOUT_TESTS), (12.0, WITHOUT_TESTS)]

    events, run, _ = simulate(one_nurse, patients)

    starts = [(e.episode_id, e.sim_time) for e in events if e.event_type == "triage_started"]
    assert starts == [("EP-000000", 10.0), ("EP-000001", 15.0), ("EP-000002", 20.0)]
    assert_valid(events, one_nurse, run)


# --- Horizonte ----------------------------------------------------------------------


def test_nada_en_el_instante_del_horizonte(center):
    # Llega en 1435 y su triaje terminaría en 1440 = 1 día: no ocurre.
    events, run, _ = simulate(center, [(1435.0, WITH_TESTS)], days=1)

    assert trace(events) == [
        ("patient_arrived", 1435.0, {}),
        ("patient_registered", 1435.0, {}),
        ("triage_started", 1435.0, {}),
    ]
    assert run.inside == 1
    assert len(run.episodes) == 1
    assert_valid(events, center, run)


def test_pacientes_dentro_al_final(center):
    patients = [(10.0, WITHOUT_TESTS), (1400.0, WITH_TESTS), (1430.0, WITHOUT_TESTS)]

    events, run, _ = simulate(center, patients, days=1)

    departed = {e.episode_id for e in events if e.event_type == "patient_departed"}
    assert departed == {"EP-000000"}
    assert run.inside == 2
    assert all(e.sim_time < 1440 for e in events)
    assert_valid(events, center, run)


def test_dias_no_validos(center):
    with pytest.raises(ValueError, match="days"):
        simulate(center, [(10.0, WITH_TESTS)], days=0)
