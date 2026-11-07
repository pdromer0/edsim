"""Hand-built logs distinguish arrivals, completed patients and time averages."""

import dataclasses

import numpy as np
import pytest
from test_invariants import build, journey

from edsim.engine.analysis import episode_table, step_curves, window_metrics
from edsim.engine.center import load_center
from edsim.runs import window_compliance, window_kpis

DAY = 1440


def patient(number, arrival, door, stay, *, level=2, displacements=0, admitted=False):
    """Build milestone events; displacement events test folding, not invariants."""
    rows = [
        (arrival, number, "patient_arrived", {}),
        (arrival, number, "triage_started", {"circuito": "enfermeria"}),
        (arrival, number, "triage_completed", {"nivel": level}),
        (arrival, number, "box_assigned", {"box": 1}),
        (
            arrival + door,
            number,
            "assessment_started",
            {"tipo": "inicial", "pool": "medicos", "box": 1},
        ),
    ]
    for index in range(displacements):
        time = arrival + door + 1 + index * 2
        rows += [
            (time, number, "patient_displaced", {"box": 1, "desalojado_por": "EP-000099"}),
            (time + 1, number, "box_assigned", {"box": 1}),
        ]
    if stay is not None:
        destination = "ingreso" if admitted else "alta"
        rows.append((arrival + stay, number, "patient_departed", {"destino": destination}))
    return rows


@pytest.fixture
def sample():
    events = build(
        patient(0, 1400, 10, 80, displacements=3),  # warmup: contributes 40 census-minutes
        patient(1, 1500, 10, 30, displacements=2, admitted=True),
        patient(2, 1560, 20, 90),
        patient(3, 2900, 0, 20, level=1, displacements=1),
        patient(4, 3000, 5, None, displacements=4),
        patient(5, 4320, 0, None),  # right edge: not an arrival in the window
    )
    table = episode_table(events)
    center = load_center("tests/data/centro_ejemplo.toml")
    metrics = window_metrics(table, step_curves(events, 4320), center, DAY, 3 * DAY)
    return table, metrics


def test_kpis_have_hand_calculated_populations_units_and_percentiles(sample):
    table, metrics = sample
    kpis = window_kpis(table, metrics)
    assert kpis.n == 3
    assert kpis.arrivals_per_day == 2  # four arrivals in two days, one unfinished
    assert kpis.census_mean == pytest.approx(1500 / 2880)
    assert kpis.stay_mean == pytest.approx(140 / 3)
    assert kpis.stay_p90 == 78
    assert kpis.door_to_doctor_mean == 10
    assert kpis.door_to_doctor_p90 == 18
    assert (kpis.displaced_episodes, kpis.total_displacements) == (2, 3)
    assert kpis.admission_share == pytest.approx(1 / 3)


def test_no_completed_patients_keeps_time_values_and_zero_counts():
    events = build(journey(0, 100, tests=False)[:3])
    table = episode_table(events)
    center = load_center("tests/data/centro_ejemplo.toml")
    metrics = window_metrics(table, step_curves(events, DAY), center, 0, DAY)
    kpis = window_kpis(table, metrics)
    assert kpis.n == kpis.displaced_episodes == kpis.total_displacements == 0
    assert kpis.arrivals_per_day == 1
    assert kpis.census_mean == pytest.approx(1340 / DAY)
    for field in (
        "stay_mean",
        "stay_p90",
        "door_to_doctor_mean",
        "door_to_doctor_p90",
        "admission_share",
    ):
        assert getattr(kpis, field) is None


def test_manchester_integer_counts_exact_threshold_immediate_and_weighted_days(sample):
    table, _ = sample
    # Add a second day with fewer level-2 patients: patient shares and day shares differ.
    extra = dataclasses.replace(table[2], episode_id="EP-000010", arrival=3000, door_to_doctor=10)
    immediate_late = dataclasses.replace(table[3], episode_id="EP-000011", door_to_doctor=0.001)
    # The sample sets door_to_doctor by hand: clock A, explicit since task 4.9.
    result = window_compliance((*table, extra, immediate_late), 1, 3, measure="door_to_doctor")
    immediate, level2, *empty = result.by_level
    assert (immediate.n, immediate.exceeded, immediate.exceeded_share) == (2, 1, 0.5)
    assert (level2.n, level2.exceeded, level2.exceeded_share) == (3, 1, 1 / 3)
    assert level2.share_out == 0.5  # first day fails, second day complies
    for index, level in enumerate(result.by_level):
        assert type(level.exceeded) is int
        if level.n:
            within = np.nansum(result.daily.n[:, index] * result.daily.within[:, index])
            assert level.exceeded_share == pytest.approx(1 - within / level.n)
        else:
            assert level.exceeded == 0
            assert level.exceeded_share is level.share_out is None
    assert len(empty) == 3


def test_manchester_of_runs_uses_classified_to_doctor_by_default():
    # Level 2 (maximum 10): arrives 1500, triage 1502-1507, doctor at 1512. Clock A is
    # 12 (exceeded), clock C only 5. Since task 4.9 the default is clock C; clock A is
    # still available explicitly.
    events = build(
        [
            (1500, 0, "patient_arrived", {}),
            (1502, 0, "triage_started", {"circuito": "enfermeria"}),
            (1507, 0, "triage_completed", {"nivel": 2}),
            (1507, 0, "box_assigned", {"box": 1}),
            (1512, 0, "assessment_started", {"tipo": "inicial", "pool": "medicos", "box": 1}),
            (1600, 0, "patient_departed", {"destino": "alta"}),
        ]
    )
    result = window_compliance(episode_table(events), 1, 2)
    assert result.daily.measure == "classified_to_doctor"
    level_2 = result.by_level[1]
    assert (level_2.n, level_2.exceeded, level_2.share_out) == (1, 0, 0.0)
    clock_a = window_compliance(episode_table(events), 1, 2, measure="door_to_doctor")
    level_2 = clock_a.by_level[1]
    assert (level_2.n, level_2.exceeded, level_2.share_out) == (1, 1, 1.0)


def test_public_exports():
    import edsim.runs as runs

    for name in (
        "WindowKPIs",
        "LevelCompliance",
        "WindowCompliance",
        "window_kpis",
        "window_compliance",
    ):
        assert name in runs.__all__
