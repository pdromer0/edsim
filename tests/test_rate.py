from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest
from scipy.integrate import quad

from edsim.arrivals.profile import ArrivalProfile, load_profile
from edsim.arrivals.rate import cumulative_rate, rate

EXAMPLE = Path(__file__).parent / "data" / "llegadas_ejemplo.toml"
DAY = 1440  # minutos

# Valores calculados a mano para el lunes 2026-01-05 (día 0) con el perfil de ejemplo:
# escala = 300/1440 · d_lun · m_ene = 300/1440 · 1,1389 · 1,10/1,000740 = 0,260805 por minuto.
LAMBDA_1130 = 0.43815  # escala · h₁₁ (centro de las 11 h)
LAMBDA_1100 = 0.42563  # escala · (h₁₀ + h₁₁)/2 (entre los centros de las 10 y las 11 h)
CUMULATIVE_DAY = 375.559  # B · d · m
CUMULATIVE_FIRST_HOUR = 10.187  # trapecios de 0:00 a 0:30 y de 0:30 a 1:00


@pytest.fixture(scope="module")
def profile() -> ArrivalProfile:
    return load_profile(EXAMPLE)


def day_scale(profile: ArrivalProfile, day: int) -> float:
    """B/1440 · d · m of a day, computed with datetime, independently of rate.py."""
    when = profile.start_date + timedelta(days=day)
    return (
        profile.daily_base
        / DAY
        * profile.weekday_factors[when.weekday()]
        * profile.month_factors[when.month - 1]
    )


def day_of(profile: ArrivalProfile, when: date) -> int:
    return (when - profile.start_date).days


# --- λ(t) ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("when", "weekday"),
    [(date(2026, 1, 5), 0), (date(2026, 9, 12), 5)],  # lunes de enero, sábado de septiembre
)
def test_centros_de_hora(profile, when, weekday):
    day = day_of(profile, when)
    assert when.weekday() == weekday
    centres = day * DAY + 60 * np.arange(24) + 30

    expected = [day_scale(profile, day) * h for h in profile.hour_factors]

    assert rate(centres, profile) == pytest.approx(expected, rel=1e-12)


def test_valores_a_mano_lunes(profile):
    assert rate(11 * 60 + 30, profile) == pytest.approx(LAMBDA_1130, abs=5e-6)
    assert rate(11 * 60, profile) == pytest.approx(LAMBDA_1100, abs=5e-6)


def test_continuidad_en_cambios_de_hora(profile):
    # Dentro del día, λ no salta en las horas en punto.
    o_clock = 60 * np.arange(1, 24)
    eps = 1e-6

    assert rate(o_clock - eps, profile) == pytest.approx(rate(o_clock + eps, profile), rel=1e-6)


def test_medianoche_enlaza_2330_con_0030(profile):
    # Interpolación periódica: a las 0:00 y justo antes de las 24:00, λ está a medio
    # camino entre el centro de las 23 h y el de las 0 h.
    h = profile.hour_factors
    midnight = day_scale(profile, 0) * (h[23] + h[0]) / 2

    assert rate(0, profile) == pytest.approx(midnight, rel=1e-12)
    assert rate(DAY - 1e-9, profile) == pytest.approx(midnight, rel=1e-9)


def test_cambio_de_dia_a_medianoche(profile):
    # De lunes a martes, la forma horaria es la misma y solo cambia el factor del día.
    d = profile.weekday_factors
    before = rate(DAY - 1e-9, profile)
    after = rate(DAY + 1e-9, profile)

    assert after / before == pytest.approx(d[1] / d[0], rel=1e-9)


# --- Λ(t) ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "when",
    [
        date(2026, 1, 5),  # lunes, día 0
        date(2026, 1, 11),  # domingo
        date(2026, 1, 31),  # último día de enero
        date(2026, 2, 1),  # primero de febrero
        date(2026, 9, 12),  # sábado de septiembre (mes mínimo)
        date(2027, 1, 4),  # lunes del año siguiente
    ],
)
def test_lambda_de_un_dia_es_B_d_m(profile, when):
    day = day_of(profile, when)
    expected = (
        profile.daily_base
        * profile.weekday_factors[when.weekday()]
        * profile.month_factors[when.month - 1]
    )

    area = cumulative_rate((day + 1) * DAY, profile) - cumulative_rate(day * DAY, profile)

    assert area == pytest.approx(expected, rel=1e-12)


def test_lambda_a_mano_lunes(profile):
    assert cumulative_rate(DAY, profile) == pytest.approx(CUMULATIVE_DAY, abs=5e-4)
    assert cumulative_rate(60, profile) == pytest.approx(CUMULATIVE_FIRST_HOUR, abs=5e-4)


def _quad(profile: ArrivalProfile, a: float, b: float) -> float:
    """Integral of λ from a to b with scipy, breaking at the hour centres (the kinks)."""
    first = np.floor(a / 60) * 60 + 30
    kinks = [x for x in np.arange(first, b, 60) if a < x < b]
    value, _ = quad(lambda x: rate(x, profile), a, b, points=kinks or None, limit=200)
    return value


def test_lambda_frente_a_quad(profile):
    # 35 días desde el lunes 5 de enero: cruza a febrero. Se integra día a día,
    # porque λ salta a medianoche.
    for day in range(35):
        start = day * DAY
        exact = cumulative_rate(start + DAY, profile) - cumulative_rate(start, profile)
        assert exact == pytest.approx(_quad(profile, start, start + DAY), rel=1e-9), day

    # Tramos parciales, incluidos los bordes de 0:00 a 0:30 y de 23:30 a 24:00,
    # el lunes, el 31 de enero y el 1 de febrero.
    for day in (0, 26, 27):
        start = day * DAY
        for minute in (17.0, 45.0, 700.5, 1425.0):
            exact = cumulative_rate(start + minute, profile) - cumulative_rate(start, profile)
            assert exact == pytest.approx(_quad(profile, start, start + minute), rel=1e-9)


def test_derivada_de_lambda_es_la_tasa(profile):
    # La pendiente de Λ es λ. Se evita la medianoche, donde λ salta.
    t = np.linspace(0.5, 10 * DAY - 0.5, 997)
    t = t[np.abs(t - DAY * np.round(t / DAY)) > 1]
    delta = 1e-3

    slope = (cumulative_rate(t + delta, profile) - cumulative_rate(t - delta, profile)) / (
        2 * delta
    )

    assert slope == pytest.approx(rate(t, profile), rel=1e-5)


def test_lambda_empieza_en_cero_y_crece(profile):
    t = np.linspace(0, 3 * DAY, 4001)
    values = cumulative_rate(t, profile)

    assert cumulative_rate(0, profile) == 0
    assert np.all(np.diff(values) > 0)


# --- Vectorización y errores ---------------------------------------------------


@pytest.mark.parametrize("function", [rate, cumulative_rate])
def test_vectorizado(profile, function):
    t = np.array([[0.0, 30.0, 659.0], [1440.0, 2000.5, 40_000.0]])

    result = function(t, profile)
    scalar = function(2000.5, profile)

    assert isinstance(result, np.ndarray)
    assert result.shape == t.shape
    assert result == pytest.approx(np.vectorize(lambda x: function(x, profile))(t), rel=1e-15)
    assert type(scalar) is float


@pytest.mark.parametrize("function", [rate, cumulative_rate])
@pytest.mark.parametrize("t", [-1.0, -1e-9, np.nan, np.inf, [10.0, -5.0]])
def test_tiempo_negativo_o_no_finito(profile, function, t):
    with pytest.raises(ValueError, match="t must"):
        function(t, profile)
