"""The derived values of ``perfiles.toml``, computed together and rounded as written.

Three groups of values in ``[motivos]`` and ``[triaje]`` are not chosen but
derived, each with its own function, and written in the file with a comment
(docs/specs/hito-4.md):

- the base weights, ``base_weights_for``, for the catalog's global mix;
- the noise and the bias of the triage, ``triage_error_for``, for the targets
  of under- and overtriage;
- the thresholds, ``thresholds_for``, for the target assigned mix;
- with the milestone 5 block, the base percentages of the destinations,
  ``destination_bases_for``, for the targets of admission, transfer and death
  of a year (task 5.2).

They form a cascade: the noise and the bias are calibrated on the mixture of
G of a year, which depends on the base weights, and the thresholds on the
noise and the bias. Changing a reason's share or severity means running the
three again, in this order, each one on the values the previous one wrote.
``derive_written_values`` does exactly that, with the rounding of the file
(three decimals; four significant figures for the bases of the destinations,
which go down to 0.002 %), so that what it returns is what the file must say.

``severity_mean_for`` chooses the mean severity of one reason by a written
criterion, not by eye: the smallest mean of a grid such that, after the whole
cascade, at least a share of the reason's patients is true level 1 and at
least another share is assigned level 1 (task 4.6a, the cardiac arrests).
``reason_level1_shares`` gives those two shares, exactly, over a year.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType

import numpy as np
from scipy import special

from edsim.arrivals.profile import ArrivalProfile
from edsim.profiles.config import REASON_KEYS, ClinicalProfiles
from edsim.profiles.mixing import base_weights_for
from edsim.profiles.outcome import DestinationBases, destination_bases_for, with_destination_bases
from edsim.profiles.severity import severity_mixture, thresholds_for, triage_error_for

DECIMALS = 3
"""Decimals of the base weights, the noise, the bias and the thresholds in the file."""

SIGNIFICANT_DIGITS = 4
"""Significant figures of the base percentages of the destinations in the file.

The base of death is about 0.002 %: with three decimals it would be written
0.002, 3 % off, and the deaths of a year would miss their target by as much.
"""


def round_significant(x: float, digits: int = SIGNIFICANT_DIGITS) -> float:
    """``x`` rounded to ``digits`` significant figures, such as 0.0019369 → 0.001937."""
    if x == 0 or not math.isfinite(x):
        return x
    return round(x, digits - 1 - math.floor(math.log10(abs(x))))


@dataclass(frozen=True, slots=True)
class DerivedValues:
    """The derived values of a profiles file, rounded as written.

    Attributes:
        base_weights: ``peso_base`` of each reason, by key, in the order of
            ``REASON_KEYS``.
        noise: ``triaje.ruido``.
        bias: ``triaje.sesgo``.
        thresholds: ``triaje.umbrales``, from c1 to c4.
        destinations: The ``ingreso`` of each reason and the bases of transfer
            and death, with the milestone 5 block; ``None`` without it.
    """

    base_weights: Mapping[str, float]
    noise: float
    bias: float
    thresholds: tuple[float, ...]
    destinations: DestinationBases | None = None


def with_base_weights(profiles: ClinicalProfiles, weights: Mapping[str, float]) -> ClinicalProfiles:
    """The profiles with these base weights, one per reason key."""
    return replace(
        profiles,
        reasons=tuple(replace(r, base_weight=weights[r.key]) for r in profiles.reasons),
    )


def with_severity(
    profiles: ClinicalProfiles, reason: str, mean: float, sd: float
) -> ClinicalProfiles:
    """The profiles with another mean and deviation of G for one reason; ages keep their shift."""
    _check_reason(reason)
    return replace(
        profiles,
        reasons=tuple(
            replace(r, severity=replace(r.severity, mean=mean, sd=sd)) if r.key == reason else r
            for r in profiles.reasons
        ),
    )


def with_derived(profiles: ClinicalProfiles, derived: DerivedValues) -> ClinicalProfiles:
    """The profiles with the derived values written in them."""
    profiles = with_base_weights(profiles, derived.base_weights)
    profiles = replace(
        profiles,
        triage=replace(
            profiles.triage,
            noise=derived.noise,
            bias=derived.bias,
            thresholds=derived.thresholds,
        ),
    )
    if derived.destinations is not None:
        profiles = with_destination_bases(profiles, derived.destinations)
    return profiles


def with_target_mix(
    profiles: ClinicalProfiles, arrival_profile: ArrivalProfile, target_pct: Sequence[float]
) -> ClinicalProfiles:
    """A variant of the profiles with another target assigned mix and its thresholds.

    ``reparto_objetivo`` becomes ``target_pct`` and the thresholds are derived
    again for it with ``thresholds_for``, in memory and without rounding, so
    the exact assigned mix of a year is the new target. The noise and the bias
    stay as they are: they were calibrated for the base mix, so the under- and
    overtriage of the variant change. Nothing is written: the file of the
    profiles does not change.

    Args:
        profiles: The base profiles.
        arrival_profile: The arrival profile, for the mixture of a year.
        target_pct: Percentage of each assigned level, 1 to 5, adding up to 100.

    Raises:
        ValueError: If ``target_pct`` is not a valid ``reparto_objetivo``.
    """
    variant = replace(profiles, triage=replace(profiles.triage, target_pct=tuple(target_pct)))
    thresholds = thresholds_for(variant, arrival_profile)
    return replace(variant, triage=replace(variant.triage, thresholds=thresholds))


def derive_written_values(
    profiles: ClinicalProfiles,
    arrival_profile: ArrivalProfile,
    targets: Mapping[str, float] | None = None,
) -> DerivedValues:
    """The cascade of derived values, each one on the previous ones as written.

    1. ``base_weights_for(profiles, arrival_profile, targets)``, rounded to
       ``DECIMALS``.
    2. ``triage_error_for`` with those weights, rounded.
    3. ``thresholds_for`` with those weights, noise and bias, rounded.
    4. With the milestone 5 block, ``destination_bases_for`` with those
       values, rounded to ``SIGNIFICANT_DIGITS``.

    Only the factors, the severities and the targets of ``profiles`` are
    used: the derived values it already has do not change the result.

    Args:
        profiles: The clinical profiles.
        arrival_profile: The arrival profile, for the weight of each context.
        targets: Global share of each reason, by key; the catalog by default.

    Returns:
        The values that the file must have.
    """
    weights = {
        key: round(w, DECIMALS)
        for key, w in base_weights_for(profiles, arrival_profile, targets).items()
    }
    profiles = with_base_weights(profiles, weights)
    noise, bias = (round(x, DECIMALS) for x in triage_error_for(profiles, arrival_profile))
    profiles = replace(profiles, triage=replace(profiles.triage, noise=noise, bias=bias))
    thresholds = tuple(round(c, DECIMALS) for c in thresholds_for(profiles, arrival_profile))
    destinations = None
    if profiles.outcome is not None:
        profiles = replace(profiles, triage=replace(profiles.triage, thresholds=thresholds))
        bases = destination_bases_for(profiles, arrival_profile)
        destinations = DestinationBases(
            MappingProxyType({k: round_significant(v) for k, v in bases.admission.items()}),
            round_significant(bases.transfer),
            round_significant(bases.death),
        )
    return DerivedValues(MappingProxyType(weights), noise, bias, thresholds, destinations)


def _check_reason(reason: str) -> int:
    if reason not in REASON_KEYS:
        raise ValueError(f"reason must be one of {REASON_KEYS}, got {reason!r}")
    return REASON_KEYS.index(reason)


def reason_level1_shares(
    profiles: ClinicalProfiles, arrival_profile: ArrivalProfile, reason: str
) -> tuple[float, float]:
    """Share of a reason's patients of a year that are true level 1 and assigned level 1.

    Exact, with the written thresholds, noise and bias: over the age bands of
    the reason, weighted as in the mixture of a year, ``P(G > c1)`` and
    ``P(G + ε > c1)``, both sums of normal CDFs.

    Returns:
        The true and the assigned share, as fractions.
    """
    i = _check_reason(reason)
    mixture = severity_mixture(profiles, arrival_profile)
    w = mixture.weights[i] / mixture.weights[i].sum()
    m, s = mixture.means[i], mixture.sds[i]
    t = profiles.triage
    c1 = t.thresholds[0]
    real = float(w @ special.ndtr((m - c1) / s))
    assigned = float(w @ special.ndtr((m + t.bias - c1) / np.sqrt(s**2 + t.noise**2)))
    return real, assigned


def severity_mean_for(
    profiles: ClinicalProfiles,
    arrival_profile: ArrivalProfile,
    reason: str,
    sd: float,
    *,
    real_min: float,
    assigned_min: float,
    start: float,
    targets: Mapping[str, float] | None = None,
    step: float = 0.01,
    max_steps: int = 1000,
) -> float:
    """The smallest mean of G of a reason, on a grid, that meets a criterion of level 1.

    From ``start`` upwards, in steps of ``step``, each candidate mean (with
    deviation ``sd``) goes through the whole cascade
    (``derive_written_values``), and its shares of true and assigned level 1
    (``reason_level1_shares``) are compared with ``real_min`` and
    ``assigned_min``. The first one that meets both is returned. Raising the
    mean also raises c1, so each candidate needs its own cascade.

    Args:
        profiles: The clinical profiles.
        arrival_profile: The arrival profile.
        reason: Key of the reason.
        sd: Deviation of G of the reason, fixed beforehand by clinical judgement.
        real_min: Smallest share of true level 1, as a fraction.
        assigned_min: Smallest share of assigned level 1, as a fraction.
        start: First candidate; it must not meet the criterion, so that the
            answer is the smallest of the grid and not just ``start``.
        targets: Global share of each reason, by key; the catalog by default.
        step: Step of the grid; the mean is rounded to its decimals.
        max_steps: Candidates before giving up.

    Raises:
        ValueError: If ``start`` already meets the criterion.
        RuntimeError: If no candidate meets it within ``max_steps``.
    """
    decimals = max(0, -math.floor(math.log10(step)))
    first = round(start / step)
    for k in range(max_steps):
        mean = round((first + k) * step, decimals)
        candidate = with_severity(profiles, reason, mean, sd)
        candidate = with_derived(
            candidate, derive_written_values(candidate, arrival_profile, targets)
        )
        real, assigned = reason_level1_shares(candidate, arrival_profile, reason)
        if real >= real_min and assigned >= assigned_min:
            if k == 0:
                raise ValueError(f"start {start} already meets the criterion: start lower")
            return mean
    raise RuntimeError(f"no mean from {start} in {max_steps} steps of {step} meets the criterion")
