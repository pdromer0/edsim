"""Pruebas por tipo: valores a mano, bordes, ronda y valores exactos sobre la mezcla."""

import dataclasses
import math
from pathlib import Path

import numpy as np
import pytest
from profiles_factory import make_profiles
from scipy import integrate, special

from edsim.arrivals.profile import load_profile
from edsim.lognormal import Z90
from edsim.profiles.config import REASON_KEYS, TEST_TYPES, DiagnosticTest, load_profiles
from edsim.profiles.mixing import global_reason_shares
from edsim.profiles.severity import real_shares
from edsim.profiles.workup import (
    N_WORKUP_DRAWS,
    Workup,
    abnormal_probability,
    draw_workup_standard,
    older_bands,
    order_probability,
    round_turnaround,
    turnaround_from_draw,
    turnaround_shift_factors,
    workup_from_draws,
    workup_model,
)

EXAMPLE = Path(__file__).parent / "data" / "perfiles_ejemplo.toml"
ARRIVALS = Path(__file__).parent / "data" / "llegadas_ejemplo.toml"

# Prueba de la especificación: b = ln OR = 1,2 y c = ln OR_mayor = 0,8 exactos.
SPEC = DiagnosticTest(
    key="analitica",
    turnaround=(60, 150),
    severity_or=math.exp(1.2),
    older_or=math.exp(0.8),
    abnormal_pct=30,
    abnormal_severity_or=2.5,
)


@pytest.fixture(scope="module")
def example():
    return load_profiles(EXAMPLE)


@pytest.fixture(scope="module")
def model(example):
    return workup_model(example, load_profile(ARRIVALS))


# --- Valores a mano ------------------------------------------------------------


def test_logit_de_la_especificacion():
    assert special.logit(0.40) == pytest.approx(-0.4055, abs=5e-5)


@pytest.mark.parametrize(
    ("g", "older", "expected"),
    [(0, False, 40.00), (0, True, 59.74), (1, False, 68.88), (1, True, 83.13)],
)
def test_pedir_a_mano(g, older, expected):
    # logit(0,40) + 1,2·G + 0,8·mayor: −0,4055; 0,3945; 0,7945; 1,5945.
    assert 100 * order_probability(SPEC, 40, g, older) == pytest.approx(expected, abs=5e-3)


@pytest.mark.parametrize(("g", "expected"), [(0, 30.00), (1, 51.72), (2, 72.82)])
def test_alterado_a_mano(g, expected):
    # logit(0,30) + ln(2,5)·G.
    assert 100 * abnormal_probability(SPEC, g) == pytest.approx(expected, abs=5e-3)


def test_mayor_desde_la_banda_de_65(example):
    # 15-44 y 45-64 son adultos; 65-79 y 80-99, mayores.
    assert older_bands(example.population) == (False, False, True, True)


def test_la_banda_de_45_a_64_es_adulta(example):
    # Con G = 0 y un 40 % escrito, la banda 45-64 pide el 40,00 %, no el 59,74 %.
    older = older_bands(example.population)

    assert 100 * order_probability(SPEC, 40, 0, older[1]) == pytest.approx(40.00, abs=5e-3)
    assert 100 * order_probability(SPEC, 40, 0, older[2]) == pytest.approx(59.74, abs=5e-3)


def draws_with(u_order=0.99, u_result=0.99, z=0.0, index=0):
    draws = np.tile([0.99, 0.99, 0.0], 4)
    draws[3 * index : 3 * index + 3] = (u_order, u_result, z)
    return draws


def test_borde_de_pedir_estricto(example):
    # P = 0,40 exactamente (adulto, G = 0, 40 %): u = 0,39 pide, u = 0,40 no.
    tests, pct = example.diagnostic_tests, (40, 40, 40, 40)
    assert order_probability(tests[0], 40, 0.0, False) == 0.40

    assert workup_from_draws(tests, pct, 0.0, False, draws_with(u_order=0.39)).ordered[0]
    assert not workup_from_draws(tests, pct, 0.0, False, draws_with(u_order=0.40)).ordered[0]


def test_borde_de_alterado_estricto(example):
    # P = 0,30 con G = 0 en la analítica: u = 0,29 es alterado, u = 0,30 no.
    tests, pct = example.diagnostic_tests, (40, 40, 40, 40)
    assert abnormal_probability(tests[0], 0.0) == pytest.approx(0.30, abs=1e-15)
    p = abnormal_probability(tests[0], 0.0)

    assert workup_from_draws(tests, pct, 0.0, False, draws_with(u_result=0.29)).abnormal[0]
    assert not workup_from_draws(tests, pct, 0.0, False, draws_with(u_result=p)).abnormal[0]


def test_respuesta_a_mano():
    # [60, 150]: mediana con z = 0 y p90 con z = Z90; con el factor 1,1, 66 y 165.
    assert turnaround_from_draw(SPEC, 0.0) == pytest.approx(60, rel=1e-12)
    assert turnaround_from_draw(SPEC, Z90) == pytest.approx(150, rel=1e-12)
    assert 1.1 * turnaround_from_draw(SPEC, 0.0) == pytest.approx(66, rel=1e-12)
    assert 1.1 * turnaround_from_draw(SPEC, Z90) == pytest.approx(165, rel=1e-12)


def test_media_de_la_respuesta_a_mano():
    # Media de la lognormal: exp(μ + σ²/2) = 77,47; con el factor 1,1, 85,22.
    sigma = math.log(150 / 60) / Z90
    mean = 60 * math.exp(sigma**2 / 2)

    assert mean == pytest.approx(77.47, abs=5e-3)
    assert 1.1 * mean == pytest.approx(85.22, abs=5e-3)
    z = np.random.default_rng(1).standard_normal(20_000)
    sample = np.array([turnaround_from_draw(SPEC, x) for x in z])
    assert sample.mean() == pytest.approx(77.47, rel=0.03)


# --- Ronda ---------------------------------------------------------------------


def test_ronda_a_mano():
    # Analítica (75) y ECG (12) pedidas; imagen (200) no: espera a la analítica.
    ordered, times = (True, False, True, False), (75.0, 40.0, 12.0, 200.0)

    assert round_turnaround(ordered, times) == 75.0


def test_ronda_a_mano_en_la_franja_de_tarde(example):
    # Por la tarde la analítica tarda ×1,1: 82,5. La imagen, ×1,1, no se pidió.
    ordered, times = (True, False, True, False), (75.0, 40.0, 12.0, 200.0)
    factors = turnaround_shift_factors(example, "tarde")

    assert round_turnaround(ordered, times, factors) == pytest.approx(82.5)


def test_sin_pruebas_no_hay_ronda():
    assert round_turnaround((False,) * 4, (75.0, 40.0, 12.0, 200.0)) is None


def test_la_ronda_es_la_maxima_y_no_la_suma():
    assert round_turnaround((True,) * 4, (75.0, 40.0, 12.0, 200.0)) == 200.0


def test_ronda_con_longitudes_incorrectas():
    with pytest.raises(ValueError, match="must have 4 values"):
        round_turnaround((True,) * 3, (1.0,) * 3)


@pytest.mark.parametrize(
    ("band", "expected"),
    [
        ("manana", (1.0, 1.0, 1.0, 1.0)),
        ("tarde", (1.1, 1.0, 1.0, 1.1)),
        ("noche", (0.9, 1.2, 1.0, 1.3)),
        (1, (1.1, 1.0, 1.0, 1.1)),
        (2, (0.9, 1.2, 1.0, 1.3)),
    ],
)
def test_factores_de_la_franja(example, band, expected):
    # En el orden de TEST_TYPES: analítica, radiografía, ECG, imagen.
    assert turnaround_shift_factors(example, band) == expected


@pytest.mark.parametrize("band", ["madrugada", 3, -1, True, 1.0])
def test_franja_no_valida(example, band):
    with pytest.raises(ValueError, match="shift_band"):
        turnaround_shift_factors(example, band)


# --- Sorteos y resultado del paciente ------------------------------------------


def test_doce_sorteos_en_el_orden_de_los_tipos():
    # Por tipo: uniforme de pedir, uniforme de resultado y normal de respuesta.
    a, b = np.random.default_rng(3), np.random.default_rng(3)
    expected = []
    for _ in TEST_TYPES:
        expected += [b.random(), b.random(), b.standard_normal()]

    assert N_WORKUP_DRAWS == 12
    assert draw_workup_standard(a).tolist() == expected
    assert a.random() == b.random()  # nada más consumido


def test_paciente_a_mano(example):
    # Dolor torácico, adulto, G = 0,5: cada tipo con sus sorteos.
    r = example.reason("dolor_toracico")
    draws = np.array([0.5, 0.9, 0.0, 0.9, 0.1, 1.0, 0.2, 0.3, -1.0, 0.04, 0.5, Z90])
    w = workup_from_draws(example.diagnostic_tests, r.test_pct, 0.5, False, draws)

    tests = example.diagnostic_tests
    assert w.ordered == tuple(
        u < order_probability(t, p, 0.5, False)
        for u, t, p in zip(draws[::3], tests, r.test_pct, strict=True)
    )
    # 65 % a G = 0 → 77,2 % con G = 0,5 (OR 3,3): pide con u = 0,5.
    assert w.ordered[0] and not w.ordered[1] and w.ordered[2]
    assert w.abnormal[1] and not w.abnormal[0]
    assert w.turnarounds[0] == pytest.approx(60)
    assert w.turnarounds[3] == pytest.approx(240)
    assert w.draws == tuple(draws)
    assert w.ordered_types == tuple(t for t, o in zip(TEST_TYPES, w.ordered, strict=True) if o)
    assert w.has_round


def test_resultado_y_respuesta_existen_sin_pedir(example):
    # Se sortean siempre, aunque nadie los use: consumo fijo.
    w = workup_from_draws(example.diagnostic_tests, (1, 1, 1, 1), 0.0, False, draws_with())

    assert w.ordered == (False,) * 4
    assert not w.has_round and w.round_turnaround() is None
    assert all(math.isfinite(t) and t > 0 for t in w.turnarounds)
    assert len(w.abnormal) == 4


def test_numero_de_sorteos_incorrecto(example):
    with pytest.raises(ValueError, match="12 values"):
        workup_from_draws(example.diagnostic_tests, (40,) * 4, 0.0, False, np.zeros(11))


def test_workup_inmutable_y_tipos(example):
    w = workup_from_draws(example.diagnostic_tests, (40,) * 4, 0.0, True, draws_with(0.1, 0.1))

    assert all(type(x) is bool for x in (*w.ordered, *w.abnormal))
    assert all(type(x) is float for x in (*w.turnarounds, *w.draws))
    with pytest.raises(dataclasses.FrozenInstanceError):
        w.ordered = (True,) * 4
    assert isinstance(w, Workup)


# --- Valores exactos sobre la mezcla -------------------------------------------


def test_por_motivo_contra_quad(example, model):
    # La disnea, analítica: Σ_b w_b ∫ φ_b(g) P(g, b) dg / Σ_b w_b, con quad.
    m = REASON_KEYS.index("disnea")
    r, test = example.reason("disnea"), example.diagnostic_test("analitica")
    weights, means, sds = (
        x[m] for x in (model.mixture.weights, model.mixture.means, model.mixture.sds)
    )
    older = older_bands(example.population)
    total = 0.0
    for w, mu, sd, o in zip(weights, means, sds, older, strict=True):
        value, _ = integrate.quad(
            lambda g, mu=mu, sd=sd, o=o: (
                math.exp(-0.5 * ((g - mu) / sd) ** 2)
                / (sd * math.sqrt(2 * math.pi))
                * order_probability(test, r.test_pct[0], g, o)
            ),
            -np.inf,
            np.inf,
            epsabs=1e-13,
        )
        total += w * value

    assert model.order_by_reason()[m, 0] == pytest.approx(total / weights.sum(), abs=1e-11)


def test_los_desgloses_promedian_lo_global(example, model):
    arrivals = load_profile(ARRIVALS)
    total = model.order_shares()

    reasons = global_reason_shares(example, arrivals)
    assert reasons @ model.order_by_reason() == pytest.approx(total, abs=1e-12)
    levels = real_shares(model.mixture, example.triage.thresholds)
    assert levels @ model.order_by_true_level() == pytest.approx(total, abs=1e-12)
    assert model.order_by_severity().mean(axis=0) == pytest.approx(total, abs=1e-12)
    assert levels @ model.any_test_by_true_level() == pytest.approx(
        model.any_test_share(), abs=1e-12
    )


def test_quintiles_de_igual_masa(model):
    edges = model.severity_edges()
    _, mass, _ = model.nodes(edges)

    assert mass.sum(axis=(0, 2)) == pytest.approx([0.2] * 5, abs=1e-12)
    assert edges[1:-1] == pytest.approx([0.8128, 0.1796, -0.3202, -0.8435], abs=5e-5)


def test_mas_gravedad_mas_pruebas(model):
    # Del quintil más grave al más leve, cada tipo se pide menos (OR > 1).
    by = model.order_by_severity()

    assert np.all(np.diff(by, axis=0) < 0)
    assert np.all(np.diff(model.abnormal_by_severity(), axis=0) < 0)


def test_infratriaje_del_modelo(model):
    # El mismo infratriaje que la matriz de la tarea 4.3 (10,10 % con los escritos).
    assert 100 * model.undertriage_share() == pytest.approx(10.10, abs=5e-3)


def test_ronda_con_una_sola_prueba(example):
    # Si las otras tres casi nunca se piden, la ronda es la lognormal de la analítica.
    tiny = {k: (40, 1e-6, 1e-6, 1e-6) for k in REASON_KEYS}
    profiles = make_profiles(test_pct=tiny)
    m = workup_model(profiles, load_profile(ARRIVALS))
    sigma = math.log(150 / 60) / Z90

    assert m.round_cdf(60) == pytest.approx(0.5, abs=1e-6)
    assert m.round_cdf(150) == pytest.approx(0.9, abs=1e-6)
    assert m.round_quantile(0.5) == pytest.approx(60, rel=1e-5)
    assert m.round_mean() == pytest.approx(60 * math.exp(sigma**2 / 2), rel=1e-5)
    # Con el factor de la tarde, la mediana pasa a 66.
    assert m.round_quantile(0.5, (1.1, 1.0, 1.0, 1.1)) == pytest.approx(66, rel=1e-5)


def test_ronda_cdf_extremos(model):
    assert model.round_cdf(0) == 0
    assert model.round_cdf(1e-3) == pytest.approx(0, abs=1e-12)
    assert model.round_cdf(1e6) == pytest.approx(1, abs=1e-12)


# Valores exactos del perfil de ejemplo: cualquier cambio en la mezcla, en una
# definición (p. ej. qué banda es «mayor») o en la ronda los mueve.


def test_valores_exactos_del_ejemplo(model):
    assert 100 * model.order_shares() == pytest.approx([48.08, 37.32, 28.09, 13.14], abs=5e-3)
    assert 100 * model.any_test_share() == pytest.approx(72.79, abs=5e-3)
    assert 100 * model.any_test_by_true_level() == pytest.approx(
        [100.0, 98.2, 86.7, 57.1, 26.9], abs=0.05
    )
    assert 100 * model.order_given_undertriage() == pytest.approx(
        [59.81, 39.29, 35.09, 15.86], abs=5e-3
    )
    assert 100 * model.abnormal_among_ordered() == pytest.approx([42.5, 30.1, 30.9, 45.0], abs=0.05)
    assert 100 * model.any_abnormal_given_round() == pytest.approx(46.8, abs=0.05)


def test_ronda_exacta_del_ejemplo(model):
    assert model.round_quantile(0.5) == pytest.approx(57.67, abs=5e-3)
    assert model.round_quantile(0.9) == pytest.approx(161.78, abs=5e-3)
    assert model.round_mean() == pytest.approx(78.20, abs=5e-3)
