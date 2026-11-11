"""Las funciones exactas del desenlace del hito 5 (``profiles/outcome.py``) contra valores a mano.

Paciencia, destinos y espera de cama con los valores de las piezas 1 a 3 de
docs/specs/hito-5.md, cada uno con su cálculo en el plan de la tarea 5.2. Las referencias
no usan la función probada: aritmética, ``statistics.NormalDist`` y bucles a mano.
"""

import math
from dataclasses import replace
from datetime import date
from itertools import product
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pytest

from edsim.arrivals.profile import load_profile
from edsim.engine.clinical import BedWaitFactors, OutcomeDraws
from edsim.profiles.config import (
    REASON_KEYS,
    Abandonment,
    DestinationOdds,
    OutcomeProfile,
    load_profiles,
)
from edsim.profiles.outcome import (
    abnormal_count_distribution,
    bed_wait_from_draw,
    bed_wait_mean,
    destination_from_draws,
    destination_log_odds,
    destination_probabilities,
    outcome_model,
    patience_cdf,
    patience_from_draw,
    patience_quantile,
)

DATA = Path(__file__).parent / "data"
Z90 = NormalDist().inv_cdf(0.9)

# Las piezas 1 y 2 de la especificación: paciencia del nivel 5 [120, 360] y factor 0,8
# en la banda de 15 a 44 años; destinos con bases 6 / 0,5 / 0,05 %, odds ratios de G de
# 3, 2 y 6, y 1,5 por prueba alterada y 2 para los mayores en el ingreso.
ABANDONMENT = Abandonment(
    ((1440, 4320), (480, 1440), (240, 720), (150, 450), (120, 360)), (0.8, 1.0, 1.0, 1.0)
)
PIECE_2 = OutcomeProfile(
    ABANDONMENT,
    DestinationOdds("ingreso", 9.90, 3.0, older_or=2.0, abnormal_or=1.5),
    DestinationOdds("traslado", 0.75, 2.0, base=0.5),
    DestinationOdds("exitus", 0.11, 6.0, base=0.05),
)


# Paciencia (pieza 1).


@pytest.mark.parametrize(
    ("band", "minutes", "expected"),
    [
        (1, 60, 0.20938),  # Φ(ln(60/120) / σ), σ = ln 3 / z90 = 0,85725
        (1, 120, 0.5),
        (1, 240, 0.79062),
        (0, 60, 0.29175),  # con el factor 0,8 la mediana es 96: Φ(ln(60/96) / σ)
    ],
)
def test_paciencia_a_mano(band, minutes, expected):
    assert patience_cdf(ABANDONMENT, 5, band, minutes) == pytest.approx(expected, abs=5e-6)


def test_paciencia_cuantil_y_sorteo():
    # La mediana del nivel 5 en la banda 15-44 es 0,8 · 120 = 96; el p90, 0,8 · 360 = 288.
    assert patience_quantile(ABANDONMENT, 5, 0, 0.5) == pytest.approx(96)
    assert patience_quantile(ABANDONMENT, 5, 0, 0.9) == pytest.approx(288)
    assert patience_from_draw(ABANDONMENT, 5, 0, 0.0) == pytest.approx(96)
    assert patience_from_draw(ABANDONMENT, 5, 1, Z90) == pytest.approx(360)
    assert patience_from_draw(ABANDONMENT, 1, 3, 0.0) == pytest.approx(1440)
    assert patience_cdf(ABANDONMENT, 5, 1, 0) == 0.0


def test_cuantos_aguantan_una_dos_y_cuatro_horas():
    # 1 − Φ(ln(x / mediana) / σ) por nivel real, sin el factor de edad (nota 7 del issue #69).
    expected = {
        1: (100.0, 99.8, 98.2),
        2: (99.2, 94.7, 79.1),
        3: (94.7, 79.1, 50.0),
        4: (85.7, 60.3, 29.2),
        5: (79.1, 50.0, 20.9),
    }
    for level, values in expected.items():
        got = [100 * (1 - patience_cdf(ABANDONMENT, level, 1, x)) for x in (60, 120, 240)]
        assert got == pytest.approx(values, abs=0.05)


# Destinos (pieza 2).


@pytest.mark.parametrize(
    ("older", "g", "k", "expected"),
    [
        (0, 0, 0, (93.45, 6.00, 0.50, 0.05)),
        (0, 1, 0, (82.88, 15.96, 0.89, 0.27)),
        (0, 2, 0, (61.79, 35.70, 1.32, 1.19)),
        (0, 1, 2, (69.09, 29.94, 0.74, 0.22)),
        (1, 1, 0, (71.47, 27.53, 0.76, 0.23)),
        (1, 1, 2, (53.17, 46.09, 0.57, 0.17)),
    ],
    ids=["adulto-G0", "adulto-G1", "adulto-G2", "adulto-G1-2alt", "mayor-G1", "mayor-G1-2alt"],
)
def test_las_seis_filas_de_la_pieza_2(older, g, k, expected):
    probabilities = destination_probabilities(PIECE_2, 6.0, older, g, k)
    assert 100 * probabilities == pytest.approx(expected, abs=0.005)
    assert probabilities.sum() == pytest.approx(1)


def test_log_odds_a_mano():
    # G = 1: ln(6 / 93,45) + ln 3 = −1,6471; ln(0,5 / 93,45) + ln 2 = −4,5374;
    # ln(0,05 / 93,45) + ln 6 = −5,7414.
    assert destination_log_odds(PIECE_2, 6.0, 0, 1, 0) == pytest.approx(
        (0, -1.6471, -4.5374, -5.7414), abs=5e-5
    )


def test_gumbel_max_a_mano():
    gumbels = (0.10, 1.90, 0.50, 0.20)
    # G = 1: sumas (0,10; 0,2529; −4,0374; −5,5414): ingresa.
    assert destination_from_draws(PIECE_2, 6.0, False, 1.0, 0, gumbels) == "ingreso"
    # G = 0: el ingreso vale −2,7457 + 1,90 = −0,8457 < 0,10: alta.
    assert destination_from_draws(PIECE_2, 6.0, False, 0.0, 0, gumbels) == "alta"


def test_las_probabilidades_son_las_frecuencias_del_gumbel_max():
    # Las odds de Gumbel-max son las de la logística: con 200.000 sorteos, a 4 desviaciones.
    rng = np.random.default_rng(5)
    draws = rng.gumbel(size=(200_000, 4))
    logs = destination_log_odds(PIECE_2, 6.0, 1, 1.5, 1)
    observed = np.bincount(np.argmax(logs + draws, axis=1), minlength=4) / len(draws)
    expected = destination_probabilities(PIECE_2, 6.0, 1, 1.5, 1)
    assert (np.abs(observed - expected) < 4 * np.sqrt(expected / len(draws))).all()


def test_g_negativa_baja_las_odds():
    # 0 es el adulto medio: con G = −1, OR^G < 1 y todos los destinos salvo el alta bajan.
    at_0 = destination_probabilities(PIECE_2, 6.0, 0, 0, 0)
    at_minus_1 = destination_probabilities(PIECE_2, 6.0, 0, -1, 0)
    assert (at_minus_1[1:] < at_0[1:]).all() and at_minus_1[0] > at_0[0]


def test_destinos_en_arrays():
    probabilities = destination_probabilities(
        PIECE_2, np.array([6.0, 6.0]), 0, np.array([[0.0], [1.0]]), np.array([0, 2])
    )
    assert probabilities.shape == (2, 2, 4)
    assert 100 * probabilities[1, 1, 1] == pytest.approx(29.94, abs=0.005)


# Espera de cama (pieza 3).


def test_espera_de_cama_a_mano():
    # σ = 0,85725; media = 240 · e^(σ²/2) = 346,57; z = 0 → 240; z = 1,28155 → 720.
    assert bed_wait_mean((240, 720)) == pytest.approx(346.568, abs=5e-4)
    assert bed_wait_from_draw((240, 720), 0.0) == pytest.approx(240)
    assert bed_wait_from_draw((240, 720), Z90) == pytest.approx(720)


def test_espera_de_cama_de_noche_con_el_contrato_del_motor():
    # El minuto 0 son las 0:00, de noche con turnos (8, 15, 22): factor 1,5. 360 y 1.080.
    beds = BedWaitFactors(date(2026, 1, 1), (8, 15, 22), (0.8, 1.0, 1.5))
    for z, expected in ((0.0, 360), (Z90, 1080)):
        draws = OutcomeDraws(30.0, "ingreso", bed_wait_from_draw((240, 720), z), beds)
        assert draws.bed_wait(0) == pytest.approx(expected)


# Número de pruebas alteradas (Poisson-binomial).


def test_poisson_binomial_a_mano():
    # q = (0,5; 0,2; 0,1; 0): P0 = 0,36, P1 = 0,49, P2 = 0,14, P3 = 0,01, P4 = 0.
    assert abnormal_count_distribution([0.5, 0.2, 0.1, 0.0]) == pytest.approx(
        (0.36, 0.49, 0.14, 0.01, 0.0)
    )


def test_poisson_binomial_contra_la_enumeracion():
    # Las 16 combinaciones de las cuatro Bernoulli, una a una.
    q = (0.3, 0.7, 0.15, 0.55)
    expected = [0.0] * 5
    for outcome in product((0, 1), repeat=4):
        p = math.prod(qt if o else 1 - qt for qt, o in zip(q, outcome, strict=True))
        expected[sum(outcome)] += p
    assert abnormal_count_distribution(q) == pytest.approx(expected)
    assert abnormal_count_distribution(np.array([q, q])).shape == (2, 5)


def test_poisson_binomial_pide_cuatro():
    with pytest.raises(ValueError, match="4 values on its last axis"):
        abnormal_count_distribution([0.5, 0.5])


# El modelo exacto del año.


@pytest.fixture(scope="module")
def model():
    profiles = load_profiles(DATA / "perfiles_ejemplo.toml")
    reasons = tuple(replace(r, admission_pct=5.0) for r in profiles.reasons)
    profiles = replace(profiles, reasons=reasons, outcome=PIECE_2)
    return outcome_model(profiles, load_profile(DATA / "llegadas_ejemplo.toml"))


def test_el_modelo_pide_el_bloque():
    profiles = load_profiles(DATA / "perfiles_ejemplo.toml")
    with pytest.raises(ValueError, match=r"needs the block \[abandono\], \[destinos\]"):
        outcome_model(profiles, load_profile(DATA / "llegadas_ejemplo.toml"))


def test_el_numero_de_alteradas_del_ano(model):
    # El prototipo del plan (independiente de outcome.py): 66,066 / 24,156 / 7,729 / 1,833 /
    # 0,216 % con perfiles_ejemplo y llegadas_ejemplo. No depende de los destinos.
    assert 100 * model.abnormal_count_shares() == pytest.approx(
        (66.066, 24.156, 7.729, 1.833, 0.216), abs=5e-4
    )


def test_las_marginales_cuadran_con_el_ano(model):
    year = model.year_shares()
    assert year.sum() == pytest.approx(1)
    assert model.reason_shares() @ model.by_reason() == pytest.approx(year)
    assert model.abnormal_count_shares() @ model.by_abnormal_count() == pytest.approx(year)
    assert np.full(5, 0.2) @ model.by_severity(5) == pytest.approx(year)
    levels = model.true_level_band_shares()
    assert levels.sum() == pytest.approx(1)
    assert levels.sum(axis=1) @ model.by_true_level() == pytest.approx(year)
    for table in (model.by_reason(), model.by_severity(), model.by_assigned_level()):
        assert table.sum(axis=1) == pytest.approx(1)


def test_el_ingreso_crece_con_la_gravedad_y_las_alteradas(model):
    # Los quintiles van del más grave al más leve; los niveles, del 1 al 5.
    for table in (model.by_severity(), model.by_true_level(), model.by_assigned_level()):
        assert (np.diff(table[:, 1]) < 0).all()
    assert (np.diff(model.by_abnormal_count()[:, 1]) > 0).all()
    assert len(REASON_KEYS) == model.by_reason().shape[0]
