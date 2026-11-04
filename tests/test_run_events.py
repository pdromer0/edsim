"""Exercise byte offsets, sparse reads and damaged indexed lines."""

from dataclasses import replace
from datetime import date
from unittest.mock import Mock

import pytest

from edsim.engine.events import EventLog, MemorySink, read_events, to_json
from edsim.runs import RunReadError, RunStore, build_episode_event_index, read_episode_events


@pytest.fixture
def log_file(tmp_path):
    path = tmp_path / "sample" / "eventos.jsonl"
    path.parent.mkdir()
    log = EventLog("sample", date(2026, 1, 5), MemorySink())
    first = log.emit("patient_arrived", 0, arrival_id=0)
    first = replace(first, event_id="event-con-acento-á")
    events = (
        first,
        log.emit("patient_arrived", 1, arrival_id=1),
        log.emit("patient_registered", 2, arrival_id=0),
        log.emit("staffing_changed", 3, recurso="medicos", anterior=1, nueva=2),
        log.emit("patient_registered", 4, arrival_id=1),
    )
    return RunStore(tmp_path), path, events


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("final_newline", [True, False])
def test_offsets_count_original_utf8_bytes_and_physical_lines(log_file, newline, final_newline):
    store, path, events = log_file
    text = newline.join(to_json(event) for event in events)
    path.write_bytes((text + (newline if final_newline else "")).encode("utf-8"))
    index = build_episode_event_index(store, "sample")
    assert tuple(read_events(path)) == events
    assert set(index.positions) == {"EP-000000", "EP-000001"}
    assert index.positions["EP-000000"][:, 1].tolist() == [1, 3]
    assert index.positions["EP-000001"][:, 1].tolist() == [2, 5]
    for episode in index.positions:
        assert read_episode_events(store, "sample", episode, index) == tuple(
            event for event in events if event.episode_id == episode
        )
    with pytest.raises(KeyError):
        read_episode_events(store, "sample", "EP-999999", index)


@pytest.mark.parametrize("damage", [b"{bad}\n", b"\xff\n", b""])
def test_indexed_read_reports_original_line_for_damaged_or_truncated_file(log_file, damage):
    store, path, events = log_file
    path.write_bytes(b"".join((to_json(event) + "\n").encode() for event in events))
    index = build_episode_event_index(store, "sample")
    offset = int(index.positions["EP-000001"][1, 0])
    path.write_bytes(path.read_bytes()[:offset] + damage)
    with pytest.raises(RunReadError) as caught:
        read_episode_events(store, "sample", "EP-000001", index)
    assert str(caught.value).startswith(f"{path}:5:")


def test_one_episode_only_seeks_and_reads_its_lines(log_file, monkeypatch):
    from pathlib import Path

    store, path, events = log_file
    path.write_bytes(b"".join((to_json(event) + "\n").encode() for event in events))
    index = build_episode_event_index(store, "sample")
    original = Path.open
    sources = []

    def open_spy(self, *args, **kwargs):
        source = original(self, *args, **kwargs)
        if self == path:
            spy = Mock(wraps=source)
            spy.__enter__ = Mock(return_value=spy)
            spy.__exit__ = Mock(side_effect=lambda *args: source.close())
            sources.append(spy)
            return spy
        return source

    monkeypatch.setattr(Path, "open", open_spy)
    actual = read_episode_events(store, "sample", "EP-000000", index)
    assert actual == (events[0], events[2])
    assert len(sources) == 1
    assert sources[0].seek.call_count == sources[0].readline.call_count == 2
    sources[0].read.assert_not_called()


def test_replaced_line_cannot_return_another_episode(log_file):
    store, path, events = log_file
    path.write_bytes(b"".join((to_json(event) + "\n").encode() for event in events))
    index = build_episode_event_index(store, "sample")
    replaced = replace(events[0], episode_id="EP-000002", patient_id="PT-000002")
    original = (to_json(events[0]) + "\n").encode()
    path.write_bytes((to_json(replaced) + "\n").encode() + path.read_bytes()[len(original) :])
    with pytest.raises(RunReadError, match="eventos.jsonl:1: indexed event"):
        read_episode_events(store, "sample", "EP-000000", index)


def test_catalog_validation_is_deferred_until_episode_read(log_file):
    import json

    store, path, events = log_file
    data = json.loads(to_json(events[0]))
    data["event_type"] = "not_in_the_catalog"
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")
    index = build_episode_event_index(store, "sample")
    assert index.positions["EP-000000"].tolist() == [[0, 1]]
    with pytest.raises(RunReadError, match="eventos.jsonl:1: unknown event_type"):
        read_episode_events(store, "sample", "EP-000000", index)


@pytest.mark.parametrize("raw", [b"{bad}\n", b"\xff\n", b"\n"])
def test_indexing_errors_keep_physical_file_and_line(log_file, raw):
    store, path, events = log_file
    path.write_bytes((to_json(events[0]) + "\n").encode() + raw)
    with pytest.raises(RunReadError) as caught:
        build_episode_event_index(store, "sample")
    assert str(caught.value).startswith(f"{path}:2:")


def test_real_run_index_matches_all_episodes_and_is_read_only(tmp_path):
    import numpy as np

    from edsim.runs import read_run_results, simulate_run

    simulate_run(
        "tests/data/centro_ejemplo.toml",
        "tests/data/llegadas_ejemplo.toml",
        2,
        7,
        output_dir=tmp_path / "sample",
        run_id="sample",
        warmup_days=1,
        origin="app",
    )
    store = RunStore(tmp_path)
    result = read_run_results(store, "sample")
    index = build_episode_event_index(store, "sample")
    expected = {}
    for event in read_events(tmp_path / "sample" / "eventos.jsonl"):
        if event.episode_id is not None:
            expected.setdefault(event.episode_id, []).append(event)
    assert len(index.positions) == len(result.analysis.table) > 0
    for episode, events in expected.items():
        assert read_episode_events(store, "sample", episode, index) == tuple(events)
        positions = index.positions[episode]
        assert positions.dtype == np.uint64 and positions.shape[1] == 2
        assert not positions.flags.writeable
        with pytest.raises(ValueError):
            positions.setflags(write=True)
