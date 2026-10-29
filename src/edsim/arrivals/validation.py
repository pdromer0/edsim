"""Statistical validation of generated arrivals against their profile.

Five tests check that the arrivals are a non-homogeneous Poisson process with
the configured lambda(t); each one looks for a different kind of error:

a. volume: observed / expected arrivals per day, in total and per weekday.
b. hourly shape: arrivals per hour of the clock, with a chi-square test.
c. rescaled gaps: the gaps of Lambda(t_i) against an exponential of mean 1,
   with a Kolmogorov–Smirnov test.
d. dispersion: Pearson's index of the daily counts in R replications,
   against its theory, with and without Z.
e. uniformity of the p-values of c over many short runs, with a
   Kolmogorov–Smirnov test against U(0, 1).

All of them use the level ``ALPHA = 0.01``: with five tests at 5 %, a correct
generator would raise some false alarm in 23 % of the validations; at 1 %, in
5 %. A test with several confidence intervals splits ALPHA among them
(Bonferroni), so that the whole test still fails 1 % of the times by chance.

**The hypothesis comes from the profile; the records give only the facts and
Z.** Every expected value (per day, per hour, Lambda at each arrival) is
computed from the profile passed to the test, with ``cumulative_rate``. From
the records the tests take only what was observed (arrival times, accepted
arrivals per day) and the daily effect Z, which is ground truth and cannot be
derived from the profile. ``DayRecord.expected`` is never used: the generator
wrote it with the profile *it* used, so a test based on it would compare the
generator with itself. Arrivals generated with a base of 330 and validated
against 300 would always pass, and no power test could fail.

The tests are pure: they take records and a profile and do not simulate.
``validate_arrivals`` runs the whole validation from a profile and a master
seed: one long run for a–c, R replications for d and short runs for e, each
block with its own child of the seed.
"""

import collections
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy import stats

from edsim.arrivals.profile import ArrivalProfile
from edsim.arrivals.rate import MINUTES_PER_DAY, cumulative_rate
from edsim.arrivals.thinning import ArrivalRecord, DayRecord, iter_arrivals, simulate_arrivals
from edsim.seeds import child_streams
from edsim.stats import Summary, summarize

ALPHA = 0.01
"""Level of every test: a correct generator fails each one 1 % of the times."""

WEEKDAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

MIN_DAYS = 14
"""Fewest days for the volume test: two of each weekday, for a confidence interval."""

_HOURS = 24
_MINUTES_PER_HOUR = 60


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Outcome of one validation test.

    Named ``ValidationResult`` and not ``TestResult``: pytest tries to collect
    every class called ``Test*`` that a test module imports.

    Attributes:
        name: Key of the test, such as ``"volume"``, or of a part of it, such
            as ``"monday"``.
        statistic: The test statistic: a mean ratio, a chi-square value, a
            Kolmogorov–Smirnov distance or a dispersion index.
        p_value: P-value, for the tests decided by one (``None`` otherwise).
        ci_low: Lower bound of the confidence interval, for the tests decided
            by one (``None`` otherwise).
        ci_high: Upper bound of the confidence interval.
        target: Value that must fall inside the interval (``None`` for the
            tests decided by a p-value).
        criterion: The pass condition, such as ``"p >= 0.01"`` or
            ``"1 in 99.875% CI"``.
        passed: Whether the test passes; with ``details``, whether all of
            them pass.
        details: Parts of the test, when it has several intervals.
        confidence: Level of the confidence interval, such as ``0.99875``,
            for the tests decided by one (``None`` otherwise).
    """

    name: str
    statistic: float
    p_value: float | None
    ci_low: float | None
    ci_high: float | None
    target: float | None
    criterion: str
    passed: bool
    details: tuple["ValidationResult", ...] = ()
    confidence: float | None = None


def _p_value_result(name: str, statistic: float, p_value: float) -> ValidationResult:
    return ValidationResult(
        name=name,
        statistic=float(statistic),
        p_value=float(p_value),
        ci_low=None,
        ci_high=None,
        target=None,
        criterion=f"p >= {ALPHA:g}",
        passed=bool(p_value >= ALPHA),
    )


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


def _day_effects(days: Sequence[DayRecord]) -> NDArray[np.float64]:
    """The Z of each day from day 0, the only ground truth the tests use."""
    return np.array([d.day_effect for d in days], dtype=float)


def _times(arrivals: Sequence[ArrivalRecord]) -> NDArray[np.float64]:
    return np.array([a.time for a in arrivals], dtype=float)


def expected_per_day(profile: ArrivalProfile, n_days: int) -> NDArray[np.float64]:
    """Expected arrivals of each day without Z, from the profile alone.

    It is Lambda at the end of each day minus at its start, with every Z = 1:
    ``day_scale * day_shape_area``.

    Args:
        profile: The profile of the hypothesis.
        n_days: Number of days, from day 0.

    Returns:
        The expected arrivals of days ``0 .. n_days - 1``.
    """
    ends = np.arange(n_days + 1) * MINUTES_PER_DAY
    return np.diff(cumulative_rate(ends, profile))


def check_volume(profile: ArrivalProfile, days: Sequence[DayRecord]) -> ValidationResult:
    """Test a: the volume of arrivals, in total and per weekday.

    The ratio of each day is its accepted arrivals over its expected arrivals
    without Z, from the profile. Z has mean 1, so the ratios have mean 1 with
    or without overdispersion; Z only widens the interval. The test builds
    eight intervals with ``summarize`` (all the days, then Monday to Sunday),
    each at the level ``1 - ALPHA / 8`` (Bonferroni), and passes if all of
    them contain 1.

    Args:
        profile: The profile of the hypothesis.
        days: Day records of one run, from day 0, at least ``MIN_DAYS``.

    Returns:
        The result, with the mean ratio and interval of all the days, and the
        eight intervals in ``details``.

    Raises:
        ValueError: If there are fewer than ``MIN_DAYS`` days.
    """
    if len(days) < MIN_DAYS:
        raise ValueError(
            f"the volume test needs at least {MIN_DAYS} days (two of each weekday), got {len(days)}"
        )
    index = np.array([d.day for d in days])
    accepted = np.array([d.accepted for d in days], dtype=float)
    ratios = accepted / expected_per_day(profile, int(index.max()) + 1)[index]
    weekdays = (index + profile.start_date.weekday()) % 7

    confidence = 1 - ALPHA / (1 + len(WEEKDAY_NAMES))
    details = (
        _interval_result("total", summarize(ratios, confidence), 1.0),
        *(
            _interval_result(name, summarize(ratios[weekdays == k], confidence), 1.0)
            for k, name in enumerate(WEEKDAY_NAMES)
        ),
    )
    total = details[0]
    return ValidationResult(
        name="volume",
        statistic=total.statistic,
        p_value=None,
        ci_low=total.ci_low,
        ci_high=total.ci_high,
        target=1.0,
        criterion=total.criterion,
        passed=all(d.passed for d in details),
        details=details,
        confidence=total.confidence,
    )


def hour_of_day(times: ArrayLike) -> NDArray[np.int64]:
    """Hour of the clock, 0 to 23, of times in minutes since the start date.

    The hour is ``floor(minute of the day / 60)``, capped at 23 so that a
    time that rounds to the end of a day stays in hour 23.
    """
    minutes = np.asarray(times, dtype=float) % MINUTES_PER_DAY
    return np.minimum(minutes // _MINUTES_PER_HOUR, _HOURS - 1).astype(np.int64)


def interval_counts(
    profile: ArrivalProfile,
    arrivals: Sequence[ArrivalRecord],
    days: Sequence[DayRecord],
    *,
    width: int = 60,
) -> tuple[NDArray[np.int64], NDArray[np.int64], NDArray[np.float64]]:
    """Observed and expected arrivals in consecutive intervals of the whole run.

    The days are cut into intervals of ``width`` minutes, from day 0 to the
    end of the last day. An arrival counts in the interval of its minute of
    the day, with the same rule as ``hour_of_day``: a time that rounds to the
    end of a day stays in its last interval. The expected count of each
    interval is the area of lambda in it, ``Lambda(end) - Lambda(start)``,
    with the Z of each day: the mean of a Poisson count, not rescaled.

    Args:
        profile: The profile of the hypothesis.
        arrivals: Arrivals of one run.
        days: Day records of the same run, from day 0, for their Z.
        width: Minutes per interval; a positive integer that divides 1440.

    Returns:
        The interval edges in minutes (one more than intervals), and the
        observed and expected arrivals of each interval.

    Raises:
        ValueError: If ``width`` does not divide 1440 or an arrival falls
            outside the days.
    """
    # bool is a subclass of int in Python: True must not pass as 1 minute.
    if (
        isinstance(width, bool)
        or not isinstance(width, int)
        or width < 1
        or MINUTES_PER_DAY % width
    ):
        raise ValueError(f"width must be a positive integer that divides 1440, got {width!r}")
    effects = _day_effects(days)
    per_day = MINUTES_PER_DAY // width
    n = effects.size * per_day

    times = _times(arrivals)
    day = (times // MINUTES_PER_DAY).astype(np.int64)
    if day.size and (day.min() < 0 or day.max() >= effects.size):
        raise ValueError("every arrival must fall on one of the days")
    slot = np.minimum((times % MINUTES_PER_DAY) // width, per_day - 1).astype(np.int64)
    observed = np.bincount(day * per_day + slot, minlength=n)

    edges = np.arange(n + 1) * width
    expected = np.diff(cumulative_rate(edges, profile, day_effects=effects))
    return edges, observed, expected


def hourly_counts(
    profile: ArrivalProfile, arrivals: Sequence[ArrivalRecord], days: Sequence[DayRecord]
) -> tuple[NDArray[np.int64], NDArray[np.float64]]:
    """Observed and expected arrivals by hour of the clock, as compared in test b.

    The arrivals of all the days are counted by hour of the clock (24
    counts). The expected count of each hour is the area of lambda in that
    hour, with the Z of each day, added over the days and scaled to the total
    observed, so that it compares the shape and not the volume.

    Args:
        profile: The profile of the hypothesis.
        arrivals: Arrivals of one run.
        days: Day records of the same run, from day 0, for their Z.

    Returns:
        The 24 observed counts and the 24 expected counts, from 0 h to 23 h;
        both add up to the number of arrivals.
    """
    _, per_hour, expected_per_hour = interval_counts(
        profile, arrivals, days, width=_MINUTES_PER_HOUR
    )
    observed = per_hour.reshape(-1, _HOURS).sum(axis=0)
    expected = expected_per_hour.reshape(-1, _HOURS).sum(axis=0)
    expected *= observed.sum() / expected.sum()
    return observed, expected


def check_hourly_shape(
    profile: ArrivalProfile, arrivals: Sequence[ArrivalRecord], days: Sequence[DayRecord]
) -> ValidationResult:
    """Test b: the hourly shape, with a chi-square test by hour of the clock.

    A chi-square test of ``hourly_counts``: the test checks the shape, and
    test a the volume. With the total fixed, there are 23 degrees of freedom.

    Args:
        profile: The profile of the hypothesis.
        arrivals: Arrivals of one run.
        days: Day records of the same run, from day 0, for their Z.

    Returns:
        The result, with the chi-square statistic and its p-value.
    """
    statistic, p_value = stats.chisquare(*hourly_counts(profile, arrivals, days))
    return _p_value_result("hourly_shape", statistic, p_value)


def rescaled_gaps(
    profile: ArrivalProfile, arrivals: Sequence[ArrivalRecord], days: Sequence[DayRecord]
) -> NDArray[np.float64]:
    """Gaps between the rescaled times Lambda(t_i), with the Z of each day.

    If the arrivals are a Poisson process with rate lambda(t), the times
    Lambda(t_i) are a Poisson process with rate 1 (time-rescaling theorem):
    their gaps are exponential with mean 1. The first gap is measured from 0.

    Args:
        profile: The profile of the hypothesis.
        arrivals: Arrivals of one run.
        days: Day records of the same run, from day 0, for their Z.

    Returns:
        One gap per arrival.
    """
    rescaled = cumulative_rate(_times(arrivals), profile, day_effects=_day_effects(days))
    return np.diff(rescaled, prepend=0.0)


def check_rescaled_gaps(
    profile: ArrivalProfile, arrivals: Sequence[ArrivalRecord], days: Sequence[DayRecord]
) -> ValidationResult:
    """Test c: the rescaled gaps against an exponential of mean 1.

    A Kolmogorov–Smirnov test of ``rescaled_gaps``. It detects badly drawn
    gaps, a wrong bound or acceptance, and errors at the borders of the days.

    Args:
        profile: The profile of the hypothesis.
        arrivals: Arrivals of one run.
        days: Day records of the same run, from day 0, for their Z.

    Returns:
        The result, with the Kolmogorov–Smirnov distance and its p-value.
    """
    statistic, p_value = stats.kstest(rescaled_gaps(profile, arrivals, days), "expon")
    return _p_value_result("rescaled_gaps", statistic, p_value)


def _counts_and_expected(
    profile: ArrivalProfile, days: Sequence[DayRecord]
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Accepted arrivals and expected arrivals without Z of each day."""
    index = np.array([d.day for d in days])
    counts = np.array([d.accepted for d in days], dtype=float)
    return counts, expected_per_day(profile, int(index.max()) + 1)[index]


def pearson_index(profile: ArrivalProfile, days: Sequence[DayRecord]) -> float:
    """Pearson's dispersion index of the daily counts, with expected values without Z.

    ``P = mean of (c - e)**2 / e`` over the days, with ``e`` from the profile
    alone. Given Z, a day is Poisson with mean ``Z * e``; over the gamma,
    ``Var(c) = e + CV**2 * e**2``, so ``E[P] = 1 + CV**2 * mean(e)``: 1 without
    Z, and about 2.08 with CV 0.06 and 300 arrivals a day.

    Args:
        profile: The profile of the hypothesis.
        days: Day records of one run, from day 0.

    Returns:
        The index P.
    """
    counts, expected = _counts_and_expected(profile, days)
    return float(np.mean((counts - expected) ** 2 / expected))


def conditional_pearson_index(profile: ArrivalProfile, days: Sequence[DayRecord]) -> float:
    """Pearson's index given Z: expected values ``Z * e``, with the Z of the records.

    Given Z, each day is Poisson with mean ``Z * e``, so the theory is 1 with
    or without overdispersion. Together with ``pearson_index``, it tells the
    errors in Z (only the index without Z is off) from the errors in the
    Poisson of each day (both are off).

    Args:
        profile: The profile of the hypothesis.
        days: Day records of one run, from day 0, for their counts and Z.

    Returns:
        The conditional index.
    """
    counts, expected = _counts_and_expected(profile, days)
    expected = expected * _day_effects(days)
    return float(np.mean((counts - expected) ** 2 / expected))


def daily_residuals(
    profile: ArrivalProfile, days: Sequence[DayRecord]
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Standardized residuals of the daily counts, given Z and without Z.

    With ``e`` the expected arrivals of a day without Z, from the profile:

    - given Z: ``(c - Z * e) / sqrt(Z * e)``, the Poisson of each day;
    - without Z: ``(c - e) / sqrt(e + CV**2 * e**2)``, the negative binomial
      over the gamma, with the profile's ``daily_cv``.

    Under the hypothesis both have mean 0 and variance 1, and with about 300
    arrivals a day they are close to a standard normal. The raw counts are
    not compared with one distribution because each day has its own mean.
    The mean of the squared residuals given Z is
    ``conditional_pearson_index``.

    Args:
        profile: The profile of the hypothesis.
        days: Day records of one run, from day 0, for their counts and Z.

    Returns:
        The residuals given Z and without Z, one per day.
    """
    counts, expected = _counts_and_expected(profile, days)
    given_z = expected * _day_effects(days)
    conditional = (counts - given_z) / np.sqrt(given_z)
    unconditional = (counts - expected) / np.sqrt(expected + profile.daily_cv**2 * expected**2)
    return conditional, unconditional


def check_dispersion(
    profile: ArrivalProfile, replications: Sequence[Sequence[DayRecord]]
) -> ValidationResult:
    """Test d: the daily dispersion, with Pearson's index in replications.

    Estimating a variance needs many days (with one year, the daily variance
    has an error of about 7 %), so the test computes both indexes in each
    independent replication and builds a confidence interval with
    ``summarize``:

    - without Z (``pearson_index``): the theory ``1 + CV**2 * mean(e)``, with
      the profile's ``daily_cv``, must fall inside;
    - given Z (``conditional_pearson_index``): 1 must fall inside.

    Each interval is at the level ``1 - ALPHA / 2`` (Bonferroni), and the
    test passes if both contain their theory.

    Args:
        profile: The profile of the hypothesis, whose ``daily_cv`` sets the
            theory.
        replications: Day records of each replication, at least 2.

    Returns:
        The result, with the mean index without Z and its interval, and both
        intervals in ``details``.

    Raises:
        ValueError: If there are fewer than 2 replications.
    """
    if len(replications) < 2:
        raise ValueError(
            f"the dispersion test needs at least 2 replications, got {len(replications)}"
        )
    mean_expected = float(
        np.mean(np.concatenate([_counts_and_expected(profile, r)[1] for r in replications]))
    )
    theory = 1 + profile.daily_cv**2 * mean_expected

    confidence = 1 - ALPHA / 2
    details = (
        _interval_result(
            "unconditional",
            summarize((pearson_index(profile, r) for r in replications), confidence),
            theory,
        ),
        _interval_result(
            "conditional",
            summarize((conditional_pearson_index(profile, r) for r in replications), confidence),
            1.0,
        ),
    )
    unconditional = details[0]
    return ValidationResult(
        name="dispersion",
        statistic=unconditional.statistic,
        p_value=None,
        ci_low=unconditional.ci_low,
        ci_high=unconditional.ci_high,
        target=theory,
        criterion=unconditional.criterion,
        passed=all(d.passed for d in details),
        details=details,
        confidence=unconditional.confidence,
    )


def p_value_uniformity(p_values: Sequence[float] | NDArray[np.float64]) -> ValidationResult:
    """Kolmogorov–Smirnov test of p-values against a uniform on (0, 1).

    With a correct generator, the p-value of a test is uniform: 1 % of the
    runs give p < 0.01 by chance. Small biases that one run cannot see pile
    the p-values up near 0.

    Args:
        p_values: P-values of independent runs.

    Returns:
        The result ``"p_uniformity"``, with the Kolmogorov–Smirnov distance
        and its p-value.
    """
    statistic, p_value = stats.kstest(np.asarray(p_values, dtype=float), "uniform")
    return _p_value_result("p_uniformity", statistic, p_value)


def check_p_uniformity(
    profile: ArrivalProfile,
    runs: Sequence[tuple[Sequence[ArrivalRecord], Sequence[DayRecord]]],
) -> ValidationResult:
    """Test e: the p-values of test c over many short runs are uniform.

    Args:
        profile: The profile of the hypothesis.
        runs: Arrivals and day records of each independent run.

    Returns:
        The result of ``p_value_uniformity`` on the p-values of test c.
    """
    return p_value_uniformity(
        [check_rescaled_gaps(profile, arrivals, days).p_value for arrivals, days in runs]
    )


@dataclass(frozen=True, slots=True)
class ArrivalValidation:
    """Result of a whole validation, with the records it used.

    Attributes:
        results: Tests a to e, in that order.
        arrivals: Arrivals of the long run of tests a to c.
        days: Day records of the long run.
        replications: Day records of each replication of test d; their
            arrivals are not kept.
    """

    results: tuple[ValidationResult, ...]
    arrivals: tuple[ArrivalRecord, ...]
    days: tuple[DayRecord, ...]
    replications: tuple[tuple[DayRecord, ...], ...]

    @property
    def passed(self) -> bool:
        """Whether all the tests pass."""
        return all(r.passed for r in self.results)

    def result(self, name: str) -> ValidationResult:
        """Return the result of the test called ``name``."""
        for r in self.results:
            if r.name == name:
                return r
        raise KeyError(name)


def _check_count(name: str, value: object, minimum: int) -> int:
    # bool is a subclass of int in Python: True must not pass as 1.
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}, got {value!r}")
    return value


def _days_only(
    profile: ArrivalProfile, days: int, seed: np.random.SeedSequence
) -> tuple[DayRecord, ...]:
    """Day records of a run, consuming its arrivals without keeping them."""
    records: list[DayRecord] = []
    collections.deque(iter_arrivals(profile, days, seed, on_day=records.append), maxlen=0)
    return tuple(records)


def validate_arrivals(
    profile: ArrivalProfile,
    days: int = 364,
    replicas: int = 20,
    seed: int | np.random.SeedSequence = 2026,
    *,
    short_runs: int = 100,
    short_days: int = 14,
    hypothesis: ArrivalProfile | None = None,
) -> ArrivalValidation:
    """Generate arrivals with ``profile`` and run the five tests against a hypothesis.

    The hypothesis is ``profile`` itself unless ``hypothesis`` is given. A
    different one measures the power of the tests: arrivals generated with a
    base of 330 and validated against 300 must fail test a.

    ``child_streams(seed, 3)`` gives one child per block: the long run of
    ``days`` days (tests a to c), the ``replicas`` replications of ``days``
    days (test d) and the ``short_runs`` runs of ``short_days`` days (test e).
    Within a block, run ``i`` uses child ``i`` of the block's seed. So each
    run depends only on the master seed, its block and its index: the same
    seed reproduces the validation, and adding replications or short runs
    keeps the long run and the earlier runs.

    Args:
        profile: The profile used to generate the arrivals.
        days: Days of the long run and of each replication, at least
            ``MIN_DAYS``.
        replicas: Replications for test d, at least 2.
        seed: Master seed: an integer or a ``numpy.random.SeedSequence``.
        short_runs: Short runs for test e, at least 2.
        short_days: Days of each short run, at least 1.
        hypothesis: The profile the tests compare with; ``profile`` if
            ``None``. It only changes the tests, never the records.

    Returns:
        The results of the five tests and the records they used.

    Raises:
        ValueError: If an argument is not a valid integer.
    """
    days = _check_count("days", days, MIN_DAYS)
    replicas = _check_count("replicas", replicas, 2)
    short_runs = _check_count("short_runs", short_runs, 2)
    short_days = _check_count("short_days", short_days, 1)

    long_seq, replicas_seq, short_seq = child_streams(seed, 3)
    arrivals, day_records = simulate_arrivals(profile, days, long_seq)
    replications = tuple(
        _days_only(profile, days, child) for child in child_streams(replicas_seq, replicas)
    )
    runs = [
        simulate_arrivals(profile, short_days, child)
        for child in child_streams(short_seq, short_runs)
    ]

    if hypothesis is None:
        hypothesis = profile
    results = (
        check_volume(hypothesis, day_records),
        check_hourly_shape(hypothesis, arrivals, day_records),
        check_rescaled_gaps(hypothesis, arrivals, day_records),
        check_dispersion(hypothesis, replications),
        check_p_uniformity(hypothesis, runs),
    )
    return ArrivalValidation(
        results=results, arrivals=arrivals, days=day_records, replications=replications
    )
