"""Contracts of persisted runs and their public catalog."""

import dataclasses
import json

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
