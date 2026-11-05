"""Statistical checks of the sampler without the engine: the mix and the triage.

**The mix** (``check_mixing``).

For each context, the sampler draws many patients at one time of that context,
and the frequency of each category is compared with its exact probability
from the profiles, with a chi-square test of one degree of freedom. There are
89 categories per context:

- the 4 age bands;
- the 17 reasons, marginal over the bands;
- the 17 reasons within each band (68), among the patients of that band: the
  reason must be drawn with the patient's own band. A sampler that drew the
  reason with another band would keep the marginal mix and fail only here.

Each category is tested on its own, and not with one chi-square of many
degrees of freedom, so that a failure names the category and the power of
each test can be stated as «a share p0 that becomes p1». The tests within a
band are conditional on the number of patients drawn in it.

All tests use ``ALPHA = 0.01`` split with Bonferroni among the contexts and
the categories, so that a correct sampler fails the whole check 1 % of the
times by chance. ``detectable_share`` gives the size of the error that each
test sees with a power of 80 %.

**The triage** (``check_triage``). The sampler draws the patients of a year:
each patient gets a context with probability proportional to its expected
arrivals (``context_weights``), and then its person, reason, severity and
triage from streams 5, 6, 7 and 1. The counts are compared with the exact
values of ``edsim.profiles.severity`` on the mixture of the same year and with
the written thresholds: the 5 shares of assigned levels and the 25 cells of
the joint matrix of true against assigned level, 30 categories with
Bonferroni. Each one uses the chi-square of one degree of freedom if its
expected count is at least ``MIN_EXPECTED``, and the exact binomial test
below: the cells two or more levels away from the diagonal expect almost no
patient, and a sampler that put patients there must still fail.

**The hypothesis comes from the profiles; the draws, from the sampler.** For
power tests the patients can be drawn with other profiles
(``sampled_profiles``), as with the arrivals in ``arrivals.validation``.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
from scipy import optimize, stats

from edsim.arrivals.profile import ArrivalProfile
from edsim.checks import ValidationResult, check_count
from edsim.profiles.config import N_BANDS, N_LEVELS, REASON_KEYS, ClinicalProfiles
from edsim.profiles.context import ArrivalContext, all_contexts, context_time, context_weights
from edsim.profiles.mixing import band_probabilities, probabilities, reason_probabilities
from edsim.profiles.population import age_range
from edsim.profiles.sampler import PersonReasonSampler, SeverityTriageSampler
from edsim.profiles.severity import severity_mixture, triage_matrix
from edsim.seeds import child_streams

ALPHA = 0.01
"""Level of the whole check: a correct sampler fails it 1 % of the times."""

N_CATEGORIES = N_BANDS + len(REASON_KEYS) + N_BANDS * len(REASON_KEYS)
"""Categories tested in each context: 4 bands, 17 reasons and 17 reasons in each band."""

MIN_EXPECTED = 5
"""Fewest expected patients in a category, in and out of it, for the chi-square."""

POWER = 0.8
"""Power at which ``detectable_share`` states the size of the error."""

POPULATION_STREAM, REASON_STREAM = 5, 6
"""Children of ``child_streams(seed, 8)`` that the sampler uses, as in the engine."""

SEVERITY_STREAM, TRIAGE_STREAM = 7, 1
"""Children of ``child_streams(seed, 8)`` for the severity and the nurse's error."""

N_TRIAGE_CATEGORIES = N_LEVELS + N_LEVELS * N_LEVELS
"""Categories of ``check_triage``: 5 assigned levels and the 25 cells of the matrix."""


@dataclass(frozen=True, slots=True)
class _Arrival:
    """The only thing the sampler reads from an arrival: its time."""

    time: float


def detectable_share(p0: float, n: int, alpha: float, power: float = POWER) -> float:
    """Share ``p1 > p0`` that a two-sided test of level ``alpha`` detects with ``power``.

    Uses the normal approximation of the binomial with ``n`` patients: the test
    rejects when ``|k/n - p0| > z * sqrt(p0 (1 - p0) / n)``, with ``z`` the
    ``1 - alpha/2`` quantile.
    """
    z = stats.norm.ppf(1 - alpha / 2)
    limit = z * np.sqrt(p0 * (1 - p0) / n)

    def gap(p1: float) -> float:
        return stats.norm.sf((limit - (p1 - p0)) / np.sqrt(p1 * (1 - p1) / n)) - power

    return float(optimize.brentq(gap, p0 + 1e-12, 1 - 1e-12))


def detection_power(p0: float, p1: float, n: int, alpha: float) -> float:
    """Power of a two-sided test of level ``alpha`` against a share ``p1`` instead of ``p0``.

    Uses the same normal approximation as ``detectable_share``, counting both
    tails: the probability that ``k/n`` falls outside the acceptance region of
    ``p0`` when the true share is ``p1``.
    """
    z = stats.norm.ppf(1 - alpha / 2)
    limit = z * np.sqrt(p0 * (1 - p0) / n)
    sd = np.sqrt(p1 * (1 - p1) / n)
    return float(stats.norm.sf((p0 + limit - p1) / sd) + stats.norm.cdf((p0 - limit - p1) / sd))


def _category(name: str, observed: int, n: int, p: float, alpha: float) -> ValidationResult:
    expected = n * p
    if min(expected, n - expected) < MIN_EXPECTED:
        raise ValueError(
            f"too few patients for {name}: expected {min(expected, n - expected):.2f} "
            f"< {MIN_EXPECTED}; use more patients"
        )
    statistic, p_value = stats.chisquare([observed, n - observed], [expected, n - expected])
    return ValidationResult(
        name=name,
        statistic=float(statistic),
        p_value=float(p_value),
        ci_low=None,
        ci_high=None,
        target=float(p),
        criterion=f"p >= {alpha:.3g}",
        passed=bool(p_value >= alpha),
    )


def _band_name(profiles: ClinicalProfiles, band: int) -> str:
    low, high = age_range(profiles.population, band)
    return f"banda_{low}_{high}"


def check_mixing(
    profiles: ClinicalProfiles,
    start_date: date,
    *,
    seed: int | np.random.SeedSequence,
    patients: int = 20_000,
    contexts: Sequence[ArrivalContext] | None = None,
    sampled_profiles: ClinicalProfiles | None = None,
) -> ValidationResult:
    """Chi-square of every band and reason in each context, with Bonferroni.

    Each context draws ``patients`` patients at ``context_time``, with its own
    child of ``seed``, and compares the count of each category with its exact
    probability. Each test has level ``ALPHA / (contexts * 89)``.

    Args:
        profiles: The profiles that give the hypothesis.
        start_date: Date of minute 0 of the arrivals.
        seed: Master seed of the check.
        patients: Patients per context.
        contexts: Contexts to check; the 24 by default.
        sampled_profiles: Profiles the patients are drawn with; ``profiles``
            by default. Only for power tests.

    Returns:
        A result with one detail per context, each with one detail per
        category: ``banda_80_99``, ``disnea`` and ``banda_80_99/disnea``.
        Its statistic is the number of failing contexts and its p-value, the
        smallest of all.

    Raises:
        ValueError: If ``patients`` is too small for some category to have
            ``MIN_EXPECTED`` expected patients, which would let the check pass
            without testing anything.
    """
    patients = check_count("patients", patients, 1)
    contexts = tuple(all_contexts() if contexts is None else contexts)
    sampled_profiles = profiles if sampled_profiles is None else sampled_profiles
    alpha = ALPHA / (len(contexts) * N_CATEGORIES)

    details = []
    for ctx, ctx_seed in zip(contexts, child_streams(seed, len(contexts)), strict=True):
        children = child_streams(ctx_seed, 8)
        sampler = PersonReasonSampler(
            sampled_profiles, start_date, [children[POPULATION_STREAM], children[REASON_STREAM]]
        )
        arrival = _Arrival(context_time(start_date, profiles.shift_band_starts, ctx))
        draws = [sampler(arrival) for _ in range(patients)]
        joint = np.zeros((N_BANDS, len(REASON_KEYS)), dtype=np.int64)
        np.add.at(
            joint, ([d.person.band for d in draws], [REASON_KEYS.index(d.reason) for d in draws]), 1
        )
        bands, reasons = joint.sum(axis=1), joint.sum(axis=0)

        p_band = band_probabilities(profiles.population, ctx)
        p_within = [reason_probabilities(profiles, ctx, b) for b in range(N_BANDS)]
        p_reason = sum(p_band[b] * p_within[b] for b in range(N_BANDS))
        tests = (
            tuple(
                _category(_band_name(profiles, b), int(bands[b]), patients, float(p_band[b]), alpha)
                for b in range(N_BANDS)
            )
            + tuple(
                _category(key, int(reasons[i]), patients, float(p_reason[i]), alpha)
                for i, key in enumerate(REASON_KEYS)
            )
            + tuple(
                _category(
                    f"{_band_name(profiles, b)}/{key}",
                    int(joint[b, i]),
                    int(bands[b]),
                    float(p_within[b][i]),
                    alpha,
                )
                for b in range(N_BANDS)
                for i, key in enumerate(REASON_KEYS)
            )
        )
        worst = min(t.p_value for t in tests)
        details.append(
            ValidationResult(
                name=ctx.label,
                statistic=max(t.statistic for t in tests),
                p_value=worst,
                ci_low=None,
                ci_high=None,
                target=None,
                criterion=f"min p >= {alpha:.3g}",
                passed=all(t.passed for t in tests),
                details=tests,
            )
        )

    failing = sum(not d.passed for d in details)
    return ValidationResult(
        name="mixing",
        statistic=float(failing),
        p_value=min(d.p_value for d in details),
        ci_low=None,
        ci_high=None,
        target=None,
        criterion=f"all {len(details)} contexts: p >= {alpha:.3g} (Bonferroni)",
        passed=failing == 0,
        details=tuple(details),
    )


def _binomial_category(
    name: str, observed: int, n: int, p: float, alpha: float
) -> ValidationResult:
    """Exact two-sided binomial test, for a category with fewer than MIN_EXPECTED expected."""
    p = float(np.clip(p, 0.0, 1.0))
    p_value = float(stats.binomtest(observed, n, p).pvalue)
    return ValidationResult(
        name=name,
        statistic=float(observed),
        p_value=p_value,
        ci_low=None,
        ci_high=None,
        target=p,
        criterion=f"binomial p >= {alpha:.3g}",
        passed=bool(p_value >= alpha),
    )


def year_patients(profiles: ClinicalProfiles, arrival_profile: ArrivalProfile) -> int:
    """Expected arrivals of a year of the arrival profile, rounded: 109 542 in the base center."""
    return round(float(context_weights(arrival_profile, profiles.shift_band_starts).sum()))


def check_triage(
    profiles: ClinicalProfiles,
    arrival_profile: ArrivalProfile,
    *,
    seed: int | np.random.SeedSequence,
    patients: int | None = None,
    sampled_profiles: ClinicalProfiles | None = None,
) -> ValidationResult:
    """Assigned levels and the matrix of true against assigned level, over a year.

    Each patient gets its context with probability proportional to the
    expected arrivals of a year (child 0 of ``seed``) and is drawn at
    ``context_time`` of that context, with streams 5, 6, 7 and 1 of
    ``child_streams(child 1 of seed, 8)``. The 30 categories (see the module
    docstring) are compared with the exact shares, each test at level
    ``ALPHA / 30``.

    Args:
        profiles: The profiles that give the hypothesis, with their written
            thresholds, noise and bias.
        arrival_profile: The arrival profile, for the weight of each context.
        seed: Master seed of the check.
        patients: Number of patients; the expected arrivals of a year by
            default (``year_patients``).
        sampled_profiles: Profiles the patients are drawn with; ``profiles``
            by default. Only for power tests.

    Returns:
        A result with one detail per category: ``asignado_1`` to
        ``asignado_5`` and ``real_1/asignado_1`` to ``real_5/asignado_5``. Its
        statistic is the number of failing categories and its p-value, the
        smallest of all.

    Raises:
        ValueError: If ``patients`` is too small for an assigned level to have
            ``MIN_EXPECTED`` expected patients.
    """
    patients = (
        year_patients(profiles, arrival_profile)
        if patients is None
        else check_count("patients", patients, 1)
    )
    sampled_profiles = profiles if sampled_profiles is None else sampled_profiles
    alpha = ALPHA / N_TRIAGE_CATEGORIES
    start_date = arrival_profile.start_date

    context_seed, patient_seed = child_streams(seed, 2)
    contexts = all_contexts()
    weights = probabilities(
        context_weights(arrival_profile, profiles.shift_band_starts).ravel()
    )  # in the order of all_contexts()
    drawn = np.random.default_rng(context_seed).choice(len(contexts), size=patients, p=weights)
    arrivals = [_Arrival(context_time(start_date, profiles.shift_band_starts, c)) for c in contexts]

    streams = child_streams(patient_seed, 8)
    people = PersonReasonSampler(
        sampled_profiles, start_date, [streams[POPULATION_STREAM], streams[REASON_STREAM]]
    )
    triage = SeverityTriageSampler(
        sampled_profiles, [streams[SEVERITY_STREAM], streams[TRIAGE_STREAM]]
    )
    observed = np.zeros((N_LEVELS, N_LEVELS), dtype=np.int64)
    for c in drawn:
        x = triage(people(arrivals[c]))
        observed[x.true_level - 1, x.level - 1] += 1

    t = profiles.triage
    exact = triage_matrix(
        severity_mixture(profiles, arrival_profile), t.thresholds, t.noise, t.bias
    )
    assigned, expected_assigned = observed.sum(axis=0), exact.sum(axis=0)
    tests = [
        _category(
            f"asignado_{j + 1}", int(assigned[j]), patients, float(expected_assigned[j]), alpha
        )
        for j in range(N_LEVELS)
    ]
    for i in range(N_LEVELS):
        for j in range(N_LEVELS):
            name, p = f"real_{i + 1}/asignado_{j + 1}", float(exact[i, j])
            expected = patients * p
            test = (
                _category
                if min(expected, patients - expected) >= MIN_EXPECTED
                else _binomial_category
            )
            tests.append(test(name, int(observed[i, j]), patients, p, alpha))

    failing = sum(not x.passed for x in tests)
    return ValidationResult(
        name="triage",
        statistic=float(failing),
        p_value=min(x.p_value for x in tests),
        ci_low=None,
        ci_high=None,
        target=None,
        criterion=f"all {len(tests)} categories: p >= {alpha:.3g} (Bonferroni)",
        passed=failing == 0,
        details=tuple(tests),
    )
