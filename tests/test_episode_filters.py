"""Strict filters with known outcomes, censored bounds and exclusive cohorts."""

from dataclasses import replace

import pytest
from test_episode_segments import INTERRUPTED, trace_events

from edsim.engine.analysis import episode_table
from edsim.runs import EpisodeFilters, episode_observed_time, episode_period, filter_episodes


@pytest.fixture
def records():
    base = episode_table(trace_events(INTERRUPTED))[0]
    return (
        base,
        replace(
            base,
            episode_id="EP-000001",
            arrival=1440,
            departure=1500,
            level=2,
            destination="ingreso",
            displacements=0,
            door_to_doctor=20,
        ),
        replace(
            base,
            episode_id="EP-000002",
            arrival=1400,
            departure=None,
            destination=None,
            level=None,
            door_to_doctor=None,
            displacements=0,
        ),
        replace(
            base,
            episode_id="EP-000003",
            arrival=1800,
            departure=None,
            destination=None,
            door_to_doctor=10,
        ),
    )


def apply(records, **filters):
    return filter_episodes(records, EpisodeFilters(**filters), warmup_end=1440, horizon=2880)


def test_periods_are_disjoint_and_cover_all_records(records):
    groups = {
        period: apply(records, period=period) for period in ("warmup", "window", "unfinished")
    }
    assert groups["warmup"] == records[:1]
    assert groups["window"] == records[1:2]
    assert groups["unfinished"] == records[2:]
    assert sum(map(len, groups.values())) == len(records)
    assert episode_period(records[2], 1440) == "unfinished"


def test_all_optional_filters_and_combinations_keep_arrival_order(records):
    assert apply(records) == records
    assert apply(records, level=2) == records[1:2]
    assert apply(records, destination="ingreso") == records[1:2]
    assert apply(records, displaced=True) == (records[0], records[3])
    assert apply(records, displaced=False) == records[1:3]
    assert apply(records, arrival_day=0) == (records[0], records[2])
    assert (
        apply(
            records, arrival_day=1, period="window", level=2, destination="ingreso", displaced=False
        )
        == records[1:2]
    )
    assert apply(records, level=5) == ()


def test_censored_stay_uses_strict_observed_lower_bound(records):
    assert apply(records, stay_gt=1200) == records[2:3]
    assert apply(records, stay_gt=1480) == ()
    assert apply(records, stay_gt=43) == records[1:]
    assert episode_observed_time(records[2], 2880) == 1480
    assert records[2].stay is None


def test_known_door_time_is_final_even_without_departure(records):
    assert apply(records, door_to_doctor_gt=15) == records[1:3]
    assert apply(records, door_to_doctor_gt=1480) == ()
    assert apply(records, door_to_doctor_gt=10) == records[1:3]
    assert records[3].departure is None and records[3].door_to_doctor == 10


@pytest.mark.parametrize(
    "values",
    [
        {"level": True},
        {"level": 6},
        {"displaced": 1},
        {"arrival_day": -1},
        {"period": "other"},
        {"destination": "other"},
        {"stay_gt": float("nan")},
        {"door_to_doctor_gt": -1},
        {"stay_gt": True},
    ],
)
def test_invalid_filter_values(values):
    with pytest.raises(ValueError):
        EpisodeFilters(**values)
