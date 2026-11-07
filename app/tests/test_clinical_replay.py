"""Keep replay clinical details observable at the selected instant."""

import json
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import edsim_app
from edsim.runs import (
    RunStore,
    build_episode_event_index,
    episode_segments,
    observed_profiles,
    read_episode_events,
    read_run_header,
    read_run_results,
)

pytestmark = pytest.mark.slow
MAIN = Path(edsim_app.__file__).with_name("main.py")


def open_replay(run_id="clinical"):
    app = AppTest.from_file(MAIN)
    app.query_params["run"] = run_id
    app.run().switch_page("views/replay.py").run()
    assert app.title[0].value == "Replay" and not app.exception and not app.error
    return app


def seek(app, root, run_id, time):
    _, fp = read_run_header(RunStore(root), run_id)
    app.session_state["replay_positions"][(str(root), run_id, fp)].time = time
    app.run()
    assert not app.exception and not app.error


def clinical_case(root):
    store = RunStore(root)
    result = read_run_results(store, "clinical")
    record = next(
        e for e in result.analysis.table if e.departure is not None and e.results_box_wait > 0
    )
    events = read_episode_events(
        store, "clinical", record.episode_id, build_episode_event_index(store, "clinical")
    )
    return result, record, events


def test_results_room_both_states_use_their_own_label(clinical_catalog):
    result, record, events = clinical_case(clinical_catalog)
    room = [s for s in episode_segments(events, 4320).segments if s.results_room]
    assert {s.state for s in room} == {"waiting_tests", "waiting_box"}
    app = open_replay()
    for state, label in (("waiting_tests", "espera de pruebas"), ("waiting_box", "espera de box")):
        segment = next(s for s in room if s.state == state)
        seek(app, clinical_catalog, "clinical", (segment.start + segment.end) / 2)
        patients = app.dataframe[1].value.set_index("Episodio")
        assert patients.loc[record.episode_id, "Estado"] == f"Sala de resultados · {label}"
        svg = " ".join(item.proto.body for item in app.get("html"))
        assert f"Sala de resultados · {label}" in svg
        assert record.episode_id in svg


def test_nested_test_result_payload_is_serialized(clinical_catalog):
    _, _, events = clinical_case(clinical_catalog)
    event = next(e for e in events if e.event_type == "test_resulted")
    app = open_replay()
    seek(app, clinical_catalog, "clinical", event.sim_time)
    frame = app.dataframe[0].value
    payload = frame.set_index("event_id").loc[event.event_id, "payload"]
    assert json.loads(payload)["resultados"] == dict(event.payload["resultados"])


def test_patient_card_does_not_reveal_future_reason(clinical_catalog):
    store = RunStore(clinical_catalog)
    result = read_run_results(store, "clinical")
    record = next(
        e
        for e in result.analysis.table
        if e.triage_end is not None and e.triage_end > e.arrival and e.departure is not None
    )
    events = read_episode_events(
        store, "clinical", record.episode_id, build_episode_event_index(store, "clinical")
    )
    app = open_replay()
    seek(app, clinical_catalog, "clinical", record.arrival)
    app.selectbox(key="replay_patient_widget").select(record.episode_id).run()
    expected = observed_profiles(
        (e for e in events if e.sim_time <= record.arrival), result.profiles.population
    )[record.episode_id]
    assert expected.reason is None and result.observed[record.episode_id].reason is not None
    card = next(t.value for t in app.dataframe if "Edad" in t.value)
    assert card.loc[0, "Motivo"] == "Sin observar"
    assert card.loc[0, "Edad"] == expected.age
    seek(app, clinical_catalog, "clinical", record.triage_end)
    card = next(t.value for t in app.dataframe if "Edad" in t.value)
    assert (
        card.loc[0, "Motivo"]
        == result.profiles.reason(result.observed[record.episode_id].reason).name
    )


@pytest.mark.parametrize("run_id", ["provisional", "legacy"])
def test_old_replays_keep_states_and_event_tables(clinical_catalog, run_id):
    app = open_replay(run_id)
    seek(app, clinical_catalog, run_id, 720)
    assert len(app.dataframe[0].value) == 15
    assert len(app.dataframe[1].value) > 0
    assert not any("Edad" in t.value for t in app.dataframe)


def test_absurd_clinical_center_does_not_change_replay_patients(clinical_catalog):
    reference = open_replay()
    seek(reference, clinical_catalog, "clinical", 720)
    actual = open_replay("absurd")
    seek(actual, clinical_catalog, "absurd", 720)
    pd.testing.assert_frame_equal(actual.dataframe[1].value, reference.dataframe[1].value)
