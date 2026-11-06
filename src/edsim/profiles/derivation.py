"""The derived values of ``perfiles.toml``, computed together and rounded as written.

Three groups of values in ``[motivos]`` and ``[triaje]`` are not chosen but
derived, each with its own function, and written in the file with a comment
(docs/specs/hito-4.md):

- the base weights, ``base_weights_for``, for the catalog's global mix;
- the noise and the bias of the triage, ``triage_error_for``, for the targets
  of under- and overtriage;
- the thresholds, ``thresholds_for``, for the target assigned mix.

They form a cascade: the noise and the bias are calibrated on the mixture of
G of a year, which depends on the base weights, and the thresholds on the
noise and the bias. Changing a reason's share or severity means running the
three again, in this order, each one on the values the previous one wrote.
``derive_written_values`` does exactly that, with the rounding of the file
(three decimals), so that what it returns is what the file must say.

``severity_mean_for`` chooses the mean severity of one reason by a written
criterion, not by eye: the smallest mean of a grid such that, after the whole
cascade, at least a share of the reason's patients is true level 1 and at
least another share is assigned level 1 (task 4.6a, the cardiac arrests).
``reason_level1_shares`` gives those two shares, exactly, over a year.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType

import numpy as np
from scipy import special

from edsim.arrivals.profile import ArrivalProfile
from edsim.profiles.config import REASON_KEYS, ClinicalProfiles
from edsim.profiles.mixing import base_weights_for
from edsim.profiles.severity import severity_mixture, thresholds_for, triage_error_for

DECIMALS = 3
"""Decimals of the base weights, the noise, the bias and the thresholds in the file."""


@dataclass(frozen=True, slots=True)
class DerivedValues:
    """The derived values of a profiles file, rounded as written.

    Attributes:
        base_weights: ``peso_base`` of each reason, by key, in the order of
            ``REASON_KEYS``.
        noise: ``triaje.ruido``.
        bias: ``triaje.sesgo``.
        thresholds: ``triaje.umbrales``, from c1 to c4.
    """

    base_weights: Mapping[str, float]
    noise: float
    bias: float
    thresholds: tuple[float, ...]


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
    return replace(
        profiles,
        triage=replace(
            profiles.triage,
            noise=derived.noise,
            bias=derived.bias,
            thresholds=derived.thresholds,
        ),
    )


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
    return DerivedValues(MappingProxyType(weights), noise, bias, thresholds)


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
