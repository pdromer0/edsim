"""Validation of the engine: reference queues, operational laws and paired runs.

A service with lambda(t), three pools, priorities and displacement has no
closed formula. It is validated with several kinds of check, each blind to
something (docs/specs/hito-3.md, "Validación del motor"):

- M/G/1: the triage with one nurse, a constant rate and everything else with
  room to spare is an M/G/1 FIFO queue, whose wait is given by
  Pollaczek–Khinchine. It catches waits computed wrong in a FIFO queue.

As in the validation of the arrivals (milestone 2), every hypothesis comes
from the configuration, never from what the engine wrote; the level is
``ALPHA = 0.01``, split among the intervals of a check (Bonferroni); and each
block of the validation uses its own child of the master seed, with child
``i`` for replication ``i``. Each replication is simulated into memory,
reduced to a few numbers and dropped: the events of all the replications are
never kept together.
"""

import dataclasses
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import numpy as np

from edsim.arrivals.profile import ArrivalProfile
from edsim.arrivals.rate import MINUTES_PER_DAY
from edsim.arrivals.validation import ALPHA, ValidationResult
from edsim.engine.analysis import RunAnalysis, analyze_run
from edsim.engine.center import CenterConfig
from edsim.engine.clinical import lognormal_params
from edsim.engine.engine import EDResult, Sampler, simulate_ed
from edsim.engine.events import Event, MemorySink
from edsim.seeds import child_streams
from edsim.stats import Summary, summarize

INFINITE = 10_000
"""Capacity that no run reaches: the pools of the reference queues that must not queue."""

SamplerFactory = Callable[[np.random.SeedSequence], Sampler]
"""Builds the sampler of a replication from its seed; only for the power tests."""


# --- Results ------------------------------------------------------------------------
# ValidationResult is the one of milestone 2, so that the CLI prints both tables
# alike. The helpers that build it there are private to arrivals/, which this
# task does not touch: these are copies (debt for the closing task, a common module).


def _interval_result(name: str, summary: Summary, target: float) -> ValidationResult:
    return ValidationResult(
        name=name,
        statistic=summary.mean,
        p_value=None,
        ci_low=summary.ci_low,
        ci_high=summary.ci_high,
        target=target,
        criterion=f"{target:g} in {100 * summary.confidence:g}% CI",
        passed=summary.ci_low <= target <= summary.ci_high,
        confidence=summary.confidence,
    )


def _all_of(name: str, details: tuple[ValidationResult, ...]) -> ValidationResult:
    """A check made of several intervals: it passes if all of them do.

    The statistic is the number of intervals that miss their target.
    """
    misses = sum(not d.passed for d in details)
    return ValidationResult(
        name=name,
        statistic=float(misses),
        p_value=None,
        ci_low=None,
        ci_high=None,
        target=None,
        criterion=f"all {len(details)} targets in their {100 * details[0].confidence:g}% CI",
        passed=misses == 0,
        details=details,
        confidence=details[0].confidence,
    )


def _check_count(name: str, value: object, minimum: int) -> int:
    # bool is a subclass of int in Python: True must not pass as 1.
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}, got {value!r}")
    return value


def _check_days(days: object, warmup_days: object) -> tuple[int, int]:
    days = _check_count("days", days, 1)
    warmup_days = _check_count("warmup_days", warmup_days, 0)
    if warmup_days >= days:
        raise ValueError(f"warmup_days must be less than days ({days}), got {warmup_days}")
    return days, warmup_days


# --- One replication -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Run:
    """One simulated replication, with its log while it is being reduced."""

    events: list[Event]
    result: EDResult
    analysis: RunAnalysis


def _run(
    center: CenterConfig,
    profile: ArrivalProfile,
    days: int,
    warmup_days: int,
    seed: np.random.SeedSequence,
    sampler: Sampler | None = None,
) -> _Run:
    sink = MemorySink()
    result = simulate_ed(
        center, profile, days, seed, sink=sink, warmup_days=warmup_days, sampler=sampler
    )
    return _Run(sink.events, result, analyze_run(sink.events, center, days, warmup_days))


# --- M/G/1 --------------------------------------------------------------------------------


def flat_profile(daily_base: float = 192, start_date: date = date(2026, 1, 5)) -> ArrivalProfile:
    """A constant rate: every factor 1 and no daily effect (``cv_diario`` 0).

    192 arrivals a day are 8 an hour, the rate of the M/G/1 of the
    specification.
    """
    return ArrivalProfile(
        daily_base=daily_base,
        hour_factors=(1,) * 24,
        weekday_factors=(1,) * 7,
        month_factors=(1,) * 12,
        daily_cv=0.0,
        start_date=start_date,
    )


def mg1_center(center: CenterConfig) -> CenterConfig:
    """The center of the M/G/1: one triage nurse in every shift, and doctors
    and boxes that never queue. The clinical model is the one of ``center``."""
    return dataclasses.replace(
        center, triage_nurses=(1, 1, 1), doctors=(INFINITE,) * 3, boxes=INFINITE
    )


@dataclass(frozen=True, slots=True)
class MG1Theory:
    """Pollaczek–Khinchine for the triage queue.

    Attributes:
        lam: Arrival rate, per minute.
        mean_service: E[S] of the triage time, ``exp(mu + sigma**2 / 2)``.
        second_moment: E[S²], ``exp(2 mu + 2 sigma**2)``.
        rho: ``lam * E[S]``.
        wq: Mean wait in queue, ``lam * E[S²] / (2 (1 - rho))``.
        lq: Mean number in queue, ``lam * wq`` (Little).
    """

    lam: float
    mean_service: float
    second_moment: float
    rho: float
    wq: float
    lq: float


def _constant_rate(profile: ArrivalProfile) -> float:
    """The rate of a flat profile, per minute; ``ValueError`` for any other."""
    factors = (*profile.hour_factors, *profile.weekday_factors, *profile.month_factors)
    if profile.daily_cv != 0 or any(not math.isclose(f, 1, rel_tol=1e-12) for f in factors):
        raise ValueError(
            "the M/G/1 needs a flat profile: every factor 1 and cv_diario 0 (see flat_profile)"
        )
    return profile.daily_base / MINUTES_PER_DAY


def pollaczek_khinchine(center: CenterConfig, profile: ArrivalProfile) -> MG1Theory:
    """Theory of the triage queue of ``center`` with the constant rate of ``profile``.

    The triage time is the lognormal of ``center.triage_time``; with an
    exponential service it would give back the M/M/1 of milestone 1. The
    difference between both is the factor ``(1 + CV²) / 2``: the variability
    of the service, not only its mean, makes the wait.

    Args:
        center: A center with one triage nurse in every shift, such as
            ``mg1_center(...)``.
        profile: A flat profile, such as ``flat_profile()``.

    Raises:
        ValueError: If the profile is not flat, the center has not one
            nurse in every shift, or ``rho >= 1``.
    """
    lam = _constant_rate(profile)
    if center.triage_nurses != (1, 1, 1):
        raise ValueError(
            f"the M/G/1 needs one triage nurse in every shift, got {center.triage_nurses}"
        )
    mu, sigma = lognormal_params(*center.triage_time)
    mean_service = math.exp(mu + sigma**2 / 2)
    second_moment = math.exp(2 * mu + 2 * sigma**2)
    rho = lam * mean_service
    if rho >= 1:
        raise ValueError(f"the M/G/1 is unstable: rho = {rho:.4f} >= 1")
    wq = lam * second_moment / (2 * (1 - rho))
    return MG1Theory(lam, mean_service, second_moment, rho, wq, lam * wq)


@dataclass(frozen=True, slots=True)
class MG1Replicas:
    """What each replication of the M/G/1 gave, for the table and the plot.

    Attributes:
        theory: Pollaczek–Khinchine.
        wq: Mean triage wait of the episodes that arrived in the window and
            departed, one per replication.
        rho: Time average of the busy nurses in the window.
        lq: Time average of the triage queue in the window.
    """

    theory: MG1Theory
    wq: tuple[float, ...]
    rho: tuple[float, ...]
    lq: tuple[float, ...]


def check_mg1(
    center: CenterConfig,
    *,
    replicas: int = 20,
    days: int = 30,
    warmup_days: int = 2,
    seed: int | np.random.SeedSequence,
    daily_base: float = 192,
    sampler_factory: SamplerFactory | None = None,
) -> tuple[ValidationResult, MG1Replicas]:
    """The triage as an M/G/1 against Pollaczek–Khinchine.

    Each replication simulates ``mg1_center(center)`` with
    ``flat_profile(daily_base)`` and measures Wq, ρ and Lq in its window.
    Three intervals, one per metric, at the level ``1 - ALPHA / 3``
    (Bonferroni); the check passes if the theory falls inside all of them.

    Args:
        center: The center whose clinical model is used; its staff is
            replaced by the one of ``mg1_center``.
        replicas: Independent replications, at least 2; child ``i`` of
            ``seed`` for replication ``i``.
        days: Days of each replication, warm-up included.
        warmup_days: Days left out of the window.
        seed: Seed of the block.
        daily_base: Arrivals a day of the flat profile.
        sampler_factory: Builds the sampler of each replication from its
            seed; ``None`` uses the engine's. Only for the power tests: the
            theory always comes from ``center``.

    Returns:
        The result, with the three intervals in ``details``, and the values
        of each replication.

    Raises:
        ValueError: If a count is not valid or the queue is unstable.
    """
    replicas = _check_count("replicas", replicas, 2)
    days, warmup_days = _check_days(days, warmup_days)
    mg1 = mg1_center(center)
    profile = flat_profile(daily_base)
    theory = pollaczek_khinchine(mg1, profile)

    wq, rho, lq = [], [], []
    for child in child_streams(seed, replicas):
        sampler = None if sampler_factory is None else sampler_factory(child)
        metrics = _run(mg1, profile, days, warmup_days, child, sampler).analysis.metrics
        wq.append(metrics.overall.mean["triage_wait"])
        rho.append(metrics.time_averages["nurses_busy"])
        lq.append(metrics.time_averages["waiting_triage"])

    confidence = 1 - ALPHA / 3
    details = (
        _interval_result("wq", summarize(wq, confidence), theory.wq),
        _interval_result("rho", summarize(rho, confidence), theory.rho),
        _interval_result("lq", summarize(lq, confidence), theory.lq),
    )
    result = dataclasses.replace(
        _all_of("mg1", details),
        statistic=details[0].statistic,
        ci_low=details[0].ci_low,
        ci_high=details[0].ci_high,
        target=theory.wq,
    )
    return result, MG1Replicas(theory, tuple(wq), tuple(rho), tuple(lq))
