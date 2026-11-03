"""Exercise each page through the real navigation entrypoint."""

from pathlib import Path
from unittest.mock import Mock

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import edsim_app

MAIN = Path(edsim_app.__file__).resolve().with_name("main.py")


def test_default_page_and_registered_url_paths(monkeypatch):
    page_factory = Mock(wraps=st.Page)
    monkeypatch.setattr(st, "Page", page_factory)
    app = AppTest.from_file(MAIN).run()

    assert not app.exception
    assert [title.value for title in app.title] == ["Ejecuciones"]
    assert [call.kwargs["url_path"] for call in page_factory.call_args_list] == [
        "ejecuciones",
        "simular",
        "resultados",
        "episodios",
        "comparar",
        "replay",
    ]


@pytest.mark.parametrize(
    ("filename", "title"),
    [
        ("simulate", "Simular"),
        ("results", "Resultados"),
        ("episodes", "Episodios"),
        ("compare", "Comparar"),
        ("replay", "Replay"),
    ],
)
def test_switch_page_after_initial_run(filename, title):
    app = AppTest.from_file(MAIN).run()
    assert not app.exception
    assert [heading.value for heading in app.title] == ["Ejecuciones"]

    app.switch_page(f"pages/{filename}.py").run()

    assert not app.exception
    assert [heading.value for heading in app.title] == [title]
