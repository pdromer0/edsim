"""«Ver la verdad» del desenlace del hito 5 (tarea 5.4, H5-10).

El ground truth guarda la paciencia, el destino (también el de quien se fue, que es el que
habría tenido) y la espera de cama base. Aquí se compara con el log de los escenarios del
motor, cuyos instantes se calcularon a mano en la 5.1:

- M: Q2 se va en 26 con paciencia 25 (llegó en 1) y Q4 en 4 con paciencia 1 (llegó en 3);
- C: R1 pide cama en 35, de noche (× 1,5), con base 100, y la recibe en 185;
- T: T1 llega en 1 con paciencia 60 y su plazo, 61, cae en su triaje (de 55 a 62), así que
  se va en 62.
"""

import dataclasses
from pathlib import Path

import pytest

from edsim.engine.analysis import episode_table
from edsim.engine.center import load_center
from edsim.engine.scenarios import SCENARIO_START, abandonment, admission, late_triage, run_scenario
from edsim.profiles.config import load_profiles
from edsim.runs import (
    compare_episode_truth,
    episode_outcome_truth,
    episode_segments,
    true_level_abandonment,
)

DATA = Path(__file__).parent / "data"
HORIZON = 1440.0


@pytest.fixture(scope="module")
def center():
    return load_center(DATA / "centro_ejemplo.toml")


@pytest.fixture(scope="module")
def profiles():
    return load_profiles(DATA / "perfiles_ejemplo.toml")


def rows(result, scenario, episode, profiles, *, truth=None, with_center=True):
    """Las filas de compare_episode_truth de un episodio, por campo."""
    events = [e for e in result.events if e.episode_id == episode]
    truth = truth or next(t for t in result.run.episodes if t.episode_id == episode)
    found = compare_episode_truth(
        events,
        episode_segments(events, HORIZON),
        truth,
        profiles=profiles,
        start_date=SCENARIO_START,
        center=scenario.center if with_center else None,
    )
    return {row.field: row for row in found}


def test_la_paciencia_de_quien_se_va_y_su_destino_contrafactual(center, profiles):
    scenario = abandonment(center)
    result = run_scenario(scenario)
    q2 = rows(result, scenario, "EP-000001", profiles)
    assert (q2["patience"].drawn, q2["patience"].observed, q2["patience"].status) == (
        25.0,
        25.0,
        "match",
    )
    assert (q2["destination"].drawn, q2["destination"].status) == ("alta", "unused")
    assert q2["bed_wait"].status == "unused"
    q4 = rows(result, scenario, "EP-000003", profiles)
    assert (q4["patience"].observed, q4["patience"].status) == (1.0, "match")
    # Q1, vista por el médico: su paciencia no se usó.
    assert rows(result, scenario, "EP-000000", profiles)["patience"].status == "unused"


def test_lo_que_quien_se_va_nunca_alcanza_no_se_usa(center, profiles):
    """Issue #105: las etapas de después de irse salen `unused`, no `pending` para siempre."""
    scenario = abandonment(center)
    result = run_scenario(scenario)
    # Q2 se tría de 1 a 6 y se va en 26 esperando al médico (Q1 lo tiene de 5 a 45).
    q2 = rows(result, scenario, "EP-000001", profiles)
    assert (q2["level"].status, q2["triage_time"].status) == ("match", "match")
    assert (q2["assessment_time"].drawn, q2["assessment_time"].status) == (20.0, "unused")
    # Con pruebas en su verdad, la reevaluación y la respuesta tampoco llegan.
    truth = next(t for t in result.run.episodes if t.episode_id == "EP-000001")
    with_tests = rows(
        result, scenario, "EP-000001", profiles, truth=dataclasses.replace(truth, needs_tests=True)
    )
    assert with_tests["reassessment_time"].status == "unused"
    assert with_tests["test_turnaround"].status == "unused"
    # Q4 llega en 3 y se va en 4 esperando enfermera (ocupadas hasta 5 y 6): ni nivel ni triaje.
    q4 = rows(result, scenario, "EP-000003", profiles)
    assert {field: q4[field].status for field in ("level", "triage_time", "assessment_time")} == {
        "level": "unused",
        "triage_time": "unused",
        "assessment_time": "unused",
    }
    assert (q4["level"].drawn, q4["triage_time"].drawn) == (5, 5.0)
    # Q1, visto por el médico: su valoración coincide, como siempre.
    assert rows(result, scenario, "EP-000000", profiles)["assessment_time"].status == "match"


def test_el_plazo_que_vence_en_el_triaje(center, profiles):
    scenario = late_triage(center)
    result = run_scenario(scenario)
    t1 = rows(result, scenario, "EP-000001", profiles)["patience"]
    # Paciencia 60, se va en 62 − 1 = 61 desde la llegada, al acabar el triaje.
    assert (t1.drawn, t1.observed, t1.status) == (60.0, 61.0, "match")


def test_otra_paciencia_en_la_verdad_es_un_desacuerdo(center, profiles):
    scenario = abandonment(center)
    result = run_scenario(scenario)
    truth = next(t for t in result.run.episodes if t.episode_id == "EP-000001")
    wrong = dataclasses.replace(truth, outcome=dataclasses.replace(truth.outcome, patience=24.0))
    assert rows(result, scenario, "EP-000001", profiles, truth=wrong)["patience"].status == (
        "mismatch"
    )


def test_la_espera_de_cama_con_el_factor_del_pedido(center, profiles):
    scenario = admission(center)
    result = run_scenario(scenario)
    r1 = rows(result, scenario, "EP-000000", profiles)
    # Base 100 × 1,5 (noche, a las 0:35) = 150; en waiting_bed de 35 a 185.
    assert (r1["bed_wait"].drawn, r1["bed_wait"].observed, r1["bed_wait"].status) == (
        150.0,
        150.0,
        "match",
    )
    assert r1["destination"].status == "match" and r1["patience"].status == "unused"
    # R3, nivel 1 en la puerta con paciencia 0: nunca abandona.
    assert rows(result, scenario, "EP-000002", profiles)["patience"].status == "unused"


def test_sin_centro_las_filas_de_siempre(center, profiles):
    scenario = abandonment(center)
    result = run_scenario(scenario)
    q2 = rows(result, scenario, "EP-000001", profiles, with_center=False)
    assert "patience" not in q2 and "bed_wait" not in q2
    assert q2["destination"].status == "unused"


def test_la_vista_del_desenlace(center):
    scenario = abandonment(center)
    result = run_scenario(scenario)
    events = [e for e in result.events if e.episode_id == "EP-000001"]
    truth = next(t for t in result.run.episodes if t.episode_id == "EP-000001")
    view = episode_outcome_truth(events, truth, center=scenario.center, start_date=SCENARIO_START)
    assert (view.patience, view.deadline, view.left_at, view.left_from) == (
        25.0,
        26.0,
        26.0,
        "medico",
    )
    assert view.expected_leave == 26.0 and view.counterfactual
    assert (view.destination, view.destination_observed) == ("alta", None)
    assert (view.bed_factor, view.bed_expected, view.bed_observed) == (None, None, None)

    scenario = admission(center)
    result = run_scenario(scenario)
    events = [e for e in result.events if e.episode_id == "EP-000000"]
    truth = next(t for t in result.run.episodes if t.episode_id == "EP-000000")
    view = episode_outcome_truth(events, truth, center=scenario.center, start_date=SCENARIO_START)
    assert (view.bed_base, view.bed_factor, view.bed_expected, view.bed_observed) == (
        100.0,
        1.5,
        150.0,
        150.0,
    )
    assert not view.counterfactual and view.destination_observed == "ingreso"


def test_la_vista_necesita_el_desenlace(center):
    scenario = abandonment(center)
    result = run_scenario(scenario)
    truth = next(t for t in result.run.episodes if t.episode_id == "EP-000000")
    events = [e for e in result.events if e.episode_id == "EP-000000"]
    with pytest.raises(ValueError, match="no outcome"):
        episode_outcome_truth(
            events,
            dataclasses.replace(truth, outcome=None),
            center=scenario.center,
            start_date=SCENARIO_START,
        )


def test_abandono_por_nivel_real(center):
    result = run_scenario(abandonment(center))
    truth = {t.episode_id: t for t in result.run.episodes}
    table = episode_table(result.events)
    found = true_level_abandonment(table, truth, 0.0, HORIZON)
    # Niveles reales (iguales a los asignados): Q1 3, Q2 4, Q3 4 y Q4 5; se van Q2 y Q4.
    assert [(lv.level, lv.arrivals, lv.left) for lv in found.by_level] == [
        (1, 0, 0),
        (2, 0, 0),
        (3, 1, 0),
        (4, 2, 1),
        (5, 1, 1),
    ]
    assert (found.left, found.severe, found.would_be_admitted) == (2, 0, 0)

    # Con Q4 de nivel real 2 y destino sorteado de ingreso: grave y habría ingresado.
    q4 = truth["EP-000003"]
    triage = dataclasses.replace(q4.clinical.triage, true_level=2)
    truth["EP-000003"] = dataclasses.replace(
        q4,
        clinical=dataclasses.replace(q4.clinical, triage=triage),
        outcome=dataclasses.replace(q4.outcome, destination="ingreso"),
    )
    found = true_level_abandonment(table, truth, 0.0, HORIZON)
    assert (found.severe, found.would_be_admitted) == (1, 1)
    assert found.by_level[1].left == 1 and found.by_level[1].share == 1.0
