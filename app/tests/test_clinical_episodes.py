"""Exercise clinical observable filters, explicit truth and the results room."""

import json
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import edsim_app
from edsim.runs import (
    EpisodeFilters,
    RunStore,
    build_episode_event_index,
    episode_clinical_truth,
    episode_segments,
    filter_episodes,
    read_episode_events,
    read_run_episode_truth,
    read_run_results,
)
from edsim_app import results

pytestmark = pytest.mark.slow
MAIN = Path(edsim_app.__file__).with_name("main.py")


def open_episodes(run_id="clinical", episode=None):
    app = AppTest.from_file(MAIN)
    app.query_params["run"] = run_id
    if episode:
        app.query_params["episodio"] = episode
    app.run().switch_page("views/episodes.py").run()
    assert app.title[0].value == "Episodios" and not app.exception and not app.error
    return app


def completed_test_patient(result):
    return next(
        e
        for e in result.analysis.table
        if e.departure is not None
        and e.arrival >= 1440
        and result.observed[e.episode_id].tests
        and e.results_box_wait > 0
    )


def test_observable_profile_waits_and_combined_filters(clinical_catalog):
    result = read_run_results(RunStore(clinical_catalog), "clinical")
    record = completed_test_patient(result)
    p = result.observed[record.episode_id]
    app = open_episodes()
    row = app.dataframe[0].value.set_index("Episodio").loc[record.episode_id]
    assert row["Edad"] == p.age and row["Sexo"] == p.sex.capitalize()
    assert row["Motivo"] == result.profiles.reason(p.reason).name
    assert row["Pruebas"] == ", ".join(p.tests)
    assert row["Espera inicial de box (min)"] == record.initial_box_wait
    assert row["Espera de box al volver (min)"] == record.results_box_wait
    values = dict(
        age_band=p.age_band,
        sex=p.sex,
        arrival_mode=p.arrival_mode,
        reason=p.reason,
        test=p.tests[0],
        level=record.level,
        period="window",
    )
    for field, value in values.items():
        app.selectbox(key=f"episode_filter_{field}_widget").select(value).run()
        assert not app.exception
    filtered = filter_episodes(
        result.analysis.table,
        EpisodeFilters(**values),
        warmup_end=1440,
        horizon=4320,
        observed=result.observed,
    )
    assert filtered and len(filtered) < len(result.analysis.table)
    assert app.dataframe[0].value["Episodio"].tolist() == [e.episode_id for e in filtered]


def test_clinical_truth_is_explicit_and_matches_core(clinical_catalog, monkeypatch):
    store = RunStore(clinical_catalog)
    result = read_run_results(store, "clinical")
    record = completed_test_patient(result)
    events = read_episode_events(
        store, "clinical", record.episode_id, build_episode_event_index(store, "clinical")
    )
    expected = episode_clinical_truth(
        events,
        read_run_episode_truth(store, "clinical")[record.episode_id],
        profiles=result.profiles,
        start_date=result.start_date,
    )
    spy = Mock(wraps=results.read_run_episode_truth)
    monkeypatch.setattr(results, "read_run_episode_truth", spy)
    app = open_episodes(episode=record.episode_id)
    assert spy.call_count == 0
    assert not any("Dato clínico" in t.value for t in app.dataframe)
    app.toggle(key="episode_truth_widget").set_value(True).run()
    assert not app.exception and not app.error and spy.call_count == 1
    details = next(t.value for t in app.dataframe if "Dato clínico" in t.value).set_index(
        "Dato clínico"
    )["Verdad"]
    assert float(details["Gravedad latente G"]) == expected.severity
    assert int(details["Nivel real"]) == expected.true_level
    assert int(details["Nivel asignado"]) == expected.assigned_level
    assert int(details["Salto"]) == expected.jump
    tests = next(t.value for t in app.dataframe if "Pedida" in t.value)
    assert tests["Pedida"].tolist() == ["Sí" if t.ordered else "No" for t in expected.tests]
    assert tests["Resultado"].tolist() == [t.result or "—" for t in expected.tests]
    pd.testing.assert_series_equal(
        tests["Respuesta en la franja del pedido (min)"],
        pd.Series(
            [t.turnaround for t in expected.tests], name="Respuesta en la franja del pedido (min)"
        ),
    )
    comparison = next(t.value for t in app.dataframe if "Estado" in t.value)
    assert "Discrepancia" not in comparison["Estado"].tolist()


def test_room_timeline_and_nested_clinical_payload(clinical_catalog):
    store = RunStore(clinical_catalog)
    result = read_run_results(store, "clinical")
    record = completed_test_patient(result)
    events = read_episode_events(
        store, "clinical", record.episode_id, build_episode_event_index(store, "clinical")
    )
    segments = episode_segments(events, 4320)
    assert any(s.results_room and s.state == "waiting_tests" for s in segments.segments)
    assert any(s.results_room and s.state == "waiting_box" for s in segments.segments)
    app = open_episodes(episode=record.episode_id)
    frame = next(t.value for t in app.dataframe if "payload" in t.value)
    result_payload = frame.loc[frame["event_type"] == "test_resulted", "payload"]
    assert len(result_payload) == 1
    expected = next(e for e in events if e.event_type == "test_resulted")
    assert json.loads(result_payload.iloc[0])["resultados"] == dict(expected.payload["resultados"])
    chart = app.get("vega_lite_chart")[0]
    spec = json.loads(chart.proto.spec)
    # Altair transports the intervals as datasets in the chart or Arrow data.
    text = str(spec) + str(chart.proto)
    assert "Sala de resultados · espera de pruebas" in text
    assert "Sala de resultados · espera de box" in text


@pytest.mark.parametrize("run_id", ["provisional", "legacy"])
def test_provisional_hides_profile_filters_and_preserves_old_filters(clinical_catalog, run_id):
    app = open_episodes()
    app.selectbox(key="episode_filter_sex_widget").select("mujer").run()
    app.selectbox(key="episode_filter_level_widget").select(3).run()
    app.switch_page("views/runs.py").run()
    app.selectbox(key="run_choice").select(run_id).run()
    app.switch_page("views/episodes.py").run()
    assert not app.exception and not app.error
    assert not any(s.key == "episode_filter_sex_widget" for s in app.selectbox)
    assert app.selectbox(key="episode_filter_level_widget").value == 3
    assert "Edad" not in app.dataframe[0].value
    assert app.dataframe[0].value.shape[0] > 0
    assert any("filtro clínico" in t.value for t in app.info)


def test_absurd_center_fields_do_not_change_episode_table(clinical_catalog):
    reference = open_episodes()
    actual = open_episodes("absurd")
    pd.testing.assert_frame_equal(actual.dataframe[0].value, reference.dataframe[0].value)
