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


def test_episode_chart_has_independent_lab_lane_and_displacement_tooltip():
    import pandas as pd

    from edsim_app.charts import episode_chart

    segments = pd.DataFrame(
        {
            "Inicio": [pd.Timestamp("2026-01-05T00:30:00")],
            "Fin": [pd.Timestamp("2026-01-05T01:30:00")],
            "Estado": ["Espera de box"],
            "Box": [None],
            "Duración (min)": [60.0],
            "Carril": ["Recorrido"],
        }
    )
    tests = pd.DataFrame(
        {
            "Inicio": [pd.Timestamp("2026-01-05T00:25:00")],
            "Fin": [pd.Timestamp("2026-01-05T01:25:00")],
            "Estado": ["Pruebas en curso"],
            "Box": [None],
            "Duración (min)": [60.0],
            "Carril": ["Pruebas"],
        }
    )
    marks = pd.DataFrame(
        {
            "Fecha y hora": [pd.Timestamp("2026-01-05T00:30:00")],
            "Box": [1],
            "Desalojado por": ["EP-000001"],
            "Carril": ["Recorrido"],
        }
    )
    original = segments.copy(deep=True)
    spec = episode_chart(segments, tests, marks).to_dict()
    bars, points = spec["layer"]
    assert bars["mark"]["type"] == "bar"
    assert bars["encoding"]["x"]["title"] == "Fecha y hora (UTC+1)"
    assert bars["encoding"]["x2"]["field"] == "Fin"
    assert points["mark"]["shape"] == "diamond"
    assert {tip["field"] for tip in points["encoding"]["tooltip"]} == {
        "Fecha y hora",
        "Box",
        "Desalojado por",
    }
    rows = spec["datasets"][bars["data"]["name"]]
    assert rows[0]["Inicio"] == "2026-01-05T00:30:00"
    assert rows[0]["Fin"] == "2026-01-05T01:30:00"
    assert rows[1]["Carril"] == "Pruebas" and rows[1]["Fin"] == "2026-01-05T01:25:00"
    pd.testing.assert_frame_equal(segments, original)


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
        level.p90["classified_to_doctor"] for level in result.analysis.metrics.by_level
    ]


def test_weekly_charts_serialize_wall_time_capacity_and_warmup(catalog):
    from edsim.runs import RunStore, read_run_results
    from edsim_app.charts import curve_chart
    from edsim_app.frames import CURVE_LABELS, curve_frame, wall_times

    result = read_run_results(RunStore(catalog), "older")
    warmup = wall_times(result, [1440])[0]
    for name in CURVE_LABELS:
        frame = curve_frame(result, name, 0)
        assert frame["Fecha y hora"].dt.tz is None
        spec = curve_chart(frame, warmup).to_dict()
        lines = spec["layer"][-1]
        rows = spec["datasets"][lines["data"]["name"]]
        assert rows[0]["Fecha y hora"] == "2026-01-05T00:00:00"
        assert rows[1]["Fecha y hora"] == "2026-01-05T00:15:00"
        assert rows[-1]["Fecha y hora"] == "2026-01-08T00:00:00"
        assert lines["mark"]["interpolate"] == "step-after"
        names = {row["Serie"] for row in rows}
        expected = {"Media", "Máximo"}
        if name in ("nurses_busy", "doctors_busy"):
            expected.add("Plantilla vigente")
        elif name == "boxes_busy":
            expected.add("Boxes")
        assert names == expected
        assert set(lines["encoding"]["color"]["scale"]["domain"]) == expected
        shade = spec["datasets"][spec["layer"][0]["data"]["name"]]
        assert shade == [{"Inicio": "2026-01-05T00:00:00", "Fin": "2026-01-06T00:00:00"}]


def test_weekly_frame_short_last_week_and_no_warmup_shading(weekly_catalog):
    from edsim.runs import RunStore, read_run_results
    from edsim_app.charts import curve_chart
    from edsim_app.frames import curve_frame, wall_times

    result = read_run_results(RunStore(weekly_catalog), "weekly")
    frame = curve_frame(result, "doctors_busy", 1)
    means = frame.loc[frame["Serie"] == "Media"]
    assert len(means) == 97  # 96 blocks and the final drawing endpoint
    assert means.iloc[0]["Fecha y hora"].isoformat() == "2026-01-12T00:00:00"
    assert means.iloc[-1]["Fecha y hora"].isoformat() == "2026-01-13T00:00:00"
    spec = curve_chart(frame, wall_times(result, [1440])[0]).to_dict()
    assert len(spec["layer"]) == 1


def test_occupancy_and_hourly_charts_preserve_core_values(catalog):
    from edsim.runs import RunStore, read_run_results
    from edsim_app.charts import hourly_census_chart, occupancy_chart
    from edsim_app.frames import hourly_census_frame, occupancy_frame

    result = read_run_results(RunStore(catalog), "older")
    frame = occupancy_frame(result)
    frame.loc[0, "Ocupación"] = 1.2
    spec = occupancy_chart(frame).to_dict()
    rows = spec["datasets"][spec["data"]["name"]]
    assert len(rows) == 9 and rows[0]["Ocupación"] == 1.2
    assert "domainMax" not in spec["layer"][0]["encoding"]["color"]["scale"]
    spec = hourly_census_chart(hourly_census_frame(result)).to_dict()
    rows = spec["datasets"][spec["data"]["name"]]
    assert [row["Censo medio"] for row in rows] == result.hourly_census.tolist()


def test_occupancy_labels_contrast_with_the_shared_color_domain():
    import pandas as pd

    from edsim_app.charts import occupancy_chart

    for ratios, upper in (([0.1, 0.8], 1.0), ([0.2, 1.2], 1.2)):
        frame = pd.DataFrame(
            {
                "Recurso": ["Médicos", "Boxes"],
                "Turno": ["Mañana", "Noche"],
                "Ocupación": ratios,
                "Etiqueta": ["baja", "alta"],
            }
        )
        spec = occupancy_chart(frame).to_dict()
        cells, labels = spec["layer"]
        assert cells["encoding"]["color"]["scale"] == {"domain": [0, upper], "scheme": "blues"}
        color = labels["encoding"]["color"]
        assert color["condition"]["test"] == f"(datum['Ocupación'] > {0.6 * upper})"
        assert color["condition"]["value"] == "white"
        assert color["value"] == "black"
        assert ratios[0] <= 0.6 * upper < ratios[1]


def test_difference_histogram_preserves_precomputed_intervals_and_colors_each_sign():
    import pandas as pd

    from edsim.runs import DifferenceSummary, HistogramBin
    from edsim_app.charts import difference_histogram_chart
    from edsim_app.comparison_frames import difference_histogram_frame

    summary = DifferenceSummary(
        "stay",
        12,
        3,
        7,
        2,
        3 / 12,
        7 / 12,
        2 / 12,
        (HistogramBin(-10.0, 0.0, 3), HistogramBin(0.0, 20.0, 7)),
    )
    frame = difference_histogram_frame(summary)
    original = frame.copy(deep=True)
    spec = difference_histogram_chart(frame).to_dict()
    assert spec["mark"]["type"] == "bar"
    assert spec["encoding"]["x"]["bin"] == "binned"
    assert spec["encoding"]["x2"]["field"] == "Hasta (min)"
    color = spec["encoding"]["color"]
    assert color["field"] == "Efecto"
    assert color["scale"] == {
        "domain": ["Mejoran", "Empeoran"],
        "range": ["#1baf7a", "#b00020"],
    }
    rows = spec["datasets"][spec["data"]["name"]]
    assert rows == [
        {"Desde (min)": -10.0, "Hasta (min)": 0.0, "Pacientes": 3, "Efecto": "Mejoran"},
        {"Desde (min)": 0.0, "Hasta (min)": 20.0, "Pacientes": 7, "Efecto": "Empeoran"},
    ]
    assert "transform" not in spec
    assert sum(row["Pacientes"] for row in rows) == summary.improved + summary.worsened
    pd.testing.assert_frame_equal(frame, original)
