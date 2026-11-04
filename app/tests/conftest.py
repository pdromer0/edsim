"""Isolate every page from real runs and supply reproducible catalog artifacts."""

import shutil
from datetime import UTC, datetime
from pathlib import Path

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
def weekly_catalog(catalog):
    """Eight days is the smallest horizon that exercises a second weekly block."""
    simulate_run(
        "tests/data/centro_ejemplo.toml",
        "tests/data/llegadas_ejemplo.toml",
        8,
        7,
        output_dir=catalog / "weekly",
        run_id="weekly",
        warmup_days=1,
        origin="app",
    )
    return catalog


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

    from edsim.runs import offered_work
    from edsim_app import defaults, preview

    st.cache_data.clear()
    st.cache_resource.clear()
    config = tmp_path / "simulation-config"
    config.mkdir()
    for name in ("centro.toml", "llegadas.toml"):
        (config / name).write_bytes((Path("config") / name).read_bytes())
    monkeypatch.setattr(defaults, "CENTER_PATH", config / "centro.toml")
    monkeypatch.setattr(defaults, "PROFILE_PATH", config / "llegadas.toml")
    monkeypatch.setattr(defaults, "VARIANTS_DIR", tmp_path / "variants")
    monkeypatch.setattr(
        preview,
        "offered_work",
        lambda center, profile, days: offered_work(center, profile, days, sample_size=32),
    )
    yield config
    st.cache_data.clear()
    st.cache_resource.clear()


# Collection-time marks preserve the A.5 characterization files byte for byte.
# Shared catalog fixtures simulate real runs; retain explicit page smoke checks
# in the fast suite instead of repeatedly analyzing those runs in every AppTest.
_SIMULATION_TESTS = frozenset(
    {
        "test_real_one_day_simulation_uses_saved_variant_and_opens_results",
        "test_simulation_passes_relative_paths_output_and_no_variant",
        "test_preview_displays_core_table_caches_edits_and_profile_fingerprint",
        "test_preview_explains_multiple_prior_days",
    }
)


def pytest_collection_modifyitems(items):
    """Keep simulation-heavy integrations in CI and six catalog smoke checks fast."""
    for item in items:
        if item.path.name == "test_smoke.py":
            continue
        if item.path.name not in {
            "test_compare.py",
            "test_episodes.py",
            "test_navigation.py",
            "test_results.py",
            "test_runs.py",
            "test_simulate.py",
        }:
            continue
        if "run_templates" in item.fixturenames or item.originalname in _SIMULATION_TESTS:
            item.add_marker(pytest.mark.slow)
