"""Latent severity and triage with error: exact mixture, thresholds and matrix.

Each patient has a true severity ``G`` that the hospital never sees, and the
nurse classifies ``G + ε`` (ADR candidate 38):

- ``G = media + por_edad[band] + desviacion * z`` for the patient's reason, with
  ``z`` standard normal (stream 7);
- ``ε = sesgo + ruido * z_e``, with ``z_e`` standard normal (stream 1);
- the assigned level cuts ``G + ε`` with the thresholds ``c1 > c2 > c3 > c4``,
  and the true level cuts ``G`` with the same thresholds.

**Convention of the cut.** Level ``k`` is the interval ``(c_k, c_{k-1}]``, with
``c_0 = +inf`` and ``c_5 = -inf``: «level 1 if it exceeds c1». A value exactly
on a threshold stays in the less urgent level. In code, ``level = 1 + #{k : x
<= c_k}``.

**The mixture of a year.** Over a year of the arrival profile, G is a mixture
of normals, one per reason and age band, weighted by ``reason_band_mass``.
Everything here is exact on that mixture: the moments in closed form, the
shares as sums of normal CDFs, the thresholds by a root per threshold and the
joint matrix of true against assigned level by a one-dimensional integral per
component (Gauss-Legendre).

**Derived and written, not recomputed.** ``thresholds_for`` and
``triage_error_for`` are run once and their results written in
``config/perfiles.toml``; the sampler reads the written values. If the
thresholds were recomputed on loading, a scenario with more severity (a flu
outbreak, a mass casualty incident) would be renormalized back to the target
mix and the shock would vanish.

Undertriage is an assigned level less urgent (a larger number) than the true
level; overtriage, more urgent.
"""

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy import optimize, special

from edsim.arrivals.profile import ArrivalProfile
from edsim.profiles.config import N_THRESHOLDS, ClinicalProfiles, Severity
from edsim.profiles.mixing import reason_band_mass

CORRECT = "correcto"
"""Quality of a triage whose assigned level is the true level."""

UNDER = "infratriaje"
"""Quality of a triage whose assigned level is less urgent than the true level."""

OVER = "sobretriaje"
"""Quality of a triage whose assigned level is more urgent than the true level."""

QUADRATURE_NODES = 96
"""Gauss-Legendre nodes per component and interval of true severity."""

TAIL_SDS = 12.0
"""Infinite intervals are cut at mean ± 12 sd: the mass left out is below 1e-32."""

_NODES, _NODE_WEIGHTS = np.polynomial.legendre.leggauss(QUADRATURE_NODES)


@dataclass(frozen=True, slots=True, eq=False)
class SeverityMixture:
    """G over a population: a mixture of normals.

    Attributes:
        weights: Weight of each component, non-negative, adding up to 1; of
            shape (17, 4) for the reasons and age bands of a year.
        means: Mean of each component, with the shape of ``weights``.
        sds: Standard deviation of each component, positive.
    """

    weights: NDArray[np.float64]
    means: NDArray[np.float64]
    sds: NDArray[np.float64]

    def __post_init__(self) -> None:
        w, m, s = (np.asarray(x, dtype=float) for x in (self.weights, self.means, self.sds))
        if not w.shape == m.shape == s.shape:
            raise ValueError(
                f"weights, means and sds must have the same shape, got "
                f"{w.shape}, {m.shape} and {s.shape}"
            )
        if np.any(w < 0) or not np.isclose(w.sum(), 1, rtol=0, atol=1e-12):
            raise ValueError(f"weights must be non-negative and add up to 1, got {w.sum()!r}")
        if not np.all(np.isfinite(m)) or not np.all(s > 0) or not np.all(np.isfinite(s)):
            raise ValueError("means must be finite and sds positive and finite")
        for name, x in (("weights", w), ("means", m), ("sds", s)):
            object.__setattr__(self, name, x)

    @property
    def mean(self) -> float:
        """Mean of G: the weighted mean of the components."""
        return float((self.weights * self.means).sum())

    @property
    def sd(self) -> float:
        """Standard deviation of G: ``sqrt(sum w (sd² + mean²) - mean²)``."""
        second = (self.weights * (self.sds**2 + self.means**2)).sum()
        return float(np.sqrt(second - self.mean**2))


def severity_mixture(
    profiles: ClinicalProfiles, arrival_profile: ArrivalProfile
) -> SeverityMixture:
    """The mixture of G over a year of the arrival profile.

    Component ``(m, b)`` is the normal of reason ``m`` in band ``b``, with mean
    ``media + por_edad[b]`` and its ``desviacion``, weighted by the share of
    the patients of the year with that reason and band (``reason_band_mass``).
    """
    weights = reason_band_mass(profiles, arrival_profile)
    means = np.array(
        [[r.severity.mean + a for a in r.severity.age_shift] for r in profiles.reasons]
    )
    sds = np.array([[r.severity.sd] * len(r.severity.age_shift) for r in profiles.reasons])
    return SeverityMixture(weights / weights.sum(), means, sds)


def reason_year_means(mixture: SeverityMixture) -> NDArray[np.float64]:
    """Mean G of each reason over the year: its components weighted within the reason.

    The mixture must have one row per reason, as ``severity_mixture`` gives.
    """
    return (mixture.weights * mixture.means).sum(axis=1) / mixture.weights.sum(axis=1)


def _check_thresholds(thresholds: ArrayLike) -> NDArray[np.float64]:
    c = np.asarray(thresholds, dtype=float)
    if c.shape != (N_THRESHOLDS,) or np.any(np.diff(c) >= 0) or not np.all(np.isfinite(c)):
        raise ValueError(
            f"thresholds must be {N_THRESHOLDS} finite numbers, strictly decreasing, "
            f"got {thresholds!r}"
        )
    return c


def _edges(thresholds: ArrayLike) -> NDArray[np.float64]:
    """``c_0 = +inf``, the four thresholds and ``c_5 = -inf``."""
    return np.concatenate([[np.inf], _check_thresholds(thresholds), [-np.inf]])


def level_of(x: float, thresholds: ArrayLike) -> int:
    """The level, 1 to 5, of ``x`` cut by the thresholds: ``1 + #{k : x <= c_k}``."""
    return 1 + int(np.count_nonzero(x <= _check_thresholds(thresholds)))


def _shares(mixture: SeverityMixture, thresholds: ArrayLike, sd, shift) -> NDArray[np.float64]:
    """Share of each level when each component of G is moved by ``shift`` and has ``sd``."""
    edges = _edges(thresholds)
    w, m = mixture.weights.ravel(), mixture.means.ravel()
    # Share above each edge, from +inf (0) to -inf (1): differences give the levels.
    above = special.ndtr(-(edges[:, None] - m[None, :] - shift) / sd[None, :]) @ w
    return np.diff(above)


def assigned_shares(
    mixture: SeverityMixture, thresholds: ArrayLike, noise: float, bias: float
) -> NDArray[np.float64]:
    """Exact share of each assigned level, 1 to 5.

    Each component of ``G + ε`` is normal with mean ``mean + bias`` and
    deviation ``sqrt(sd² + noise²)``, so the share of level k is a sum of
    differences of normal CDFs.
    """
    sd = np.sqrt(mixture.sds.ravel() ** 2 + noise**2)
    return _shares(mixture, thresholds, sd, bias)


def real_shares(mixture: SeverityMixture, thresholds: ArrayLike) -> NDArray[np.float64]:
    """Exact share of each true level, 1 to 5: the thresholds on G alone."""
    return _shares(mixture, thresholds, mixture.sds.ravel(), 0.0)


def thresholds_for_mixture(
    mixture: SeverityMixture, target_shares: ArrayLike, noise: float, bias: float
) -> tuple[float, ...]:
    """The four thresholds whose assigned mix of ``G + ε`` is ``target_shares``.

    Threshold ``c_k`` is the root of «share of ``G + ε`` above ``c_k`` = target
    share of levels 1 to k», a decreasing function of ``c_k``.
    """
    target = np.asarray(target_shares, dtype=float)
    cumulative = np.cumsum(target / target.sum())[:N_THRESHOLDS]
    w, m = mixture.weights.ravel(), mixture.means.ravel()
    sd = np.sqrt(mixture.sds.ravel() ** 2 + noise**2)
    low, high = (m + bias).min() - 40 * sd.max(), (m + bias).max() + 40 * sd.max()

    def above(c: float, q: float) -> float:
        return float(special.ndtr(-(c - m - bias) / sd) @ w) - q

    return tuple(
        float(optimize.brentq(above, low, high, args=(q,), xtol=1e-14)) for q in cumulative
    )


def thresholds_for(
    profiles: ClinicalProfiles, arrival_profile: ArrivalProfile
) -> tuple[float, ...]:
    """The thresholds that give ``reparto_objetivo`` as the assigned mix of a year.

    Uses the noise and bias of ``profiles.triage``. It is run once, and its
    result written in ``config/perfiles.toml`` as ``umbrales``.
    """
    t = profiles.triage
    return thresholds_for_mixture(
        severity_mixture(profiles, arrival_profile), t.target_shares, t.noise, t.bias
    )


def interval_nodes(
    mixture: SeverityMixture, edges: ArrayLike
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Gauss-Legendre nodes of G per component and interval, with their weights.

    For component ``c`` and the interval ``(edges[i + 1], edges[i]]``, cut at
    ``mean ± TAIL_SDS * sd``, it gives ``QUADRATURE_NODES`` nodes ``g`` and
    weights such that ``sum(weights[c, i] * f(g[c, i]))`` is the integral of
    ``f`` times the normal density of the component over the interval. An
    interval outside the cut gets zero weights. So the share of the mixture in
    the interval with some property of g is ``mixture weights @ sum(weights *
    f(g))``: the one integrator of the exact values of the triage, the tests
    and the durations.

    Args:
        mixture: The mixture of G.
        edges: Decreasing edges of the intervals, from ``+inf`` to ``-inf``,
            such as ``+inf``, the four thresholds and ``-inf``.

    Returns:
        ``g`` and ``weights``, both of shape (components, intervals, nodes),
        with the components flattened in the order of ``mixture.weights.ravel()``.
    """
    edges = np.asarray(edges, dtype=float)
    m, s = mixture.means.ravel()[:, None], mixture.sds.ravel()[:, None]
    lo = np.maximum(edges[None, 1:], m - TAIL_SDS * s)  # (components, intervals)
    hi = np.minimum(edges[None, :-1], m + TAIL_SDS * s)
    half = (np.clip(hi - lo, 0, None) / 2)[..., None]
    g = (lo[..., None] + half) + half * _NODES
    density = np.exp(-0.5 * ((g - m[..., None]) / s[..., None]) ** 2) / (
        s[..., None] * np.sqrt(2 * np.pi)
    )
    return g, density * half * _NODE_WEIGHTS


def triage_matrix(
    mixture: SeverityMixture, thresholds: ArrayLike, noise: float, bias: float
) -> NDArray[np.float64]:
    """Exact joint share of each true level (rows) and assigned level (columns).

    For each component and each interval ``(c_i, c_{i-1}]`` of true level i,
    the cell ``(i, j)`` is the integral over g of the normal density of the
    component times ``P(c_j < g + ε <= c_{j-1})``, a difference of two normal
    CDFs. The integral is computed with ``interval_nodes`` (Gauss-Legendre on
    the interval, cut at ``mean ± TAIL_SDS * sd``).

    Returns:
        A 5×5 array adding up to 1. Its row sums are ``real_shares`` and its
        column sums, ``assigned_shares``.
    """
    edges = _edges(thresholds)
    g, weights = interval_nodes(mixture, edges)  # (components, levels, nodes)
    # P(G + ε above each edge | g), from +inf (0) to -inf (1).
    above = special.ndtr(-(edges[:, None, None, None] - g[None] - bias) / noise)
    return np.einsum("c,cin,jcin->ij", mixture.weights.ravel(), weights, np.diff(above, axis=0))


def triage_error_rates(matrix: ArrayLike) -> tuple[float, float]:
    """Undertriage and overtriage of a joint matrix (rows true, columns assigned).

    Undertriage is the mass above the diagonal (assigned level j > true level
    i: less urgent); overtriage, below it.
    """
    matrix = np.asarray(matrix, dtype=float)
    return float(np.triu(matrix, 1).sum()), float(np.tril(matrix, -1).sum())


def triage_error_for(
    profiles: ClinicalProfiles,
    arrival_profile: ArrivalProfile,
    *,
    start: tuple[float, float] = (0.32, -0.08),
    tolerance: float = 1e-10,
    max_evaluations: int = 200,
) -> tuple[float, float]:
    """Noise and bias that give the targets of under- and overtriage over a year.

    At each evaluation the thresholds are recomputed for the trial noise and
    bias (``thresholds_for_mixture``), so the assigned mix is always the
    target. The two equations (undertriage and overtriage at their targets)
    are solved with ``scipy.optimize.root`` from ``start``. It is run once, and
    its result written in ``config/perfiles.toml`` as ``ruido`` and ``sesgo``.

    Args:
        profiles: The profiles, for the mixture and the targets of ``[triaje]``.
        arrival_profile: The arrival profile, for the weight of each context.
        start: Starting noise and bias; the values of the specification.
        tolerance: Largest error allowed in each rate, as a fraction.
        max_evaluations: Evaluations of the rates before giving up.

    Returns:
        The noise and the bias, as Python floats.

    Raises:
        RuntimeError: If the root does not converge, misses the targets by more
            than ``tolerance`` or has a noise that is not positive.
    """
    mixture = severity_mixture(profiles, arrival_profile)
    t = profiles.triage
    targets = np.array([t.under_pct, t.over_pct]) / 100

    def residual(x: NDArray[np.float64]) -> NDArray[np.float64]:
        noise, bias = x
        if noise <= 0:
            return np.ones(2)
        thresholds = thresholds_for_mixture(mixture, t.target_shares, noise, bias)
        return np.array(triage_error_rates(triage_matrix(mixture, thresholds, noise, bias)))

    solution = optimize.root(
        lambda x: residual(x) - targets,
        np.asarray(start, dtype=float),
        method="hybr",
        options={"maxfev": max_evaluations, "xtol": 1e-13},
    )
    noise, bias = (float(x) for x in solution.x)
    error = float(np.max(np.abs(residual(solution.x) - targets)))
    if not solution.success or error > tolerance or noise <= 0:
        raise RuntimeError(
            f"triage_error_for did not converge after {solution.nfev} evaluations: "
            f"largest error {error:.3g} ({solution.message})"
        )
    return noise, bias


def severity_from_draw(severity: Severity, band: int, z: float) -> float:
    """G of a patient of ``band`` with the standard normal draw ``z``."""
    return float(severity.mean + severity.age_shift[band] + severity.sd * z)


def triage_from_draws(
    g: float, z_noise: float, thresholds: ArrayLike, noise: float, bias: float
) -> tuple[int, int]:
    """Assigned and true level of a patient with severity ``g`` and error draw ``z_noise``.

    The assigned level cuts ``g + bias + noise * z_noise``; the true level cuts ``g``.
    """
    assigned = level_of(g + (bias + noise * z_noise), thresholds)
    return assigned, level_of(g, thresholds)


def triage_quality(assigned: int, true: int) -> tuple[str, int]:
    """Quality of a triage and its jump in levels.

    Returns:
        ``CORRECT``, ``UNDER`` (the assigned level is less urgent: a larger
        number) or ``OVER``, and ``|assigned - true|``.
    """
    if assigned > true:
        return UNDER, assigned - true
    if assigned < true:
        return OVER, true - assigned
    return CORRECT, 0
