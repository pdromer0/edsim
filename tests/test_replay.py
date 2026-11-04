"""Checkpoint reconstruction, exact boundaries and independent curve/card oracles."""

from collections import Counter
from dataclasses import FrozenInstanceError, replace
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pytest

from edsim.engine.events import EventLog, MemorySink, read_events, to_json
from edsim.runs import (
    RunReadError,
    RunStore,
    build_episode_event_index,
    build_replay_index,
    episode_segments,
    read_center_values,
    read_episode_events,
    read_replay_state,
    read_run_results,
    replay_counts,
    simulate_run,
    write_variant,
)
from edsim.runs.replay import _empty, _fold


@pytest.fixture(scope="module")
def replay_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("replay-run")
    source = "tests/data/centro_ejemplo.toml"
    values = read_center_values(source)
    values["recursos.boxes"] = 2
    values["recursos.enfermeria_triaje"] = [3, 3, 1]
    values["recursos.medicos"] = [12, 12, 1]
    center = root / "constrained.toml"
    write_variant(source, values, center)
    simulate_run(
        center,
        "tests/data/llegadas_ejemplo.toml",
        2,
        7,
        output_dir=root / "sample",
        run_id="sample",
        warmup_days=1,
        origin="app",
    )
    store = RunStore(root)
    result = read_run_results(store, "sample")
    events = tuple(read_events(root / "sample" / "eventos.jsonl"))
    return store, result, events


@pytest.fixture
def tiny_log(tmp_path, replay_run):
    root = tmp_path / "sample"
    root.mkdir()
    replace(replay_run[1].info, run_id="sample").write(root / "run.json")
    path = root / "eventos.jsonl"

    def write(trace, newline="\n", final=True):
        sink = MemorySink()
        log = EventLog("sample", date(2026, 1, 5), sink)
        for kind, t, arrival, payload in trace:
            log.emit(kind, t, arrival_id=arrival, **payload)
        events = tuple(sink.events)
        text = newline.join(to_json(e) for e in events) + (newline if final and events else "")
        path.write_bytes(text.encode())
        return RunStore(tmp_path), path, events

    return write


TRACE = (
    ("staffing_changed", 0, None, {"recurso": "medicos", "anterior": 0, "nueva": 2}),
    ("patient_arrived", 0, 0, {}),
    ("triage_started", 0, 0, {}),
    ("triage_completed", 5, 0, {"nivel": 3}),
    ("box_assigned", 5, 0, {"box": 1}),
    ("assessment_started", 5, 0, {"tipo": "inicial", "pool": "medicos", "box": 1}),
    ("assessment_ended", 25, 0, {"tipo": "inicial", "interrumpida": False}),
    ("test_ordered", 25, 0, {}),
    ("patient_displaced", 30, 0, {"box": 1, "desalojado_por": "EP-000001"}),
    ("test_resulted", 85, 0, {}),
    ("box_assigned", 90, 0, {"box": 2}),
    ("staffing_changed", 90, None, {"recurso": "medicos", "anterior": 2, "nueva": 1}),
    ("assessment_started", 95, 0, {"tipo": "reevaluacion", "pool": "medicos", "box": 2}),
    ("assessment_ended", 105, 0, {"tipo": "reevaluacion", "interrumpida": False}),
    ("disposition_decided", 105, 0, {"destino": "ingreso"}),
    ("patient_departed", 105, 0, {"destino": "ingreso"}),
    ("patient_arrived", 240, 1, {}),
)


def test_handwritten_states_expiry_empty_hours_and_horizon(tiny_log):
    store, path, events = tiny_log(TRACE)
    index = build_replay_index(store, "sample")

    def at(t):
        return read_replay_state(store, "sample", index, t)

    assert at(0).patients[0].state == "triage"
    assert at(0).patients[0].level is None
    assert at(25).patients[0].state == "waiting_tests"
    assert at(30).patients[0].state == "waiting_box"
    assert at(60).patients[0].tests_pending
    assert at(85).patients[0].state == "waiting_box"
    assert not at(85).patients[0].tests_pending
    assert at(90).patients[0].box == 2 and at(90).staff["medicos"] == 1
    assert at(89.999).displacements and not at(90).displacements
    assert not at(105).patients
    assert at(105).departures_by_destination == {"alta": 0, "ingreso": 1}
    assert at(164.999).departures and not at(165).departures
    assert at(239).last_events == events[1:16]
    assert at(240).patients[0].state == "waiting_triage"
    assert at(index.horizon).patients == at(240).patients
    assert at(index.horizon).last_events == events[-15:]
    assert index._checkpoints[2].offset == index._checkpoints[3].offset
    assert at(30) == at(30)  # Later reads did not mutate the checkpoint.
    with pytest.raises(FrozenInstanceError):
        index.horizon = 1
    with pytest.raises(TypeError):
        at(90).staff["medicos"] = 7


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("final", [True, False])
def test_binary_offsets_with_accents_and_line_endings(tiny_log, newline, final):
    store, path, events = tiny_log(TRACE, newline, final)
    events = (replace(events[0], event_id="acentos-á-é"), *events[1:])
    path.write_bytes(
        (newline.join(to_json(e) for e in events) + (newline if final and events else "")).encode()
    )
    index = build_replay_index(store, "sample")
    assert read_replay_state(store, "sample", index, 90).last_events == events[:12]
    checkpoint = index._checkpoints[1]
    assert path.read_bytes()[checkpoint.offset :].startswith(to_json(events[9]).encode())


@pytest.mark.parametrize("damage", [b"{bad}\n", b"\xff\n", b"\n"])
def test_read_errors_include_original_line(tiny_log, damage):
    store, path, events = tiny_log(TRACE)
    index = build_replay_index(store, "sample")
    offset = index._checkpoints[1].offset
    data = path.read_bytes()
    end = data.index(b"\n", offset) + 1
    # Preserve the size so that validation exercises the indexed line.
    raw = damage.rstrip(b"\n").ljust(end - offset - 1, b" ") + b"\n"
    path.write_bytes(data[:offset] + raw + data[end:])
    with pytest.raises(RunReadError, match=r"eventos.jsonl:10:"):
        read_replay_state(store, "sample", index, 85)
    with pytest.raises(RunReadError, match=r"eventos.jsonl:10:"):
        build_replay_index(store, "sample")


def test_index_checks_run_truncation_order_and_horizon(tiny_log):
    store, path, events = tiny_log(TRACE)
    index = build_replay_index(store, "sample")
    with pytest.raises(RunReadError, match="index belongs"):
        read_replay_state(store, "other", index, 0)
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(RunReadError, match="size has changed"):
        read_replay_state(store, "sample", index, 240)
    for bad in (replace(events[1], sim_time=4000), replace(events[1], run_id="other")):
        path.write_text("\n".join(to_json(e) for e in (events[0], bad, events[2])) + "\n")
        with pytest.raises(RunReadError, match="eventos.jsonl:2:"):
            build_replay_index(store, "sample")
    path.write_text("\n".join(to_json(e) for e in (events[1], events[4], events[2])) + "\n")
    with pytest.raises(RunReadError, match="eventos.jsonl:3:"):
        build_replay_index(store, "sample")


@pytest.mark.parametrize("t", [-1, float("inf"), float("nan"), True, 2881])
def test_invalid_times(tiny_log, t):
    store, _, _ = tiny_log(TRACE)
    with pytest.raises(ValueError):
        read_replay_state(store, "sample", build_replay_index(store, "sample"), t)


def test_hour_zero_horizon_events_and_empty_log(tiny_log):
    store, _, events = tiny_log((("patient_arrived", 2880, 0, {}),))
    index = build_replay_index(store, "sample")
    assert not read_replay_state(store, "sample", index, 2879).patients
    assert read_replay_state(store, "sample", index, 2880).patients[0].arrival == 2880
    store, _, _ = tiny_log(())
    index = build_replay_index(store, "sample")
    assert not read_replay_state(store, "sample", index, 2880).last_events


def test_reads_only_the_indexed_hour(tiny_log, monkeypatch):
    store, path, events = tiny_log(TRACE)
    index = build_replay_index(store, "sample")
    original = Path.open
    sources = []

    def spy_open(self, *args, **kwargs):
        source = original(self, *args, **kwargs)
        if self == path:
            spy = Mock(wraps=source)
            spy.__enter__ = Mock(return_value=spy)
            spy.__exit__ = Mock(side_effect=lambda *args: source.close())
            sources.append(spy)
            return spy
        return source

    monkeypatch.setattr(Path, "open", spy_open)
    read_replay_state(store, "sample", index, 119)
    assert sources[0].readline.call_count == 7
    sources[0].read.assert_not_called()
    assert sources[0].seek.call_args_list[1].args == (index._checkpoints[1].offset,)


def test_every_minute_matches_curves_full_fold_and_cards(replay_run):
    store, result, events = replay_run
    index = build_replay_index(store, "sample")
    horizon = int(index.horizon)
    assert any(e.event_type == "patient_displaced" for e in events)
    assert any(e.event_type == "test_resulted" for e in events)
    assert any(e.departure is None for e in result.analysis.table)
    seen_overstaff = False
    for t in range(horizon + 1):
        actual = read_replay_state(store, "sample", index, t)
        assert actual == _fold(_empty(), events, t)
        counts = replay_counts(result, t)
        states = Counter(p.state for p in actual.patients)
        assert len(actual.patients) == counts.census
        assert states["waiting_triage"] == counts.waiting_triage
        assert states["waiting_box"] == counts.waiting_box
        assert states["triage"] == counts.nurses_busy
        assert states["assessment"] + states["reassessment"] == counts.doctors_busy
        assert sum(p.box is not None for p in actual.patients) == counts.boxes_busy
        assert actual.staff == {
            "medicos": counts.doctors_staff,
            "enfermeria_triaje": counts.nurses_staff,
        }
        seen_overstaff |= (
            counts.nurses_busy > counts.nurses_staff or counts.doctors_busy > counts.doctors_staff
        )
    assert seen_overstaff
    assert len(actual.patients) == sum(e.departure is None for e in result.analysis.table)
    episode_index = build_episode_event_index(store, "sample")
    timelines = {
        record.episode_id: episode_segments(
            read_episode_events(store, "sample", record.episode_id, episode_index), horizon
        )
        for record in result.analysis.table
    }
    selected = {0, 1320, 1440, horizon - 1}
    selected.update(
        e.sim_time for e in events if e.event_type in ("patient_displaced", "test_resulted")
    )
    for t in selected:
        for patient in read_replay_state(store, "sample", index, t).patients:
            segment = next(
                s for s in timelines[patient.episode_id].segments if s.start <= t < s.end
            )
            assert (patient.state, patient.box) == (segment.state, segment.box)


def test_any_earlier_checkpoint_reconstructs_same_state(tiny_log):
    store, _, events = tiny_log(TRACE)
    index = build_replay_index(store, "sample")
    for t in range(301):
        expected = _fold(_empty(), events, t)
        for checkpoint in index._checkpoints[: t // 60 + 1]:
            tail = (e for e in events if e.sim_time >= checkpoint.time)
            assert _fold(checkpoint, tail, t) == expected
