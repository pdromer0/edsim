"""Escenarios didácticos: el de tres boxes y el triaje exponencial.

Los instantes del escenario de tres boxes se comprueban en test_priority.py, que lo
usa; aquí, lo que el escenario es: determinista, con los sorteos de cada llegada y
con el centro reducido que necesita.
"""

import math
from pathlib import Path

import numpy as np
import pytest

from edsim.arrivals.thinning import ArrivalRecord
from edsim.engine.center import load_center
from edsim.engine.clinical import ProvisionalSampler
from edsim.engine.scenarios import (
    THREE_BOXES_PATIENTS,
    exponential_triage,
    hand_draws,
    run_scenario,
    three_boxes,
)
from edsim.engine.validation import flat_profile, mg1_center, pollaczek_khinchine
from edsim.seeds import child_streams

EXAMPLE = Path(__file__).parent / "data" / "centro_ejemplo.toml"


@pytest.fixture(scope="module")
def center():
    return load_center(EXAMPLE)


def test_sorteos_a_mano_por_defecto():
    d = hand_draws(2, 5, 20)
    assert (d.level, d.triage_time, d.assessment_time) == (2, 5, 20)
    assert (d.reassessment_time, d.needs_tests, d.test_turnaround, d.admitted) == (
        10.0,
        False,
        60.0,
        False,
    )
    assert hand_draws(1, 5, 30, admitted=True).admitted


def test_tres_boxes_reduce_el_centro(center):
    s = three_boxes(center)
    assert s.center.boxes == 3 and s.center.triage_nurses == (3, 3, 3)
    assert s.center.doctors == center.doctors
    assert s.days == 1
    assert [a.time for a in s.arrivals] == [0.0, 1.0, 2.0, 10.0, 15.0]
    assert [a.arrival_id for a in s.arrivals] == list(range(5))
    # El muestreador devuelve los sorteos de cada llegada, por su número.
    assert s.sampler(ArrivalRecord(4, 15.0)) == THREE_BOXES_PATIENTS[4][1]
    assert [d.level for _, d in THREE_BOXES_PATIENTS] == [3, 4, 5, 2, 1]


def test_tres_boxes_es_determinista(center):
    a, b = run_scenario(three_boxes(center)), run_scenario(three_boxes(center))
    assert a.events == b.events
    assert a.run.inside == 0
    assert sum(e.event_type == "patient_displaced" for e in a.events) == 1


def test_triaje_exponencial_solo_cambia_el_triaje(center):
    c = mg1_center(center)
    factory = exponential_triage(c)
    seed = np.random.SeedSequence(5)
    sampler = factory(seed)
    base = ProvisionalSampler(c, child_streams(seed, 6)[1:5])
    arrival = ArrivalRecord(0, 0.0)
    triages = []
    for _ in range(20_000):
        got, expected = sampler(arrival), base(arrival)
        assert got.level == expected.level
        assert got.assessment_time == expected.assessment_time
        assert got.needs_tests == expected.needs_tests
        triages.append(got.triage_time)
    triages = np.array(triages)
    mean = pollaczek_khinchine(c, flat_profile()).mean_service
    # Exponencial: media la de la lognormal y CV 1 (error típico de la media ≈ 0,7 %).
    assert triages.mean() == pytest.approx(mean, rel=0.03)
    assert triages.std() / triages.mean() == pytest.approx(1.0, rel=0.03)
    assert not math.isclose(triages.std() / triages.mean(), 0.57, rel_tol=0.1)


def test_triaje_exponencial_reproducible(center):
    factory = exponential_triage(mg1_center(center))
    one, two = factory(np.random.SeedSequence(5)), factory(np.random.SeedSequence(5))
    arrival = ArrivalRecord(0, 0.0)
    assert [one(arrival) for _ in range(5)] == [two(arrival) for _ in range(5)]
