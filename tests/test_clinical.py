import dataclasses
import math
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest
from scipy import stats

from edsim.arrivals.thinning import ArrivalRecord
from edsim.engine.center import CenterConfig, load_center
from edsim.engine.clinical import (
    PatientDraws,
    ProvisionalSampler,
    cumulative_shares,
    lognormal_params,
)
from edsim.seeds import child_streams

EXAMPLE = Path(__file__).parent / "data" / "centro_ejemplo.toml"
SEED = 2026
N = 20_000  # pacientes de las pruebas de frecuencias
N_SMALL = 2_000  # pacientes de las pruebas de reproducibilidad e independencia
ALPHA = 0.01

DURATIONS = ["triage_time", "assessment_time", "reassessment_time", "test_turnaround"]


def streams(seed=SEED) -> list[np.random.SeedSequence]:
    """The four streams of the sampler, as the engine will pass them."""
    return child_streams(seed, 5)[1:]  # el 0 es el de las llegadas


def draw(center: CenterConfig, n: int, seed=SEED) -> list[PatientDraws]:
    sampler = ProvisionalSampler(center, streams(seed))
    return [sampler(ArrivalRecord(k, float(k))) for k in range(n)]


def column(draws: list[PatientDraws], field: str) -> np.ndarray:
    return np.array([getattr(d, field) for d in draws])


@pytest.fixture(scope="module")
def center() -> CenterConfig:
    return load_center(EXAMPLE)


@pytest.fixture(scope="module")
def many(center) -> list[PatientDraws]:
    return draw(center, N)


# --- Parámetros de la lognormal a mano -----------------------------------------


def test_lognormal_triaje_a_mano():
    # mu = ln 5 = 1,60944; sigma = ln(10/5) / 1,28155 = 0,69315 / 1,28155 = 0,54087.
    mu, sigma = lognormal_params(5, 10)

    assert mu == pytest.approx(1.60944, abs=5e-6)
    assert sigma == pytest.approx(0.54087, abs=5e-6)


def test_lognormal_valoracion_a_mano():
    # sigma = ln(45/20) / 1,28155 = 0,81093 / 1,28155 = 0,63277.
    mu, sigma = lognormal_params(20, 45)

    assert mu == pytest.approx(math.log(20), rel=1e-15)
    assert sigma == pytest.approx(0.63277, abs=5e-6)


@pytest.mark.parametrize(("median", "p90"), [(5, 10), (20, 45), (10, 20), (60, 150)])
def test_lognormal_devuelve_mediana_y_p90(median, p90):
    # scipy parametriza la lognormal con s = sigma y scale = exp(mu).
    mu, sigma = lognormal_params(median, p90)
    dist = stats.lognorm(s=sigma, scale=math.exp(mu))

    assert dist.median() == pytest.approx(median, rel=1e-12)
    assert dist.ppf(0.9) == pytest.approx(p90, rel=1e-12)


@pytest.mark.parametrize(("median", "p90"), [(0, 10), (-5, 10), (5, 5), (5, 4)])
def test_lognormal_parametros_no_validos(median, p90):
    with pytest.raises(ValueError):
        lognormal_params(median, p90)


# --- Suma acumulada del reparto ------------------------------------------------


def normalized(shares: list[float]) -> list[float]:
    total = sum(shares)
    return [x / total for x in shares]


def test_acumulada_fuerza_uno_desde_el_ultimo_nivel_con_peso():
    # Con este reparto la suma hasta el nivel 4 da 0,9999999999999999 en coma flotante:
    # si solo se forzara el último valor, u = 0,9999999999999999 elegiría el nivel 5.
    shares = normalized([0.3, 12.1, 33.6, 52.6, 0])
    assert sum(shares[:4]) < 1  # el caso que motiva la función

    cum = cumulative_shares(shares)

    assert cum[3] == 1.0
    assert cum[4] == 1.0


def test_acumulada_un_solo_nivel():
    assert cumulative_shares([0, 0, 1, 0, 0]) == (0.0, 0.0, 1.0, 1.0, 1.0)


def test_acumulada_del_ejemplo(center):
    cum = cumulative_shares(center.level_shares)

    assert cum[-1] == 1.0
    assert cum == pytest.approx((0.003, 0.124, 0.46, 0.986, 1.0), rel=1e-12)
    assert all(a <= b for a, b in pairwise(cum))


@pytest.mark.parametrize(
    ("shares", "first", "last"),
    [
        ([0.3, 12.1, 33.6, 52.6, 0], 1, 4),
        ([0, 12.1, 33.6, 52.6, 1.4], 2, 5),
        ([0, 0, 1, 0, 0], 3, 3),
        ([0, 1, 0, 1, 0], 2, 4),
    ],
)
def test_extremos_del_uniforme_nunca_eligen_nivel_sin_peso(shares, first, last):
    # Los uniformes de numpy están en [0, 1): sus extremos son 0 y nextafter(1, 0).
    cum = cumulative_shares(normalized(shares))
    level = lambda u: int(np.searchsorted(cum, u, side="right")) + 1  # noqa: E731

    assert level(0.0) == first
    assert level(np.nextafter(1.0, 0.0)) == last


# --- Interfaz ------------------------------------------------------------------


def test_tipos_de_python(many):
    # Tipos de Python, no escalares de numpy: igualdad limpia y JSON sin sorpresas.
    d = many[0]

    assert type(d.level) is int
    assert type(d.needs_tests) is bool
    assert type(d.admitted) is bool
    assert all(type(getattr(d, f)) is float for f in DURATIONS)


def test_valores_en_rango(many):
    assert set(column(many, "level")) <= {1, 2, 3, 4, 5}
    assert all((column(many, f) > 0).all() for f in DURATIONS)


def test_inmutable(many):
    with pytest.raises(dataclasses.FrozenInstanceError):
        many[0].level = 1


@pytest.mark.parametrize("n", [3, 5])
def test_numero_de_flujos_incorrecto(center, n):
    with pytest.raises(ValueError, match="4"):
        ProvisionalSampler(center, child_streams(SEED, n))


def test_flujos_que_no_son_seed_sequence(center):
    with pytest.raises(ValueError, match="SeedSequence"):
        ProvisionalSampler(center, [1, 2, 3, 4])


def test_la_llegada_no_cambia_los_sorteos_en_el_hito_3(center):
    # Hoy el muestreador no usa la llegada; en el hito 4 la mezcla de casos dependerá
    # de la hora. Este test fija el comportamiento actual.
    a = ProvisionalSampler(center, streams())
    b = ProvisionalSampler(center, streams())

    for k in range(100):
        assert a(ArrivalRecord(k, float(k))) == b(ArrivalRecord(1000 + k, 5000.0 + 7 * k))


def test_un_solo_nivel(center):
    c = dataclasses.replace(center, level_shares=(0, 0, 1, 0, 0))

    assert set(column(draw(c, N_SMALL), "level")) == {3}


def test_sin_nivel_1(center):
    c = dataclasses.replace(center, level_shares=(0, 12.1, 33.6, 52.6, 1.4))

    assert 1 not in set(column(draw(c, N_SMALL), "level"))


# --- Frecuencias (n = 20 000) --------------------------------------------------


def test_frecuencias_de_nivel(center, many):
    # Esperados: 60, 2420, 6720, 10520 y 280 pacientes; todos muy por encima de 5.
    counts = np.bincount(column(many, "level"), minlength=6)[1:]
    expected = N * np.array(center.level_shares)

    assert stats.chisquare(counts, expected).pvalue >= ALPHA


def proportion_ci(successes: int, n: int, confidence: float) -> tuple[float, float]:
    ci = stats.binomtest(int(successes), n).proportion_ci(confidence_level=confidence)
    return ci.low, ci.high


def test_proporcion_con_pruebas(many):
    # 0,003·0,95 + 0,121·0,85 + 0,336·0,70 + 0,526·0,40 + 0,014·0,20 = 0,5541.
    # El nivel es i.i.d., así que cada indicador es Bernoulli de la mezcla.
    low, high = proportion_ci(column(many, "needs_tests").sum(), N, 1 - ALPHA)

    assert low <= 0.5541 <= high


def test_proporcion_de_ingresos(many):
    # 0,003·0,80 + 0,121·0,45 + 0,336·0,15 + 0,526·0,04 + 0,014·0,01 = 0,12843.
    low, high = proportion_ci(column(many, "admitted").sum(), N, 1 - ALPHA)

    assert low <= 0.12843 <= high


@pytest.mark.parametrize("field", DURATIONS)
@pytest.mark.parametrize(("q", "index"), [(0.5, 0), (0.9, 1)])
def test_mediana_y_p90_empiricos(center, many, field, q, index):
    # Si el cuantil configurado es el verdadero, el número de sorteos por debajo de él
    # es Binomial(N, q). El IC de esa proporción es el IC del cuantil empírico construido
    # con estadísticos de orden. Bonferroni entre las 8 comparaciones. Con N = 20 000,
    # la tolerancia equivale a ±1,6-2,1 % en la mediana y ±2,1-2,8 % en el p90.
    configured = getattr(center, field)[index]
    below = (column(many, field) <= configured).sum()

    low, high = proportion_ci(below, N, 1 - ALPHA / 8)

    assert low <= q <= high


# --- Reproducibilidad ----------------------------------------------------------


def test_misma_semilla_mismos_sorteos(center):
    assert draw(center, N_SMALL) == draw(center, N_SMALL)


def test_semillas_distintas_sorteos_distintos(center):
    a, b = draw(center, N_SMALL, seed=SEED), draw(center, N_SMALL, seed=SEED + 1)

    for field in ["level", *DURATIONS, "needs_tests", "admitted"]:
        assert (column(a, field) != column(b, field)).any(), field


def test_mismo_seed_sequence_dos_veces(center):
    # child_streams no muta el SeedSequence ni default_rng los hijos: pasar el mismo
    # objeto dos veces reproduce los sorteos.
    seq = np.random.SeedSequence(SEED)

    assert draw(center, N_SMALL, seed=seq) == draw(center, N_SMALL, seed=seq)
    assert draw(center, N_SMALL, seed=seq) == draw(center, N_SMALL, seed=SEED)


def test_mismos_cuatro_flujos_en_dos_muestreadores(center):
    four = streams()
    a, b = ProvisionalSampler(center, four), ProvisionalSampler(center, four)
    arrivals = [ArrivalRecord(k, float(k)) for k in range(N_SMALL)]

    assert [a(x) for x in arrivals] == [b(x) for x in arrivals]


# --- Flujos independientes -----------------------------------------------------


def test_otras_probabilidades_de_pruebas_no_cambian_lo_demas(center):
    other = dataclasses.replace(center, test_probability=(0.5, 0.5, 0.5, 0.9, 0.9))
    a, b = draw(center, N_SMALL), draw(other, N_SMALL)

    # El cambio surte efecto: si no, el test pasaría de forma vacía.
    assert (column(a, "needs_tests") != column(b, "needs_tests")).any()
    # El tiempo de respuesta se sortea siempre: tampoco cambia.
    for field in ["level", *DURATIONS, "admitted"]:
        assert (column(a, field) == column(b, field)).all(), field


def test_otro_reparto_no_cambia_duraciones_ni_respuesta(center):
    other = dataclasses.replace(center, level_shares=(5, 20, 30, 30, 15))
    a, b = draw(center, N_SMALL), draw(other, N_SMALL)

    assert (column(a, "level") != column(b, "level")).any()
    for field in DURATIONS:
        assert (column(a, field) == column(b, field)).all(), field
