"""Exercise episode exploration through the real app entrypoint."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from fragment_runner import FragmentRunner
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
    assert not app.metric and not app.get("vega_lite_chart")


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


def test_card_has_basics_timeline_log_and_lazy_truth(catalog, monkeypatch):
    import json

    read = Mock(wraps=results.read_run_episode_truth)
    monkeypatch.setattr(results, "read_run_episode_truth", read)
    app = open_episodes("older", "EP-000000")
    assert not app.exception and not app.error
    assert any("Ficha del episodio EP-000000" == item.value for item in app.subheader)
    assert {item.label for item in app.metric} == {
        "Llegada (UTC+1)",
        "Nivel",
        "Destino",
        "Estancia",
    }
    assert app.get("vega_lite_chart")
    events = app.dataframe[1].value
    assert events["event_type"].iloc[0] == "patient_arrived"
    assert events["episode_id"].unique().tolist() == ["EP-000000"]
    assert json.loads(events["payload"].iloc[0]) == {}
    assert read.call_count == 0
    app.toggle(key="episode_truth_widget").set_value(True).run()
    assert not app.exception and not app.error
    assert set(app.dataframe[2].value["Estado"]) <= {"Coincide", "No usada"}
    assert len(app.dataframe[2].value) == 6
    app.run()
    app.selectbox(key="episode_filter_arrival_day_widget").select(0).run()
    assert not app.exception and read.call_count == 1
    app.button(key="episode_open_replay").click().run()
    assert not app.exception and app.title[0].value == "Replay"
    from edsim.runs import read_run_header

    _, fingerprint = read_run_header(RunStore(catalog), "older")
    position = app.session_state["replay_positions"][(str(catalog), "older", fingerprint)]
    assert position.time == events["sim_time"].iloc[0]
    assert not position.playing and position.highlighted_episode == "EP-000000"
    assert any('data-mark="highlight"' in item.proto.body for item in app.get("html"))


def test_unfinished_card_shows_censoring_and_partial_truth(catalog):
    result = read_run_results(RunStore(catalog), "older")
    record = next(record for record in result.analysis.table if record.departure is None)
    app = open_episodes("older", record.episode_id)
    assert not app.exception
    assert next(item.value for item in app.metric if item.label == "Estancia") == "—"
    assert any("cota inferior de la estancia" in item.value for item in app.caption)
    app.toggle(key="episode_truth_widget").set_value(True).run()
    assert not app.exception and not app.error
    statuses = set(app.dataframe[2].value["Estado"])
    assert "Discrepancia" not in statuses and "Pendiente" in statuses


def test_missing_truth_is_lazy_error_and_keeps_card(catalog):
    (catalog / "older" / "ground_truth_episodios.csv").unlink()
    app = open_episodes("older", "EP-000000")
    assert not app.exception and not app.error and app.metric
    app.toggle(key="episode_truth_widget").set_value(True).run()
    assert not app.exception and "ground_truth_episodios.csv" in app.error[0].value
    assert app.metric and app.get("vega_lite_chart")


def test_truth_missing_selected_episode_has_message_and_keeps_card(catalog):
    path = catalog / "older" / "ground_truth_episodios.csv"
    path.write_bytes(b"".join(path.read_bytes().splitlines(keepends=True)[:2]))
    app = open_episodes("older", "EP-000001")
    app.toggle(key="episode_truth_widget").set_value(True).run()
    assert not app.exception and app.metric
    assert "no contiene el episodio EP-000001" in app.error[0].value


def test_no_completed_window_shows_analysis_error_with_header(catalog):
    from edsim.engine.events import read_events, to_json

    path = catalog / "older" / "eventos.jsonl"
    events = [event for event in read_events(path) if event.sim_time < 1440]
    path.write_text("".join(to_json(event) + "\n" for event in events))
    app = open_episodes()
    assert not app.exception and app.header[0].value == "older"
    assert "no tiene episodios completados" in app.error[0].value
    assert not app.dataframe and not app.metric


def test_bad_indexed_event_is_read_error_with_file_line_and_no_card(catalog):
    app = open_episodes()
    from edsim.runs import read_run_header

    store = RunStore(catalog)
    _, fingerprint = read_run_header(store, "older")
    index = results.cached_episode_event_index(str(catalog), "older", fingerprint)
    offset, line = index.positions["EP-000000"][0]
    path = catalog / "older" / "eventos.jsonl"
    data = path.read_bytes()
    offset = int(offset)
    stop = data.index(b"\n", offset)
    path.write_bytes(data[:offset] + b"{" + b" " * (stop - offset - 1) + data[stop:])
    app.selectbox(key="episode_choice_widget").select("EP-000000").run()
    assert not app.exception and not app.metric and not app.get("vega_lite_chart")
    assert app.error[0].value.startswith(f"{path}:{int(line)}:")


def test_index_and_card_reads_are_cached_and_results_does_not_build_index(catalog, monkeypatch):
    index_read = Mock(wraps=results.build_episode_event_index)
    event_read = Mock(wraps=results.read_episode_events)
    monkeypatch.setattr(results, "build_episode_event_index", index_read)
    monkeypatch.setattr(results, "read_episode_events", event_read)
    app = AppTest.from_file(MAIN, default_timeout=20)
    app.query_params["run"] = "older"
    app.run().switch_page("views/results.py").run()
    assert not app.exception and app.metric and index_read.call_count == 0
    app.switch_page("views/episodes.py").run()
    assert index_read.call_count == 1 and event_read.call_count == 0
    app.selectbox(key="episode_choice_widget").select("EP-000000").run()
    app.selectbox(key="episode_filter_arrival_day_widget").select(0).run()
    app.run()
    assert not app.exception and app.metric
    assert index_read.call_count == event_read.call_count == 1


@pytest.mark.parametrize("kind", ["index", "truth"])
def test_episode_resource_caches_include_root_and_fingerprint_and_limit_four(
    catalog, tmp_path, monkeypatch, kind
):
    import shutil

    from edsim.runs import read_run_header

    _, fingerprint = read_run_header(RunStore(catalog), "older")
    cached = results.cached_episode_event_index if kind == "index" else results.cached_episode_truth
    name = "build_episode_event_index" if kind == "index" else "read_run_episode_truth"
    read = Mock(wraps=getattr(results, name))
    monkeypatch.setattr(results, name, read)
    first = cached(str(catalog), "older", fingerprint)
    assert cached(str(catalog), "older", fingerprint) is first
    assert read.call_count == 1
    other = tmp_path / "other"
    shutil.copytree(catalog, other)
    assert cached(str(other), "older", fingerprint) is not first
    cached.clear()
    for key in range(5):
        cached(str(catalog), "older", str(key))
    assert read.call_count == 7
    cached(str(catalog), "older", "0")
    assert read.call_count == 8


def test_episodes_help_explains_censoring_and_lab_work(catalog):
    app = open_episodes()
    box = next(item for item in app.expander if item.label == "¿Qué estoy viendo?")
    text = " ".join(item.value for item in box.markdown)
    assert "cota inferior" in text and "Las pruebas siguen aunque pierda el box" in text
    assert "parcial" in text and "UTC+1 fijo" in text


def test_fragment_selection_and_truth_do_not_rebuild_table_or_initialize_state(
    catalog, monkeypatch
):
    import edsim_app.frames as frames
    import edsim_app.state as state

    frame = Mock(wraps=frames.episodes_frame)
    initialize = Mock(wraps=state.initialize_state)
    monkeypatch.setattr(frames, "episodes_frame", frame)
    monkeypatch.setattr(state, "initialize_state", initialize)
    with FragmentRunner() as runner:
        app = open_episodes()
        assert frame.call_count == 1
        before_initializations = initialize.call_count
        before_table = app.dataframe[0].value.copy(deep=True)
        table_bytes = app.dataframe[0].proto.arrow_data.data
        app.selectbox(key="episode_choice_widget").select("EP-000000")
        runner.run_fragment(app)
        assert not app.exception and app.metric and app.get("vega_lite_chart")
        assert app.query_params["run"] == "older" and app.query_params["episodio"] == "EP-000000"
        assert frame.call_count == 1 and initialize.call_count == before_initializations
        assert app.dataframe[0].value.equals(before_table)
        assert app.dataframe[1].value["event_type"].iloc[0] == "patient_arrived"
        sent_frames = [
            message.delta.new_element.dataframe
            for message in runner.new_messages
            if message.HasField("delta") and message.delta.new_element.HasField("dataframe")
        ]
        assert len(sent_frames) == 1
        assert all(frame.arrow_data.data != table_bytes for frame in sent_frames)
        assert len(app.expander) >= 3
        app.toggle(key="episode_truth_widget").set_value(True)
        runner.run_fragment(app)
        assert not app.exception and len(app.dataframe[2].value) == 6
        assert "Discrepancia" not in app.dataframe[2].value["Estado"].tolist()
        sent_frames = [
            message.delta.new_element.dataframe
            for message in runner.new_messages
            if message.HasField("delta") and message.delta.new_element.HasField("dataframe")
        ]
        assert len(sent_frames) == 2
        assert all(frame.arrow_data.data != table_bytes for frame in sent_frames)
        assert frame.call_count == 1 and initialize.call_count == before_initializations
        assert runner.partial_runs == 2
        app.selectbox(key="episode_choice_widget").select(None)
        runner.run_fragment(app)
        assert not app.exception and not app.metric and not app.get("vega_lite_chart")
        assert "episodio" not in app.query_params and app.query_params["run"] == "older"
        assert frame.call_count == 1


def test_filter_after_partial_run_rebuilds_table_and_hides_excluded_card(catalog, monkeypatch):
    import edsim_app.frames as frames

    frame = Mock(wraps=frames.episodes_frame)
    monkeypatch.setattr(frames, "episodes_frame", frame)
    with FragmentRunner() as runner:
        app = open_episodes()
        level = int(app.dataframe[0].value["Nivel"].iloc[0])
        app.selectbox(key="episode_choice_widget").select("EP-000000")
        runner.run_fragment(app)
        assert not app.exception and app.metric and frame.call_count == 1
        app.selectbox(key="episode_filter_level_widget").select(level % 5 + 1).run()
        assert not app.exception and frame.call_count == 2
        assert "no pasa los filtros" in app.warning[0].value
        assert not app.metric and not app.get("vega_lite_chart")
        assert app.query_params["episodio"] == "EP-000000"


def test_partial_selection_survives_navigation_and_stays_per_run(catalog):
    with FragmentRunner() as runner:
        app = open_episodes()
        app.selectbox(key="episode_choice_widget").select("EP-000000")
        runner.run_fragment(app)
        assert not app.exception and app.query_params["episodio"] == "EP-000000"
        change_run(app, "newer")
        assert not app.metric and app.selectbox(key="episode_choice_widget").value is None
        app.selectbox(key="episode_choice_widget").select("EP-000001")
        runner.run_fragment(app)
        assert app.query_params["episodio"] == "EP-000001" and not app.exception
        change_run(app, "older")
        assert app.selectbox(key="episode_choice_widget").value == "EP-000000"
        assert app.metric and app.query_params["episodio"] == "EP-000000"
        app.query_params.clear()
        app.switch_page("views/results.py").run()
        app.switch_page("views/episodes.py").run()
        assert not app.exception and app.metric
        assert app.query_params["episodio"] == "EP-000000"
