"""Emparejamiento con el modelo clínico (tareas 4.5b y 4.8a).

pairing_blockers impide comparar como «mismos pacientes» dos ejecuciones de modelos
distintos. Desde la tarea 4.8a, dos clínicas con perfiles de huella distinta sí se
emparejan: son los mismos sorteos estándar con otros valores, y compare_runs lo comprueba
con el ground truth.
"""

import csv
import json
import re
from pathlib import Path

import pytest
from runs_factory import copy_run
from scipy.stats import binom

from edsim.profiles.coupling import gumbel_change_share
from edsim.profiles.mixing import reason_weights
from edsim.runs import (
    CLINICAL_DRAW_EFFECTS,
    DRAW_EFFECTS,
    MetadataDifference,
    PairingCheckError,
    RunStore,
    compare_runs,
    read_center_values,
    read_run_episode_truth,
    read_run_results,
    simulate_run,
    write_variant,
)
from edsim.runs.compare import pairing_blockers, pairing_category

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
    other_profiles.write_text(PROFILES.read_text().replace("ruido = 0.334", "ruido = 0.4"))
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
    # Tarea 4.8a: ya no bloquea (en la 4.5b bloqueaba la huella de los perfiles).
    _, results = runs
    a, b = results["clinica"], results["clinica-otros-perfiles"]

    assert a.info.clinical_profiles_fingerprint != b.info.clinical_profiles_fingerprint
    assert pairing_blockers(a, b) == ()
    assert pairing_category(a, b) == "clinical"
    assert pairing_category(a, results["clinica-noche"]) == "template"
    assert pairing_category(a, results["provisional"]) == "unpaired"


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


# --- Emparejamiento comprobado con el ground truth (tarea 4.8a) -----------------------
#
# Tres días con config/ y la semilla 2026: el centro calibrado ([12, 11, 4]), el mismo con
# un médico más de noche ([12, 11, 5]) y la gripe (el peso base de la disnea × 1,5 en una
# copia temporal de los perfiles). Los tres días caen del 5 al 7 de enero, antes de la
# semana del 19 al 25.

CONFIG = Path("config")
FLU = 1.5
FLU_LEVEL = 0.999
"""Nivel del intervalo binomial de la gripe, fijado antes de medir."""


@pytest.fixture(scope="module")
def checked(tmp_path_factory):
    root = tmp_path_factory.mktemp("emparejamiento-comprobado")
    values = read_center_values(CONFIG / "centro.toml")
    assert values["recursos.medicos"] == [12, 11, 4]
    values["recursos.medicos"] = [12, 11, 5]
    night = root / "centro_noche.toml"
    write_variant(CONFIG / "centro.toml", values, night)
    text = (CONFIG / "perfiles.toml").read_text()
    weight = re.search(r"\[motivos\.disnea\]\n[^\n]*\npeso_base = ([0-9.]+)", text).group(1)
    flu = root / "perfiles_gripe.toml"
    flu.write_text(text.replace(f"peso_base = {weight}", f"peso_base = {float(weight) * FLU!r}", 1))
    for run_id, center, profiles in (
        ("base", CONFIG / "centro.toml", CONFIG / "perfiles.toml"),
        ("noche", night, CONFIG / "perfiles.toml"),
        ("gripe", CONFIG / "centro.toml", flu),
    ):
        simulate_run(
            center,
            ARRIVALS,
            3,
            2026,
            output_dir=root / run_id,
            run_id=run_id,
            warmup_days=1,
            origin="cli",
            profiles=profiles,
        )
    store = RunStore(root)
    results = {run_id: read_run_results(store, run_id) for run_id in ("base", "noche", "gripe")}
    truth = {run_id: read_run_episode_truth(store, run_id) for run_id in results}
    return store, results, truth


def test_una_clinica_contra_si_misma_todo_cero(checked):
    _, results, truth = checked
    a = results["base"]

    comparison = compare_runs(a, a, truth["base"], truth["base"])

    assert comparison.pairing.kind == "same_draws"
    assert all(d.changed == 0 for d in comparison.pairing.draw_differences)
    assert [d.field for d in comparison.pairing.clinical_differences] == [
        "reason",
        "level",
        "true_level",
        "age",
        "sex",
        "arrival_mode",
        "tests",
    ]
    assert all(d.changed == 0 for d in comparison.pairing.clinical_differences)
    assert all(e.stay_difference == 0 for e in comparison.episodes)


def test_plantilla_los_mismos_pacientes_y_sorteos_clinicos(checked):
    _, results, truth = checked
    a, b = results["base"], results["noche"]

    comparison = compare_runs(a, b, truth["base"], truth["noche"])

    assert pairing_category(a, b) == "template"
    assert comparison.pairing.kind == "same_draws"
    assert all(d.changed == 0 for d in comparison.pairing.clinical_differences)
    assert all(t.clinical == truth["noche"][k].clinical for k, t in truth["base"].items())
    # Guarda: la plantilla cambia los resultados de verdad.
    assert any(e.stay_change != "unchanged" for e in comparison.episodes)


def test_la_gripe_solo_lleva_pacientes_a_disnea(checked):
    _, results, truth = checked
    a, b = results["base"], results["gripe"]
    before, after = a.profiles, b.profiles

    comparison = compare_runs(a, b, truth["base"], truth["gripe"])
    changed = [
        (t.clinical.reason, truth["gripe"][k].clinical.reason)
        for k, t in truth["base"].items()
        if t.clinical.reason != truth["gripe"][k].clinical.reason
    ]
    # Lo esperado con los contextos y las bandas de estos pacientes (enero), no el 3,37 %
    # del año: la probabilidad exacta de cambiar de cada uno con Gumbel-max.
    shares = [
        gumbel_change_share(
            reason_weights(before, t.clinical.context, t.clinical.person.band),
            reason_weights(after, t.clinical.context, t.clinical.person.band),
        )
        for t in truth["base"].values()
    ]
    n, p = len(shares), sum(shares) / len(shares)
    low, high = binom.interval(FLU_LEVEL, n, p)

    assert comparison.pairing.kind == "clinical_profiles"
    reasons = {d.field: d.changed for d in comparison.pairing.clinical_differences}
    assert reasons["reason"] == len(changed)
    assert changed and all(new == "disnea" for _, new in changed)
    assert low <= len(changed) <= high
    # Los sorteos estándar no cambian; la edad, el sexo y el medio, tampoco.
    assert reasons["age"] == reasons["sex"] == reasons["arrival_mode"] == 0


def test_una_z_alterada_rompe_el_emparejamiento_clinico(checked, tmp_path):
    store, results, truth = checked
    copy_store, path = copy_run(store, "gripe", tmp_path)
    csv_path = path / "ground_truth_episodios.csv"
    with csv_path.open(newline="") as source:
        reader = csv.DictReader(source)
        fields, rows = reader.fieldnames, list(reader)
    rows[3]["z_gravedad"] = repr(float(rows[3]["z_gravedad"]) + 0.5)
    with csv_path.open("w", newline="") as destination:
        writer = csv.DictWriter(destination, fields)
        writer.writeheader()
        writer.writerows(rows)
    altered = read_run_episode_truth(copy_store, "gripe")

    with pytest.raises(PairingCheckError) as caught:
        compare_runs(results["base"], results["gripe"], truth["base"], altered)

    assert (caught.value.field, caught.value.affected) == ("severity_z", 1)


def test_los_modelos_distintos_siguen_bloqueados(runs):
    _, results = runs
    a, b = results["provisional"], results["clinica-otros-perfiles"]

    assert [d.field for d in pairing_blockers(a, b)] == ["model", "clinical_profiles_fingerprint"]
    with pytest.raises(ValueError, match="pairable"):
        compare_runs(a, b, {}, {})


def test_el_centro_clinico_solo_cambia_el_destino():
    assert CLINICAL_DRAW_EFFECTS.keys() == DRAW_EFFECTS.keys()
    assert {k: v for k, v in CLINICAL_DRAW_EFFECTS.items() if v} == {
        "destino.probabilidad_ingreso": frozenset({"admitted"})
    }
