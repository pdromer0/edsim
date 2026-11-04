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


@pytest.fixture(scope="session")
def comparison_templates(tmp_path_factory):
    from edsim.runs import read_center_values, write_variant

    root = tmp_path_factory.mktemp("comparison-app-templates")
    source = "tests/data/centro_ejemplo.toml"
    for name in ("night", "assessment", "probability"):
        values = read_center_values(source)
        if name == "night":
            values["recursos.medicos"][2] += 1
        elif name == "assessment":
            values["duraciones.valoracion"] = [
                value * 1.2 for value in values["duraciones.valoracion"]
            ]
        else:
            values["pruebas.probabilidad"][0] += 1e-12
        path = root / f"{name}.toml"
        write_variant(source, values, path)
        simulate_run(
            path,
            "tests/data/llegadas_ejemplo.toml",
            3,
            7,
            output_dir=root / name,
            run_id=name,
            warmup_days=1,
            origin="app",
        )
    return root


@pytest.fixture
def paired_catalog(catalog, comparison_templates):
    for name in ("night", "assessment", "probability"):
        shutil.copytree(comparison_templates / name, catalog / name)
    return catalog


def test_self_comparison_has_zero_differences_and_all_equal(catalog):
    app = open_compare("older", "older")
    assert not app.exception and not app.error
    assert any("mismos sorteos" in item.value for item in app.success)
    assert len(app.metric) == 6
    assert all("(100,0 %)" in item.value for item in app.metric if "Iguales" in item.label)
    assert all("0 (0,0 %)" == item.value for item in app.metric if "Iguales" not in item.label)
    assert not app.get("vega_lite_chart")
    top = next(item.value for item in app.dataframe if "Episodio" in item.value)
    assert len(top) == 10 and set(top["B − A (min)"]) == {"0,0"}
    draws = next(item.value for item in app.dataframe if "Sorteo" in item.value)
    assert len(draws) == 7 and draws["Pacientes distintos"].sum() == 0
    assert any("Terminan solo en A: 0" in item.value for item in app.caption)


def test_staffing_comparison_has_checked_draws_histograms_and_both_exclusions(paired_catalog):
    from edsim.runs import compare_runs, read_run_episode_truth

    store = RunStore(paired_catalog)
    expected = compare_runs(
        read_run_results(store, "older"),
        read_run_results(store, "night"),
        read_run_episode_truth(store, "older"),
        read_run_episode_truth(store, "night"),
    )
    app = open_compare("older", "night")
    assert not app.exception and not app.error
    assert any("mismos sorteos" in item.value for item in app.success)
    assert app.get("vega_lite_chart") and len(app.metric) == 6
    captions = " ".join(item.value for item in app.caption)
    assert f"Terminan solo en A: {expected.excluded.only_a}" in captions
    assert f"Terminan solo en B: {expected.excluded.only_b}" in captions
    assert f"No terminan en ninguna: {expected.excluded.neither}" in captions
    assert f"sin terminar: {expected.summary.unfinished_a}" in captions
    assert f"sin terminar: {expected.summary.unfinished_b}" in captions
    top = next(item.value for item in app.dataframe if "Episodio" in item.value)
    assert top["Episodio"].tolist() == [e.episode_id for e in expected.most_affected]
    assert len([button for button in app.button if button.key.startswith("compare_open_")]) == 20
    for difference in expected.differences:
        label = "Estancia" if difference.measure == "stay" else "Puerta-médico"
        metric = next(item for item in app.metric if item.label == f"{label}: Mejoran")
        assert metric.value.startswith(f"{difference.improved} (")


@pytest.mark.parametrize("run_id", ["assessment", "probability"])
def test_clinical_category_and_observed_changes(paired_catalog, run_id):
    app = open_compare("older", run_id)
    assert not app.exception and not app.error
    assert any("sorteos distintos" in item.value for item in app.success)
    draws = next(item.value for item in app.dataframe if "Sorteo" in item.value)
    if run_id == "assessment":
        changed = draws.loc[draws["Pacientes distintos"] > 0]
        assert changed["Sorteo"].tolist() == ["Valoración"]
        assert changed.iloc[0]["Pacientes distintos"] == changed.iloc[0]["Total"]
    else:
        assert draws["Pacientes distintos"].sum() == 0
        assert any("ninguno en esta muestra (0 pacientes)" in item.value for item in app.warning)
    assert any(item.value == "Paciente a paciente" for item in app.subheader)


@pytest.mark.parametrize("side,run_id", [("A", "older"), ("B", "night")])
@pytest.mark.parametrize("kind", ["missing", "unreadable", "contradictory"])
def test_truth_failure_keeps_summary_and_blocks_patients(paired_catalog, side, run_id, kind):
    import csv
    import io

    path = paired_catalog / run_id / "ground_truth_episodios.csv"
    if kind == "missing":
        path.unlink()
    elif kind == "unreadable":
        path.write_text("invalid header\n")
    else:
        reader = csv.DictReader(io.StringIO(path.read_text()))
        rows = list(reader)
        rows[0]["nivel"] = str(int(rows[0]["nivel"]) % 5 + 1)
        with path.open("w", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=reader.fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    app = open_compare("older", "night")
    assert not app.exception and app.error
    assert "ground_truth_episodios.csv" in app.error[0].value
    assert "simulate_run" in app.error[0].value and "fuera de la app" in app.error[0].value
    if kind == "contradictory":
        assert "level, 1 pacientes" in app.error[0].value
    kpis, levels = summary_frames(app)
    assert len(kpis) == 9 and len(levels) == 5
    assert not app.success and not app.metric
    assert not any(item.value == "Paciente a paciente" for item in app.subheader)
    assert not any(button.key.startswith("compare_open_") for button in app.button)


@pytest.mark.parametrize("side,run_id", [("A", "older"), ("B", "night")])
def test_link_partial_request_resets_every_filter_and_opens_correct_card(
    paired_catalog,
    side,
    run_id,
    monkeypatch,
):
    from dataclasses import asdict

    from fragment_runner import FragmentRunner

    from edsim.runs import EpisodeFilters, read_run_header
    from edsim_app import comparison, state
    from edsim_app.episodes import episode_identity

    calculate = Mock(wraps=comparison.compare_runs)
    initialize = Mock(wraps=state.initialize_state)
    monkeypatch.setattr(comparison, "compare_runs", calculate)
    monkeypatch.setattr(state, "initialize_state", initialize)
    with FragmentRunner() as runner:
        app = open_compare("older", "night")
        top = next(item.value for item in app.dataframe if "Episodio" in item.value)
        episode = top["Episodio"].iloc[0]
        app.session_state["episode_filters"] = asdict(
            EpisodeFilters(
                level=1,
                destination="ingreso",
                displaced=True,
                arrival_day=0,
                period="warmup",
                door_to_doctor_gt=999999,
                stay_gt=999999,
            )
        )
        before = initialize.call_count
        runner.run_fragment(app, key="comparison_patients")
        assert calculate.call_count == 1 and initialize.call_count == before
        app.button(key=f"compare_open_{side}_{episode}").click()
        runner.run_fragment(app, key="comparison_patients")
        assert not app.exception
        assert app.title[0].value == "Episodios"
        assert app.session_state["selected_run_id"] == run_id
        assert app.query_params["run"] == run_id and app.query_params["episodio"] == episode
        _, fingerprint = read_run_header(RunStore(paired_catalog), run_id)
        identity = episode_identity(str(paired_catalog), run_id, fingerprint)
        assert app.session_state["episode_choices"][identity] == episode
        assert app.session_state["episode_filters"] == asdict(EpisodeFilters())
        assert any("Se han quitado los filtros" in item.value for item in app.info)
        assert any(item.value == f"Ficha del episodio {episode}" for item in app.subheader)
        assert not any("no pasa los filtros" in item.value for item in app.warning)
        assert calculate.call_count == 1
        assert (
            app.session_state["compare_a"] == "older" and app.session_state["compare_b"] == "night"
        )
        assert app.selectbox(key="episode_filter_level_widget").value is None
        assert app.number_input(key="episode_filter_stay_gt_widget").value is None


def test_internal_comparison_value_error_remains_exception(paired_catalog, monkeypatch):
    from edsim_app import comparison

    def fail(*args, **kwargs):
        raise ValueError("comparison programming error")

    monkeypatch.setattr(comparison, "compare_runs", fail)
    app = open_compare("older", "night")
    assert app.exception[0].message == "comparison programming error"
    assert not app.error


def test_pair_cache_reloads_recreated_run(paired_catalog, monkeypatch):
    from edsim_app import comparison

    calculate = Mock(wraps=comparison.compare_runs)
    monkeypatch.setattr(comparison, "compare_runs", calculate)
    app = open_compare("older", "night")
    app.run()
    assert not app.exception and calculate.call_count == 1
    shutil.rmtree(paired_catalog / "night")
    simulate_run(
        paired_catalog / "assessment" / "centro.toml",
        "tests/data/llegadas_ejemplo.toml",
        3,
        7,
        output_dir=paired_catalog / "night",
        run_id="night",
        warmup_days=1,
        origin="app",
    )
    app.run()
    assert not app.exception and calculate.call_count == 2
    assert any("sorteos distintos" in item.value for item in app.success)


def test_pair_cache_includes_both_ordered_identities_and_limits_four(catalog, monkeypatch):
    from edsim.runs import compare_runs, read_run_episode_truth
    from edsim_app import comparison

    store = RunStore(catalog)
    a, truth = read_run_results(store, "older"), read_run_episode_truth(store, "older")
    expected = compare_runs(a, a, truth, truth)
    monkeypatch.setattr(comparison, "cached_run_results", Mock(return_value=a))
    monkeypatch.setattr(comparison, "cached_episode_truth", Mock(return_value=truth))
    calculate = Mock(return_value=expected)
    monkeypatch.setattr(comparison, "compare_runs", calculate)
    cache = comparison.cached_run_comparison
    first = (str(catalog), "a", "fa", "b", "fb")
    assert cache(*first) is expected and cache(*first) is expected
    assert calculate.call_count == 1
    for args in (
        (str(catalog), "b", "fb", "a", "fa"),
        (str(catalog), "a", "fa2", "b", "fb"),
        (str(catalog), "a", "fa", "b", "fb2"),
        (str(catalog.parent / "other"), "a", "fa", "b", "fb"),
    ):
        cache(*args)
    assert calculate.call_count == 5
    cache(*first)
    assert calculate.call_count == 6


@pytest.mark.parametrize("run_id,side", [("older", "A"), ("newer", "B")])
def test_no_completed_window_error_is_independent(catalog, run_id, side):
    (catalog / run_id / "eventos.jsonl").write_text("")
    app = open_compare()
    assert not app.exception
    assert any(
        f"Lado {side}" in item.value and "no tiene episodios completados" in item.value
        for item in app.error
    )
    other = "B" if side == "A" else "A"
    assert any(item.value == f"Resultados disponibles de {other}" for item in app.subheader)
