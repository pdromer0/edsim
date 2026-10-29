from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest
from scipy.integrate import quad

from edsim.arrivals.profile import ArrivalProfile, load_profile
from edsim.arrivals.rate import cumulative_rate, day_scale, day_shape_area, rate, shape

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


def day_scale_reference(profile: ArrivalProfile, day: int) -> float:
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

    expected = [day_scale_reference(profile, day) * h for h in profile.hour_factors]

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
    midnight = day_scale_reference(profile, 0) * (h[23] + h[0]) / 2

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


# --- Escala diaria -------------------------------------------------------------


def test_escala_diaria(profile):
    days = [0, 6, 26, 27, 250, 364]  # lunes, domingo, 31 de enero, 1 de febrero, septiembre, 2027

    assert day_scale(0, profile) == pytest.approx(LAMBDA_1130 / max(profile.hour_factors), abs=1e-5)
    assert type(day_scale(0, profile)) is float
    assert day_scale(np.array(days), profile) == pytest.approx(
        [day_scale_reference(profile, d) for d in days], rel=1e-12
    )


def test_tasa_es_escala_por_forma(profile):
    # El thinning evalúa λ(t) como day_scale · shape(t − inicio del día): debe ser
    # idéntico a rate, bit a bit. Se parte de t, como el thinning: day·1440 + m
    # redondea, y restar después el inicio no devuelve exactamente m.
    for day in (0, 6, 27, 250):
        start = day * DAY
        t = start + np.arange(0, DAY, 0.37)
        thinning_lambda = day_scale(day, profile) * shape(t - start, profile)
        assert np.array_equal(thinning_lambda, rate(t, profile))
    assert type(shape(30.0, profile)) is float
    assert shape(11 * 60 + 30, profile) == pytest.approx(max(profile.hour_factors), rel=1e-15)


def test_tasa_con_z_es_escala_por_z_por_forma(profile):
    # Con Z, el thinning calcula zscale = day_scale · Z una vez al día y λ = zscale · forma:
    # debe ser idéntico, bit a bit, a rate con day_effects.
    effects = np.ones(251)
    effects[[0, 6, 27, 250]] = [1.07, 0.93, 1.2, 0.5]
    for day in (0, 6, 27, 250):
        start = day * DAY
        t = start + np.arange(0, DAY, 0.37)
        zscale = day_scale(day, profile) * effects[day]
        assert np.array_equal(
            zscale * shape(t - start, profile), rate(t, profile, day_effects=effects)
        )


@pytest.mark.parametrize("day", [-1, 1.5, True, [0, -2]])
def test_escala_diaria_dia_invalido(profile, day):
    with pytest.raises(ValueError, match="day must"):
        day_scale(day, profile)


# --- Efecto diario Z ------------------------------------------------------------


def day_area(profile: ArrivalProfile, day: int, **kwargs) -> float:
    return cumulative_rate((day + 1) * DAY, profile, **kwargs) - cumulative_rate(
        day * DAY, profile, **kwargs
    )


def test_area_de_la_forma_en_un_dia(profile):
    # Los factores horarios tienen media 1: el área de la forma en un día es 1440.
    assert day_shape_area(profile) == pytest.approx(DAY, rel=1e-12)
    assert type(day_shape_area(profile)) is float
    for day in (0, 27, 250):
        assert day_area(profile, day) == pytest.approx(
            day_scale(day, profile) * day_shape_area(profile), rel=1e-12
        )


@pytest.mark.parametrize("function", [rate, cumulative_rate])
def test_day_effects_unos_igual_que_sin(profile, function):
    t = np.linspace(0, 5 * DAY - 1e-6, 1001)

    assert np.array_equal(function(t, profile, day_effects=np.ones(5)), function(t, profile))


def test_z2_duplica_lambda_y_el_area_del_dia(profile):
    effects = [1.0, 2.0, 1.0]
    t = np.arange(0, 3 * DAY, 7.3)

    ratio = rate(t, profile, day_effects=effects) / rate(t, profile)
    assert ratio == pytest.approx(np.array(effects)[(t // DAY).astype(int)], rel=1e-15)

    for day, z in enumerate(effects):
        assert day_area(profile, day, day_effects=effects) == pytest.approx(
            z * day_area(profile, day), rel=1e-12
        )
    # Al final, Λ lleva un día 1 más: el área extra del día con Z = 2.
    assert cumulative_rate(3 * DAY, profile, day_effects=effects) == pytest.approx(
        cumulative_rate(3 * DAY, profile) + day_area(profile, 1), rel=1e-12
    )


def test_lambda_al_final_del_horizonte(profile):
    # Λ(n·1440) solo recorre los días 0 a n−1: basta con sus n valores de Z. λ en ese
    # instante ya es del día n y necesita uno más.
    effects = [1.1, 0.9]

    assert cumulative_rate(2 * DAY, profile, day_effects=effects) == pytest.approx(
        1.1 * day_area(profile, 0) + 0.9 * day_area(profile, 1), rel=1e-12
    )
    with pytest.raises(ValueError, match="day_effects"):
        rate(2 * DAY, profile, day_effects=effects)


@pytest.mark.parametrize("function", [rate, cumulative_rate])
@pytest.mark.parametrize(
    "effects",
    [
        [1.0, 1.0],  # no cubre el día 2
        [1.0, 0.0, 1.0],
        [1.0, -1.0, 1.0],
        [1.0, np.nan, 1.0],
        [1.0, np.inf, 1.0],
        [[1.0, 1.0, 1.0]],  # 2-D
    ],
)
def test_day_effects_invalidos(profile, function, effects):
    with pytest.raises(ValueError, match="day_effects"):
        function(2 * DAY + 100, profile, day_effects=effects)


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
