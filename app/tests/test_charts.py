"""Inspect declarative chart specifications without starting Streamlit."""

from edsim.runs import read_center_values, summarize_center
from edsim_app.charts import duration_chart


def test_duration_chart_keeps_supplied_points_and_numeric_axes():
    duration = summarize_center(read_center_values("tests/data/centro_ejemplo.toml")).durations[0]
    spec = duration_chart(duration).to_dict()
    assert spec["mark"]["type"] == "line"
    assert spec["encoding"]["x"]["field"] == "Minutos"
    assert spec["encoding"]["y"]["field"] == "Densidad"
    rows = spec["datasets"][spec["data"]["name"]]
    assert len(rows) == 122
    assert rows[0] == {"Minutos": 0, "Densidad": 0}
    assert rows[61] == {
        "Minutos": duration.curve_minutes[61],
        "Densidad": duration.curve_density[61],
    }


def test_offered_chart_has_both_series_shared_scale_and_step_means():
    import pandas as pd

    from edsim_app.charts import offered_chart

    frame = pd.DataFrame(
        {
            "Fecha y hora": pd.date_range("2026-01-05", periods=2, freq="15min"),
            "Carga ofrecida": [2.0, 3.0],
            "Capacidad": [4.0, 4.0],
        }
    )
    spec = offered_chart(frame).to_dict()
    assert spec["mark"] == {"type": "line", "interpolate": "step-after"}
    assert spec["encoding"]["x"]["type"] == "temporal"
    assert spec["encoding"]["y"]["field"] == "Recursos"
    assert spec["encoding"]["color"]["scale"]["domain"] == ["Carga ofrecida", "Capacidad"]
    rows = spec["datasets"][spec["data"]["name"]]
    assert [r["Recursos"] for r in rows] == [2, 3, 4, 4]
    assert [r["Serie"] for r in rows] == ["Carga ofrecida"] * 2 + ["Capacidad"] * 2


def test_offered_chart_serializes_utc_plus_one_wall_time_without_offset():
    from edsim.runs import load_center, load_profile, offered_work
    from edsim_app.charts import offered_chart
    from edsim_app.frames import offered_frame

    work = offered_work(
        load_center("tests/data/centro_ejemplo.toml"),
        load_profile("tests/data/llegadas_ejemplo.toml"),
        days=1,
        sample_size=2,
    )
    frame = offered_frame(work, "medicos")
    assert frame["Fecha y hora"].dt.tz is None
    spec = offered_chart(frame).to_dict()
    rows = spec["datasets"][spec["data"]["name"]]
    assert rows[0]["Fecha y hora"] == "2026-01-05T00:00:00"
    assert rows[1]["Fecha y hora"] == "2026-01-05T00:15:00"
    assert spec["encoding"]["x"]["title"] == "Fecha y hora (UTC+1)"


def test_waits_chart_keeps_supplied_door_waits_and_manchester(catalog):
    from edsim.runs import RunStore, read_run_results
    from edsim_app.charts import waits_chart
    from edsim_app.frames import waits_frame

    result = read_run_results(RunStore(catalog), "older")
    spec = waits_chart(waits_frame(result)).to_dict()
    rows = spec["datasets"][spec["data"]["name"]]
    assert len(rows) == 15
    assert {row["Serie"] for row in rows} == {"Media", "p90", "Máximo Manchester"}
    assert [row["Minutos"] for row in rows if row["Serie"] == "Máximo Manchester"] == [
        0,
        10,
        60,
        120,
        240,
    ]
    assert [row["Minutos"] for row in rows if row["Serie"] == "p90"] == [
        level.p90["door_to_doctor"] for level in result.analysis.metrics.by_level
    ]
