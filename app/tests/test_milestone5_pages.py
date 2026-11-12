"""Open milestone 5 runs (catalog version 4) in every page (task 5.5, H5-11, H5-12).

The two smoke tests at the top stay in the fast suite: a three-day run takes
about a second, and they catch the ``waiting_bed`` KeyError if it comes back.
Every test first checks that its situation happens in the run (an abandonment,
an admitted patient waiting for a bed, one in the hallway) and picks its
instant or episode from the data. Displayed figures are compared with what
``edsim.runs`` returns, never recomputed here.
"""

import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import edsim_app
from edsim.runs import (
    RunStore,
    build_episode_event_index,
    episode_segments,
    read_center_values,
    read_episode_events,
    read_run_header,
    read_run_results,
)
from edsim_app import defaults

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


# --- Simular with a center with [camas] (task 5.5) -----------------------------------------


def open_simulation(profiles):
    """Simular with a milestone 5 variant copied into the temporary variants folder."""
    variants = Path(defaults.VARIANTS_DIR)
    variants.mkdir(parents=True, exist_ok=True)
    variant = variants / "h5.toml"
    shutil.copyfile("tests/data/centro_h5_ejemplo.toml", variant)
    app = AppTest.from_file(MAIN, default_timeout=TIMEOUT)
    app.session_state["simulation_settings"] = {
        "clinical_path": profiles,
        "days": defaults.SIMULATION_DAYS,
        "warmup_days": defaults.SIMULATION_WARMUP_DAYS,
        "seed": "2026",
        "run_id": "",
        "run_id_mode": "automatic",
    }
    app.run().switch_page("views/simulate.py").run()
    app.selectbox(key="source_widget").set_value(str(variant)).run()
    assert not app.exception
    return app, variant


@pytest.mark.slow
def test_simulate_edits_the_wait_for_a_bed_and_explains_the_missing_load():
    app, variant = open_simulation("tests/data/perfiles_h5_ejemplo.toml")
    assert not app.error
    values = read_center_values(variant)
    shown = {
        key: [app.number_input(key=f"edit_{key}_{i}").value for i in range(n)]
        for key, n in (("camas.espera", 2), ("camas.factor_turno", 3))
    }
    assert shown == {key: values[key] for key in shown}
    keys = {widget.key for widget in app.number_input}
    # The file has no seasonal factor, and a center with [camas] has no admission probability.
    assert not any(k.startswith(("edit_camas.factor_estacion", "edit_destino.")) for k in keys)
    assert "La carga prevista del modelo del hito 5 llega con el issue #103." in [
        i.value for i in app.info
    ]
    app.number_input(key="edit_camas.espera_0").set_value(300.0).run()
    assert not app.exception
    changes = " ".join(m.value for m in app.markdown)
    assert "Espera de cama (min)" in changes and "camas.espera" in changes


@pytest.mark.slow
def test_simulate_shows_the_core_error_when_the_files_do_not_agree():
    app, _ = open_simulation(str(defaults.CLINICAL_PROFILES_PATH))
    assert not app.exception
    assert any("camas" in e.value or "milestone 5" in e.value for e in app.error)
    assert "Corrige la configuración para calcular la carga prevista." in [
        i.value for i in app.info
    ]
