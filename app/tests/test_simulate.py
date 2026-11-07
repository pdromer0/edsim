"""Exercise simulation editing through the real navigation entrypoint."""

import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import edsim_app
from edsim.runs import RunConfigurationError, read_center_values, write_variant
from edsim_app import defaults

MAIN = Path(edsim_app.__file__).resolve().with_name("main.py")


def expected_sequence(values):
    """Spell out the Spanish separators and decimal commas expected in the UI."""
    return "[" + "; ".join(f"{value:.15g}".replace(".", ",") for value in values) + "]"


def replace_raw_value(source, key, replacement, index=None):
    """Replace one actual TOML value while retaining all surrounding bytes."""
    pattern = rb"(?m)^" + key.encode() + rb"[ \t]*=[ \t]*(\[[^\]\r\n]*\]|[^ \t#\r\n]+)"
    matches = list(re.finditer(pattern, source))
    assert len(matches) == 1
    match = matches[0]
    start, end = match.span(1)
    if index is not None:
        token = list(re.finditer(rb"[^,\[\]\s]+", match[1]))[index]
        start, end = start + token.start(), start + token.end()
    changed = source[:start] + replacement.encode() + source[end:]
    assert changed != source
    return changed


def open_simulation():
    app = AppTest.from_file(MAIN, default_timeout=15)
    app.session_state["simulation_settings"] = {
        "clinical_path": str(defaults.CLINICAL_PROFILES_PATH),
        "days": defaults.SIMULATION_DAYS,
        "warmup_days": min(defaults.SIMULATION_WARMUP_DAYS, defaults.SIMULATION_DAYS - 1),
        "seed": "2026",
        "run_id": "",
        "run_id_mode": "automatic",
    }
    app.run(timeout=15)
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


def test_all_widget_types_are_fixed_and_base_numbers_visible(center_template):
    app = open_simulation()
    for widget in app.number_input:
        integer = widget.key.startswith(("edit_turnos.", "edit_recursos.")) or widget.key in (
            "days_widget",
            "warmup_widget",
        )
        assert type(widget.value) is (int if integer else float)
        assert widget.proto.format == ("%d" if integer else "%.15g")
    for key in ("medicos", "enfermeria_triaje", "boxes"):
        value = center_template["recursos"][key]
        if isinstance(value, list):
            for index, count in enumerate(value):
                assert app.number_input(key=f"edit_recursos.{key}_{index}").value == count
        else:
            assert app.number_input(key=f"edit_recursos.{key}_None").value == value
    assert not any(widget.key == "model_widget" for widget in app.selectbox)
    assert not any(
        widget.key.startswith(("edit_triaje.", "edit_duraciones.", "edit_pruebas."))
        for widget in app.number_input
    )
    assert (
        app.number_input(key="edit_turnos.inicio_0").value == center_template["turnos"]["inicio"][0]
    )
    assert (
        app.number_input(key="edit_destino.probabilidad_ingreso_0").value
        == (center_template["destino"]["probabilidad_ingreso"][0])
    )


def test_multiple_errors_disable_saving_and_show_each_diagnostic():
    app = open_simulation()
    edit(app, "recursos.medicos", 0, 0)
    edit(app, "destino.probabilidad_ingreso", 1, 1.1)
    app.text_input(key="variant_name_widget").set_value("invalid").run()
    assert not app.exception
    assert any("recursos.medicos[0] must be at least 1" in e.value for e in app.error)
    assert any("destino.probabilidad_ingreso[1]" in e.value for e in app.error)
    assert app.button(key="save_variant").disabled
    assert app.button(key="simulate_run").disabled
    assert not (defaults.VARIANTS_DIR / "invalid.toml").exists()


def test_change_list_and_save_preserve_only_edited_bytes_from_source(center_template):
    doctors = center_template["recursos"]["medicos"]
    edited_doctors = doctors.copy()
    edited_doctors[1] += 3
    source = named_variant(comment=True)
    before = source.read_bytes()
    app = open_simulation()
    app.selectbox(key="source_widget").select(str(source)).run()
    edit(app, "recursos.medicos", 1, edited_doctors[1])
    assert any(
        (
            f"**Médicos** · `recursos.medicos`: {expected_sequence(doctors)} → "
            f"{expected_sequence(edited_doctors)}"
        )
        in x.value
        for x in app.markdown
    )
    app.text_input(key="variant_name_widget").set_value("edited").run()
    app.button(key="save_variant").click().run()
    assert not app.exception
    assert (defaults.VARIANTS_DIR / "edited.toml").read_bytes() == replace_raw_value(
        before, "medicos", str(edited_doctors[1]), index=1
    )
    assert source.read_bytes() == before
    assert any("Todos los cambios están guardados" in x.value for x in app.caption)
    assert app.selectbox(key="source_widget").value == str(defaults.VARIANTS_DIR / "edited.toml")


def test_overwrite_cancel_confirm_and_edit_cancels_pending_confirmation(center_template):
    boxes = center_template["recursos"]["boxes"]
    edited_boxes = boxes + 1
    destination = named_variant()
    before = destination.read_bytes()
    app = open_simulation()
    edit(app, "recursos.boxes", None, edited_boxes)
    app.text_input(key="variant_name_widget").set_value("night").run()
    app.button(key="save_variant").click().run()
    assert destination.read_bytes() == before
    assert app.button(key="confirm_overwrite")
    app.button(key="cancel_overwrite").click().run()
    assert destination.read_bytes() == before
    assert not any(b.key == "confirm_overwrite" for b in app.button)
    app.button(key="save_variant").click().run()
    edit(app, "recursos.boxes", None, boxes + 2)
    assert not any(b.key == "confirm_overwrite" for b in app.button)
    assert destination.read_bytes() == before
    app.button(key="save_variant").click().run()
    app.button(key="confirm_overwrite").click().run()
    assert not app.exception
    assert destination.read_bytes() == replace_raw_value(before, "boxes", str(boxes + 2))


def test_draft_survives_navigation_and_raw_equivalent_edit_is_unsaved(center_template):
    doctors = center_template["recursos"]["medicos"][0]
    edited_doctors = doctors + 1
    app = open_simulation()
    edit(app, "recursos.medicos", 0, edited_doctors)
    app.switch_page("views/runs.py").run()
    assert app.title[0].value == "Ejecuciones"
    app.switch_page("views/simulate.py").run()
    assert not app.exception
    assert app.number_input(key="edit_recursos.medicos_0").value == edited_doctors
    assert any("Cambios sin guardar" in x.value for x in app.caption)
    edit(app, "recursos.medicos", 0, doctors)
    assert any("Todos los cambios están guardados" in x.value for x in app.caption)


def test_switching_dirty_source_requires_confirmation_or_cancel(center_template):
    boxes = center_template["recursos"]["boxes"]
    edited_boxes = boxes + 1
    destination = named_variant()
    app = open_simulation()
    edit(app, "recursos.boxes", None, edited_boxes)
    app.selectbox(key="source_widget").select(str(destination)).run()
    assert any("Descartarlos" in x.value for x in app.warning)
    assert app.number_input(key="edit_recursos.boxes_None").value == edited_boxes
    app.button(key="cancel_source").click().run()
    assert app.selectbox(key="source_widget").value == str(defaults.CENTER_PATH)
    assert app.number_input(key="edit_recursos.boxes_None").value == edited_boxes
    app.selectbox(key="source_widget").select(str(destination)).run()
    app.button(key="confirm_source").click().run()
    assert not app.exception
    assert app.selectbox(key="source_widget").value == str(destination)
    assert app.number_input(key="edit_recursos.boxes_None").value == boxes


@pytest.mark.parametrize("removed", [False, True])
def test_external_source_change_or_removal_blocks_save(removed, center_template):
    boxes = center_template["recursos"]["boxes"]
    edited_boxes = boxes + 1
    source = named_variant()
    app = open_simulation()
    app.selectbox(key="source_widget").select(str(source)).run()
    edit(app, "recursos.boxes", None, edited_boxes)
    if removed:
        source.unlink()
    else:
        source.write_bytes(replace_raw_value(source.read_bytes(), "boxes", str(boxes + 5)))
    app.run()
    assert not app.exception
    assert any("El origen ha cambiado" in x.value for x in app.warning)
    assert app.number_input(key="edit_recursos.boxes_None").value == edited_boxes
    assert app.button(key="save_variant").disabled
    assert app.button(key="simulate_run").disabled


@pytest.mark.parametrize("name", ["centro", "bad name", "x" * 43])
def test_invalid_or_reserved_variant_name_blocks_save(name):
    app = open_simulation()
    app.text_input(key="variant_name_widget").set_value(name).run()
    assert not app.exception
    assert app.button(key="save_variant").disabled
    assert app.error
    if name == "centro":
        assert "reservado al centro base" in app.error[0].value


def test_preview_displays_core_table_caches_edits_and_profile_fingerprint(
    monkeypatch, center_template
):
    import os
    from unittest.mock import Mock

    import edsim_app.preview as preview
    from edsim.runs import center_from_values, load_profile, load_profiles, offered_work_from_load
    from edsim_app.frames import utilization_frame

    edited_doctors = center_template["recursos"]["medicos"][0] + 1
    calculate = Mock(wraps=preview.offered_load)
    monkeypatch.setattr(preview, "offered_load", calculate)
    app = open_simulation()
    assert calculate.call_count == 1
    args = calculate.call_args
    assert args.kwargs == {
        "profiles": load_profiles(defaults.CLINICAL_PROFILES_PATH),
        "sample_size": 50_000,
        "sample_seed": 73_001,
    }
    # Compute the expected table with the same small real core calculation.
    work = offered_work_from_load(args.args[0], calculate._mock_wraps(*args.args, **args.kwargs))
    assert app.dataframe[-1].value.equals(utilization_frame(work))
    app.selectbox(key="preview_pool").select("boxes").run()
    assert not app.exception
    assert calculate.call_count == 1
    edit(app, "recursos.medicos", 0, edited_doctors)
    assert calculate.call_count == 1
    assert not app.dataframe[-1].value.equals(utilization_frame(work))
    before = defaults.PROFILE_PATH.stat()
    defaults.PROFILE_PATH.write_bytes(
        defaults.PROFILE_PATH.read_bytes().replace(b"base_diaria = 300", b"base_diaria = 600")
    )
    os.utime(defaults.PROFILE_PATH, ns=(before.st_atime_ns, before.st_mtime_ns))
    app.run()
    assert not app.exception
    assert calculate.call_count == 2
    values = read_center_values(defaults.CENTER_PATH)
    values["recursos.medicos"][0] = edited_doctors
    center = center_from_values(values)
    changed = offered_work_from_load(
        center,
        calculate._mock_wraps(
            center,
            load_profile(defaults.PROFILE_PATH),
            7,
            profiles=load_profiles(defaults.CLINICAL_PROFILES_PATH),
        ),
    )
    assert app.dataframe[-1].value.equals(utilization_frame(changed))


def test_preview_explains_multiple_prior_days(monkeypatch):
    from dataclasses import replace

    from edsim.runs import load_center, load_profile, load_profiles
    from edsim_app import preview

    small = preview.offered_load(
        load_center(defaults.CENTER_PATH),
        load_profile(defaults.PROFILE_PATH),
        7,
        profiles=load_profiles(defaults.CLINICAL_PROFILES_PATH),
    )
    monkeypatch.setattr(
        preview, "offered_load", lambda *args, **kwargs: replace(small, prior_days=3)
    )
    app = open_simulation()
    assert any("3 días previos" in x.value for x in app.markdown)
    assert any("empieza vacía" in x.value for x in app.markdown)


@pytest.mark.parametrize("seed", ["", "-1", "1.5", "1_000", " 7", "٣", "9" * 21])
def test_invalid_seed_disables_simulation(seed):
    app = open_simulation()
    assert not app.button(key="simulate_run").disabled
    app.text_input(key="seed_widget").set_value(seed).run()
    assert not app.exception
    assert app.button(key="simulate_run").disabled
    assert any("entre 1 y 20 cifras ASCII" in e.value for e in app.error)


@pytest.mark.parametrize("seed, suffix", [("0", "0"), ("0007", "7"), ("9" * 20, "9" * 20)])
def test_valid_ascii_seed_keeps_all_digits_without_widget_integer_limits(seed, suffix):
    app = open_simulation()
    app.text_input(key="seed_widget").set_value(seed).run()
    assert not app.exception
    assert not app.button(key="simulate_run").disabled
    assert app.text_input(key="run_id_widget").value == f"centro-r{suffix}"


def test_automatic_identifier_follows_seed_and_source():
    source = named_variant()
    app = open_simulation()
    assert app.text_input(key="run_id_widget").value == "centro-r2026"
    app.text_input(key="seed_widget").set_value("7").run()
    assert app.text_input(key="run_id_widget").value == "centro-r7"
    app.selectbox(key="source_widget").select(str(source)).run()
    assert not app.exception
    assert app.text_input(key="run_id_widget").value == "night-r7"
    assert any("Identificador automático" in x.value for x in app.caption)


def test_manual_identifier_survives_seed_source_navigation_and_reset():
    source = named_variant()
    app = open_simulation()
    app.text_input(key="run_id_widget").set_value("custom").run()
    app.text_input(key="seed_widget").set_value("7").run()
    assert app.text_input(key="run_id_widget").value == "custom"
    app.selectbox(key="source_widget").select(str(source)).run()
    assert app.text_input(key="run_id_widget").value == "custom"
    assert any("Propuesta actual: night-r7" in x.value for x in app.caption)
    app.switch_page("views/runs.py").run()
    assert app.title[0].value == "Ejecuciones"
    app.switch_page("views/simulate.py").run()
    assert not app.exception
    assert app.text_input(key="run_id_widget").value == "custom"
    assert app.text_input(key="seed_widget").value == "7"
    assert any("Identificador manual" in x.value for x in app.caption)
    app.button(key="use_run_suggestion").click().run()
    assert app.text_input(key="run_id_widget").value == "night-r7"
    assert any("Identificador automático" in x.value for x in app.caption)
    app.text_input(key="seed_widget").set_value("8").run()
    assert app.text_input(key="run_id_widget").value == "night-r8"


def test_automatic_collision_and_manual_occupied_or_invalid_id(catalog_root):
    catalog_root.mkdir()
    (catalog_root / "centro-r2026").mkdir()
    (catalog_root / "centro-r2026-2").mkdir()
    app = open_simulation()
    assert app.text_input(key="run_id_widget").value == "centro-r2026-3"
    assert any("Se propone «centro-r2026-3»" in x.value for x in app.info)
    for invalid in ("../outside", "centro-r2026"):
        app.text_input(key="run_id_widget").set_value(invalid).run()
        assert not app.exception
        assert app.button(key="simulate_run").disabled
        assert app.error
        assert app.text_input(key="run_id_widget").value == invalid
    app.button(key="use_run_suggestion").click().run()
    assert app.text_input(key="run_id_widget").value == "centro-r2026-3"
    assert not app.button(key="simulate_run").disabled


def test_maximum_identifier_collision_has_no_suggestion_and_accepts_short_manual_id(catalog_root):
    source = named_variant("v" * 42)
    seed = "9" * 20
    preferred = source.stem + "-r" + seed
    assert len(preferred) == 64
    (catalog_root / preferred).mkdir(parents=True)
    app = open_simulation()
    app.selectbox(key="source_widget").select(str(source)).run()
    app.text_input(key="seed_widget").set_value(seed).run()
    assert not app.exception
    assert app.text_input(key="run_id_widget").value == preferred
    assert app.button(key="use_run_suggestion").disabled
    assert app.button(key="simulate_run").disabled
    assert any("no cabe un sufijo; escribe uno más corto" in x.value for x in app.warning)
    assert not any("Propuesta actual:" in x.value for x in app.caption)
    app.text_input(key="run_id_widget").set_value("short-free").run()
    assert not app.button(key="simulate_run").disabled
    assert app.selectbox(key="source_widget").value == str(source)


def test_reducing_days_adjusts_warmup_and_settings_survive_navigation():
    app = open_simulation()
    assert app.number_input(key="warmup_widget").value == 2
    app.number_input(key="days_widget").set_value(1).run()
    assert not app.exception
    assert app.number_input(key="warmup_widget").value == 0
    assert not app.button(key="simulate_run").disabled
    app.switch_page("views/runs.py").run()
    assert app.title[0].value == "Ejecuciones"
    app.switch_page("views/simulate.py").run()
    assert app.number_input(key="days_widget").value == 1
    assert app.number_input(key="warmup_widget").value == 0


def test_unsaved_destination_changes_block_simulation():
    app = open_simulation()
    edit(app, "destino.probabilidad_ingreso", 0, 0.5)
    assert any("destino.probabilidad_ingreso" in x.value for x in app.markdown)
    assert app.button(key="simulate_run").disabled
    assert any("Guarda una variante antes de simular" in x.value for x in app.info)


def test_real_one_day_simulation_uses_saved_variant_and_opens_results(
    catalog_root, monkeypatch, center_template
):
    from edsim.runs import RunStore

    edited_doctors = center_template["recursos"]["medicos"][0] + 1
    monkeypatch.setattr(defaults, "SIMULATION_DAYS", 1)
    monkeypatch.setattr(defaults, "SIMULATION_WARMUP_DAYS", 0)
    app = open_simulation()
    edit(app, "recursos.medicos", 0, edited_doctors)
    assert app.button(key="simulate_run").disabled
    app.text_input(key="variant_name_widget").set_value("extra-doctor").run()
    app.button(key="save_variant").click().run()
    source = defaults.VARIANTS_DIR / "extra-doctor.toml"
    assert source.exists()
    assert not app.button(key="simulate_run").disabled
    app.button(key="simulate_run").click().run(timeout=30)
    assert not app.exception
    assert not app.error
    info = RunStore(catalog_root).open("extra-doctor-r2026")
    assert (info.days, info.warmup_days, info.seed, info.origin) == (1, 0, 2026, "app")
    assert info.variant == "extra-doctor"
    assert info.center_path == str(source)
    assert info.profile_path == str(defaults.PROFILE_PATH)
    assert info.window_arrivals > 0
    assert info.invariant_violations == 0
    destination = catalog_root / info.run_id
    assert {p.name for p in destination.iterdir()} == {
        "run.json",
        "centro.toml",
        "llegadas.toml",
        "perfiles.toml",
        "eventos.jsonl",
        "ground_truth_episodios.csv",
        "ground_truth_dias.csv",
    }
    assert (destination / "centro.toml").read_bytes() == source.read_bytes()
    assert (destination / "llegadas.toml").read_bytes() == defaults.PROFILE_PATH.read_bytes()
    assert any(info.run_id in x.value for x in app.success)
    assert app.query_params["run"] == info.run_id
    metrics = {item.label: item.value for item in app.metric}
    assert metrics["Llegadas de la ventana"] == str(info.window_arrivals)
    assert metrics["Violaciones"] == "0"
    assert "Segundos de simulación" in metrics
    assert info.run_id in [x.value for x in app.sidebar.markdown]
    app.button(key="view_results").click().run()
    assert not app.exception
    assert app.title[0].value == "Resultados"
    assert app.query_params["run"] == info.run_id
    assert info.run_id in [x.value for x in app.sidebar.markdown]


def test_simulation_passes_relative_paths_output_and_no_variant(catalog_root, monkeypatch):
    import os
    from unittest.mock import Mock

    import edsim.runs as runs

    monkeypatch.setattr(defaults, "CENTER_PATH", Path(os.path.relpath(defaults.CENTER_PATH)))
    monkeypatch.setattr(defaults, "PROFILE_PATH", Path(os.path.relpath(defaults.PROFILE_PATH)))
    monkeypatch.setattr(defaults, "SIMULATION_DAYS", 1)
    monkeypatch.setattr(defaults, "SIMULATION_WARMUP_DAYS", 0)
    simulate = Mock(wraps=runs.simulate_run)
    monkeypatch.setattr(runs, "simulate_run", simulate)
    app = open_simulation()
    app.button(key="simulate_run").click().run(timeout=30)
    assert not app.exception
    assert simulate.call_args.args == (defaults.CENTER_PATH, defaults.PROFILE_PATH, 1, 2026)
    assert simulate.call_args.kwargs == {
        "output_dir": catalog_root / "centro-r2026",
        "warmup_days": 0,
        "run_id": "centro-r2026",
        "origin": "app",
        "profiles": str(defaults.CLINICAL_PROFILES_PATH),
    }
    assert (catalog_root / "centro-r2026" / "run.json").is_file()


@pytest.mark.parametrize("error_type", [FileExistsError, RunConfigurationError])
def test_simulation_reports_expected_errors_only(monkeypatch, catalog_root, error_type):
    def fail(*args, **kwargs):
        raise error_type("injected expected failure")

    monkeypatch.setattr("edsim.runs.simulate_run", fail)
    app = open_simulation()
    app.button(key="simulate_run").click().run()
    assert not app.exception
    assert app.error
    assert app.status[0].state == "error"
    assert not catalog_root.exists()


@pytest.mark.parametrize("error_type", [ValueError, RuntimeError, OSError])
def test_simulation_does_not_hide_internal_errors(monkeypatch, catalog_root, error_type):
    def fail(*args, **kwargs):
        raise error_type("injected internal failure")

    monkeypatch.setattr("edsim.runs.simulate_run", fail)
    app = open_simulation()
    app.button(key="simulate_run").click().run()
    assert len(app.exception) == 1
    assert app.exception[0].message == "injected internal failure"
    assert not app.error
    assert not catalog_root.exists()


@pytest.mark.parametrize("kind", ["missing", "toml", "validation"])
def test_unreadable_or_invalid_profile_blocks_simulation(kind):
    if kind == "missing":
        defaults.PROFILE_PATH.unlink()
    elif kind == "toml":
        defaults.PROFILE_PATH.write_text("[broken")
    else:
        defaults.PROFILE_PATH.write_text("unknown = 1\n")
    app = open_simulation()
    assert not app.exception
    assert any("No se puede cargar el perfil de llegadas" in e.value for e in app.error)
    assert app.button(key="simulate_run").disabled


@pytest.mark.parametrize("error_type", [ValueError, RuntimeError, OSError])
def test_offered_calculation_does_not_hide_internal_errors(monkeypatch, error_type):
    from edsim_app import preview

    def fail(*args, **kwargs):
        raise error_type("injected offered failure")

    monkeypatch.setattr(preview, "offered_load", fail)
    app = AppTest.from_file(MAIN, default_timeout=15).run(timeout=15)
    app.switch_page("views/simulate.py").run(timeout=15)
    assert len(app.exception) == 1
    assert app.exception[0].message == "injected offered failure"
    assert not app.error


@pytest.mark.parametrize(
    "key,index,replacement,error",
    [
        ("boxes", None, '"treinta"', "recursos.boxes must be an integer, got 'treinta'"),
        ("boxes", None, "30.5", "recursos.boxes must be an integer, got 30.5"),
        ("boxes", None, "true", "recursos.boxes must be an integer, got True"),
        ("boxes", None, "30.0", "recursos.boxes must be an integer, got 30.0"),
        ("inicio", 0, "8.5", "turnos.inicio[0] must be an integer"),
        ("medicos", 0, "true", "recursos.medicos[0] must be an integer"),
        ("probabilidad_ingreso", 0, "true", "destino.probabilidad_ingreso[0]"),
    ],
)
def test_unrepresentable_raw_values_stop_before_widgets(key, index, replacement, error):
    source = defaults.CENTER_PATH.read_bytes()
    changed = replace_raw_value(source, key, replacement, index)
    defaults.CENTER_PATH.write_bytes(changed)
    app = open_simulation()
    assert any(error in item.value for item in app.error)
    assert any("fichero fuera de la app" in item.value for item in app.info)
    assert not app.number_input
    assert not any(button.key in ("save_variant", "simulate_run") for button in app.button)
    assert defaults.CENTER_PATH.read_bytes() == changed


def test_change_list_names_fields_and_formats_staff_and_destination(center_template):
    doctors = center_template["recursos"]["medicos"]
    edited_doctors = doctors.copy()
    edited_doctors[1] += 3
    app = open_simulation()
    edit(app, "recursos.medicos", 1, edited_doctors[1])
    admission = center_template["destino"]["probabilidad_ingreso"]
    changed_admission = admission.copy()
    changed_admission[0] = 0.5
    edit(app, "destino.probabilidad_ingreso", 0, changed_admission[0])
    visible = [item.value for item in app.markdown]
    assert (
        f"**Médicos** · `recursos.medicos`: {expected_sequence(doctors)} → "
        f"{expected_sequence(edited_doctors)}"
    ) in visible
    assert (
        "**Probabilidad de ingreso** · `destino.probabilidad_ingreso`: "
        f"{expected_sequence(admission)} → {expected_sequence(changed_admission)}"
    ) in visible


@pytest.mark.parametrize("failure", ["missing", "toml"])
def test_failed_pending_source_load_cancels_confirmation_and_preserves_draft(
    failure, center_template
):
    boxes = center_template["recursos"]["boxes"]
    edited_boxes = boxes + 1
    destination = named_variant()
    app = open_simulation()
    edit(app, "recursos.boxes", None, edited_boxes)
    app.selectbox(key="source_widget").select(str(destination)).run()
    assert app.button(key="confirm_source")
    if failure == "missing":
        destination.unlink()
    else:
        destination.write_text("[broken", encoding="utf-8")
    app.button(key="confirm_source").click().run()
    assert not app.exception
    assert any("No se puede leer el origen" in item.value for item in app.error)
    assert not any(button.key == "confirm_source" for button in app.button)
    assert not any("Descartarlos" in item.value for item in app.warning)
    assert app.selectbox(key="source_widget").value == str(defaults.CENTER_PATH)
    assert app.number_input(key="edit_recursos.boxes_None").value == edited_boxes


def test_invalid_noneditable_field_is_visible_and_blocks_saving_and_simulation():
    source = named_variant("invalid-duration")
    source.write_bytes(replace_raw_value(source.read_bytes(), "triaje", "[10, 5]"))
    app = open_simulation()
    app.selectbox(key="source_widget").select(str(source)).run()
    app.text_input(key="variant_name_widget").set_value("valid-name").run()
    assert not app.exception
    assert any(
        "duraciones.triaje" in error.value and "p90 must be greater" in error.value
        for error in app.error
    )
    assert any("fichero fuera de la app" in notice.value for notice in app.info)
    assert app.button(key="save_variant").disabled
    assert app.button(key="simulate_run").disabled
    assert not (defaults.VARIANTS_DIR / "valid-name.toml").exists()
