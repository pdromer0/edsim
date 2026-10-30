"""Prioridad (nivel, llegada) y desalojo del nivel 1 con reanudación: escenarios a mano.

Llegadas fijas y sorteos elegidos a mano, como en test_patient.py, así que cada
instante del log se calcula de antemano. El centro de ejemplo tiene 3 enfermeras, 12
médicos y 30 boxes; cada escenario reduce lo que necesita.
"""

import dataclasses
from datetime import date
from pathlib import Path

import pytest
import simpy

from edsim.arrivals.profile import load_profile
from edsim.arrivals.thinning import ArrivalRecord
from edsim.engine.center import CenterConfig, load_center
from edsim.engine.clinical import PatientDraws
from edsim.engine.engine import EngineRun, run_engine, simulate_ed
from edsim.engine.events import Event, EventLog, MemorySink
from edsim.engine.ground_truth import GroundTruth
from edsim.engine.invariants import check_invariants
from edsim.engine.resources import BoxNumbers, Holder, priority_key, should_displace

DATA = Path(__file__).parent / "data"
START = date(2026, 1, 5)


@pytest.fixture(scope="module")
def center() -> CenterConfig:
    return load_center(DATA / "centro_ejemplo.toml")


def draws(level: int, triage: float, assessment: float, **kwargs) -> PatientDraws:
    """Sorteos a mano; sin pruebas y con alta salvo que se diga."""
    values = {
        "reassessment_time": 10.0,
        "needs_tests": False,
        "test_turnaround": 60.0,
        "admitted": False,
    } | kwargs
    return PatientDraws(level=level, triage_time=triage, assessment_time=assessment, **values)


def simulate(
    center: CenterConfig, patients: list[tuple[float, PatientDraws]], days: int = 1
) -> tuple[list[Event], EngineRun]:
    arrivals = [ArrivalRecord(i, t) for i, (t, _) in enumerate(patients)]
    sink = MemorySink()
    run = run_engine(
        center,
        arrivals,
        lambda arrival: patients[arrival.arrival_id][1],
        EventLog("rtest", START, sink),
        days,
    )
    return sink.events, run


def trace(events: list[Event], arrival_id: int) -> list[tuple]:
    episode = f"EP-{arrival_id:06d}"
    return [(e.event_type, e.sim_time, dict(e.payload)) for e in events if e.episode_id == episode]


def at(events: list[Event], time: float) -> list[tuple]:
    """(episodio, tipo, payload) de los eventos de un instante, en orden del fichero."""
    return [(e.episode_id, e.event_type, dict(e.payload)) for e in events if e.sim_time == time]


def assert_valid(events: list[Event], center: CenterConfig, run: EngineRun) -> None:
    truth = GroundTruth(episodes=run.episodes, days=())
    assert check_invariants(events, center, ground_truth=truth, inside=run.inside) == []


def started(tipo: str, box: int) -> dict:
    return {"tipo": tipo, "pool": "medicos", "box": box}


def ended(tipo: str, cut: bool = False) -> dict:
    return {"tipo": tipo, "interrumpida": cut}


ALTA = {"destino": "alta"}


# --- Piezas de resources.py ------------------------------------------------------------


def test_clave_de_prioridad():
    assert priority_key(3, 12.5) == (3, 12.5)
    assert priority_key(1, 900.0) < priority_key(2, 0.0) < priority_key(2, 0.5)


def test_solo_el_nivel_1_desaloja_y_solo_a_niveles_mayores():
    env = simpy.Environment()
    boxes = simpy.PreemptiveResource(env, capacity=2)
    assert not should_displace(boxes, 1)  # vacío: no hay a quién desalojar

    boxes.request(priority=(1, 0.0), preempt=False)
    assert not should_displace(boxes, 1)  # solo niveles 1 dentro

    boxes.request(priority=(4, 2.0), preempt=False)
    assert should_displace(boxes, 1)
    assert not should_displace(boxes, 2)


def test_box_traspasado_al_que_desaloja():
    boxes = BoxNumbers(3)
    env = simpy.Environment()
    victim, displacer, other = (
        Holder(env.event(), 0, 5),
        Holder(env.event(), 1, 1),
        Holder(env.event(), 2, 3),
    )
    assert [boxes.take(Holder(env.event(), 9, 3)), boxes.take(victim)] == [1, 2]
    boxes.give(1)

    boxes.hand_over(2, to=displacer.process)

    # El 1 está libre y es menor, pero el 2 es del que desaloja.
    assert boxes.holder(2) is None
    assert boxes.take(displacer) == 2
    assert boxes.holder(2) == displacer
    assert boxes.take(other) == 1


def test_no_se_traspasa_un_box_libre():
    boxes = BoxNumbers(2)

    with pytest.raises(RuntimeError, match="box 1"):
        boxes.hand_over(1, to=simpy.Environment().event())


# --- Escenario de tres boxes de la sesión conceptual ---------------------------------

# P1 nivel 3, P2 nivel 4 y P3 nivel 5 ocupan los tres boxes; P4 (nivel 2) espera; P5
# (nivel 1) desaloja a P3 en plena valoración. P4 recibe el box antes que P3, y P3
# reanuda con el tiempo que le faltaba.
THREE_BOXES = [
    (0.0, draws(3, 5, 60)),  # P1, EP-0: box 1 de 5 a 65
    (1.0, draws(4, 5, 60)),  # P2, EP-1: box 2 de 6 a 66
    (2.0, draws(5, 5, 40)),  # P3, EP-2: box 3 en 7, valoración 7-47
    (10.0, draws(2, 5, 20)),  # P4, EP-3: espera box desde 15
    (15.0, draws(1, 5, 30, admitted=True)),  # P5, EP-4: termina el triaje en 20
]


@pytest.fixture(scope="module")
def three_boxes(center):
    small = dataclasses.replace(center, boxes=3)
    events, run = simulate(small, THREE_BOXES)
    return events, run, small


def test_tres_boxes_desalojo_en_plena_valoracion(three_boxes):
    # En 20 los tres boxes tienen nivel > 1: P5 echa al de clave mayor, P3 (5, 2), que
    # lleva 13 de sus 40 minutos. Primero el desalojado, luego la concesión.
    events, _, _ = three_boxes

    assert at(events, 20.0) == [
        ("EP-000004", "triage_completed", {"nivel": 1}),
        ("EP-000002", "assessment_ended", ended("inicial", cut=True)),
        ("EP-000002", "patient_displaced", {"box": 3, "desalojado_por": "EP-000004"}),
        ("EP-000004", "box_assigned", {"box": 3}),
        ("EP-000004", "assessment_started", started("inicial", 3)),
    ]


def test_tres_boxes_p4_antes_que_p3(three_boxes):
    # P5 sale en 50: el box 3 va a P4 (2, 10), no a P3 (5, 2), que llegó antes.
    events, _, _ = three_boxes

    assert at(events, 50.0) == [
        ("EP-000004", "assessment_ended", ended("inicial")),
        ("EP-000004", "disposition_decided", {"destino": "ingreso"}),
        ("EP-000004", "patient_departed", {"destino": "ingreso"}),
        ("EP-000003", "box_assigned", {"box": 3}),
        ("EP-000003", "assessment_started", started("inicial", 3)),
    ]
    assert trace(events, 3)[-1] == ("patient_departed", 70.0, ALTA)


def test_tres_boxes_p3_reanuda_con_lo_que_le_faltaba(three_boxes):
    # P1 sale en 65 y P3 recibe el box 1: le faltaban 40 - 13 = 27 minutos, acaba en 92.
    events, run, small = three_boxes

    assert trace(events, 2) == [
        ("patient_arrived", 2.0, {}),
        ("patient_registered", 2.0, {}),
        ("triage_started", 2.0, {}),
        ("triage_completed", 7.0, {"nivel": 5}),
        ("box_assigned", 7.0, {"box": 3}),
        ("assessment_started", 7.0, started("inicial", 3)),
        ("assessment_ended", 20.0, ended("inicial", cut=True)),
        ("patient_displaced", 20.0, {"box": 3, "desalojado_por": "EP-000004"}),
        ("box_assigned", 65.0, {"box": 1}),
        ("assessment_started", 65.0, started("inicial", 1)),
        ("assessment_ended", 92.0, ended("inicial")),
        ("disposition_decided", 92.0, ALTA),
        ("patient_departed", 92.0, ALTA),
    ]
    assert [e.sim_time for e in events if e.event_type == "patient_departed"] == [
        50.0,
        65.0,
        66.0,
        70.0,
        92.0,
    ]
    assert run.inside == 0
    assert_valid(events, small, run)


# --- Desalojo en cada etapa ----------------------------------------------------------


def test_desalojo_durante_las_pruebas(center):
    # Un box. A valorado de 5 a 25 pide pruebas (resultado en 85). L (nivel 1) lo
    # desaloja en 30 y sale en 90. El resultado llega en 85, con A esperando box; al
    # recuperarlo en 90 pasa directo a la reevaluación (90-100).
    one_box = dataclasses.replace(center, boxes=1)
    patients = [
        (0.0, draws(3, 5, 20, needs_tests=True)),
        (25.0, draws(1, 5, 60)),
    ]

    events, run = simulate(one_box, patients)

    assert trace(events, 0)[4:] == [
        ("box_assigned", 5.0, {"box": 1}),
        ("assessment_started", 5.0, started("inicial", 1)),
        ("assessment_ended", 25.0, ended("inicial")),
        ("test_ordered", 25.0, {}),
        ("patient_displaced", 30.0, {"box": 1, "desalojado_por": "EP-000001"}),
        ("test_resulted", 85.0, {}),
        ("box_assigned", 90.0, {"box": 1}),
        ("assessment_started", 90.0, started("reevaluacion", 1)),
        ("assessment_ended", 100.0, ended("reevaluacion")),
        ("disposition_decided", 100.0, ALTA),
        ("patient_departed", 100.0, ALTA),
    ]
    assert_valid(events, one_box, run)


def test_desalojo_esperando_medico(center):
    # Dos boxes y un médico. B (nivel 4) se valora de 5 a 45. A (nivel 5) tiene el box 2
    # en 6 y espera médico. L (nivel 1) termina el triaje en 10 y echa a A, la clave
    # mayor: A cancela su petición de médico sin valorarse. En 45, el médico va a L
    # (45-75) y el box 1 de B a A, que espera médico hasta 75 y se valora de 75 a 95.
    small = dataclasses.replace(center, boxes=2, doctors=(1, 1, 1))
    patients = [
        (0.0, draws(4, 5, 40)),
        (1.0, draws(5, 5, 20)),
        (5.0, draws(1, 5, 30)),
    ]

    events, run = simulate(small, patients)

    assert trace(events, 1)[4:] == [
        ("box_assigned", 6.0, {"box": 2}),
        ("patient_displaced", 10.0, {"box": 2, "desalojado_por": "EP-000002"}),
        ("box_assigned", 45.0, {"box": 1}),
        ("assessment_started", 75.0, started("inicial", 1)),
        ("assessment_ended", 95.0, ended("inicial")),
        ("disposition_decided", 95.0, ALTA),
        ("patient_departed", 95.0, ALTA),
    ]
    assert trace(events, 2)[4:6] == [
        ("box_assigned", 10.0, {"box": 2}),
        ("assessment_started", 45.0, started("inicial", 2)),
    ]
    assert_valid(events, small, run)


def test_dos_desalojos_del_mismo_paciente(center):
    # Un box. A (nivel 3) se valora desde 5 (40 minutos). L1 lo echa en 12 (faltan 33)
    # y sale en 32; A vuelve en 32 y L2 lo echa en 40 (faltan 25); L2 sale en 60 y A
    # termina en 85.
    one_box = dataclasses.replace(center, boxes=1)
    patients = [
        (0.0, draws(3, 5, 40)),
        (7.0, draws(1, 5, 20)),
        (35.0, draws(1, 5, 20)),
    ]

    events, run = simulate(one_box, patients)

    assert trace(events, 0)[4:] == [
        ("box_assigned", 5.0, {"box": 1}),
        ("assessment_started", 5.0, started("inicial", 1)),
        ("assessment_ended", 12.0, ended("inicial", cut=True)),
        ("patient_displaced", 12.0, {"box": 1, "desalojado_por": "EP-000001"}),
        ("box_assigned", 32.0, {"box": 1}),
        ("assessment_started", 32.0, started("inicial", 1)),
        ("assessment_ended", 40.0, ended("inicial", cut=True)),
        ("patient_displaced", 40.0, {"box": 1, "desalojado_por": "EP-000002"}),
        ("box_assigned", 60.0, {"box": 1}),
        ("assessment_started", 60.0, started("inicial", 1)),
        ("assessment_ended", 85.0, ended("inicial")),
        ("disposition_decided", 85.0, ALTA),
        ("patient_departed", 85.0, ALTA),
    ]
    assert_valid(events, one_box, run)


def test_un_nivel_1_no_desaloja_a_otro(center):
    # Un box. L1b llega en 1, termina el triaje en 3 y ocupa el box hasta 33. L1a llegó
    # antes (0) pero termina el triaje en 10: su clave es menor, y aun así espera.
    one_box = dataclasses.replace(center, boxes=1)
    patients = [
        (0.0, draws(1, 10, 20)),
        (1.0, draws(1, 2, 30)),
    ]

    events, run = simulate(one_box, patients)

    assert not any(e.event_type == "patient_displaced" for e in events)
    assert trace(events, 1)[4][:2] == ("box_assigned", 3.0)
    assert trace(events, 0)[4][:2] == ("box_assigned", 33.0)
    assert_valid(events, one_box, run)


# --- Orden de llegada dentro del nivel ---------------------------------------------------

# Cuatro pacientes de nivel 4. P0 termina el triaje en 1 y retiene el recurso hasta 21.
# Los demás terminan el triaje en orden inverso a su llegada (P3 en 4, P2 en 5, P1 en
# 11), pero lo reciben por orden de llegada: P1 en 21, P2 en 41 y P3 en 61.
SAME_LEVEL = [
    (0.0, draws(4, 1, 20)),
    (1.0, draws(4, 10, 20)),
    (2.0, draws(4, 3, 20)),
    (3.0, draws(4, 1, 20)),
]


@pytest.mark.parametrize(
    ("resource", "event_type", "change"),
    [
        ("boxes", "box_assigned", {"boxes": 1}),
        ("médicos", "assessment_started", {"doctors": (1, 1, 1)}),
    ],
)
def test_mismo_nivel_por_orden_de_llegada(center, resource, event_type, change):
    small = dataclasses.replace(center, **change)

    events, run = simulate(small, SAME_LEVEL)

    starts = [(e.episode_id, e.sim_time) for e in events if e.event_type == event_type]
    assert starts == [
        ("EP-000000", 1.0),
        ("EP-000001", 21.0),
        ("EP-000002", 41.0),
        ("EP-000003", 61.0),
    ], resource
    assert_valid(events, small, run)


# --- Sin nivel 1 ----------------------------------------------------------------------


def test_sin_nivel_1_ningun_desalojo(center):
    # Pocos boxes para que haya colas de box: sin nivel 1 en el reparto, nadie desaloja.
    no_level1 = dataclasses.replace(center, boxes=12, level_shares=(0.0, 25.0, 25.0, 25.0, 25.0))
    profile = load_profile(DATA / "llegadas_ejemplo.toml")
    sink = MemorySink()

    result = simulate_ed(no_level1, profile, 3, 2026, sink=sink)

    events = sink.events
    assert not any(e.event_type == "patient_displaced" for e in events)
    waits = [e for e in events if e.event_type == "box_assigned"]
    triaged = {e.episode_id: e.sim_time for e in events if e.event_type == "triage_completed"}
    assert any(e.sim_time > triaged[e.episode_id] for e in waits)  # hubo colas de box
    assert (
        check_invariants(events, no_level1, ground_truth=result.ground_truth, inside=result.inside)
        == []
    )
