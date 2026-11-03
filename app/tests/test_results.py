"""Exercise Resultados through main.py with small, isolated real runs."""

import dataclasses
import shutil
from collections.abc import Mapping
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest
import streamlit as st
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


def test_results_help_explains_immediate_level_model_limit(catalog):
    app = open_results()
    assert not app.exception
    help_box = next(box for box in app.expander if box.label == "¿Qué estoy viendo?")
    text = " ".join(item.value for item in help_box.markdown)
    assert "Puerta-médico incluye la espera de triaje y el propio triaje" in text
    assert "nivel 1 («inmediato», 0 minutos) nunca cumple en el modelo actual" in text
    assert "días con pacientes salen al 100 % fuera de objetivo" in text
    assert "hito 3" in text and "sin prioridad en el triaje" in text and "hito 4" in text


def test_week_labels_show_half_open_intervals(weekly_catalog):
    app = open_results("weekly")
    assert not app.exception
    assert app.selectbox(key="results_week_widget").options == [
        "Semana 1 · [día 0, día 7)",
        "Semana 2 · [día 7, día 8)",
    ]


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


def test_empty_level_is_normal_and_keeps_other_results(catalog):
    import pandas as pd

    from edsim.runs import read_center_values, write_variant

    source = "tests/data/centro_ejemplo.toml"
    values = read_center_values(source)
    values["triaje.reparto_niveles"][0] = 0
    center = catalog.parent / "no-level-one.toml"
    write_variant(source, values, center)
    simulate_run(
        str(center),
        "tests/data/llegadas_ejemplo.toml",
        2,
        7,
        output_dir=catalog / "empty-level",
        run_id="empty-level",
        warmup_days=1,
        origin="app",
    )
    app = open_results("empty-level")
    assert not app.exception and not app.error
    assert app.dataframe[0].value.loc[0, "n"] == 0
    assert pd.isna(app.dataframe[0].value.loc[0, "Puerta-médico media (min)"])
    assert pd.isna(app.dataframe[0].value.loc[0, "Superan el máximo"])
    assert app.dataframe[0].value["n"].sum() > 0
    assert app.metric and len(app.dataframe[2].value) == 3


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


def test_occupancy_and_little_equal_independent_analysis_and_cli(catalog):
    from edsim.engine.analysis import analyze_run
    from edsim.runs import load_center

    app = open_results()
    assert not app.exception
    path = catalog / "older"
    analysis = analyze_run(
        list(read_events(path / "eventos.jsonl")), load_center(path / "centro.toml"), 3, 1
    )
    summary = format_run_summary(analysis, ())
    occupancy = app.dataframe[1].value
    assert len(occupancy) == 9
    assert occupancy["Ocupación"].tolist() == [value.ratio for value in analysis.metrics.occupancy]
    for value in occupancy["Ocupación"]:
        assert f"{100 * value:.1f} %" in summary
    little = app.dataframe[2].value
    assert len(little) == 3
    for row, law in zip(little.to_dict("records"), analysis.little, strict=True):
        assert row["L"] == law.l
        assert row["λ·W"] == law.lam * law.w
        assert row["Error relativo"] == law.relative_error
        assert f"{row['L']:.4f}" in summary
        assert f"{row['λ·W']:.4f}" in summary
        assert f"{100 * row['Error relativo']:.2f} %" in summary
    assert len(app.get("vega_lite_chart")) == 4


def test_downloads_defer_all_five_reads_and_keep_exact_names(catalog, monkeypatch):
    download = Mock(wraps=st.download_button)
    original = RunStore.read_file
    read = Mock(wraps=original)

    def record(self, run_id, filename):
        return read(self, run_id, filename)

    monkeypatch.setattr(st, "download_button", download)
    monkeypatch.setattr(RunStore, "read_file", record)
    app = open_results()
    app.run()
    assert not app.exception
    assert all(call.args[2] == "run.json" for call in read.call_args_list)
    calls = [
        call.kwargs
        for call in download.call_args_list
        if call.kwargs["key"].startswith("download_result_")
    ][-5:]
    assert {call["file_name"] for call in calls} == {
        "eventos.jsonl",
        "ground_truth_episodios.csv",
        "ground_truth_dias.csv",
        "centro.toml",
        "llegadas.toml",
    }
    assert len(app.get("download_button")) == 5
    for call in calls:
        assert call["on_click"] == "ignore" and callable(call["data"])
        assert call["data"]() == (catalog / "older" / call["file_name"]).read_bytes()


def assert_same_result(actual, expected):
    """Compare nested dataclasses, maps and arrays including NaNs and every field."""
    assert type(actual) is type(expected)
    if dataclasses.is_dataclass(actual):
        for field in dataclasses.fields(actual):
            assert_same_result(getattr(actual, field.name), getattr(expected, field.name))
    elif isinstance(actual, np.ndarray):
        np.testing.assert_array_equal(actual, expected)
    elif isinstance(actual, Mapping):
        assert actual.keys() == expected.keys()
        for key in actual:
            assert_same_result(actual[key], expected[key])
    elif isinstance(actual, tuple):
        assert len(actual) == len(expected)
        for first, second in zip(actual, expected, strict=True):
            assert_same_result(first, second)
    else:
        assert actual == expected


def test_plot_choices_survive_navigation_clamp_and_never_mutate_cached_result(weekly_catalog):
    store = RunStore(weekly_catalog)
    _, fingerprint = read_run_header(store, "weekly")
    shared = results.cached_run_results(str(store.root), "weekly", fingerprint)
    app = open_results("weekly")
    assert not app.exception
    for curve in (
        "census",
        "waiting_triage",
        "waiting_box",
        "nurses_busy",
        "doctors_busy",
        "boxes_busy",
    ):
        app.selectbox(key="results_curve_widget").select(curve).run()
        app.selectbox(key="results_week_widget").select(1).run()
        assert not app.exception
        app.run()
    app.switch_page("views/runs.py").run()
    app.switch_page("views/results.py").run()
    assert not app.exception
    assert app.selectbox(key="results_week_widget").value == 1
    assert app.selectbox(key="results_curve_widget").value == "boxes_busy"
    assert results.cached_run_results(str(store.root), "weekly", fingerprint) is shared
    assert_same_result(shared, read_run_results(store, "weekly"))
    app.switch_page("views/runs.py").run()
    app.selectbox(key="run_choice").select("older").run()
    app.switch_page("views/results.py").run()
    assert not app.exception
    assert app.selectbox(key="results_week_widget").value == 0
    assert app.selectbox(key="results_curve_widget").value == "boxes_busy"
