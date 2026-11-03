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
