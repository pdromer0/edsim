"""Hand-written patient logs and a full real-run timeline comparison."""

from datetime import date

import pytest

from edsim.engine.events import EventLog, MemorySink, read_events
from edsim.engine.timeline import Segment, episode_timeline
from edsim.runs import (
    Displacement,
    EpisodeSegment,
    RunStore,
    build_episode_event_index,
    episode_segments,
    read_center_values,
    read_episode_events,
    read_run_results,
    simulate_run,
    write_variant,
)
from edsim.runs import TestBand as LabBand


def trace_events(trace):
    """Write one episode's explicitly chosen transitions in emission order."""
    sink = MemorySink()
    log = EventLog("sample", date(2026, 1, 5), sink)
    for event_type, minute, payload in trace:
        log.emit(event_type, minute, arrival_id=0, **payload)
    return tuple(sink.events)


INTERRUPTED = (
    ("patient_arrived", 0, {}),
    ("patient_registered", 0, {}),
    ("triage_started", 2, {}),
    ("triage_completed", 5, {"nivel": 3}),
    ("box_assigned", 8, {"box": 1}),
    ("assessment_started", 10, {"tipo": "inicial", "pool": "medicos", "box": 1}),
    ("assessment_ended", 17, {"tipo": "inicial", "interrumpida": True}),
    ("patient_displaced", 17, {"box": 1, "desalojado_por": "EP-000001"}),
    ("box_assigned", 30, {"box": 2}),
    ("assessment_started", 33, {"tipo": "inicial", "pool": "medicos", "box": 2}),
    ("assessment_ended", 43, {"tipo": "inicial", "interrumpida": False}),
    ("disposition_decided", 43, {"destino": "alta"}),
    ("patient_departed", 43, {"destino": "alta"}),
)

TESTS_IN_QUEUE = (
    ("patient_arrived", 0, {}),
    ("triage_started", 0, {}),
    ("triage_completed", 5, {"nivel": 3}),
    ("box_assigned", 5, {"box": 1}),
    ("assessment_started", 5, {"tipo": "inicial", "pool": "medicos", "box": 1}),
    ("assessment_ended", 25, {"tipo": "inicial", "interrumpida": False}),
    ("test_ordered", 25, {}),
    ("patient_displaced", 30, {"box": 1, "desalojado_por": "EP-000001"}),
    ("test_resulted", 85, {}),
    ("box_assigned", 90, {"box": 2}),
    ("assessment_started", 95, {"tipo": "reevaluacion", "pool": "medicos", "box": 2}),
    ("assessment_ended", 105, {"tipo": "reevaluacion", "interrumpida": False}),
    ("disposition_decided", 105, {"destino": "ingreso"}),
    ("patient_departed", 105, {"destino": "ingreso"}),
)


def test_interrupted_assessment_resumes_in_its_new_box():
    result = episode_segments(trace_events(INTERRUPTED), 60)
    assert result.segments == (
        EpisodeSegment("waiting_triage", 0, 2, None),
        EpisodeSegment("triage", 2, 5, None),
        EpisodeSegment("waiting_box", 5, 8, None),
        EpisodeSegment("waiting_doctor", 8, 10, 1),
        EpisodeSegment("assessment", 10, 17, 1),
        EpisodeSegment("waiting_box", 17, 30, None),
        EpisodeSegment("waiting_doctor", 30, 33, 2),
        EpisodeSegment("assessment", 33, 43, 2),
    )
    assert result.tests is None
    assert result.displacements == (Displacement(17, 1, "EP-000001"),)


def test_lab_result_in_box_queue_does_not_split_or_end_the_queue():
    result = episode_segments(trace_events(TESTS_IN_QUEUE), 120)
    assert result.segments == (
        EpisodeSegment("triage", 0, 5, None),
        EpisodeSegment("assessment", 5, 25, 1),
        EpisodeSegment("waiting_tests", 25, 30, 1),
        EpisodeSegment("waiting_box", 30, 90, None),
        EpisodeSegment("waiting_doctor", 90, 95, 2),
        EpisodeSegment("reassessment", 95, 105, 2),
    )
    assert result.tests == LabBand(25, 85, True)
    assert result.displacements == (Displacement(30, 1, "EP-000001"),)


def test_without_tests_has_no_lab_band_or_zero_duration_transitions():
    events = trace_events(
        INTERRUPTED[:6]
        + (
            ("assessment_ended", 20, {"tipo": "inicial", "interrumpida": False}),
            ("disposition_decided", 20, {"destino": "alta"}),
            ("patient_departed", 20, {"destino": "alta"}),
        )
    )
    result = episode_segments(events, 60)
    assert result.tests is None and not result.displacements
    assert all(segment.end > segment.start for segment in result.segments)
    assert sum(segment.end - segment.start for segment in result.segments) == 20


@pytest.mark.parametrize(
    "trace,horizon,last",
    [
        (INTERRUPTED[:10], 40, EpisodeSegment("assessment", 33, 40, 2)),
        (TESTS_IN_QUEUE[:8], 60, EpisodeSegment("waiting_box", 30, 60, None)),
        (TESTS_IN_QUEUE[:7], 60, EpisodeSegment("waiting_tests", 25, 60, 1)),
        (INTERRUPTED[:2], 1, EpisodeSegment("waiting_triage", 0, 1, None)),
    ],
)
def test_unfinished_state_ends_at_horizon(trace, horizon, last):
    result = episode_segments(trace_events(trace), horizon)
    assert result.segments[-1] == last
    assert sum(segment.end - segment.start for segment in result.segments) == horizon
    if any(event[0] == "test_ordered" for event in trace):
        assert result.tests == LabBand(25, horizon, False)


def test_displacement_while_waiting_doctor_and_immediate_reassignment():
    events = trace_events(
        INTERRUPTED[:5]
        + (
            ("patient_displaced", 9, {"box": 1, "desalojado_por": "EP-000001"}),
            ("box_assigned", 9, {"box": 2}),
        )
    )
    result = episode_segments(events, 12)
    assert result.segments[-2:] == (
        EpisodeSegment("waiting_doctor", 8, 9, 1),
        EpisodeSegment("waiting_doctor", 9, 12, 2),
    )
    assert all(segment.end > segment.start for segment in result.segments)


def test_unobserved_grant_changes_neither_box_wait_nor_displacements():
    # SimPy can grant then preempt before resumption; there are no emitted events.
    result = episode_segments(trace_events(INTERRUPTED[:4]), 20)
    assert result.segments[-1] == EpisodeSegment("waiting_box", 5, 20, None)
    assert result.displacements == ()


def test_arrival_at_horizon_has_no_positive_segments():
    assert episode_segments(trace_events(INTERRUPTED[:2]), 0).segments == ()


@pytest.mark.parametrize("horizon", [-1, float("inf"), float("nan"), True, 10])
def test_invalid_horizon(horizon):
    with pytest.raises(ValueError):
        episode_segments(trace_events(INTERRUPTED), horizon)


def test_rejects_empty_mixed_or_unordered_input():
    from dataclasses import replace

    events = trace_events(INTERRUPTED)
    for invalid in (
        (),
        events[1:],
        (events[0], replace(events[1], episode_id="EP-000001", patient_id="PT-000001")),
        (events[0], events[3], events[2]),
    ):
        with pytest.raises(ValueError):
            episode_segments(invalid, 60)


@pytest.fixture(scope="module")
def real_episode_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("episode-run")
    source = "tests/data/centro_ejemplo.toml"
    values = read_center_values(source)
    values["recursos.boxes"] = 2
    center = root / "constrained.toml"
    write_variant(source, values, center)
    simulation = simulate_run(
        str(center),
        "tests/data/llegadas_ejemplo.toml",
        2,
        7,
        output_dir=root / "sample",
        run_id="sample",
        warmup_days=1,
        origin="app",
    )
    store = RunStore(root)
    return store, read_run_results(store, "sample"), simulation


def test_all_real_episodes_cover_their_stay_and_match_engine_timeline(real_episode_run):
    import math

    store, result, _ = real_episode_run
    horizon = result.analysis.curves.horizon
    index = build_episode_event_index(store, "sample")
    events = tuple(read_events(store.root / "sample" / "eventos.jsonl"))
    assert any(record.departure is None for record in result.analysis.table)
    assert any(record.departure is not None for record in result.analysis.table)
    assert any(event.event_type == "test_ordered" for event in events)
    assert any(record.displacements for record in result.analysis.table)
    for record in result.analysis.table:
        own = read_episode_events(store, "sample", record.episode_id, index)
        actual = episode_segments(own, horizon)
        segments = actual.segments
        assert segments[0].start == record.arrival
        assert segments[-1].end == (horizon if record.departure is None else record.departure)
        assert all(segment.start < segment.end for segment in segments)
        assert all(a.end == b.start for a, b in zip(segments, segments[1:], strict=False))
        assert math.fsum(segment.end - segment.start for segment in segments) == pytest.approx(
            (horizon if record.departure is None else record.departure) - record.arrival,
            abs=1e-8,
            rel=0,
        )
        projected = []
        for segment in segments:
            in_box = segment.state in {
                "waiting_doctor",
                "assessment",
                "waiting_tests",
                "reassessment",
            }
            assert (segment.box is not None) == in_box
            state = "tests" if segment.state == "waiting_tests" else segment.state
            if projected and projected[-1].state == state:
                projected[-1] = Segment(state, projected[-1].start, segment.end)
            else:
                projected.append(Segment(state, segment.start, segment.end))
        assert tuple(projected) == episode_timeline(events, record.episode_id, horizon)
