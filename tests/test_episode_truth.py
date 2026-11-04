"""Exact CSV round trips and comparisons of complete or censored stages."""

import csv
from dataclasses import replace

import pytest
from test_episode_segments import INTERRUPTED, TESTS_IN_QUEUE, trace_events
from test_episode_segments import real_episode_run as real_episode_run

from edsim.engine.engine import simulate_ed
from edsim.engine.events import MemorySink
from edsim.runs import (
    TRUTH_ABS_TOL_MINUTES,
    EpisodeTruth,
    RunReadError,
    build_episode_event_index,
    compare_episode_truth,
    episode_segments,
    load_center,
    load_profile,
    read_episode_events,
    read_run_episode_truth,
)


def truth_for_interrupted(**changes):
    return replace(EpisodeTruth("EP-000000", 0, 0, 3, 3, 17, 10, False, 60, False), **changes)


def comparisons(trace, horizon, truth):
    events = trace_events(trace)
    return {
        row.field: row
        for row in compare_episode_truth(events, episode_segments(events, horizon), truth)
    }


def test_interrupted_assessment_compares_sum_of_all_segments():
    rows = comparisons(INTERRUPTED, 60, truth_for_interrupted())
    assert rows["assessment_time"].observed == 17
    assert {row.status for row in rows.values()} == {"match", "unused"}
    assert rows["reassessment_time"].status == rows["test_turnaround"].status == "unused"


def test_test_turnaround_includes_time_outside_box():
    truth = truth_for_interrupted(
        triage_time=5, assessment_time=20, needs_tests=True, admitted=True
    )
    rows = comparisons(TESTS_IN_QUEUE, 120, truth)
    assert all(row.status == "match" for row in rows.values())
    assert rows["test_turnaround"].observed == 60


def test_partial_assessment_after_displacement_sums_past_and_current_work():
    rows = comparisons(INTERRUPTED[:10], 40, truth_for_interrupted())
    assert rows["assessment_time"].observed == 14
    assert rows["assessment_time"].drawn == 17
    assert rows["assessment_time"].status == "partial"
    assert rows["triage_time"].status == "match"
    assert rows["destination"].status == "pending"


def test_interrupted_reassessment_compares_all_its_segments():
    trace = TESTS_IN_QUEUE[:11] + (
        ("assessment_ended", 100, {"tipo": "reevaluacion", "interrumpida": True}),
        ("patient_displaced", 100, {"box": 2, "desalojado_por": "EP-000001"}),
        ("box_assigned", 110, {"box": 3}),
        ("assessment_started", 115, {"tipo": "reevaluacion", "pool": "medicos", "box": 3}),
        ("assessment_ended", 120, {"tipo": "reevaluacion", "interrumpida": False}),
        ("disposition_decided", 120, {"destino": "ingreso"}),
        ("patient_departed", 120, {"destino": "ingreso"}),
    )
    truth = truth_for_interrupted(
        triage_time=5, assessment_time=20, needs_tests=True, admitted=True
    )
    rows = comparisons(trace, 140, truth)
    assert rows["reassessment_time"].observed == 10
    assert all(row.status == "match" for row in rows.values())


def test_waiting_tests_has_partial_lab_and_pending_reassessment():
    truth = truth_for_interrupted(triage_time=5, assessment_time=20, needs_tests=True)
    rows = comparisons(TESTS_IN_QUEUE[:8], 60, truth)
    assert rows["test_turnaround"].observed == 35
    assert rows["test_turnaround"].status == "partial"
    assert rows["reassessment_time"].observed is None
    assert rows["reassessment_time"].status == "pending"


def test_level_is_pending_until_triage_and_destination_until_decision():
    rows = comparisons(INTERRUPTED[:3], 4, truth_for_interrupted())
    assert rows["level"].status == rows["assessment_time"].status == "pending"
    assert rows["triage_time"].observed == 2 and rows["triage_time"].status == "partial"
    rows = comparisons(INTERRUPTED[:-1], 43, truth_for_interrupted())
    assert rows["destination"].status == "match"


def test_fixed_tolerance_detects_real_differences_and_partial_excess():
    assert TRUTH_ABS_TOL_MINUTES == 1e-8
    near = comparisons(INTERRUPTED, 60, truth_for_interrupted(assessment_time=17 + 0.5e-8))
    wrong = comparisons(INTERRUPTED, 60, truth_for_interrupted(assessment_time=17 + 1e-5))
    excess = comparisons(INTERRUPTED[:10], 40, truth_for_interrupted(assessment_time=13))
    assert near["assessment_time"].status == "match"
    assert wrong["assessment_time"].status == excess["assessment_time"].status == "mismatch"
    wrong = comparisons(INTERRUPTED, 60, truth_for_interrupted(level=2, admitted=True))
    assert wrong["level"].status == wrong["destination"].status == "mismatch"


def test_csv_round_trip_preserves_every_draw_bit_for_bit(real_episode_run):
    store, result, _ = real_episode_run
    expected = simulate_ed(
        load_center(store.root / "sample" / "centro.toml"),
        load_profile(store.root / "sample" / "llegadas.toml"),
        2,
        7,
        sink=MemorySink(),
        warmup_days=1,
    ).ground_truth.episodes
    actual = read_run_episode_truth(store, "sample")
    assert tuple(actual.values()) == expected
    assert any(truth.needs_tests for truth in actual.values())
    assert any(not truth.needs_tests for truth in actual.values())
    assert all(
        type(truth.needs_tests) is bool and type(truth.admitted) is bool
        for truth in actual.values()
    )
    assert len(actual) == len(result.analysis.table) > 0
    with pytest.raises(TypeError):
        actual["new"] = expected[0]


def test_every_real_complete_stage_matches_and_partial_work_is_bounded(real_episode_run):
    store, result, _ = real_episode_run
    truth = read_run_episode_truth(store, "sample")
    index = build_episode_event_index(store, "sample")
    counts = {"finished": 0, "unfinished": 0, "partial": 0, "match": 0}
    for record in result.analysis.table:
        events = read_episode_events(store, "sample", record.episode_id, index)
        segments = episode_segments(events, result.analysis.curves.horizon)
        rows = compare_episode_truth(events, segments, truth[record.episode_id])
        if record.departure is not None:
            counts["finished"] += 1
            assert all(row.status in {"match", "unused"} for row in rows)
        else:
            counts["unfinished"] += 1
            assert all(row.status != "mismatch" for row in rows)
        for row in rows:
            if row.status == "partial":
                counts["partial"] += 1
                assert 0 <= row.observed <= row.drawn + TRUTH_ABS_TOL_MINUTES
            elif row.status == "match":
                counts["match"] += 1
    assert all(count > 0 for count in counts.values())


@pytest.fixture
def truth_copy(real_episode_run, tmp_path):
    import shutil

    from edsim.runs import RunStore

    store, _, _ = real_episode_run
    shutil.copytree(store.root / "sample", tmp_path / "sample")
    return RunStore(tmp_path), tmp_path / "sample" / "ground_truth_episodios.csv"


@pytest.mark.parametrize(
    "column,value",
    [
        ("nivel", "6"),
        ("nivel", "true"),
        ("pruebas", "0"),
        ("pruebas", "false"),
        ("destino", "urgencias"),
        ("triaje", "nan"),
        ("valoracion", "inf"),
        ("reevaluacion", "-1"),
        ("minuto_llegada", "3000"),
        ("episodio", "EP-999999"),
        ("run_id", "other"),
        ("semilla", "42"),
    ],
)
def test_invalid_csv_values_keep_filename_and_line(truth_copy, column, value):
    store, path = truth_copy
    with path.open(newline="") as source:
        reader = csv.DictReader(source)
        fields, rows = reader.fieldnames, list(reader)
    rows[0][column] = value
    with path.open("w", newline="") as destination:
        writer = csv.DictWriter(destination, fields)
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(RunReadError) as caught:
        read_run_episode_truth(store, "sample")
    assert str(caught.value).startswith(f"{path}:2:")


@pytest.mark.parametrize("kind", ["header", "missing", "extra", "duplicate", "encoding"])
def test_csv_structure_failures(truth_copy, kind):
    store, path = truth_copy
    rows = path.read_bytes().splitlines(keepends=True)
    if kind == "header":
        rows[0] = b"bad,header\n"
    elif kind == "missing":
        rows[1] = b"EP-000000\n"
    elif kind == "extra":
        rows[1] = rows[1].rstrip() + b",extra\n"
    elif kind == "duplicate":
        rows.insert(2, rows[1])
    else:
        rows[1] = b"\xff\n"
    path.write_bytes(b"".join(rows))
    with pytest.raises(RunReadError, match="ground_truth_episodios.csv"):
        read_run_episode_truth(store, "sample")
