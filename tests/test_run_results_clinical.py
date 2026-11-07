"""Resultados de una ejecución clínica: modelo, perfiles y recuento de violaciones (tarea 4.8a).

``read_run_results`` lee los perfiles de la copia de la carpeta y, cuando ``run.json``
guarda violaciones, las recalcula como la simulación: con el ground truth (episodios y
días) y con los perfiles. El recuento se compara con la verdad que la simulación tenía en
memoria, no con la leída de disco, para que un error del lector no se cancele.
"""

import dataclasses
import json

import pytest
from runs_factory import copy_run

from edsim.engine.events import read_events, to_json
from edsim.engine.invariants import check_invariants
from edsim.profiles.config import load_profiles
from edsim.runs import RunReadError, RunStore, load_center, read_run_results
from edsim.runs.results import _saved_ground_truth


def test_la_clinica_trae_su_modelo_y_los_perfiles_de_su_copia(clinical_store):
    result = read_run_results(clinical_store, "clinica")
    copy = clinical_store.root / "clinica" / "perfiles.toml"

    assert result.model == "clinico"
    assert result.profiles == load_profiles(copy)


def test_la_provisional_no_tiene_perfiles(clinical_store):
    result = read_run_results(clinical_store, "provisional")

    assert result.model == "provisional"
    assert result.profiles is None


def test_se_abre_un_run_json_de_la_version_1(clinical_store, tmp_path):
    # Las claves de tests/data/run_v1.json sobre una provisional recién simulada, así que
    # posterior a la tarea 4.1 (el nivel 1 ya va a la puerta).
    reference = json.loads(open("tests/data/run_v1.json").read())
    store, path = copy_run(clinical_store, "provisional", tmp_path, "antigua")
    data = json.loads((path / "run.json").read_text())
    del data["model"]
    data |= {"format_version": 1, "run_id": "antigua"}
    assert data.keys() == reference.keys()
    (path / "run.json").write_text(json.dumps(data))

    result = read_run_results(store, "antigua")

    assert result.info.format_version == 1
    assert result.model == "provisional" and result.profiles is None
    assert result.analysis.table == read_run_results(clinical_store, "provisional").analysis.table


def test_la_verdad_leida_de_disco_es_la_de_la_simulacion(clinical_store, clinical_simulation):
    _, simulated = clinical_simulation
    result = read_run_results(clinical_store, "clinica")

    saved = _saved_ground_truth(clinical_store, "clinica", result.info, result.start_date)

    assert len(saved.episodes) == len(simulated.episodes)
    for read, drawn in zip(saved.episodes, simulated.episodes, strict=True):
        for field in dataclasses.fields(drawn):
            assert getattr(read, field.name) == getattr(drawn, field.name), field.name
    assert saved.days == simulated.days


def _delay_one_result(path):
    """Retrasa 1 minuto el primer ``test_resulted`` del log guardado y devuelve los eventos."""
    events = list(read_events(path / "eventos.jsonl"))
    index = next(i for i, e in enumerate(events) if e.event_type == "test_resulted")
    events[index] = dataclasses.replace(events[index], sim_time=events[index].sim_time + 1)
    (path / "eventos.jsonl").write_text("".join(to_json(e) + "\n" for e in events))
    return events


def test_el_recuento_clinico_usa_la_verdad_y_los_perfiles(
    clinical_store, clinical_simulation, tmp_path
):
    _, simulated = clinical_simulation
    store, path = copy_run(clinical_store, "clinica", tmp_path)
    events = _delay_one_result(path)
    info = store.open("clinica")
    dataclasses.replace(info, invariant_violations=1).write(path / "run.json")
    center = load_center(path / "centro.toml")
    profiles = load_profiles(path / "perfiles.toml")

    expected = check_invariants(events, center, ground_truth=simulated, profiles=profiles)
    without_profiles = check_invariants(events, center, ground_truth=simulated)
    result = read_run_results(store, "clinica")

    assert result.violations == tuple(expected)
    # Guarda contra un test vacío: la ronda retrasada solo la ve la comprobación con perfiles.
    only_with_profiles = set(expected) - set(without_profiles)
    assert only_with_profiles and all(v.check == "clinical" for v in only_with_profiles)


def test_el_recuento_provisional_no_cambia(clinical_store, tmp_path):
    store, path = copy_run(clinical_store, "provisional", tmp_path)
    events = _delay_one_result(path)
    info = store.open("provisional")
    dataclasses.replace(info, invariant_violations=1).write(path / "run.json")

    result = read_run_results(store, "provisional")

    assert result.violations == tuple(check_invariants(events, load_center(path / "centro.toml")))


def _rewrite(path, column, row, value):
    """Cambia una celda de la fila ``row`` (0 es la primera de datos) de un CSV guardado."""
    lines = path.read_text().splitlines()
    header = lines[0].split(",")
    cells = lines[row + 1].split(",")
    cells[header.index(column)] = value
    lines[row + 1] = ",".join(cells)
    path.write_text("\n".join(lines) + "\n")


@pytest.mark.parametrize(
    ("column", "row", "value", "line", "message"),
    [
        ("semilla", 0, "7", 2, "semilla does not match run.json"),
        ("fecha", 1, "2026-01-07", 3, "fecha of dia 1"),
        ("dia", 2, "1", 4, "dia must be 2"),
        ("esperadas", 0, "nan", 2, "esperadas must be finite"),
    ],
)
def test_errores_del_csv_de_dias_con_fichero_y_linea(
    clinical_store, tmp_path, column, row, value, line, message
):
    store, path = copy_run(clinical_store, "clinica", tmp_path)
    info = store.open("clinica")
    _rewrite(path / "ground_truth_dias.csv", column, row, value)
    result = read_run_results(clinical_store, "clinica")

    with pytest.raises(RunReadError, match=f"ground_truth_dias.csv:{line}: .*{message}"):
        _saved_ground_truth(store, "clinica", info, result.start_date)


def test_un_csv_de_dias_sin_un_dia_es_un_error(clinical_store, tmp_path):
    store, path = copy_run(clinical_store, "clinica", tmp_path)
    days = path / "ground_truth_dias.csv"
    days.write_text("\n".join(days.read_text().splitlines()[:-1]) + "\n")
    result = read_run_results(clinical_store, "clinica")

    with pytest.raises(RunReadError, match="2 days, run.json has 3"):
        _saved_ground_truth(store, "clinica", store.open("clinica"), result.start_date)


def test_los_perfiles_invalidos_de_la_copia_son_un_error_de_lectura(clinical_store, tmp_path):
    store, path = copy_run(clinical_store, "clinica", tmp_path)
    (path / "perfiles.toml").write_text("no = [valido")

    with pytest.raises(RunReadError, match="perfiles.toml"):
        read_run_results(RunStore(tmp_path), "clinica")


# --- Cumplimiento con el reloj C por defecto (tarea 4.9) -------------------------------


def test_el_cumplimiento_de_la_ejecucion_usa_el_reloj_c(clinical_store):
    from edsim.runs import APP_COMPLIANCE_MEASURE, window_compliance

    result = read_run_results(clinical_store, "clinica")
    first, end = result.info.warmup_days, result.info.days
    table = result.analysis.table
    c = window_compliance(table, first, end, measure="classified_to_doctor")
    a = window_compliance(table, first, end, measure="door_to_doctor")

    assert APP_COMPLIANCE_MEASURE == "classified_to_doctor"
    assert result.compliance.daily.measure == "classified_to_doctor"
    assert result.compliance.by_level == c.by_level
    # Guarda: en esta ejecución los dos relojes dan otro cumplimiento, así que el test no
    # pasa en vacío.
    assert any(x.exceeded != y.exceeded for x, y in zip(c.by_level, a.by_level, strict=True))
