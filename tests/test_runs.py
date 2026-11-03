"""Contracts of persisted runs and their public catalog."""

import dataclasses
import json
from datetime import UTC, datetime

import numpy as np
import pytest

from edsim.engine.engine import default_run_id
from edsim.runs import RunInfo, RunStore, validate_run_id


@pytest.fixture
def info():
    return RunInfo(
        format_version=1,
        run_id="r2026",
        created_at="2026-11-03T12:00:00+00:00",
        origin="cli",
        edsim_version="0.1.0",
        seed=2026,
        days=2,
        warmup_days=1,
        variant="base",
        center_fingerprint="123456789abc",
        profile_fingerprint="abcdef012345",
        center_path="config/centro.toml",
        profile_path="config/llegadas.toml",
        invariant_violations=0,
        window_arrivals=307,
        simulation_seconds=0.25,
    )


@pytest.mark.parametrize("run_id", ["r2026", "r2026.1.0", "r1_2_3", "base-noche", "a" * 64])
def test_valid_run_ids(run_id):
    assert validate_run_id(run_id) == run_id


@pytest.mark.parametrize(
    "run_id",
    [
        "",
        ".",
        "..",
        "../x",
        "a/b",
        "a\\b",
        "-x",
        ".x",
        "a" * 65,
        "ñ",
        "a b",
        "a\n",
    ],
)
def test_invalid_run_ids(run_id):
    with pytest.raises(ValueError, match="run_id"):
        validate_run_id(run_id)


def test_default_ids_for_usual_seeds():
    child = np.random.SeedSequence(2026).spawn(2)[1]
    grandchild = child.spawn(1)[0]
    for seed in (0, 7, 2026, child, grandchild):
        assert validate_run_id(default_run_id(seed)) == default_run_id(seed)


def test_metadata_roundtrip(info, tmp_path):
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    info.write(first)
    loaded = RunInfo.read(first)
    assert loaded == info
    loaded.write(second)
    assert first.read_bytes() == second.read_bytes()
    assert json.loads(first.read_text()) == dataclasses.asdict(info)


@pytest.mark.parametrize(
    "change",
    [
        {"format_version": 2},
        {"format_version": True},
        {"created_at": "2026-11-03T12:00:00"},
        {"origin": "other"},
        {"days": 0},
        {"simulation_seconds": -1},
        {"window_arrivals": True},
    ],
)
def test_metadata_rejects_invalid_fields(info, change, tmp_path):
    path = tmp_path / "run.json"
    path.write_text(json.dumps(dataclasses.asdict(info) | change))
    with pytest.raises(ValueError):
        RunInfo.read(path)


def test_metadata_rejects_missing_extra_and_non_object(info, tmp_path):
    path = tmp_path / "run.json"
    data = dataclasses.asdict(info)
    missing = data.copy()
    del missing["seed"]
    for value in (missing, data | {"extra": 1}, []):
        path.write_text(json.dumps(value))
        with pytest.raises(ValueError):
            RunInfo.read(path)


def save_info(root, info):
    directory = root / info.run_id
    directory.mkdir(parents=True)
    info.write(directory / "run.json")
    return directory


def test_catalog_valid_invalid_hidden_and_occupied(info, tmp_path):
    store = RunStore(tmp_path / "catalog")
    assert store.list() == store.invalid() == []
    assert not store.exists(info.run_id)
    save_info(store.root, info)
    newer = dataclasses.replace(info, run_id="newer", created_at="2026-11-04T09:00:00+01:00")
    save_info(store.root, newer)
    hidden = store.root / ".temporary"
    hidden.mkdir()
    incomplete = store.root / "incomplete"
    incomplete.mkdir()
    corrupt = store.root / "corrupt"
    corrupt.mkdir()
    (corrupt / "run.json").write_text("{broken")
    wrong = dataclasses.replace(info, run_id="wrong", format_version=1)
    directory = save_info(store.root, wrong)
    (directory / "run.json").write_text(
        json.dumps(dataclasses.asdict(wrong) | {"format_version": 2})
    )
    mismatch = store.root / "mismatch"
    mismatch.mkdir()
    info.write(mismatch / "run.json")
    assert store.list() == [newer, info]
    assert store.open(info.run_id) == info
    invalid = dict(store.invalid())
    assert set(invalid) == {"incomplete", "corrupt", "wrong", "mismatch"}
    assert all(invalid.values())
    for name in (info.run_id, "incomplete", "corrupt", "wrong", "mismatch"):
        assert store.exists(name)
    assert not store.exists("absent")
    with pytest.raises(ValueError, match="format_version"):
        store.open("wrong")
    with pytest.raises(ValueError, match="match"):
        store.open("mismatch")
    with pytest.raises(FileNotFoundError):
        store.open("absent")


def test_catalog_sort_uses_instants_and_deterministic_ties(info, tmp_path):
    older = dataclasses.replace(info, run_id="older", created_at="2026-11-03T12:30:00+01:00")
    tie = dataclasses.replace(info, run_id="z2026")
    for item in (older, info, tie):
        save_info(tmp_path, item)
    assert RunStore(tmp_path).list() == [tie, info, older]


def test_delete_valid_and_incomplete(info, tmp_path):
    store = RunStore(tmp_path)
    save_info(tmp_path, info)
    (tmp_path / "incomplete").mkdir()
    for name in (info.run_id, "incomplete"):
        store.delete(name)
        assert not store.exists(name)
    with pytest.raises(FileNotFoundError):
        store.delete("absent")


@pytest.mark.parametrize("run_id", ["../outside", ".", "..", "-x", "a/b", "a\\b"])
def test_store_rejects_invalid_ids(run_id, tmp_path):
    store = RunStore(tmp_path)
    protected = tmp_path / "-x"
    protected.mkdir()
    for operation in (store.delete, store.open, store.exists):
        with pytest.raises(ValueError, match="run_id"):
            operation(run_id)
    assert protected.is_dir()


def test_store_rejects_symlinks(info, tmp_path):
    root = tmp_path / "catalog"
    root.mkdir()
    outside = save_info(tmp_path / "outside", info)
    link = root / info.run_id
    link.symlink_to(outside, target_is_directory=True)
    store = RunStore(root)
    assert store.exists(info.run_id)
    assert store.list() == []
    assert dict(store.invalid()).keys() == {info.run_id}
    for operation in (store.open, store.delete):
        with pytest.raises(ValueError, match="inside"):
            operation(info.run_id)
    assert (outside / "run.json").is_file()
    link.unlink()
    link.symlink_to(tmp_path / "missing", target_is_directory=True)
    assert store.exists(info.run_id)
    with pytest.raises(ValueError):
        store.delete(info.run_id)


# --- Simulation service ---------------------------------------------------------------


@pytest.fixture
def simulate(tmp_path):
    from edsim.runs import simulate_run

    def run(**overrides):
        arguments = dict(
            center="tests/data/centro_ejemplo.toml",
            profile="tests/data/llegadas_ejemplo.toml",
            days=2,
            seed=7,
            warmup_days=1,
            run_id="test-run",
            origin="app",
            output_dir=tmp_path / "run",
            clock=lambda: datetime(2026, 11, 3, tzinfo=UTC),
        )
        arguments.update(overrides)
        return simulate_run(**arguments)

    return run


def test_simulation_metadata_and_copies(simulate, tmp_path):
    from pathlib import Path

    from edsim.arrivals.report import config_fingerprint
    from edsim.engine.events import read_events

    ticks = iter([10.0, 10.25])
    result = simulate(timer=lambda: next(ticks))
    output = tmp_path / "run"
    assert RunInfo.read(output / "run.json") == result.info
    assert result.info.simulation_seconds == 0.25
    assert result.info.created_at == "2026-11-03T00:00:00+00:00"
    assert result.info.variant == "centro_ejemplo"
    assert result.info.invariant_violations == len(result.violations) == 0
    events = list(read_events(output / "eventos.jsonl"))
    assert result.info.window_arrivals == sum(
        e.event_type == "patient_arrived" and 1440 <= e.sim_time < 2880 for e in events
    )
    assert result.info.window_arrivals == result.analysis.metrics.arrivals == 307
    for name, original, fingerprint in (
        ("centro.toml", result.info.center_path, result.info.center_fingerprint),
        ("llegadas.toml", result.info.profile_path, result.info.profile_fingerprint),
    ):
        assert (output / name).read_bytes() == Path(original).read_bytes()
        assert config_fingerprint(output / name) == fingerprint
    assert {p.name for p in output.iterdir()} == {
        "run.json",
        "centro.toml",
        "llegadas.toml",
        "eventos.jsonl",
        "ground_truth_episodios.csv",
        "ground_truth_dias.csv",
    }
    assert not any(p.name.startswith(".") for p in tmp_path.iterdir())


def test_reproduce_from_saved_copies(simulate, tmp_path):
    simulate()
    saved = tmp_path / "run"
    simulate(
        center=saved / "centro.toml",
        profile=saved / "llegadas.toml",
        output_dir=tmp_path / "reproduced",
    )
    assert (saved / "eventos.jsonl").read_bytes() == (
        tmp_path / "reproduced" / "eventos.jsonl"
    ).read_bytes()


def test_loads_copies_even_if_original_changes_after_copy(simulate, tmp_path, monkeypatch):
    import shutil
    from pathlib import Path

    original = tmp_path / "original.toml"
    original.write_bytes(Path("tests/data/centro_ejemplo.toml").read_bytes())
    baseline = tmp_path / "baseline"
    simulate(output_dir=baseline)
    copyfile = shutil.copyfile
    copied = []

    def copy_then_modify(source, destination):
        result = copyfile(source, destination)
        copied.append(Path(destination).name)
        if Path(source) == original:
            original.write_text(original.read_text().replace("boxes = 30", "boxes = 1"))
        return result

    monkeypatch.setattr("edsim.runs.service.shutil.copyfile", copy_then_modify)
    simulate(center=original)
    assert copied == ["centro.toml", "llegadas.toml"]
    assert "boxes = 1\n" in original.read_text()
    assert "boxes = 30\n" in (tmp_path / "run" / "centro.toml").read_text()
    assert (tmp_path / "run" / "eventos.jsonl").read_bytes() == (
        baseline / "eventos.jsonl"
    ).read_bytes()


@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt])
def test_simulation_failure_cleans_destination_and_temporary(
    simulate, tmp_path, monkeypatch, failure
):
    from edsim.runs import service

    real = service.simulate_ed
    calls = []

    def fail_after_events(*args, **kwargs):
        real(*args, **kwargs)
        calls.append(True)
        assert list(tmp_path.rglob("eventos.jsonl"))
        raise failure("injected interruption")

    monkeypatch.setattr(service, "simulate_ed", fail_after_events)
    with pytest.raises(failure, match="injected"):
        simulate()
    assert calls == [True]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("stage", ["write_episodes_csv", "check_invariants", "analyze_run"])
def test_late_failure_cleans_run(simulate, tmp_path, monkeypatch, stage):
    def fail(*args, **kwargs):
        raise RuntimeError("injected late failure")

    monkeypatch.setattr(f"edsim.runs.service.{stage}", fail)
    with pytest.raises(RuntimeError, match="injected"):
        simulate()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("kind", ["directory", "file", "broken_symlink"])
def test_service_refuses_occupied_destination_before_simulation(
    simulate,
    tmp_path,
    monkeypatch,
    kind,
):
    output = tmp_path / "run"
    if kind == "directory":
        output.mkdir()
    elif kind == "file":
        output.write_text("untouched")
    else:
        output.symlink_to(tmp_path / "missing")
    monkeypatch.setattr("edsim.runs.service.simulate_ed", lambda *a, **kw: pytest.fail("simulated"))
    with pytest.raises(FileExistsError):
        simulate()
    assert RunStore(tmp_path).exists("run")
    if kind == "file":
        assert output.read_text() == "untouched"


def test_service_saves_violations_and_checks_ground_truth(simulate, tmp_path, monkeypatch):
    from edsim.engine.events import read_events
    from edsim.engine.invariants import Violation
    from edsim.runs import service

    real = service.simulate_ed
    engine_results, calls = [], []
    violation = Violation("capacity", "injected", None, None, None)

    def engine(*args, **kwargs):
        result = real(*args, **kwargs)
        engine_results.append(result)
        return result

    def check(events, center, **kwargs):
        calls.append((events, kwargs))
        return [violation]

    monkeypatch.setattr(service, "simulate_ed", engine)
    monkeypatch.setattr(service, "check_invariants", check)
    result = simulate()
    assert result.violations == (violation,)
    assert result.info.invariant_violations == 1
    assert RunInfo.read(tmp_path / "run" / "run.json").invariant_violations == 1
    assert len(calls) == len(engine_results) == 1
    assert calls[0][0] == list(read_events(tmp_path / "run" / "eventos.jsonl"))
    assert calls[0][1] == {
        "ground_truth": engine_results[0].ground_truth,
        "inside": engine_results[0].inside,
    }


def test_metadata_written_last_before_publish(simulate, tmp_path, monkeypatch):
    real = RunInfo.write
    calls = []

    def write(info, path):
        calls.append(path)
        assert not (tmp_path / "run").exists()
        assert {p.name for p in path.parent.iterdir()} == {
            "eventos.jsonl",
            "ground_truth_episodios.csv",
            "ground_truth_dias.csv",
            "centro.toml",
            "llegadas.toml",
        }
        real(info, path)

    monkeypatch.setattr(RunInfo, "write", write)
    simulate()
    assert len(calls) == 1
    assert (tmp_path / "run" / "run.json").is_file()


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"run_id": "../outside"}, "run_id"),
        ({"run_id": None, "seed": 10**70}, "explicit run_id"),
        ({"days": 1, "warmup_days": 1}, "warmup_days"),
        ({"seed": -1}, "seed"),
        ({"origin": "other"}, "origin"),
        ({"clock": lambda: datetime(2026, 11, 3)}, "timezone"),
    ],
)
def test_service_rejects_arguments_before_simulation(
    simulate, tmp_path, monkeypatch, overrides, message
):
    monkeypatch.setattr("edsim.runs.service.simulate_ed", lambda *a, **kw: pytest.fail("simulated"))
    with pytest.raises(ValueError, match=message):
        simulate(**overrides)
    assert list(tmp_path.iterdir()) == []


def test_cli_and_service_share_artifact_format(simulate, tmp_path, monkeypatch):
    from pathlib import Path

    from edsim.cli import main

    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    result = simulate()
    cli_output = tmp_path / "cli"
    assert (
        main(
            [
                "motor",
                "simular",
                "--centro",
                "tests/data/centro_ejemplo.toml",
                "--llegadas",
                "tests/data/llegadas_ejemplo.toml",
                "--dias",
                "2",
                "--calentamiento",
                "1",
                "--semilla",
                "7",
                "--run-id",
                "test-run",
                "--salida",
                str(cli_output),
            ]
        )
        == 0
    )
    for name in (
        "eventos.jsonl",
        "ground_truth_episodios.csv",
        "ground_truth_dias.csv",
        "centro.toml",
        "llegadas.toml",
    ):
        assert (cli_output / name).read_bytes() == (tmp_path / "run" / name).read_bytes()
    cli_info = RunInfo.read(cli_output / "run.json")
    equal_fields = (
        "format_version",
        "run_id",
        "edsim_version",
        "seed",
        "days",
        "warmup_days",
        "variant",
        "center_fingerprint",
        "profile_fingerprint",
        "center_path",
        "profile_path",
        "invariant_violations",
        "window_arrivals",
    )
    assert {field.name for field in dataclasses.fields(RunInfo)} == set(equal_fields) | {
        "origin",
        "created_at",
        "simulation_seconds",
    }
    for name in equal_fields:
        assert getattr(cli_info, name) == getattr(result.info, name), name
    assert cli_info.origin == "cli"
    assert result.info.origin == "app"
    for info in (cli_info, result.info):
        assert isinstance(info.created_at, str)
        assert datetime.fromisoformat(info.created_at).utcoffset() is not None
        assert isinstance(info.simulation_seconds, float)
        assert info.simulation_seconds >= 0
    assert result.info.invariant_violations == len(result.violations)


def test_service_uses_default_id_and_custom_variant(simulate):
    result = simulate(run_id=None, variant="base-noche")
    assert result.info.run_id == "r7"
    assert result.info.variant == "base-noche"


def test_service_missing_input_cleans_temporary(simulate, tmp_path):
    with pytest.raises(FileNotFoundError):
        simulate(center=tmp_path / "missing.toml")
    assert list(tmp_path.iterdir()) == []
