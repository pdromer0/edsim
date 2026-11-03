"""Isolate every page from real runs and supply reproducible catalog artifacts."""

import shutil
from datetime import UTC, datetime

import pytest

from edsim.runs import RunInfo, simulate_run


@pytest.fixture(autouse=True)
def catalog_root(tmp_path, monkeypatch):
    root = tmp_path / "catalog"
    monkeypatch.setenv("EDSIM_EJECUCIONES", str(root))
    return root


@pytest.fixture(scope="session")
def run_templates(tmp_path_factory):
    root = tmp_path_factory.mktemp("run-templates")
    for run_id, day, seed in (("older", 2, 7), ("newer", 3, 8)):
        simulate_run(
            "tests/data/centro_ejemplo.toml",
            "tests/data/llegadas_ejemplo.toml",
            3,
            seed,
            output_dir=root / run_id,
            warmup_days=1,
            run_id=run_id,
            origin="app",
            clock=lambda day=day: datetime(2026, 11, day, 12, tzinfo=UTC),
        )
    return root


@pytest.fixture
def catalog(catalog_root, run_templates):
    shutil.copytree(run_templates, catalog_root)
    return catalog_root


@pytest.fixture
def run_info():
    return RunInfo(
        format_version=1,
        run_id="example",
        created_at="2026-07-03T23:30:00+00:00",
        origin="cli",
        edsim_version="0.1.0",
        seed=2026,
        days=4,
        warmup_days=2,
        variant="base",
        center_fingerprint="123456789abcdef",
        profile_fingerprint="abcdef0123456789",
        center_path="config/centro.toml",
        profile_path="config/llegadas.toml",
        invariant_violations=0,
        window_arrivals=615,
        simulation_seconds=0.25,
    )


@pytest.fixture(autouse=True)
def simulation_files(tmp_path, monkeypatch):
    """Isolate center edits and every data-cache entry from other page tests."""
    import streamlit as st

    from edsim_app import defaults

    st.cache_data.clear()
    config = tmp_path / "simulation-config"
    config.mkdir()
    from pathlib import Path

    for name in ("centro.toml", "llegadas.toml"):
        (config / name).write_bytes((Path("config") / name).read_bytes())
    monkeypatch.setattr(defaults, "CENTER_PATH", config / "centro.toml")
    monkeypatch.setattr(defaults, "PROFILE_PATH", config / "llegadas.toml")
    monkeypatch.setattr(defaults, "VARIANTS_DIR", tmp_path / "variants")
    yield config
    st.cache_data.clear()
