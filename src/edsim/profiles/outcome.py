"""The exact outcome of milestone 5: patience, destinations and the wait for a bed.

Three pieces of docs/specs/hito-5.md, with the values of the milestone 5 block
of the profiles (``[abandono]``, ``[destinos]`` and the ``ingreso`` of each
reason) and of ``[camas]`` of the center:

- **Patience** (decision 70, H5-4): a lognormal per true level, ``[mediana,
  p90]`` in minutes, with the median of the age band multiplied by its factor
  (σ does not change), counted from the arrival.
- **Destinations** (decision 71, H5-5): a multinomial logit with discharge as
  the reference. The odds of destination d against discharge are ``p_d,m /
  p_alta,m · OR_G,d^G · OR_mayor,d^mayor · OR_alt,d^k``, with ``p_d,m`` the
  base percentages of an adult under 65 with G = 0 and no abnormal tests (the
  admission per reason m, transfer and death global), ``p_alta,m = 100 −
  their sum``, G the true severity, ``mayor`` 1 from 65 years and k the number
  of abnormal tests among the ordered ones. The sampler draws the destination
  with Gumbel-max on these odds.
- **Wait for a bed** (decision 72, H5-6): a lognormal ``[mediana, p90]`` with
  factor 1; the engine multiplies it by the factors of the shift and the
  season of the request (``engine.clinical.BedWaitFactors``).

``OutcomeModel`` integrates the destinations over a year of the arrival
profile, without simulating: over the mixture of G with the Gauss-Legendre
integrator of milestone 4 (``WorkupModel.nodes``) and, at each node, over the
exact distribution of k. Given G, each type of test is abnormal *and ordered*
with probability ``P(ordered) · P(abnormal)``, independently of the others, so
k is the sum of four Bernoulli with different probabilities: a Poisson
binomial (``abnormal_count_distribution``). The result of a test that is not
ordered does not count.

The module does not import the engine nor SimPy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy import special

from edsim.arrivals.profile import ArrivalProfile
from edsim.lognormal import lognormal_params
from edsim.profiles.config import (
    DESTINATIONS,
    N_BANDS,
    N_DESTINATIONS,
    N_LEVELS,
    N_TEST_TYPES,
    Abandonment,
    ClinicalProfiles,
    OutcomeProfile,
)
from edsim.profiles.durations import duration_params, lognormal_mean
from edsim.profiles.mixing import gumbel_max
from edsim.profiles.workup import WorkupModel, abnormal_logit, older_bands, workup_model

N_ABNORMAL_COUNTS = N_TEST_TYPES + 1
"""Possible numbers of abnormal tests among the ordered ones: 0 to 4."""


def require_outcome(profiles: ClinicalProfiles) -> OutcomeProfile:
    """The milestone 5 block of ``profiles``.

    Raises:
        ValueError: If the profiles have no milestone 5 block.
    """
    if profiles.outcome is None:
        raise ValueError(
            "the outcome of milestone 5 needs the block [abandono], [destinos] and the "
            "ingreso of every reason in the profiles, and these have none"
        )
    return profiles.outcome


# Patience.


def patience_params(abandonment: Abandonment, true_level: int, band: int) -> tuple[float, float]:
    """``(mu, sigma)`` of the patience of a true level and an age band.

    ``mu = ln(paciencia_edad[band] · mediana)``: the factor moves the median
    and the p90 together, so σ is that of the level.
    """
    median, p90 = abandonment.patience[true_level - 1]
    return duration_params(median, p90, abandonment.age_factors[band])


def patience_cdf(abandonment: Abandonment, true_level: int, band: int, minutes: float) -> float:
    """P(patience <= ``minutes``) of a patient of ``true_level`` and ``band``."""
    if minutes <= 0:
        return 0.0
    mu, sigma = patience_params(abandonment, true_level, band)
    return float(special.ndtr((math.log(minutes) - mu) / sigma))


def patience_quantile(abandonment: Abandonment, true_level: int, band: int, q: float) -> float:
    """The ``q`` quantile of the patience of ``true_level`` and ``band``, in minutes."""
    mu, sigma = patience_params(abandonment, true_level, band)
    return math.exp(mu + sigma * float(special.ndtri(q)))


def patience_from_draw(abandonment: Abandonment, true_level: int, band: int, z: float) -> float:
    """The patience, in minutes, that the standard normal ``z`` (stream 8) gives."""
    mu, sigma = patience_params(abandonment, true_level, band)
    return math.exp(mu + sigma * z)


# Wait for a bed.


def bed_wait_from_draw(bed_wait: tuple[float, float], z: float) -> float:
    """The base wait for a bed (factor 1), in minutes, that ``z`` (stream 9) gives.

    Args:
        bed_wait: ``[mediana, p90]`` of ``[camas]`` of the center (``espera``).
        z: The standard normal draw of the patient.
    """
    mu, sigma = lognormal_params(*bed_wait)
    return math.exp(mu + sigma * z)


def bed_wait_mean(bed_wait: tuple[float, float]) -> float:
    """Mean base wait for a bed: ``mediana · exp(σ² / 2)``."""
    return lognormal_mean(*lognormal_params(*bed_wait))


# Destinations.


def destination_log_odds(
    outcome: OutcomeProfile,
    admission_pct: ArrayLike,
    older: ArrayLike,
    g: ArrayLike,
    k: ArrayLike,
) -> NDArray[np.float64]:
    """Log odds of each destination against discharge, on the last axis (4 values).

    Discharge is 0. Works on arrays: ``admission_pct``, ``older``, ``g`` and
    ``k`` broadcast together.

    Args:
        outcome: The milestone 5 block.
        admission_pct: ``ingreso`` of the patient's reason, in (0, 100).
        older: Whether the patient's band is older (``older_bands``): 1 or 0.
        g: True severity G.
        k: Number of abnormal tests among the ordered ones, 0 to 4.
    """
    pct = np.asarray(admission_pct, dtype=float)
    older = np.asarray(older, dtype=float)
    g = np.asarray(g, dtype=float)
    k = np.asarray(k, dtype=float)
    reference = 100 - pct - outcome.transfer.base - outcome.death.base
    bases = (pct, outcome.transfer.base, outcome.death.base)
    shape = np.broadcast_shapes(pct.shape, older.shape, g.shape, k.shape)
    logs = [np.zeros(shape)]
    for d, base in zip(outcome.destinations, bases, strict=True):
        logs.append(
            np.broadcast_to(
                np.log(base / reference)
                + math.log(d.severity_or) * g
                + math.log(d.older_or) * older
                + math.log(d.abnormal_or) * k,
                shape,
            )
        )
    return np.stack(logs, axis=-1)


def destination_probabilities(
    outcome: OutcomeProfile, admission_pct: ArrayLike, older: ArrayLike, g: ArrayLike, k: ArrayLike
) -> NDArray[np.float64]:
    """Probability of each destination, in the order of ``DESTINATIONS``, on the last axis.

    ``P(d) = odds_d / (1 + Σ odds)``, the softmax of ``destination_log_odds``.
    """
    return special.softmax(destination_log_odds(outcome, admission_pct, older, g, k), axis=-1)


def destination_from_draws(
    outcome: OutcomeProfile,
    admission_pct: float,
    older: bool,
    g: float,
    k: int,
    gumbels: ArrayLike,
) -> str:
    """The destination that four standard Gumbel draws give (Gumbel-max, stream 4).

    The winner is the destination with the largest log odds plus its draw, in
    the order of ``DESTINATIONS``; discharge has log odds 0. A tie has
    probability 0, and goes to the first.
    """
    odds = np.exp(destination_log_odds(outcome, admission_pct, float(older), g, k))
    return DESTINATIONS[gumbel_max(odds, gumbels)]


def abnormal_count_distribution(q: ArrayLike) -> NDArray[np.float64]:
    """Distribution of the number of successes of four independent Bernoulli.

    Args:
        q: Probability of each, on the last axis (4 values), such as ``P(ordered)
            · P(abnormal)`` of each type of test given G.

    Returns:
        P(k) for k = 0 to 4, on the last axis: the Poisson binomial, built one
        Bernoulli at a time.
    """
    q = np.asarray(q, dtype=float)
    if q.shape[-1:] != (N_TEST_TYPES,):
        raise ValueError(f"q must have {N_TEST_TYPES} values on its last axis, got {q.shape}")
    pk = np.zeros((*q.shape[:-1], N_ABNORMAL_COUNTS))
    pk[..., 0] = 1.0
    for t in range(N_TEST_TYPES):
        p = q[..., t, None]
        shifted = np.zeros_like(pk)
        shifted[..., 1:] = pk[..., :-1]
        pk = pk * (1 - p) + shifted * p
    return pk


@dataclass(frozen=True, slots=True, eq=False)
class OutcomeModel:
    """The exact destinations of a year of the arrival profile, with the written values.

    Built with ``outcome_model``. Components are the 68 pairs (reason, band) of
    the mixture of G, in the order of ``workup.mixture.weights.ravel()``. The
    bases are read as written in the profiles, never derived again: a scenario
    with more of a severe reason gives more admission.

    Attributes:
        profiles: The profiles, with the milestone 5 block.
        workup: The exact model of the tests of the same year, for its nodes.
        admission_pct: ``ingreso`` of the reason of each component, shape (68,).
        older: Whether the band of each component is older, shape (68,).
    """

    profiles: ClinicalProfiles
    workup: WorkupModel
    admission_pct: NDArray[np.float64]
    older: NDArray[np.float64]

    @property
    def outcome(self) -> OutcomeProfile:
        return self.profiles.outcome

    def joint(self, edges: ArrayLike) -> NDArray[np.float64]:
        """Share of the year at each node, number of abnormal tests and destination.

        Returns:
            An array of shape (68, intervals, nodes, 5, 4): for each component,
            interval of ``edges`` and node of G, the mass of the node times
            ``P(k | g)`` times ``P(d | g, k)``. It adds up to the share of the
            year in each interval.
        """
        g, mass, p = self.workup.nodes(edges)
        abnormal = np.stack(
            [special.expit(abnormal_logit(t, g)) for t in self.profiles.diagnostic_tests], axis=-1
        )
        pk = abnormal_count_distribution(p * abnormal)  # (68, I, N, 5)
        probs = destination_probabilities(
            self.outcome,
            self.admission_pct[:, None, None, None],
            self.older[:, None, None, None],
            g[..., None],
            np.arange(N_ABNORMAL_COUNTS),
        )  # (68, I, N, 5, 4)
        return (mass[..., None] * pk)[..., None] * probs

    def _all(self) -> NDArray[np.float64]:
        return self.joint([np.inf, -np.inf])

    def year_shares(self) -> NDArray[np.float64]:
        """Share of the patients of a year with each destination, of shape (4,)."""
        return self._all().sum(axis=(0, 1, 2, 3))

    def by_reason(self) -> NDArray[np.float64]:
        """Share of each destination among the patients of each reason, of shape (17, 4).

        The «marginal of a year» of each reason, to read clinically.
        """
        joint = self._all().sum(axis=(1, 2, 3)).reshape(-1, N_BANDS, N_DESTINATIONS).sum(axis=1)
        return joint / joint.sum(axis=1, keepdims=True)

    def reason_shares(self) -> NDArray[np.float64]:
        """Share of the year of each reason, of shape (17,)."""
        return self.workup.mixture.weights.sum(axis=1)

    def _by_interval(self, edges: ArrayLike) -> NDArray[np.float64]:
        joint = self.joint(edges).sum(axis=(0, 2, 3))  # (intervals, 4)
        return joint / joint.sum(axis=1, keepdims=True)

    def by_true_level(self) -> NDArray[np.float64]:
        """Share of each destination among the patients of each true level, of shape (5, 4)."""
        return self._by_interval(self.workup.level_edges())

    def by_severity(self, n: int = 5) -> NDArray[np.float64]:
        """Share of each destination within ``n`` intervals of G of equal mass, shape (n, 4).

        Rows go from the most severe interval down, as ``WorkupModel.severity_edges``.
        """
        return self._by_interval(self.workup.severity_edges(n))

    def by_abnormal_count(self) -> NDArray[np.float64]:
        """Share of each destination among the patients with k abnormal tests, shape (5, 4)."""
        joint = self._all().sum(axis=(0, 1, 2))
        return joint / joint.sum(axis=1, keepdims=True)

    def abnormal_count_shares(self) -> NDArray[np.float64]:
        """Share of the year with k = 0 to 4 abnormal tests among the ordered ones, shape (5,)."""
        return self._all().sum(axis=(0, 1, 2, 4))

    def by_assigned_level(self) -> NDArray[np.float64]:
        """Share of each destination among the patients of each assigned level, shape (5, 4).

        The nurse assigns the level by ``G + ε``, with ``ε`` normal of mean
        ``sesgo`` and deviation ``ruido``; the destination depends on G. At each
        node, ``P(assigned j | g)`` is a difference of two normal CDFs, as in
        ``severity.triage_matrix``.
        """
        g, _, _ = self.workup.nodes([np.inf, -np.inf])
        t = self.profiles.triage
        edges = self.workup.level_edges()
        above = special.ndtr(-(edges[:, None, None, None] - g[None] - t.bias) / t.noise)
        assigned = np.diff(above, axis=0)  # (5, 68, 1, N)
        joint = np.einsum("jcin,cinkd->jd", assigned, self._all())
        return joint / joint.sum(axis=1, keepdims=True)

    def true_level_band_shares(self) -> NDArray[np.float64]:
        """Share of the year of each true level (rows) and age band (columns), shape (5, 4)."""
        _, mass, _ = self.workup.nodes(self.workup.level_edges())  # (68, 5, N)
        by_component = mass.sum(axis=2)  # (68, 5)
        return by_component.reshape(-1, N_BANDS, N_LEVELS).sum(axis=0).T


def outcome_model(profiles: ClinicalProfiles, arrival_profile: ArrivalProfile) -> OutcomeModel:
    """The exact model of the destinations over a year of the arrival profile.

    Raises:
        ValueError: If the profiles have no milestone 5 block.
    """
    require_outcome(profiles)
    workup = workup_model(profiles, arrival_profile)
    n_bands = workup.mixture.weights.shape[1]
    pct = np.array([r.admission_pct for r in profiles.reasons], dtype=float)
    older = np.array(older_bands(profiles.population), dtype=float)
    return OutcomeModel(
        profiles=profiles,
        workup=workup,
        admission_pct=np.repeat(pct, n_bands),
        older=np.tile(older, len(profiles.reasons)),
    )
