"""Check catalog values and formatting without running Streamlit."""

from dataclasses import replace
from types import SimpleNamespace

from pandas.api.types import is_numeric_dtype

from edsim_app.frames import model_label, runs_frame, style_runs


def test_run_table_columns_values_and_fixed_timezone(run_info):
    frame = runs_frame([run_info])
    assert frame.to_dict("records") == [
        {
            "Ejecución": "example",
            "Variante del centro": "base",
            "Fecha de creación (UTC+1)": "04/07/2026 00:30:00",
            "Días": 4,
            "Calentamiento (días)": 2,
            "Semilla": 2026,
            "Huella del centro": "12345678",
            "Modelo": "Provisional",
            "Huella de perfiles clínicos": "—",
            "Llegadas por día": 307.5,
            "Invariantes": "correctas",
            "Origen": "CLI",
        }
    ]


def test_model_column_tells_milestone_4_from_milestone_5_by_the_catalog(run_info):
    clinical = {
        "model": "clinico",
        "clinical_profiles_path": "config/perfiles.toml",
        "clinical_profiles_fingerprint": "fedcba9876543210",
    }
    milestone_4 = replace(run_info, run_id="h4", format_version=2, **clinical)
    milestone_5 = replace(run_info, run_id="h5", format_version=3, schema_version=4, **clinical)
    assert [info.catalog_version for info in (run_info, milestone_4, milestone_5)] == [1, 3, 4]
    frame = runs_frame([run_info, milestone_4, milestone_5])
    assert frame["Modelo"].tolist() == [
        "Provisional",
        "Clínico · hito 4 (v3)",
        "Clínico · hito 5 (v4)",
    ]


def test_model_label_of_an_unknown_catalog_names_its_version():
    future = SimpleNamespace(is_clinical=True, catalog_version=5)
    assert model_label(future) == "Clínico (v5)"


def test_table_preserves_input_order_and_describes_violations(run_info):
    second = replace(run_info, run_id="second", invariant_violations=3, origin="app")
    frame = runs_frame([second, run_info])
    assert frame["Ejecución"].tolist() == ["second", "example"]
    assert frame["Invariantes"].tolist() == ["3 violaciones", "correctas"]
    assert frame["Origen"].tolist() == ["app", "CLI"]


def test_empty_table_keeps_all_headers():
    frame = runs_frame([])
    assert frame.empty
    assert list(frame.columns) == [
        "Ejecución",
        "Variante del centro",
        "Fecha de creación (UTC+1)",
        "Días",
        "Calentamiento (días)",
        "Semilla",
        "Huella del centro",
        "Modelo",
        "Huella de perfiles clínicos",
        "Llegadas por día",
        "Invariantes",
        "Origen",
    ]


def test_decimal_comma_does_not_turn_numbers_into_strings(run_info):
    frame = runs_frame([run_info])
    styled = style_runs(frame)
    assert "307,5" in styled.to_html()
    assert is_numeric_dtype(styled.data["Llegadas por día"])
    assert styled.data.loc[0, "Llegadas por día"] == 307.5


def test_episode_frame_preserves_missing_final_times_and_observed_bound(catalog):
    import pandas as pd

    from edsim.runs import RunStore, episode_observed_time, read_run_results
    from edsim_app.frames import EPISODE_COLUMNS, episodes_frame, style_episodes

    result = read_run_results(RunStore(catalog), "older")
    frame = episodes_frame(result.analysis.table, result)
    assert list(frame) == [*EPISODE_COLUMNS.values(), "Tiempo observado (min)"]
    assert frame["Llegada (UTC+1)"].dt.tz is None
    unfinished = next(record for record in result.analysis.table if record.departure is None)
    row = frame.set_index("Episodio").loc[unfinished.episode_id]
    assert pd.isna(row["Estancia (min)"])
    assert row["Tiempo observado (min)"] == episode_observed_time(unfinished, 4320)
    assert "—" in style_episodes(frame.tail(3)).to_html()
    assert is_numeric_dtype(frame["Estancia (min)"])
    assert episodes_frame((), result).empty
    frame.loc[0, "Tiempo observado (min)"] = -1
    assert result.analysis.table[0].arrival >= 0


def test_episode_timeline_frames_separate_lab_and_preserve_wall_time(catalog):
    from edsim.runs import (
        Displacement,
        EpisodeSegment,
        EpisodeSegments,
        RunStore,
        TestBand,
        read_run_results,
    )
    from edsim_app.frames import episode_timeline_frames

    result = read_run_results(RunStore(catalog), "older")
    timeline = EpisodeSegments(
        "EP-000000",
        (
            EpisodeSegment("waiting_tests", 25, 30, 1),
            EpisodeSegment("waiting_box", 30, 90, None),
        ),
        TestBand(25, 85, True),
        (Displacement(30, 1, "EP-000001"),),
    )
    segments, tests, marks = episode_timeline_frames(timeline, result)
    assert segments["Estado"].tolist() == ["En box esperando pruebas", "Espera de box"]
    assert segments["Duración (min)"].tolist() == [5, 60]
    assert tests["Duración (min)"].tolist() == [60]
    assert tests["Carril"].tolist() == ["Pruebas"]
    assert marks["Desalojado por"].tolist() == ["EP-000001"]
    assert marks["Box"].tolist() == [1]
    for frame in (segments, tests):
        assert frame["Inicio"].dt.tz is None and frame["Fin"].dt.tz is None
    assert segments["Inicio"].iloc[0].isoformat() == "2026-01-05T00:25:00"
    assert marks["Fecha y hora"].dt.tz is None
    empty = EpisodeSegments("EP-000000", (), None, ())
    assert all(frame.empty for frame in episode_timeline_frames(empty, result))


def test_episode_event_frame_keeps_log_values_and_payload(catalog):
    import json

    from edsim.runs import RunStore, build_episode_event_index, read_episode_events
    from edsim_app.frames import episode_events_frame

    store = RunStore(catalog)
    index = build_episode_event_index(store, "older")
    events = read_episode_events(store, "older", "EP-000000", index)
    frame = episode_events_frame(events)
    assert frame["event_id"].tolist() == [event.event_id for event in events]
    assert frame["sim_time"].tolist() == [event.sim_time for event in events]
    assert frame["event_time"].tolist() == [event.event_time for event in events]
    assert [json.loads(value) for value in frame["payload"]] == [
        dict(event.payload) for event in events
    ]


def test_truth_frame_shows_partial_pending_and_unused_without_changing_values():
    from edsim.runs import TruthComparison
    from edsim_app.frames import episode_truth_frame

    comparisons = (
        TruthComparison("level", 3, 3, "match"),
        TruthComparison("assessment_time", 20.0, 3.2, "partial"),
        TruthComparison("reassessment_time", 10.0, None, "unused"),
        TruthComparison("destination", "alta", None, "pending"),
    )
    frame = episode_truth_frame(comparisons)
    assert frame["Estado"].tolist() == ["Coincide", "Parcial", "No usada", "Pendiente"]
    assert frame["Observado"].tolist() == ["3", "3,2 de 20,0 min", "—", "—"]
    assert frame["Sorteado"].tolist() == ["3", "20,0 min", "10,0 min", "Alta"]
    assert comparisons[1].observed == 3.2


def test_offered_blocks_integrate_linear_load_and_exclude_final_endpoint():
    from datetime import date

    import numpy as np

    from edsim.runs import OfferedWork
    from edsim_app.frames import offered_frame

    minutes = np.arange(1441)
    load = minutes.astype(float)
    capacity = np.where(minutes < 8 * 60, 2, 4)
    work = OfferedWork(
        date(2026, 1, 5),
        1,
        1,
        minutes,
        {"medicos": load},
        {"medicos": capacity},
        {"medicos": (0, 0, 0)},
    )
    frame = offered_frame(work, "medicos")
    assert frame.shape == (96, 3)
    assert frame["Carga ofrecida"].iloc[0] == 7.5
    assert frame["Carga ofrecida"].iloc[-1] == 1432.5
    assert frame["Capacidad"].iloc[31:33].tolist() == [2, 4]
    assert frame["Fecha y hora"].iloc[0].isoformat() == "2026-01-05T00:00:00"
    assert frame["Fecha y hora"].iloc[-1].isoformat() == "2026-01-05T23:45:00"
    work.load["medicos"][:] = 3.25
    assert (offered_frame(work, "medicos")["Carga ofrecida"] == 3.25).all()


def test_offered_blocks_cross_check_shift_utilization():
    import pytest

    from edsim.runs import load_center, load_profile, offered_work
    from edsim_app.frames import POOL_LABELS, offered_frame

    center = load_center("tests/data/centro_ejemplo.toml")
    profile = load_profile("tests/data/llegadas_ejemplo.toml")
    work = offered_work(center, profile, days=2, sample_size=32)
    for pool in POOL_LABELS:
        frame = offered_frame(work, pool)
        hours = frame["Fecha y hora"].dt.hour
        morning, afternoon, night = center.shift_starts
        masks = (
            (hours >= morning) & (hours < afternoon),
            (hours >= afternoon) & (hours < night),
            (hours < morning) | (hours >= night),
        )
        for index, mask in enumerate(masks):
            assert mask.any()
            selected = frame.loc[mask]
            assert selected["Capacidad"].nunique() == 1
            actual = selected["Carga ofrecida"].mean() / selected["Capacidad"].iloc[0]
            assert actual == pytest.approx(work.utilization[pool][index], rel=1e-12)


def test_utilization_table_preserves_core_values_and_strict_thresholds():
    from datetime import date

    import numpy as np

    from edsim.runs import OfferedWork
    from edsim_app.frames import POOL_LABELS, style_utilization, utilization_frame

    work = OfferedWork(
        date(2026, 1, 5),
        1,
        1,
        np.arange(1441),
        {},
        {},
        {pool: (0.85, 1, 1.01) for pool in POOL_LABELS},
    )
    frame = utilization_frame(work)
    assert frame["Utilización"].tolist() == [0.85, 1, 1.01] * 3
    assert frame["Estado"].tolist() == ["Hasta 0,85", "Por encima de 0,85", "Por encima de 1"] * 3
    assert frame["Turno"].tolist() == ["Mañana", "Tarde", "Noche"] * 3
    html = style_utilization(frame).to_html()
    assert "85,0%" in html
    assert "#ffdddd" in html and "#fff0cc" in html


def test_results_kpis_keep_counts_and_missing_statistics_numeric():
    import pandas as pd

    from edsim.runs import WindowKPIs
    from edsim_app.frames import format_number, kpis_frame

    frame = kpis_frame(WindowKPIs(0, 3.5, 2.25, None, None, None, None, 0, 0, None))
    assert is_numeric_dtype(frame["Valor"])
    values = frame.set_index("Indicador")["Valor"]
    assert values["Llegadas por día"] == 3.5
    assert values["Episodios desalojados"] == values["Desalojos totales"] == 0
    assert pd.isna(values["Estancia media"])
    assert format_number(None) == format_number(float("nan")) == "—"
    assert format_number(0.125, percentage=True) == "12,5 %"


def test_results_empty_level_preserves_none_and_formats_dash(catalog):
    import pandas as pd

    from edsim.runs import RunStore, read_run_results
    from edsim_app.frames import style_waits, waits_frame

    result = read_run_results(RunStore(catalog), "older")
    first = result.analysis.metrics.by_level[0]
    empty = replace(first, n=0, mean=dict.fromkeys(first.mean), p90=dict.fromkeys(first.p90))
    metrics = replace(
        result.analysis.metrics, by_level=(empty, *result.analysis.metrics.by_level[1:])
    )
    compliance = replace(
        result.compliance.by_level[0], n=0, exceeded=0, exceeded_share=None, share_out=None
    )
    result = replace(
        result,
        analysis=replace(result.analysis, metrics=metrics),
        compliance=replace(
            result.compliance, by_level=(compliance, *result.compliance.by_level[1:])
        ),
    )
    frame = waits_frame(result)
    assert frame.loc[0, "n"] == 0
    assert pd.isna(frame.loc[0, "Estancia media (min)"])
    assert frame.loc[0, "Pacientes que superan el máximo"] == 0
    assert pd.isna(frame.loc[0, "Superan el máximo"])
    assert "—" in style_waits(frame).to_html()


def test_results_occupancy_keeps_ratios_above_one_and_little_product(catalog):
    from edsim.runs import RunStore, read_run_results
    from edsim_app.frames import hourly_census_frame, little_frame, occupancy_frame, style_little

    result = read_run_results(RunStore(catalog), "older")
    original = result.analysis.metrics.occupancy[0]
    occupancy = replace(original, busy_area=original.staff_area * 1.2)
    metrics = replace(
        result.analysis.metrics, occupancy=(occupancy, *result.analysis.metrics.occupancy[1:])
    )
    changed = replace(result, analysis=replace(result.analysis, metrics=metrics))
    frame = occupancy_frame(changed)
    assert len(frame) == 9 and frame.iloc[0]["Ocupación"] == 1.2
    assert frame.iloc[0]["Etiqueta"] == "120,0 %"
    little = little_frame(result)
    assert little["λ·W"].tolist() == [law.lam * law.w for law in result.analysis.little]
    assert little["Error relativo"].tolist() == [
        law.relative_error for law in result.analysis.little
    ]
    assert "λ·W" in style_little(little).to_html()
    hourly = hourly_census_frame(result)
    assert hourly["Hora del día"].tolist() == list(range(24))
    assert hourly["Censo medio"].tolist() == result.hourly_census.tolist()
    hourly.loc[0, "Censo medio"] = -1
    assert result.hourly_census[0] >= 0


def test_payload_serializes_nested_immutable_results_without_changing_them():
    import json
    from types import MappingProxyType

    from edsim_app.frames import plain_payload

    payload = MappingProxyType(
        {
            "resultados": MappingProxyType({"analitica": "alterado"}),
            "pruebas": ("analitica", "ecg"),
        }
    )
    assert json.loads(json.dumps(plain_payload(payload))) == {
        "resultados": {"analitica": "alterado"},
        "pruebas": ["analitica", "ecg"],
    }
    assert isinstance(payload["resultados"], MappingProxyType)


def test_results_room_labels_preserve_both_physical_states():
    from edsim_app.frames import episode_state_label

    assert episode_state_label("waiting_tests", results_room=True) == (
        "Sala de resultados · espera de pruebas"
    )
    assert episode_state_label("waiting_box", results_room=True) == (
        "Sala de resultados · espera de box"
    )
    assert episode_state_label("waiting_tests") == "En box esperando pruebas"
    assert episode_state_label("waiting_box") == "Espera de box"


def test_waiting_bed_label_and_hallway_mark():
    """The state says what the patient does; the hallway mark, where it is (H5-11)."""
    from edsim_app.frames import episode_state_label

    assert episode_state_label("waiting_bed") == "Esperando cama"
    assert episode_state_label("waiting_bed", hallway=True) == "Pasillo · esperando cama"
