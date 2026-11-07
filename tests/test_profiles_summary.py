"""Resumen exacto de los perfiles clínicos (tarea 4.8a).

``summarize_profiles`` da lo que se espera de un año de pacientes: motivos, niveles
asignados y reales, infra y sobretriaje, pruebas y carga del médico. Con ``config/`` se
compara con los valores a mano de la especificación; con un perfil hecho a mano, con un
cálculo independiente (Φ y ``quad``) en lugar de las funciones exactas de ``profiles/``.
"""

import dataclasses
import math

import pytest
from profiles_factory import DIAGNOSTIC_TESTS, DURATIONS, TRIAGE, make_profiles
from scipy import integrate
from scipy.stats import norm

from edsim.arrivals.profile import load_profile
from edsim.profiles.config import REASONS, TEST_TYPES, load_profiles
from edsim.runs import summarize_profiles

TOLERANCE = 1e-4
"""En puntos porcentuales (y en minutos para la carga), fijada antes de medir."""

Z90 = 1.2815515655446004


@pytest.fixture(scope="module")
def config_summary():
    return summarize_profiles(
        load_profiles("config/perfiles.toml"), load_profile("config/llegadas.toml")
    )


def test_niveles_asignados_y_reales_con_config(config_summary):
    assigned = (0.3998, 12.0960, 33.5610, 52.5431, 1.4002)
    true = (0.3881, 12.5147, 35.8221, 50.6227, 0.6524)

    assert config_summary.assigned_level_percentages == pytest.approx(assigned, abs=TOLERANCE)
    assert config_summary.true_level_percentages == pytest.approx(true, abs=TOLERANCE)
    # Los literales son los valores a mano de la especificación, con dos decimales más.
    assert [round(x, 2) for x in assigned] == [0.40, 12.10, 33.56, 52.54, 1.40]
    assert [round(x, 2) for x in true] == [0.39, 12.51, 35.82, 50.62, 0.65]
    assert sum(config_summary.assigned_level_percentages) == pytest.approx(100)


def test_infra_y_sobretriaje_con_config(config_summary):
    assert config_summary.undertriage_percentage == pytest.approx(10.1005, abs=TOLERANCE)
    assert config_summary.overtriage_percentage == pytest.approx(6.2896, abs=TOLERANCE)
    assert (round(10.1005, 2), round(6.2896, 2)) == (10.10, 6.29)


def test_pruebas_y_carga_del_medico_con_config(config_summary):
    assert config_summary.any_test_percentage == pytest.approx(72.7472, abs=TOLERANCE)
    assert list(config_summary.test_percentages) == list(TEST_TYPES)
    assert config_summary.assessment_minutes == pytest.approx(24.1966, abs=TOLERANCE)
    assert config_summary.reassessment_minutes == pytest.approx(8.1761, abs=TOLERANCE)
    assert config_summary.physician_minutes == pytest.approx(32.3727, abs=TOLERANCE)
    assert config_summary.physician_minutes == pytest.approx(
        config_summary.assessment_minutes + config_summary.reassessment_minutes
    )
    assert (round(72.7472, 2), round(24.1966, 2), round(8.1761, 2)) == (72.75, 24.20, 8.18)


def test_motivos_con_config(config_summary):
    shares = config_summary.reason_percentages

    assert list(shares) == [key for key, _, _ in REASONS]
    assert sum(shares.values()) == pytest.approx(100)
    assert shares["traumatismo"] == pytest.approx(20.1412, abs=TOLERANCE)
    assert shares["parada"] == pytest.approx(0.3022, abs=TOLERANCE)


# --- Un perfil hecho a mano -----------------------------------------------------------
#
# Gravedad normal estándar en todos los motivos y sin ajuste por edad, el 40 % de cada
# prueba en todos los motivos y sin odds ratio de los mayores: el motivo y la edad no
# cambian nada, como si hubiera un solo motivo. La validación exige pesos base positivos,
# así que los 17 motivos siguen ahí, con su peso del catálogo y sin factores.


@pytest.fixture(scope="module")
def hand():
    tests = tuple(dataclasses.replace(t, older_or=1.0) for t in DIAGNOSTIC_TESTS)
    profiles = make_profiles(diagnostic_tests=tests)
    return profiles, summarize_profiles(profiles, load_profile("tests/data/llegadas_ejemplo.toml"))


def _edges():
    return (math.inf, *TRIAGE.thresholds, -math.inf)


def _order(test, g):
    """P(pedir | G = g) = logística(logit(0,40) + ln(OR_gravedad)·g)."""
    x = math.log(0.40 / 0.60) + math.log(test.severity_or) * g
    return 1 / (1 + math.exp(-x))


def _any_test(g):
    return 1 - math.prod(1 - _order(t, g) for t in DIAGNOSTIC_TESTS)


def _mean(median, p90):
    sigma = (math.log(p90) - math.log(median)) / Z90
    return median * math.exp(sigma**2 / 2)


def test_motivos_del_perfil_a_mano(hand):
    _, summary = hand
    total = sum(weight for _, _, weight in REASONS)

    for key, _, weight in REASONS:
        assert summary.reason_percentages[key] == pytest.approx(100 * weight / total, abs=1e-9)


def test_niveles_del_perfil_a_mano(hand):
    _, summary = hand
    edges = _edges()
    # Real: G normal estándar; asignado: G + ε, con ε normal de media sesgo y dt ruido.
    spread = math.hypot(1, TRIAGE.noise)
    true = [100 * (norm.cdf(edges[k]) - norm.cdf(edges[k + 1])) for k in range(5)]
    assigned = [
        100
        * (norm.cdf(edges[k], TRIAGE.bias, spread) - norm.cdf(edges[k + 1], TRIAGE.bias, spread))
        for k in range(5)
    ]

    assert summary.true_level_percentages == pytest.approx(true, abs=TOLERANCE)
    assert summary.assigned_level_percentages == pytest.approx(assigned, abs=TOLERANCE)


def test_infra_y_sobretriaje_del_perfil_a_mano(hand):
    _, summary = hand
    edges = _edges()

    def less_urgent(g, k):
        # Nivel real k + 1 (índice k): asignado por debajo del borde inferior de su franja.
        return norm.cdf((edges[k + 1] - g - TRIAGE.bias) / TRIAGE.noise)

    def more_urgent(g, k):
        return norm.sf((edges[k] - g - TRIAGE.bias) / TRIAGE.noise)

    def mass(f):
        return 100 * sum(
            integrate.quad(
                lambda g, k=k: norm.pdf(g) * f(g, k), max(edges[k + 1], -10), min(edges[k], 10)
            )[0]
            for k in range(5)
        )

    assert summary.undertriage_percentage == pytest.approx(mass(less_urgent), abs=TOLERANCE)
    assert summary.overtriage_percentage == pytest.approx(mass(more_urgent), abs=TOLERANCE)


def test_pruebas_y_carga_del_perfil_a_mano(hand):
    _, summary = hand
    edges = _edges()

    def expected(f, low=-10, high=10):
        return integrate.quad(lambda g: norm.pdf(g) * f(g), low, high)[0]

    for test in DIAGNOSTIC_TESTS:
        assert summary.test_percentages[test.key] == pytest.approx(
            100 * expected(lambda g, t=test: _order(t, g)), abs=TOLERANCE
        )
    assert summary.any_test_percentage == pytest.approx(100 * expected(_any_test), abs=TOLERANCE)
    # Valoración por nivel real y reevaluación solo con alguna prueba, sin factores k.
    assessment = reassessment = 0.0
    for k in range(5):
        low, high = max(edges[k + 1], -10), min(edges[k], 10)
        share = norm.cdf(high) - norm.cdf(low)
        assessment += share * _mean(*DURATIONS.assessment[k])
        reassessment += expected(_any_test, low, high) * _mean(*DURATIONS.reassessment[k])
    assert summary.assessment_minutes == pytest.approx(assessment, abs=TOLERANCE)
    assert summary.reassessment_minutes == pytest.approx(reassessment, abs=TOLERANCE)
    assert summary.physician_minutes == pytest.approx(assessment + reassessment, abs=TOLERANCE)
