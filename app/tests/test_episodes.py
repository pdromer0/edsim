"""Exercise episode exploration through the real app entrypoint."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

import edsim_app
from edsim.runs import EpisodeFilters, RunStore, filter_episodes, read_run_results, simulate_run
from edsim_app import results

MAIN = Path(edsim_app.__file__).with_name("main.py")


def open_episodes(run_id="older", episode=None):
    app = AppTest.from_file(MAIN, default_timeout=20)
    if run_id is not None:
        app.query_params["run"] = run_id
    if episode is not None:
        app.query_params["episodio"] = episode
    app.run()
    app.switch_page("views/episodes.py").run()
    assert app.title[0].value == "Episodios"
    return app


def change_run(app, run_id):
    app.switch_page("views/runs.py").run()
    app.selectbox(key="run_choice").select(run_id).run()
    app.switch_page("views/episodes.py").run()
    assert app.title[0].value == "Episodios" and not app.exception


def test_table_and_filter_values_match_public_core(catalog):
    app = open_episodes()
    expected = read_run_results(RunStore(catalog), "older")
    assert not app.exception and not app.error
    assert app.header[0].value == "older"
    assert len(app.dataframe[0].value) == len(expected.analysis.table) > 0
    app.selectbox(key="episode_filter_level_widget").select(3).run()
    app.selectbox(key="episode_filter_period_widget").select("window").run()
    filtered = filter_episodes(
        expected.analysis.table,
        EpisodeFilters(level=3, period="window"),
        warmup_end=1440,
        horizon=4320,
    )
    assert filtered and not app.exception
    assert app.dataframe[0].value["Episodio"].tolist() == [record.episode_id for record in filtered]
    assert f"{len(filtered)} de {len(expected.analysis.table)} episodios" in app.caption[0].value


def test_no_run_or_missing_run_has_clear_message(catalog):
    app = open_episodes(None)
    assert not app.exception and not app.dataframe
    assert "Elige una ejecución" in app.info[0].value
    app = open_episodes("absent", "EP-000000")
    assert not app.exception and not app.dataframe
    assert "episodio" not in app.query_params


@pytest.mark.parametrize("filename", ["eventos.jsonl", "centro.toml"])
def test_read_errors_preserve_header(catalog, filename):
    (catalog / "older" / filename).write_text("[broken")
    app = open_episodes()
    assert not app.exception
    assert app.header[0].value == "older"
    assert filename in app.error[0].value and not app.dataframe


def test_common_filters_survive_navigation_and_run_change(catalog):
    app = open_episodes()
    app.selectbox(key="episode_filter_level_widget").select(3).run()
    app.selectbox(key="episode_filter_period_widget").select("window").run()
    app.number_input(key="episode_filter_stay_gt_widget").set_value(10.0).run()
    change_run(app, "newer")
    assert app.selectbox(key="episode_filter_level_widget").value == 3
    assert app.selectbox(key="episode_filter_period_widget").value == "window"
    assert app.number_input(key="episode_filter_stay_gt_widget").value == 10.0
    assert len(app.dataframe[0].value) > 0


def test_out_of_range_day_is_clamped_and_explained(weekly_catalog):
    app = open_episodes("weekly")
    app.selectbox(key="episode_filter_arrival_day_widget").select(7).run()
    assert not app.exception and len(app.dataframe[0].value) > 0
    change_run(app, "older")
    assert app.selectbox(key="episode_filter_arrival_day_widget").value == 2
    assert any("se ajusta al día 2" in message.value for message in app.info)
    assert len(app.dataframe[0].value) > 0


def test_episode_selection_and_link_survive_navigation_per_run(catalog):
    app = open_episodes()
    older = app.dataframe[0].value["Episodio"].iloc[0]
    app.selectbox(key="episode_choice_widget").select(older).run()
    assert app.query_params["episodio"] == older
    change_run(app, "newer")
    assert app.selectbox(key="episode_choice_widget").value is None
    newer = app.dataframe[0].value["Episodio"].iloc[1]
    assert older != newer
    app.selectbox(key="episode_choice_widget").select(newer).run()
    change_run(app, "older")
    assert app.selectbox(key="episode_choice_widget").value == older
    assert app.query_params["run"] == "older" and app.query_params["episodio"] == older
    app.query_params.clear()
    app.switch_page("views/results.py").run()
    app.switch_page("views/episodes.py").run()
    assert app.selectbox(key="episode_choice_widget").value == older
    assert app.query_params["episodio"] == older


def test_initial_link_selects_card_and_unknown_episode_does_not_choose_replacement(catalog):
    app = open_episodes("older", "EP-000000")
    assert not app.exception
    assert app.selectbox(key="episode_choice_widget").value == "EP-000000"
    app = open_episodes("older", "EP-999999")
    assert not app.exception
    assert app.selectbox(key="episode_choice_widget").value is None
    assert "no existe" in app.warning[0].value
    assert app.query_params["episodio"] == "EP-999999"


def test_episode_excluded_by_filters_has_message_and_no_selection(catalog):
    app = open_episodes("older", "EP-000000")
    level = int(app.dataframe[0].value["Nivel"].iloc[0])
    app.selectbox(key="episode_filter_level_widget").select(level % 5 + 1).run()
    assert not app.exception and "no pasa los filtros" in app.warning[0].value
    assert app.selectbox(key="episode_choice_widget").value is None
    assert app.query_params["episodio"] == "EP-000000"


def test_recreated_run_forgets_episode_but_keeps_filters(catalog):
    import shutil

    app = open_episodes("older", "EP-000000")
    app.selectbox(key="episode_filter_period_widget").select("window").run()
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
    assert app.selectbox(key="episode_choice_widget").value is None
    assert "episodio" not in app.query_params
    assert app.selectbox(key="episode_filter_period_widget").value == "window"


def test_results_cache_is_shared_and_filters_do_not_reread_log(catalog, monkeypatch):
    read = Mock(wraps=results.read_run_results)
    monkeypatch.setattr(results, "read_run_results", read)
    app = open_episodes()
    app.selectbox(key="episode_filter_level_widget").select(3).run()
    app.switch_page("views/results.py").run()
    app.switch_page("views/episodes.py").run()
    assert not app.exception and len(app.dataframe[0].value) > 0
    assert read.call_count == 1
