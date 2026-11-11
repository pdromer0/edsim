"""El cumplimiento con censura y las medias de los atendidos (tarea 5.4, pieza 4, H5-8).

Con el abandono, quitar a los que se van haría parecer mejor un servicio que va peor. Cada
métrica sigue la regla de su fuente:

- las medias de los relojes son de los atendidos;
- en el cumplimiento, quien se va con su reloj ya en el máximo o por encima incumple, y
  quien se va antes queda censurado (no cuenta);
- quien se va antes del triaje no tiene nivel y queda fuera de todo cumplimiento.

Los logs se escriben a mano con `v4_logs.HandLog` y pasan por `episode_table`, así que
comprueban también lo que la tabla saca del log. Los valores, del plan de la 5.4 (A, A2 y
A3): los pacientes llegan en 0 y se clasifican de 0 a 5, y el reloj C cuenta desde el 5.
"""

from pathlib import Path

import numpy as np
import pytest
from clinical_factory import hand_truth
from v4_logs import HandLog

from edsim.engine.analysis import analyze_run, episode_table
from edsim.engine.center import load_center
from edsim.engine.ground_truth import EpisodeTruth, GroundTruth
from edsim.engine.report import format_run_summary
from edsim.engine.targets import (
    compliance_cases,
    manchester_compliance,
    pretriage,
    true_level_compliance,
)
from edsim.runs.metrics import window_clocks, window_compliance
from edsim.runs.truth import true_level_window_compliance

LEVEL_4 = 3  # columna del nivel 4 en las tablas por nivel


def three_patients(p3_leaves: float) -> list:
    """P1 y P2 ven al médico en 35 y 95 (C = 30 y 90); P3 se va esperando box en `p3_leaves`."""
    log = HandLog()
    for who in (1, 2, 3):
        log.arrive(who, 0.0)
    for who in (1, 2, 3):
        log.triage(who, 0.0, 5.0, 4)
    log.box(1, 5.0, 1).box(2, 5.0, 2)
    log.assess(1, 35.0, 45.0, 1).depart(1, 45.0)
    log.leave(3, p3_leaves, "box")
    log.assess(2, 95.0, 105.0, 2).depart(2, 105.0)
    return episode_table(log.events())


def test_los_relojes_de_la_tabla_a_mano():
    table = {e.episode_id: e for e in three_patients(155.0)}
    assert [table[f"EP-00000{i}"].classified_to_doctor for i in (1, 2)] == [30.0, 90.0]
    p3 = table["EP-000003"]
    assert (p3.classified_to_doctor, p3.left, p3.left_from) == (None, 155.0, "box")


# --- A: los tres pacientes de la pieza 4 -----------------------------------------------


def test_la_media_es_de_los_atendidos():
    level_4 = window_clocks(three_patients(155.0), 0, 1)[LEVEL_4]
    clock_c = next(c for c in level_4.clocks if c.measure == "classified_to_doctor")
    assert level_4.n == 2
    assert clock_c.mean == (30 + 90) / 2  # 60; con P3 serían (30 + 90 + 150) / 3 = 90


@pytest.mark.parametrize(
    ("p3_leaves", "n", "within", "exceeded", "censored"),
    [
        (155.0, 3, 2 / 3, 1, 0),  # C = 150 ≥ 120: incumple
        (25.0, 2, 1.0, 0, 1),  # C = 20 < 120: censurado
        (125.0, 3, 2 / 3, 1, 0),  # C = 120, justo el máximo: incumple (no fue visto en 125)
    ],
)
def test_cumplimiento_con_censura(p3_leaves, n, within, exceeded, censored):
    table = three_patients(p3_leaves)

    daily = manchester_compliance(table, 0, 1)
    assert daily.n[0, LEVEL_4] == n
    assert daily.within[0, LEVEL_4] == within
    assert daily.left_late[0, LEVEL_4] == exceeded
    assert daily.censored[0, LEVEL_4] == censored
    assert daily.pooled_within[LEVEL_4] == pytest.approx(within, abs=1e-12)

    pooled = window_compliance(table, 0, 1).by_level[LEVEL_4]
    assert (pooled.n, pooled.exceeded, pooled.censored) == (n, exceeded, censored)
    assert pooled.exceeded_share == pytest.approx(exceeded / n, abs=1e-12)


def test_sin_abandonos_los_campos_nuevos_valen_0():
    log = HandLog().arrive(1, 0.0).triage(1, 0.0, 5.0, 4).box(1, 5.0, 1)
    log.assess(1, 35.0, 45.0, 1).depart(1, 45.0)
    daily = manchester_compliance(episode_table(log.events()), 0, 1)
    assert not daily.left_late.any() and not daily.censored.any()
    assert daily.within[0, LEVEL_4] == 1.0


# --- A2: el tiempo de quien se va depende del reloj -----------------------------------


def leaves_at_122() -> list:
    """Nivel 4, clasificado de 0 a 5; se va en 122 esperando box."""
    log = HandLog().arrive(1, 0.0).triage(1, 0.0, 5.0, 4).leave(1, 122.0, "box")
    return episode_table(log.events())


@pytest.mark.parametrize(
    ("measure", "clock", "status"),
    [
        ("classified_to_doctor", 117.0, "censored"),  # 122 − 5
        ("triage_start_to_doctor", 122.0, "exceeded"),  # 122 − 0
        ("door_to_doctor", 122.0, "exceeded"),  # 122 − 0
    ],
)
def test_el_tiempo_de_quien_se_va_depende_del_reloj(measure, clock, status):
    table = leaves_at_122()
    [case] = compliance_cases(table, 0, 1, (0, 10, 60, 120, 240), measure=measure)
    assert (case.clock, case.status) == (clock, status)

    daily = manchester_compliance(table, 0, 1, measure=measure)
    counted = status == "exceeded"
    assert daily.n[0, LEVEL_4] == int(counted)
    assert daily.censored[0, LEVEL_4] == int(not counted)


# --- A3: quien se va antes del triaje queda fuera de todo cumplimiento ----------------


def before_triage() -> list:
    """P1 y P2 de A, más EP-000003: llega en 0 y se va en 200 sin triaje."""
    log = HandLog()
    for who in (1, 2, 3):
        log.arrive(who, 0.0)
    for who in (1, 2):
        log.triage(who, 0.0, 5.0, 4)
    log.box(1, 5.0, 1).box(2, 5.0, 2)
    log.assess(1, 35.0, 45.0, 1).depart(1, 45.0)
    log.assess(2, 95.0, 105.0, 2).depart(2, 105.0)
    log.leave(3, 200.0, "triaje")
    return episode_table(log.events())


def truth(n: int) -> EpisodeTruth:
    """La verdad de un paciente de nivel asignado y real 4."""
    return EpisodeTruth(
        episode_id=f"EP-{n:06d}",
        arrival_id=n,
        arrival_time=0.0,
        level=4,
        triage_time=5.0,
        assessment_time=10.0,
        reassessment_time=10.0,
        needs_tests=False,
        test_turnaround=None,
        admitted=False,
        clinical=hand_truth(level=4, true_level=4),
    )


@pytest.mark.parametrize("measure", ["classified_to_doctor", "door_to_doctor"])
def test_quien_se_va_antes_del_triaje_no_cuenta_en_ningun_cumplimiento(measure):
    table = before_triage()
    ground_truth = GroundTruth(tuple(truth(n) for n in (1, 2, 3)), ())

    for daily in (
        manchester_compliance(table, 0, 1, measure=measure),
        true_level_compliance(table, ground_truth, 0, 1, measure=measure),
    ):
        assert daily.n[0, LEVEL_4] == 2
        assert daily.within[0, LEVEL_4] == 1.0
        assert not daily.censored.any() and not daily.left_late.any()

    by_truth = {e.episode_id: e for e in ground_truth.episodes}
    pooled = true_level_window_compliance(table, by_truth, 0, 1, measure=measure)
    assert (pooled.by_level[LEVEL_4].n, pooled.by_level[LEVEL_4].censored) == (2, 0)


# --- El pretriaje es de los triados ---------------------------------------------------


def test_el_pretriaje_cuenta_a_quien_se_va_despues_del_triaje():
    # Tres de nivel 4, los tres triados en 0: P3 se va después (en 155) y cuenta;
    # un cuarto se va antes del triaje y no cuenta.
    log = HandLog()
    for who in (1, 2, 3, 4):
        log.arrive(who, 0.0)
    for who in (1, 2, 3):
        log.triage(who, 0.0, 5.0, 4)
    log.box(1, 5.0, 1).box(2, 5.0, 2)
    log.assess(1, 35.0, 45.0, 1).depart(1, 45.0)
    log.leave(4, 50.0, "triaje")
    log.leave(3, 155.0, "box")
    log.assess(2, 95.0, 105.0, 2).depart(2, 105.0)
    p = pretriage(episode_table(log.events()), 0, 1)
    level_4 = p.groups.index(4)
    assert p.n[0, level_4] == 3
    assert np.array_equal(p.n_within[0], p.n[0])  # pretriaje 0: todos dentro


# --- El resumen de la CLI ---------------------------------------------------------------


def test_un_nivel_sin_atendidos_y_con_un_incumplimiento_seguro(tmp_path):
    # Un único paciente de nivel 4: se clasifica de 0 a 5 y se va en 200 esperando box
    # (C = 195 ≥ 120). Nadie del nivel ve al médico, pero su cumplimiento existe: 0 % y el
    # día fuera, no «—».
    log = HandLog().staff(0.0, "enfermeria_triaje", 0, 1).staff(0.0, "medicos", 0, 1)
    log.arrive(1, 0.0).triage(1, 0.0, 5.0, 4).leave(1, 200.0, "box")
    center = load_center(Path(__file__).parent / "data" / "centro_h5_ejemplo.toml")
    analysis = analyze_run(log.events(), center, 1, 0)
    line = next(x for x in format_run_summary(analysis, []).splitlines() if x.startswith("nivel 4"))
    assert line.split()[2:] == ["0", "—", "—", "—", "120", "0.0", "%", "1", "de", "1"]
