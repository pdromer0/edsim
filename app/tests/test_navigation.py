"""Exercise each page through the real navigation entrypoint."""

import shutil
from pathlib import Path
from unittest.mock import Mock

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import edsim_app

MAIN = Path(edsim_app.__file__).resolve().with_name("main.py")


def test_no_legacy_pages_directory_next_to_entrypoint():
    # A pages/ directory activates legacy navigation, which can skip main.py
    # on direct entry and in AppTest (notably for the matching Replay URL).
    assert not MAIN.with_name("pages").exists()


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

    app.switch_page(f"views/{filename}.py").run()

    assert not app.exception
    assert [heading.value for heading in app.title] == [title]


def test_initial_valid_link_selects_run(catalog):
    app = AppTest.from_file(MAIN)
    app.query_params.update(run="older", extra="preserved")
    app.run()
    assert not app.exception
    assert "older" in [item.value for item in app.sidebar.markdown]
    assert app.session_state["selected_run_id"] == "older"
    assert app.query_params == {"run": "older", "extra": "preserved"}


@pytest.mark.parametrize("run_id", ["absent", "../outside", ""])
def test_initial_unknown_link_warns_once_and_clears_url(catalog, run_id):
    app = AppTest.from_file(MAIN)
    app.query_params["run"] = run_id
    app.run()
    assert not app.exception
    assert len(app.warning) == 1
    assert "no está en el catálogo" in app.warning[0].value
    assert "run" not in app.query_params
    assert app.session_state["selected_run_id"] is None
    app.run()
    assert not app.warning


@pytest.mark.parametrize("page", ["simulate", "results", "episodes", "compare", "replay"])
def test_selection_and_marks_survive_navigation_and_restore_url(catalog, page):
    app = AppTest.from_file(MAIN)
    app.query_params["run"] = "older"
    app.session_state["compare_a"] = "older"
    app.session_state["compare_b"] = "newer"
    app.run()
    # AppTest.switch_page does not clear URL params like the browser sidebar does.
    app.query_params.clear()
    app.switch_page(f"views/{page}.py").run()
    assert not app.exception
    assert app.title[0].value != "Ejecuciones"
    assert app.query_params["run"] == "older"
    visible = [item.value for item in app.sidebar.markdown]
    assert "older" in visible
    assert "Marca A: older" in visible
    assert "Marca B: newer" in visible


def test_external_deletion_clears_selection_and_marks_with_one_warning(catalog):
    app = AppTest.from_file(MAIN).run()
    app.selectbox(key="run_choice").select("older").run()
    app.button(key="mark_a").click().run()
    app.button(key="mark_b").click().run()
    assert "older" in [item.value for item in app.sidebar.markdown]
    shutil.rmtree(catalog / "older")
    app.run()
    assert not app.exception
    assert len(app.warning) == 1
    assert "older" in app.warning[0].value
    assert "ya no está" in app.warning[0].value
    assert "run" not in app.query_params
    assert all(
        app.session_state[key] is None for key in ("selected_run_id", "compare_a", "compare_b")
    )
    assert [item.value for item in app.sidebar.markdown] == [
        "Ninguna",
        "Marca A: Ninguna",
        "Marca B: Ninguna",
    ]
    app.run()
    assert not app.warning


def test_default_catalog_is_relative_to_launch_directory(tmp_path, monkeypatch):
    from edsim_app.state import catalog_store

    monkeypatch.delenv("EDSIM_EJECUCIONES")
    monkeypatch.chdir(tmp_path)
    assert catalog_store().root == tmp_path / "resultados" / "ejecuciones"


def test_overridden_catalog_can_be_relative(tmp_path, monkeypatch):
    from edsim_app.state import catalog_store

    monkeypatch.setenv("EDSIM_EJECUCIONES", "other-runs")
    monkeypatch.chdir(tmp_path)
    assert catalog_store().root == tmp_path / "other-runs"
