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

**The tests** (``check_workup``) and **the durations** (``check_durations``).
The sampler draws the patients of a year as in ``check_triage``, now also
with streams 3 and 2, and compares them with the exact values of
``workup.WorkupModel`` and ``durations.DurationModel`` on the mixture of the
same year. Each category is a proportion: the patients with a test ordered
among those of a group, or the patients with a duration at or below its exact
quantile, which is binomial with the quantile's probability (as in the
quantiles of task 3.1). Each uses the chi-square of one degree of freedom,
or the exact binomial below ``MIN_EXPECTED`` expected, with Bonferroni over
all the categories of the check. Every group a category is conditioned on
(an interval of G, a reason, a true level, the undertriaged, the patients
with a round) must expect at least ``MIN_GROUP_PATIENTS`` patients, so that
the rare true levels 1 and 5 never pass without testing anything.

- ``check_workup``, 134 categories: each type ordered within each fifth of G
  (20), abnormal within each fifth over all patients, ordered or not, since
  the result is always drawn (20), ordered among the undertriaged (4), by
  reason (68) and by true level (20), and the median and p90 of the round
  with factor 1 (2).
- ``check_durations``, 64 categories: median and p90 of the triage (2), of
  the base turnaround of each type over all patients (8), and of the
  assessment and the reassessment per true level (20), and their median per
  reason (34), which tests the factors k directly.

**All of them at once** (``validate_profiles``, for ``edsim perfiles
validar``). The mix with its own child of the seed and, with the other child,
one sample of a year for the triage, the tests and the durations: the three
checks draw the same patients with the same seed, so one draw gives the three
results of ``check_triage``, ``check_workup`` and ``check_durations``, ``==``,
and the data of the plots. Each check keeps its ``ALPHA`` with Bonferroni
within it, so a correct sampler fails some of the four up to 4 % of the times
(Boole's inequality). ``check_profiles_validation_counts`` refuses, before
drawing, a number of patients with which a check would fail for lack of
patients instead of testing something.

**The hypothesis comes from the profiles; the draws, from the sampler.** For
power tests the patients can be drawn with other profiles
(``sampled_profiles``), as with the arrivals in ``arrivals.validation``. A
mistake shared by the sampler and the exact values (such as which bands are
older) moves both and cannot be seen here: only the values by hand see it.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from time import perf_counter

import numpy as np
from scipy import optimize, stats

from edsim.arrivals.profile import ArrivalProfile
from edsim.checks import ValidationResult, check_count
from edsim.profiles.config import N_BANDS, N_LEVELS, REASON_KEYS, TEST_TYPES, ClinicalProfiles
from edsim.profiles.context import ArrivalContext, all_contexts, context_time, context_weights
from edsim.profiles.durations import ASSESSMENT, REASSESSMENT, duration_model
from edsim.profiles.mixing import band_probabilities, probabilities, reason_probabilities
from edsim.profiles.population import age_range
from edsim.profiles.sampler import (
    PersonReasonSampler,
    SeverityTriageSampler,
    WorkupDurationSampler,
)
from edsim.profiles.severity import UNDER, severity_mixture, triage_matrix
from edsim.profiles.workup import workup_model
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

WORKUP_STREAM, DURATION_STREAM = 3, 2
"""Children of ``child_streams(seed, 8)`` for the tests and the durations."""

N_SEVERITY_GROUPS = 5
"""Intervals of G of equal mass (fifths) of ``check_workup``."""

N_TESTS = len(TEST_TYPES)

N_WORKUP_CATEGORIES = (
    2 * N_SEVERITY_GROUPS * N_TESTS + N_TESTS + len(REASON_KEYS) * N_TESTS + N_LEVELS * N_TESTS + 2
)
"""Categories of ``check_workup``: 20 + 20 + 4 + 68 + 20 + 2 = 134."""

N_DURATION_CATEGORIES = 2 + 2 * N_TESTS + 2 * 2 * N_LEVELS + 2 * len(REASON_KEYS)
"""Categories of ``check_durations``: 2 + 8 + 20 + 34 = 64."""

MIN_GROUP_PATIENTS = 50
"""Fewest expected patients in a group a category is conditioned on.

With 50 patients, the p90 of a duration expects 5 patients above it, the
``MIN_EXPECTED`` of the chi-square. With fewer, a test can hardly fail and
would pass without testing anything: since task 4.6a the cardiac arrest
(0.30 % of the patients, in the medians by reason) needs 16 545 patients, and
the true levels 1 (0.39 %) and 5 (0.65 %) about 12 900 and 7 700.
"""

DEFAULT_MIXING_PATIENTS = 25_000
"""Patients per context of the mix by default.

It must be at least ``mixing_minimum``: 21 379 with ``config/perfiles.toml``
since task 4.6a, set by the cardiac arrest at 15-44 years on a winter weekday
afternoon (20 491 expected, plus the margin of ``MAX_MIXING_ERROR``). 25 000
is 16.9 % above it, with a chance of stopping for lack of patients below
1e-100. It was 20 000 until task 4.6a, when the minimum was 15 234.
"""

QUANTILES = (("mediana", 0.5), ("p90", 0.9))
"""Quantiles of the duration checks, by name."""


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
    patients: int = DEFAULT_MIXING_PATIENTS,
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
        patients: Patients per context; ``DEFAULT_MIXING_PATIENTS`` by default.
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
    return _triage_result(profiles, arrival_profile, observed)


def exact_triage_matrix(profiles: ClinicalProfiles, arrival_profile: ArrivalProfile) -> np.ndarray:
    """Exact shares of true (rows) against assigned (columns) level over a year, (5, 5)."""
    t = profiles.triage
    return triage_matrix(severity_mixture(profiles, arrival_profile), t.thresholds, t.noise, t.bias)


def _triage_result(
    profiles: ClinicalProfiles, arrival_profile: ArrivalProfile, observed: np.ndarray
) -> ValidationResult:
    """The 30 categories of ``check_triage`` from the counts of true × assigned level."""
    patients = int(observed.sum())
    alpha = ALPHA / N_TRIAGE_CATEGORIES
    exact = exact_triage_matrix(profiles, arrival_profile)
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


def _proportion(name: str, observed: int, n: int, p: float, alpha: float) -> ValidationResult:
    """Chi-square of one degree of freedom, or the exact binomial below MIN_EXPECTED."""
    expected = n * p
    test = _category if min(expected, n - expected) >= MIN_EXPECTED else _binomial_category
    return test(name, int(observed), int(n), float(p), alpha)


def _check_groups(groups: dict[str, float], patients: int) -> None:
    """Every group must expect at least MIN_GROUP_PATIENTS patients (exact, not observed)."""
    small = {k: patients * v for k, v in groups.items() if patients * v < MIN_GROUP_PATIENTS}
    if small:
        worst = min(small, key=small.get)
        raise ValueError(
            f"too few patients for {worst}: expected {small[worst]:.1f} < "
            f"{MIN_GROUP_PATIENTS}; use more patients"
        )


@dataclass(frozen=True, slots=True)
class _Year:
    """The patients drawn for the checks of tests and durations, as arrays."""

    severity: np.ndarray
    level: np.ndarray  # assigned
    true_level: np.ndarray
    under: np.ndarray
    reason: np.ndarray
    ordered: np.ndarray  # (n, 4)
    abnormal: np.ndarray
    turnaround: np.ndarray
    round_turnaround: np.ndarray  # nan without a round
    triage: np.ndarray
    assessment: np.ndarray
    reassessment: np.ndarray


def _draw_year(
    sampled_profiles: ClinicalProfiles,
    arrival_profile: ArrivalProfile,
    seed: int | np.random.SeedSequence,
    patients: int,
) -> _Year:
    """Patients of a year: contexts by their weight and streams 5, 6, 7, 1, 3 and 2."""
    start_date = arrival_profile.start_date
    starts = sampled_profiles.shift_band_starts
    context_seed, patient_seed = child_streams(seed, 2)
    contexts = all_contexts()
    weights = probabilities(context_weights(arrival_profile, starts).ravel())
    drawn = np.random.default_rng(context_seed).choice(len(contexts), size=patients, p=weights)
    arrivals = [_Arrival(context_time(start_date, starts, c)) for c in contexts]

    streams = child_streams(patient_seed, 8)
    people = PersonReasonSampler(
        sampled_profiles, start_date, [streams[POPULATION_STREAM], streams[REASON_STREAM]]
    )
    triage = SeverityTriageSampler(
        sampled_profiles, [streams[SEVERITY_STREAM], streams[TRIAGE_STREAM]]
    )
    workup = WorkupDurationSampler(
        sampled_profiles, [streams[WORKUP_STREAM], streams[DURATION_STREAM]]
    )
    rows = []
    for c in drawn:
        pr = people(arrivals[c])
        st = triage(pr)
        wd = workup(pr, st)
        w, d = wd.workup, wd.durations
        r = w.round_turnaround()
        rows.append(
            (
                st.severity,
                st.true_level,
                st.quality == UNDER,
                st.level,
                REASON_KEYS.index(pr.reason),
                *w.ordered,
                *w.abnormal,
                *w.turnarounds,
                np.nan if r is None else r,
                d.triage_time,
                d.assessment_time,
                d.reassessment_time,
            )
        )
    a = np.array(rows, dtype=float)
    k = N_TESTS
    return _Year(
        severity=a[:, 0],
        level=a[:, 3].astype(int),
        true_level=a[:, 1].astype(int),
        under=a[:, 2].astype(bool),
        reason=a[:, 4].astype(int),
        ordered=a[:, 5 : 5 + k].astype(bool),
        abnormal=a[:, 5 + k : 5 + 2 * k].astype(bool),
        turnaround=a[:, 5 + 2 * k : 5 + 3 * k],
        round_turnaround=a[:, 5 + 3 * k],
        triage=a[:, 6 + 3 * k],
        assessment=a[:, 7 + 3 * k],
        reassessment=a[:, 8 + 3 * k],
    )


def _summary(name: str, tests: list[ValidationResult], alpha: float) -> ValidationResult:
    failing = sum(not x.passed for x in tests)
    return ValidationResult(
        name=name,
        statistic=float(failing),
        p_value=min(x.p_value for x in tests),
        ci_low=None,
        ci_high=None,
        target=None,
        criterion=f"all {len(tests)} categories: p >= {alpha:.3g} (Bonferroni)",
        passed=failing == 0,
        details=tuple(tests),
    )


def _patients(profiles, arrival_profile, patients) -> int:
    if patients is None:
        return year_patients(profiles, arrival_profile)
    return check_count("patients", patients, 1)


def check_workup(
    profiles: ClinicalProfiles,
    arrival_profile: ArrivalProfile,
    *,
    seed: int | np.random.SeedSequence,
    patients: int | None = None,
    sampled_profiles: ClinicalProfiles | None = None,
) -> ValidationResult:
    """The tests of a year against their exact shares: 134 categories with Bonferroni.

    The patients are drawn as in ``check_triage`` (contexts with child 0 of
    ``seed``; streams 5, 6, 7, 1, 3 and 2 of ``child_streams(child 1, 8)``).
    The categories (see the module docstring) are named
    ``pedir/analitica/quintil_1`` (fifths of G from the least severe),
    ``alterado/ecg/quintil_5``, ``pedir/imagen/infratriaje``,
    ``pedir/radiografia/traumatismo``, ``pedir/ecg/real_1``,
    ``ronda/mediana`` and ``ronda/p90``.

    Args:
        profiles: The profiles that give the hypothesis.
        arrival_profile: The arrival profile, for the weight of each context.
        seed: Master seed of the check.
        patients: Number of patients; a year by default (``year_patients``).
        sampled_profiles: Profiles the patients are drawn with; ``profiles``
            by default. Only for power tests.

    Raises:
        ValueError: If a group expects fewer than ``MIN_GROUP_PATIENTS``
            patients, such as the true level 1 with fewer than 12 000.
    """
    patients = _patients(profiles, arrival_profile, patients)
    sampled_profiles = profiles if sampled_profiles is None else sampled_profiles
    model = workup_model(profiles, arrival_profile)
    _check_groups(_workup_groups(model), patients)
    year = _draw_year(sampled_profiles, arrival_profile, seed, patients)
    return _workup_result(model, year)


def _workup_groups(model) -> dict[str, float]:
    """Exact share of each group a category of ``check_workup`` is conditioned on."""
    levels = real_shares_of(model)
    reasons = model.mixture.weights.sum(axis=1)
    groups = {f"real_{n + 1}": float(levels[n]) for n in range(N_LEVELS)}
    groups |= {key: float(reasons[i]) for i, key in enumerate(REASON_KEYS)}
    groups |= {"infratriaje": model.undertriage_share(), "ronda": model.round_share()}
    return groups


def severity_fifth(model, severity: np.ndarray) -> np.ndarray:
    """Fifth of G of each patient, 1 the least severe, with the exact edges of ``model``."""
    edges = model.severity_edges(N_SEVERITY_GROUPS)  # decreasing
    # Fifth 1 is the least severe: count the edges at or above each G.
    return N_SEVERITY_GROUPS - np.searchsorted(-edges[1:-1], -severity, side="right")


def _workup_result(model, year: _Year) -> ValidationResult:
    """The 134 categories of ``check_workup`` from drawn patients."""
    alpha = ALPHA / N_WORKUP_CATEGORIES
    fifth = severity_fifth(model, year.severity)
    order_g = model.order_by_severity(N_SEVERITY_GROUPS)[::-1]
    abnormal_g = model.abnormal_by_severity(N_SEVERITY_GROUPS)[::-1]

    tests = []
    for q in range(N_SEVERITY_GROUPS):
        in_q = fifth == q + 1
        for t, key in enumerate(TEST_TYPES):
            tests.append(
                _proportion(
                    f"pedir/{key}/quintil_{q + 1}",
                    year.ordered[in_q, t].sum(),
                    in_q.sum(),
                    order_g[q, t],
                    alpha,
                )
            )
    for q in range(N_SEVERITY_GROUPS):
        in_q = fifth == q + 1
        for t, key in enumerate(TEST_TYPES):
            tests.append(
                _proportion(
                    f"alterado/{key}/quintil_{q + 1}",
                    year.abnormal[in_q, t].sum(),
                    in_q.sum(),
                    abnormal_g[q, t],
                    alpha,
                )
            )
    under = model.order_given_undertriage()
    for t, key in enumerate(TEST_TYPES):
        tests.append(
            _proportion(
                f"pedir/{key}/infratriaje",
                year.ordered[year.under, t].sum(),
                year.under.sum(),
                under[t],
                alpha,
            )
        )
    by_reason = model.order_by_reason()
    for i, reason in enumerate(REASON_KEYS):
        mask = year.reason == i
        for t, key in enumerate(TEST_TYPES):
            tests.append(
                _proportion(
                    f"pedir/{key}/{reason}",
                    year.ordered[mask, t].sum(),
                    mask.sum(),
                    by_reason[i, t],
                    alpha,
                )
            )
    by_level = model.order_by_true_level()
    for n in range(N_LEVELS):
        mask = year.true_level == n + 1
        for t, key in enumerate(TEST_TYPES):
            tests.append(
                _proportion(
                    f"pedir/{key}/real_{n + 1}",
                    year.ordered[mask, t].sum(),
                    mask.sum(),
                    by_level[n, t],
                    alpha,
                )
            )
    rounds = year.round_turnaround[~np.isnan(year.round_turnaround)]
    for name, q in QUANTILES:
        x = model.round_quantile(q)
        tests.append(_proportion(f"ronda/{name}", (rounds <= x).sum(), rounds.size, q, alpha))
    return _summary("workup", tests, alpha)


def real_shares_of(model) -> np.ndarray:
    """Share of each true level in the mixture of a workup model, of shape (5,)."""
    _, mass, _ = model.nodes(model.level_edges())
    return mass.sum(axis=(0, 2))


def check_durations(
    profiles: ClinicalProfiles,
    arrival_profile: ArrivalProfile,
    *,
    seed: int | np.random.SeedSequence,
    patients: int | None = None,
    sampled_profiles: ClinicalProfiles | None = None,
) -> ValidationResult:
    """The durations of a year against their exact quantiles: 64 categories with Bonferroni.

    For each exact quantile x_q, the patients with a duration at or below x_q
    are binomial with probability q (the quantiles of task 3.1). The patients
    are drawn as in ``check_workup``. The categories are named
    ``triaje/mediana``, ``respuesta/imagen/p90``, ``valoracion/real_1/p90``
    and ``reevaluacion/traumatismo/mediana``.

    Args and errors as in ``check_workup``.
    """
    patients = _patients(profiles, arrival_profile, patients)
    sampled_profiles = profiles if sampled_profiles is None else sampled_profiles
    model = duration_model(profiles, arrival_profile)
    _check_groups(_duration_groups(model), patients)
    year = _draw_year(sampled_profiles, arrival_profile, seed, patients)
    return _durations_result(profiles, model, year)


def _duration_groups(model) -> dict[str, float]:
    """Exact share of each group a category of ``check_durations`` is conditioned on."""
    levels = model.reason_level.sum(axis=0)
    reasons = model.reason_level.sum(axis=1)
    groups = {f"real_{n + 1}": float(levels[n]) for n in range(N_LEVELS)}
    groups |= {key: float(reasons[i]) for i, key in enumerate(REASON_KEYS)}
    return groups


def _durations_result(profiles: ClinicalProfiles, model, year: _Year) -> ValidationResult:
    """The 64 categories of ``check_durations`` from drawn patients."""
    patients = year.severity.size
    alpha = ALPHA / N_DURATION_CATEGORIES
    tests = []
    for (name, q), x in zip(QUANTILES, profiles.triage.duration, strict=True):
        tests.append(_proportion(f"triaje/{name}", (year.triage <= x).sum(), patients, q, alpha))
    for t, test in enumerate(profiles.diagnostic_tests):
        for (name, q), x in zip(QUANTILES, test.turnaround, strict=True):
            observed = (year.turnaround[:, t] <= x).sum()
            tests.append(_proportion(f"respuesta/{test.key}/{name}", observed, patients, q, alpha))
    for which, values in ((ASSESSMENT, year.assessment), (REASSESSMENT, year.reassessment)):
        for n in range(1, N_LEVELS + 1):
            mask = year.true_level == n
            for name, q in QUANTILES:
                x = model.quantile(which, q, level=n)
                tests.append(
                    _proportion(
                        f"{which}/real_{n}/{name}", (values[mask] <= x).sum(), mask.sum(), q, alpha
                    )
                )
    for which, values in ((ASSESSMENT, year.assessment), (REASSESSMENT, year.reassessment)):
        for i, reason in enumerate(REASON_KEYS):
            mask = year.reason == i
            x = model.quantile(which, 0.5, reason=i)
            tests.append(
                _proportion(
                    f"{which}/{reason}/mediana", (values[mask] <= x).sum(), mask.sum(), 0.5, alpha
                )
            )
    return _summary("durations", tests, alpha)


# --- All the checks at once: edsim perfiles validar ------------------------------------------

MAX_MIXING_ERROR = 1e-6
"""Largest accepted chance that ``check_mixing`` stops for lack of patients after drawing.

The categories of the reasons within a band expect ``n_band · p`` patients,
with the *observed* count of the band, which is random: at the exact minimum
the check would stop half the times.
"""

CONFIDENCE = 0.95
"""Level of the intervals of the plots; the verdict is the table's, with Bonferroni."""

CHECK_NAMES = ("mixing", "triage", "workup", "durations")
"""The four checks of ``validate_profiles``, in their order."""


def _mixing_bands(profiles: ClinicalProfiles, contexts: Sequence[ArrivalContext]):
    """For each context and band: its share and the smallest min(p, 1 - p) of its reasons."""
    out = []
    for ctx in contexts:
        p_band = band_probabilities(profiles.population, ctx)
        for b in range(N_BANDS):
            p = reason_probabilities(profiles, ctx, b)
            out.append((ctx, b, float(p_band[b]), float(np.minimum(p, 1 - p).min())))
    return out


def mixing_error_probability(
    profiles: ClinicalProfiles, patients: int, contexts: Sequence[ArrivalContext] | None = None
) -> float:
    """Upper bound of the chance that ``check_mixing`` stops for lack of patients.

    A category of a reason within a band stops the check if
    ``n_band · min(p, 1 - p) < MIN_EXPECTED``, with ``n_band`` binomial of
    ``patients`` and the share of the band. The bound is the sum over the
    contexts and the bands (union bound) of ``P(n_band < MIN_EXPECTED / min p)``.
    """
    contexts = tuple(all_contexts() if contexts is None else contexts)
    total = 0.0
    for _, _, share, p in _mixing_bands(profiles, contexts):
        fewest = math.ceil(MIN_EXPECTED / p)  # n_band at or above it never stops
        total += float(stats.binom.cdf(fewest - 1, patients, share))
    return total


def mixing_minimum(
    profiles: ClinicalProfiles,
    contexts: Sequence[ArrivalContext] | None = None,
    max_error: float = MAX_MIXING_ERROR,
) -> int:
    """Fewest patients per context with ``mixing_error_probability`` below ``max_error``.

    It is at least the exact minimum, ``MIN_EXPECTED`` expected in every band
    and reason (13 993 with ``config/perfiles.toml``), plus the margin for the
    random count of the band (15 234).
    """
    contexts = tuple(all_contexts() if contexts is None else contexts)
    exact = max(
        math.ceil(MIN_EXPECTED / (share * p))
        for _, _, share, p in _mixing_bands(profiles, contexts)
    )
    low, high = exact, 2 * exact
    while mixing_error_probability(profiles, high, contexts) >= max_error:
        high *= 2
    while low < high:
        middle = (low + high) // 2
        if mixing_error_probability(profiles, middle, contexts) < max_error:
            high = middle
        else:
            low = middle + 1
    return low


def year_minimum(profiles: ClinicalProfiles, arrival_profile: ArrivalProfile) -> int:
    """Fewest patients of the sample of a year for the triage, the tests and the durations.

    Every group expects ``MIN_GROUP_PATIENTS`` (the true level 1 needs about
    12 000) and every assigned level ``MIN_EXPECTED`` patients, in and out.
    """
    groups = _workup_groups(workup_model(profiles, arrival_profile))
    groups |= _duration_groups(duration_model(profiles, arrival_profile))
    fewest = max(math.ceil(MIN_GROUP_PATIENTS / v) for v in groups.values())
    assigned = exact_triage_matrix(profiles, arrival_profile).sum(axis=0)
    return max(fewest, *(math.ceil(MIN_EXPECTED / min(p, 1 - p)) for p in assigned))


def check_profiles_validation_counts(
    profiles: ClinicalProfiles,
    arrival_profile: ArrivalProfile,
    patients: int | None = None,
    contexts: Sequence[ArrivalContext] | None = None,
) -> tuple[int, int]:
    """Patients per context of the mix and of the year, checked before drawing.

    Args:
        patients: Patients of each sample: per context in the mix and in total
            in the year. ``None`` for the defaults: ``DEFAULT_MIXING_PATIENTS``
            per context and a year of the arrival profile (``year_patients``).

    Returns:
        The patients per context of the mix and those of the year.

    Raises:
        ValueError: If ``patients`` is not a positive integer or is below
            ``mixing_minimum`` or ``year_minimum``; the message gives the
            minimum.
    """
    if patients is None:
        mixing, year = DEFAULT_MIXING_PATIENTS, year_patients(profiles, arrival_profile)
    else:
        mixing = year = check_count("patients", patients, 1)
    fewest = mixing_minimum(profiles, contexts)
    if mixing < fewest:
        raise ValueError(
            f"too few patients per context for the mix: {mixing} < {fewest}, the fewest "
            f"with which it stops for lack of patients with a chance below {MAX_MIXING_ERROR:g}"
        )
    fewest = year_minimum(profiles, arrival_profile)
    if year < fewest:
        raise ValueError(
            f"too few patients for the triage, the tests and the durations: {year} < {fewest}"
        )
    return mixing, year


@dataclass(frozen=True, slots=True)
class DetectableError:
    """The error a check sees with a power of 80 %, for one reference category.

    Attributes:
        category: The reference category, such as ``pedir/analitica/quintil_3``.
        p0: Its exact share.
        p1: The share it is detected at (``detectable_share``).
        patients: The patients of the category's group.
    """

    category: str
    p0: float
    p1: float
    patients: int


def detectable_errors(
    profiles: ClinicalProfiles,
    arrival_profile: ArrivalProfile,
    mixing_patients: int,
    year_patients: int,
    contexts: Sequence[ArrivalContext] | None = None,
) -> dict[str, DetectableError]:
    """The reference error of each check, with the categories of the specification.

    The mix: a reason (``motivo``) of 5 % with the patients of a context. The triage: the
    assigned level 1. The tests: ordering a blood test in the central fifth of
    G. The durations: the median of the assessment of true level 3.
    """
    n_contexts = len(all_contexts() if contexts is None else contexts)
    workup = workup_model(profiles, arrival_profile)
    durations = duration_model(profiles, arrival_profile)
    level_1 = float(exact_triage_matrix(profiles, arrival_profile).sum(axis=0)[0])
    central = float(workup.order_by_severity(N_SEVERITY_GROUPS)[::-1][2, 0])
    in_fifth = round(year_patients / N_SEVERITY_GROUPS)
    in_level_3 = round(year_patients * float(durations.reason_level.sum(axis=0)[2]))
    references = {
        "mixing": ("motivo", 0.05, mixing_patients, ALPHA / (n_contexts * N_CATEGORIES)),
        "triage": ("asignado_1", level_1, year_patients, ALPHA / N_TRIAGE_CATEGORIES),
        "workup": ("pedir/analitica/quintil_3", central, in_fifth, ALPHA / N_WORKUP_CATEGORIES),
        "durations": ("valoracion/real_3/mediana", 0.5, in_level_3, ALPHA / N_DURATION_CATEGORIES),
    }
    return {
        name: DetectableError(category, p0, detectable_share(p0, n, alpha), n)
        for name, (category, p0, n, alpha) in references.items()
    }


@dataclass(frozen=True, slots=True)
class CheckOutcome:
    """One row of ``edsim perfiles validar``.

    Attributes:
        name: ``mixing``, ``triage``, ``workup`` or ``durations``.
        result: The ``ValidationResult`` of the check, ``==`` to its ``check_*``.
        patients: Patients drawn for it: all the contexts of the mix, or the
            sample of the year (shared by the other three).
        categories: Categories tested.
        failures: Categories that fail.
        alpha: Level of each category, with Bonferroni.
        detectable: The reference error it sees.
        seconds: Time of the check; the mix includes its draw, the other three
            only their evaluation of the shared sample.
    """

    name: str
    result: ValidationResult
    patients: int
    categories: int
    failures: int
    alpha: float
    detectable: DetectableError
    seconds: float

    @property
    def passed(self) -> bool:
        return self.result.passed

    @property
    def min_p(self) -> float:
        """The smallest p-value of its categories."""
        return float(self.result.p_value)


@dataclass(frozen=True, slots=True)
class ShareComparison:
    """Exact shares against the observed ones, with their intervals, for a plot.

    Every tuple has one value per label. ``counts`` are the patients of the
    group of each share: the interval is that of a binomial proportion of
    ``counts`` patients (Wilson, at ``CONFIDENCE``).
    """

    title: str
    labels: tuple[str, ...]
    exact: tuple[float, ...]
    observed: tuple[float, ...]
    low: tuple[float, ...]
    high: tuple[float, ...]
    counts: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class QuantileComparison:
    """Exact quantiles against the observed ones, with their intervals, for a plot.

    The interval is distribution-free, between two order statistics of the
    sample (``quantile_interval``, at ``CONFIDENCE``).
    """

    title: str
    q: float
    labels: tuple[str, ...]
    exact: tuple[float, ...]
    observed: tuple[float, ...]
    low: tuple[float, ...]
    high: tuple[float, ...]
    counts: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ProfilesFigures:
    """What the four plots of ``edsim perfiles validar`` draw.

    Attributes:
        reasons: The 17 reasons of the sample of the year.
        triage: P(assigned | true) for each true level, 1 to 5.
        workup: Ordering each type of test by fifth of G, in the order of
            ``TEST_TYPES``.
        durations: Median and p90 of the assessment and the reassessment by
            true level.
    """

    reasons: ShareComparison
    triage: tuple[ShareComparison, ...]
    workup: tuple[ShareComparison, ...]
    durations: tuple[QuantileComparison, ...]


def share_interval(k: int, n: int, confidence: float = CONFIDENCE) -> tuple[float, float]:
    """Wilson interval of a binomial proportion ``k / n``."""
    ci = stats.binomtest(int(k), int(n)).proportion_ci(confidence, method="wilson")
    return float(ci.low), float(ci.high)


def quantile_interval(
    values: np.ndarray, q: float, confidence: float = CONFIDENCE
) -> tuple[float, float]:
    """Distribution-free interval of the ``q`` quantile from order statistics.

    The ranks ``l = B⁻¹(α/2)`` and ``u = B⁻¹(1 - α/2) + 1`` of the binomial of
    ``n`` and ``q`` (1-based, clipped to 1 and ``n``) give ``[x_(l), x_(u)]``,
    which covers the quantile with a chance of at least ``confidence``.
    """
    x = np.sort(np.asarray(values, dtype=float))
    n = x.size
    alpha = 1 - confidence
    low = int(stats.binom.ppf(alpha / 2, n, q))
    high = int(stats.binom.ppf(1 - alpha / 2, n, q)) + 1
    return float(x[max(low, 1) - 1]), float(x[min(high, n) - 1])


def _shares(title, labels, exact, hits, counts) -> ShareComparison:
    intervals = [share_interval(k, n) for k, n in zip(hits, counts, strict=True)]
    return ShareComparison(
        title=title,
        labels=tuple(labels),
        exact=tuple(float(p) for p in exact),
        observed=tuple(float(k / n) for k, n in zip(hits, counts, strict=True)),
        low=tuple(low for low, _ in intervals),
        high=tuple(high for _, high in intervals),
        counts=tuple(int(n) for n in counts),
    )


def _figures(profiles, arrival_profile, workup, durations, year: _Year) -> ProfilesFigures:
    n = year.severity.size
    reasons = _shares(
        "Motivos de consulta",
        REASON_KEYS,
        workup.mixture.weights.sum(axis=1),
        np.bincount(year.reason, minlength=len(REASON_KEYS)),
        [n] * len(REASON_KEYS),
    )
    exact = exact_triage_matrix(profiles, arrival_profile)
    observed = np.zeros((N_LEVELS, N_LEVELS), dtype=np.int64)
    np.add.at(observed, (year.true_level - 1, year.level - 1), 1)
    levels = [f"asignado_{j + 1}" for j in range(N_LEVELS)]
    triage = tuple(
        _shares(
            f"Nivel real {i + 1}",
            levels,
            exact[i] / exact[i].sum(),
            observed[i],
            [observed[i].sum()] * N_LEVELS,
        )
        for i in range(N_LEVELS)
    )
    fifth = severity_fifth(workup, year.severity)
    order = workup.order_by_severity(N_SEVERITY_GROUPS)[::-1]
    in_fifth = [int((fifth == q + 1).sum()) for q in range(N_SEVERITY_GROUPS)]
    fifths = [f"quintil_{q + 1}" for q in range(N_SEVERITY_GROUPS)]
    tests = tuple(
        _shares(
            key,
            fifths,
            order[:, t],
            [int(year.ordered[fifth == q + 1, t].sum()) for q in range(N_SEVERITY_GROUPS)],
            in_fifth,
        )
        for t, key in enumerate(TEST_TYPES)
    )
    quantiles = []
    for which, values in ((ASSESSMENT, year.assessment), (REASSESSMENT, year.reassessment)):
        for name, q in QUANTILES:
            groups = [values[year.true_level == level] for level in range(1, N_LEVELS + 1)]
            intervals = [quantile_interval(g, q) for g in groups]
            quantiles.append(
                QuantileComparison(
                    title=f"{which}/{name}",
                    q=q,
                    labels=tuple(f"real_{level}" for level in range(1, N_LEVELS + 1)),
                    exact=tuple(
                        float(durations.quantile(which, q, level=level))
                        for level in range(1, N_LEVELS + 1)
                    ),
                    observed=tuple(float(np.quantile(g, q)) for g in groups),
                    low=tuple(low for low, _ in intervals),
                    high=tuple(high for _, high in intervals),
                    counts=tuple(g.size for g in groups),
                )
            )
    return ProfilesFigures(reasons=reasons, triage=triage, workup=tests, durations=tuple(quantiles))


@dataclass(frozen=True, slots=True)
class ProfilesValidation:
    """The outcome of ``validate_profiles``: the four rows and the data of the plots.

    Attributes:
        checks: Mix, triage, tests and durations, in that order.
        year_patients: Patients of the sample of the year.
        year_seconds: Time of drawing that sample, once.
        figures: The data of the four plots.
    """

    checks: tuple[CheckOutcome, ...]
    year_patients: int
    year_seconds: float
    figures: ProfilesFigures

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def check(self, name: str) -> CheckOutcome:
        """The row of one check, by name."""
        (outcome,) = (c for c in self.checks if c.name == name)
        return outcome


def _failures(result: ValidationResult) -> int:
    """Failing leaf categories: those of each context in the mix, or the details."""
    leaves = [x for d in result.details for x in (d.details or (d,))]
    return sum(not x.passed for x in leaves)


def validate_profiles(
    profiles: ClinicalProfiles,
    arrival_profile: ArrivalProfile,
    *,
    seed: int | np.random.SeedSequence,
    patients: int | None = None,
    contexts: Sequence[ArrivalContext] | None = None,
    sampled_profiles: ClinicalProfiles | None = None,
    timer: Callable[[], float] = perf_counter,
) -> ProfilesValidation:
    """Run the four checks of the sampler, drawing the year once.

    The mix is ``check_mixing`` with child 0 of ``seed``; the triage, the
    tests and the durations evaluate one sample of a year drawn with child 1,
    so each result is ``==`` to the one of ``check_triage``, ``check_workup``
    and ``check_durations`` with that child and the same patients.

    Args:
        profiles: The profiles that give the hypothesis.
        arrival_profile: The arrival profile: the start date and the weight of
            each context.
        seed: Master seed.
        patients: Patients per context in the mix and in total in the year;
            ``None`` for the defaults (see ``check_profiles_validation_counts``).
        contexts: Contexts of the mix; the 24 by default.
        sampled_profiles: Profiles the patients are drawn with; ``profiles``
            by default. Only for power tests.
        timer: Clock of the times, injected in tests.

    Raises:
        ValueError: As ``check_profiles_validation_counts``, before drawing.
    """
    contexts = tuple(all_contexts() if contexts is None else contexts)
    mixing_n, year_n = check_profiles_validation_counts(
        profiles, arrival_profile, patients, contexts
    )
    sampled_profiles = profiles if sampled_profiles is None else sampled_profiles
    mixing_seed, year_seed = child_streams(seed, 2)
    detectable = detectable_errors(profiles, arrival_profile, mixing_n, year_n, contexts)

    start = timer()
    mixing = check_mixing(
        profiles,
        arrival_profile.start_date,
        seed=mixing_seed,
        patients=mixing_n,
        contexts=contexts,
        sampled_profiles=sampled_profiles,
    )
    mixing_end = timer()
    year = _draw_year(sampled_profiles, arrival_profile, year_seed, year_n)
    year_end = timer()
    observed = np.zeros((N_LEVELS, N_LEVELS), dtype=np.int64)
    np.add.at(observed, (year.true_level - 1, year.level - 1), 1)
    triage = _triage_result(profiles, arrival_profile, observed)
    triage_end = timer()
    workup = workup_model(profiles, arrival_profile)
    workup_result = _workup_result(workup, year)
    workup_end = timer()
    durations = duration_model(profiles, arrival_profile)
    durations_result = _durations_result(profiles, durations, year)
    durations_end = timer()

    rows = (
        (
            "mixing",
            mixing,
            len(contexts) * mixing_n,
            len(contexts) * N_CATEGORIES,
            start,
            mixing_end,
        ),
        ("triage", triage, year_n, N_TRIAGE_CATEGORIES, year_end, triage_end),
        ("workup", workup_result, year_n, N_WORKUP_CATEGORIES, triage_end, workup_end),
        ("durations", durations_result, year_n, N_DURATION_CATEGORIES, workup_end, durations_end),
    )
    checks = tuple(
        CheckOutcome(
            name=name,
            result=result,
            patients=n,
            categories=categories,
            failures=_failures(result),
            alpha=ALPHA / categories,
            detectable=detectable[name],
            seconds=end - begin,
        )
        for name, result, n, categories, begin, end in rows
    )
    return ProfilesValidation(
        checks=checks,
        year_patients=year_n,
        year_seconds=year_end - mixing_end,
        figures=_figures(profiles, arrival_profile, workup, durations, year),
    )
