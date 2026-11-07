"""La verdad de una ejecución clínica desde runs/ (tarea 4.8a).

``read_run_episode_truth`` lee el CSV clínico con ``episode_from_row`` y comprueba los
parámetros y los perfiles contra ``run.json``; ``compare_episode_truth`` compara la
respuesta de la ronda con la franja del pedido; ``episode_clinical_truth`` es «ver la
verdad»; ``true_level_window_compliance`` cuenta el cumplimiento por nivel real.
"""

import csv
import dataclasses
from collections import defaultdict

import numpy as np
import pytest
from clinical_factory import START, clinical_log, example_profiles, hand_truth, ordered_of
from runs_factory import copy_run

from edsim.engine.events import read_events
from edsim.engine.ground_truth import EpisodeTruth, GroundTruth
from edsim.engine.targets import true_level_compliance
from edsim.runs import (
    RunReadError,
    compare_episode_truth,
    episode_clinical_truth,
    episode_segments,
    read_run_episode_truth,
    read_run_results,
    true_level_window_compliance,
)


def test_ida_y_vuelta_de_la_verdad_clinica(clinical_store, clinical_simulation):
    _, simulated = clinical_simulation
    truth = read_run_episode_truth(clinical_store, "clinica")

    assert list(truth) == [e.episode_id for e in simulated.episodes]
    for drawn in simulated.episodes:
        read = truth[drawn.episode_id]
        assert read.clinical is not None
        for field in dataclasses.fields(drawn):
            assert getattr(read, field.name) == getattr(drawn, field.name), field.name


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("huella_perfiles", "000000000000"),
        ("perfiles", "otros/perfiles.toml"),
        ("semilla", "7"),
    ],
)
def test_otra_huella_ruta_o_parametro_con_fichero_y_linea(clinical_store, tmp_path, column, value):
    store, path = copy_run(clinical_store, "clinica", tmp_path)
    csv_path = path / "ground_truth_episodios.csv"
    with csv_path.open(newline="") as source:
        reader = csv.DictReader(source)
        fields, rows = reader.fieldnames, list(reader)
    rows[0][column] = value
    with csv_path.open("w", newline="") as destination:
        writer = csv.DictWriter(destination, fields)
        writer.writeheader()
        writer.writerows(rows)

    with pytest.raises(RunReadError) as caught:
        read_run_episode_truth(store, "clinica")

    assert str(caught.value).startswith(f"{csv_path}:2:")
    assert f"{column} does not match run.json" in str(caught.value)


def test_una_clinica_con_el_csv_provisional_es_un_error(clinical_store, tmp_path):
    store, path = copy_run(clinical_store, "clinica", tmp_path)
    provisional = clinical_store.read_file("provisional", "ground_truth_episodios.csv")
    (path / "ground_truth_episodios.csv").write_bytes(provisional)

    with pytest.raises(RunReadError, match="invalid header"):
        read_run_episode_truth(store, "clinica")


def _episodes(store, run_id):
    """Los eventos del log guardado, por episodio, en orden."""
    by_episode = defaultdict(list)
    for event in read_events(store.root / run_id / "eventos.jsonl"):
        if event.episode_id is not None:
            by_episode[event.episode_id].append(event)
    return by_episode


@pytest.mark.parametrize("run_id", ["clinica", "clinica-sala"])
def test_una_clinica_limpia_no_tiene_discrepancias(clinical_store, run_id):
    result = read_run_results(clinical_store, run_id)
    truth = read_run_episode_truth(clinical_store, run_id)
    horizon = result.analysis.curves.horizon
    statuses = defaultdict(int)
    for episode_id, events in _episodes(clinical_store, run_id).items():
        rows = compare_episode_truth(
            events,
            episode_segments(events, horizon),
            truth[episode_id],
            profiles=result.profiles,
            start_date=result.start_date,
        )
        for row in rows:
            assert row.status != "mismatch", (episode_id, row)
            statuses[row.field, row.status] += 1

    # Guarda: la comparación de las rondas se hace de verdad en muchos pacientes.
    assert statuses["test_turnaround", "match"] > 50
    assert statuses["assessment_time", "match"] > 100


def test_una_duracion_alterada_es_una_discrepancia(clinical_store):
    result = read_run_results(clinical_store, "clinica")
    truth = read_run_episode_truth(clinical_store, "clinica")
    events = _episodes(clinical_store, "clinica")["EP-000010"]
    segments = episode_segments(events, result.analysis.curves.horizon)
    changed = dataclasses.replace(
        truth["EP-000010"], assessment_time=truth["EP-000010"].assessment_time + 1
    )
    kwargs = {"profiles": result.profiles, "start_date": result.start_date}

    rows = {r.field: r for r in compare_episode_truth(events, segments, changed, **kwargs)}

    assert rows["assessment_time"].status == "mismatch"


def test_una_verdad_clinica_necesita_los_perfiles(clinical_store):
    result = read_run_results(clinical_store, "clinica")
    truth = read_run_episode_truth(clinical_store, "clinica")
    events = _episodes(clinical_store, "clinica")["EP-000010"]
    segments = episode_segments(events, result.analysis.curves.horizon)

    with pytest.raises(ValueError, match="profiles and the start_date"):
        compare_episode_truth(events, segments, truth["EP-000010"])


def _truth(truth, arrival=5.0):
    return EpisodeTruth(
        "EP-000000",
        0,
        arrival,
        truth.triage.level,
        5.0,
        20.0,
        10.0,
        truth.workup.has_round,
        None,
        False,
        clinical=truth,
    )


def test_ver_la_verdad_de_un_infratriado_a_mano():
    # Real 2 asignado como 4. Pide analítica y ECG a las 00:30 (noche): analítica
    # 75 × 0,9 = 67,5 y ECG 12 × 1 = 12; la ronda dura 67,5, y el log la da igual.
    clinical = hand_truth(
        level=4,
        true_level=2,
        ordered=ordered_of("analitica", "ecg"),
        abnormal=ordered_of("analitica"),
    )
    log, sink = clinical_log()
    log.emit("patient_arrived", 5.0, arrival_id=0, medio="propios_medios")
    log.emit("patient_registered", 5.0, arrival_id=0, edad=50, sexo="mujer")
    log.emit("triage_started", 5.0, arrival_id=0, circuito="enfermeria")
    log.emit("triage_completed", 10.0, arrival_id=0, nivel=4, motivo="otros")
    log.emit("test_ordered", 30.0, arrival_id=0, pruebas=["analitica", "ecg"])
    resultados = {"analitica": "alterado", "ecg": "normal"}
    log.emit("test_resulted", 97.5, arrival_id=0, resultados=resultados)

    view = episode_clinical_truth(
        sink.events, _truth(clinical), profiles=example_profiles(), start_date=START
    )

    assert (view.assigned_level, view.true_level) == (4, 2)
    assert (view.quality, view.jump) == ("infratriaje", 2)
    assert view.severity == 0.5
    analitica, radiografia, ecg, imagen = view.tests
    assert (analitica.test, analitica.ordered, analitica.result) == ("analitica", True, "alterado")
    assert analitica.base_turnaround == 75.0
    assert analitica.turnaround == pytest.approx(67.5)
    assert (ecg.result, ecg.turnaround) == ("normal", 12.0)
    assert (radiografia.ordered, radiografia.result, radiografia.turnaround) == (False, None, None)
    assert imagen.base_turnaround == 200.0 and imagen.turnaround is None
    assert view.round_expected == pytest.approx(67.5)
    assert view.round_observed == pytest.approx(67.5)


def test_ver_la_verdad_de_un_sobretriado_a_mano():
    # Real 4 asignado como 2, sin pruebas: no hay ronda esperada ni observada.
    clinical = hand_truth(level=2, true_level=4)
    log, sink = clinical_log()
    log.emit("patient_arrived", 900.0, arrival_id=0, medio="ambulancia")
    log.emit("patient_registered", 900.0, arrival_id=0, edad=81, sexo="hombre")

    view = episode_clinical_truth(
        sink.events, _truth(clinical, 900.0), profiles=example_profiles(), start_date=START
    )

    assert (view.assigned_level, view.true_level) == (2, 4)
    assert (view.quality, view.jump) == ("sobretriaje", 2)
    assert all(not t.ordered and t.result is None and t.turnaround is None for t in view.tests)
    assert view.round_expected is view.round_observed is None


def test_ver_la_verdad_exige_una_verdad_clinica():
    log, sink = clinical_log()
    log.emit("patient_arrived", 5.0, arrival_id=0, medio="propios_medios")
    provisional = EpisodeTruth("EP-000000", 0, 5.0, 3, 5.0, 20.0, 10.0, False, 30.0, False)

    with pytest.raises(ValueError, match="no clinical truth"):
        episode_clinical_truth(
            sink.events, provisional, profiles=example_profiles(), start_date=START
        )


def test_cumplimiento_por_nivel_real_de_la_ejecucion(clinical_store):
    result = read_run_results(clinical_store, "clinica")
    truth = read_run_episode_truth(clinical_store, "clinica")
    table, first, end = result.analysis.table, result.info.warmup_days, result.info.days

    window = true_level_window_compliance(table, truth, first, end)
    daily = true_level_compliance(table, GroundTruth(tuple(truth.values()), ()), first, end)

    assert window.daily.measure == "classified_to_doctor"
    np.testing.assert_array_equal(window.daily.n, daily.n)
    np.testing.assert_array_equal(window.daily.within, daily.within)
    # Los recuentos agrupan por el nivel real y cada uno con su máximo.
    done = [e for e in table if first * 1440 <= e.arrival < end * 1440 and e.departure]
    for level in window.by_level:
        patients = [
            e for e in done if truth[e.episode_id].clinical.triage.true_level == level.level
        ]
        assert level.n == len(patients)
        assert level.exceeded == sum(e.classified_to_doctor > level.max_wait for e in patients)
    # Guarda: hay pacientes mal clasificados, así que no es el cumplimiento asignado.
    assert any(t.clinical.triage.quality != "correcto" for t in truth.values())
