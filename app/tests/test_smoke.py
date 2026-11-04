"""Keep one real-catalog smoke check per page in the fast suite."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import edsim_app

MAIN = Path(edsim_app.__file__).with_name("main.py")


@pytest.mark.parametrize(
    "page,title",
    [
        ("runs", "Ejecuciones"),
        ("simulate", "Simular"),
        ("results", "Resultados"),
        ("episodes", "Episodios"),
        ("compare", "Comparar"),
        ("replay", "Replay"),
    ],
)
def test_page_with_short_run(catalog, page, title):
    app = AppTest.from_file(MAIN, default_timeout=30)
    app.query_params["run"] = "older"
    app.session_state["compare_a"] = "older"
    app.session_state["compare_b"] = "newer"
    app.run()
    app.switch_page(f"views/{page}.py").run()
    assert not app.exception and not app.error
    assert app.title[0].value == title
    assert app.query_params["run"] == "older"
    assert "older" in [item.value for item in app.sidebar.markdown]
    if page in ("runs", "episodes", "compare"):
        assert len(app.dataframe[0].value) > 0
    elif page == "results":
        assert any(item.label == "Censo medio" for item in app.metric)
    elif page == "simulate":
        assert app.number_input(key="edit_recursos.boxes_None").value == 30
    else:
        assert app.header[0].value == "older"
        assert app.get("html") and app.get("vega_lite_chart")
        assert app.selectbox(key="replay_day_widget").value == 0
