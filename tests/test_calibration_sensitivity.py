"""Sensibilidad de los mandos y elección de la plantilla (tarea 4.6b)."""

from fractions import Fraction
from pathlib import Path
from types import MappingProxyType

import pytest

from edsim.arrivals.profile import load_profile
from edsim.calibration import evaluate
from edsim.calibration.evaluate import (
    COMPLIANCE_SHARE_OUT,
    KNOB_TARGETS,
    ReplicaValues,
    SensitivityRow,
    TargetResult,
    candidate_center,
    check_knob_targets,
    choose_staffing,
    compliant_staffing,
    complies,
    evaluate_staffings,
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


def row(staff, u, results, *replicas) -> SensitivityRow:
    """Una fila a mano; cada réplica, (días fuera, días medidos) por nivel 1 a 5. Sin
    réplicas, dos sin días fuera y con 12 días medidos en cada nivel."""
    replicas = replicas or (((0,) * 5, (12,) * 5),) * 2
    reps = tuple(ReplicaValues(MappingProxyType({}), 100, 0, out, days) for out, days in replicas)
    return SensitivityRow(RuleStaffing(staff, u, u), None, tuple(results), reps)


def level4(out_by_replica, days_by_replica):
    """Réplicas con días fuera solo en el nivel 4; los niveles 2, 3 y 5, 12 días sin fallos."""
    return tuple(
        ((0, 0, 0, out, 0), (12, 12, 12, days, 12))
        for out, days in zip(out_by_replica, days_by_replica, strict=True)
    )


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


def test_medicos_eligen_por_el_centro_de_la_horquilla_y_el_nivel_3_no_decide():
    # Los niveles 2 a 5 no tienen referencia: decide el centro de [35, 70], 52,5. Entre
    # las que pasan, la de 54,5 (a 2,0) gana a la de 43,8 (a 8,7). La de 52,0 estaría
    # más cerca, pero no pasa (su IC es más ancho que la horquilla); y la de 30,0 tiene
    # el nivel 3 más cercano a 59, pero una comprobación no decide el ajuste.
    rows = [
        row((13, 13, 5), 0.72, [result(CLOCK_A, 30.0, passed=False), result(LEVEL_3, 58.0)]),
        row((12, 12, 5), 0.80, [result(CLOCK_A, 43.8), result(LEVEL_3, 22.0)]),
        row((12, 11, 5), 0.85, [result(CLOCK_A, 54.5), result(LEVEL_3, 22.9)]),
        row((12, 11, 4), 0.85, [result(CLOCK_A, 52.0, passed=False), result(LEVEL_3, 29.0)]),
    ]
    assert CLOCK_A.reference is None and CLOCK_A.aim == 52.5
    assert choose_staffing(rows, DOCTORS).staffing.staff == (12, 11, 5)


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
    # Dos réplicas de 10 días medidos (20 en total). El nivel 1 no cuenta. La de u 0,80
    # tiene el nivel 2 con 2 de 20 (justo el 10 %) y el 4 con 1 de 20; la de 0,90, el
    # nivel 2 con 3 de 20; la de 0,95, sin pacientes de nivel 3 (0 días medidos).
    def rep(out, days=(10,) * 5):
        return out, days

    rows = [
        row((14, 13, 5), 0.70, [], rep((10, 0, 0, 0, 0)), rep((10, 0, 0, 0, 0))),
        row((12, 12, 5), 0.80, [], rep((10, 1, 0, 1, 0)), rep((10, 1, 0, 0, 0))),
        row((11, 10, 4), 0.90, [], rep((10, 2, 0, 0, 0)), rep((10, 1, 0, 0, 0))),
        row(
            (10, 10, 4),
            0.95,
            [],
            rep((10, 0, 0, 0, 0), (10, 10, 0, 10, 10)),
            rep((10,) + (0,) * 4, (10, 10, 0, 10, 10)),
        ),
    ]
    assert compliant_staffing(rows).staffing.staff == (12, 12, 5)
    assert compliant_staffing(rows[2:]) is None
    assert rows[1].compliance_days[1] == (2, 20) and rows[1].compliance_days[3] == (1, 20)


def test_el_cumplidor_en_el_borde_con_dias_enteros():
    # 10 réplicas × 12 días = 120 días medidos en el nivel 4: con 12 fuera (justo el
    # 10 %) pasa; con 13, no.
    days = [12] * 10
    border = row((12, 12, 5), 0.80, [], *level4([2, 2, 1, 1, 1, 1, 1, 1, 1, 1], days))
    over = row((12, 12, 5), 0.80, [], *level4([2, 2, 2, 1, 1, 1, 1, 1, 1, 1], days))
    assert border.compliance_days[3] == (12, 120) and over.compliance_days[3] == (13, 120)
    assert compliant_staffing([border]) is border
    assert compliant_staffing([over]) is None
    assert complies(border.compliance_days) and not complies(over.compliance_days)


def test_el_cumplidor_suma_los_dias_y_no_promedia_las_proporciones():
    # 12 réplicas con 120 días medidos en el nivel 4: ocho de 12 días y cuatro de 6 (días
    # sin pacientes de nivel 4), y los 12 días fuera en las de 6. Sumados, 12 de 120: justo
    # el 10 %, pasa. La media de las proporciones por réplica sería 4 · 0,5 / 12 = 0,167.
    out = [0] * 8 + [3] * 4
    days = [12] * 8 + [6] * 4
    r = row((12, 12, 5), 0.80, [], *level4(out, days))
    assert r.compliance_days[3] == (12, 120)
    assert r.compliance_out[3] > COMPLIANCE_SHARE_OUT  # el caso ocurre: la media pasa de 0,10
    assert r.compliance_out[3] == pytest.approx(1 / 6)
    assert compliant_staffing([r]) is r


def test_el_cumplidor_exige_dias_medidos_en_cada_nivel():
    r = row((12, 12, 5), 0.80, [], *level4([0, 0], [0, 0]))
    assert r.compliance_days[3] == (0, 0)
    assert compliant_staffing([r]) is None


def test_el_limite_del_cumplidor_es_una_fraccion_exacta():
    assert COMPLIANCE_SHARE_OUT == Fraction(1, 10)


def test_objetivos_de_cada_mando():
    assert KNOB_TARGETS[NURSES] == (("pretriaje_medio",), "pretriaje_medio")
    assert KNOB_TARGETS[DOCTORS] == (("tiempo_medico_niveles_2_5",), "tiempo_medico_niveles_2_5")
    real = load_targets(ROOT / "config" / "objetivos.toml")
    check_knob_targets(real, NURSES)
    check_knob_targets(real, DOCTORS)
    with pytest.raises(ValueError, match="needs the target objetivos.tiempo_medico_niveles_2_5"):
        check_knob_targets([PRETRIAGE, LEVEL_3], DOCTORS)
    check_knob_targets([target("pretriaje_medio")], NURSES)  # sin referencia: el centro
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


# --- Plantillas dadas (notebook 04, sección 9) --------------------------------------------


def test_plantillas_dadas_en_su_orden_y_cada_una_con_su_plantilla(monkeypatch):
    center = load_center(DATA / "centro_sala_ejemplo.toml")
    arrivals = load_profile(DATA / "llegadas_ejemplo.toml")
    profiles = load_profiles(DATA / "perfiles_ejemplo.toml")
    targets = load_targets(ROOT / "config" / "objetivos.toml")
    # Dos plantillas de médicos que no son de la regla, en un orden cualquiera.
    given = [RuleStaffing((9, 9, 4), 0.80, 0.81), RuleStaffing((14, 13, 5), 0.60, 0.61)]

    simulated = []
    real = evaluate.simulate_ed

    def spy(sim_center, *args, **kwargs):
        simulated.append((sim_center.triage_nurses, sim_center.doctors))
        return real(sim_center, *args, **kwargs)

    monkeypatch.setattr(evaluate, "simulate_ed", spy)
    seen = []
    rows = evaluate_staffings(
        center,
        arrivals,
        profiles,
        targets,
        DOCTORS,
        given,
        replicas=2,
        days=2,
        warmup_days=1,
        seed=7,
        on_row=seen.append,
    )

    assert [r.staffing for r in rows] == given
    assert list(rows) == seen
    assert simulated == [(center.triage_nurses, s.staff) for s in given for _ in range(2)]
    assert [r.center.doctors for r in rows] == [(9, 9, 4), (14, 13, 5)]


def test_plantillas_dadas_con_un_mando_desconocido():
    with pytest.raises(ValueError, match="knob must be one of"):
        evaluate_staffings(
            None, None, None, (), "boxes", [], replicas=2, days=2, warmup_days=1, seed=7
        )
