"""Read saved artifacts with narrow input errors and unchanged engine analysis."""

import dataclasses
import os
from hashlib import sha256
from unittest.mock import Mock

import numpy as np
import pytest

from edsim.engine.analysis import analyze_run
from edsim.engine.events import read_events, to_json
from edsim.runs import (
    RunAnalysisError,
    RunReadError,
    RunStore,
    load_center,
    read_run_header,
    read_run_results,
    simulate_run,
)


@pytest.fixture
def saved(tmp_path):
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
    return RunStore(tmp_path), tmp_path / "sample"


def test_results_reproduce_analysis_and_metadata_using_saved_copies(saved):
    store, path = saved
    info = store.open("sample")
    # Provenance paths are not inputs when reopening a run.
    dataclasses.replace(info, center_path="missing.toml", profile_path="missing.toml").write(
        path / "run.json"
    )
    result = read_run_results(store, "sample")
    events = list(read_events(path / "eventos.jsonl"))
    expected = analyze_run(events, load_center(path / "centro.toml"), 2, 1)
    assert result.analysis.table == expected.table
    assert result.analysis.metrics == expected.metrics
    assert result.analysis.little == expected.little
    assert result.analysis.utilization == expected.utilization
    for name in expected.curves.values:
        np.testing.assert_array_equal(result.analysis.curves[name], expected.curves[name])
    assert result.kpis.arrivals_per_day == result.info.arrivals_per_day
    assert result.start_date.isoformat() == "2026-01-05"
    assert result.hourly_census.shape == (24,)
    assert result.hourly_census.mean() == pytest.approx(result.kpis.census_mean)
    assert result.violations is None


def test_header_reopens_and_fingerprints_exact_metadata_bytes(saved, monkeypatch):
    store, path = saved
    opened = Mock(wraps=store.open)
    monkeypatch.setattr(store, "open", opened)
    first, fingerprint = read_run_header(store, "sample")
    assert fingerprint == sha256((path / "run.json").read_bytes()).hexdigest()
    (path / "run.json").write_bytes((path / "run.json").read_bytes() + b" ")
    second, changed = read_run_header(store, "sample")
    assert second == first and changed != fingerprint
    assert opened.call_count == 2
    (path / "run.json").unlink()
    with pytest.raises(RunReadError, match="run.json"):
        read_run_header(store, "sample")


@pytest.mark.parametrize(
    "filename",
    [
        "run.json",
        "centro.toml",
        "llegadas.toml",
        "eventos.jsonl",
        "ground_truth_episodios.csv",
        "ground_truth_dias.csv",
    ],
)
def test_read_file_returns_exact_bytes(saved, filename):
    store, path = saved
    assert store.read_file("sample", filename) == (path / filename).read_bytes()


@pytest.mark.parametrize(
    "filename", ["../run.json", "extra.txt", "/etc/passwd", "nested/centro.toml"]
)
def test_read_file_rejects_non_format_names(saved, filename):
    store, _ = saved
    with pytest.raises(ValueError, match="filename"):
        store.read_file("sample", filename)


@pytest.mark.parametrize("kind", ["symlink", "directory", "fifo"])
@pytest.mark.parametrize("filename", ["eventos.jsonl", "run.json"])
def test_non_regular_files_are_rejected_before_open(saved, tmp_path, kind, filename):
    store, path = saved
    target = path / filename
    data = target.read_bytes()
    target.unlink()
    if kind == "symlink":
        outside = tmp_path / "outside"
        outside.write_bytes(data)
        target.symlink_to(outside)
    elif kind == "directory":
        target.mkdir()
    else:
        os.mkfifo(target)
    with pytest.raises(ValueError, match="regular"):
        store.read_file("sample", filename)
    with pytest.raises(RunReadError, match="regular"):
        read_run_results(store, "sample")


@pytest.mark.parametrize("filename", ["run.json", "centro.toml", "llegadas.toml", "eventos.jsonl"])
@pytest.mark.parametrize("kind", ["missing", "invalid"])
def test_input_failures_keep_filename_and_reason(saved, filename, kind):
    store, path = saved
    target = path / filename
    if kind == "missing":
        target.unlink()
    else:
        target.write_text("[broken", encoding="utf-8")
    with pytest.raises(RunReadError, match=filename):
        read_run_results(store, "sample")


def test_empty_observation_window_has_explicit_error(saved):
    store, path = saved
    events = [event for event in read_events(path / "eventos.jsonl") if event.sim_time < 1440]
    (path / "eventos.jsonl").write_text("".join(to_json(event) + "\n" for event in events))
    with pytest.raises(RunAnalysisError, match="no tiene episodios completados"):
        read_run_results(store, "sample")


@pytest.mark.parametrize("error_type", [ValueError, RuntimeError, OSError])
def test_internal_analysis_failures_are_not_input_errors(saved, monkeypatch, error_type):
    store, _ = saved

    def fail(*args, **kwargs):
        raise error_type("injected analysis failure")

    monkeypatch.setattr("edsim.runs.results.analyze_run", fail)
    with pytest.raises(error_type, match="injected analysis failure") as caught:
        read_run_results(store, "sample")
    assert not isinstance(caught.value, RunReadError | RunAnalysisError)


def test_zero_invariants_skip_check_positive_count_rechecks_only_log(saved, monkeypatch):
    import edsim.runs.results as module

    store, path = saved
    check = Mock(wraps=module.check_invariants)
    monkeypatch.setattr(module, "check_invariants", check)
    assert read_run_results(store, "sample").violations is None
    check.assert_not_called()
    dataclasses.replace(store.open("sample"), invariant_violations=17).write(path / "run.json")
    result = read_run_results(store, "sample")
    assert result.violations == ()
    assert check.call_count == 1
    assert len(check.call_args.args) == 2 and check.call_args.kwargs == {}
    # A duplicate registration is structurally readable and breaks invariants.
    events = list(read_events(path / "eventos.jsonl"))
    registered = next(event for event in events if event.event_type == "patient_registered")
    index = events.index(registered)
    events.insert(index, registered)
    (path / "eventos.jsonl").write_text("".join(to_json(event) + "\n" for event in events))
    result = read_run_results(store, "sample")
    assert result.violations and any(v.check == "transitions" for v in result.violations)


def test_public_exports():
    import edsim.runs as runs

    for name in (
        "RunResults",
        "RunReadError",
        "RunAnalysisError",
        "read_run_header",
        "read_run_results",
        "Compliance",
        "Violation",
    ):
        assert name in runs.__all__
