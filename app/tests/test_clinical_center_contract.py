"""Exercise the complete app workflow with the center format planned for task 4.9."""

import json
from pathlib import Path

import pytest
import tomlkit
from streamlit.testing.v1 import AppTest

import edsim_app
from edsim.runs import RunStore, config_fingerprint
from edsim_app import defaults


@pytest.mark.slow
def test_center_without_provisional_sections_can_save_preview_and_simulate(
    tmp_path, monkeypatch, catalog_root
):
    document = tomlkit.parse(defaults.CENTER_PATH.read_text())
    for section in ("triaje", "duraciones", "pruebas"):
        document.pop(section, None)
    source = tmp_path / "clinical-center.toml"
    source.write_text(tomlkit.dumps(document))
    monkeypatch.setattr(defaults, "CENTER_PATH", source)
    app = AppTest.from_file(Path(edsim_app.__file__).with_name("main.py"), default_timeout=15)
    app.run().switch_page("views/simulate.py").run()
    assert not app.exception
    assert not app.error, [error.value for error in app.error]
    assert app.title[0].value == "Simular"
    for key in (
        "edit_turnos.inicio_0",
        "edit_recursos.boxes_None",
        "edit_destino.probabilidad_ingreso_0",
    ):
        assert app.number_input(key=key)
    boxes = app.number_input(key="edit_recursos.boxes_None").value
    app.number_input(key="edit_recursos.boxes_None").set_value(boxes + 1).run()
    app.text_input(key="variant_name_widget").set_value("without-provisional").run()
    app.button(key="save_variant").click().run()
    assert not app.exception and not app.error
    saved_path = defaults.VARIANTS_DIR / "without-provisional.toml"
    saved = tomlkit.parse(saved_path.read_text())
    assert not {"triaje", "duraciones", "pruebas"} & saved.keys()
    assert saved["recursos"]["boxes"] == boxes + 1
    load = next(table.value for table in app.dataframe if "Utilización" in table.value)
    assert len(load) == 9 and load["Utilización"].notna().all()
    assert app.get("vega_lite_chart")
    app.number_input(key="days_widget").set_value(1).run()
    app.button(key="simulate_run").click().run(timeout=30)
    assert not app.exception and not app.error
    info = RunStore(catalog_root).open("without-provisional-r2026")
    assert info.is_clinical and info.days == 1 and info.warmup_days == 0
    assert info.clinical_profiles_fingerprint == config_fingerprint(defaults.CLINICAL_PROFILES_PATH)
    metadata = json.loads((catalog_root / info.run_id / "run.json").read_text())
    assert metadata["model"] == "clinico"
    assert (catalog_root / info.run_id / "centro.toml").read_bytes() == saved_path.read_bytes()
