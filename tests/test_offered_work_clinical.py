"""Carga prevista con los perfiles clínicos (tarea 4.8a).

Cada paciente de la muestra sale del muestreador clínico con el contexto de su instante
de llegada, y la sala de resultados no cuenta como box. Con perfiles neutros (sin
factores de franja, día ni estación, tampoco en la respuesta de las pruebas) y llegadas
planas, la carga por turno es la de ``knob_loads``: el paciente medio del año.
"""

import dataclasses
import math
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest
from clinical_factory import example_profiles, hand_patient, ordered_of

import edsim.runs.offered as offered
from edsim.calibration.staffing import DOCTORS, NURSES, knob_loads
from edsim.engine.validation import draws_sample, flat_profile, offered_load_by_pool
from edsim.profiles.config import load_profiles
from edsim.profiles.context import arrival_context
from edsim.runs import (
    load_center,
    load_profile,
    offered_load,
    offered_work,
    offered_work_from_load,
)

CONFIG = Path(__file__).parents[1] / "config"
DATA = Path(__file__).parent / "data"

KNOB_TOLERANCE = 0.02
"""Relativa, fijada antes de medir. El error de la media muestral de los minutos por
paciente es de un 0,4 % (CV ≈ 0,9 entre 50 000), así que una carga un 4,7 % por debajo
(los 30,84 min del provisional frente a 32,37) queda a unos 6,7 errores típicos del borde
del 2 %: la potencia es prácticamente 1."""


def neutral(profiles):
    """Los perfiles sin factores de franja, día ni estación, en motivos, bandas y pruebas."""
    population = dataclasses.replace(
        profiles.population,
        band_shift_factors=tuple((1.0,) * 3 for _ in profiles.population.band_starts),
        band_day_factors=tuple((1.0,) * 2 for _ in profiles.population.band_starts),
    )
    reasons = tuple(
        dataclasses.replace(
            r, shift_factors=(1.0,) * 3, day_factors=(1.0,) * 2, season_factors=(1.0,) * 4
        )
        for r in profiles.reasons
    )
    tests = tuple(
        dataclasses.replace(t, turnaround_shift_factors=(1.0,) * 3)
        for t in profiles.diagnostic_tests
    )
    return dataclasses.replace(
        profiles, population=population, reasons=reasons, diagnostic_tests=tests
    )


@pytest.fixture(scope="module")
def center():
    return load_center(CONFIG / "centro.toml")


@pytest.fixture(scope="module")
def neutral_profiles():
    return neutral(load_profiles(CONFIG / "perfiles.toml"))


@pytest.fixture(scope="module")
def flat():
    return flat_profile(300)


def shift_loads(work, pool, staff):
    """Carga media de cada turno: la utilización por la plantilla constante del turno."""
    return [u * s for u, s in zip(work.utilization[pool], staff, strict=True)]


@pytest.mark.slow
@pytest.mark.parametrize(
    ("knob", "pool", "staff"),
    [(DOCTORS, "medicos", "doctors"), (NURSES, "enfermeria_triaje", "triage_nurses")],
)
def test_con_perfiles_neutros_la_carga_por_turno_es_la_de_knob_loads(
    center, neutral_profiles, flat, knob, pool, staff
):
    work = offered_work(center, flat, profiles=neutral_profiles)
    expected = knob_loads(knob, neutral_profiles, flat, center.shift_starts)
    observed = shift_loads(work, pool, getattr(center, staff))

    for got, want in zip(observed, expected, strict=True):
        assert got == pytest.approx(want, rel=KNOB_TOLERANCE)


def test_sin_perfiles_la_carga_es_la_de_antes_bit_a_bit(center):
    # Referencia: el cálculo de antes de la tarea 4.8a, escrito aquí con sus funciones.
    profile = load_profile(CONFIG / "llegadas.toml")
    work = offered_work(center, profile, days=2, sample_size=2_000)
    explicit = offered_work(center, profile, days=2, sample_size=2_000, profiles=None)
    draws = draws_sample(center, 2_000, seed=73_001)
    prior = work.prior_days
    previous = dataclasses.replace(profile, start_date=profile.start_date - timedelta(days=prior))
    curves = offered_load_by_pool(previous, draws, horizon=(prior + 2) * 1440)

    for pool in ("medicos", "boxes", "enfermeria_triaje"):
        np.testing.assert_array_equal(work.load[pool], curves[pool][prior * 1440 :])
        np.testing.assert_array_equal(explicit.load[pool], work.load[pool])
    assert explicit.utilization == work.utilization


class HandSampler:
    """Un muestreador espía: el mismo paciente a mano para todos, salvo lo que diga ``draw``."""

    calls: list = []

    def __init__(self, draw):
        self.draw = draw

    def __call__(self, profiles, start_date, center, streams):
        def sample(arrival):
            HandSampler.calls.append((arrival.time, start_date))
            return self.draw(arrival, start_date)

        return sample


def run_with(monkeypatch, center, draw, days=2, sample_size=4_000):
    HandSampler.calls = []
    monkeypatch.setattr(offered, "ClinicalSampler", HandSampler(draw))
    return offered_work(
        center, flat_profile(300), days=days, sample_size=sample_size, profiles=example_profiles()
    )


def test_la_sala_no_cuenta_como_box(monkeypatch, center):
    # Nivel 4: triaje 5, valoración 20, ECG (base 12, sin factor de franja) y reevaluación
    # 10. En el box de 5 a 47 (42 min); con la sala, de 5 a 25 y de 37 a 47 (30 min).
    patient = hand_patient(example_profiles(), level=4, ordered=ordered_of("ecg"))
    lam = 300 / 1440
    with_room = dataclasses.replace(center, results_wait_outside=(4, 5))
    without = dataclasses.replace(center, results_wait_outside=())

    room = run_with(monkeypatch, with_room, lambda a, s: patient)
    plain = run_with(monkeypatch, without, lambda a, s: patient)

    np.testing.assert_allclose(plain.load["boxes"], lam * 42, rtol=1e-9)
    np.testing.assert_allclose(room.load["boxes"], lam * 30, rtol=1e-9)
    # El médico y la enfermera no cambian: 20 + 10 y 5 minutos.
    np.testing.assert_allclose(room.load["medicos"], lam * 30, rtol=1e-9)
    np.testing.assert_allclose(room.load["medicos"], plain.load["medicos"], rtol=1e-12)
    np.testing.assert_allclose(room.load["enfermeria_triaje"], lam * 5, rtol=1e-9)


def test_cada_paciente_lleva_el_contexto_de_su_llegada(monkeypatch, center):
    # De noche la valoración dura 40 min y el resto del día, 20. A las 3:00 todos los que
    # están con el médico llegaron de noche: carga λ·40; a las 12:00, λ·20. Con una mezcla
    # de contextos sin colocar por hora saldría lo mismo a las dos horas.
    starts = example_profiles().shift_band_starts
    night = hand_patient(example_profiles(), level=3, assessment=40.0)
    day = hand_patient(example_profiles(), level=3, assessment=20.0)

    def draw(arrival, start_date):
        band = arrival_context(arrival.time, start_date, starts).shift_band
        return night if band == 2 else day

    work = run_with(monkeypatch, center, draw)
    lam = 300 / 1440

    assert work.load["medicos"][1440 + 3 * 60] == pytest.approx(lam * 40, rel=1e-9)
    assert work.load["medicos"][1440 + 12 * 60] == pytest.approx(lam * 20, rel=1e-9)
    # Los instantes de la muestra cubren la prehistoria y la ventana, desde 7 días antes.
    times = np.array([t for t, _ in HandSampler.calls])
    assert times.min() >= 0 and times.max() < (offered.OFFERED_PRIOR_CAP_DAYS + 2) * 1440
    start = flat_profile(300).start_date - timedelta(days=offered.OFFERED_PRIOR_CAP_DAYS)
    assert {s for _, s in HandSampler.calls} == {start}


def test_una_muestra_demasiado_pequena_es_un_error(center):
    with pytest.raises(ValueError, match="too small"):
        offered_work(center, flat_profile(300), days=1, sample_size=1, profiles=example_profiles())


def test_una_prehistoria_mas_larga_que_el_tope_es_un_error(monkeypatch, center):
    long = hand_patient(example_profiles(), level=3, assessment=8 * 1440.0)

    with pytest.raises(ValueError, match="OFFERED_PRIOR_CAP_DAYS"):
        run_with(monkeypatch, center, lambda a, s: long, sample_size=50)


def test_la_carga_con_perfiles_es_reproducible(center):
    profile = load_profile(DATA / "llegadas_ejemplo.toml")
    first = offered_work(center, profile, days=1, sample_size=3_000, profiles=example_profiles())
    again = offered_work(center, profile, days=1, sample_size=3_000, profiles=example_profiles())

    for pool in ("medicos", "boxes", "enfermeria_triaje"):
        np.testing.assert_array_equal(first.load[pool], again.load[pool])
    assert first.prior_days >= 1 and math.isfinite(first.utilization["medicos"][0])


# --- La carga en dos partes (revisión del PR #51) -------------------------------------
#
# offered_load hace la parte lenta (la muestra y la convolución) y offered_work_from_load
# solo pone la plantilla. Un editor del centro calcula la carga una vez y repite la
# segunda parte con cada plantilla.

POOLS = ("medicos", "boxes", "enfermeria_triaje")


def assert_same_work(a, b):
    """Igualdad bit a bit de dos OfferedWork, campo a campo."""
    assert (a.start_date, a.days, a.prior_days) == (b.start_date, b.days, b.prior_days)
    np.testing.assert_array_equal(a.minutes, b.minutes)
    for pool in POOLS:
        np.testing.assert_array_equal(a.load[pool], b.load[pool])
        np.testing.assert_array_equal(a.capacity[pool], b.capacity[pool])
    assert a.utilization == b.utilization


@pytest.fixture(scope="module")
def short():
    """Llegadas de ejemplo, 2 días y una muestra pequeña: lo que se prueba es el corte."""
    return load_profile(DATA / "llegadas_ejemplo.toml"), {"days": 2, "sample_size": 3_000}


@pytest.mark.parametrize("clinical", [False, True])
def test_offered_work_son_las_dos_partes_seguidas(center, short, clinical):
    profile, options = short
    profiles = example_profiles() if clinical else None

    whole = offered_work(center, profile, profiles=profiles, **options)
    load = offered_load(center, profile, profiles=profiles, **options)

    assert_same_work(whole, offered_work_from_load(center, load))


@pytest.mark.parametrize("clinical", [False, True])
def test_otra_plantilla_reutiliza_la_carga(center, short, clinical):
    profile, options = short
    profiles = example_profiles() if clinical else None
    other = dataclasses.replace(
        center, triage_nurses=(4, 3, 1), doctors=(13, 12, 5), boxes=center.boxes + 6
    )
    load = offered_load(center, profile, profiles=profiles, **options)

    reused = offered_work_from_load(other, load)

    assert_same_work(reused, offered_work(other, profile, profiles=profiles, **options))
    # Guarda: la plantilla cambia de verdad la utilización.
    assert reused.utilization != offered_work_from_load(center, load).utilization


def test_otra_espera_fuera_del_box_da_otra_carga_de_box(center, short):
    profile, options = short
    room = dataclasses.replace(center, results_wait_outside=(4, 5))
    plain = dataclasses.replace(center, results_wait_outside=())

    with_room = offered_load(room, profile, profiles=example_profiles(), **options)
    without = offered_load(plain, profile, profiles=example_profiles(), **options)

    assert with_room.load["boxes"].sum() < without.load["boxes"].sum()
    np.testing.assert_array_equal(with_room.load["medicos"], without.load["medicos"])
    np.testing.assert_array_equal(
        with_room.load["enfermeria_triaje"], without.load["enfermeria_triaje"]
    )
