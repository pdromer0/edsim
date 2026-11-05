"""Validación del motor: M/G/1, Mₜ/G/∞, leyes operacionales y más médicos.

Los tests rápidos comprueban la teoría y las piezas con valores a mano; los slow
ejecutan las comprobaciones estadísticas con semilla fija y miden su potencia con
versiones incorrectas que deben fallar, con menos réplicas que la validación.
"""

import dataclasses
import math
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from edsim.arrivals.profile import ArrivalProfile, load_profile
from edsim.arrivals.rate import cumulative_rate
from edsim.engine import analysis
from edsim.engine.center import load_center
from edsim.engine.clinical import PatientDraws, ProvisionalSampler, lognormal_params
from edsim.engine.engine import simulate_ed
from edsim.engine.events import MemorySink
from edsim.engine.scenarios import exponential_triage
from edsim.engine.validation import (
    INFINITE,
    census_by_day_and_hour,
    check_engine_validation_counts,
    check_infinite_server,
    check_mg1,
    check_more_doctors,
    check_operational_laws,
    check_warmup,
    draws_sample,
    flat_profile,
    hourly_grid_means,
    infinite_center,
    mg1_center,
    offered_load,
    offered_load_by_pool,
    pollaczek_khinchine,
    stay_sample,
    total_stay,
    validate_engine,
)
from edsim.seeds import child_streams

ROOT = Path(__file__).parent.parent
SEED = 2026


@pytest.fixture(scope="module")
def center():
    return load_center(ROOT / "config" / "centro.toml")


@pytest.fixture(scope="module")
def profile():
    return load_profile(ROOT / "config" / "llegadas.toml")


# --- M/G/1: teoría ------------------------------------------------------------------


def test_perfil_plano():
    p = flat_profile()
    assert p.daily_base == 192
    assert p.daily_cv == 0
    assert set(p.hour_factors) == set(p.weekday_factors) == set(p.month_factors) == {1.0}


def test_centro_mg1(center):
    c = mg1_center(center)
    assert c.triage_nurses == (1, 1, 1)
    assert c.doctors == (INFINITE,) * 3 and c.boxes == INFINITE
    assert c.triage_time == center.triage_time


def test_pollaczek_khinchine_de_la_especificacion(center):
    # Triaje con mediana 5 y p90 10, 8 llegadas por hora (docs/specs/hito-3.md). Desde
    # la tarea 4.1 el nivel 1 (0,3 %) se clasifica en la puerta: a la enfermera le llega
    # un Poisson de λ·(1 − p₁) (thinning), y Wq pasa de 13,10 a 12,93 minutos.
    theory = pollaczek_khinchine(mg1_center(center), flat_profile())

    assert center.level_shares[0] == 0.003
    assert theory.lam == 192 / 1440 * (1 - 0.003)
    assert theory.lam == pytest.approx(0.13293, abs=5e-6)
    assert theory.mean_service == pytest.approx(5.788, abs=5e-4)
    assert theory.second_moment == pytest.approx(44.88, abs=5e-3)
    assert theory.rho == pytest.approx(0.7694, abs=5e-5)
    assert theory.wq == pytest.approx(12.93, abs=5e-3)
    assert theory.lq == pytest.approx(1.719, abs=5e-4)
    assert theory.lq == theory.lam * theory.wq  # Little en la teoría


def test_la_teoria_usa_las_llegadas_que_ven_la_enfermera(center):
    # La parte de niveles 1 sale de la configuración. Con p₁ = 0,5 llega a la enfermera
    # la mitad: λ = 192/1440 · 0,5 = 1/15, ρ = 5,788/15 = 0,3858 y
    # Wq = (1/15) · 44,88 / (2 · 0,6142) = 2,436.
    half = dataclasses.replace(mg1_center(center), level_shares=(50, 12.5, 12.5, 12.5, 12.5))
    theory = pollaczek_khinchine(half, flat_profile())
    assert theory.lam == pytest.approx(1 / 15, rel=1e-15)
    assert theory.rho == pytest.approx(0.3858, abs=5e-5)
    assert theory.wq == pytest.approx(2.436, abs=5e-4)
    # Sin niveles 1 vuelve la cifra del hito 3.
    none = dataclasses.replace(mg1_center(center), level_shares=(0, 12.1, 33.6, 52.6, 1.4))
    assert pollaczek_khinchine(none, flat_profile()).wq == pytest.approx(13.10, abs=5e-3)


def test_pollaczek_khinchine_a_mano(center):
    mu, sigma = lognormal_params(*center.triage_time)
    es = math.exp(mu + sigma**2 / 2)
    es2 = math.exp(2 * mu + 2 * sigma**2)
    lam = 192 / 1440 * (1 - center.level_shares[0])
    theory = pollaczek_khinchine(mg1_center(center), flat_profile())
    assert theory.mean_service == pytest.approx(es, rel=1e-15)
    assert theory.second_moment == pytest.approx(es2, rel=1e-15)
    assert theory.wq == pytest.approx(lam * es2 / (2 * (1 - lam * es)), rel=1e-15)


def test_la_teoria_sale_de_la_configuracion(center):
    # Otra mediana de triaje cambia la teoría: no está copiada de la especificación.
    slower = dataclasses.replace(mg1_center(center), triage_time=(6.0, 10.0))
    assert pollaczek_khinchine(slower, flat_profile()).wq > 13.10


@pytest.mark.parametrize(
    "change",
    [
        {"daily_cv": 0.06},
        {"hour_factors": (2,) + (1,) * 23},
        {"weekday_factors": (2,) + (1,) * 6},
        {"month_factors": (2,) + (1,) * 11},
    ],
)
def test_pollaczek_khinchine_exige_perfil_plano(center, change):
    with pytest.raises(ValueError, match="flat"):
        pollaczek_khinchine(center, dataclasses.replace(flat_profile(), **change))


def test_pollaczek_khinchine_exige_una_enfermera(center):
    with pytest.raises(ValueError, match="one triage nurse"):
        pollaczek_khinchine(center, flat_profile())


def test_pollaczek_khinchine_inestable(center):
    busy = flat_profile(daily_base=300)  # ρ = 300/1440 · 5,788 > 1
    with pytest.raises(ValueError, match="unstable"):
        pollaczek_khinchine(mg1_center(center), busy)


def test_check_mg1_argumentos(center):
    with pytest.raises(ValueError, match="replicas"):
        check_mg1(center, replicas=1, seed=SEED)
    with pytest.raises(ValueError, match="warmup_days"):
        check_mg1(center, days=2, warmup_days=2, seed=SEED)


# --- M/G/1: simulación (slow) -------------------------------------------------------------


@pytest.mark.slow
def test_potencia_mg1_con_triaje_exponencial(center):
    # Misma media, CV 1 en lugar de 0,57: Wq ≈ 19,3 min frente a 12,93. Con 5 réplicas
    # no basta: la t de 4 grados de libertad al 99,67 % vale 6,25 y el IC de Wq (medido,
    # 9,3-28,6) contiene la teoría. Con 10, t = 3,95 y el IC queda por encima.
    c = mg1_center(center)
    result, replicas = check_mg1(
        center, replicas=10, seed=SEED, sampler_factory=exponential_triage(c)
    )

    assert not result.passed
    wq, rho, _ = result.details
    assert not wq.passed and wq.ci_low > replicas.theory.wq
    assert rho.passed  # la media del servicio es la misma: ρ no lo ve


def test_flat_profile_con_otra_fecha():
    p = flat_profile(daily_base=100, start_date=date(2026, 3, 1))
    assert isinstance(p, ArrivalProfile) and p.start_date == date(2026, 3, 1)


# --- Mₜ/G/∞: piezas -----------------------------------------------------------------------

DRAWS = PatientDraws(
    level=3,
    triage_time=5.0,
    assessment_time=20.0,
    reassessment_time=10.0,
    needs_tests=True,
    test_turnaround=60.0,
    admitted=False,
)


def test_estancia_total_a_mano():
    assert total_stay(DRAWS) == 5 + 20 + 60 + 10
    # Sin pruebas no cuentan la respuesta ni la reevaluación, aunque se sorteen.
    assert total_stay(dataclasses.replace(DRAWS, needs_tests=False)) == 25
    # Un nivel 1 se clasifica en la puerta: su triaje sorteado no cuenta (tarea 4.1).
    assert total_stay(dataclasses.replace(DRAWS, level=1)) == 20 + 60 + 10


def test_centro_infinito(center):
    c = infinite_center(center)
    assert c.triage_nurses == c.doctors == (INFINITE,) * 3 and c.boxes == INFINITE
    assert c.test_probability == center.test_probability


def test_muestra_de_estancias_reproducible(center):
    a = stay_sample(center, 1000, seed=7)
    b = stay_sample(center, 1000, seed=7)
    assert a.shape == (1000,) and np.array_equal(a, b)
    assert not np.array_equal(a, stay_sample(center, 1000, seed=8))
    # Las mismas que da el muestreador del motor con esa semilla.
    sampler = ProvisionalSampler(center, child_streams(7, 4))
    assert a[0] == total_stay(sampler(None))


def test_carga_ofrecida_con_tasa_constante():
    # Con λ constante, pasada la estancia máxima, m = λ·E[S] (la media de la muestra).
    stays = np.array([10.0, 30.0, 80.0])
    profile = flat_profile(daily_base=144)  # 0,1 por minuto
    m = offered_load(profile, stays, horizon=300)

    assert m.shape == (301,)
    assert m[0] == 0.0
    assert m[200] == pytest.approx(0.1 * stays.mean(), rel=1e-12)
    # Antes de la primera salida posible, m(t) = λ·t (nadie ha salido aún).
    assert m[5] == pytest.approx(0.1 * 5, rel=1e-12)


def test_carga_ofrecida_frente_a_la_formula_exacta(center, profile):
    # m(t) = E[Λ(t) - Λ((t - S)⁺)], exacta para la muestra; la rejilla de 1 minuto
    # (regla del punto medio) debe acercarse mucho.
    stays = stay_sample(center, 20_000, seed=11)
    flat_z = dataclasses.replace(profile, daily_cv=0.0)
    m = offered_load(flat_z, stays, horizon=3 * 1440)
    for t in (90, 600, 1000, 2000, 3 * 1440):
        exact = np.mean(
            cumulative_rate(t, flat_z) - cumulative_rate(np.maximum(0.0, t - stays), flat_z)
        )
        assert m[t] == pytest.approx(exact, rel=1e-3), t


def test_medias_horarias_de_la_rejilla():
    # Una rejilla que vale la hora del día en cada minuto: la media de la hora h es h,
    # salvo en el borde, donde el trapecio mezcla con la hora siguiente.
    minutes = np.arange(2 * 1440 + 1)
    values = (minutes % 1440) // 60
    means = hourly_grid_means(values.astype(float), start=1440, end=2 * 1440)
    assert means.shape == (24,)
    assert means[5] == pytest.approx(5 + 0.5 / 60)


def test_check_infinite_server_argumentos(center, profile):
    with pytest.raises(ValueError, match="n_stays"):
        check_infinite_server(center, profile, seed=SEED, stay_seed=1, n_stays=1)


# --- Mₜ/G/∞ (slow) -----------------------------------------------------------------------


@pytest.mark.slow
def test_potencia_mtginf_con_el_perfil_desplazado(center, profile):
    # Se simula con el perfil una hora más tarde y se valida contra el real.
    h = profile.hour_factors
    shifted = dataclasses.replace(profile, hour_factors=h[-1:] + h[:-1])

    result, infinite, _ = check_infinite_server(
        center, shifted, replicas=5, seed=SEED, stay_seed=SEED + 1, hypothesis=profile
    )

    assert not result.passed
    # Medido: 5 horas fuera (8 a 11 h y 21 h, donde λ(t) sube o baja deprisa).
    assert result.statistic >= 4  # varias horas fuera, no una por azar
    assert infinite.passed  # sin colas sigue sin haber esperas


# --- Leyes operacionales y más médicos: piezas --------------------------------------------

EXAMPLE_PROFILE = ROOT / "tests" / "data" / "llegadas_ejemplo.toml"


def test_leyes_operacionales_en_una_ejecucion_corta(center):
    # Tres días bastan para las invariantes y la utilización; Little necesita la larga.
    results = check_operational_laws(
        center, load_profile(EXAMPLE_PROFILE), days=3, warmup_days=1, seed=SEED
    )
    by_name = {r.name: r for r in results}
    assert list(by_name) == [
        "invariants",
        "little_system",
        "little_triage_queue",
        "little_box_queue",
        "utilization_enfermeria_triaje",
        "utilization_medicos",
        "utilization_boxes",
    ]
    assert by_name["invariants"].passed and by_name["invariants"].statistic == 0
    assert all(
        by_name[f"utilization_{p}"].passed for p in ("enfermeria_triaje", "medicos", "boxes")
    )


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [({"extra": 0}, "extra"), ({"replicas": 1}, "replicas"), ({"days": 1}, "warmup_days")],
)
def test_check_more_doctors_argumentos(center, profile, kwargs, match):
    with pytest.raises(ValueError, match=match):
        check_more_doctors(center, profile, seed=SEED, **kwargs)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"replicas": 1}, "replicas"),
        ({"paired_replicas": 1}, "paired_replicas"),
        ({"n_stays": 10}, "n_stays"),
        ({"long_days": 2}, "warmup_days"),
    ],
)
def test_validate_engine_argumentos(center, profile, kwargs, match):
    with pytest.raises(ValueError, match=match):
        validate_engine(center, profile, **kwargs)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"replicas": 1}, "replicas"),
        ({"replicas": True}, "replicas"),
        ({"paired_replicas": 1}, "paired_replicas"),
        ({"n_stays": 10}, "n_stays"),
        ({"long_days": 2}, "warmup_days"),
        ({"mg1_days": 0}, "days"),
        ({"warmup_days": -1}, "warmup_days"),
    ],
)
def test_check_engine_validation_counts(kwargs, match):
    # Las mismas comprobaciones que validate_engine, sin simular: la CLI las usa
    # antes de imprimir nada.
    with pytest.raises(ValueError, match=match):
        check_engine_validation_counts(**kwargs)


def test_check_engine_validation_counts_por_defecto():
    check_engine_validation_counts()
    check_engine_validation_counts(replicas=2, paired_replicas=2, n_stays=1000)


def test_validate_engine_guarda_la_ejecucion_larga():
    # Réplicas y días mínimos: aquí se prueba qué guarda, no la estadística.
    center = load_center(ROOT / "tests" / "data" / "centro_ejemplo.toml")
    v = validate_engine(
        center,
        load_profile(EXAMPLE_PROFILE),
        seed=SEED,
        replicas=2,
        mg1_days=2,
        mtginf_days=2,
        long_days=3,
        paired_replicas=2,
        paired_days=2,
        warmup_days=1,
        n_stays=1000,
    )
    long_run = v.long_run
    assert (long_run.metrics.start, long_run.metrics.end) == (1440.0, 3 * 1440.0)
    assert long_run.curves.horizon == 3 * 1440.0
    for law in long_run.little:
        assert v.result(f"little_{law.name}").statistic == law.relative_error
    for u in long_run.utilization:
        assert v.result(f"utilization_{u.pool}").statistic == u.relative_error


# --- validate_engine completo (slow) ----------------------------------------------------
# engine_validation_real (conftest.py): la validación completa con la semilla 2026, una
# vez por sesión, compartida con el test slow de la CLI.


@pytest.mark.slow
def test_validate_engine_todas_pasan(engine_validation_real):
    failed = [r for r in engine_validation_real.results if not r.passed]
    assert engine_validation_real.passed, failed
    assert [r.name for r in engine_validation_real.results] == [
        "invariants",
        "little_system",
        "little_triage_queue",
        "little_box_queue",
        "utilization_enfermeria_triaje",
        "utilization_medicos",
        "utilization_boxes",
        "mg1",
        "mtginf",
        "infinite_capacity",
        "more_doctors",
    ]


@pytest.mark.slow
def test_validate_engine_mg1(engine_validation_real):
    mg1 = engine_validation_real.result("mg1")
    assert [d.name for d in mg1.details] == ["wq", "rho", "lq"]
    assert all(d.confidence == pytest.approx(1 - 0.01 / 3) for d in mg1.details)
    assert len(engine_validation_real.mg1.wq) == 20
    # 12,93 con λ·(1 − p₁) desde la tarea 4.1 (13,10 en el hito 3, sin nivel 1 en la puerta).
    assert engine_validation_real.mg1.theory.wq == pytest.approx(12.93, abs=5e-3)
    assert engine_validation_real.long_run.metrics.end == 28 * 1440


@pytest.mark.slow
def test_validate_engine_mtginf(engine_validation_real):
    mtginf = engine_validation_real.result("mtginf")
    assert len(mtginf.details) == 24
    assert mtginf.confidence == pytest.approx(1 - 0.01 / 24)
    assert engine_validation_real.hourly.census.shape == (20, 24)
    assert engine_validation_real.hourly.expected.shape == (24,)


@pytest.mark.slow
def test_validate_engine_mas_medicos(engine_validation_real):
    more = engine_validation_real.result("more_doctors")
    assert more.ci_high < 0 and more.statistic < 0


@pytest.mark.slow
def test_potencia_utilizacion_con_un_recorte_mal_hecho(center, profile, monkeypatch):
    # Versión incorrecta: no recorta por la izquierda, así que cuenta entera la parte
    # anterior al calentamiento de los servicios que lo cruzan.
    monkeypatch.setattr(
        analysis, "time_in_window", lambda start, end, w0, w1: max(0.0, min(end, w1) - start)
    )
    by_name = {r.name: r for r in check_operational_laws(center, profile, seed=SEED)}

    for pool in ("enfermeria_triaje", "medicos", "boxes"):
        assert not by_name[f"utilization_{pool}"].passed, pool
    assert by_name["little_system"].passed  # Little no usa los intervalos


# --- Carga ofrecida por pool ---------------------------------------------------------------


def test_muestra_de_sorteos_es_la_de_las_estancias(center):
    draws = draws_sample(center, 500, seed=7)
    assert np.array_equal(stay_sample(center, 500, seed=7), [total_stay(d) for d in draws])


def test_carga_por_pool_a_mano():
    # λ constante de 0,1 por minuto. Dos pacientes: uno sin pruebas (triaje 5,
    # valoración 20) y otro con pruebas (triaje 5, valoración 10, respuesta 30,
    # reevaluación 10). Pasada la estancia máxima, m = λ · E[tiempo en el pool].
    no_tests = dataclasses.replace(DRAWS, assessment_time=20.0, needs_tests=False)
    tests = dataclasses.replace(
        DRAWS, assessment_time=10.0, test_turnaround=30.0, reassessment_time=10.0
    )
    load = offered_load_by_pool(flat_profile(daily_base=144), [no_tests, tests], horizon=200)

    assert set(load) == {"census", "enfermeria_triaje", "medicos", "boxes"}
    assert load["census"][150] == pytest.approx(0.1 * (25 + 55) / 2, rel=1e-12)
    assert load["enfermeria_triaje"][150] == pytest.approx(0.1 * 5, rel=1e-12)
    assert load["medicos"][150] == pytest.approx(0.1 * (20 + 20) / 2, rel=1e-12)
    assert load["boxes"][150] == pytest.approx(0.1 * (20 + 50) / 2, rel=1e-12)
    # Al principio nadie ha terminado el triaje: ni boxes ni médicos.
    assert load["boxes"][4] == load["medicos"][4] == 0.0
    assert load["enfermeria_triaje"][4] == pytest.approx(0.1 * 4, rel=1e-12)


def test_carga_por_pool_del_nivel_1_sin_enfermera():
    # El mismo paciente sin pruebas como nivel 1: sin enfermera, box y médico desde la
    # llegada. Pasada la estancia, m = λ · 20 en médicos, boxes y censo.
    door = dataclasses.replace(DRAWS, level=1, assessment_time=20.0, needs_tests=False)
    load = offered_load_by_pool(flat_profile(daily_base=144), [door], horizon=100)

    assert load["enfermeria_triaje"][50] == 0.0
    assert load["medicos"][50] == load["boxes"][50] == load["census"][50]
    assert load["census"][50] == pytest.approx(0.1 * 20, rel=1e-12)
    assert load["boxes"][4] == pytest.approx(0.1 * 4, rel=1e-12)  # box desde el minuto 0


def test_carga_del_censo_es_la_de_offered_load(center, profile):
    draws = draws_sample(center, 5000, seed=3)
    stays = np.array([total_stay(d) for d in draws])
    flat_z = dataclasses.replace(profile, daily_cv=0.0)
    by_pool = offered_load_by_pool(flat_z, draws, horizon=2 * 1440)
    np.testing.assert_allclose(
        by_pool["census"], offered_load(flat_z, stays, 2 * 1440), rtol=1e-12, atol=1e-12
    )
    # Censo = enfermería + boxes (sin esperas, el box empieza al acabar el triaje).
    np.testing.assert_allclose(
        by_pool["census"], by_pool["enfermeria_triaje"] + by_pool["boxes"], rtol=1e-12, atol=1e-12
    )


def test_carga_por_pool_sin_muestra(profile):
    with pytest.raises(ValueError, match="empty"):
        offered_load_by_pool(profile, [], horizon=10)


# --- Medias horarias de la Mₜ/G/∞ ----------------------------------------------------------


def test_medias_horarias_iguales_que_antes(center):
    # La fórmula de la tarea 3.6, escrita aquí, da los mismos bits que la nueva.
    sink = MemorySink()
    simulate_ed(center, load_profile(EXAMPLE_PROFILE), 3, SEED, sink=sink, warmup_days=1)
    curves = analysis.step_curves(sink.events, 3 * 1440)
    edges = np.append(curves.times, curves.horizon)
    cumulative = np.concatenate([[0.0], np.cumsum(np.diff(edges) * curves["census"])])
    hours = np.arange(1440, 3 * 1440 + 1, 60, dtype=float)
    old = (np.diff(np.interp(hours, edges, cumulative)) / 60).reshape(-1, 24).mean(axis=0)
    new = analysis.hourly_means_by_day(curves, "census", 1440, 3 * 1440).mean(axis=0)
    assert np.array_equal(old, new)


# --- Calentamiento ---------------------------------------------------------------------------


def test_censo_por_dia_y_hora(center):
    census = census_by_day_and_hour(center, load_profile(EXAMPLE_PROFILE), 2, SEED, 2)
    assert census.shape == (2, 2, 24)
    # Desde vacío: a las 0 h del día 0 hay menos gente que a las 0 h del día 1.
    assert census[:, 0, 0].mean() < census[:, 1, 0].mean()
    again = census_by_day_and_hour(center, load_profile(EXAMPLE_PROFILE), 2, SEED, 2)
    assert np.array_equal(census, again)


def test_comprobacion_del_calentamiento_a_mano():
    # 5 réplicas iguales salvo ruido; el día 0 tiene la hora 2 desplazada a propósito.
    rng = np.random.default_rng(1)
    census = 20 + rng.normal(0, 1, size=(5, 8, 24))
    census[:, 0, 2] -= 10
    result = check_warmup(census, 0, 7)
    assert result.name == "warmup" and not result.passed
    assert [d.name for d in result.details if not d.passed] == ["02h"]
    assert result.statistic == 1
    assert result.confidence == pytest.approx(1 - 0.01 / 24)
    assert check_warmup(census, 1, 7).passed


@pytest.mark.parametrize(
    ("shape", "day", "ref"), [((1, 8, 24), 0, 7), ((5, 8, 23), 0, 7), ((5, 8, 24), 0, 8)]
)
def test_comprobacion_del_calentamiento_argumentos(shape, day, ref):
    with pytest.raises(ValueError):
        check_warmup(np.zeros(shape), day, ref)
