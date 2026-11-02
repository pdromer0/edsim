"""Recorrido de un episodio y Gantt de boxes y médicos.

Los instantes salen de los escenarios a mano de test_priority.py, ya comprobados allí:
el de tres boxes y el del desalojo durante las pruebas.
"""

import dataclasses
from pathlib import Path

import pytest

from edsim.arrivals.profile import load_profile
from edsim.engine.analysis import step_curves
from edsim.engine.center import load_center
from edsim.engine.engine import simulate_ed
from edsim.engine.events import MemorySink
from edsim.engine.scenarios import Scenario, hand_draws, run_scenario, three_boxes
from edsim.engine.timeline import STATES, Bar, Segment, episode_timeline, gantt

DATA = Path(__file__).parent / "data"
DAY = 1440.0


@pytest.fixture(scope="module")
def center():
    return load_center(DATA / "centro_ejemplo.toml")


@pytest.fixture(scope="module")
def three(center):
    return run_scenario(three_boxes(center)).events


@pytest.fixture(scope="module")
def real_run(center):
    sink = MemorySink()
    profile = load_profile(DATA / "llegadas_ejemplo.toml")
    simulate_ed(center, profile, 2, 2026, sink=sink, warmup_days=1)
    return sink.events


# --- Recorrido de un episodio --------------------------------------------------------


def test_recorrido_del_desalojado(three):
    # P3: triaje 2-7, box y médico en 7, desalojado en 20, box 1 en 65, sale en 92.
    assert episode_timeline(three, "EP-000002", DAY) == (
        Segment("triage", 2.0, 7.0),
        Segment("assessment", 7.0, 20.0),
        Segment("waiting_box", 20.0, 65.0),
        Segment("assessment", 65.0, 92.0),
    )


def test_recorrido_con_espera_de_box(three):
    # P4: triaje 10-15, espera box hasta 50, valoración 50-70.
    assert episode_timeline(three, "EP-000003", DAY) == (
        Segment("triage", 10.0, 15.0),
        Segment("waiting_box", 15.0, 50.0),
        Segment("assessment", 50.0, 70.0),
    )


def test_recorrido_con_pruebas_fuera_del_box(center):
    # Un box. A se valora 5-25 y pide pruebas (resultado en 85); L lo desaloja en 30 y
    # sale en 90. Los resultados llegan con A esperando box: un solo tramo 30-90.
    one_box = dataclasses.replace(center, boxes=1)
    s = Scenario(
        one_box, ((0.0, hand_draws(3, 5, 20, needs_tests=True)), (25.0, hand_draws(1, 5, 60)))
    )
    events = run_scenario(s).events
    assert episode_timeline(events, "EP-000000", DAY) == (
        Segment("triage", 0.0, 5.0),
        Segment("assessment", 5.0, 25.0),
        Segment("tests", 25.0, 30.0),
        Segment("waiting_box", 30.0, 90.0),
        Segment("reassessment", 90.0, 100.0),
    )
    # L no espera enfermera: su triaje va de 25 a 30.
    assert episode_timeline(events, "EP-000001", DAY)[0] == Segment("triage", 25.0, 30.0)


def test_recorrido_con_espera_de_triaje_y_de_medico(center):
    # Una enfermera y un médico: B espera triaje 1-5 y médico 10-25.
    small = dataclasses.replace(center, triage_nurses=(1, 1, 1), doctors=(1, 1, 1))
    s = Scenario(small, ((0.0, hand_draws(3, 5, 20)), (1.0, hand_draws(4, 5, 10))))
    events = run_scenario(s).events
    assert episode_timeline(events, "EP-000001", DAY) == (
        Segment("waiting_triage", 1.0, 5.0),
        Segment("triage", 5.0, 10.0),
        Segment("waiting_doctor", 10.0, 25.0),
        Segment("assessment", 25.0, 35.0),
    )


def test_recorrido_cortado_por_el_horizonte(real_run):
    inside = [
        e.episode_id
        for e in real_run
        if e.event_type == "patient_arrived"
        and not any(
            x.episode_id == e.episode_id and x.event_type == "patient_departed" for x in real_run
        )
    ]
    segments = episode_timeline(real_run, inside[-1], 2 * DAY)
    assert segments[-1].end == 2 * DAY
    assert all(s.state in STATES for s in segments)
    assert all(a.end == b.start for a, b in zip(segments, segments[1:], strict=False))


def test_episodio_que_no_esta(three):
    with pytest.raises(ValueError, match="EP-000099"):
        episode_timeline(three, "EP-000099", DAY)


# --- Gantt ---------------------------------------------------------------------------


def test_gantt_de_tres_boxes(three):
    g = gantt(three, 0.0, 100.0)
    assert {
        box: [(b.start, b.end, b.episode_id) for b in bars] for box, bars in g.boxes.items()
    } == {
        1: [(5.0, 65.0, "EP-000000"), (65.0, 92.0, "EP-000002")],
        2: [(6.0, 66.0, "EP-000001")],
        3: [(7.0, 20.0, "EP-000002"), (20.0, 50.0, "EP-000004"), (50.0, 70.0, "EP-000003")],
    }
    assert g.boxes[3][1].level == 1 and g.boxes[3][1].tipo is None


def test_gantt_carriles_de_medico_en_tres_boxes(three):
    # P3 termina (cortada) en 20 y P5 empieza en 20: comparten carril. En 65 P1 libera
    # el carril 0 y P3 reanuda en él: nunca hay más de 3 valoraciones a la vez.
    g = gantt(three, 0.0, 100.0)
    lanes = [[(b.episode_id, b.start, b.end, b.interrupted) for b in lane] for lane in g.doctors]
    assert lanes == [
        [("EP-000000", 5.0, 65.0, False), ("EP-000002", 65.0, 92.0, False)],
        [("EP-000001", 6.0, 66.0, False)],
        [
            ("EP-000002", 7.0, 20.0, True),
            ("EP-000004", 20.0, 50.0, False),
            ("EP-000003", 50.0, 70.0, False),
        ],
    ]


def test_gantt_recorta_al_tramo(three):
    g = gantt(three, 30.0, 60.0)
    assert [(b.start, b.end) for b in g.boxes[3]] == [(30.0, 50.0), (50.0, 60.0)]
    assert g.boxes[1] == (Bar(30.0, 60.0, "EP-000000", 3),)
    assert all(b.start >= 30.0 and b.end <= 60.0 for lane in g.doctors for b in lane)


def no_overlaps(bars):
    ordered = sorted(bars, key=lambda b: b.start)
    return all(a.end <= b.start for a, b in zip(ordered, ordered[1:], strict=False))


def test_gantt_de_una_manana_real(real_run):
    start, end = DAY + 8 * 60, DAY + 15 * 60
    g = gantt(real_run, start, end)
    assert all(no_overlaps(bars) for bars in g.boxes.values())
    assert all(no_overlaps(lane) for lane in g.doctors)
    # Tantos carriles como el máximo de médicos ocupados en el tramo.
    curves = step_curves(real_run, 2 * DAY)
    inside = (curves.times >= start) & (curves.times < end)
    busy = list(curves["doctors_busy"][inside]) + [curves.value("doctors_busy", start)]
    assert len(g.doctors) == max(busy)
    assert gantt(real_run, start, end) == g  # determinista


def test_gantt_tramo_vacio(three):
    with pytest.raises(ValueError, match="start < end"):
        gantt(three, 10.0, 10.0)
