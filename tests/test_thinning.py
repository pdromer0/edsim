import itertools
import math
import time
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest
import simpy

from edsim.arrivals import thinning
from edsim.arrivals.profile import ArrivalProfile, load_profile
from edsim.arrivals.rate import cumulative_rate, rate
from edsim.arrivals.thinning import (
    ArrivalRecord,
    DayRecord,
    arrival_source,
    iter_arrivals,
    simulate_arrivals,
)

EXAMPLE = Path(__file__).parent / "data" / "llegadas_ejemplo.toml"
DAY = 1440  # minutos
DAYS, SEED = 56, 2026

# Valores calculados a mano para el lunes 2026-01-05 (día 0) con el perfil de ejemplo
# (ver tests/test_rate.py): la cota es escala · máx(h) = 0,260805 · 1,68 = λ(11:30).
BOUND_MONDAY = 0.43815
EXPECTED_MONDAY = 375.559
MAX_H = 1.68  # 24 · 7,0 / 100: el reparto de las 11 h frente a la media
ACCEPTANCE = 1 / MAX_H  # media de λ / cota, igual en todos los días: 0,595


@pytest.fixture(scope="module")
def profile() -> ArrivalProfile:
    return load_profile(EXAMPLE)


@pytest.fixture(scope="module")
def run(profile) -> tuple[tuple[ArrivalRecord, ...], tuple[DayRecord, ...]]:
    return simulate_arrivals(profile, DAYS, SEED)


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
    a, _ = simulate_arrivals(profile, 3, 1)
    b, _ = simulate_arrivals(profile, 3, 2)

    assert times_of(a) != times_of(b)


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
    # Sin efecto diario hasta la tarea 2.3.
    assert all(d.day_effect == 1.0 for d in days)


def test_aceptadas_y_candidatas(run):
    arrivals, days = run
    per_day = np.bincount([math.floor(a.time / DAY) for a in arrivals], minlength=DAYS).tolist()

    assert all(0 <= d.accepted <= d.candidates for d in days)
    assert [d.accepted for d in days] == per_day
    assert sum(d.accepted for d in days) == len(arrivals)


def test_expected_es_lambda_del_dia(profile, run):
    for d in run[1]:
        area = cumulative_rate((d.day + 1) * DAY, profile) - cumulative_rate(d.day * DAY, profile)
        assert d.expected == pytest.approx(area, rel=1e-12), d.day


def test_cota_es_escala_por_max_h(profile, run):
    max_h = max(profile.hour_factors)

    for d in run[1]:
        assert d.bound == pytest.approx(day_scale_reference(profile, d.day) * max_h, rel=1e-12)


def test_valores_a_mano_lunes(profile, run):
    monday = run[1][0]

    assert monday.bound == pytest.approx(BOUND_MONDAY, abs=5e-6)
    assert monday.bound == pytest.approx(rate(11 * 60 + 30, profile), rel=1e-12)
    assert monday.expected == pytest.approx(EXPECTED_MONDAY, abs=5e-4)


def test_proporcion_de_aceptacion(profile, run):
    days = run[1]

    # Teórica: Λ del día / (cota · 1440) = media(h) / máx(h), la misma en todos los días.
    assert max(profile.hour_factors) == pytest.approx(MAX_H, rel=1e-12)
    for d in days:
        assert d.expected / (d.bound * DAY) == pytest.approx(ACCEPTANCE, rel=1e-12)

    # Observada: con ~28 000 candidatas, la desviación típica de la proporción es
    # √(p(1−p)/n) ≈ 0,003; 0,015 son unas 5 desviaciones típicas.
    observed = sum(d.accepted for d in days) / sum(d.candidates for d in days)
    assert observed == pytest.approx(ACCEPTANCE, abs=0.015)


def test_volumen_56_dias(profile, run):
    # Comprobación gruesa: el número de llegadas es una Poisson de media Λ.
    expected = cumulative_rate(DAYS * DAY, profile)

    assert abs(len(run[0]) - expected) < 4 * math.sqrt(expected)


# --- Cota ---------------------------------------------------------------------


def test_lambda_no_supera_cota_en_rejilla(profile, run):
    grid = np.arange(0, DAY, 0.25)  # incluye los centros de las horas (h:30)

    for d in run[1]:
        assert np.all(rate(d.day * DAY + grid, profile) <= d.bound * (1 + 1e-12)), d.day


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
    # Espías: el generador no debe calcular nada de días posteriores al primero.
    scaled_days: list = []
    cumulative_times: list = []
    day_scale, cumulative = thinning.day_scale, thinning.cumulative_rate

    def spy_day_scale(day, prof):
        scaled_days.append(day)
        return day_scale(day, prof)

    def spy_cumulative(t, prof):
        cumulative_times.append(t)
        return cumulative(t, prof)

    monkeypatch.setattr(thinning, "day_scale", spy_day_scale)
    monkeypatch.setattr(thinning, "cumulative_rate", spy_cumulative)
    closed: list[DayRecord] = []

    start = time.perf_counter()
    first = list(itertools.islice(iter_arrivals(profile, 10**6, SEED, on_day=closed.append), 5))
    elapsed = time.perf_counter() - start

    assert len(first) == 5
    assert elapsed < 2  # holgado para un CI lento: lo importante son los espías
    assert closed == []
    assert scaled_days == [0]
    assert all(np.all(np.asarray(t) <= DAY) for t in cumulative_times)


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
