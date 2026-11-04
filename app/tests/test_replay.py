"""Run Replay through main.py, including real partial ScriptRunner requests."""

from datetime import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from fragment_runner import FragmentRunner
from streamlit.testing.v1 import AppTest

import edsim_app
from edsim.runs import RunStore, read_run_header, read_run_results
from edsim_app import replay, state

pytestmark = pytest.mark.slow
MAIN = Path(edsim_app.__file__).with_name("main.py")


def open_replay(run_id="older"):
    app = AppTest.from_file(MAIN, default_timeout=30)
    if run_id:
        app.query_params["run"] = run_id
    app.run().switch_page("views/replay.py").run()
    assert app.title[0].value == "Replay" and not app.exception
    return app


def position(app, catalog):
    _, fingerprint = read_run_header(RunStore(catalog), "older")
    return app.session_state["replay_positions"][(str(catalog), "older", fingerprint)]


def html(app):
    return " ".join(item.proto.body for item in app.get("html"))


def test_short_run_page_controls_real_data_and_terminal_entry(catalog):
    app = open_replay()
    assert not app.error and app.header[0].value == "older"
    assert 'data-role="box"' in html(app)
    assert any("Censo: 0" in item.value and "Calentamiento" in item.value for item in app.markdown)
    assert app.get("vega_lite_chart")
    assert app.dataframe[0].value["event_type"].tolist() == ["staffing_changed"] * 2
    app.selectbox(key="replay_day_widget").select(3).run()
    expected = read_run_results(RunStore(catalog), "older")
    assert position(app, catalog).time == 4320
    assert app.slider(key="replay_clock_widget").disabled
    assert app.slider(key="replay_clock_widget").value == time(0)
    assert app.button(key="replay_step_1").disabled and app.button(key="replay_play").disabled
    assert len(app.dataframe[1].value) == sum(e.departure is None for e in expected.analysis.table)
    assert any("Fin de la ejecución" in item.value for item in app.markdown)
    app.button(key="replay_step_-10").click().run()
    assert position(app, catalog).time == 4310
    assert app.selectbox(key="replay_day_widget").value == 2
    assert app.slider(key="replay_clock_widget").value == time(23, 50)
    app.slider(key="replay_clock_widget").set_value(time(14, 2)).run()
    assert position(app, catalog).time == 2 * 1440 + 842
    assert "día 2" in " ".join(item.value for item in app.caption)


def test_no_selection_and_read_error_are_visible(catalog):
    app = open_replay(None)
    assert app.info and not app.dataframe
    (catalog / "older" / "eventos.jsonl").write_text("{")
    app = open_replay()
    assert app.error and "eventos.jsonl" in app.error[0].value
    assert app.header[0].value == "older" and not app.get("html")


def test_real_fragment_keeps_details_frozen_then_pause_synchronizes(catalog, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(replay, "clock", lambda: now[0])
    initialize = Mock(wraps=state.initialize_state)
    monkeypatch.setattr(state, "initialize_state", initialize)
    import edsim_app.frames as frames

    details = Mock(wraps=frames.episode_events_frame)
    monkeypatch.setattr(frames, "episode_events_frame", details)
    with FragmentRunner() as runner:
        app = open_replay()
        app.selectbox(key="replay_speed_widget").select(60).run()
        app.button(key="replay_play").click().run()
        before = details.call_count
        inits = initialize.call_count
        for _ in range(3):
            now[0] += 1
            runner.run_fragment(app, key="replay_live")
            assert not app.exception and not app.error
        assert runner.partial_runs == 3
        assert position(app, catalog).time == 180
        assert details.call_count == before and initialize.call_count == inits
        assert app.selectbox(key="replay_day_widget").disabled
        assert app.slider(key="replay_clock_widget").disabled
        assert app.slider(key="replay_clock_widget").value == time(0)
        assert any(
            "Detalles de las 00:00 del día 0; se actualizan al pausar" in c.value
            for c in app.caption
        )
        assert all(
            not (m.HasField("delta") and m.delta.new_element.HasField("dataframe"))
            for m in runner.new_messages
        )
        app.button(key="replay_pause").click().run()
        assert not position(app, catalog).playing
        assert app.slider(key="replay_clock_widget").value == time(3)
        assert details.call_count == before + 1
        assert not any("se actualizan al pausar" in c.value for c in app.caption)


def test_midnight_live_steps_speed_and_auto_pause(catalog, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(replay, "clock", lambda: now[0])
    with FragmentRunner() as runner:
        app = open_replay()
        app.slider(key="replay_clock_widget").set_value(time(23, 59)).run()
        app.button(key="replay_play").click().run()
        now[0] += 1
        runner.run_fragment(app, key="replay_live")
        assert position(app, catalog).time == 1440
        app.button(key="replay_step_-1").click().run()
        assert position(app, catalog).time == 1439 and not position(app, catalog).playing
        app.button(key="replay_play").click().run()
        app.selectbox(key="replay_speed_widget").select(60).run()
        assert position(app, catalog).playing and position(app, catalog).speed == 60
        now[0] += 100
        runner.run_fragment(app, key="replay_live")
        assert not app.exception and not app.error
        assert position(app, catalog).time == 4320 and not position(app, catalog).playing
        assert app.selectbox(key="replay_day_widget").value == 3
        assert any("Fin de la ejecución" in m.value for m in app.markdown)
        assert not any("se actualizan al pausar" in c.value for c in app.caption)
        assert len(app.dataframe[1].value) > 0


def test_leaving_pauses_and_restores_position_speed_and_highlight(catalog, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(replay, "clock", lambda: now[0])
    with FragmentRunner() as runner:
        app = open_replay()
        p = position(app, catalog)
        p.highlighted_episode = "EP-000000"
        app.selectbox(key="replay_speed_widget").select(15).run()
        app.button(key="replay_play").click().run()
        now[0] += 2
        runner.run_fragment(app, key="replay_live")
        assert p.time == 30
        app.switch_page("views/episodes.py").run()
        assert not p.playing
        now[0] += 1000
        app.switch_page("views/replay.py").run()
        assert not app.exception and not p.playing and p.time == 30
        assert p.speed == 15 and p.highlighted_episode == "EP-000000"
        assert app.slider(key="replay_clock_widget").value == time(0, 30)
        assert not any("se actualizan al pausar" in c.value for c in app.caption)
        app.selectbox(key="replay_run_widget").select("newer").run()
        assert app.query_params["run"] == "newer" and app.header[0].value == "newer"
        app.selectbox(key="replay_run_widget").select("older").run()
        assert position(app, catalog).time == 30


def test_patient_button_opens_exact_card_and_clears_filters(catalog):
    app = open_replay()
    app.slider(key="replay_clock_widget").set_value(time(12)).run()
    identifiers = app.dataframe[1].value["Episodio"].tolist()
    assert identifiers
    episode = identifiers[0]
    app.selectbox(key="replay_patient_widget").select(episode).run()
    app.button(key="replay_open_episode").click().run()
    assert not app.exception and app.title[0].value == "Episodios"
    assert any(s.value == f"Ficha del episodio {episode}" for s in app.subheader)
    assert app.query_params["run"] == "older" and app.query_params["episodio"] == episode
    assert any("desde Replay" in m.value for m in app.info)


def test_resource_cache_key_limit_and_no_index_on_results(catalog, tmp_path, monkeypatch):
    import shutil

    read = Mock(wraps=replay.build_replay_index)
    monkeypatch.setattr(replay, "build_replay_index", read)
    app = AppTest.from_file(MAIN, default_timeout=30)
    app.query_params["run"] = "older"
    app.run().switch_page("views/results.py").run()
    assert read.call_count == 0
    app.switch_page("views/replay.py").run()
    assert read.call_count == 1 and not app.exception
    _, fp = read_run_header(RunStore(catalog), "older")
    first = replay.cached_replay_index(str(catalog), "older", fp)
    assert replay.cached_replay_index(str(catalog), "older", fp) is first
    other = tmp_path / "other"
    shutil.copytree(catalog, other)
    assert replay.cached_replay_index(str(other), "older", fp) is not first
    replay.cached_replay_index.clear()
    for n in range(5):
        replay.cached_replay_index(str(catalog), "older", str(n))
    calls = read.call_count
    replay.cached_replay_index(str(catalog), "older", "0")
    assert read.call_count == calls + 1
