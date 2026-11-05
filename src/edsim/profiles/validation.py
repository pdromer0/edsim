"""Statistical checks of the mix of age bands and reasons, without the engine.

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

**The hypothesis comes from the profiles; the draws, from the sampler.** For
power tests the patients can be drawn with other profiles
(``sampled_profiles``), as with the arrivals in ``arrivals.validation``.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
from scipy import optimize, stats

from edsim.checks import ValidationResult, check_count
from edsim.profiles.config import N_BANDS, REASON_KEYS, ClinicalProfiles
from edsim.profiles.context import ArrivalContext, all_contexts, context_time
from edsim.profiles.mixing import band_probabilities, reason_probabilities
from edsim.profiles.population import age_range
from edsim.profiles.sampler import PersonReasonSampler
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
