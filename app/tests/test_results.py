"""Exercise Resultados through main.py with small, isolated real runs."""

import dataclasses
import shutil
from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

import edsim_app
from edsim.engine.events import read_events, to_json
from edsim.engine.report import format_run_summary
from edsim.runs import RunStore, Violation, read_run_header, read_run_results, simulate_run
from edsim_app import results

MAIN = Path(edsim_app.__file__).with_name("main.py")


def open_results(run_id="older"):
    app = AppTest.from_file(MAIN, default_timeout=15)
    if run_id is not None:
        app.query_params["run"] = run_id
    app.run()
    app.switch_page("views/results.py").run()
    assert app.title[0].value == "Resultados"
    return app


def test_selected_header_kpis_waits_and_cli_numbers(catalog):
    app = open_results()
    expected = read_run_results(RunStore(catalog), "older")
    summary = format_run_summary(expected.analysis, ())
    assert not app.exception and not app.error
    assert app.header[0].value == "older"
    assert app.query_params["run"] == "older"
    captions = " ".join(item.value for item in app.caption)
    assert "Días: 3 · Calentamiento: 1 días · Semilla: 7" in captions
    assert "Fecha de creación (UTC+1): 02/11/2026 13:00:00" in captions
    assert f"Episodios completados: {expected.kpis.n}" in captions
    metrics = {item.label: item.value for item in app.metric}
    assert len(metrics) == 9
    for label, value, unit in (
        ("Llegadas por día", expected.kpis.arrivals_per_day, "pacientes/día"),
        ("Estancia media", expected.kpis.stay_mean, "min"),
        ("Estancia p90", expected.kpis.stay_p90, "min"),
        ("Puerta-médico media", expected.kpis.door_to_doctor_mean, "min"),
        ("Puerta-médico p90", expected.kpis.door_to_doctor_p90, "min"),
    ):
        assert metrics[label] == f"{value:.1f} {unit}".replace(".", ",")
        assert f"{value:.1f}" in summary
    assert expected.kpis.arrivals_per_day == expected.info.arrivals_per_day
    waits = app.dataframe[0].value
    assert waits["Nivel"].tolist() == [1, 2, 3, 4, 5]
    assert waits["n"].sum() == expected.kpis.n
    assert waits["Estancia media (min)"].tolist() == [
        level.mean["stay"] for level in expected.analysis.metrics.by_level
    ]
    assert "Invariantes: 0 violaciones" in [item.value for item in app.success]
    assert app.get("vega_lite_chart")
    assert "ground truth" in " ".join(item.value for item in app.markdown)


def test_no_selection_asks_for_catalog(catalog_root):
    app = open_results(None)
    assert not app.exception and not app.error
    assert "Elige una ejecución en Ejecuciones" in app.info[0].value
    assert not app.metric


@pytest.mark.parametrize("filename", ["centro.toml", "llegadas.toml", "eventos.jsonl"])
def test_input_error_shows_filename_with_header(catalog, filename):
    (catalog / "older" / filename).write_text("[broken")
    app = open_results()
    assert not app.exception
    assert app.header[0].value == "older"
    assert filename in app.error[0].value
    assert not app.metric


def test_empty_completed_window_keeps_header_and_explains_modified_log(catalog):
    path = catalog / "older" / "eventos.jsonl"
    events = [event for event in read_events(path) if event.sim_time < 1440]
    path.write_text("".join(to_json(event) + "\n" for event in events))
    app = open_results()
    assert not app.exception
    assert app.header[0].value == "older"
    assert "no tiene episodios completados" in app.error[0].value
    assert "modificado fuera de la app" in app.error[0].value
    assert not app.metric


@pytest.mark.parametrize("error_type", [ValueError, RuntimeError, OSError])
def test_internal_analysis_error_remains_an_exception(catalog, monkeypatch, error_type):
    def fail(*args, **kwargs):
        raise error_type("injected internal analysis failure")

    monkeypatch.setattr("edsim.runs.results.analyze_run", fail)
    app = open_results()
    assert len(app.exception) == 1
    assert app.exception[0].message == "injected internal analysis failure"
    assert not app.error


@pytest.mark.parametrize("kind", ["deleted", "broken"])
def test_open_on_reload_prevents_old_cached_results(catalog, monkeypatch, kind):
    calculate = Mock(wraps=results.read_run_results)
    monkeypatch.setattr(results, "read_run_results", calculate)
    app = open_results()
    assert not app.exception and app.metric
    if kind == "deleted":
        shutil.rmtree(catalog / "older")
    else:
        (catalog / "older" / "run.json").write_text("[broken")
    app.run()
    assert not app.exception
    assert not app.metric
    assert app.session_state["selected_run_id"] is None
    assert "run" not in app.query_params
    assert "Motivo:" in app.warning[0].value
    assert calculate.call_count == 1


def test_resource_cache_reloads_recreated_run(catalog, monkeypatch):
    calculate = Mock(wraps=results.read_run_results)
    monkeypatch.setattr(results, "read_run_results", calculate)
    app = open_results()
    first = app.dataframe[0].value.copy()
    app.run()
    assert calculate.call_count == 1
    shutil.rmtree(catalog / "older")
    simulate_run(
        "tests/data/centro_ejemplo.toml",
        "tests/data/llegadas_ejemplo.toml",
        3,
        9,
        output_dir=catalog / "older",
        run_id="older",
        warmup_days=1,
        origin="app",
    )
    app.run()
    assert not app.exception
    assert calculate.call_count == 2
    assert not first.equals(app.dataframe[0].value)
    expected = read_run_results(RunStore(catalog), "older")
    assert app.dataframe[0].value["n"].sum() == expected.kpis.n


def test_resource_cache_includes_catalog_root_and_limits_entries(catalog, tmp_path, monkeypatch):
    store = RunStore(catalog)
    _, fingerprint = read_run_header(store, "older")
    first = results.cached_run_results(str(catalog), "older", fingerprint)
    assert first is results.cached_run_results(str(catalog), "older", fingerprint)
    other = tmp_path / "other"
    shutil.copytree(catalog, other)
    second = results.cached_run_results(str(other), "older", fingerprint)
    assert second is not first
    results.cached_run_results.clear()
    calculate = Mock(return_value=first)
    monkeypatch.setattr(results, "read_run_results", calculate)
    for index in range(5):
        results.cached_run_results(str(catalog), "older", str(index))
    assert calculate.call_count == 5
    results.cached_run_results(str(catalog), "older", "0")
    assert calculate.call_count == 6


@pytest.mark.parametrize("saved,recalculated", [(12, 12), (17, 12), (1, 0)])
def test_invariants_limit_counts_and_mismatch(catalog, monkeypatch, saved, recalculated):
    store = RunStore(catalog)
    dataclasses.replace(store.open("older"), invariant_violations=saved).write(
        catalog / "older" / "run.json"
    )
    violations = [
        Violation("capacity" if index % 2 else "time", f"violation-{index}", sim_time=index)
        for index in range(recalculated)
    ]
    check = Mock(return_value=violations)
    monkeypatch.setattr("edsim.runs.results.check_invariants", check)
    app = open_results()
    assert not app.exception
    assert check.call_count == 1
    visible = " ".join(item.value for item in app.markdown)
    for index in range(min(recalculated, 10)):
        assert f"violation-{index}" in visible
    assert "violation-10" not in visible
    assert "Recuento por comprobación:" in visible
    assert bool(app.warning) == (saved != recalculated)
    if saved != recalculated:
        assert f"recalculado ({recalculated})" in app.warning[0].value
