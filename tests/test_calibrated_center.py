"""Centro base calibrado y centro cumplidor (tarea 4.6b)."""

import dataclasses
from pathlib import Path

import pytest

from edsim.arrivals.profile import load_profile
from edsim.calibration.evaluate import simulate_replicas, summarize_targets
from edsim.calibration.staffing import doctor_loads, equivalent_staff, nurse_loads
from edsim.calibration.targets import load_targets
from edsim.engine.center import load_center
from edsim.profiles.config import load_profiles

CONFIG = Path(__file__).resolve().parents[1] / "config"
DATA = Path(__file__).resolve().parent / "data"

# Los intervalos de u del comentario de config/centro.toml y config/centro_cumplidor.toml.
NURSES_U = (0.795, 0.8325)
DOCTORS_U = (0.81, 0.8475)
COMPLIANT_U = (0.625, 0.635)
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
    assert base.doctors == (12, 11, 5)
    assert base.boxes == 30 and base.results_wait_outside == (4, 5)


def test_el_cumplidor_solo_difiere_en_los_medicos(centers):
    base, compliant = centers
    assert compliant.doctors == (15, 15, 6)
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
