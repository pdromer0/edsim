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
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy import stats

from edsim.arrivals.profile import ArrivalProfile
from edsim.arrivals.rate import MINUTES_PER_DAY, cumulative_rate
from edsim.arrivals.thinning import ArrivalRecord, DayRecord
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
    )


def check_hourly_shape(
    profile: ArrivalProfile, arrivals: Sequence[ArrivalRecord], days: Sequence[DayRecord]
) -> ValidationResult:
    """Test b: the hourly shape, with a chi-square test by hour of the clock.

    The arrivals of all the days are counted by hour of the clock (24
    counts). The expected count of each hour is the area of lambda in that
    hour, with the Z of each day, added over the days and scaled to the total
    observed: the test checks the shape, and test a the volume. With the
    total fixed, there are 23 degrees of freedom.

    Args:
        profile: The profile of the hypothesis.
        arrivals: Arrivals of one run.
        days: Day records of the same run, from day 0, for their Z.

    Returns:
        The result, with the chi-square statistic and its p-value.
    """
    effects = _day_effects(days)
    minutes = _times(arrivals) % MINUTES_PER_DAY
    hours = np.minimum(minutes // _MINUTES_PER_HOUR, _HOURS - 1).astype(np.int64)
    observed = np.bincount(hours, minlength=_HOURS)

    edges = np.arange(effects.size * _HOURS + 1) * _MINUTES_PER_HOUR
    per_hour = np.diff(cumulative_rate(edges, profile, day_effects=effects))
    expected = per_hour.reshape(effects.size, _HOURS).sum(axis=0)
    expected *= observed.sum() / expected.sum()

    statistic, p_value = stats.chisquare(observed, expected)
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
