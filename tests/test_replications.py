import numpy as np
import pytest

from edsim.queueing.mm1 import simulate_mm1
from edsim.queueing.replications import METRIC_NAMES, compare_mm1, coverage_mm1
from edsim.queueing.theory import mm1_theory

# Corridas pequeñas: aquí se prueba la mecánica, no la precisión.
SMALL = {"lam": 0.5, "mu": 1.0, "duration": 500.0, "warmup": 50.0}


def test_misma_semilla_maestra_mismo_resultado():
    a = compare_mm1(**SMALL, replicas=3, seed=7)
    b = compare_mm1(**SMALL, replicas=3, seed=7)

    assert a == b


def test_semillas_maestras_distintas():
    a = compare_mm1(**SMALL, replicas=3, seed=7)
    b = compare_mm1(**SMALL, replicas=3, seed=8)

    assert a.replications != b.replications


def test_replicas_distintas_entre_si():
    reps = compare_mm1(**SMALL, replicas=3, seed=7).replications

    assert len(reps) == 3
    assert len(set(reps)) == 3


def test_mas_replicas_conserva_las_primeras():
    # La réplica i depende solo de (semilla maestra, i): ampliar R no cambia las anteriores.
    three = compare_mm1(**SMALL, replicas=3, seed=7).replications
    five = compare_mm1(**SMALL, replicas=5, seed=7).replications

    assert five[:3] == three


def test_campos_de_la_comparacion():
    c = compare_mm1(**SMALL, replicas=3, seed=7)
    theory = mm1_theory(SMALL["lam"], SMALL["mu"])

    assert tuple(m.name for m in c.metrics) == METRIC_NAMES == ("wq", "w", "lq", "l", "rho")
    for m in c.metrics:
        assert c.metric(m.name) is m
        assert m.theory == getattr(theory, m.name)
        assert m.summary.n == 3
        assert m.summary.mean == pytest.approx(
            np.mean([getattr(r, m.name) for r in c.replications])
        )
        assert m.rel_error == pytest.approx(abs(m.summary.mean - m.theory) / m.theory)
        assert m.theory_in_ci == (m.summary.ci_low <= m.theory <= m.summary.ci_high)


def test_metrica_desconocida():
    c = compare_mm1(**SMALL, replicas=3, seed=7)

    with pytest.raises(KeyError):
        c.metric("xyz")


def test_simulate_acepta_seedsequence():
    # Un entero y la SeedSequence de ese entero son la misma semilla.
    a = simulate_mm1(lam=0.5, mu=1.0, horizon=200.0, seed=2026)
    b = simulate_mm1(lam=0.5, mu=1.0, horizon=200.0, seed=np.random.SeedSequence(2026))

    assert a == b


# --- Cobertura ---------------------------------------------------------------

COVERAGE_SEEDS = (0, 1, 2, 3, 4)


def test_cobertura_un_intervalo_por_semilla():
    cov = coverage_mm1(**SMALL, replicas=3, seeds=COVERAGE_SEEDS, metric="wq")

    assert cov.metric == "wq"
    assert cov.seeds == COVERAGE_SEEDS
    for seed, interval in zip(COVERAGE_SEEDS, cov.intervals, strict=True):
        assert interval == compare_mm1(**SMALL, replicas=3, seed=seed).metric("wq")


def test_cobertura_aciertos_y_lados():
    cov = coverage_mm1(**SMALL, replicas=3, seeds=COVERAGE_SEEDS, metric="lq")

    assert cov.hits + len(cov.below) + len(cov.above) == len(COVERAGE_SEEDS)
    assert cov.rate == cov.hits / len(COVERAGE_SEEDS)
    for seed, m in zip(COVERAGE_SEEDS, cov.intervals, strict=True):
        # Por debajo: la simulación queda bajo la teoría (el IC entero está debajo).
        assert (seed in cov.below) == (m.summary.ci_high < m.theory)
        assert (seed in cov.above) == (m.summary.ci_low > m.theory)


def test_cobertura_confianza():
    cov = coverage_mm1(**SMALL, replicas=3, seeds=(0,), confidence=0.90)

    assert cov.intervals[0].summary.confidence == 0.90


@pytest.mark.parametrize(("seeds", "metric"), [((), "wq"), ((0,), "xyz")])
def test_cobertura_parametros_invalidos(seeds, metric):
    with pytest.raises(ValueError):
        coverage_mm1(**SMALL, replicas=3, seeds=seeds, metric=metric)
