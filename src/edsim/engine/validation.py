"""Validation of the engine: reference queues, operational laws and paired runs.

A service with lambda(t), three pools, priorities and displacement has no
closed formula. It is validated with several kinds of check, each blind to
something (docs/specs/hito-3.md, "Validación del motor"):

- M/G/1: the triage with one nurse, a constant rate and everything else with
  room to spare is an M/G/1 FIFO queue, whose wait is given by
  Pollaczek–Khinchine. It catches waits computed wrong in a FIFO queue.
- Mₜ/G/∞: with infinite capacity nobody waits, and the census at t is
  Poisson with mean m(t) = ∫ λ(s) · P(stay > t − s) ds. It catches errors in
  the flow with lambda(t). The same runs check an extreme condition: every
  wait is exactly 0 and every stay is exactly the sum of its durations.
- Operational laws, on one long run of the real center: Little's law
  (system, triage queue, box queue) within 2 %, the identity of utilization
  within 1e-9, and the invariants with zero violations. They are not
  statistical: they compare two ways of computing the same thing.
- More doctors with the same seed: every patient is the same (common random
  numbers), so the paired difference of the mean doctor wait must be below 0.

``validate_engine`` runs them all and returns one result per check.

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
from edsim.arrivals.rate import MINUTES_PER_DAY, rate
from edsim.arrivals.thinning import ArrivalRecord
from edsim.arrivals.validation import ALPHA, ValidationResult
from edsim.engine.analysis import RunAnalysis, analyze_run
from edsim.engine.center import CenterConfig
from edsim.engine.clinical import PatientDraws, ProvisionalSampler, lognormal_params
from edsim.engine.engine import EDResult, Sampler, simulate_ed
from edsim.engine.events import Event, MemorySink
from edsim.engine.ground_truth import EpisodeTruth
from edsim.engine.invariants import check_invariants
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


# --- Mₜ/G/∞ ------------------------------------------------------------------------------

HOURS = 24
_MINUTES_PER_HOUR = 60


def infinite_center(center: CenterConfig) -> CenterConfig:
    """The center with every pool at ``INFINITE``: nobody ever queues."""
    return dataclasses.replace(
        center,
        triage_nurses=(INFINITE,) * 3,
        doctors=(INFINITE,) * 3,
        boxes=INFINITE,
    )


def total_stay(draws: PatientDraws) -> float:
    """Stay of a patient who never waits: triage and assessment and, with tests,
    their turnaround and the reassessment (the box is kept while they run)."""
    stay = draws.triage_time + draws.assessment_time
    if draws.needs_tests:
        stay += draws.test_turnaround + draws.reassessment_time
    return stay


def stay_sample(center: CenterConfig, n: int, seed: int | np.random.SeedSequence) -> np.ndarray:
    """``n`` stays without waits, from the engine's own sampler.

    The sampler is called as the engine calls it, with streams 1 to 4 of
    ``child_streams(seed, 4)``; the arrival is not used by the provisional
    model. The seed must be independent of the replications', so that the
    estimate of P(stay > u) and the census compared with it do not share
    numbers.
    """
    sampler = ProvisionalSampler(center, child_streams(seed, 4))
    arrival = ArrivalRecord(0, 0.0)
    return np.array([total_stay(sampler(arrival)) for _ in range(n)])


def offered_load(profile: ArrivalProfile, stays: np.ndarray, horizon: int) -> np.ndarray:
    """m(t) = ∫ λ(s) · P(S > t − s) ds at every whole minute 0..``horizon``, from empty at 0.

    P(S > u) is the share of ``stays`` greater than u. The integral is a
    midpoint sum on a grid of 1 minute::

        m(j) = Σ_k λ(j − k − ½) · P(S > k + ½),   with λ = 0 before 0,

    a convolution done with ``numpy.convolve``. λ comes from ``rate`` of
    milestone 2, without daily effects: every Z is 1. Starting from 0, the
    empty start is part of m(t), as in the simulation.

    Args:
        profile: The arrival profile of the hypothesis.
        stays: A sample of stays, such as ``stay_sample(...)``.
        horizon: Last minute of the grid, a whole number.

    Returns:
        ``horizon + 1`` values: m(0), m(1), ..., m(horizon).
    """
    ordered = np.sort(np.asarray(stays, dtype=float))
    # Survival at the midpoints k + 1/2, until the longest stay.
    midpoints = np.arange(int(math.ceil(ordered[-1])) + 1) + 0.5
    survival = 1 - np.searchsorted(ordered, midpoints, side="right") / ordered.size
    lam = rate(np.arange(horizon) + 0.5, profile)
    load = np.convolve(lam, survival)[:horizon]
    return np.concatenate([[0.0], load])


def hourly_grid_means(values: np.ndarray, start: int, end: int) -> np.ndarray:
    """Mean by hour of the clock of a function given at every whole minute.

    Each hour of each day of ``[start, end]`` is averaged with the trapezoid
    rule, and the days are averaged: one value per hour, 0 h to 23 h.
    ``start`` and ``end`` are whole days, in minutes.
    """
    days = (end - start) // MINUTES_PER_DAY
    segment = np.asarray(values[start : end + 1], dtype=float)
    # Area of each minute, then of each hour, then the mean of each hour over the days.
    per_minute = (segment[:-1] + segment[1:]) / 2
    per_hour = per_minute.reshape(days * HOURS, _MINUTES_PER_HOUR).mean(axis=1)
    return per_hour.reshape(days, HOURS).mean(axis=0)


def _hourly_step_means(analysis: RunAnalysis, name: str, start: float, end: float) -> np.ndarray:
    """Mean by hour of the clock of a step curve, over the days of ``[start, end]``.

    Exact: the area of a step function at any instant is the linear
    interpolation of its cumulative area at the steps.
    """
    curves = analysis.curves
    t = curves.times
    edges = np.append(t, curves.horizon)
    cumulative = np.concatenate([[0.0], np.cumsum(np.diff(edges) * curves[name])])
    hours = np.arange(start, end + 1, _MINUTES_PER_HOUR, dtype=float)
    area = np.diff(np.interp(hours, edges, cumulative))
    return (area / _MINUTES_PER_HOUR).reshape(-1, HOURS).mean(axis=0)


@dataclass(frozen=True, slots=True)
class HourlyCensus:
    """Census by hour of the clock against m(t), for the table and the plot.

    Attributes:
        expected: m(t) averaged by hour, as the census, from 0 h to 23 h.
        census: Mean census by hour of each replication, one row each.
        ci_low: Lower bound of the interval of each hour.
        ci_high: Upper bound.
    """

    expected: np.ndarray
    census: np.ndarray
    ci_low: np.ndarray
    ci_high: np.ndarray


def _exact_infinite_capacity(run: _Run) -> int:
    """Episodes of a run without queues whose log is not exact.

    Every wait must be exactly 0, and the departure must be the arrival of
    the log plus the durations of the ground truth, added in the order the
    engine waits them (as ``test_capacidad_infinita_sin_esperas``).
    """
    truth: dict[str, EpisodeTruth] = {e.episode_id: e for e in run.result.ground_truth.episodes}
    wrong = 0
    for episode in run.analysis.table:
        draws = truth[episode.episode_id]
        waits = (episode.triage_wait, episode.box_wait, episode.doctor_wait)
        if any(w is not None and w != 0 for w in waits):
            wrong += 1
            continue
        if episode.departure is None:
            continue
        t = episode.arrival + draws.triage_time
        t += draws.assessment_time
        if draws.needs_tests:
            t += draws.test_turnaround
            t += draws.reassessment_time
        wrong += episode.departure != t
    return wrong


def check_infinite_server(
    center: CenterConfig,
    profile: ArrivalProfile,
    *,
    replicas: int = 20,
    days: int = 14,
    warmup_days: int = 2,
    seed: int | np.random.SeedSequence,
    stay_seed: int | np.random.SeedSequence,
    n_stays: int = 200_000,
    hypothesis: ArrivalProfile | None = None,
) -> tuple[ValidationResult, ValidationResult, HourlyCensus]:
    """The center without queues as an Mₜ/G/∞, against m(t).

    Each replication simulates ``infinite_center(center)`` with ``profile``
    without daily effect (``cv_diario`` 0) and measures the mean census of
    each hour of the clock over the days of its window. m(t) is averaged the
    same way, with P(stay > u) from ``n_stays`` draws of the sampler with
    ``stay_seed``. One interval per hour at ``1 - ALPHA / 24`` (Bonferroni):
    the check passes if m(t) falls inside all of them.

    The same runs give the extreme condition "infinite capacity": no wait and
    every stay exactly the sum of its durations, in every replication.

    Args:
        center: The center whose clinical model is used.
        profile: The profile of the simulation; its ``cv_diario`` is set to 0.
        replicas: Independent replications, at least 2.
        days: Days of each replication, warm-up included.
        warmup_days: Days left out of the window.
        seed: Seed of the replications; child ``i`` for replication ``i``.
        stay_seed: Seed of the sample of stays, independent of ``seed``.
        n_stays: Size of the sample of stays, at least 1000.
        hypothesis: Profile of m(t); ``profile`` if ``None``. Only for the
            power tests: it never changes the simulation.

    Returns:
        The result of the Mₜ/G/∞ (statistic: hours outside their interval,
        with the 24 intervals in ``details``), the result of the infinite
        capacity (statistic: inexact episodes over all the replications) and
        the census by hour.
    """
    replicas = _check_count("replicas", replicas, 2)
    days, warmup_days = _check_days(days, warmup_days)
    n_stays = _check_count("n_stays", n_stays, 1000)
    no_z = dataclasses.replace(profile, daily_cv=0.0)
    hypothesis = no_z if hypothesis is None else dataclasses.replace(hypothesis, daily_cv=0.0)
    infinite = infinite_center(center)
    start, end = warmup_days * MINUTES_PER_DAY, days * MINUTES_PER_DAY

    stays = stay_sample(center, n_stays, stay_seed)
    expected = hourly_grid_means(offered_load(hypothesis, stays, end), start, end)

    census, wrong = [], 0
    for child in child_streams(seed, replicas):
        run = _run(infinite, no_z, days, warmup_days, child)
        census.append(_hourly_step_means(run.analysis, "census", start, end))
        wrong += _exact_infinite_capacity(run)
    census = np.array(census)

    confidence = 1 - ALPHA / HOURS
    details = tuple(
        _interval_result(f"{h:02d}h", summarize(census[:, h], confidence), float(expected[h]))
        for h in range(HOURS)
    )
    exact = ValidationResult(
        name="infinite_capacity",
        statistic=float(wrong),
        p_value=None,
        ci_low=None,
        ci_high=None,
        target=0.0,
        criterion="no wait and exact stays (0 episodes wrong)",
        passed=wrong == 0,
    )
    hourly = HourlyCensus(
        expected=expected,
        census=census,
        ci_low=np.array([d.ci_low for d in details]),
        ci_high=np.array([d.ci_high for d in details]),
    )
    return _all_of("mtginf", details), exact, hourly


# --- Operational laws -------------------------------------------------------------------

LITTLE_TOLERANCE = 0.02
"""Largest relative error of Little's law on the long run."""

UTILIZATION_TOLERANCE = 1e-9
"""Largest relative error of the identity of utilization: rounding only."""


def _tolerance_result(name: str, error: float, tolerance: float) -> ValidationResult:
    return ValidationResult(
        name=name,
        statistic=float(error),
        p_value=None,
        ci_low=None,
        ci_high=None,
        target=None,
        criterion=f"relative error <= {tolerance:g}",
        passed=bool(error <= tolerance),
    )


def check_operational_laws(
    center: CenterConfig,
    profile: ArrivalProfile,
    *,
    days: int = 28,
    warmup_days: int = 2,
    seed: int | np.random.SeedSequence,
) -> tuple[ValidationResult, ...]:
    """Invariants, Little's law and the identity of utilization on one long run.

    Returns:
        ``invariants`` (statistic: violations), ``little_system``,
        ``little_triage_queue``, ``little_box_queue`` and one
        ``utilization_<pool>`` per pool (statistic: relative error).
    """
    days, warmup_days = _check_days(days, warmup_days)
    run = _run(center, profile, days, warmup_days, seed)
    violations = check_invariants(
        run.events, center, ground_truth=run.result.ground_truth, inside=run.result.inside
    )
    invariants = ValidationResult(
        name="invariants",
        statistic=float(len(violations)),
        p_value=None,
        ci_low=None,
        ci_high=None,
        target=0.0,
        criterion="0 violations",
        passed=not violations,
    )
    return (
        invariants,
        *(
            _tolerance_result(f"little_{law.name}", law.relative_error, LITTLE_TOLERANCE)
            for law in run.analysis.little
        ),
        *(
            _tolerance_result(f"utilization_{u.pool}", u.relative_error, UTILIZATION_TOLERANCE)
            for u in run.analysis.utilization
        ),
    )


# --- More doctors -------------------------------------------------------------------------


def check_more_doctors(
    center: CenterConfig,
    profile: ArrivalProfile,
    *,
    extra: int = 2,
    replicas: int = 10,
    days: int = 14,
    warmup_days: int = 2,
    seed: int | np.random.SeedSequence,
) -> ValidationResult:
    """More doctors with the same seed lower the mean doctor wait.

    Each replication runs ``center`` and the same center with ``extra`` more
    doctors in every shift, with the same seed: the arrivals and the draws of
    every patient are the same, only the waits change. The difference of the
    mean ``doctor_wait`` (more doctors minus base) is paired, so the noise of
    the patients cancels out. Its interval at ``1 - ALPHA`` must lie entirely
    below 0, and the ground truth of the episodes must be identical in every
    pair.

    Returns:
        The result, with the mean difference in minutes and its interval
        (``target`` 0, which the interval must stay below).
    """
    extra = _check_count("extra", extra, 1)
    replicas = _check_count("replicas", replicas, 2)
    days, warmup_days = _check_days(days, warmup_days)
    more = dataclasses.replace(center, doctors=tuple(d + extra for d in center.doctors))

    differences, same_patients = [], True
    for child in child_streams(seed, replicas):
        base = _run(center, profile, days, warmup_days, child)
        plus = _run(more, profile, days, warmup_days, child)
        same_patients &= base.result.ground_truth.episodes == plus.result.ground_truth.episodes
        differences.append(
            plus.analysis.metrics.overall.mean["doctor_wait"]
            - base.analysis.metrics.overall.mean["doctor_wait"]
        )

    summary = summarize(differences, 1 - ALPHA)
    return ValidationResult(
        name="more_doctors",
        statistic=summary.mean,
        p_value=None,
        ci_low=summary.ci_low,
        ci_high=summary.ci_high,
        target=0.0,
        criterion=f"{100 * summary.confidence:g}% CI < 0 and the same patients",
        passed=bool(summary.ci_high < 0 and same_patients),
        confidence=summary.confidence,
    )


# --- The whole validation -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EngineValidation:
    """Result of ``validate_engine``, with what the plots need.

    Attributes:
        results: One per check: invariants, Little (3), utilization (3),
            M/G/1, Mₜ/G/∞, infinite capacity and more doctors.
        mg1: The values of each replication of the M/G/1 and its theory.
        hourly: The census by hour against m(t).
    """

    results: tuple[ValidationResult, ...]
    mg1: MG1Replicas
    hourly: HourlyCensus

    @property
    def passed(self) -> bool:
        """Whether every check passes."""
        return all(r.passed for r in self.results)

    def result(self, name: str) -> ValidationResult:
        """Return the result of the check called ``name``."""
        for r in self.results:
            if r.name == name:
                return r
        raise KeyError(name)


def validate_engine(
    center: CenterConfig,
    profile: ArrivalProfile,
    seed: int | np.random.SeedSequence = 2026,
    *,
    replicas: int = 20,
    mg1_days: int = 30,
    mtginf_days: int = 14,
    long_days: int = 28,
    paired_replicas: int = 10,
    paired_days: int = 14,
    warmup_days: int = 2,
    n_stays: int = 200_000,
) -> EngineValidation:
    """Run every check of the engine.

    ``child_streams(seed, 5)`` gives one child per block: the M/G/1, the
    Mₜ/G/∞, the long run, the more-doctors pairs and the sample of stays.
    So each block depends only on the master seed and its index, and the
    sample of stays is independent of the replications it is compared with.

    Args:
        center: The center: the long run and the pairs use it as it is; the
            reference queues take its clinical model.
        profile: The arrival profile, such as ``config/llegadas.toml``.
        seed: Master seed.
        replicas: Replications of the M/G/1 and the Mₜ/G/∞.
        mg1_days: Days of each replication of the M/G/1.
        mtginf_days: Days of each replication of the Mₜ/G/∞.
        long_days: Days of the long run of the operational laws.
        paired_replicas: Pairs of runs with more doctors.
        paired_days: Days of each run of a pair.
        warmup_days: Warm-up of every run, in days.
        n_stays: Size of the sample of stays of m(t).

    Raises:
        ValueError: If a count is not valid; checked before simulating.
    """
    replicas = _check_count("replicas", replicas, 2)
    paired_replicas = _check_count("paired_replicas", paired_replicas, 2)
    n_stays = _check_count("n_stays", n_stays, 1000)
    for days in (mg1_days, mtginf_days, long_days, paired_days):
        _check_days(days, warmup_days)

    mg1_seed, mtginf_seed, long_seed, paired_seed, stay_seed = child_streams(seed, 5)
    laws = check_operational_laws(
        center, profile, days=long_days, warmup_days=warmup_days, seed=long_seed
    )
    mg1, mg1_replicas = check_mg1(
        center, replicas=replicas, days=mg1_days, warmup_days=warmup_days, seed=mg1_seed
    )
    mtginf, infinite, hourly = check_infinite_server(
        center,
        profile,
        replicas=replicas,
        days=mtginf_days,
        warmup_days=warmup_days,
        seed=mtginf_seed,
        stay_seed=stay_seed,
        n_stays=n_stays,
    )
    more_doctors = check_more_doctors(
        center,
        profile,
        replicas=paired_replicas,
        days=paired_days,
        warmup_days=warmup_days,
        seed=paired_seed,
    )
    return EngineValidation(
        results=(*laws, mg1, mtginf, infinite, more_doctors), mg1=mg1_replicas, hourly=hourly
    )
