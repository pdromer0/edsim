"""Compare real temporary runs through main.py, including independent side failures."""

import shutil
from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

import edsim_app
from edsim.runs import RunStore, read_run_results, simulate_run
from edsim_app import results
from edsim_app.comparison_frames import comparison_kpis_frame, comparison_levels_frame

MAIN = Path(edsim_app.__file__).with_name("main.py")


def open_compare(a="older", b="newer"):
    app = AppTest.from_file(MAIN, default_timeout=20)
    app.session_state["compare_a"] = a
    app.session_state["compare_b"] = b
    app.run().switch_page("views/compare.py").run()
    assert app.title[0].value == "Comparar"
    return app


def summary_frames(app):
    kpis = next(item.value for item in app.dataframe if "Cambio relativo" in item.value)
    levels = next(item.value for item in app.dataframe if "n A" in item.value)
    return kpis, levels


def test_unpaired_summary_matches_core_and_does_not_read_truth(catalog, monkeypatch):
    from edsim.runs import compare_run_summary

    read_truth = Mock(side_effect=AssertionError("nonpaired runs must not read truth"))
    monkeypatch.setattr(results, "read_run_episode_truth", read_truth)
    app = open_compare()
    assert not app.exception and not app.error
    assert "No emparejada" in " ".join(item.value for item in app.info)
    assert "Semilla" in " ".join(item.value for item in app.info)
    assert not read_truth.called
    store = RunStore(catalog)
    expected = compare_run_summary(
        read_run_results(store, "older"), read_run_results(store, "newer")
    )
    kpis, levels = summary_frames(app)
    assert kpis.equals(comparison_kpis_frame(expected)) and len(kpis) == 9
    assert levels.equals(comparison_levels_frame(expected)) and len(levels) == 5
    captions = " ".join(item.value for item in app.caption)
    assert f"sin terminar: {expected.unfinished_a}" in captions
    assert f"sin terminar: {expected.unfinished_b}" in captions
    assert expected.unfinished_a != expected.unfinished_b
    assert any("más pacientes sin terminar" in item.value for item in app.warning)
    assert not any("Paciente a paciente" == item.value for item in app.subheader)
    assert not any("Terminan solo en A" in item.value for item in app.caption)
    assert any("hito 9" in item.value for item in app.warning)


def test_marks_are_shared_both_directions_and_selection_is_independent(catalog):
    app = AppTest.from_file(MAIN).run()
    app.selectbox(key="run_choice").select("older").run()
    app.button(key="mark_a").click().run()
    app.selectbox(key="run_choice").select("newer").run()
    app.button(key="mark_b").click().run()
    app.switch_page("views/compare.py").run()
    assert app.selectbox(key="compare_a_widget").value == "older"
    assert app.selectbox(key="compare_b_widget").value == "newer"
    app.selectbox(key="compare_a_widget").select("newer").run()
    app.selectbox(key="compare_b_widget").select("older").run()
    assert app.session_state["selected_run_id"] == "newer"
    assert app.query_params["run"] == "newer"
    app.switch_page("views/runs.py").run()
    assert "Marca A: newer" in [item.value for item in app.sidebar.markdown]
    assert "Marca B: older" in [item.value for item in app.sidebar.markdown]
    app.switch_page("views/compare.py").run()
    assert app.selectbox(key="compare_a_widget").value == "newer"
    assert app.selectbox(key="compare_b_widget").value == "older"
    assert not app.exception


def test_empty_choices_and_one_available_side(catalog):
    app = open_compare(None, None)
    assert not app.exception and not app.dataframe
    app.selectbox(key="compare_a_widget").select("older").run()
    assert any("Resultados disponibles de A" == item.value for item in app.subheader)
    assert not any("Cambio relativo" in item.value for item in app.dataframe)
    app.selectbox(key="compare_a_widget").select(None).run()
    assert app.session_state["compare_a"] is None
    assert not app.dataframe


@pytest.mark.parametrize("side,run_id", [("A", "older"), ("B", "newer")])
@pytest.mark.parametrize("filename", ["run.json", "centro.toml", "llegadas.toml", "eventos.jsonl"])
def test_each_side_error_keeps_other_results(catalog, side, run_id, filename):
    (catalog / run_id / filename).write_text("[broken")
    app = open_compare()
    assert not app.exception
    assert any(f"Lado {side}" in item.value and filename in item.value for item in app.error)
    other = "B" if side == "A" else "A"
    assert any(item.value == f"Resultados disponibles de {other}" for item in app.subheader)
    assert any(item.value.startswith(f"{other}:") for item in app.header)
    assert not any("Cambio relativo" in item.value for item in app.dataframe)


def test_results_cache_is_shared_and_recreation_invalidates(catalog, monkeypatch):
    read = Mock(wraps=results.read_run_results)
    monkeypatch.setattr(results, "read_run_results", read)
    app = open_compare()
    app.run()
    assert not app.exception and read.call_count == 2
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
    assert not app.exception and read.call_count == 3
    app.switch_page("views/runs.py").run()
    app.selectbox(key="run_choice").select("older").run()
    app.switch_page("views/results.py").run()
    assert app.title[0].value == "Resultados" and app.metric
    assert read.call_count == 3


def test_unexpected_analysis_failure_is_not_hidden(catalog, monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("programming error")

    monkeypatch.setattr(results, "read_run_results", fail)
    app = open_compare()
    assert app.exception and app.exception[0].message == "programming error"
    assert not app.error


def test_presentation_has_signed_pp_relative_percent_and_undefined_values(catalog):
    from dataclasses import replace

    from edsim.runs import KPIComparison, compare_run_summary

    a = read_run_results(RunStore(catalog), "older")
    summary = compare_run_summary(a, a)
    summary = replace(
        summary,
        kpis=(
            KPIComparison("admission_share", 0.2, 0.3, 0.1, 0.5),
            KPIComparison("census_mean", 0, 10, 10, None),
            KPIComparison("stay_mean", None, 20, None, None),
        ),
    )
    rows = comparison_kpis_frame(summary).set_index("Indicador")
    assert rows.loc["Ingreso"].to_dict() == {
        "Unidad": "%",
        "A": "20,0 %",
        "B": "30,0 %",
        "B − A": "+10,0 pp",
        "Cambio relativo": "+50,0 %",
    }
    assert rows.loc["Censo medio", "Cambio relativo"] == "—"
    assert rows.loc["Estancia media", "B − A"] == "—"
    assert summary.kpis[0].difference == 0.1
