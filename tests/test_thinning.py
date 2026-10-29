import dataclasses
import hashlib
import itertools
import math
import statistics
import time
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest
import simpy
from scipy import stats

from edsim.arrivals import thinning
from edsim.arrivals.profile import ArrivalProfile, load_profile
from edsim.arrivals.rate import cumulative_rate, day_scale, day_shape_area, rate
from edsim.arrivals.thinning import (
    ArrivalRecord,
    DayRecord,
    arrival_source,
    draw_day_effects,
    iter_arrivals,
    simulate_arrivals,
)
from edsim.arrivals.validation import pearson_index

EXAMPLE = Path(__file__).parent / "data" / "llegadas_ejemplo.toml"
DAY = 1440  # minutos
DAYS, SEED = 56, 2026

# Valores calculados a mano para el lunes 2026-01-05 (día 0) con el perfil de ejemplo
# (ver tests/test_rate.py): la cota es escala · máx(h) = 0,260805 · 1,68 = λ(11:30).
BOUND_MONDAY = 0.43815
EXPECTED_MONDAY = 375.559
MAX_H = 1.68  # 24 · 7,0 / 100: el reparto de las 11 h frente a la media
ACCEPTANCE = 1 / MAX_H  # media de λ / cota, igual en todos los días: 0,595

# Efecto diario con el CV del perfil de ejemplo, 0,06: Z ~ Gamma(k = 1/CV², θ = CV²).
CV = 0.06
GAMMA_SHAPE = 277.78  # k = 1 / 0,0036
GAMMA_SCALE = 0.0036  # θ = 0,0036
# Lunes 5 de enero: varianza de la binomial negativa e + CV²·e² frente a la de Poisson, e.
VAR_NB_MONDAY = 883.3
VAR_POISSON_MONDAY = 375.6

# Huella de las llegadas en main (commit e657930, tarea 2.2, antes del efecto diario):
# perfil de ejemplo, 56 días, semilla 2026. Con CV 0, Z = 1 sin sortear y el generador
# debe dar exactamente las mismas llegadas, bit a bit. Solo es legítimo regenerarla si
# se cambia a propósito el orden o el número de los sorteos del flujo de llegadas, y
# explicándolo en el PR; nunca para que un test pase. Para regenerarla, ejecuta
# fingerprint(simulate_arrivals(<perfil de ejemplo con cv_diario = 0>, 56, 2026)[0])
# y copia aquí el número de llegadas y el sha256.
MAIN_ARRIVALS = 18176
MAIN_SHA256 = "75646b4f06e378e72028ae91ef31e81554924170e2ad18029c6c9f613766d441"


def example_with_cv(directory: Path, cv: float) -> ArrivalProfile:
    """The example profile with another cv_diario, loaded from TOML.

    dataclasses.replace would normalize the factors again and change their last
    bit; loading a copy of the file keeps them identical to the example.
    """
    text = EXAMPLE.read_text()
    assert "cv_diario = 0.06\n" in text
    path = directory / f"llegadas_cv_{cv}.toml"
    path.write_text(text.replace("cv_diario = 0.06\n", f"cv_diario = {cv}\n"))
    return load_profile(path)


def fingerprint(arrivals) -> tuple[int, str]:
    """Number of arrivals and sha256 of their times as little-endian float64."""
    times = np.array([a.time for a in arrivals], dtype="<f8")
    return len(arrivals), hashlib.sha256(times.tobytes()).hexdigest()


@pytest.fixture(scope="module")
def profile() -> ArrivalProfile:
    return load_profile(EXAMPLE)


@pytest.fixture(scope="module")
def profile_cv0(tmp_path_factory) -> ArrivalProfile:
    return example_with_cv(tmp_path_factory.mktemp("perfil"), 0)


@pytest.fixture(scope="module")
def run(profile) -> tuple[tuple[ArrivalRecord, ...], tuple[DayRecord, ...]]:
    # Con el CV de 0,06 del perfil de ejemplo: el efecto diario está activo.
    return simulate_arrivals(profile, DAYS, SEED)


@pytest.fixture(scope="module")
def run_cv0(profile_cv0) -> tuple[tuple[ArrivalRecord, ...], tuple[DayRecord, ...]]:
    return simulate_arrivals(profile_cv0, DAYS, SEED)


def effects_of(days: tuple[DayRecord, ...]) -> list[float]:
    return [d.day_effect for d in days]


def day_scale_reference(profile: ArrivalProfile, day: int) -> float:
    """B/1440 · d · m of a day, computed with datetime, independently of rate.py."""
    when = profile.start_date + timedelta(days=day)
    return (
        profile.daily_base
        / DAY
        * profile.weekday_factors[when.weekday()]
        * profile.month_factors[when.month - 1]
    )


def times_of(arrivals) -> list[float]:
    return [a.time for a in arrivals]


# --- Semillas y reproducibilidad ----------------------------------------------


def test_misma_semilla_mismos_registros(profile, run):
    assert simulate_arrivals(profile, DAYS, SEED) == run


def test_int_equivale_a_seedsequence(profile, run):
    assert simulate_arrivals(profile, DAYS, np.random.SeedSequence(SEED)) == run


def test_semillas_distintas(profile):
    a, days_a = simulate_arrivals(profile, 3, 1)
    b, days_b = simulate_arrivals(profile, 3, 2)

    assert times_of(a) != times_of(b)
    assert effects_of(days_a) != effects_of(days_b)


def test_mismo_seedsequence_dos_veces(profile):
    # El mismo objeto, reutilizado, da los mismos flujos (child_streams no lo modifica).
    seq = np.random.SeedSequence(SEED)

    first = simulate_arrivals(profile, 3, seq)
    effects = draw_day_effects(CV, 3, seq)
    second = simulate_arrivals(profile, 3, seq)

    assert first == second
    assert effects.tolist() == effects_of(first[1])


# --- Efecto diario Z ----------------------------------------------------------


def test_cv0_mismas_llegadas_que_main(run_cv0):
    arrivals, days = run_cv0

    assert fingerprint(arrivals) == (MAIN_ARRIVALS, MAIN_SHA256)
    assert all(d.day_effect == 1.0 for d in days)


def test_cv0_z_es_uno():
    assert draw_day_effects(0, 10, SEED).tolist() == [1.0] * 10


def test_parametros_gamma_a_mano():
    k, theta = thinning._gamma_parameters(CV)

    assert k == pytest.approx(GAMMA_SHAPE, abs=5e-3)
    assert theta == pytest.approx(GAMMA_SCALE, rel=1e-12)
    # Mezclar Poisson(Z·e) sobre la gamma da una binomial negativa: Var = e + CV²·e².
    nb = stats.nbinom(n=k, p=1 / (1 + theta * EXPECTED_MONDAY))
    assert nb.mean() == pytest.approx(EXPECTED_MONDAY, rel=1e-12)
    assert nb.var() == pytest.approx(VAR_NB_MONDAY, abs=0.05)
    assert stats.poisson(EXPECTED_MONDAY).var() == pytest.approx(VAR_POISSON_MONDAY, abs=0.05)


def test_media_y_cv_de_z():
    n = 20_000
    z = draw_day_effects(CV, n, SEED)
    mean = statistics.fmean(z)
    cv = statistics.stdev(z) / mean

    # Error típico de la media: CV/√n = 0,00042; del CV muestral, ≈ CV/√(2n) = 0,0003.
    # Las tolerancias son 5 errores típicos.
    assert z.shape == (n,)
    assert np.all(z > 0)
    assert mean == pytest.approx(1, abs=5 * CV / math.sqrt(n))
    assert cv == pytest.approx(CV, abs=5 * CV / math.sqrt(2 * n))


def test_el_run_usa_las_z_del_flujo_propio(run):
    assert effects_of(run[1]) == draw_day_effects(CV, DAYS, SEED).tolist()
    assert len(set(effects_of(run[1]))) == DAYS  # Z distinta cada día


def test_z_no_depende_del_perfil(profile, run):
    # Mismo flujo de Z con otra base: las candidatas cambian, las Z no.
    arrivals, days = simulate_arrivals(dataclasses.replace(profile, daily_base=400), DAYS, SEED)

    assert effects_of(days) == effects_of(run[1])
    assert times_of(arrivals) != times_of(run[0])


@pytest.mark.parametrize("cv", [-0.1, math.nan, math.inf, True])
def test_draw_day_effects_cv_invalido(cv):
    with pytest.raises(ValueError, match="daily_cv"):
        draw_day_effects(cv, 3, SEED)


@pytest.mark.parametrize("days", [0, 1.5, True])
def test_draw_day_effects_dias_invalido(days):
    with pytest.raises(ValueError, match="days"):
        draw_day_effects(CV, days, SEED)


# --- Llegadas -----------------------------------------------------------------


def test_tiempos_crecientes_en_horizonte(run):
    times = np.array(times_of(run[0]))

    assert times.size > 0
    assert np.all(np.diff(times) > 0)
    assert times[0] >= 0
    assert times[-1] < DAYS * DAY


def test_ids_consecutivos(run):
    assert [a.arrival_id for a in run[0]] == list(range(len(run[0])))


# --- Registros diarios --------------------------------------------------------


def test_un_registro_por_dia(profile, run):
    days = run[1]

    assert [d.day for d in days] == list(range(DAYS))
    assert [d.date for d in days] == [profile.start_date + timedelta(days=k) for k in range(DAYS)]
    assert all(d.day_effect > 0 for d in days)


def test_aceptadas_y_candidatas(run):
    arrivals, days = run
    per_day = np.bincount([math.floor(a.time / DAY) for a in arrivals], minlength=DAYS).tolist()

    assert all(0 <= d.accepted <= d.candidates for d in days)
    assert [d.accepted for d in days] == per_day
    assert sum(d.accepted for d in days) == len(arrivals)


def test_expected_es_z_por_lambda_del_dia(profile, run):
    days = run[1]
    effects = effects_of(days)

    for d in days:
        assert d.expected == pytest.approx(
            d.day_effect * day_scale(d.day, profile) * day_shape_area(profile), rel=1e-12
        ), d.day
        start, end = d.day * DAY, (d.day + 1) * DAY
        area = cumulative_rate(end, profile, day_effects=effects) - cumulative_rate(
            start, profile, day_effects=effects
        )
        assert d.expected == pytest.approx(area, rel=1e-12), d.day


def test_cota_es_z_por_escala_por_max_h(profile, run):
    max_h = max(profile.hour_factors)

    for d in run[1]:
        assert d.bound == pytest.approx(
            d.day_effect * day_scale_reference(profile, d.day) * max_h, rel=1e-12
        )


def test_valores_a_mano_lunes(profile_cv0, profile, run_cv0, run):
    monday = run_cv0[1][0]
    assert monday.bound == pytest.approx(BOUND_MONDAY, abs=5e-6)
    assert monday.bound == pytest.approx(rate(11 * 60 + 30, profile_cv0), rel=1e-12)
    assert monday.expected == pytest.approx(EXPECTED_MONDAY, abs=5e-4)

    # Con Z, la cota y lo esperado del lunes se multiplican por su Z.
    monday = run[1][0]
    assert monday.day_effect != 1.0
    assert monday.bound / monday.day_effect == pytest.approx(BOUND_MONDAY, abs=5e-6)
    assert monday.expected / monday.day_effect == pytest.approx(EXPECTED_MONDAY, abs=5e-4)


def test_proporcion_de_aceptacion(profile, run):
    days = run[1]

    # Teórica: Λ del día / (cota · 1440) = media(h) / máx(h), la misma en todos los días:
    # Z multiplica Λ y la cota, y se cancela.
    assert max(profile.hour_factors) == pytest.approx(MAX_H, rel=1e-12)
    for d in days:
        assert d.expected / (d.bound * DAY) == pytest.approx(ACCEPTANCE, rel=1e-12)

    # Observada: con ~28 000 candidatas, la desviación típica de la proporción es
    # √(p(1−p)/n) ≈ 0,003; 0,015 son unas 5 desviaciones típicas.
    observed = sum(d.accepted for d in days) / sum(d.candidates for d in days)
    assert observed == pytest.approx(ACCEPTANCE, abs=0.015)


def test_volumen_56_dias(profile, run):
    # Comprobación gruesa: dadas las Z, el número de llegadas es una Poisson de media Λ.
    expected = cumulative_rate(DAYS * DAY, profile, day_effects=effects_of(run[1]))

    assert abs(len(run[0]) - expected) < 4 * math.sqrt(expected)


# --- Cota ---------------------------------------------------------------------


def test_lambda_no_supera_cota_en_rejilla(profile, run):
    grid = np.arange(0, DAY, 0.25)  # incluye los centros de las horas (h:30)
    effects = effects_of(run[1])

    for d in run[1]:
        lam = rate(d.day * DAY + grid, profile, day_effects=effects)
        assert np.all(lam <= d.bound * (1 + 1e-12)), d.day


def test_cota_insuficiente_da_error(profile):
    # Una cota un 10 % baja: λ la supera cerca del pico del mediodía.
    with pytest.raises(RuntimeError, match="bound"):
        list(iter_arrivals(profile, 1, SEED, bound_factor=0.9))


@pytest.mark.parametrize("factor", [0, -1.0, math.nan, math.inf])
def test_bound_factor_invalido(profile, factor):
    # El error salta al llamar, sin esperar a la primera llegada.
    with pytest.raises(ValueError, match="bound_factor"):
        iter_arrivals(profile, 1, SEED, bound_factor=factor)


# --- Pereza y emisión de los días ---------------------------------------------


def test_perezoso(profile, monkeypatch):
    # Espías: el generador no debe calcular nada de días posteriores al primero,
    # ni sortear sus Z.
    scaled_days: list = []
    drawn: list[float] = []
    original_day_scale, original_effects = thinning.day_scale, thinning._day_effects

    def spy_day_scale(day, prof):
        scaled_days.append(day)
        return original_day_scale(day, prof)

    def spy_effects(cv, rng):
        for z in original_effects(cv, rng):
            drawn.append(z)
            yield z

    monkeypatch.setattr(thinning, "day_scale", spy_day_scale)
    monkeypatch.setattr(thinning, "_day_effects", spy_effects)
    closed: list[DayRecord] = []

    start = time.perf_counter()
    first = list(itertools.islice(iter_arrivals(profile, 10**6, SEED, on_day=closed.append), 5))
    elapsed = time.perf_counter() - start

    assert len(first) == 5
    assert elapsed < 2  # holgado para un CI lento: lo importante son los espías
    assert closed == []
    assert scaled_days == [0]
    assert len(drawn) == 1


def test_on_day_al_cerrar_cada_dia(profile):
    # Cada día se cierra después de su última llegada y antes de la primera del siguiente.
    events: list[tuple[int, int]] = []  # (día, 0 llegada | 1 cierre)

    for a in iter_arrivals(profile, 3, SEED, on_day=lambda d: events.append((d.day, 1))):
        events.append((math.floor(a.time / DAY), 0))

    assert [e for e in events if e[1] == 1] == [(0, 1), (1, 1), (2, 1)]
    assert events == sorted(events)


@pytest.mark.parametrize("days", [0, -1, 1.5, True])
def test_days_invalido(profile, days):
    with pytest.raises(ValueError, match="days"):
        iter_arrivals(profile, days, SEED)
    with pytest.raises(ValueError, match="days"):
        simulate_arrivals(profile, days, SEED)


# --- Proceso SimPy ------------------------------------------------------------


def test_simpy_mismos_instantes(profile):
    arrivals, _ = simulate_arrivals(profile, 3, SEED)
    env = simpy.Environment()
    seen: list[tuple[float, ArrivalRecord]] = []

    env.process(arrival_source(env, arrivals, lambda a: seen.append((env.now, a))))
    env.run()

    assert len(seen) == len(arrivals)
    for (now, delivered), original in zip(seen, arrivals, strict=True):
        assert delivered is original  # el registro original, no uno con env.now
        assert now == pytest.approx(original.time, rel=1e-12)


def test_simpy_consume_el_generador(profile):
    arrivals, _ = simulate_arrivals(profile, 3, SEED)
    env = simpy.Environment()
    seen: list[ArrivalRecord] = []

    env.process(arrival_source(env, iter_arrivals(profile, 3, SEED), seen.append))
    env.run(until=DAY)

    assert seen == [a for a in arrivals if a.time < DAY]


# --- Dispersión diaria (slow) -------------------------------------------------

PEARSON_DAYS = 1092  # tres años de 364 días


@pytest.mark.slow
@pytest.mark.parametrize("cv", [0, CV])
def test_indice_de_pearson(tmp_path, cv):
    # Dado Z, el día es Poisson de media Z·e; sobre la gamma, Var(c) = e + CV²·e², así
    # que E[(c − e)²/e] = 1 + CV²·e y P ≈ 1 + CV²·ē: 1 sin Z y ≈ 2,08 con CV 0,06.
    # Cada término es ≈ (Var/e)·χ²₁, de desviación √2·Var/e: P tiene un error típico
    # ≈ P·√(2/n), 0,043 con CV 0 y 0,089 con CV 0,06. La tolerancia son 4 errores
    # típicos (±0,17 y ±0,36), muy por debajo de la distancia entre ambas teorías (1,08).
    profile = example_with_cv(tmp_path, cv)
    _, days = simulate_arrivals(profile, PEARSON_DAYS, SEED)
    mean_expected = statistics.fmean(d.expected / d.day_effect for d in days)
    theory = 1 + cv**2 * mean_expected

    observed = pearson_index(profile, days)

    tolerance = 4 * theory * math.sqrt(2 / PEARSON_DAYS)
    assert observed == pytest.approx(theory, abs=tolerance), f"P = {observed:.3f}"
