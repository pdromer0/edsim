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
    EpisodeFilters,
    RunStore,
    build_episode_event_index,
    compare_episode_truth,
    episode_segments,
    filter_episodes,
    read_center_values,
    read_episode_events,
    read_run_episode_truth,
    read_run_header,
    read_run_results,
    true_level_abandonment,
    true_level_window_compliance,
)
from edsim_app import defaults
from edsim_app.frames import format_number, wall_times
from edsim_app.outcome_frames import format_censored

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


def wall_times_of(result, minute):
    return wall_times(result, [minute])[0]


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


# --- Resultados ----------------------------------------------------------------------------


def metric_values(app):
    return {m.label: m.value for m in app.metric}


@pytest.mark.slow
def test_results_show_the_outcome_with_its_lower_bounds(h5_catalog):
    result = results(h5_catalog)
    bed = result.outcome.bed_wait
    # The situation: admitted patients still waiting for a bed make both quantiles bounds.
    assert bed.censored > 0 and not bed.median.exact and not bed.p90.exact
    assert result.outcome.left.left > 0
    app = open_page("views/results.py")
    assert "Desenlace: abandono, destinos y espera de cama" in [s.value for s in app.subheader]
    metrics = metric_values(app)
    assert metrics["Mediana"] == f"{format_censored(bed.median)} min"
    assert metrics["Mediana"].startswith("≥ ") and "," in metrics["Mediana"]
    assert metrics["p90"] == f"{format_censored(bed.p90)} min"
    assert metrics["Siguen esperando"] == str(bed.censored)
    frames = [d.value for d in app.dataframe]
    left = next(f for f in frames if "Abandono" in f.columns).set_index("Abandono")
    assert left.loc["Se van sin ser vistos", "Pacientes"] == result.outcome.left.left
    assert left.loc["Se van sin ser vistos", "Sobre las llegadas"] == format_number(
        result.outcome.left.share, percentage=True
    )
    thresholds = next(f for f in frames if "Sin saber" in f.columns and len(f) == 3)
    assert list(thresholds["Porcentaje (por encima / conocidos)"]) == [
        format_number(t.share, percentage=True) for t in bed.over
    ]
    assert list(thresholds["Sin saber"]) == [t.unknown for t in bed.over]
    waits = next(f for f in frames if "Se van después del máximo" in f.columns)
    expected = {c.level: (c.left_late, c.censored) for c in result.compliance.by_level}
    assert sum(lt for lt, _ in expected.values()) > 0
    for _, row in waits.iterrows():
        assert (row["Se van después del máximo"], row["Censurados (se van antes)"]) == expected[
            row["Nivel"]
        ]
    curves = app.selectbox(key="results_curve_widget")
    assert "Boxes con ingresados esperando cama" in curves.options
    curves.set_value("hallway").run()
    assert not app.exception


@pytest.mark.slow
def test_results_of_milestone_4_have_no_outcome(h5_catalog):
    app = open_page("views/results.py", run_id="h4")
    assert "Desenlace: abandono, destinos y espera de cama" not in [s.value for s in app.subheader]
    options = app.selectbox(key="results_curve_widget").options
    assert "Boxes con ingresados esperando cama" not in options
    assert "Pacientes en el pasillo" not in options
    assert not any("Se van después del máximo" in d.value.columns for d in app.dataframe)


@pytest.mark.slow
def test_results_truth_only_after_the_toggle(h5_catalog):
    result = results(h5_catalog)
    truth = read_run_episode_truth(RunStore(h5_catalog), "h5")
    expected = true_level_abandonment(
        result.analysis.table, truth, result.outcome.start, result.outcome.end
    )
    assert expected.left > 0
    app = open_page("views/results.py")
    hidden = " ".join(m.value for m in app.markdown)
    assert "Abandono por nivel real" not in hidden
    assert "Cumplimiento Manchester por nivel real" not in hidden
    app.toggle(key="results_truth_widget").set_value(True).run()
    assert not app.exception and not app.error
    shown = " ".join(m.value for m in app.markdown)
    assert "Abandono por nivel real" in shown and "por nivel real (reloj C)" in shown
    frames = [d.value for d in app.dataframe]
    harm = next(f for f in frames if list(f.columns) == ["Grupo", "Pacientes"])
    assert list(harm["Pacientes"]) == [expected.left, expected.severe, expected.would_be_admitted]
    by_level = next(f for f in frames if "Llegadas" in f.columns and "Nivel real" in f.columns)
    assert list(by_level["Se van"]) == [level.left for level in expected.by_level]
    compliance = true_level_window_compliance(result.analysis.table, truth, 1, 3)
    table = next(f for f in frames if "Porcentaje que lo supera" in f.columns)
    assert list(table["Superan el máximo"]) == [c.exceeded for c in compliance.by_level]


# --- Episodios -----------------------------------------------------------------------------


def passing(app):
    caption = next(c.value for c in app.caption if "episodios pasan los filtros" in c.value)
    return int(caption.split(" de ")[0])


def filtered_count(result, filters):
    return len(
        filter_episodes(
            result.analysis.table,
            filters,
            warmup_end=result.info.warmup_days * 1440,
            horizon=result.analysis.curves.horizon,
            observed=result.observed,
        )
    )


@pytest.mark.slow
def test_episodes_filters_of_the_outcome_match_the_core(h5_catalog):
    result = results(h5_catalog)
    app = open_page("views/episodes.py")
    for field, value, filters in (
        ("left", True, EpisodeFilters(left=True)),
        ("left_from", "medico", EpisodeFilters(left=True, left_from="medico")),
        ("bed", True, EpisodeFilters(left=True, left_from="medico", bed=True)),
    ):
        app.selectbox(key=f"episode_filter_{field}_widget").set_value(value).run()
        assert not app.exception
        assert passing(app) == filtered_count(result, filters)
    # Who leaves never asks for a bed: the three filters together leave nobody.
    assert passing(app) == 0
    for field in ("left", "left_from", "bed"):
        app.selectbox(key=f"episode_filter_{field}_widget").set_value(None).run()
    app.selectbox(key="episode_filter_hallway_widget").set_value(True).run()
    expected = filtered_count(result, EpisodeFilters(hallway=True))
    assert expected > 0 and passing(app) == expected
    frame = app.dataframe[0].value
    assert set(frame["Pasillo"]) == {"Sí"}


@pytest.mark.slow
def test_episodes_outcome_filter_is_removed_for_a_milestone_4_run(h5_catalog):
    app = open_page("views/episodes.py")
    app.selectbox(key="episode_filter_left_widget").set_value(True).run()
    app.query_params["run"] = "h4"
    app.session_state["selected_run_id"] = "h4"
    app.run()
    assert not app.exception
    assert any("filtro del desenlace" in i.value for i in app.info)
    assert app.session_state["episode_filters"]["left"] is None
    assert not any(s.key == "episode_filter_left_widget" for s in app.selectbox)


@pytest.mark.slow
def test_episode_card_and_truth_of_a_patient_who_left(h5_catalog):
    result = results(h5_catalog)
    record = next(e for e in result.analysis.table if e.left_from == "medico")
    app = open_page("views/episodes.py", episode=record.episode_id)
    metrics = metric_values(app)
    assert metrics["Se va sin ser visto (UTC+1)"] == (
        wall_times_of(result, record.left).strftime("%d/%m/%Y %H:%M:%S")
    )
    assert "**Desde:** Esperando médico en el box" in [m.value for m in app.markdown]
    row = app.dataframe[0].value.set_index("Episodio").loc[record.episode_id]
    assert row["Se va sin ser visto (min)"] == record.left
    app.toggle(key="episode_truth_widget").set_value(True).run()
    assert not app.exception and not app.error
    store = RunStore(h5_catalog)
    events = read_episode_events(
        store, "h5", record.episode_id, build_episode_event_index(store, "h5")
    )
    truth = read_run_episode_truth(store, "h5")[record.episode_id]
    expected = {
        row.field: row.status
        for row in compare_episode_truth(
            events,
            episode_segments(events, result.analysis.curves.horizon),
            truth,
            profiles=result.profiles,
            start_date=result.start_date,
            center=result.center,
        )
    }
    assert expected["patience"] == "match" and expected["assessment_time"] == "unused"
    frames = [d.value for d in app.dataframe]
    shown = next(f for f in frames if "Estado" in f.columns and "Dato" in f.columns)
    shown = dict(zip(shown["Dato"], shown["Estado"], strict=True))
    assert shown["Paciencia"] == "Coincide" and shown["Valoración"] == "No usada"
    assert shown["Destino"] == "No usada" and shown["Espera de cama"] == "No usada"
    outcome = next(f for f in frames if list(f.columns) == ["Dato", "Valor"]).set_index("Dato")
    assert outcome.loc["Contrafactual", "Valor"].startswith("Sí")
    assert outcome.loc["Paciencia", "Valor"] == f"{format_number(truth.outcome.patience)} min"


@pytest.mark.slow
def test_episode_card_of_a_hallway_patient_shows_its_bed_wait(h5_catalog):
    record, _ = hallway_case(h5_catalog)
    app = open_page("views/episodes.py", episode=record.episode_id)
    metrics = metric_values(app)
    expected = (
        "Sigue esperando" if record.bed_wait is None else f"{format_number(record.bed_wait)} min"
    )
    assert metrics["Espera de cama"] == expected
    assert any(m.value.startswith("**Pasillo:** sí") for m in app.markdown)
