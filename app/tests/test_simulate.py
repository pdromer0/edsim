"""Exercise simulation editing through the real navigation entrypoint."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import edsim_app
from edsim.runs import read_center_values, write_variant
from edsim_app import defaults

MAIN = Path(edsim_app.__file__).resolve().with_name("main.py")


def open_simulation():
    app = AppTest.from_file(MAIN, default_timeout=15).run(timeout=15)
    app.switch_page("views/simulate.py").run(timeout=15)
    assert not app.exception
    assert app.title[0].value == "Simular"
    return app


def edit(app, key, index, value):
    app.number_input(key=f"edit_{key}_{index}").set_value(value).run()
    assert not app.exception
    return app


def named_variant(name="night", *, comment=False):
    path = defaults.VARIANTS_DIR / f"{name}.toml"
    write_variant(defaults.CENTER_PATH, read_center_values(defaults.CENTER_PATH), path)
    if comment:
        path.write_bytes(
            path.read_bytes().replace(b"# Centro base", b"# Comentario propio\n# Centro base")
        )
    return path


def test_all_widget_types_are_fixed_and_base_numbers_visible():
    app = open_simulation()
    for widget in app.number_input:
        integer = widget.key.startswith(("edit_turnos.", "edit_recursos."))
        assert type(widget.value) is (int if integer else float)
        assert widget.proto.format == ("%d" if integer else "%.17g")
    visible = " ".join(item.value for item in app.markdown)
    assert "Suma del reparto: 100,0" in visible
    assert {metric.label: metric.value for metric in app.metric} == {
        "Pruebas globales": "55,410 %",
        "Ingreso global": "12,843 %",
    }


def test_multiple_errors_disable_saving_and_show_each_diagnostic():
    app = open_simulation()
    edit(app, "recursos.medicos", 0, 0)
    edit(app, "duraciones.triaje", 1, 4.0)
    app.text_input(key="variant_name_widget").set_value("invalid").run()
    assert not app.exception
    assert any("recursos.medicos[0] must be at least 1" in e.value for e in app.error)
    assert any("p90 must be greater" in e.value for e in app.error)
    assert app.button(key="save_variant").disabled
    assert not (defaults.VARIANTS_DIR / "invalid.toml").exists()


def test_change_list_and_save_preserve_only_edited_bytes_from_source():
    source = named_variant(comment=True)
    before = source.read_bytes()
    app = open_simulation()
    app.selectbox(key="source_widget").select(str(source)).run()
    edit(app, "recursos.medicos", 1, 15)
    assert any("recursos.medicos: (12, 12, 7) → (12, 15, 7)" in x.value for x in app.markdown)
    app.text_input(key="variant_name_widget").set_value("edited").run()
    app.button(key="save_variant").click().run()
    assert not app.exception
    assert (defaults.VARIANTS_DIR / "edited.toml").read_bytes() == before.replace(
        b"medicos = [12, 12, 7]", b"medicos = [12, 15, 7]"
    )
    assert source.read_bytes() == before
    assert any("Todos los cambios están guardados" in x.value for x in app.caption)
    assert app.selectbox(key="source_widget").value == str(defaults.VARIANTS_DIR / "edited.toml")


def test_overwrite_cancel_confirm_and_edit_cancels_pending_confirmation():
    destination = named_variant()
    before = destination.read_bytes()
    app = open_simulation()
    edit(app, "recursos.boxes", None, 31)
    app.text_input(key="variant_name_widget").set_value("night").run()
    app.button(key="save_variant").click().run()
    assert destination.read_bytes() == before
    assert app.button(key="confirm_overwrite")
    app.button(key="cancel_overwrite").click().run()
    assert destination.read_bytes() == before
    assert not any(b.key == "confirm_overwrite" for b in app.button)
    app.button(key="save_variant").click().run()
    edit(app, "recursos.boxes", None, 32)
    assert not any(b.key == "confirm_overwrite" for b in app.button)
    assert destination.read_bytes() == before
    app.button(key="save_variant").click().run()
    app.button(key="confirm_overwrite").click().run()
    assert not app.exception
    assert destination.read_bytes() == before.replace(b"boxes = 30", b"boxes = 32")


def test_draft_survives_navigation_and_raw_equivalent_edit_is_unsaved():
    app = open_simulation()
    edit(app, "recursos.medicos", 0, 13)
    app.switch_page("views/runs.py").run()
    assert app.title[0].value == "Ejecuciones"
    app.switch_page("views/simulate.py").run()
    assert not app.exception
    assert app.number_input(key="edit_recursos.medicos_0").value == 13
    assert any("Cambios sin guardar" in x.value for x in app.caption)
    edit(app, "recursos.medicos", 0, 12)
    assert any("Todos los cambios están guardados" in x.value for x in app.caption)


def test_switching_dirty_source_requires_confirmation_or_cancel():
    destination = named_variant()
    app = open_simulation()
    edit(app, "recursos.boxes", None, 31)
    app.selectbox(key="source_widget").select(str(destination)).run()
    assert any("Descartarlos" in x.value for x in app.warning)
    assert app.number_input(key="edit_recursos.boxes_None").value == 31
    app.button(key="cancel_source").click().run()
    assert app.selectbox(key="source_widget").value == str(defaults.CENTER_PATH)
    assert app.number_input(key="edit_recursos.boxes_None").value == 31
    app.selectbox(key="source_widget").select(str(destination)).run()
    app.button(key="confirm_source").click().run()
    assert not app.exception
    assert app.selectbox(key="source_widget").value == str(destination)
    assert app.number_input(key="edit_recursos.boxes_None").value == 30


@pytest.mark.parametrize("removed", [False, True])
def test_external_source_change_or_removal_blocks_save(removed):
    source = named_variant()
    app = open_simulation()
    app.selectbox(key="source_widget").select(str(source)).run()
    edit(app, "recursos.boxes", None, 31)
    if removed:
        source.unlink()
    else:
        source.write_bytes(source.read_bytes().replace(b"boxes = 30", b"boxes = 35"))
    app.run()
    assert not app.exception
    assert any("El origen ha cambiado" in x.value for x in app.warning)
    assert app.number_input(key="edit_recursos.boxes_None").value == 31
    assert app.button(key="save_variant").disabled


@pytest.mark.parametrize("name", ["centro", "bad name", "x" * 43])
def test_invalid_or_reserved_variant_name_blocks_save(name):
    app = open_simulation()
    app.text_input(key="variant_name_widget").set_value(name).run()
    assert not app.exception
    assert app.button(key="save_variant").disabled
    assert app.error
    if name == "centro":
        assert "reservado al centro base" in app.error[0].value


def test_preview_displays_core_table_caches_edits_and_profile_fingerprint(monkeypatch):
    import os
    from unittest.mock import Mock

    import edsim_app.preview as preview
    from edsim.runs import center_from_values, load_profile
    from edsim_app.frames import utilization_frame

    calculate = Mock(wraps=preview.offered_work)
    monkeypatch.setattr(preview, "offered_work", calculate)
    app = open_simulation()
    assert calculate.call_count == 1
    args = calculate.call_args
    assert args.kwargs == {"days": 7}
    # Compute the expected table with the same small real core calculation.
    work = calculate._mock_wraps(*args.args, **args.kwargs)
    assert app.dataframe[0].value.equals(utilization_frame(work))
    app.selectbox(key="preview_pool").select("boxes").run()
    assert not app.exception
    assert calculate.call_count == 1
    edit(app, "recursos.medicos", 0, 13)
    assert calculate.call_count == 2
    assert not app.dataframe[0].value.equals(utilization_frame(work))
    before = defaults.PROFILE_PATH.stat()
    defaults.PROFILE_PATH.write_bytes(
        defaults.PROFILE_PATH.read_bytes().replace(b"base_diaria = 300", b"base_diaria = 600")
    )
    os.utime(defaults.PROFILE_PATH, ns=(before.st_atime_ns, before.st_mtime_ns))
    app.run()
    assert not app.exception
    assert calculate.call_count == 3
    values = read_center_values(defaults.CENTER_PATH)
    values["recursos.medicos"][0] = 13
    changed = calculate._mock_wraps(
        center_from_values(values), load_profile(defaults.PROFILE_PATH), 7
    )
    assert app.dataframe[0].value.equals(utilization_frame(changed))


def test_preview_explains_multiple_prior_days(monkeypatch):
    from dataclasses import replace

    from edsim.runs import load_center, load_profile
    from edsim_app import preview

    small = preview.offered_work(
        load_center(defaults.CENTER_PATH), load_profile(defaults.PROFILE_PATH), 7
    )
    monkeypatch.setattr(
        preview, "offered_work", lambda *args, **kwargs: replace(small, prior_days=3)
    )
    app = open_simulation()
    assert any("3 días previos" in x.value for x in app.markdown)
    assert any("empieza vacía" in x.value for x in app.markdown)
