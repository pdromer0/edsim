"""The log-linear categorical: weights, exact probabilities, Gumbel-max and base weights.

The weight of a category is a base weight times one factor per feature of the
context; the probability is the weight over the sum of the weights. In
logarithms the factors add up: a factor multiplies, it does not add points.

- Reason ``m`` for a patient of band ``b`` in context ``c``:
  ``peso_base[m] * edad[m][b] * franja[m][c] * dia[m][c] * estacion[m][c]``.
- Band ``b`` in context ``c``: ``reparto_edad[b] * franja[b][c] * dia[b][c]``.

**Gumbel-max.** With one standard Gumbel ``g`` per category, the category with
the largest ``log w + g`` follows exactly the categorical with probabilities
``w / sum(w)``, with no need to normalize. Raising one weight only moves
patients into that category: the others keep their winner. So the same
draws give the same patient in two scenarios except where the change
matters (common random numbers, ADR candidate 43).

**Base weights.** The catalog's shares are a global mix: the mix of each
context weighted by the expected arrivals of a year and by the band mix of
each context. ``base_weights_for`` finds the base weights that give the
catalog back, with a multiplicative fixed point.
"""

from collections.abc import Mapping

import numpy as np
from numpy.typing import ArrayLike, NDArray

from edsim.arrivals.profile import ArrivalProfile
from edsim.checks import check_number
from edsim.profiles.config import (
    REASON_KEYS,
    REASONS,
    ClinicalProfiles,
    Population,
)
from edsim.profiles.context import DAYS_PER_YEAR, ArrivalContext, context_weights


def gumbel_max(weights: ArrayLike, gumbels: ArrayLike) -> int:
    """Index of the category with the largest ``log(weight) + gumbel``.

    With standard Gumbel draws, the index follows the categorical with
    probabilities ``weights / sum(weights)``. The weights are not normalized:
    dividing them all by the same number subtracts the same amount from every
    ``log w`` and does not change the winner. A weight of 0 never wins.

    Args:
        weights: Non-negative weights, with at least one positive.
        gumbels: One standard Gumbel draw per weight.

    Returns:
        The index of the winner, as a Python ``int``.

    Raises:
        ValueError: If the two sequences have different lengths.
    """
    w = np.asarray(weights, dtype=float)
    g = np.asarray(gumbels, dtype=float)
    if w.shape != g.shape:
        raise ValueError(
            f"weights and gumbels must have the same length, got {w.size} and {g.size}"
        )
    with np.errstate(divide="ignore"):  # log(0) = -inf: a weight of 0 never wins
        return int(np.argmax(np.log(w) + g))


def probabilities(weights: ArrayLike, axis: int = 0) -> NDArray[np.float64]:
    """Exact probabilities of a categorical: the weights over their sum along ``axis``."""
    w = np.asarray(weights, dtype=float)
    return w / w.sum(axis=axis, keepdims=True)


def band_weight_table(population: Population) -> NDArray[np.float64]:
    """Weight of each band in each shift band and day type, of shape (4, 3, 2)."""
    shares = np.asarray(population.band_shares)
    shift = np.asarray(population.band_shift_factors)
    day = np.asarray(population.band_day_factors)
    return shares[:, None, None] * shift[:, :, None] * day[:, None, :]


def band_weights(population: Population, context: ArrivalContext) -> NDArray[np.float64]:
    """Weights of the 4 bands in a context; the season does not change them."""
    return band_weight_table(population)[:, context.shift_band, context.day_type]


def band_probabilities(population: Population, context: ArrivalContext) -> NDArray[np.float64]:
    """Exact probabilities of the 4 bands in a context."""
    return probabilities(band_weights(population, context))


def factor_table(profiles: ClinicalProfiles) -> NDArray[np.float64]:
    """Product of the factors of each reason, of shape (17, 4, 3, 2, 4).

    The axes are reason, band, shift band, day type and season; the base
    weights are not included.
    """
    age = np.array([r.age_factors for r in profiles.reasons])
    shift = np.array([r.shift_factors for r in profiles.reasons])
    day = np.array([r.day_factors for r in profiles.reasons])
    season = np.array([r.season_factors for r in profiles.reasons])
    return (
        age[:, :, None, None, None]
        * shift[:, None, :, None, None]
        * day[:, None, None, :, None]
        * season[:, None, None, None, :]
    )


def reason_weight_table(
    profiles: ClinicalProfiles, base_weights: ArrayLike | None = None
) -> NDArray[np.float64]:
    """Weight of each reason for each band and context, of shape (17, 4, 3, 2, 4).

    Args:
        profiles: The clinical profiles.
        base_weights: 17 base weights in the order of ``REASON_KEYS``; the
            profiles' own by default.
    """
    if base_weights is None:
        base_weights = [r.base_weight for r in profiles.reasons]
    base = np.asarray(base_weights, dtype=float)
    return base[:, None, None, None, None] * factor_table(profiles)


def reason_weights(
    profiles: ClinicalProfiles, context: ArrivalContext, band: int
) -> NDArray[np.float64]:
    """Weights of the 17 reasons for a patient of ``band`` in ``context``."""
    table = reason_weight_table(profiles)
    return table[:, band, context.shift_band, context.day_type, context.season]


def reason_probabilities(
    profiles: ClinicalProfiles, context: ArrivalContext, band: int
) -> NDArray[np.float64]:
    """Exact probabilities of the 17 reasons for a patient of ``band`` in ``context``."""
    return probabilities(reason_weights(profiles, context, band))


def band_context_mass(
    profiles: ClinicalProfiles, arrival_profile: ArrivalProfile, days: int = DAYS_PER_YEAR
) -> NDArray[np.float64]:
    """Share of the arrivals of ``days`` days in each band and context, of shape (4, 3, 2, 4).

    It is the expected arrivals of each context times the probability of each
    band in it, over the total; it adds up to 1.
    """
    w = context_weights(arrival_profile, profiles.shift_band_starts, days)
    bands = probabilities(band_weight_table(profiles.population))  # (4, 3, 2)
    mass = bands[:, :, :, None] * w[None, :, :, :]
    return mass / mass.sum()


def _global_shares(base: NDArray, factors: NDArray, mass: NDArray) -> NDArray[np.float64]:
    """Global mix of the reasons: the mix of each band and context weighted by ``mass``."""
    p = probabilities(base[:, None, None, None, None] * factors, axis=0)
    return np.einsum("mbfds,bfds->m", p, mass)


def global_reason_shares(
    profiles: ClinicalProfiles, arrival_profile: ArrivalProfile
) -> NDArray[np.float64]:
    """Share of each reason over a year of the arrival profile, with the profiles' weights.

    Each context weighs its expected arrivals in a year, and within each
    context each band weighs its probability there.

    Returns:
        17 shares in the order of ``REASON_KEYS``, adding up to 1.
    """
    base = np.array([r.base_weight for r in profiles.reasons])
    return _global_shares(
        base, factor_table(profiles), band_context_mass(profiles, arrival_profile)
    )


def catalog_shares() -> NDArray[np.float64]:
    """The shares of the catalog (``REASONS``), normalized to add up to 1."""
    return probabilities([w for _, _, w in REASONS])


def _check_targets(targets: Mapping[str, float]) -> NDArray[np.float64]:
    missing = [f"motivos.{k}" for k in REASON_KEYS if k not in targets]
    unknown = sorted(f"motivos.{k}" for k in set(targets) - set(REASON_KEYS))
    problems = []
    if missing:
        problems.append(f"missing keys: {', '.join(missing)}")
    if unknown:
        problems.append(f"unknown keys: {', '.join(unknown)}")
    if problems:
        raise ValueError(f"targets: {'; '.join(problems)}")
    values = []
    for key in REASON_KEYS:
        x = check_number(f"targets[{key}]", targets[key])
        if x <= 0:
            raise ValueError(f"targets[{key}] must be positive, got {targets[key]!r}")
        values.append(x)
    return probabilities(values)


def base_weights_for(
    profiles: ClinicalProfiles,
    arrival_profile: ArrivalProfile,
    targets: Mapping[str, float] | None = None,
    *,
    tolerance: float = 1e-10,
    max_iterations: int = 1000,
) -> dict[str, float]:
    """Base weights whose global mix over a year is ``targets``, given the factors.

    The global mix ``S(w)`` is the mix of each band and context weighted by the
    expected arrivals of a year of ``arrival_profile`` and by the band mix
    (``band_context_mass``). Starting from the targets ``t``, each iteration
    multiplies each weight by ``t / S(w)``: a reason that comes out too often
    gets less weight. The weights are scaled to add up to 100 at every step.

    Only the factors of ``profiles`` are used: the result does not depend on
    the base weights the profiles already have. It is run once, and its
    result written in ``config/perfiles.toml`` with a comment.

    Args:
        profiles: The clinical profiles, for their factors and population.
        arrival_profile: The arrival profile, for the weight of each context.
        targets: Global share of each reason, by key, in any positive units;
            the catalog (``REASONS``) by default.
        tolerance: Largest allowed difference between a global share and its
            target, as a fraction (1e-10 is 1e-8 percentage points).
        max_iterations: Iterations before giving up.

    Returns:
        The base weights by key, in the order of ``REASON_KEYS``, adding up
        to 100.

    Raises:
        ValueError: If ``targets`` does not have the 17 keys with positive
            values.
        RuntimeError: If the fixed point does not converge within
            ``max_iterations``.
    """
    t = catalog_shares() if targets is None else _check_targets(targets)
    factors = factor_table(profiles)
    mass = band_context_mass(profiles, arrival_profile, DAYS_PER_YEAR)
    w = 100 * t
    error = np.inf
    for _ in range(max_iterations):
        shares = _global_shares(w, factors, mass)
        error = float(np.max(np.abs(shares - t)))
        if error < tolerance:
            return {key: float(x) for key, x in zip(REASON_KEYS, w, strict=True)}
        w = w * t / shares
        w = 100 * w / w.sum()
    raise RuntimeError(
        f"base_weights_for did not converge after {max_iterations} "
        f"iteration{'s' if max_iterations != 1 else ''}: largest error {error:.3g}"
    )
