"""Check catalog values and formatting without running Streamlit."""

from dataclasses import replace

from pandas.api.types import is_numeric_dtype

from edsim_app.frames import runs_frame, style_runs


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
            "Llegadas por día": 307.5,
            "Invariantes": "correctas",
            "Origen": "CLI",
        }
    ]


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
