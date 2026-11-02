"""Fixtures compartidos por varios ficheros de tests.

Los fixtures se construyen solo cuando un test los pide, no al importar este
fichero: pytest lo carga en cada ejecución. Sus nombres son propios para no
chocar con los fixtures ``center`` o ``profile`` de cada módulo.
"""

from pathlib import Path

import numpy as np
import pytest

from edsim.arrivals.profile import load_profile
from edsim.arrivals.validation import ALPHA, ValidationResult
from edsim.engine.analysis import analyze_run
from edsim.engine.center import load_center
from edsim.engine.engine import simulate_ed
from edsim.engine.events import MemorySink
from edsim.engine.validation import (
    EngineValidation,
    HourlyCensus,
    MG1Replicas,
    flat_profile,
    mg1_center,
    pollaczek_khinchine,
    validate_engine,
)
from edsim.stats import summarize

DATA = Path(__file__).parent / "data"
EXAMPLE_CENTER = DATA / "centro_ejemplo.toml"
EXAMPLE_PROFILE = DATA / "llegadas_ejemplo.toml"
CONFIG = Path(__file__).parent.parent / "config"
REAL_CENTER = CONFIG / "centro.toml"
REAL_PROFILE = CONFIG / "llegadas.toml"
REAL_SEED = 2026

_VALIDATION_NAMES = (
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
)
"""Los nombres de ``validate_engine``, en su orden."""


def _interval(name, values, target, confidence):
    s = summarize(values, confidence)
    return ValidationResult(
        name=name,
        statistic=s.mean,
        p_value=None,
        ci_low=s.ci_low,
        ci_high=s.ci_high,
        target=target,
        criterion=f"{target:g} in CI",
        passed=s.ci_low <= target <= s.ci_high,
        confidence=confidence,
    )


def _count(name, statistic, passed=True, details=(), confidence=None, **interval):
    return ValidationResult(
        name=name,
        statistic=float(statistic),
        p_value=None,
        ci_low=interval.get("ci_low"),
        ci_high=interval.get("ci_high"),
        target=interval.get("target"),
        criterion="hecho a mano",
        passed=passed,
        details=details,
        confidence=confidence,
    )


@pytest.fixture(scope="session")
def engine_validation_pequena():
    """Un ``EngineValidation`` construido a mano, sin la validación de 2 minutos.

    La ejecución larga es de verdad (3 días del centro de ejemplo, semilla 7);
    la M/G/1 usa la teoría real con tres Wq inventados, y el censo por hora,
    una curva inventada con m(t) dentro de los 24 IC. Todas las comprobaciones
    pasan; los tests que necesiten un fallo lo fuerzan con
    ``dataclasses.replace``.
    """
    center = load_center(EXAMPLE_CENTER)
    sink = MemorySink()
    simulate_ed(center, load_profile(EXAMPLE_PROFILE), 3, 7, sink=sink, warmup_days=1)
    long_run = analyze_run(sink.events, center, 3, 1)

    theory = pollaczek_khinchine(mg1_center(center), flat_profile())
    wq = (theory.wq - 1.0, theory.wq + 0.2, theory.wq + 0.9)
    rho = (theory.rho - 0.01, theory.rho, theory.rho + 0.01)
    lq = (theory.lq - 0.1, theory.lq, theory.lq + 0.2)
    mg1_confidence = 1 - ALPHA / 3
    mg1_details = (
        _interval("wq", wq, theory.wq, mg1_confidence),
        _interval("rho", rho, theory.rho, mg1_confidence),
        _interval("lq", lq, theory.lq, mg1_confidence),
    )
    mg1 = _count(
        "mg1",
        mg1_details[0].statistic,
        details=mg1_details,
        confidence=mg1_confidence,
        ci_low=mg1_details[0].ci_low,
        ci_high=mg1_details[0].ci_high,
        target=theory.wq,
    )

    hours = np.arange(24)
    expected = 15 + 10 * np.sin(np.pi * hours / 24)
    census = np.array([expected - 0.5, expected + 0.1, expected + 0.4])
    hour_confidence = 1 - ALPHA / 24
    hour_details = tuple(
        _interval(f"{h:02d}h", census[:, h], float(expected[h]), hour_confidence) for h in hours
    )
    hourly = HourlyCensus(
        expected=expected,
        census=census,
        ci_low=np.array([d.ci_low for d in hour_details]),
        ci_high=np.array([d.ci_high for d in hour_details]),
    )
    mtginf = _count("mtginf", 0, details=hour_details, confidence=hour_confidence)

    results = (
        _count("invariants", 0, target=0.0),
        *(_count(f"little_{law.name}", law.relative_error) for law in long_run.little),
        *(_count(f"utilization_{u.pool}", u.relative_error) for u in long_run.utilization),
        mg1,
        mtginf,
        _count("infinite_capacity", 0, target=0.0),
        _count("more_doctors", -3.7, confidence=1 - ALPHA, ci_low=-4.5, ci_high=-2.9, target=0.0),
    )
    assert tuple(r.name for r in results) == _VALIDATION_NAMES
    assert all(r.passed for r in results)
    return EngineValidation(
        results=results,
        mg1=MG1Replicas(theory, wq, rho, lq),
        hourly=hourly,
        long_run=long_run,
    )


@pytest.fixture(scope="session")
def engine_validation_real():
    """La validación completa de verdad: ``validate_engine`` con ``config/centro.toml``,
    ``config/llegadas.toml``, la semilla 2026 y los valores por defecto.

    Tarda unos 2 minutos, así que se ejecuta una sola vez por sesión: la comparten los
    tests slow de test_engine_validation.py y el de ``motor validar`` en test_cli.py,
    que la recibe con ``monkeypatch`` en lugar de repetirla.
    """
    return validate_engine(load_center(REAL_CENTER), load_profile(REAL_PROFILE), seed=REAL_SEED)
