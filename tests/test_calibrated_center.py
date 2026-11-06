"""Centro base calibrado y centro cumplidor (tareas 4.6b y 4.6c)."""

import dataclasses
from pathlib import Path

import pytest

from edsim.arrivals.profile import load_profile
from edsim.calibration.evaluate import (
    CHECK_SEED,
    CONFIRMATION_SEED,
    FIT_SEED,
    choose_staffing,
    compliant_staffing,
    complies,
    evaluate_staffings,
    passes_fit,
    simulate_replicas,
    summarize_targets,
)
from edsim.calibration.staffing import (
    DOCTORS,
    NURSES,
    doctor_loads,
    equivalent_staff,
    nurse_loads,
    rule_staffings,
)
from edsim.calibration.targets import load_targets
from edsim.calibration.window import ANNUAL, window_start_dates
from edsim.engine.center import load_center
from edsim.profiles.config import load_profiles

CONFIG = Path(__file__).resolve().parents[1] / "config"
DATA = Path(__file__).resolve().parent / "data"

# Los intervalos de u del comentario de config/centro.toml y config/centro_cumplidor.toml.
NURSES_U = (0.795, 0.8325)
DOCTORS_U = (0.85, 0.85)
COMPLIANT_U = (0.67, 0.6775)
STEP = 0.0025


@pytest.fixture(scope="module")
def centers():
    return load_center(CONFIG / "centro.toml"), load_center(CONFIG / "centro_cumplidor.toml")


@pytest.fixture(scope="module")
def loads(centers):
    profiles = load_profiles(CONFIG / "perfiles.toml")
    arrivals = load_profile(CONFIG / "llegadas.toml")
    starts = centers[0].shift_starts
    return nurse_loads(profiles, arrivals, starts), doctor_loads(profiles, arrivals, starts)


def test_plantilla_calibrada(centers):
    base, _ = centers
    assert base.triage_nurses == (3, 2, 1)
    assert base.doctors == (12, 11, 4)
    assert base.boxes == 30 and base.results_wait_outside == (4, 5)


def test_el_cumplidor_solo_difiere_en_los_medicos(centers):
    base, compliant = centers
    assert compliant.doctors == (14, 14, 6)
    assert compliant != base
    assert dataclasses.replace(compliant, doctors=base.doctors) == base


@pytest.mark.parametrize(
    ("which", "knob", "u"),
    [
        ("base", "nurses", NURSES_U),
        ("base", "doctors", DOCTORS_U),
        ("compliant", "doctors", COMPLIANT_U),
    ],
)
def test_las_plantillas_salen_de_la_regla_con_los_u_del_comentario(centers, loads, which, knob, u):
    # Los dos bordes del intervalo dan la plantilla escrita, y el paso de fuera, otra.
    center = centers[0] if which == "base" else centers[1]
    staff = center.triage_nurses if knob == "nurses" else center.doctors
    knob_loads = loads[0] if knob == "nurses" else loads[1]
    low, high = u
    assert equivalent_staff(knob_loads, low) == staff
    assert equivalent_staff(knob_loads, high) == staff
    assert equivalent_staff(knob_loads, round(low - STEP, 10)) != staff
    assert equivalent_staff(knob_loads, round(high + STEP, 10)) != staff


@pytest.mark.slow
def test_reproduce_la_fila_corta_del_registro():
    # docs/calibracion/registro.md, «Fila reproducible» de la tarea 4.6b: el centro
    # calibrado entonces (fijado en tests/data/centro_4_6b.toml), 3 réplicas de 5 días con
    # 1 de calentamiento (y el de vaciado), semilla 2026, todas desde fecha_inicio (sin
    # fechas, simulate_replicas da lo mismo que antes de la ventana anual). Con tan pocas
    # réplicas el IC de los niveles 2 a 5 es más ancho que la horquilla: código 1.
    targets = load_targets(CONFIG / "objetivos.toml")
    replicas = simulate_replicas(
        load_center(DATA / "centro_4_6b.toml"),
        load_profile(CONFIG / "llegadas.toml"),
        load_profiles(CONFIG / "perfiles.toml"),
        targets,
        replicas=3,
        days=5,
        warmup_days=1,
        seed=2026,
    )
    means = {r.target.name: r.mean for r in summarize_targets(replicas, targets)}

    assert means == pytest.approx(
        {
            "pretriaje_medio": 10.939513866386463,
            "tiempo_medico_niveles_2_5": 94.5574689541477,
            "tiempo_medico_nivel_3": 24.577156905916294,
            "porcentaje_sobre_manchester": 29.98304318137241,
            "porcentaje_pretriaje_mas_5": 41.77703464589846,
        },
        rel=1e-12,
    )
    assert [r.censored for r in replicas] == [0, 0, 0]


# --- Lo escrito en config/ y en el registro, recalculado (tarea 4.6c) -------------------------
# Cada evaluación anual (12 réplicas de 14 días) tarda unos 25 s. La sensibilidad entera no
# cabe en la suite: se recalculan la plantilla elegida, la vetada y las vecinas del cumplidor.


@pytest.fixture(scope="module")
def inputs():
    arrivals = load_profile(CONFIG / "llegadas.toml")
    return (
        load_center(CONFIG / "centro.toml"),
        arrivals,
        load_profiles(CONFIG / "perfiles.toml"),
        load_targets(CONFIG / "objetivos.toml"),
        window_start_dates(ANNUAL, arrivals),
    )


def evaluate(inputs, knob, staffs, seed):
    """Las plantillas ``staffs`` del mando, con la ventana anual y su u de la regla."""
    center, arrivals, profiles, targets, dates = inputs
    loads = (nurse_loads if knob == NURSES else doctor_loads)(
        profiles, arrivals, center.shift_starts
    )
    by_staff = {s.staff: s for s in rule_staffings(loads)}
    return evaluate_staffings(
        center,
        arrivals,
        profiles,
        targets,
        knob,
        [by_staff[staff] for staff in staffs],
        replicas=12,
        days=14,
        warmup_days=2,
        seed=seed,
        start_dates=dates,
    )


def means(row):
    return {r.target.name: r.mean for r in row.results}


@pytest.fixture(scope="module")
def nurses_fit(inputs):
    """[3, 2, 1] (la del centro) y [2, 2, 1] con la semilla de ajuste."""
    return evaluate(inputs, NURSES, [(3, 2, 1), (2, 2, 1)], FIT_SEED)


@pytest.mark.slow
def test_reproduce_la_fila_del_registro_del_centro(nurses_fit):
    # docs/calibracion/registro.md, tarea 4.6c: el centro de config/ con la ventana anual y
    # la semilla 2026 (uv run edsim calibracion evaluar). Los 8 censurados son de enero.
    base = nurses_fit[0]
    assert base.center == load_center(CONFIG / "centro.toml")
    assert means(base) == pytest.approx(
        {
            "pretriaje_medio": 6.775383837987635,
            "tiempo_medico_niveles_2_5": 42.09580955505777,
            "tiempo_medico_nivel_3": 18.76361118983426,
            "porcentaje_sobre_manchester": 16.126272674880855,
            "porcentaje_pretriaje_mas_5": 31.377237247267754,
        },
        rel=1e-12,
    )
    assert [r.censored for r in base.replicas] == [8] + [0] * 11
    assert passes_fit(base, NURSES) and passes_fit(base, DOCTORS)


@pytest.mark.slow
def test_la_semilla_2027_veta_2_2_1_y_queda_3_2_1(inputs, nurses_fit):
    # Con la semilla de ajuste la regla elige [2, 2, 1] (13,21, la más cercana a 12,4);
    # con la de comprobación su pretriaje sale de la horquilla (15,16) y se toma la
    # siguiente, [3, 2, 1], que pasa (7,86).
    assert choose_staffing(nurses_fit, NURSES).staffing.staff == (2, 2, 1)
    checked = {
        r.staffing.staff: r for r in evaluate(inputs, NURSES, [(2, 2, 1), (3, 2, 1)], CHECK_SEED)
    }
    assert means(checked[(2, 2, 1)])["pretriaje_medio"] == pytest.approx(
        15.156119695453697, rel=1e-12
    )
    assert means(checked[(3, 2, 1)])["pretriaje_medio"] == pytest.approx(
        7.85924888158394, rel=1e-12
    )
    chosen = choose_staffing(nurses_fit, NURSES, check=lambda r: checked[r.staffing.staff])
    assert chosen is nurses_fit[0]
    # Los médicos de config/ pasan también con 2027 (43,29): no hay veto de médicos.
    assert means(checked[(3, 2, 1)])["tiempo_medico_niveles_2_5"] == pytest.approx(
        43.290854567363205, rel=1e-12
    )
    assert passes_fit(checked[(3, 2, 1)], DOCTORS)


@pytest.mark.slow
def test_la_comprobacion_independiente_con_2028(inputs):
    (row,) = evaluate(inputs, NURSES, [(3, 2, 1)], CONFIRMATION_SEED)
    assert means(row)["pretriaje_medio"] == pytest.approx(7.755837104447242, rel=1e-12)
    assert means(row)["tiempo_medico_niveles_2_5"] == pytest.approx(41.204916261142074, rel=1e-12)
    assert passes_fit(row, NURSES) and passes_fit(row, DOCTORS)
    assert all(r.censored == 0 for r in row.replicas)


@pytest.mark.slow
def test_el_cumplidor_y_su_siguiente_con_dias_enteros(inputs, centers):
    # [14, 14, 6]: 1/144, 0/144, 2/144 y 6/142 días fuera en los niveles 2 a 5, pasa; la
    # siguiente de la regla (u más alto), [14, 14, 5], tiene 22/142 en el nivel 5 y no.
    compliant, following = evaluate(inputs, DOCTORS, [(14, 14, 6), (14, 14, 5)], FIT_SEED)
    assert compliant.center == centers[1]
    assert compliant.compliance_days[1:] == ((1, 144), (0, 144), (2, 144), (6, 142))
    assert following.compliance_days[4] == (22, 142)
    assert complies(compliant.compliance_days) and not complies(following.compliance_days)
    assert compliant_staffing([compliant, following]) is compliant


@pytest.mark.slow
def test_reproduce_la_fila_corta_anual_del_registro(inputs):
    # docs/calibracion/registro.md, «Fila reproducible» de la tarea 4.6c:
    # uv run edsim calibracion evaluar --dias 5 --calentamiento 1 (12 réplicas, código 1:
    # con 5 días el IC de los niveles 2 a 5 es más ancho que la horquilla).
    center, arrivals, profiles, targets, dates = inputs
    replicas = simulate_replicas(
        center,
        arrivals,
        profiles,
        targets,
        replicas=12,
        days=5,
        warmup_days=1,
        seed=2026,
        start_dates=dates,
    )
    assert {r.target.name: r.mean for r in summarize_targets(replicas, targets)} == pytest.approx(
        {
            "pretriaje_medio": 7.080989099427243,
            "tiempo_medico_niveles_2_5": 58.58413543293185,
            "tiempo_medico_nivel_3": 20.87839135683418,
            "porcentaje_sobre_manchester": 18.11759503873689,
            "porcentaje_pretriaje_mas_5": 31.571442270815748,
        },
        rel=1e-12,
    )
    assert [r.censored for r in replicas] == [0] * 8 + [1] + [0] * 3
