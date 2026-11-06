"""How many patients change category when the weights change: Gumbel-max against the inverse CDF.

A scenario that changes the weights of a categorical (a flu outbreak: dyspnoea
×1.5) should change only the patients the change concerns, so that two runs
with the same seed differ only where they must (common random numbers, ADR
candidate 43). Two samplers give the same categorical with different couplings
between the scenarios:

- **Gumbel-max** (the sampler of EDsim): one standard Gumbel per category and
  the largest ``log w + g`` wins. A patient stays in category ``i`` if ``i``
  wins with both sets of weights, that is, if for every ``j``
  ``g_j < g_i + min(log(w_i / w_j), log(w'_i / w'_j))``. That is a Gumbel race
  of ``i`` against weights ``w_i * max(w_j / w_i, w'_j / w'_i)``, so
  ``P(stays in i) = 1 / sum_j max(w_j / w_i, w'_j / w'_i)``, exactly.
- **Inverse CDF**: one uniform ``u`` and the first category whose cumulative
  share exceeds it. A patient stays if ``u`` falls in the intersection of the
  intervals of the same category before and after; the result depends on
  the order of the categories.

No coupling can change fewer patients than the total variation distance
``½ sum |p - q|``. When only one weight grows, Gumbel-max reaches it exactly:
only the patients who move into that category change.

``reason_shock_changes`` gives the three shares exactly over a year of the
arrival profile; ``simulate_changes`` and ``simulate_reason_shock`` draw them
with common random numbers, the second one with the ``PersonReasonSampler`` of
the engine.
"""

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

from edsim.arrivals.profile import ArrivalProfile
from edsim.checks import check_count
from edsim.profiles.config import ClinicalProfiles
from edsim.profiles.context import all_contexts, context_time, context_weights
from edsim.profiles.mixing import band_context_mass, probabilities, reason_weight_table
from edsim.profiles.sampler import PersonReasonSampler
from edsim.profiles.validation import POPULATION_STREAM, REASON_STREAM, year_patients
from edsim.seeds import child_streams


@dataclass(frozen=True, slots=True)
class _Arrival:
    """The only thing the sampler reads from an arrival: its time. ``ArrivalRecord``
    would import SimPy, and ``profiles`` does not load it."""

    time: float


def _weights(before: ArrayLike, after: ArrayLike) -> tuple[NDArray, NDArray]:
    w = np.asarray(before, dtype=float)
    v = np.asarray(after, dtype=float)
    if w.shape != v.shape or w.ndim == 0 or w.shape[0] < 2:
        raise ValueError(
            f"before and after need the same shape, with at least 2 categories on axis 0, "
            f"got {w.shape} and {v.shape}"
        )
    for name, x in (("before", w), ("after", v)):
        if not np.all(np.isfinite(x)) or np.any(x < 0) or np.any(x.sum(axis=0) <= 0):
            raise ValueError(f"{name} must be non-negative and finite, with a positive sum")
    return w, v


def _scalar(x: NDArray) -> float | NDArray[np.float64]:
    return float(x) if x.ndim == 0 else x


def total_variation(before: ArrayLike, after: ArrayLike) -> float | NDArray[np.float64]:
    """Total variation distance between two categoricals given by their weights.

    ``½ sum |p - q|`` with the weights normalized along axis 0: the smallest
    share of patients that must change category under any coupling.
    """
    w, v = _weights(before, after)
    return _scalar(0.5 * np.abs(probabilities(w) - probabilities(v)).sum(axis=0))


def gumbel_change_share(before: ArrayLike, after: ArrayLike) -> float | NDArray[np.float64]:
    """Exact share of patients whose Gumbel-max winner changes with the weights.

    With the same Gumbel draws in both scenarios, ``1 - sum_i 1 / sum_j
    max(w_j / w_i, w'_j / w'_i)`` (see the module docstring); a category with
    weight 0 in either scenario keeps nobody.

    Args:
        before: Weights before the change, categories on axis 0; other axes,
            such as band and context, are kept.
        after: Weights after the change, with the same shape.
    """
    w, v = _weights(before, after)
    stay = np.zeros(w.shape[1:])
    with np.errstate(divide="ignore", invalid="ignore"):
        for i in range(w.shape[0]):
            ratio = np.maximum(w / w[i], v / v[i]).sum(axis=0)
            stay = stay + np.where((w[i] > 0) & (v[i] > 0), 1 / ratio, 0.0)
    return _scalar(np.clip(1 - stay, 0.0, 1.0))


def inverse_cdf(weights: ArrayLike, u: float) -> int:
    """The category of the uniform ``u`` with the inverse CDF, in the order given.

    It is the first category whose cumulative share is above ``u``; a weight
    of 0 has an empty interval and never comes out.
    """
    p = probabilities(np.asarray(weights, dtype=float))
    if not 0 <= u < 1:
        raise ValueError(f"u must be in [0, 1), got {u!r}")
    return min(int(np.searchsorted(np.cumsum(p), u, side="right")), p.size - 1)


def inverse_cdf_change_share(before: ArrayLike, after: ArrayLike) -> float | NDArray[np.float64]:
    """Exact share of patients whose inverse-CDF category changes with the weights.

    With the same uniform in both scenarios, a patient stays if the uniform
    falls in the intersection of the intervals of one category before and
    after: one minus the sum of those intersections, in the order of axis 0.
    """
    w, v = _weights(before, after)
    upper_p, upper_q = np.cumsum(probabilities(w), axis=0), np.cumsum(probabilities(v), axis=0)
    zero = np.zeros_like(upper_p[:1])
    lower_p = np.concatenate([zero, upper_p[:-1]])
    lower_q = np.concatenate([zero, upper_q[:-1]])
    overlap = np.clip(np.minimum(upper_p, upper_q) - np.maximum(lower_p, lower_q), 0, None)
    return _scalar(np.clip(1 - overlap.sum(axis=0), 0.0, 1.0))


@dataclass(frozen=True, slots=True)
class ReasonShockChanges:
    """Share of the patients of a year whose reason changes with other profiles.

    Attributes:
        gumbel: With Gumbel-max, the sampler of EDsim.
        inverse_cdf: With the inverse CDF, in the order of ``REASON_KEYS``.
        minimum: The total variation distance in each band and context: no
            sampler can change fewer patients.
    """

    gumbel: float
    inverse_cdf: float
    minimum: float


def _check_same_population(profiles: ClinicalProfiles, shocked: ClinicalProfiles) -> None:
    if (
        shocked.population != profiles.population
        or shocked.shift_band_starts != profiles.shift_band_starts
    ):
        raise ValueError(
            "shocked must have the same population and shift bands: otherwise the age band "
            "of a patient changes too"
        )


def _shock_tables(
    profiles: ClinicalProfiles, shocked: ClinicalProfiles
) -> tuple[NDArray, NDArray, NDArray]:
    """Exact shares by band and context, shape (4, 3, 2, 4): Gumbel, inverse CDF and minimum."""
    _check_same_population(profiles, shocked)
    before, after = reason_weight_table(profiles), reason_weight_table(shocked)
    return (
        gumbel_change_share(before, after),
        inverse_cdf_change_share(before, after),
        total_variation(before, after),
    )


def reason_shock_changes(
    profiles: ClinicalProfiles, shocked: ClinicalProfiles, arrival_profile: ArrivalProfile
) -> ReasonShockChanges:
    """Exact share of the patients of a year whose reason changes from ``profiles`` to ``shocked``.

    Each band and context weighs its share of the patients of the year
    (``band_context_mass``); within it, the three shares are exact.

    Raises:
        ValueError: If the population or the shift bands differ: the age band
            would change too, and the reasons would not be comparable.
    """
    gumbel, inverse, minimum = _shock_tables(profiles, shocked)
    mass = band_context_mass(profiles, arrival_profile)
    return ReasonShockChanges(
        gumbel=float((mass * gumbel).sum()),
        inverse_cdf=float((mass * inverse).sum()),
        minimum=float((mass * minimum).sum()),
    )


@dataclass(frozen=True, slots=True)
class SimulatedChanges:
    """Patients drawn with common random numbers, and how many change category.

    Attributes:
        patients: Patients drawn.
        gumbel: How many change with Gumbel-max (the same Gumbel draws before
            and after).
        inverse_cdf: How many change with the inverse CDF (the same uniform).
    """

    patients: int
    gumbel: int
    inverse_cdf: int


def simulate_changes(
    before: ArrayLike, after: ArrayLike, patients: int, seed: int | np.random.SeedSequence
) -> SimulatedChanges:
    """Draw ``patients`` from one categorical before and after a change of weights.

    Child 0 of ``seed`` gives one standard Gumbel per category and patient,
    child 1 one uniform per patient; each method uses its draws in both
    scenarios.
    """
    w, v = _weights(before, after)
    if w.ndim != 1:
        raise ValueError(f"before and after must be one-dimensional, got shape {w.shape}")
    patients = check_count("patients", patients, 1)
    gumbel_seed, uniform_seed = child_streams(seed, 2)
    g = np.random.default_rng(gumbel_seed).gumbel(size=(patients, w.size))
    u = np.random.default_rng(uniform_seed).random(patients)
    with np.errstate(divide="ignore"):  # log(0) = -inf: a weight of 0 never wins
        g_before = np.argmax(np.log(w) + g, axis=1)
        g_after = np.argmax(np.log(v) + g, axis=1)
    i_before = np.minimum(np.searchsorted(np.cumsum(probabilities(w)), u, side="right"), w.size - 1)
    i_after = np.minimum(np.searchsorted(np.cumsum(probabilities(v)), u, side="right"), v.size - 1)
    return SimulatedChanges(
        patients=patients,
        gumbel=int(np.sum(g_before != g_after)),
        inverse_cdf=int(np.sum(i_before != i_after)),
    )


@dataclass(frozen=True, slots=True)
class SimulatedShock:
    """Patients of a year drawn with both profiles, and how many change reason.

    Attributes:
        patients: Patients drawn.
        gumbel: How many change reason with the ``PersonReasonSampler`` (the
            same streams 5 and 6 with both profiles).
        inverse_cdf: How many change with the inverse CDF, with one shared
            uniform per patient.
        expected_gumbel: Exact share expected for these same patients: the
            mean of the exact share of the band and context of each one.
        expected_inverse_cdf: The same with the inverse CDF.
        expected_minimum: The same with the total variation distance.
    """

    patients: int
    gumbel: int
    inverse_cdf: int
    expected_gumbel: float
    expected_inverse_cdf: float
    expected_minimum: float


def simulate_reason_shock(
    profiles: ClinicalProfiles,
    shocked: ClinicalProfiles,
    arrival_profile: ArrivalProfile,
    *,
    seed: int | np.random.SeedSequence,
    patients: int | None = None,
) -> SimulatedShock:
    """Draw the patients of a year with both profiles and count who changes reason.

    As ``check_triage``: each patient gets its context with probability
    proportional to the expected arrivals of a year (child 0 of ``seed``) and
    is drawn at ``context_time`` of that context, with streams 5 and 6 of
    ``child_streams(child 1 of seed, 8)``, the same ones for both profiles.
    The inverse CDF uses one uniform per patient from child 2, with the exact
    probabilities of the reasons in the patient's band and context.

    Args:
        profiles: The profiles before the change.
        shocked: The profiles after it, with the same population.
        arrival_profile: The arrival profile: the start date and the weight of
            each context.
        seed: Master seed.
        patients: Patients to draw; the expected arrivals of a year by default.

    Raises:
        ValueError: If the population or the shift bands differ.
    """
    gumbel_table, inverse_table, minimum_table = _shock_tables(profiles, shocked)
    patients = (
        year_patients(profiles, arrival_profile)
        if patients is None
        else check_count("patients", patients, 1)
    )
    start_date, starts = arrival_profile.start_date, profiles.shift_band_starts
    context_seed, patient_seed, uniform_seed = child_streams(seed, 3)
    contexts = all_contexts()
    weights = probabilities(context_weights(arrival_profile, starts).ravel())
    drawn = np.random.default_rng(context_seed).choice(len(contexts), size=patients, p=weights)
    times = [context_time(start_date, starts, c) for c in contexts]
    uniforms = np.random.default_rng(uniform_seed).random(patients)

    streams = child_streams(patient_seed, 8)
    pair = [streams[POPULATION_STREAM], streams[REASON_STREAM]]
    base = PersonReasonSampler(profiles, start_date, pair)
    other = PersonReasonSampler(shocked, start_date, pair)
    p_before = probabilities(reason_weight_table(profiles), axis=0)
    p_after = probabilities(reason_weight_table(shocked), axis=0)
    gumbel = inverse = 0
    expected = np.zeros(3)
    for k, c in enumerate(drawn):
        arrival = _Arrival(times[c])
        a, b = base(arrival), other(arrival)
        gumbel += a.reason != b.reason
        cell = (a.person.band, a.context.shift_band, a.context.day_type, a.context.season)
        before = inverse_cdf(p_before[(slice(None), *cell)], uniforms[k])
        after = inverse_cdf(p_after[(slice(None), *cell)], uniforms[k])
        inverse += before != after
        expected += (gumbel_table[cell], inverse_table[cell], minimum_table[cell])
    expected /= patients
    return SimulatedShock(
        patients=patients,
        gumbel=int(gumbel),
        inverse_cdf=int(inverse),
        expected_gumbel=float(expected[0]),
        expected_inverse_cdf=float(expected[1]),
        expected_minimum=float(expected[2]),
    )
