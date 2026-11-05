"""Gravedad latente y triaje: valores a mano, exactitud y la tabla de la especificación.

Los valores de referencia de la reproducción se calcularon aparte, con
``scipy.integrate.quad`` sobre G normal estándar (no con ``triage_matrix``), con
el reparto objetivo normalizado (suma 100,1). La tabla anterior de la
especificación era de Monte Carlo con un millón de pacientes: su fila del
nivel 1 (unos 3400 pacientes) tenía alrededor de 0,8 puntos de error.
"""

import dataclasses
import math
from pathlib import Path

import numpy as np
import pytest
from profiles_factory import TRIAGE, make_profiles
from scipy import integrate, stats

from edsim.arrivals.profile import load_profile
from edsim.profiles.config import Severity
from edsim.profiles.severity import (
    CORRECT,
    OVER,
    UNDER,
    SeverityMixture,
    assigned_shares,
    level_of,
    real_shares,
    severity_from_draw,
    severity_mixture,
    thresholds_for,
    thresholds_for_mixture,
    triage_error_for,
    triage_error_rates,
    triage_from_draws,
    triage_matrix,
    triage_quality,
)

ARRIVALS = Path(__file__).parent / "data" / "llegadas_ejemplo.toml"
HAND_THRESHOLDS = (2.0, 1.0, 0.0, -1.0)

# Matriz de nivel real (filas) frente a asignado (columnas), en % de cada fila,
# con G normal estándar, ruido 0,32 y sesgo -0,08 (quad, ver el docstring).
SPEC_MATRIX = np.array(
    [
        [69.08, 30.92, 0.00, 0.00, 0.00],
        [1.30, 76.49, 22.21, 0.01, 0.00],
        [0.00, 6.47, 75.37, 18.17, 0.00],
        [0.00, 0.00, 7.12, 91.50, 1.38],
        [0.00, 0.00, 0.00, 16.77, 83.23],
    ]
)
SPEC_REAL = [0.342, 12.615, 36.085, 50.110, 0.848]  # % de cada nivel real
SPEC_THRESHOLDS = (2.70490, 1.12845, 0.02402, -2.38746)


@pytest.fixture(scope="module")
def arrivals():
    return load_profile(ARRIVALS)


@pytest.fixture(scope="module")
def standard(arrivals) -> SeverityMixture:
    """La mezcla de un año con G normal estándar en todos los motivos."""
    return severity_mixture(make_profiles(), arrivals)


def mixture(weights, means, sds) -> SeverityMixture:
    return SeverityMixture(np.asarray(weights), np.asarray(means), np.asarray(sds))


# --- Valores a mano ------------------------------------------------------------


def test_gravedad_a_mano():
    s = Severity(mean=0.5, sd=0.9, age_shift=(-0.3, 0.0, 0.3, 0.5))

    assert severity_from_draw(s, 3, -1.0) == pytest.approx(0.1, abs=1e-15)  # 0,5 + 0,5 - 0,9
    assert severity_from_draw(s, 0, 2.0) == pytest.approx(2.0, abs=1e-15)  # 0,5 - 0,3 + 1,8
    assert severity_from_draw(s, 1, 0.0) == 0.5


@pytest.mark.parametrize(
    ("x", "level"),
    [
        # Convención: el nivel k es (c_k, c_{k-1}]. «Nivel 1 si supera c1»: un
        # valor justo en un umbral se queda en el nivel menos urgente.
        (2.0, 2),
        (np.nextafter(2.0, math.inf), 1),
        (1.0, 3),
        (np.nextafter(1.0, math.inf), 2),
        (0.0, 4),
        (-1.0, 5),
        (np.nextafter(-1.0, math.inf), 4),
        (10.0, 1),
        (-10.0, 5),
    ],
)
def test_nivel_en_los_bordes(x, level):
    assert level_of(x, HAND_THRESHOLDS) == level


def test_nivel_es_int():
    assert type(level_of(0.5, HAND_THRESHOLDS)) is int


@pytest.mark.parametrize(
    ("g", "z_noise", "assigned", "true"),
    [
        # Valores exactos en binario: sesgo -0,25 y ruido 0,5.
        # ε = -0,25 + 0,5 · 1,5 = 0,5; G + ε = 2,0 justo en c1: nivel 2, como el real.
        (1.5, 1.5, 2, 2),
        # ε = -0,25 + 1,25 = 1,0; G + ε = 2,5: asignado 1, real 2 (sobretriaje).
        (1.5, 2.5, 1, 2),
        # ε = -0,25 - 0,75 = -1,0; G + ε = -0,5: asignado 4, real 3 (infratriaje).
        (0.5, -1.5, 4, 3),
        # G = -1,0 justo en c4: real 5; G + ε = -1,0 + 0,5 = -0,5: asignado 4.
        (-1.0, 1.5, 4, 5),
    ],
)
def test_triaje_a_mano(g, z_noise, assigned, true):
    result = triage_from_draws(g, z_noise, HAND_THRESHOLDS, 0.5, -0.25)

    assert result == (assigned, true)
    assert all(type(x) is int for x in result)


@pytest.mark.parametrize(
    ("assigned", "true", "quality", "jump"),
    [
        (3, 3, CORRECT, 0),
        (4, 2, UNDER, 2),  # asignado menos urgente que el real
        (1, 2, OVER, 1),  # asignado más urgente que el real
        (5, 1, UNDER, 4),
    ],
)
def test_calidad_del_triaje(assigned, true, quality, jump):
    assert triage_quality(assigned, true) == (quality, jump)


def test_nombres_de_la_calidad():
    assert (CORRECT, UNDER, OVER) == ("correcto", "infratriaje", "sobretriaje")


# --- Momentos y repartos a mano ------------------------------------------------


def test_momentos_de_una_mezcla_simetrica():
    m = mixture([0.5, 0.5], [-1.0, 1.0], [1.0, 1.0])

    assert m.mean == pytest.approx(0, abs=1e-15)
    assert m.sd == pytest.approx(math.sqrt(2), rel=1e-15)


def test_momentos_de_una_mezcla_a_mano():
    # Media 0,3 + 1 = 1,3; E[G²] = 0,2·1 + 0,3·(4 + 1) + 0,5·(0,25 + 4) = 3,825;
    # varianza 3,825 - 1,69 = 2,135.
    m = mixture([0.2, 0.3, 0.5], [0.0, 1.0, 2.0], [1.0, 2.0, 0.5])

    assert m.mean == pytest.approx(1.3, rel=1e-15)
    assert m.sd == pytest.approx(math.sqrt(2.135), rel=1e-14)


def test_reparto_asignado_a_mano():
    # G normal estándar, ruido 0,75 y sin sesgo: G + ε es normal de desviación
    # 1,25. Con umbrales 1,25 · (2, 1, 0, -1) el reparto es el de z en (2, 1, 0, -1).
    m = mixture([1.0], [0.0], [1.0])
    shares = assigned_shares(m, tuple(1.25 * z for z in (2, 1, 0, -1)), 0.75, 0.0)

    np.testing.assert_allclose(
        shares, [0.0227501, 0.1359051, 0.3413447, 0.3413447, 0.1586553], atol=1e-7
    )


def test_reparto_real_a_mano():
    m = mixture([1.0], [0.0], [1.0])

    np.testing.assert_allclose(
        real_shares(m, (2, 1, 0, -1)),
        [0.0227501, 0.1359051, 0.3413447, 0.3413447, 0.1586553],
        atol=1e-7,
    )


def test_los_repartos_suman_uno():
    m = mixture([0.2, 0.3, 0.5], [0.0, 1.0, 2.0], [1.0, 2.0, 0.5])

    assert assigned_shares(m, HAND_THRESHOLDS, 0.4, -0.1).sum() == pytest.approx(1, abs=1e-15)
    assert real_shares(m, HAND_THRESHOLDS).sum() == pytest.approx(1, abs=1e-15)


@pytest.mark.parametrize(
    "bad",
    [
        ([0.5, 0.4], [0.0, 1.0], [1.0, 1.0]),  # no suma 1
        ([0.5, 0.5], [0.0, 1.0], [1.0, 0.0]),  # desviación 0
        ([0.5, 0.5], [0.0, 1.0], [1.0]),  # formas distintas
        ([1.5, -0.5], [0.0, 1.0], [1.0, 1.0]),  # peso negativo
    ],
)
def test_mezcla_no_valida(bad):
    with pytest.raises(ValueError):
        mixture(*bad)


# --- Exactitud de la matriz ----------------------------------------------------


def _quad_matrix(mean, sd, thresholds, noise, bias):
    edges = [math.inf, *thresholds, -math.inf]
    m = np.zeros((5, 5))
    for i in range(5):
        lo, hi = max(edges[i + 1], mean - 15 * sd), min(edges[i], mean + 15 * sd)
        for j in range(5):

            def f(g, j=j):
                return stats.norm.pdf(g, mean, sd) * (
                    stats.norm.cdf((edges[j] - g - bias) / noise)
                    - stats.norm.cdf((edges[j + 1] - g - bias) / noise)
                )

            m[i, j] = integrate.quad(f, lo, hi, epsabs=1e-14, epsrel=1e-12, limit=400)[0]
    return m


@pytest.mark.parametrize(
    ("mean", "sd"),
    [
        (0.0, 1.0),
        (0.38, 1.14),  # ancha, como los motivos «variable»
        (2.94, 0.47),  # estrecha y en la cola, como la parada
        (-0.85, 0.57),  # estrecha y baja, como ORL
    ],
)
def test_matriz_contra_quad(mean, sd):
    thresholds = (3.09, 1.15, -0.04, -2.18)
    exact = triage_matrix(mixture([1.0], [mean], [sd]), thresholds, 0.335, -0.082)

    np.testing.assert_allclose(exact, _quad_matrix(mean, sd, thresholds, 0.335, -0.082), atol=1e-11)


def test_filas_y_columnas_de_la_matriz():
    m = mixture([0.2, 0.3, 0.5], [0.0, 1.0, 2.0], [1.0, 2.0, 0.5])
    matrix = triage_matrix(m, HAND_THRESHOLDS, 0.4, -0.1)

    assert matrix.shape == (5, 5)
    assert matrix.sum() == pytest.approx(1, abs=1e-12)
    np.testing.assert_allclose(matrix.sum(axis=1), real_shares(m, HAND_THRESHOLDS), atol=1e-12)
    np.testing.assert_allclose(
        matrix.sum(axis=0), assigned_shares(m, HAND_THRESHOLDS, 0.4, -0.1), atol=1e-12
    )


def test_infra_es_asignado_menos_urgente():
    # Matriz a mano: 0,1 de reales 2 asignados como 3 (infra) y 0,05 de reales 3
    # asignados como 2 (sobre).
    matrix = np.zeros((5, 5))
    matrix[1, 2], matrix[2, 1], matrix[2, 2] = 0.1, 0.05, 0.85

    assert triage_error_rates(matrix) == pytest.approx((0.1, 0.05), abs=1e-15)


# --- Reproducción de la especificación -----------------------------------------


def test_mezcla_normal_estandar(standard):
    assert standard.mean == pytest.approx(0, abs=1e-12)
    assert standard.sd == pytest.approx(1, abs=1e-12)


def test_umbrales_dan_el_reparto_asignado(arrivals, standard):
    profiles = make_profiles()
    thresholds = thresholds_for(profiles, arrivals)
    shares = assigned_shares(standard, thresholds, 0.32, -0.08)

    np.testing.assert_allclose(shares, profiles.triage.target_shares, atol=1e-9)
    np.testing.assert_allclose(thresholds, SPEC_THRESHOLDS, atol=1e-4)
    assert all(type(c) is float for c in thresholds)


def test_reparto_real_de_la_especificacion(arrivals, standard):
    # El ruido ensancha G + ε: el reparto real es más estrecho que el asignado.
    real = real_shares(standard, thresholds_for(make_profiles(), arrivals))

    np.testing.assert_allclose(100 * real, SPEC_REAL, atol=5e-3)
    assert real[0] < 0.004 and real[4] < 0.014


def test_matriz_de_la_especificacion(arrivals, standard):
    matrix = triage_matrix(standard, thresholds_for(make_profiles(), arrivals), 0.32, -0.08)
    rows = 100 * matrix / matrix.sum(axis=1, keepdims=True)

    np.testing.assert_allclose(rows, SPEC_MATRIX, atol=0.01)
    assert rows[0, 1] == pytest.approx(30.92, abs=0.01)  # nivel 1 real asignado como 2
    assert rows[4, 3] == pytest.approx(16.77, abs=0.01)  # nivel 5 real que sube a 4


def test_infra_y_sobretriaje_de_la_especificacion(arrivals, standard):
    matrix = triage_matrix(standard, thresholds_for(make_profiles(), arrivals), 0.32, -0.08)
    under, over = triage_error_rates(matrix)

    assert 100 * under == pytest.approx(10.1557, abs=1e-3)
    assert 100 * over == pytest.approx(6.2074, abs=1e-3)


def test_sin_sesgo_mas_sobretriaje_que_infratriaje(standard):
    # La especificación: un ruido simétrico sin sesgo daría más sobre que infra.
    target = make_profiles().triage.target_shares
    thresholds = thresholds_for_mixture(standard, target, 0.32, 0.0)
    under, over = triage_error_rates(triage_matrix(standard, thresholds, 0.32, 0.0))

    assert over > under


# --- Calibración del error -----------------------------------------------------


def test_triage_error_for_recupera_ruido_y_sesgo(arrivals, standard):
    # Con los objetivos que dan 0,32 y -0,08, partiendo de otro punto, la raíz es
    # (0,32; -0,08): la calibración no pasa por quedarse donde empieza.
    thresholds = thresholds_for_mixture(standard, TRIAGE.target_shares, 0.32, -0.08)
    under, over = triage_error_rates(triage_matrix(standard, thresholds, 0.32, -0.08))
    triage = dataclasses.replace(TRIAGE, under_pct=100 * under, over_pct=100 * over)

    noise, bias = triage_error_for(make_profiles(triage=triage), arrivals, start=(0.5, 0.0))

    assert noise == pytest.approx(0.32, abs=1e-8)
    assert bias == pytest.approx(-0.08, abs=1e-8)
    assert type(noise) is float and type(bias) is float


def test_triage_error_for_da_los_objetivos(arrivals, standard):
    # Con los objetivos de Asturias (10,1 y 6,3) sobre G normal estándar.
    profiles = make_profiles()
    noise, bias = triage_error_for(profiles, arrivals)
    thresholds = thresholds_for_mixture(standard, profiles.triage.target_shares, noise, bias)
    under, over = triage_error_rates(triage_matrix(standard, thresholds, noise, bias))

    assert 100 * under == pytest.approx(10.1, abs=1e-8)
    assert 100 * over == pytest.approx(6.3, abs=1e-8)
    assert bias < 0  # el sesgo hacia el infratriaje


def test_triage_error_for_sin_converger(arrivals):
    with pytest.raises(RuntimeError, match="did not converge"):
        triage_error_for(make_profiles(), arrivals, max_evaluations=1)
