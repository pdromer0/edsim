import dataclasses
from pathlib import Path

import numpy as np
import pytest
from profiles_factory import POPULATION, make_profiles
from scipy import stats

from edsim.arrivals.profile import load_profile
from edsim.profiles.context import ArrivalContext
from edsim.profiles.population import (
    Person,
    age_range,
    draw_person_standard,
    global_band_shares,
    person_from_draws,
    share_65_plus,
)

ARRIVALS = Path(__file__).parent / "data" / "llegadas_ejemplo.toml"
MORNING = ArrivalContext(0, 0, 0)
LAST_U = float(np.nextafter(1.0, 0.0))  # el mayor uniforme de numpy, [0, 1)
N = 20_000
ALPHA = 0.01


def draws(band_gumbels, u_age=0.5, u_sex=0.5, u_mode=0.5) -> np.ndarray:
    return np.array([*band_gumbels, u_age, u_sex, u_mode], dtype=float)


def forced(band: int) -> list[float]:
    """Gumbel draws that make ``band`` win by far."""
    g = [0.0] * 4
    g[band] = 50.0
    return g


@pytest.fixture(scope="module")
def arrivals():
    return load_profile(ARRIVALS)


# --- Edad dentro de la banda ---------------------------------------------------


def test_rangos_de_edad():
    assert [age_range(POPULATION, b) for b in range(4)] == [(15, 44), (45, 64), (65, 79), (80, 99)]


@pytest.mark.parametrize(
    ("band", "low", "high"), [(0, 15, 44), (1, 45, 64), (2, 65, 79), (3, 80, 99)]
)
def test_edad_en_los_bordes(band, low, high):
    # u = 0 da la edad más baja y el mayor u < 1 da el tope, incluido.
    assert person_from_draws(POPULATION, MORNING, draws(forced(band), u_age=0.0)).age == low
    assert person_from_draws(POPULATION, MORNING, draws(forced(band), u_age=LAST_U)).age == high


def test_edad_a_mano():
    # 80 + floor(0,5 × 20) = 90; 15 + floor(0,999 × 30) = 44.
    assert person_from_draws(POPULATION, MORNING, draws(forced(3), u_age=0.5)).age == 90
    assert person_from_draws(POPULATION, MORNING, draws(forced(0), u_age=0.999)).age == 44


def test_edades_uniformes_y_todas_presentes():
    # 20 000 pacientes de 80-99: 1000 por edad. Ninguna edad falta (tampoco el 99)
    # y el chi² contra la uniforme pasa; sin el tope, 99 tendría 0 pacientes.
    rng = np.random.default_rng(2026)
    ages = np.array(
        [
            person_from_draws(POPULATION, MORNING, draws(forced(3), u_age=u)).age
            for u in rng.random(N)
        ]
    )
    counts = np.bincount(ages - 80, minlength=20)

    assert ages.min() == 80 and ages.max() == 99
    assert len(counts) == 20 and (counts > 0).all()
    assert stats.chisquare(counts).pvalue >= ALPHA


# --- Banda, sexo y medio -------------------------------------------------------


def test_banda_con_gumbel_max():
    # Pesos de mañana laborable: 38, 22, 22, 18. Con g = 0 gana la mayor (15-44);
    # con g = [0, 0,6, 0, 0], log 22 + 0,6 = 3,69 > log 38 = 3,64.
    assert person_from_draws(POPULATION, MORNING, draws([0, 0, 0, 0])).band == 0
    assert person_from_draws(POPULATION, MORNING, draws([0, 0.6, 0, 0])).band == 1


@pytest.mark.parametrize(
    ("u", "female"), [(0.0, True), (0.6199, True), (0.62, False), (LAST_U, False)]
)
def test_sexo_a_mano(u, female):
    # 62 % de mujeres en 80-99: mujer si u < 0,62.
    assert person_from_draws(POPULATION, MORNING, draws(forced(3), u_sex=u)).female is female


@pytest.mark.parametrize(("u", "ambulance"), [(0.0, True), (0.3399, True), (0.34, False)])
def test_medio_a_mano(u, ambulance):
    # 34 % de ambulancias en 80-99.
    assert person_from_draws(POPULATION, MORNING, draws(forced(3), u_mode=u)).ambulance is ambulance


def test_porcentajes_extremos():
    p = dataclasses.replace(POPULATION, female_pct=(0, 100, 0, 100), ambulance_pct=(100, 0, 100, 0))

    for u in (0.0, 0.5, LAST_U):
        assert person_from_draws(p, MORNING, draws(forced(0), u_sex=u, u_mode=u)).female is False
        assert person_from_draws(p, MORNING, draws(forced(1), u_sex=u, u_mode=u)).female is True
        assert person_from_draws(p, MORNING, draws(forced(0), u_sex=u, u_mode=u)).ambulance is True
        assert person_from_draws(p, MORNING, draws(forced(1), u_sex=u, u_mode=u)).ambulance is False


def test_banda_con_reparto_cero_no_sale():
    p = dataclasses.replace(POPULATION, band_shares=(38, 22, 0, 18))

    assert person_from_draws(p, MORNING, draws(forced(2))).band != 2


def test_tipos_de_python():
    person = person_from_draws(POPULATION, MORNING, draws(forced(2)))

    # 65 + floor(0,5 × 15) = 72; mujer porque 0,5 < 0,55; propio porque 0,5 ≥ 0,21.
    assert person == Person(band=2, age=72, female=True, ambulance=False)
    assert type(person.band) is int and type(person.age) is int
    assert type(person.female) is bool and type(person.ambulance) is bool


def test_numero_de_sorteos_incorrecto():
    with pytest.raises(ValueError, match="7"):
        person_from_draws(POPULATION, MORNING, np.zeros(6))


# --- Sorteos estándar ----------------------------------------------------------


def test_siete_sorteos_estandar():
    a, b = np.random.default_rng(1), np.random.default_rng(1)

    standard = draw_person_standard(a)

    assert standard.shape == (7,)
    np.testing.assert_array_equal(standard[:4], b.gumbel(size=4))
    np.testing.assert_array_equal(standard[4:], b.random(3))
    assert ((standard[4:] >= 0) & (standard[4:] < 1)).all()


def test_frecuencias_de_sexo_y_medio_por_banda():
    # 20 000 pacientes de cada banda: cada porcentaje dentro de su IC del 99 %
    # (Clopper–Pearson), con Bonferroni entre las 8 proporciones.
    rng = np.random.default_rng(7)
    confidence = 1 - ALPHA / 8
    for band in range(4):
        people = [
            person_from_draws(POPULATION, MORNING, np.concatenate([forced(band), rng.random(3)]))
            for _ in range(N)
        ]
        for field, pct in (
            ("female", POPULATION.female_pct),
            ("ambulance", POPULATION.ambulance_pct),
        ):
            k = sum(getattr(p, field) for p in people)
            ci = stats.binomtest(k, N).proportion_ci(confidence_level=confidence)
            assert ci.low <= pct[band] / 100 <= ci.high, (band, field, k / N)


# --- Reparto global de edad ----------------------------------------------------


def test_reparto_global_de_bandas(arrivals):
    shares = global_band_shares(make_profiles(), arrivals)

    assert shares.sum() == pytest.approx(1, rel=1e-12)
    # Más jóvenes que en mañana laborable (38 %): noche y fin de semana los suben.
    assert shares[0] == pytest.approx(0.4024, abs=5e-4)


def test_mayores_de_65_en_la_horquilla(arrivals):
    # Objetivo: 34-44 % de mayores de 65 años sobre adultos (Gaceta Sanitaria 2018,
    # convertido a adultos). En mañana laborable es el 40 %; en el año, el 38,6 %.
    share = share_65_plus(make_profiles(), arrivals)

    assert share == pytest.approx(0.3855, abs=5e-4)
    assert 0.34 <= share <= 0.44


def test_sin_factores_de_poblacion_el_reparto_es_el_escrito(arrivals):
    flat = dataclasses.replace(
        POPULATION, band_shift_factors=((1, 1, 1),) * 4, band_day_factors=((1, 1),) * 4
    )

    shares = global_band_shares(make_profiles(population=flat), arrivals)

    np.testing.assert_allclose(shares, [0.38, 0.22, 0.22, 0.18], rtol=1e-12)


def test_mayores_de_65_necesita_la_banda_de_65(arrivals):
    other = dataclasses.replace(POPULATION, band_starts=(15, 40, 60, 80))

    with pytest.raises(ValueError, match="65"):
        share_65_plus(make_profiles(population=other), arrivals)
