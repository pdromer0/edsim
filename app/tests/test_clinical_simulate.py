"""Exercise clinical inputs, demand caching and actual one-day simulation."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

import edsim_app
from edsim.runs import (
    RunStore,
    config_fingerprint,
    load_profile,
    load_profiles,
    read_center_values,
    summarize_profiles,
)
from edsim_app import defaults, preview
from edsim_app.frames import utilization_frame

pytestmark = pytest.mark.slow
MAIN = Path(edsim_app.__file__).with_name("main.py")


def open_clinical():
    app = AppTest.from_file(MAIN).run()
    app.switch_page("views/simulate.py").run()
    assert app.title[0].value == "Simular" and not app.exception
    return app


def test_default_clinical_summary_and_saved_one_day_run(catalog_root):
    app = open_clinical()
    assert app.selectbox(key="model_widget").value == "clinico"
    assert app.text_input(key="clinical_path_widget").value == str(defaults.CLINICAL_PROFILES_PATH)
    assert not any(
        w.key.startswith(("edit_triaje.", "edit_duraciones.", "edit_pruebas."))
        for w in app.number_input
    )
    expected = summarize_profiles(
        load_profiles(defaults.CLINICAL_PROFILES_PATH), load_profile(defaults.PROFILE_PATH)
    )
    assert app.dataframe[0].value["Porcentaje esperado"].tolist() == list(
        expected.reason_percentages.values()
    )
    metrics = {m.label: m.value for m in app.metric}
    assert metrics[
        "Médico total esperado"
    ] == f"{expected.physician_minutes:.2f} min/paciente".replace(".", ",")
    app.number_input(key="days_widget").set_value(1).run()
    app.button(key="simulate_run").click().run()
    assert not app.exception and not app.error
    info = RunStore(catalog_root).open("centro-r2026")
    assert info.is_clinical and info.days == 1 and info.warmup_days == 0
    assert info.clinical_profiles_fingerprint == config_fingerprint(defaults.CLINICAL_PROFILES_PATH)
    assert (
        catalog_root / info.run_id / "perfiles.toml"
    ).read_bytes() == defaults.CLINICAL_PROFILES_PATH.read_bytes()
    app.button(key="view_results").click().run()
    assert app.title[0].value == "Resultados" and app.metric and not app.exception


def test_staff_changes_reuse_sample_and_profiles_and_room_invalidate_it():
    values = read_center_values(defaults.CENTER_PATH)
    spy = Mock(wraps=preview.offered_load)
    original = preview.offered_load
    preview.offered_load = spy
    try:
        work = preview.preview_work(values, defaults.PROFILE_PATH, defaults.CLINICAL_PROFILES_PATH)
        changed = dict(values)
        changed["recursos.medicos"] = [n + 1 for n in values["recursos.medicos"]]
        new = preview.preview_work(changed, defaults.PROFILE_PATH, defaults.CLINICAL_PROFILES_PATH)
        assert spy.call_count == 1
        assert (work.load["medicos"] == new.load["medicos"]).all()
        assert not utilization_frame(work).equals(utilization_frame(new))
        changed["recursos.espera_resultados_fuera"] = []
        preview.preview_work(changed, defaults.PROFILE_PATH, defaults.CLINICAL_PROFILES_PATH)
        assert spy.call_count == 2
        path = defaults.CLINICAL_PROFILES_PATH
        path.write_text(path.read_text().replace("peso_base = 7.397", "peso_base = 11.0955"))
        preview.preview_work(changed, defaults.PROFILE_PATH, path)
        assert spy.call_count == 3
    finally:
        preview.offered_load = original


@pytest.mark.parametrize("content", [None, "[broken", "unknown = 1"])
def test_invalid_clinical_file_is_a_message_and_blocks_simulation(content):
    path = defaults.CLINICAL_PROFILES_PATH
    if content is None:
        path.unlink()
    else:
        path.write_text(content)
    app = open_clinical()
    assert not app.exception and app.button(key="simulate_run").disabled
    assert any("No se pueden cargar los perfiles clínicos" in item.value for item in app.error)


def test_switching_models_keeps_draft_settings_and_room_in_variants():
    app = open_clinical()
    app.number_input(key="edit_recursos.medicos_0").set_value(13).run()
    app.text_input(key="seed_widget").set_value("7").run()
    app.selectbox(key="model_widget").select("provisional").run()
    assert app.number_input(key="edit_duraciones.triaje_0")
    app.selectbox(key="model_widget").select("clinico").run()
    assert app.number_input(key="edit_recursos.medicos_0").value == 13
    assert app.text_input(key="seed_widget").value == "7"
    app.text_input(key="variant_name_widget").set_value("staff").run()
    app.button(key="save_variant").click().run()
    assert not app.exception
    assert (
        read_center_values(defaults.VARIANTS_DIR / "staff.toml")["recursos.espera_resultados_fuera"]
        == read_center_values(defaults.CENTER_PATH)["recursos.espera_resultados_fuera"]
    )


def test_clinical_editor_ignores_absurd_provisional_fields(monkeypatch):
    import pandas as pd

    from edsim.runs import write_variant

    app = open_clinical()
    expected = [table.value.copy() for table in app.dataframe]
    metrics = {m.label: m.value for m in app.metric}
    values = read_center_values(defaults.CENTER_PATH)
    values["triaje.reparto_niveles"] = [96, 1, 1, 1, 1]
    values["duraciones.triaje"] = [500, 1000]
    values["duraciones.valoracion"] = [500, 1000]
    values["duraciones.reevaluacion"] = [500, 1000]
    values["duraciones.respuesta_pruebas"] = [500, 1000]
    values["pruebas.probabilidad"] = [0] * 5
    variant = defaults.VARIANTS_DIR / "absurd.toml"
    write_variant(defaults.CENTER_PATH, values, variant)
    # Opening a fresh page loads the changed file, rather than an existing draft.
    monkeypatch.setattr(defaults, "CENTER_PATH", variant)
    import edsim.runs as runs

    monkeypatch.setattr(
        runs,
        "summarize_center",
        Mock(
            side_effect=AssertionError("clinical model must not summarize the provisional center")
        ),
    )
    actual = open_clinical()
    for table, reference in zip(actual.dataframe, expected, strict=True):
        pd.testing.assert_frame_equal(table.value, reference)
    assert {m.label: m.value for m in actual.metric} == metrics


def test_local_profile_path_survives_navigation_and_updates_summary():
    import tomlkit

    path = defaults.CLINICAL_PROFILES_PATH.parent / "alternative.toml"
    document = tomlkit.parse(defaults.CLINICAL_PROFILES_PATH.read_text())
    document["motivos"]["disnea"]["peso_base"] *= 1.5
    path.write_text(tomlkit.dumps(document))
    app = open_clinical()
    original = app.dataframe[0].value.copy()
    app.text_input(key="clinical_path_widget").set_value(str(path)).run()
    assert not app.exception and not original.equals(app.dataframe[0].value)
    expected = summarize_profiles(load_profiles(path), load_profile(defaults.PROFILE_PATH))
    assert app.dataframe[0].value["Porcentaje esperado"].tolist() == list(
        expected.reason_percentages.values()
    )
    app.switch_page("views/runs.py").run()
    app.switch_page("views/simulate.py").run()
    assert app.text_input(key="clinical_path_widget").value == str(path)
    assert any(config_fingerprint(path) in t.value for t in app.caption)


def test_spinner_is_shown_only_when_a_new_clinical_sample_is_needed(monkeypatch):
    import streamlit as st

    spinner = Mock(wraps=st.spinner)
    monkeypatch.setattr(st, "spinner", spinner)
    values = read_center_values(defaults.CENTER_PATH)
    preview.preview_work(values, defaults.PROFILE_PATH, defaults.CLINICAL_PROFILES_PATH)
    before = sum(
        call.args == ("Calculando la carga prevista con los perfiles…",)
        for call in spinner.call_args_list
    )
    assert before == 1
    values["recursos.medicos"][0] += 1
    preview.preview_work(values, defaults.PROFILE_PATH, defaults.CLINICAL_PROFILES_PATH)
    assert (
        sum(
            call.args == ("Calculando la carga prevista con los perfiles…",)
            for call in spinner.call_args_list
        )
        == before
    )


def test_load_values_match_public_offered_work():
    import numpy as np

    from edsim.runs import center_from_values, offered_work

    values = read_center_values(defaults.CENTER_PATH)
    actual = preview.preview_work(values, defaults.PROFILE_PATH, defaults.CLINICAL_PROFILES_PATH)
    expected = offered_work(
        center_from_values(values),
        load_profile(defaults.PROFILE_PATH),
        7,
        profiles=load_profiles(defaults.CLINICAL_PROFILES_PATH),
        sample_size=32,
    )
    assert actual.prior_days == expected.prior_days
    for pool in actual.load:
        np.testing.assert_array_equal(actual.load[pool], expected.load[pool])
        np.testing.assert_array_equal(actual.capacity[pool], expected.capacity[pool])
    assert actual.utilization == expected.utilization
