"""El centro base calibrado del hito 5 (tarea 5.6): config/ y su registro, recalculados.

config/ es el modelo del hito 5 desde la tarea 5.6: la cama (m = 210, p90 = 3 · m), la
paciencia (k = 4 sobre la de partida), 36 boxes (30 + la ley de Little de la espera de cama)
y la plantilla de la 4.6c, que pasa con el modelo nuevo. Ver docs/calibracion/registro.md,
«Tarea 5.6».
"""

import dataclasses
from pathlib import Path

import pytest

from edsim.arrivals.profile import load_profile
from edsim.calibration.evaluate import boxes_waiting_bed, simulate_replicas, summarize_targets
from edsim.calibration.knobs import BED_P90_RATIO, scaled_patience
from edsim.calibration.targets import load_targets
from edsim.calibration.window import ANNUAL, window_start_dates
from edsim.engine.center import load_center
from edsim.profiles.config import load_profiles

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
DATA = ROOT / "tests" / "data"

# Lo elegido en la tarea 5.6, como en los comentarios de config/.
BED_MEDIAN = 210.0
PATIENCE_FACTOR = 4.0
H4_BOXES = 30


@pytest.fixture(scope="module")
def inputs():
    arrivals = load_profile(CONFIG / "llegadas.toml")
    return (
        load_center(CONFIG / "centro.toml"),
        arrivals,
        load_profiles(CONFIG / "perfiles.toml"),
        load_targets(CONFIG / "objetivos.toml"),
    )


def test_el_centro_base_es_el_calibrado(inputs):
    center = inputs[0]
    assert center.bed_wait == (BED_MEDIAN, BED_P90_RATIO * BED_MEDIAN)
    assert center.bed_shift_factors == (0.8, 1.0, 1.5)
    assert center.boxes == 36
    # La plantilla de la 4.6c no cambia: con el modelo nuevo, sus objetivos pasan.
    assert (center.triage_nurses, center.doctors) == ((3, 2, 1), (12, 11, 4))
    assert center.results_wait_outside == (4, 5)


def test_la_paciencia_es_la_de_partida_por_k(inputs):
    # perfiles_h5_ejemplo.toml es el bloque de partida sobre los perfiles del hito 4, que
    # config/ comparte valor a valor: config/ es ese ejemplo con la paciencia por k = 4.
    profiles = inputs[2]
    start = load_profiles(DATA / "perfiles_h5_ejemplo.toml")
    assert profiles == scaled_patience(start, PATIENCE_FACTOR)
    # La mediana del nivel 4 es de 600 min y la del 5 de 480 (la discrepancia del registro).
    assert profiles.outcome.abandonment.patience[3] == (600.0, 1800.0)
    assert profiles.outcome.abandonment.patience[4] == (480.0, 1440.0)


def test_el_cumplidor_solo_difiere_en_los_medicos(inputs):
    base = inputs[0]
    compliant = load_center(CONFIG / "centro_cumplidor.toml")
    assert dataclasses.replace(compliant, doctors=base.doctors) == base


@pytest.mark.slow
def test_reproduce_la_fila_anual_del_registro_y_los_boxes_por_little(inputs):
    # docs/calibracion/registro.md, tarea 5.6: config/ con la ventana anual y la semilla
    # 2026 (unos 30 s). Los boxes son los 30 del hito 4 más λ · W redondeado: 6,44 → 36.
    center, arrivals, profiles, targets = inputs
    replicas = simulate_replicas(
        center,
        arrivals,
        profiles,
        targets,
        replicas=12,
        days=14,
        warmup_days=2,
        seed=2026,
        start_dates=window_start_dates(ANNUAL, arrivals),
    )
    means = {r.target.name: r.mean for r in summarize_targets(replicas, targets)}

    assert means == pytest.approx(
        {
            "pretriaje_medio": 6.731171066934777,
            "tiempo_medico_niveles_2_5": 35.307242606141834,
            "tiempo_medico_nivel_3": 18.78788717653041,
            "porcentaje_sobre_manchester": 16.083366661005623,
            "porcentaje_pretriaje_mas_5": 31.35300221433774,
            "abandono": 1.6775801934649364,
            "estancia_ingresados": 479.90435164309457,
            "ingresados_mas_4h": 78.69863346138129,
            "estancia_atendidos": 164.42680410986495,
            "ingreso_observado": 9.751136652738877,
        },
        rel=1e-12,
    )
    little = boxes_waiting_bed(replicas)
    assert little == pytest.approx(6.44, abs=0.005)
    assert center.boxes == H4_BOXES + round(little)


@pytest.mark.slow
def test_reproduce_la_fila_corta_del_registro(inputs):
    # La «Fila reproducible» de la tarea 5.6: calibracion evaluar --dias 5 --calentamiento 1
    # (12 réplicas de la ventana anual; unos 12 s).
    center, arrivals, profiles, targets = inputs
    replicas = simulate_replicas(
        center,
        arrivals,
        profiles,
        targets,
        replicas=12,
        days=5,
        warmup_days=1,
        seed=2026,
        start_dates=window_start_dates(ANNUAL, arrivals),
    )
    means = {r.target.name: r.mean for r in summarize_targets(replicas, targets)}

    assert means["abandono"] == pytest.approx(2.1112205650309526, rel=1e-12)
    assert means["estancia_ingresados"] == pytest.approx(476.42323944741884, rel=1e-12)
    assert means["tiempo_medico_niveles_2_5"] == pytest.approx(37.69523072025964, rel=1e-12)
    assert sum(r.left for r in replicas) == 313
    assert sum(r.censored_admitted for r in replicas) == 1
