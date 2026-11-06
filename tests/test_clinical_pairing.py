"""Emparejamiento mínimo con el modelo clínico (tarea 4.5b).

pairing_blockers impide comparar como «mismos pacientes» dos ejecuciones de modelos
distintos o con perfiles de huella distinta. El emparejamiento clínico completo, con el
ground truth, es de la tarea 4.8a.
"""

import json
from pathlib import Path

import pytest

from edsim.runs import (
    MetadataDifference,
    RunStore,
    read_center_values,
    read_run_results,
    simulate_run,
    write_variant,
)
from edsim.runs.compare import pairing_blockers

CENTER = Path("tests/data/centro_ejemplo.toml")
ARRIVALS = "tests/data/llegadas_ejemplo.toml"
PROFILES = Path("tests/data/perfiles_ejemplo.toml")


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    """Ejecuciones de 2 días con la semilla 7: provisional y clínicas."""
    root = tmp_path_factory.mktemp("emparejamiento")
    values = read_center_values(CENTER)
    values["recursos.medicos"][2] += 1
    night = root / "noche.toml"
    write_variant(CENTER, values, night)
    other_profiles = root / "perfiles_otros.toml"
    other_profiles.write_text(PROFILES.read_text().replace("ruido = 0.333", "ruido = 0.4"))
    for run_id, center, profiles in (
        ("provisional", CENTER, None),
        ("clinica", CENTER, PROFILES),
        ("clinica-noche", night, PROFILES),
        ("clinica-otros-perfiles", CENTER, other_profiles),
    ):
        simulate_run(
            center,
            ARRIVALS,
            2,
            7,
            output_dir=root / run_id,
            run_id=run_id,
            warmup_days=1,
            origin="cli",
            profiles=profiles,
        )
    store = RunStore(root)
    return store, {info.run_id: read_run_results(store, info.run_id) for info in store.list()}


def test_provisional_frente_a_clinico_con_la_misma_semilla(runs):
    _, results = runs
    a, b = results["provisional"], results["clinica"]

    assert a.info.seed == b.info.seed
    assert a.info.profile_fingerprint == b.info.profile_fingerprint
    assert pairing_blockers(a, b) == (
        MetadataDifference("model", "provisional", "clinico"),
        MetadataDifference(
            "clinical_profiles_fingerprint", None, b.info.clinical_profiles_fingerprint
        ),
    )


def test_dos_clinicas_con_los_mismos_perfiles_y_otra_plantilla(runs):
    _, results = runs
    a, b = results["clinica"], results["clinica-noche"]

    # Guarda: la plantilla cambia de verdad.
    assert a.info.center_fingerprint != b.info.center_fingerprint
    assert pairing_blockers(a, b) == ()


def test_dos_clinicas_con_perfiles_de_huella_distinta(runs):
    _, results = runs
    a, b = results["clinica"], results["clinica-otros-perfiles"]

    assert pairing_blockers(a, b) == (
        MetadataDifference(
            "clinical_profiles_fingerprint",
            a.info.clinical_profiles_fingerprint,
            b.info.clinical_profiles_fingerprint,
        ),
    )


def test_una_version_1_y_una_2_provisionales_se_emparejan(runs, tmp_path):
    # El formato no cambia los pacientes: una ejecución de la versión 1 (escrita aquí a
    # mano, quitando model) se empareja con la misma en la versión 2.
    store, results = runs
    source = store.root / "provisional"
    copy = tmp_path / "v1"
    copy.mkdir()
    for name in store.run_files("provisional"):
        (copy / name).write_bytes((source / name).read_bytes())
    data = json.loads((copy / "run.json").read_text())
    del data["model"]
    (copy / "run.json").write_text(json.dumps(data | {"format_version": 1, "run_id": "v1"}))
    old = read_run_results(RunStore(tmp_path), "v1")

    assert old.info.format_version == 1
    assert pairing_blockers(old, results["provisional"]) == ()
