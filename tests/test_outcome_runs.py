"""Las ejecuciones guardadas del modelo del hito 5 (tarea 5.3).

``run.json`` de la versión 3 registra el modelo del hito 5 con la versión del catálogo de
su log; las versiones 1 y 2 se leen como siempre. ``RunInfo.catalog_version`` da esa
versión para cualquier ``run.json``. Un bloque del hito 5 en uno solo de los dos ficheros
es un error antes de crear nada, y un run del hito 4 y uno del hito 5 no se emparejan.
"""

import csv
import dataclasses
import json
from pathlib import Path

import pytest
from runs_factory import copy_run

from edsim.runs import (
    PairingCheckError,
    RunStore,
    compare_runs,
    read_center_values,
    read_run_episode_truth,
    read_run_results,
    simulate_run,
    write_variant,
)
from edsim.runs.compare import pairing_blockers
from edsim.runs.service import RunConfigurationError
from edsim.runs.store import RunInfo

DATA = Path("tests/data")
CENTER_4 = DATA / "centro_sala_ejemplo.toml"
CENTER_5 = DATA / "centro_h5_ejemplo.toml"
PROFILES_4 = DATA / "perfiles_ejemplo.toml"
PROFILES_5 = DATA / "perfiles_h5_ejemplo.toml"
ARRIVALS = DATA / "llegadas_ejemplo.toml"


def simulate(root: Path, run_id: str, center, profiles=None):
    return simulate_run(
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


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    """Ejecuciones de 2 días con la semilla 7: provisional, hito 4 y cuatro del hito 5."""
    root = tmp_path_factory.mktemp("hito5")
    values = read_center_values(CENTER_5)
    values["recursos.boxes"] += 5
    staff = root / "plantilla.toml"
    write_variant(CENTER_5, values, staff)
    values = read_center_values(CENTER_5)
    values["camas.espera"] = [300, 900]
    beds = root / "camas.toml"
    write_variant(CENTER_5, values, beds)
    other_profiles = root / "perfiles_otros.toml"
    text = PROFILES_5.read_text(encoding="utf-8")
    assert text.count("paciencia_edad = [0.8, 1.0, 1.0, 1.0]") == 1
    other_profiles.write_text(
        text.replace(
            "paciencia_edad = [0.8, 1.0, 1.0, 1.0]", "paciencia_edad = [0.7, 1.0, 1.0, 1.0]"
        )
    )
    for run_id, center, profiles in (
        ("provisional", DATA / "centro_ejemplo.toml", None),
        ("hito4", CENTER_4, PROFILES_4),
        ("hito5", CENTER_5, PROFILES_5),
        ("hito5-plantilla", staff, PROFILES_5),
        ("hito5-camas", beds, PROFILES_5),
        ("hito5-otros-perfiles", CENTER_5, other_profiles),
    ):
        simulate(root, run_id, center, profiles)
    store = RunStore(root)
    return store, {info.run_id: read_run_results(store, info.run_id) for info in store.list()}


# --- run.json -------------------------------------------------------------------------------


def test_el_run_json_del_hito_5_es_la_version_3(runs):
    store, results = runs
    data = json.loads((store.root / "hito5" / "run.json").read_text(encoding="utf-8"))
    v2 = json.loads((store.root / "hito4" / "run.json").read_text(encoding="utf-8"))

    assert (data["format_version"], data["model"], data["schema_version"]) == (3, "clinico", 4)
    assert list(data) == [*v2, "schema_version"]  # la 2 clínica más la clave, al final
    assert v2["format_version"] == 2 and "schema_version" not in v2
    assert results["hito5"].info == RunInfo.read(store.root / "hito5" / "run.json")


def test_la_version_del_catalogo_de_cualquier_run_json(runs):
    # 1 con la versión 1 y con la 2 provisional, 3 con la 2 clínica y 4 con la 3.
    _, results = runs
    v1 = RunInfo.read(DATA / "run_v1.json")

    assert (v1.format_version, v1.catalog_version) == (1, 1)
    assert results["provisional"].info.catalog_version == 1
    assert results["hito4"].info.catalog_version == 3
    assert results["hito5"].info.catalog_version == 4


def test_el_run_json_de_la_version_3_vuelve_igual(runs, tmp_path):
    _, results = runs
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    results["hito5"].info.write(first)
    RunInfo.read(first).write(second)

    assert first.read_bytes() == second.read_bytes()


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"model": "provisional"}, "format_version 3 is of the milestone 5 model"),
        ({"schema_version": 3}, "needs schema_version 4"),
        ({"schema_version": True}, "needs schema_version 4"),
        ({"schema_version": 4.0}, "needs schema_version 4"),
        ({"schema_version": "4"}, "needs schema_version 4"),
        ({"schema_version": 10**400}, "needs schema_version 4"),
        ({"schema_version": None}, "needs schema_version 4"),
        ({"format_version": 2}, "schema_version exists only in format_version 3"),
    ],
)
def test_una_sola_forma_de_escribir_la_version_3(runs, changes, message):
    _, results = runs
    info = results["hito5"].info
    if changes.get("model") == "provisional":
        changes |= {"clinical_profiles_path": None, "clinical_profiles_fingerprint": None}

    with pytest.raises(ValueError, match=message):
        dataclasses.replace(info, **changes)


@pytest.mark.parametrize(
    ("version", "drop", "add"),
    [(3, "schema_version", None), (2, None, ("schema_version", 4))],
)
def test_las_claves_de_cada_version_son_exactas(runs, tmp_path, version, drop, add):
    # La 3 sin schema_version, o la 2 con ella: los valores por defecto no rellenan nada.
    store, _ = runs
    data = json.loads((store.root / "hito5" / "run.json").read_text(encoding="utf-8"))
    data["format_version"] = version
    if drop:
        del data[drop]
    if add:
        data[add[0]] = add[1]
    path = tmp_path / "run.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid run.json fields"):
        RunInfo.read(path)


# --- El bloque a medias, antes de crear nada ------------------------------------------------


@pytest.mark.parametrize(
    ("center", "profiles", "file", "key"),
    [
        (CENTER_4, PROFILES_5, CENTER_4, "[camas]"),
        (CENTER_5, PROFILES_4, PROFILES_4, "[abandono]"),
    ],
)
def test_un_bloque_a_medias_no_crea_nada(tmp_path, center, profiles, file, key):
    with pytest.raises(RunConfigurationError) as error:
        simulate(tmp_path, "medias", center, profiles)

    assert str(error.value).startswith(f"{file}:") and key in str(error.value)
    assert list(tmp_path.iterdir()) == []  # ni la carpeta ni la temporal


# --- La verdad guardada ---------------------------------------------------------------------


def test_la_verdad_del_hito_5_se_lee_con_su_desenlace(runs):
    store, _ = runs
    truth = read_run_episode_truth(store, "hito5")
    old = read_run_episode_truth(store, "hito4")

    assert truth and all(t.outcome is not None for t in truth.values())
    assert old and all(t.outcome is None for t in old.values())


@pytest.mark.parametrize(("run_id", "other"), [("hito4", "hito5"), ("hito5", "hito4")])
def test_la_cabecera_de_la_verdad_es_la_de_su_catalogo(runs, tmp_path, run_id, other):
    # 57 columnas con la versión 3 del catálogo y 65 con la 4: la de otro modelo no se lee.
    store, _ = runs
    copy_store, path = copy_run(store, run_id, tmp_path)
    (path / "ground_truth_episodios.csv").write_bytes(
        store.read_file(other, "ground_truth_episodios.csv")
    )

    with pytest.raises(ValueError, match="invalid header of ground_truth_episodios.csv"):
        read_run_episode_truth(copy_store, run_id)


# --- Emparejamiento -------------------------------------------------------------------------


def test_un_run_del_hito_4_y_uno_del_hito_5_no_se_emparejan(runs):
    _, results = runs
    a, b = results["hito4"], results["hito5"]
    blockers = pairing_blockers(a, b)

    # Las dos son clínicas con la misma semilla: solo las separa el catálogo (y los perfiles,
    # que entre dos clínicas no bloquean).
    assert [(d.field, d.a, d.b) for d in blockers] == [("catalog_version", 3, 4)]
    with pytest.raises(ValueError, match="pairable"):
        compare_runs(a, b, {}, {})


def test_con_modelos_distintos_solo_bloquea_el_modelo(runs):
    # La versión del catálogo no se añade cuando ya bloquea el modelo: la vista de la app
    # etiqueta cada bloqueo, y la del catálogo no tiene etiqueta hasta la 5.5.
    _, results = runs
    blockers = pairing_blockers(results["provisional"], results["hito5"])

    assert "catalog_version" not in [d.field for d in blockers]
    assert [d.field for d in blockers][0] == "model"


@pytest.mark.parametrize("other", ["hito5-plantilla", "hito5-camas"])
def test_dos_del_hito_5_con_otro_centro_se_emparejan(runs, other):
    store, results = runs
    truth = {run_id: read_run_episode_truth(store, run_id) for run_id in ("hito5", other)}
    comparison = compare_runs(results["hito5"], results[other], truth["hito5"], truth[other])

    assert comparison.pairing.kind == "same_draws"
    bed = [
        t.outcome.bed_base != truth[other][key].outcome.bed_base
        for key, t in truth["hito5"].items()
    ]
    # Con camas.espera [300, 900] cambia toda espera base; con otra plantilla, ninguna.
    assert all(bed) if other == "hito5-camas" else not any(bed)


def altered_copy(store, run_id, root, column, change):
    """La verdad de una copia del run con ``column`` de la cuarta fila cambiada."""
    copy_store, path = copy_run(store, run_id, root)
    csv_path = path / "ground_truth_episodios.csv"
    with csv_path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        fields, rows = reader.fieldnames, list(reader)
    rows[3][column] = change(rows[3][column])
    with csv_path.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(destination, fields)
        writer.writeheader()
        writer.writerows(rows)
    return read_run_episode_truth(copy_store, run_id)


@pytest.mark.parametrize(
    ("column", "field"),
    [("paciencia", "outcome"), ("espera_cama_base", "bed_base")],
)
def test_con_los_mismos_perfiles_el_desenlace_no_cambia(runs, tmp_path, column, field):
    # Con la misma plantilla de camas, ni la paciencia ni la espera base pueden cambiar.
    store, results = runs
    altered = altered_copy(
        store, "hito5-plantilla", tmp_path, column, lambda v: repr(float(v) + 1.0)
    )

    with pytest.raises(PairingCheckError) as caught:
        compare_runs(
            results["hito5"],
            results["hito5-plantilla"],
            read_run_episode_truth(store, "hito5"),
            altered,
        )
    assert (caught.value.field, caught.value.affected) == (field, 1)


def test_con_otros_perfiles_los_sorteos_del_desenlace_son_los_mismos(runs, tmp_path):
    store, results = runs
    a, b = results["hito5"], results["hito5-otros-perfiles"]
    truth_a = read_run_episode_truth(store, "hito5")
    truth_b = read_run_episode_truth(store, "hito5-otros-perfiles")

    assert compare_runs(a, b, truth_a, truth_b).pairing.kind == "clinical_profiles"
    altered = altered_copy(
        store, "hito5-otros-perfiles", tmp_path, "z_paciencia", lambda v: repr(float(v) + 0.5)
    )
    with pytest.raises(PairingCheckError) as caught:
        compare_runs(a, b, truth_a, altered)
    assert (caught.value.field, caught.value.affected) == ("outcome_draws", 1)
