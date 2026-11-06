"""Sensibilidad de los mandos y elección de la plantilla (tarea 4.6b)."""

import math
from pathlib import Path
from types import MappingProxyType

import pytest

from edsim.arrivals.profile import load_profile
from edsim.calibration import evaluate
from edsim.calibration.evaluate import (
    KNOB_TARGETS,
    ReplicaValues,
    SensitivityRow,
    TargetResult,
    candidate_center,
    check_knob_targets,
    choose_staffing,
    compliant_staffing,
    sensitivity,
)
from edsim.calibration.staffing import DOCTORS, NURSES, RuleStaffing, nurse_loads, rule_staffings
from edsim.calibration.targets import CHECK, FIT, Target, load_targets
from edsim.engine.center import load_center
from edsim.profiles.config import load_profiles
from edsim.stats import Summary

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data"


def target(name, reference=None, band=(6, 15), use=FIT):
    return Target(
        name=name,
        measure="triage_wait",
        levels=(2, 3, 4, 5),
        statistic="media",
        threshold=None,
        band=band,
        use=use,
        source="a mano",
        link="https://example.org",
        reference=reference,
    )


PRETRIAGE = target("pretriaje_medio", reference=12.4)
CLOCK_A = target("tiempo_medico_niveles_2_5", band=(35, 70))
LEVEL_3 = target("tiempo_medico_nivel_3", reference=59.0, band=(45, 75))


def result(t: Target, mean: float, passed: bool = True) -> TargetResult:
    """Un resultado a mano: la media y si pasa (por la media)."""
    summary = Summary(10, mean, 1.0, 0.3, mean - 0.7, mean + 0.7, 0.95)
    return TargetResult(t, (mean,) * 10, summary, (0.0,) * 10, passed, True)


def row(staff, u, results, compliance=(math.nan,) * 5) -> SensitivityRow:
    """Una fila a mano, con dos réplicas que dan el cumplimiento indicado."""
    reps = tuple(ReplicaValues(MappingProxyType({}), 100, 0, compliance) for _ in range(2))
    return SensitivityRow(RuleStaffing(staff, u, u), None, tuple(results), reps)


# --- Elección -----------------------------------------------------------------------------


def test_enfermeria_la_mas_cercana_a_la_referencia_entre_las_que_pasan():
    # [3, 2, 1] queda a 0,4 de 12,4 pero no pasa; entre las que pasan, [3, 3, 1] (a 2,4)
    # gana a [3, 3, 2] (a 6,1).
    rows = [
        row((3, 3, 2), 0.60, [result(PRETRIAGE, 6.3)]),
        row((3, 3, 1), 0.70, [result(PRETRIAGE, 10.0)]),
        row((3, 2, 1), 0.80, [result(PRETRIAGE, 12.0, passed=False)]),
        row((2, 2, 1), 0.85, [result(PRETRIAGE, 19.8, passed=False)]),
    ]
    assert choose_staffing(rows, NURSES).staffing.staff == (3, 3, 1)


def test_medicos_tienen_que_pasar_los_dos_objetivos_y_decide_el_nivel_3():
    rows = [
        row((12, 12, 5), 0.80, [result(CLOCK_A, 30.0, passed=False), result(LEVEL_3, 58.0)]),
        row((11, 10, 4), 0.90, [result(CLOCK_A, 40.0), result(LEVEL_3, 50.0)]),
        row((10, 10, 4), 0.95, [result(CLOCK_A, 55.0), result(LEVEL_3, 70.0)]),
    ]
    assert choose_staffing(rows, DOCTORS).staffing.staff == (11, 10, 4)


def test_ninguna_pasa_y_no_se_fuerza():
    rows = [row((3, 3, 2), 0.6, [result(PRETRIAGE, 1.4, passed=False)])]
    assert choose_staffing(rows, NURSES) is None
    assert choose_staffing([], NURSES) is None


def test_empate_la_de_menos_personal():
    rows = [
        row((3, 3, 2), 0.6, [result(PRETRIAGE, 11.4)]),
        row((3, 3, 1), 0.7, [result(PRETRIAGE, 13.4)]),
    ]
    assert choose_staffing(rows, NURSES).staffing.staff == (3, 3, 1)


def test_el_cumplidor_es_el_de_u_mas_alto_con_todos_los_niveles_al_10_por_ciento():
    # Nivel 1 sin porcentaje (no cuenta); la de u 0,95 tiene el nivel 2 al 30 %.
    nan = math.nan
    rows = [
        row((14, 13, 5), 0.70, [], (1.0, 0.0, 0.0, 0.0, 0.0)),
        row((12, 12, 5), 0.80, [], (1.0, 0.10, 0.0, 0.05, 0.0)),
        row((11, 10, 4), 0.90, [], (1.0, 0.12, 0.0, 0.0, 0.0)),
        row((10, 10, 4), 0.95, [], (1.0, 0.30, nan, 0.0, 0.0)),
    ]
    assert compliant_staffing(rows).staffing.staff == (12, 12, 5)
    assert compliant_staffing(rows[2:]) is None


def test_objetivos_de_cada_mando():
    assert KNOB_TARGETS[NURSES] == (("pretriaje_medio",), "pretriaje_medio")
    real = load_targets(ROOT / "config" / "objetivos.toml")
    check_knob_targets(real, NURSES)
    check_knob_targets(real, DOCTORS)
    with pytest.raises(ValueError, match="needs the target objetivos.tiempo_medico_nivel_3"):
        check_knob_targets([PRETRIAGE, CLOCK_A], DOCTORS)
    with pytest.raises(ValueError, match="objetivos.pretriaje_medio.referencia is needed"):
        check_knob_targets([target("pretriaje_medio")], NURSES)
    with pytest.raises(ValueError, match="must be of use 'ajuste'"):
        check_knob_targets([target("pretriaje_medio", 12.4, use=CHECK)], NURSES)
    with pytest.raises(ValueError, match="knob must be one of"):
        check_knob_targets(real, "boxes")


def test_candidato_cambia_solo_su_mando():
    center = load_center(DATA / "centro_sala_ejemplo.toml")
    nurses = candidate_center(center, NURSES, (2, 2, 1))
    doctors = candidate_center(center, DOCTORS, (9, 9, 4))
    assert (nurses.triage_nurses, nurses.doctors) == ((2, 2, 1), center.doctors)
    assert (doctors.triage_nurses, doctors.doctors) == (center.triage_nurses, (9, 9, 4))


# --- Sensibilidad corta con el ejemplo ------------------------------------------------------


def test_sensibilidad_corta_cada_candidato_con_su_plantilla(monkeypatch):
    center = load_center(DATA / "centro_sala_ejemplo.toml")
    arrivals = load_profile(DATA / "llegadas_ejemplo.toml")
    profiles = load_profiles(DATA / "perfiles_ejemplo.toml")
    targets = load_targets(ROOT / "config" / "objetivos.toml")
    expected = rule_staffings(nurse_loads(profiles, arrivals, center.shift_starts), 0.6, 0.9)
    assert len(expected) >= 2  # hay varias plantillas que comparar

    simulated = []
    real = evaluate.simulate_ed

    def spy(sim_center, *args, **kwargs):
        simulated.append((sim_center.triage_nurses, sim_center.doctors))
        return real(sim_center, *args, **kwargs)

    monkeypatch.setattr(evaluate, "simulate_ed", spy)
    seen = []
    rows = sensitivity(
        center,
        arrivals,
        profiles,
        targets,
        NURSES,
        replicas=2,
        days=2,
        warmup_days=1,
        seed=7,
        u_min=0.6,
        u_max=0.9,
        on_row=seen.append,
    )

    assert [r.staffing for r in rows] == list(expected)
    assert list(rows) == seen
    assert simulated == [(s.staff, center.doctors) for s in expected for _ in range(2)]
    assert all(r.center.triage_nurses == r.staffing.staff for r in rows)
    pretriage = [r.result("pretriaje_medio").mean for r in rows]
    assert len(set(pretriage)) == len(pretriage)  # cada plantilla da otro pretriaje
