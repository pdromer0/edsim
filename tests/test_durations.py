"""Duraciones: lognormal por nivel real y motivo, sorteos y valores exactos de un año."""

import dataclasses
import math
from pathlib import Path

import numpy as np
import pytest
from scipy import integrate

from edsim.arrivals.profile import load_profile
from edsim.lognormal import Z90
from edsim.profiles.config import REASON_KEYS, load_profiles
from edsim.profiles.durations import (
    ASSESSMENT,
    N_DURATION_DRAWS,
    REASSESSMENT,
    PatientDurations,
    draw_durations_standard,
    duration_model,
    duration_params,
    durations_from_draws,
    lognormal_mean,
)
from edsim.profiles.mixing import global_reason_shares
from edsim.profiles.severity import real_shares

EXAMPLE = Path(__file__).parent / "data" / "perfiles_ejemplo.toml"
ARRIVALS = Path(__file__).parent / "data" / "llegadas_ejemplo.toml"
ASSESSMENT_MEANS = (48.87, 37.33, 27.01, 18.66, 12.91)  # por nivel real, sin k
REASSESSMENT_MEANS = (17.36, 14.14, 11.58, 9.02, 6.95)


@pytest.fixture(scope="module")
def example():
    return load_profiles(EXAMPLE)


@pytest.fixture(scope="module")
def model(example):
    return duration_model(example, load_profile(ARRIVALS))


def without_k(profiles):
    return dataclasses.replace(
        profiles,
        reasons=tuple(dataclasses.replace(r, duration_factor=1.0) for r in profiles.reasons),
    )


# --- Valores a mano ------------------------------------------------------------


def test_lognormal_a_mano():
    # [20, 45]: σ = ln(45/20)/Z90 = 0,6328 y media 24,43.
    mu, sigma = duration_params(20, 45)

    assert sigma == pytest.approx(0.6328, abs=5e-5)
    assert lognormal_mean(mu, sigma) == pytest.approx(24.43, abs=5e-3)


def test_factor_sobre_la_mediana_a_mano():
    # k = 1,2: mediana 24, p90 54, media 29,32 y la misma σ.
    mu, sigma = duration_params(20, 45, 1.2)

    assert math.exp(mu) == pytest.approx(24, rel=1e-12)
    assert math.exp(mu + Z90 * sigma) == pytest.approx(54, rel=1e-12)
    assert sigma == duration_params(20, 45)[1]
    assert lognormal_mean(mu, sigma) == pytest.approx(29.32, abs=5e-3)
    assert lognormal_mean(mu, sigma) == pytest.approx(
        1.2 * lognormal_mean(*duration_params(20, 45))
    )


def test_medias_por_nivel_a_mano(example):
    d = example.durations

    for pairs, means in ((d.assessment, ASSESSMENT_MEANS), (d.reassessment, REASSESSMENT_MEANS)):
        assert [lognormal_mean(*duration_params(*p)) for p in pairs] == pytest.approx(
            means, abs=5e-3
        )


def test_medias_con_el_reparto_real(example, model):
    # Con el reparto real exacto (0,39 / 12,52 / 35,82 / 50,62 / 0,65 % desde la tarea
    # 4.6a; 0,42 / 12,46 / 35,81 / 50,65 / 0,65 antes) y k = 1: 24,07 de valoración y
    # 10,60 de reevaluación.
    shares = real_shares(model.workup.mixture, example.triage.thresholds)
    d = example.durations

    assert shares @ [lognormal_mean(*duration_params(*p)) for p in d.assessment] == pytest.approx(
        24.07, abs=5e-3
    )
    assert shares @ [lognormal_mean(*duration_params(*p)) for p in d.reassessment] == pytest.approx(
        10.60, abs=5e-3
    )
    plain = duration_model(without_k(example), load_profile(ARRIVALS))
    assert plain.mean(ASSESSMENT) == pytest.approx(24.070, abs=5e-4)
    assert plain.mean(REASSESSMENT) == pytest.approx(10.596, abs=5e-4)


# --- Sorteos del paciente ------------------------------------------------------


def test_tres_normales_en_orden():
    a, b = np.random.default_rng(9), np.random.default_rng(9)
    expected = [b.standard_normal() for _ in range(3)]

    assert N_DURATION_DRAWS == 3
    assert draw_durations_standard(a).tolist() == expected
    assert a.random() == b.random()


def test_duraciones_a_mano(example):
    # z = 0 da la mediana; z = Z90, el p90. Traumatismo (k = 0,85), nivel real 4:
    # valoración [15, 35] → mediana 12,75; reevaluación [8, 15] → p90 12,75.
    trauma = example.reason("traumatismo")
    d = durations_from_draws(example, trauma, 4, [0.0, 0.0, Z90])

    assert d.triage_time == pytest.approx(5, rel=1e-12)
    assert d.assessment_time == pytest.approx(0.85 * 15, rel=1e-12)
    assert d.reassessment_time == pytest.approx(0.85 * 15, rel=1e-12)
    assert d.draws == (0.0, 0.0, Z90)


def test_el_triaje_no_lleva_factor_y_se_sortea_en_el_nivel_1(example):
    psiq = example.reason("psiquiatrico")  # k = 1,3
    d = durations_from_draws(example, psiq, 1, [Z90, 0.0, 0.0])

    assert d.triage_time == pytest.approx(10, rel=1e-12)
    assert d.assessment_time == pytest.approx(1.3 * 40, rel=1e-12)
    assert d.reassessment_time == pytest.approx(1.3 * 15, rel=1e-12)


def test_duraciones_usan_el_nivel_que_se_pasa(example):
    r = example.reason("otros")
    times = [durations_from_draws(example, r, n, [0, 0, 0]).assessment_time for n in range(1, 6)]

    assert times == pytest.approx([0.9 * m for m in (40, 30, 22, 15, 10)], rel=1e-12)


@pytest.mark.parametrize("level", [0, 6, 2.0])
def test_nivel_no_valido(example, level):
    with pytest.raises(ValueError, match="true_level"):
        durations_from_draws(example, example.reason("otros"), level, [0, 0, 0])


def test_numero_de_sorteos_incorrecto(example):
    with pytest.raises(ValueError, match="3 values"):
        durations_from_draws(example, example.reason("otros"), 3, [0, 0])


def test_tipos_e_inmutable(example):
    d = durations_from_draws(example, example.reason("otros"), 3, np.array([0.1, 0.2, 0.3]))

    assert all(type(x) is float for x in (d.triage_time, d.assessment_time, *d.draws))
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.triage_time = 1.0
    assert isinstance(d, PatientDurations)


# --- Valores exactos -----------------------------------------------------------


@pytest.mark.parametrize("which", [ASSESSMENT, REASSESSMENT])
def test_lo_exacto_usa_los_parametros_del_muestreador(example, model, which):
    # Cada (motivo, nivel real) del modelo exacto tiene la μ y la σ que usa el
    # muestreador (duration_params con su k): lo exacto no da por hecho cómo
    # actúa k. Lo añadió la versión incorrecta V4 de la tarea 4.4, que se veía en
    # los p90 porque σ se tomaba sin k.
    mu, sigma = model.params(which)
    pairs = getattr(example.durations, "assessment" if which == ASSESSMENT else "reassessment")
    for i, r in enumerate(example.reasons):
        for n, pair in enumerate(pairs):
            assert (mu[i, n], sigma[i, n]) == duration_params(*pair, r.duration_factor)


def test_reparto_de_motivo_y_nivel(example, model):
    # Sus filas suman el reparto de motivos del año; sus columnas, el real.
    arrivals = load_profile(ARRIVALS)
    rl = model.reason_level

    assert rl.sum() == pytest.approx(1, abs=1e-12)
    assert rl.sum(axis=1) == pytest.approx(global_reason_shares(example, arrivals), abs=1e-12)
    assert rl.sum(axis=0) == pytest.approx(
        real_shares(model.workup.mixture, example.triage.thresholds), abs=1e-12
    )


@pytest.mark.parametrize("which", [ASSESSMENT, REASSESSMENT])
@pytest.mark.parametrize("level", [1, 3, 5])
def test_media_es_la_integral_de_la_supervivencia(model, which, level):
    # Comprueba la CDF de mezcla contra la media por nivel, por otro camino.
    value, _ = integrate.quad(
        lambda x: 1 - model.cdf(which, x, level=level), 0, np.inf, limit=200, epsabs=1e-9
    )

    assert value == pytest.approx(model.mean_by_level(which)[level - 1], rel=1e-7)


def test_cuantil_y_cdf(model):
    x = model.quantile(ASSESSMENT, 0.9, level=3)

    assert model.cdf(ASSESSMENT, x, level=3) == pytest.approx(0.9, abs=1e-12)
    m = REASON_KEYS.index("traumatismo")
    y = model.quantile(REASSESSMENT, 0.5, reason=m)
    assert model.cdf(REASSESSMENT, y, reason=m) == pytest.approx(0.5, abs=1e-12)


def test_cdf_por_nivel_y_motivo_a_la_vez(model):
    with pytest.raises(ValueError, match="either"):
        model.cdf(ASSESSMENT, 10, level=1, reason=0)
    with pytest.raises(ValueError, match="either"):
        model.cdf(ASSESSMENT, 10)


def test_sin_k_la_razon_es_uno(example):
    load = duration_model(without_k(example), load_profile(ARRIVALS)).physician_load()

    assert load.k_ratio == pytest.approx(1, abs=1e-14)
    assert load.mean_k == pytest.approx(1, abs=1e-14)


def test_la_reevaluacion_solo_cuenta_con_pruebas(example):
    # Con casi ninguna prueba, la reevaluación no carga; con casi todas, carga entera.
    arrivals = load_profile(ARRIVALS)
    few = dataclasses.replace(
        example,
        reasons=tuple(dataclasses.replace(r, test_pct=(1e-6,) * 4) for r in example.reasons),
    )
    nearly_all = dataclasses.replace(
        example,
        reasons=tuple(dataclasses.replace(r, test_pct=(99.9999,) * 4) for r in example.reasons),
    )

    low = duration_model(few, arrivals).physician_load()
    high = duration_model(nearly_all, arrivals).physician_load()
    assert low.reassessment_with_tests < 1e-3
    assert high.reassessment_with_tests == pytest.approx(high.reassessment, rel=1e-6)


# Valores exactos del perfil de ejemplo: la comprobación clínica del plan.


def test_carga_del_medico_del_ejemplo(model):
    load = model.physician_load()

    assert load.assessment == pytest.approx(24.20, abs=5e-3)
    assert load.reassessment == pytest.approx(10.60, abs=5e-3)
    assert load.reassessment_with_tests == pytest.approx(8.18, abs=5e-3)
    assert load.load == pytest.approx(32.37, abs=5e-3)  # 32,38 hasta la tarea 4.6a
    assert load.k_ratio == pytest.approx(1.0053, abs=5e-5)  # 1,0052
    assert load.mean_k == pytest.approx(0.9904, abs=5e-5)  # 0,9905


def test_medias_por_nivel_con_los_k_del_ejemplo(model):
    # Recalculadas en la tarea 4.6a; antes, 50,24 / 40,44 / 27,95 / 17,48 / 12,17 y
    # 17,85 / 15,32 / 11,98 / 8,45 / 6,54.
    assert model.mean_by_level(ASSESSMENT) == pytest.approx(
        [50.06, 40.48, 27.94, 17.48, 12.17], abs=5e-3
    )
    assert model.mean_by_level(REASSESSMENT) == pytest.approx(
        [17.79, 15.33, 11.97, 8.45, 6.54], abs=5e-3
    )


def test_cuantiles_por_nivel_del_ejemplo(model):
    # Recalculados en la tarea 4.6a; antes, (41,07; 92,66), (32,41; 76,03), (22,60; 52,13).
    expected = [(40.93, 92.31), (32.45, 76.11), (22.59, 52.12), (13.92, 33.03), (9.36, 23.67)]
    got = [
        (model.quantile(ASSESSMENT, 0.5, level=n), model.quantile(ASSESSMENT, 0.9, level=n))
        for n in range(1, 6)
    ]

    assert np.array(got) == pytest.approx(np.array(expected), abs=5e-3)
