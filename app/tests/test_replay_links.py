"""Open exact arrivals, including an episode entirely contained in one minute."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import edsim_app
from edsim.runs import (
    RunStore,
    read_center_values,
    read_run_header,
    read_run_results,
    simulate_run,
    write_variant,
)

pytestmark = pytest.mark.slow
MAIN = Path(edsim_app.__file__).with_name("main.py")


def test_fractional_arrival_short_episode_and_round_trip(catalog):
    values = read_center_values("tests/data/centro_ejemplo.toml")
    values["duraciones.triaje"] = [0.01, 0.02]
    values["duraciones.valoracion"] = [0.01, 0.02]
    values["pruebas.probabilidad"] = [0.0] * 5
    center = catalog.parent / "quick.toml"
    write_variant("tests/data/centro_ejemplo.toml", values, center)
    simulate_run(
        center,
        "tests/data/llegadas_ejemplo.toml",
        1,
        7,
        output_dir=catalog / "quick",
        run_id="quick",
        warmup_days=0,
        origin="app",
    )
    result = read_run_results(RunStore(catalog), "quick")
    candidates = [
        p
        for p in result.analysis.table
        if p.departure is not None and int(p.arrival) == int(p.departure) and p.arrival % 1
    ]
    assert candidates
    record = candidates[0]
    app = AppTest.from_file(MAIN, default_timeout=30)
    app.query_params.update(run="quick", episodio=record.episode_id)
    app.run().switch_page("views/episodes.py").run()
    app.button(key="episode_open_replay").click().run()
    assert not app.exception and not app.error and app.title[0].value == "Replay"
    # AppTest does not adopt the browser route emitted by st.switch_page.
    # Assert the navigation first, then synchronize its client before more input.
    app.switch_page("views/replay.py").run()
    _, fp = read_run_header(RunStore(catalog), "quick")
    p = app.session_state["replay_positions"][(str(catalog), "quick", fp)]
    assert p.time == record.arrival and not p.playing
    assert p.highlighted_episode == record.episode_id
    assert record.episode_id in " ".join(e.proto.body for e in app.get("html"))
    assert any('data-mark="highlight"' in e.proto.body for e in app.get("html"))
    assert record.episode_id in app.dataframe[1].value["Episodio"].tolist()
    from datetime import datetime

    expected_clock = datetime.fromisoformat(app.dataframe[0].value["event_time"].iloc[-1]).strftime(
        "%H:%M:%S"
    )
    assert any(expected_clock in m.value for m in app.markdown)
    app.button(key="replay_step_1").click().run()
    assert p.time == int(record.arrival) + 1
    assert record.episode_id not in app.dataframe[1].value["Episodio"].tolist()
    app.switch_page("views/episodes.py").run()
    assert app.selectbox(key="episode_choice_widget").value == record.episode_id
    app.button(key="episode_open_replay").click().run()
    assert app.title[0].value == "Replay"
    app.switch_page("views/replay.py").run()
    app.button(key="replay_step_-1").click().run()
    assert p.time == int(record.arrival)


def test_card_fragment_opens_replay_paused_at_exact_arrival(catalog):
    from fragment_runner import FragmentRunner

    result = read_run_results(RunStore(catalog), "older")
    record = result.analysis.table[0]
    with FragmentRunner() as runner:
        app = AppTest.from_file(MAIN, default_timeout=30)
        app.query_params.update(run="older", episodio=record.episode_id)
        app.run().switch_page("views/episodes.py").run()
        app.button(key="episode_open_replay").click()
        runner.run_fragment(app, key="episode_card")
        assert not app.exception and app.title[0].value == "Replay"
        _, fp = read_run_header(RunStore(catalog), "older")
        position = app.session_state["replay_positions"][(str(catalog), "older", fp)]
        assert position.time == record.arrival and not position.playing
        assert position.highlighted_episode == record.episode_id
        assert runner.partial_runs == 1
