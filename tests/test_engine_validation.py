"""Validación del motor: M/G/1, Mₜ/G/∞, leyes operacionales y más médicos.

Los tests rápidos comprueban la teoría y las piezas con valores a mano; los slow
ejecutan las comprobaciones estadísticas con semilla fija y miden su potencia con
versiones incorrectas que deben fallar, con menos réplicas que la validación.
"""

import dataclasses
import math
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from edsim.arrivals.profile import ArrivalProfile, load_profile
from edsim.engine.center import load_center
from edsim.engine.clinical import ProvisionalSampler, lognormal_params
from edsim.engine.validation import (
    INFINITE,
    check_mg1,
    flat_profile,
    mg1_center,
    pollaczek_khinchine,
)
from edsim.seeds import child_streams

ROOT = Path(__file__).parent.parent
SEED = 2026


@pytest.fixture(scope="module")
def center():
    return load_center(ROOT / "config" / "centro.toml")


@pytest.fixture(scope="module")
def profile():
    return load_profile(ROOT / "config" / "llegadas.toml")


# --- M/G/1: teoría ------------------------------------------------------------------


def test_perfil_plano():
    p = flat_profile()
    assert p.daily_base == 192
    assert p.daily_cv == 0
    assert set(p.hour_factors) == set(p.weekday_factors) == set(p.month_factors) == {1.0}


def test_centro_mg1(center):
    c = mg1_center(center)
    assert c.triage_nurses == (1, 1, 1)
    assert c.doctors == (INFINITE,) * 3 and c.boxes == INFINITE
    assert c.triage_time == center.triage_time


def test_pollaczek_khinchine_de_la_especificacion(center):
    # Triaje con mediana 5 y p90 10, 8 llegadas por hora (docs/specs/hito-3.md).
    theory = pollaczek_khinchine(mg1_center(center), flat_profile())

    assert theory.lam == 192 / 1440
    assert theory.mean_service == pytest.approx(5.788, abs=5e-4)
    assert theory.second_moment == pytest.approx(44.88, abs=5e-3)
    assert theory.rho == pytest.approx(0.7717, abs=5e-5)
    assert theory.wq == pytest.approx(13.10, abs=5e-3)
    assert theory.lq == pytest.approx(1.747, abs=5e-4)
    assert theory.lq == theory.lam * theory.wq  # Little en la teoría


def test_pollaczek_khinchine_a_mano(center):
    mu, sigma = lognormal_params(*center.triage_time)
    es = math.exp(mu + sigma**2 / 2)
    es2 = math.exp(2 * mu + 2 * sigma**2)
    lam = 192 / 1440
    theory = pollaczek_khinchine(mg1_center(center), flat_profile())
    assert theory.mean_service == pytest.approx(es, rel=1e-15)
    assert theory.second_moment == pytest.approx(es2, rel=1e-15)
    assert theory.wq == pytest.approx(lam * es2 / (2 * (1 - lam * es)), rel=1e-15)


def test_la_teoria_sale_de_la_configuracion(center):
    # Otra mediana de triaje cambia la teoría: no está copiada de la especificación.
    slower = dataclasses.replace(mg1_center(center), triage_time=(6.0, 10.0))
    assert pollaczek_khinchine(slower, flat_profile()).wq > 13.10


@pytest.mark.parametrize(
    "change",
    [
        {"daily_cv": 0.06},
        {"hour_factors": (2,) + (1,) * 23},
        {"weekday_factors": (2,) + (1,) * 6},
        {"month_factors": (2,) + (1,) * 11},
    ],
)
def test_pollaczek_khinchine_exige_perfil_plano(center, change):
    with pytest.raises(ValueError, match="flat"):
        pollaczek_khinchine(center, dataclasses.replace(flat_profile(), **change))


def test_pollaczek_khinchine_exige_una_enfermera(center):
    with pytest.raises(ValueError, match="one triage nurse"):
        pollaczek_khinchine(center, flat_profile())


def test_pollaczek_khinchine_inestable(center):
    busy = flat_profile(daily_base=300)  # ρ = 300/1440 · 5,788 > 1
    with pytest.raises(ValueError, match="unstable"):
        pollaczek_khinchine(mg1_center(center), busy)


def test_check_mg1_argumentos(center):
    with pytest.raises(ValueError, match="replicas"):
        check_mg1(center, replicas=1, seed=SEED)
    with pytest.raises(ValueError, match="warmup_days"):
        check_mg1(center, days=2, warmup_days=2, seed=SEED)


# --- M/G/1: simulación (slow) -------------------------------------------------------------


@pytest.mark.slow
def test_mg1_pasa_con_semilla_fija(center):
    result, replicas = check_mg1(center, seed=SEED)

    assert result.passed, result
    assert [d.name for d in result.details] == ["wq", "rho", "lq"]
    assert all(d.confidence == pytest.approx(1 - 0.01 / 3) for d in result.details)
    assert len(replicas.wq) == 20
    assert replicas.theory.wq == pytest.approx(13.10, abs=5e-3)


def exponential_triage(center):
    """Fábrica de muestreadores con el triaje exponencial de la misma media que la lognormal.

    El resto de sorteos es el del ProvisionalSampler; la exponencial sale de un flujo
    propio (el quinto hijo de la réplica), así que nada más cambia.
    """
    mean = pollaczek_khinchine(mg1_center(center), flat_profile()).mean_service

    def factory(seed):
        streams = child_streams(seed, 6)
        base = ProvisionalSampler(center, streams[1:5])
        rng = np.random.default_rng(streams[5])

        def sampler(arrival):
            return dataclasses.replace(base(arrival), triage_time=float(rng.exponential(mean)))

        return sampler

    return factory


@pytest.mark.slow
def test_potencia_mg1_con_triaje_exponencial(center):
    # Misma media, CV 1 en lugar de 0,57: Wq ≈ 19,6 min frente a 13,10. Con 5 réplicas
    # no basta: la t de 4 grados de libertad al 99,67 % vale 6,25 y el IC de Wq (medido,
    # 9,3-28,6) contiene la teoría. Con 10, t = 3,95 y el IC queda por encima.
    c = mg1_center(center)
    result, replicas = check_mg1(
        center, replicas=10, seed=SEED, sampler_factory=exponential_triage(c)
    )

    assert not result.passed
    wq, rho, _ = result.details
    assert not wq.passed and wq.ci_low > replicas.theory.wq
    assert rho.passed  # la media del servicio es la misma: ρ no lo ve


def test_flat_profile_con_otra_fecha():
    p = flat_profile(daily_base=100, start_date=date(2026, 3, 1))
    assert isinstance(p, ArrivalProfile) and p.start_date == date(2026, 3, 1)
