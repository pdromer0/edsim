"""Perfil observable de cada episodio y sus filtros (tarea 4.8a).

Edad, sexo, medio de llegada, motivo y pruebas salen del log (``patient_arrived``,
``patient_registered``, ``triage_completed`` y ``test_ordered``), nunca del ground
truth: una ejecución clínica sin el CSV de verdad sigue mostrando el perfil.
"""

import pytest
from clinical_factory import clinical_log, example_profiles
from runs_factory import copy_run

from edsim.engine.analysis import episode_table
from edsim.runs import (
    EpisodeFilters,
    ObservedProfile,
    filter_episodes,
    observed_profiles,
    read_run_results,
)


@pytest.fixture
def events():
    """Tres pacientes a mano: con pruebas, sin pruebas y sin terminar el triaje."""
    log, sink = clinical_log()

    def arrive(who, t, medio, edad, sexo):
        log.emit("patient_arrived", t, arrival_id=who, medio=medio)
        log.emit("patient_registered", t, arrival_id=who, edad=edad, sexo=sexo)
        log.emit("triage_started", t, arrival_id=who, circuito="enfermeria")

    arrive(0, 1500.0, "ambulancia", 82, "hombre")
    log.emit("triage_completed", 1505.0, arrival_id=0, nivel=3, motivo="disnea")
    log.emit("box_assigned", 1505.0, arrival_id=0, box=1)
    arrive(1, 1510.0, "propios_medios", 30, "mujer")
    log.emit("triage_completed", 1515.0, arrival_id=1, nivel=4, motivo="traumatismo")
    log.emit("box_assigned", 1515.0, arrival_id=1, box=2)
    log.emit("assessment_started", 1520.0, arrival_id=0, tipo="inicial", pool="medicos", box=1)
    arrive(2, 1525.0, "propios_medios", 64, "mujer")
    log.emit("assessment_started", 1530.0, arrival_id=1, tipo="inicial", pool="medicos", box=2)
    log.emit("assessment_ended", 1540.0, arrival_id=0, tipo="inicial", interrumpida=False)
    log.emit("test_ordered", 1540.0, arrival_id=0, pruebas=["analitica", "radiografia"])
    return sink.events


def test_el_perfil_sale_del_log(events):
    profiles = observed_profiles(events, example_profiles().population)

    assert profiles["EP-000000"] == ObservedProfile(
        "EP-000000", 82, 3, "hombre", "ambulancia", "disnea", ("analitica", "radiografia")
    )
    assert profiles["EP-000001"] == ObservedProfile(
        "EP-000001", 30, 0, "mujer", "propios_medios", "traumatismo", ()
    )
    # Sin triaje terminado todavía no hay motivo; 64 años es la banda 45-64.
    assert profiles["EP-000002"] == ObservedProfile(
        "EP-000002", 64, 1, "mujer", "propios_medios", None, ()
    )


def test_filtros_de_perfil_combinados_con_los_de_siempre(events):
    table = episode_table(events)
    profiles = observed_profiles(events, example_profiles().population)

    def ids(**filters):
        kept = filter_episodes(
            table, EpisodeFilters(**filters), warmup_end=1440, horizon=2880, observed=profiles
        )
        return [e.episode_id for e in kept]

    assert ids(sex="mujer") == ["EP-000001", "EP-000002"]
    assert ids(sex="mujer", age_band=0) == ["EP-000001"]
    assert ids(test="radiografia") == ["EP-000000"]
    assert ids(test="radiografia", level=4) == []
    assert ids(arrival_mode="propios_medios", level=4) == ["EP-000001"]
    assert ids(reason="traumatismo", period="unfinished") == ["EP-000001"]
    # Sin motivo en el log, el tercero no pasa ningún filtro de motivo.
    assert "EP-000002" not in ids(reason="disnea") + ids(reason="traumatismo")


def test_un_filtro_de_perfil_sin_perfiles_es_un_error(events):
    with pytest.raises(ValueError, match="observed profiles"):
        filter_episodes(episode_table(events), EpisodeFilters(sex="mujer"), warmup_end=0, horizon=1)


@pytest.mark.parametrize(
    "changes",
    [
        {"age_band": 4},
        {"age_band": True},
        {"sex": "otro"},
        {"arrival_mode": "taxi"},
        {"reason": "gripe"},
        {"test": "resonancia"},
    ],
)
def test_valores_de_filtro_invalidos(changes):
    with pytest.raises(ValueError):
        EpisodeFilters(**changes)


def test_sin_filtros_de_perfil_no_hace_falta_el_perfil(events):
    table = episode_table(events)
    kept = filter_episodes(table, EpisodeFilters(level=3), warmup_end=1440, horizon=2880)

    assert [e.episode_id for e in kept] == ["EP-000000"]
    assert not EpisodeFilters().uses_profile


def test_sin_el_csv_de_verdad_la_tabla_sigue_con_el_perfil(
    clinical_store, clinical_simulation, tmp_path
):
    _, simulated = clinical_simulation
    store, path = copy_run(clinical_store, "clinica", tmp_path)
    (path / "ground_truth_episodios.csv").unlink()

    result = read_run_results(store, "clinica")

    records = {e.episode_id: e for e in result.analysis.table}
    assert result.observed.keys() == records.keys()
    with_tests = 0
    for truth in simulated.episodes:
        profile, clinical = result.observed[truth.episode_id], truth.clinical
        assert profile.age == clinical.person.age
        assert profile.age_band == clinical.person.band
        assert (profile.sex, profile.arrival_mode) == (clinical.sex, clinical.arrival_mode)
        triaged = records[truth.episode_id].triage_end is not None
        assert profile.reason == (clinical.reason if triaged else None)
        assert profile.tests in ((), clinical.workup.ordered_types)
        if records[truth.episode_id].departure is not None:
            assert profile.tests == clinical.workup.ordered_types
        with_tests += bool(profile.tests)
    assert with_tests > 100  # guarda: hay pruebas que comparar


def test_la_provisional_no_tiene_perfil(clinical_store):
    assert read_run_results(clinical_store, "provisional").observed is None


def test_esperas_de_box_inicial_y_de_la_vuelta_en_la_tabla(clinical_store):
    # Con espera_resultados_fuera = [4, 5], solo los niveles 4 y 5 con pruebas dejan el box,
    # y solo ellos pueden esperar box a la vuelta.
    result = read_run_results(clinical_store, "clinica-sala")
    done = [e for e in result.analysis.table if e.departure is not None]
    left = {e.episode_id for e in done if e.level in (4, 5) and result.observed[e.episode_id].tests}

    assert left  # guarda: alguien dejó el box
    assert all(e.initial_box_wait is not None for e in done)
    assert all(e.results_box_wait == 0 for e in done if e.episode_id not in left)
    assert any(e.results_box_wait > 0 for e in done if e.episode_id in left)
