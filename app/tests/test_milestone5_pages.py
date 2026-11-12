"""Open milestone 5 runs (catalog version 4) in every page (task 5.5, H5-11, H5-12).

The two smoke tests at the top stay in the fast suite: a three-day run takes
about a second, and they catch the ``waiting_bed`` KeyError if it comes back.
Every test first checks that its situation happens in the run (an abandonment,
an admitted patient waiting for a bed, one in the hallway) and picks its
instant or episode from the data. Displayed figures are compared with what
``edsim.runs`` returns, never recomputed here.
"""

from pathlib import Path

from streamlit.testing.v1 import AppTest

import edsim_app
from edsim.runs import (
    RunStore,
    build_episode_event_index,
    episode_segments,
    read_episode_events,
    read_run_header,
    read_run_results,
)

MAIN = Path(edsim_app.__file__).with_name("main.py")
TIMEOUT = 30


def open_page(page, run_id="h5", episode=None):
    app = AppTest.from_file(MAIN, default_timeout=TIMEOUT)
    app.query_params["run"] = run_id
    if episode:
        app.query_params["episodio"] = episode
    app.run().switch_page(page).run()
    assert not app.exception and not app.error
    return app


def results(root, run_id="h5"):
    return read_run_results(RunStore(root), run_id)


def segments_of(root, episode_id, run_id="h5"):
    store = RunStore(root)
    events = read_episode_events(
        store, run_id, episode_id, build_episode_event_index(store, run_id)
    )
    return episode_segments(events, 3 * 1440).segments


def hallway_case(root):
    """An admitted patient displaced to the hallway, and its hallway segment."""
    result = results(root)
    record = next(e for e in result.analysis.table if e.hallway)
    segment = next(
        s for s in segments_of(root, record.episode_id) if s.state == "waiting_bed" and s.hallway
    )
    return record, segment


def seek(app, root, time, run_id="h5"):
    _, fingerprint = read_run_header(RunStore(root), run_id)
    app.session_state["replay_positions"][(str(root), run_id, fingerprint)].time = time
    app.run()
    assert not app.exception and not app.error


def test_replay_shows_the_wait_for_a_bed_in_the_hallway(h5_catalog):
    record, segment = hallway_case(h5_catalog)
    app = open_page("views/replay.py")
    assert app.title[0].value == "Replay"
    seek(app, h5_catalog, (segment.start + segment.end) / 2)
    patients = app.dataframe[1].value.set_index("Episodio")
    assert patients.loc[record.episode_id, "Estado"] == "Pasillo · esperando cama"


def test_episodes_opens_the_card_of_a_hallway_patient(h5_catalog):
    record, _ = hallway_case(h5_catalog)
    app = open_page("views/episodes.py", episode=record.episode_id)
    assert app.title[0].value == "Episodios"
    assert any(f"Ficha del episodio {record.episode_id}" in s.value for s in app.subheader)
    destinations = app.selectbox(key="episode_filter_destination_widget").options
    assert destinations == ["Todos", "Alta", "Ingreso", "Traslado", "Exitus"]
