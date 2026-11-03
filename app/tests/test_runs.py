"""Exercise the catalog through the same entrypoint used by the browser."""

import shutil
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock
from zipfile import ZipFile

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import edsim_app
from edsim.runs import RunStore

MAIN = Path(edsim_app.__file__).resolve().with_name("main.py")


def select_run(app, run_id):
    app.selectbox(key="run_choice").select(run_id).run()
    assert not app.exception
    return app


def test_catalog_lists_newest_first_and_displays_path(catalog):
    app = AppTest.from_file(MAIN).run()
    assert not app.exception
    assert app.dataframe[0].value["Ejecución"].tolist() == ["newer", "older"]
    assert app.selectbox[0].options == ["newer", "older"]
    assert app.selectbox[0].value is None
    assert str(catalog) in app.caption[0].value


def test_selection_updates_sidebar_and_url(catalog):
    app = select_run(AppTest.from_file(MAIN).run(), "older")
    assert app.selectbox[0].value == "older"
    assert app.query_params["run"] == "older"
    assert "older" in [item.value for item in app.sidebar.markdown]
    select_run(app, "newer")
    assert app.query_params["run"] == "newer"
    assert "newer" in [item.value for item in app.sidebar.markdown]


def test_comparison_marks_survive_changing_selection_and_navigation(catalog):
    app = select_run(AppTest.from_file(MAIN).run(), "older")
    app.button(key="mark_a").click().run()
    select_run(app, "newer")
    app.button(key="mark_b").click().run()
    assert not app.exception
    assert "Marca A: older" in [item.value for item in app.sidebar.markdown]
    assert "Marca B: newer" in [item.value for item in app.sidebar.markdown]
    app.switch_page("views/compare.py").run()
    assert not app.exception
    assert app.title[0].value == "Comparar"
    assert "Marca A: older" in [item.value for item in app.sidebar.markdown]
    assert "Marca B: newer" in [item.value for item in app.sidebar.markdown]
    app.switch_page("views/runs.py").run()
    assert app.selectbox[0].value == "newer"
    assert app.query_params["run"] == "newer"


@pytest.mark.parametrize(
    "filename, title",
    [
        ("results", "Resultados"),
        ("episodes", "Episodios"),
        ("replay", "Replay"),
    ],
)
def test_open_action_reaches_destination_with_selected_run(catalog, filename, title):
    app = select_run(AppTest.from_file(MAIN).run(), "older")
    app.button(key=f"open_{filename}").click().run()
    assert not app.exception
    assert app.title[0].value == title
    assert app.query_params["run"] == "older"
    assert "older" in [item.value for item in app.sidebar.markdown]


def test_download_is_deferred_and_uses_selected_run_filename(catalog, monkeypatch):
    download = Mock(wraps=st.download_button)
    archive = Mock(wraps=RunStore.archive)

    # Binding the original method explicitly keeps the real zip implementation.
    def record_archive(self, run_id):
        return archive(self, run_id)

    monkeypatch.setattr(st, "download_button", download)
    monkeypatch.setattr(RunStore, "archive", record_archive)
    app = select_run(AppTest.from_file(MAIN).run(), "older")
    app.run()
    assert not app.exception
    assert app.get("download_button")[0].label == "Descargar zip"
    args = download.call_args.kwargs
    assert args["file_name"] == "older.zip"
    assert args["mime"] == "application/zip"
    assert callable(args["data"])
    archive.assert_not_called()
    with ZipFile(BytesIO(args["data"]())) as zipped:
        assert len(zipped.namelist()) == 6
        assert zipped.read("run.json") == (catalog / "older" / "run.json").read_bytes()
    assert archive.call_count == 1
    select_run(app, "newer")
    assert download.call_args.kwargs["file_name"] == "newer.zip"


def test_confirmed_deletion_cleans_selection_and_both_marks(catalog):
    app = select_run(AppTest.from_file(MAIN).run(), "older")
    app.button(key="mark_a").click().run()
    app.button(key="mark_b").click().run()
    assert "Marca A: older" in [item.value for item in app.sidebar.markdown]
    assert "Marca B: older" in [item.value for item in app.sidebar.markdown]
    app.button(key="delete_run").click().run()
    assert (catalog / "older").is_dir()
    assert "older" in app.warning[0].value
    app.button(key="confirm_delete").click().run()
    assert not app.exception
    assert not (catalog / "older").exists()
    assert (catalog / "newer").is_dir()
    assert app.dataframe[0].value["Ejecución"].tolist() == ["newer"]
    assert app.selectbox[0].value is None
    assert "run" not in app.query_params
    assert [item.value for item in app.sidebar.markdown] == [
        "Ninguna",
        "Marca A: Ninguna",
        "Marca B: Ninguna",
    ]
    assert "older" in app.success[0].value
    assert not app.warning


def test_deletion_preserves_marks_for_other_runs(catalog):
    app = select_run(AppTest.from_file(MAIN).run(), "newer")
    app.button(key="mark_b").click().run()
    select_run(app, "older")
    app.button(key="mark_a").click().run()
    app.button(key="delete_run").click().run()
    app.button(key="confirm_delete").click().run()
    assert not app.exception
    assert "Marca A: Ninguna" in [item.value for item in app.sidebar.markdown]
    assert "Marca B: newer" in [item.value for item in app.sidebar.markdown]
    assert not (catalog / "older").exists()


def test_external_deletion_of_unselected_marks_is_checked_on_other_pages(catalog):
    app = select_run(AppTest.from_file(MAIN).run(), "older")
    app.button(key="mark_a").click().run()
    app.button(key="mark_b").click().run()
    select_run(app, "newer")
    app.switch_page("views/results.py").run()
    assert "Marca A: older" in [item.value for item in app.sidebar.markdown]
    assert "Marca B: older" in [item.value for item in app.sidebar.markdown]
    shutil.rmtree(catalog / "older")
    app.run()
    assert not app.exception
    assert app.title[0].value == "Resultados"
    assert app.query_params["run"] == "newer"
    assert len(app.warning) == 1 and "older" in app.warning[0].value
    assert [item.value for item in app.sidebar.markdown] == [
        "newer",
        "Marca A: Ninguna",
        "Marca B: Ninguna",
    ]
    app.run()
    assert not app.warning


def test_cancel_deletion_preserves_disk_and_selection(catalog):
    app = select_run(AppTest.from_file(MAIN).run(), "older")
    before = (catalog / "older" / "run.json").read_bytes()
    app.button(key="delete_run").click().run()
    app.button(key="cancel_delete").click().run()
    assert not app.exception
    assert not app.warning
    assert not any(button.label == "Confirmar borrado" for button in app.button)
    assert (catalog / "older" / "run.json").read_bytes() == before
    assert app.selectbox[0].value == "older"


def test_changing_selection_cancels_pending_deletion(catalog):
    app = select_run(AppTest.from_file(MAIN).run(), "older")
    app.button(key="delete_run").click().run()
    select_run(app, "newer")
    assert not app.warning
    assert not any(button.label == "Confirmar borrado" for button in app.button)
    assert (catalog / "older").is_dir() and (catalog / "newer").is_dir()


def test_invalid_folders_show_reasons_and_safe_deletion(catalog, tmp_path):
    (catalog / "incomplete").mkdir()
    (catalog / "-bad").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "protected.txt").write_text("untouched")
    (catalog / "linked").symlink_to(outside, target_is_directory=True)
    app = AppTest.from_file(MAIN).run()
    assert not app.exception
    assert "Carpetas no válidas" in [item.label for item in app.expander]
    diagnostics = [item.value for item in app.markdown if "Motivo:" in item.value]
    assert len(diagnostics) == 3
    assert all(
        any(name in item for item in diagnostics) for name in ("incomplete", "-bad", "linked")
    )
    assert all(item.split("Motivo:")[1].strip() for item in diagnostics)
    assert len([item for item in app.caption if "borrarla a mano" in item.value]) == 2
    assert [b.label for b in app.button] == ["Borrar carpeta «incomplete»"]
    app.button(key="delete_invalid_incomplete").click().run()
    assert (catalog / "incomplete").is_dir()
    app.button(key="confirm_delete").click().run()
    assert not app.exception
    assert not (catalog / "incomplete").exists()
    assert (catalog / "-bad").is_dir()
    assert (catalog / "linked").is_symlink()
    assert (outside / "protected.txt").read_text() == "untouched"
