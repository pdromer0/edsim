"""Contracts of persisted runs and their public catalog."""

import dataclasses
import json
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pytest

from edsim.arrivals.profile import load_profile
from edsim.engine.center import load_center
from edsim.engine.engine import default_run_id
from edsim.runs import RunInfo, RunStore, validate_run_id


@pytest.fixture
def info():
    return RunInfo(
        format_version=2,
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
    # El provisional no escribe las claves nulas de los perfiles clínicos.
    expected = dataclasses.asdict(info)
    del expected["clinical_profiles_path"], expected["clinical_profiles_fingerprint"]
    assert json.loads(first.read_text()) == expected
    assert "arrivals_per_day" not in json.loads(first.read_text())


@pytest.mark.parametrize(
    "days, warmup, arrivals, expected",
    [(5, 2, 900, 300.0), (4, 0, 1001, 250.25), (2, 1, 0, 0.0)],
)
def test_arrivals_per_day_uses_observation_window(info, days, warmup, arrivals, expected):
    info = dataclasses.replace(info, days=days, warmup_days=warmup, window_arrivals=arrivals)
    assert info.arrivals_per_day == expected


@pytest.mark.parametrize(
    "change",
    [
        {"format_version": 3},
        {"format_version": True},
        {"format_version": 1},
        {"model": "otro"},
        {"model": "clinico"},
        {"clinical_profiles_fingerprint": None},
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
    wrong = dataclasses.replace(info, run_id="wrong")
    directory = save_info(store.root, wrong)
    (directory / "run.json").write_text(
        json.dumps(json.loads((directory / "run.json").read_text()) | {"format_version": 3})
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
    for operation in (store.delete, store.open, store.exists, store.archive):
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
    for operation in (store.open, store.delete, store.archive):
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


def test_archive_has_exactly_the_six_original_files(simulate, tmp_path):
    simulate()
    directory = tmp_path / "run"
    names = {
        "run.json",
        "centro.toml",
        "llegadas.toml",
        "eventos.jsonl",
        "ground_truth_episodios.csv",
        "ground_truth_dias.csv",
    }
    (directory / "extra.txt").write_text("not part of the run")
    (directory / "nested").mkdir()
    with ZipFile(BytesIO(RunStore(tmp_path).archive("run"))) as archive:
        assert len(archive.namelist()) == 6
        assert set(archive.namelist()) == names
        for name in names:
            assert archive.read(name) == (directory / name).read_bytes()


@pytest.mark.parametrize("kind", ["symlink", "directory", "fifo"])
def test_archive_rejects_non_regular_files(simulate, tmp_path, kind):
    import os

    simulate()
    file = tmp_path / "run" / "eventos.jsonl"
    original = file.read_bytes()
    file.unlink()
    if kind == "symlink":
        outside = tmp_path / "outside.jsonl"
        outside.write_bytes(original)
        file.symlink_to(outside)
    elif kind == "directory":
        file.mkdir()
    else:
        os.mkfifo(file)
    with pytest.raises(ValueError, match="regular"):
        RunStore(tmp_path).archive("run")


def test_archive_missing_run(tmp_path):
    with pytest.raises(FileNotFoundError):
        RunStore(tmp_path).archive("absent")


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
    from edsim.runs import service

    original = tmp_path / "original.toml"
    original.write_bytes(Path("tests/data/centro_ejemplo.toml").read_bytes())
    baseline = tmp_path / "baseline"
    simulate(output_dir=baseline)
    copyfile = service._copy_configuration
    copied = []

    def copy_then_modify(source, destination):
        result = copyfile(source, destination)
        copied.append(Path(destination).name)
        if Path(source) == original:
            original.write_text(original.read_text().replace("boxes = 30", "boxes = 1"))
        return result

    monkeypatch.setattr(service, "_copy_configuration", copy_then_modify)
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
        "profiles": None,
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
        "model",
        "clinical_profiles_path",
        "clinical_profiles_fingerprint",
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
    from edsim.runs import RunConfigurationError

    with pytest.raises(RunConfigurationError) as caught:
        simulate(center=tmp_path / "missing.toml")
    assert isinstance(caught.value.__cause__, FileNotFoundError)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("argument", ["center", "profile", "profiles"])
@pytest.mark.parametrize("kind", ["missing", "directory", "unreadable", "toml", "validation"])
def test_configuration_failures_keep_their_cause(simulate, tmp_path, monkeypatch, argument, kind):
    from edsim.runs import RunConfigurationError

    path = tmp_path / "input.toml"
    if kind == "directory":
        path.mkdir()
        expected = IsADirectoryError
    elif kind == "missing":
        expected = FileNotFoundError
    elif kind == "unreadable":
        path.write_text("")
        real = Path.read_bytes

        def unreadable(self):
            if self == path:
                raise PermissionError("injected permission failure")
            return real(self)

        monkeypatch.setattr(Path, "read_bytes", unreadable)
        expected = PermissionError
    else:
        path.write_text("[broken" if kind == "toml" else "unknown = 1\n")
        expected = ValueError
    with pytest.raises(RunConfigurationError) as caught:
        simulate(**{argument: path})
    assert isinstance(caught.value.__cause__, expected)
    assert str(path) in str(caught.value)
    assert not (tmp_path / "run").exists()
    assert not list(tmp_path.glob(".test-run-*"))


@pytest.mark.parametrize("stage", ["simulate_ed", "config_fingerprint", "analyze_run"])
def test_internal_value_errors_are_not_configuration_errors(simulate, tmp_path, monkeypatch, stage):
    from edsim.runs import RunConfigurationError

    error = ValueError("injected internal failure")

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(f"edsim.runs.service.{stage}", fail)
    with pytest.raises(ValueError) as caught:
        simulate()
    assert caught.value is error
    assert not isinstance(caught.value, RunConfigurationError)
    assert list(tmp_path.iterdir()) == []


def test_configuration_destination_write_error_is_not_wrapped(simulate, tmp_path, monkeypatch):
    from edsim.runs import RunConfigurationError

    error = PermissionError("injected destination failure")
    real = Path.write_bytes

    def fail(self, data):
        if self.name == "centro.toml":
            raise error
        return real(self, data)

    monkeypatch.setattr(Path, "write_bytes", fail)
    with pytest.raises(PermissionError) as caught:
        simulate()
    assert caught.value is error
    assert not isinstance(caught.value, RunConfigurationError)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("mask", [0o002, 0o022, 0o027, 0o077])
def test_published_directory_matches_normal_mkdir_permissions(simulate, tmp_path, mask):
    import os
    import stat

    previous = os.umask(mask)
    try:
        reference = tmp_path / "reference"
        reference.mkdir()
        simulate()
    finally:
        os.umask(previous)
    assert stat.S_IMODE((tmp_path / "run").stat().st_mode) == stat.S_IMODE(reference.stat().st_mode)


def test_suggest_run_id_uses_first_free_name_including_invalid_entries(tmp_path):
    store = RunStore(tmp_path / "runs")
    assert store.suggest_run_id("centro-r2026") == "centro-r2026"
    assert not store.root.exists()
    store.root.mkdir()
    (store.root / "centro-r2026").mkdir()
    (store.root / "centro-r2026-2").write_text("occupied")
    (store.root / "centro-r2026-3").symlink_to(tmp_path / "absent")
    assert store.suggest_run_id("centro-r2026") == "centro-r2026-4"


def test_suggest_run_id_never_truncates_and_validates_preferred(tmp_path):
    store = RunStore(tmp_path)
    preferred = "v" * 42 + "-r" + "9" * 20
    assert len(preferred) == 64
    assert store.suggest_run_id(preferred) == preferred
    (tmp_path / preferred).mkdir()
    assert store.suggest_run_id(preferred) is None
    with pytest.raises(ValueError, match="run_id"):
        store.suggest_run_id("../invalid")


def test_configuration_fingerprint_is_public(tmp_path):
    import edsim.runs as runs

    path = tmp_path / "profile.toml"
    path.write_bytes(b"abc")
    assert "config_fingerprint" in runs.__all__
    assert runs.config_fingerprint(path) == "ba7816bf8f01"


# --- run.json de la versión 1 ----------------------------------------------------------

# Escrito con simulate_run en main, antes de la tarea 4.5b, y guardado tal cual: la
# versión 1 solo se lee desde entonces.
RUN_V1 = Path(__file__).parent / "data" / "run_v1.json"


def test_run_json_de_la_version_1_de_referencia():
    info = RunInfo.read(RUN_V1)

    assert info.format_version == 1
    assert (info.run_id, info.seed, info.days, info.warmup_days) == ("referencia-v1", 7, 2, 1)
    assert (info.center_fingerprint, info.profile_fingerprint) == ("5b86440058ee", "63d0ae1fb4f0")
    assert len(json.loads(RUN_V1.read_text())) == 16
    # Una versión 1 es siempre del modelo provisional, sin perfiles clínicos.
    assert info.model == "provisional"
    assert not info.is_clinical
    assert info.clinical_profiles_path is info.clinical_profiles_fingerprint is None


def test_la_version_1_se_lee_pero_no_se_escribe(tmp_path):
    info = RunInfo.read(RUN_V1)

    with pytest.raises(ValueError, match="only format_version 2"):
        info.write(tmp_path / "run.json")
    assert not (tmp_path / "run.json").exists()


@pytest.mark.parametrize(
    "extra",
    [
        {"model": "provisional"},
        {"clinical_profiles_path": "p.toml", "clinical_profiles_fingerprint": "abc"},
    ],
)
def test_la_version_1_no_admite_claves_de_la_2(extra, tmp_path):
    path = tmp_path / "run.json"
    path.write_text(json.dumps(json.loads(RUN_V1.read_text()) | extra))

    with pytest.raises(ValueError, match="unexpected"):
        RunInfo.read(path)


V2_KEYS = [*json.loads(RUN_V1.read_text()), "model"]
"""Las claves de la versión 2 del provisional: las 16 de la 1, en su orden, y el modelo."""


@pytest.fixture
def clinical_info(info):
    return dataclasses.replace(
        info,
        model="clinico",
        clinical_profiles_path="config/perfiles.toml",
        clinical_profiles_fingerprint="fedcba987654",
    )


def test_ida_y_vuelta_de_la_version_2_provisional(info, tmp_path):
    path = tmp_path / "run.json"
    info.write(path)

    data = json.loads(path.read_text())
    assert list(data) == V2_KEYS
    assert (data["format_version"], data["model"]) == (2, "provisional")
    assert RunInfo.read(path) == info


def test_ida_y_vuelta_de_la_version_2_clinica(clinical_info, tmp_path):
    path = tmp_path / "run.json"
    clinical_info.write(path)

    data = json.loads(path.read_text())
    assert list(data) == [*V2_KEYS, "clinical_profiles_path", "clinical_profiles_fingerprint"]
    assert data["model"] == "clinico"
    assert data["clinical_profiles_path"] == "config/perfiles.toml"
    assert data["clinical_profiles_fingerprint"] == "fedcba987654"
    loaded = RunInfo.read(path)
    assert loaded == clinical_info
    assert loaded.is_clinical


@pytest.mark.parametrize(
    "change, message",
    [
        ({"format_version": 3}, "format_version"),
        ({"format_version": "2"}, "format_version"),
        ({"model": None}, "missing"),
        ({"clinical_profiles_fingerprint": None}, "missing"),
        ({"extra": 1}, "unexpected"),
    ],
)
def test_version_2_clinica_rechaza_claves_o_valores_invalidos(
    clinical_info, tmp_path, change, message
):
    # None en el cambio quiere decir «quitar la clave»: los valores por defecto del
    # dataclass nunca rellenan una clave que falta.
    path = tmp_path / "run.json"
    clinical_info.write(path)
    data = json.loads(path.read_text())
    for key, value in change.items():
        if value is None:
            del data[key]
        else:
            data[key] = value
    path.write_text(json.dumps(data))

    with pytest.raises(ValueError, match=message):
        RunInfo.read(path)


def test_version_2_provisional_sin_modelo_es_un_error(info, tmp_path):
    path = tmp_path / "run.json"
    info.write(path)
    data = json.loads(path.read_text())
    del data["model"]
    path.write_text(json.dumps(data))

    with pytest.raises(ValueError, match="missing"):
        RunInfo.read(path)


def test_version_2_provisional_con_perfiles_es_un_error(info, tmp_path):
    path = tmp_path / "run.json"
    info.write(path)
    data = json.loads(path.read_text()) | {
        "clinical_profiles_path": "p.toml",
        "clinical_profiles_fingerprint": "abc",
    }
    path.write_text(json.dumps(data))

    with pytest.raises(ValueError, match="unexpected"):
        RunInfo.read(path)


@pytest.mark.parametrize(
    "change, message",
    [
        ({"format_version": 1}, "format_version 1 has no clinical model"),
        ({"clinical_profiles_path": None}, "clinical_profiles_path"),
        ({"clinical_profiles_fingerprint": ""}, "clinical_profiles_fingerprint"),
        ({"model": "otro"}, "model"),
    ],
)
def test_el_modelo_explica_los_campos_opcionales(clinical_info, change, message):
    with pytest.raises(ValueError, match=message):
        dataclasses.replace(clinical_info, **change)


def test_el_provisional_no_lleva_perfiles(info):
    with pytest.raises(ValueError, match="None with model provisional"):
        dataclasses.replace(info, clinical_profiles_fingerprint="abc")


def test_archivo_de_una_ejecucion_clinica_con_siete_ficheros(clinical_info, tmp_path):
    info = dataclasses.replace(clinical_info, run_id="clinica")
    directory = save_info(tmp_path, info)
    names = {
        "centro.toml",
        "llegadas.toml",
        "perfiles.toml",
        "eventos.jsonl",
        "ground_truth_episodios.csv",
        "ground_truth_dias.csv",
    }
    for name in names:
        (directory / name).write_text(f"contenido de {name}\n")
    store = RunStore(tmp_path)

    assert set(store.run_files("clinica")) == names | {"run.json"}
    with ZipFile(BytesIO(store.archive("clinica"))) as archive:
        assert sorted(archive.namelist()) == sorted(names | {"run.json"})
        for name in names | {"run.json"}:
            assert archive.read(name) == (directory / name).read_bytes()
    assert store.read_file("clinica", "perfiles.toml") == b"contenido de perfiles.toml\n"


# --- simulate_run con perfiles clínicos (tarea 4.5b) ----------------------------------------

PROFILES = "tests/data/perfiles_ejemplo.toml"


def test_simulacion_clinica_metadatos_y_copias(simulate, tmp_path):
    from edsim.arrivals.report import config_fingerprint
    from edsim.engine.report import CLINICAL_EPISODE_COLUMNS

    result = simulate(profiles=PROFILES)
    output = tmp_path / "run"
    info = RunInfo.read(output / "run.json")

    assert info == result.info
    assert (info.format_version, info.model) == (2, "clinico")
    assert info.clinical_profiles_path == PROFILES
    assert (output / "perfiles.toml").read_bytes() == Path(PROFILES).read_bytes()
    assert info.clinical_profiles_fingerprint == config_fingerprint(output / "perfiles.toml")
    # Las huellas del centro y de las llegadas no dependen del modelo.
    assert info.profile_path == "tests/data/llegadas_ejemplo.toml"
    assert info.invariant_violations == len(result.violations) == 0
    assert {p.name for p in output.iterdir()} == {
        "run.json",
        "centro.toml",
        "llegadas.toml",
        "perfiles.toml",
        "eventos.jsonl",
        "ground_truth_episodios.csv",
        "ground_truth_dias.csv",
    }
    header = (output / "ground_truth_episodios.csv").read_text().splitlines()[0]
    assert tuple(header.split(",")) == CLINICAL_EPISODE_COLUMNS
    assert not any(p.name.startswith(".") for p in tmp_path.iterdir())


def test_simulacion_clinica_es_la_de_simulate_ed(simulate, tmp_path):
    # El log y el ground truth guardados son los de simulate_ed con los mismos argumentos.
    from edsim.engine.engine import simulate_ed
    from edsim.engine.events import JsonlSink
    from edsim.engine.report import read_episodes_csv
    from edsim.profiles.config import load_profiles

    simulate(profiles=PROFILES)
    path = tmp_path / "eventos.jsonl"
    with JsonlSink(path) as sink:
        expected = simulate_ed(
            load_center("tests/data/centro_ejemplo.toml"),
            load_profile("tests/data/llegadas_ejemplo.toml"),
            2,
            7,
            sink=sink,
            warmup_days=1,
            run_id="test-run",
            profiles=load_profiles(PROFILES),
        )

    assert (tmp_path / "run" / "eventos.jsonl").read_bytes() == path.read_bytes()
    episodes = read_episodes_csv(tmp_path / "run" / "ground_truth_episodios.csv")
    assert episodes == expected.ground_truth.episodes
    assert all(e.clinical is not None for e in episodes)


def test_reproducir_desde_la_copia_con_perfiles(simulate, tmp_path):
    simulate(profiles=PROFILES)
    saved = tmp_path / "run"
    simulate(
        center=saved / "centro.toml",
        profile=saved / "llegadas.toml",
        profiles=saved / "perfiles.toml",
        output_dir=tmp_path / "reproduced",
    )

    from edsim.engine.report import read_episodes_csv

    reproduced = tmp_path / "reproduced"
    assert (saved / "eventos.jsonl").read_bytes() == (reproduced / "eventos.jsonl").read_bytes()
    # Los CSV llevan las rutas de procedencia, que aquí cambian; los episodios, no.
    assert read_episodes_csv(saved / "ground_truth_episodios.csv") == read_episodes_csv(
        reproduced / "ground_truth_episodios.csv"
    )


def test_perfiles_desde_la_copia_aunque_cambie_el_original(simulate, tmp_path, monkeypatch):
    from edsim.runs import service

    original = tmp_path / "perfiles.toml"
    original.write_bytes(Path(PROFILES).read_bytes())
    baseline = tmp_path / "baseline"
    simulate(profiles=original, output_dir=baseline)
    copyfile = service._copy_configuration
    copied = []

    def copy_then_modify(source, destination):
        result = copyfile(source, destination)
        copied.append(Path(destination).name)
        if Path(source) == original:
            # Más ruido de triaje: otro reparto de niveles asignados, otro log.
            original.write_text(original.read_text().replace("ruido = 0.333", "ruido = 0.9"))
        return result

    monkeypatch.setattr(service, "_copy_configuration", copy_then_modify)
    simulate(profiles=original)

    assert copied == ["centro.toml", "llegadas.toml", "perfiles.toml"]
    assert "ruido = 0.9" in original.read_text()
    assert "ruido = 0.333" in (tmp_path / "run" / "perfiles.toml").read_text()
    assert (tmp_path / "run" / "eventos.jsonl").read_bytes() == (
        baseline / "eventos.jsonl"
    ).read_bytes()


def test_simulate_run_pasa_los_perfiles_a_las_invariantes(simulate, monkeypatch):
    # Espía: check_invariants recibe el mismo objeto de perfiles que simulate_ed, el
    # cargado de la copia, junto al ground truth.
    from edsim.profiles.config import load_profiles
    from edsim.runs import service

    real_engine, real_check = service.simulate_ed, service.check_invariants
    engine_profiles, check_kwargs = [], []

    def engine(*args, **kwargs):
        engine_profiles.append(kwargs["profiles"])
        return real_engine(*args, **kwargs)

    def check(events, center, **kwargs):
        check_kwargs.append(kwargs)
        return real_check(events, center, **kwargs)

    monkeypatch.setattr(service, "simulate_ed", engine)
    monkeypatch.setattr(service, "check_invariants", check)
    simulate(profiles=PROFILES)

    assert len(engine_profiles) == len(check_kwargs) == 1
    assert check_kwargs[0]["profiles"] is engine_profiles[0]
    assert engine_profiles[0] == load_profiles(PROFILES)
    assert check_kwargs[0]["ground_truth"] is not None


def test_simulate_run_guarda_las_violaciones_de_la_respuesta(simulate, tmp_path, monkeypatch):
    # Comportamiento: si el motor alarga cada ronda un minuto, solo la comprobación de la
    # respuesta con los perfiles lo ve (la base del ground truth no cambia).
    from edsim.engine.clinical_sampler import ClinicalDraws

    real = ClinicalDraws.round_turnaround
    monkeypatch.setattr(ClinicalDraws, "round_turnaround", lambda self, t: real(self, t) + 1.0)
    result = simulate(profiles=PROFILES)

    turnaround = [
        v for v in result.violations if v.check == "clinical" and "turnaround" in v.message
    ]
    assert turnaround
    assert result.info.invariant_violations == len(result.violations) > 0
    assert RunInfo.read(tmp_path / "run" / "run.json").invariant_violations > 0


def test_la_cli_y_simulate_run_dan_el_mismo_log_con_perfiles(simulate, tmp_path, monkeypatch):
    from edsim.cli import main

    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    result = simulate(profiles=PROFILES)
    cli_output = tmp_path / "cli"
    arguments = ["--centro", "tests/data/centro_ejemplo.toml"]
    arguments += ["--llegadas", "tests/data/llegadas_ejemplo.toml", "--perfiles", PROFILES]
    arguments += ["--dias", "2", "--calentamiento", "1", "--semilla", "7"]
    arguments += ["--run-id", "test-run", "--salida", str(cli_output)]

    assert main(["motor", "simular", *arguments]) == 0
    for name in (
        "eventos.jsonl",
        "ground_truth_episodios.csv",
        "ground_truth_dias.csv",
        "centro.toml",
        "llegadas.toml",
        "perfiles.toml",
    ):
        assert (cli_output / name).read_bytes() == (tmp_path / "run" / name).read_bytes(), name
    cli_info = RunInfo.read(cli_output / "run.json")
    assert (
        dataclasses.replace(
            cli_info,
            created_at=result.info.created_at,
            origin="app",
            simulation_seconds=result.info.simulation_seconds,
        )
        == result.info
    )
