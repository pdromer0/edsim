"""Tests of each patient: whether each type is ordered, its result and its turnaround.

There are four types of test (``TEST_TYPES``), ordered in a single round
(ADR candidate 42). For a patient of reason m, age band b and true severity
G, the type t:

- is ordered with probability ``logistic(logit(p_tm) + ln(or_gravedad_t) * G +
  ln(or_mayor_t) * older)``, where ``p_tm`` is the percentage of the reason
  for an adult with G = 0 and ``older`` is 1 for the bands that start at 65
  or more (``older_bands``);
- has an abnormal result with probability ``logistic(logit(base_t) +
  ln(alterado.or_gravedad_t) * G)``;
- has a base turnaround ``exp(mu_t + sigma_t * z)``, the lognormal of its
  ``respuesta`` with factor 1.

**True severity, not what the nurse sees.** The probabilities use G, not
``G + ε``: the doctor orders for the patient in front of them, so an
undertriaged patient waits like its assigned level but needs the tests of its
true severity.

**Fixed consumption** (stream 3, ADR candidate 43). Each patient draws 12
standard numbers, per type in the order of ``TEST_TYPES``: a uniform to order
it, a uniform for the result and a normal for the turnaround, whether the test
is ordered or not. A test is ordered if its uniform is strictly below the
probability, and abnormal likewise. The result and the turnaround of a test
that is not ordered are drawn too, so that changing the probability of one
test does not shift the draws of the others; nobody uses them.

**The round.** The patient waits for the slowest of the ordered tests:
``round_turnaround`` is the largest ``factor_t * base_t`` over them, or
``None`` without any. The factor of the shift band of the order
(``respuesta_franja``) multiplies the median, which for a lognormal is the
same as multiplying the draw; so the sampler gives the base turnaround and
the engine applies the factor when it orders, in task 4.5
(``turnaround_shift_factors``).

**Exact values.** ``WorkupModel`` holds the mixture of G over a year
(``severity_mixture``) and integrates over it with the one integrator of the
milestone (``severity.interval_nodes``): the share of each test globally, by
reason, by true level and by intervals of G; the share with some test; the
abnormal results; the tests of the undertriaged; and the distribution of the
round. These are the hypotheses of ``validation.check_workup``.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy import integrate, optimize, special

from edsim.arrivals.profile import ArrivalProfile
from edsim.lognormal import lognormal_params
from edsim.profiles.config import (
    N_SHIFT_BANDS,
    N_TEST_TYPES,
    TEST_TYPES,
    ClinicalProfiles,
    DiagnosticTest,
    Population,
)
from edsim.profiles.context import SHIFT_BANDS
from edsim.profiles.population import OLDER_AGE
from edsim.profiles.severity import SeverityMixture, interval_nodes, severity_mixture

N_WORKUP_DRAWS = 3 * N_TEST_TYPES
"""Standard draws of stream 3 per patient: order, result and turnaround of each type."""


def older_bands(population: Population) -> tuple[bool, ...]:
    """Whether each age band is «older»: it starts at ``OLDER_AGE`` (65) or more.

    The sampler and the exact values share it, so that both mean the same
    patients.
    """
    return tuple(start >= OLDER_AGE for start in population.band_starts)


def order_logit(test: DiagnosticTest, pct: ArrayLike, g: ArrayLike, older: ArrayLike):
    """``logit(pct / 100) + ln(or_gravedad) * g + ln(or_mayor) * older``; works on arrays."""
    return (
        special.logit(np.asarray(pct, dtype=float) / 100)
        + math.log(test.severity_or) * np.asarray(g, dtype=float)
        + math.log(test.older_or) * np.asarray(older, dtype=float)
    )


def order_probability(test: DiagnosticTest, pct: float, g: float, older: bool) -> float:
    """Probability of ordering ``test`` for a patient with severity ``g``.

    Args:
        test: The type of test.
        pct: Percentage of the patient's reason for that type, for an adult
            with G = 0, in (0, 100).
        g: True severity G.
        older: Whether the patient's band is older (``older_bands``).
    """
    return float(special.expit(order_logit(test, pct, g, older)))


def abnormal_logit(test: DiagnosticTest, g: ArrayLike):
    """``logit(base / 100) + ln(alterado.or_gravedad) * g``; works on arrays."""
    return special.logit(test.abnormal_pct / 100) + math.log(
        test.abnormal_severity_or
    ) * np.asarray(g, dtype=float)


def abnormal_probability(test: DiagnosticTest, g: float) -> float:
    """Probability that ``test`` comes out abnormal for a patient with severity ``g``."""
    return float(special.expit(abnormal_logit(test, g)))


def turnaround_from_draw(test: DiagnosticTest, z: float) -> float:
    """Base turnaround of ``test`` (factor 1) for the standard normal draw ``z``, in minutes."""
    mu, sigma = lognormal_params(*test.turnaround)
    return math.exp(mu + sigma * z)


def turnaround_shift_factors(
    profiles: ClinicalProfiles, shift_band: int | str
) -> tuple[float, ...]:
    """Factor on the turnaround of each type of test, in the order of ``TEST_TYPES``.

    Args:
        profiles: The profiles, with ``respuesta_franja`` of each type.
        shift_band: The shift band of the order: its index (0 morning, 1
            afternoon, 2 night) or its name in ``SHIFT_BANDS``.

    Raises:
        ValueError: If the shift band is not one of the three.
    """
    if isinstance(shift_band, str):
        if shift_band not in SHIFT_BANDS:
            raise ValueError(f"shift_band must be one of {SHIFT_BANDS}, got {shift_band!r}")
        shift_band = SHIFT_BANDS.index(shift_band)
    elif isinstance(shift_band, bool) or not isinstance(shift_band, int | np.integer):
        raise ValueError(f"shift_band must be an index or a name, got {shift_band!r}")
    if not 0 <= shift_band < N_SHIFT_BANDS:
        raise ValueError(f"shift_band must be between 0 and {N_SHIFT_BANDS - 1}, got {shift_band}")
    return tuple(t.turnaround_shift_factors[shift_band] for t in profiles.diagnostic_tests)


def round_turnaround(
    ordered: Sequence[bool],
    turnarounds: Sequence[float],
    factors: Sequence[float] | None = None,
) -> float | None:
    """Turnaround of the round: the slowest of the ordered tests, or ``None`` without any.

    Args:
        ordered: Whether each type is ordered, in the order of ``TEST_TYPES``.
        turnarounds: Base turnaround of each type (factor 1).
        factors: Factor of each type for the shift band of the order
            (``turnaround_shift_factors``); 1 by default.

    Returns:
        ``max(factor_t * turnaround_t)`` over the ordered types, or ``None``
        if no test is ordered: then there is no round.
    """
    factors = (1.0,) * N_TEST_TYPES if factors is None else factors
    if not len(ordered) == len(turnarounds) == len(factors) == N_TEST_TYPES:
        raise ValueError(f"ordered, turnarounds and factors must have {N_TEST_TYPES} values")
    times = [f * t for o, t, f in zip(ordered, turnarounds, factors, strict=True) if o]
    return max(times) if times else None


def draw_workup_standard(rng: np.random.Generator) -> NDArray[np.float64]:
    """The 12 standard draws of one patient from stream 3.

    Per type, in the order of ``TEST_TYPES``: a uniform to order it, a uniform
    for its result and a standard normal for its turnaround.
    """
    draws = np.empty(N_WORKUP_DRAWS)
    for i in range(N_TEST_TYPES):
        draws[3 * i] = rng.random()
        draws[3 * i + 1] = rng.random()
        draws[3 * i + 2] = rng.standard_normal()
    return draws


@dataclass(frozen=True, slots=True)
class Workup:
    """The tests of one patient, for the engine and the ground truth.

    Every tuple has one value per type, in the order of ``TEST_TYPES``. The
    result and the turnaround exist for every type, ordered or not; only those
    of the ordered tests are used.

    Attributes:
        ordered: Whether each type is ordered.
        abnormal: Whether its result is abnormal.
        turnarounds: Base turnaround of each type in minutes (factor 1).
        draws: The 12 standard draws of stream 3 (``draw_workup_standard``).
    """

    ordered: tuple[bool, ...]
    abnormal: tuple[bool, ...]
    turnarounds: tuple[float, ...]
    draws: tuple[float, ...]

    @property
    def has_round(self) -> bool:
        """Whether some test is ordered: then the patient waits for a round."""
        return any(self.ordered)

    @property
    def ordered_types(self) -> tuple[str, ...]:
        """The ordered types, such as ``("analitica", "ecg")``."""
        return tuple(t for t, o in zip(TEST_TYPES, self.ordered, strict=True) if o)

    def round_turnaround(self, factors: Sequence[float] | None = None) -> float | None:
        """The slowest ordered test with the factors of a shift band; ``None`` without tests."""
        return round_turnaround(self.ordered, self.turnarounds, factors)


def workup_from_draws(
    tests: Sequence[DiagnosticTest],
    test_pct: Sequence[float],
    g: float,
    older: bool,
    draws: ArrayLike,
) -> Workup:
    """The tests that the 12 standard draws give to a patient.

    Args:
        tests: The four types of test, in the order of ``TEST_TYPES``.
        test_pct: The percentages of the patient's reason, in the same order.
        g: True severity G.
        older: Whether the patient's band is older (``older_bands``).
        draws: The 12 draws of ``draw_workup_standard``.

    Raises:
        ValueError: If ``draws`` does not have 12 values.
    """
    draws = np.asarray(draws, dtype=float)
    if draws.shape != (N_WORKUP_DRAWS,):
        raise ValueError(f"draws must have {N_WORKUP_DRAWS} values, got shape {draws.shape}")
    ordered, abnormal, turnarounds = [], [], []
    for i, (test, pct) in enumerate(zip(tests, test_pct, strict=True)):
        u_order, u_result, z = (float(x) for x in draws[3 * i : 3 * i + 3])
        ordered.append(u_order < order_probability(test, pct, g, older))
        abnormal.append(u_result < abnormal_probability(test, g))
        turnarounds.append(turnaround_from_draw(test, z))
    return Workup(
        ordered=tuple(ordered),
        abnormal=tuple(abnormal),
        turnarounds=tuple(turnarounds),
        draws=tuple(float(x) for x in draws),
    )


def severity_quantile_edges(mixture: SeverityMixture, n: int = 5) -> NDArray[np.float64]:
    """Edges of the ``n`` intervals of G with equal mass in the mixture, decreasing.

    Returns ``+inf``, the ``n - 1`` quantiles from the highest down, and
    ``-inf``: the form of ``interval_nodes``. The first interval is the most
    severe fifth of the patients.
    """
    w, m, s = mixture.weights.ravel(), mixture.means.ravel(), mixture.sds.ravel()
    low, high = (m - 40 * s).min(), (m + 40 * s).max()

    def cdf(x: float, q: float) -> float:
        return float(special.ndtr((x - m) / s) @ w) - q

    quantiles = [
        optimize.brentq(cdf, low, high, args=(q,), xtol=1e-13) for q in np.arange(1, n) / n
    ]
    return np.array([np.inf, *quantiles[::-1], -np.inf])


@dataclass(frozen=True, slots=True, eq=False)
class WorkupModel:
    """The exact probabilities of the tests over the mixture of G of a year.

    Built with ``workup_model``. Components are the 68 pairs (reason, band) of
    the mixture, flattened in the order of ``mixture.weights.ravel()``.

    Attributes:
        profiles: The profiles.
        mixture: The mixture of G of a year of the arrival profile.
        thresholds: The written thresholds, to cut the true levels.
        intercepts: ``logit(p_tm) + ln(or_mayor_t) * older_b`` per component
            and type, of shape (68, 4).
    """

    profiles: ClinicalProfiles
    mixture: SeverityMixture
    thresholds: tuple[float, ...]
    intercepts: NDArray[np.float64]

    def nodes(self, edges: ArrayLike):
        """Nodes of G and their mass per component and interval, with the order probabilities.

        Returns:
            ``g`` and ``mass`` of shape (68, intervals, nodes): ``mass`` is the
            share of the year at each node (the weights of ``interval_nodes``
            times the weight of the component), adding up to the share of
            each interval. And ``p``, of shape (68, intervals, nodes, 4): the
            probability of ordering each type.
        """
        g, weights = interval_nodes(self.mixture, edges)
        mass = weights * self.mixture.weights.ravel()[:, None, None]
        p = np.stack(
            [
                special.expit(self.intercepts[:, t, None, None] + math.log(test.severity_or) * g)
                for t, test in enumerate(self.profiles.diagnostic_tests)
            ],
            axis=-1,
        )
        return g, mass, p

    def _abnormal(self, g: NDArray[np.float64]) -> NDArray[np.float64]:
        return np.stack(
            [special.expit(abnormal_logit(t, g)) for t in self.profiles.diagnostic_tests], axis=-1
        )

    def _all(self):
        return self.nodes([np.inf, -np.inf])

    def level_edges(self) -> NDArray[np.float64]:
        """``+inf``, the four thresholds and ``-inf``: the intervals of the true levels."""
        return np.array([np.inf, *self.thresholds, -np.inf])

    def order_shares(self) -> NDArray[np.float64]:
        """Share of the patients of a year with each type of test ordered, of shape (4,)."""
        _, mass, p = self._all()
        return (p * mass[..., None]).sum(axis=(0, 1, 2))

    def any_test_share(self) -> float:
        """Share of the patients with some test: a round."""
        _, mass, p = self._all()
        return float(((1 - np.prod(1 - p, axis=-1)) * mass).sum())

    def _by(self, edges, values, rows: str):
        """Mean of ``values(g, p)`` within each interval (rows "interval") or reason."""
        g, mass, p = self.nodes(edges)
        v = values(g, p)
        weighted = v * mass[..., None] if v.ndim == 4 else v * mass
        if rows == "interval":
            total = mass.sum(axis=(0, 2))
            out = weighted.sum(axis=(0, 2))
        else:  # reason: components are (reason, band) flattened
            n_bands = self.mixture.weights.shape[1]
            total = mass.sum(axis=(1, 2)).reshape(-1, n_bands).sum(axis=1)
            out = weighted.sum(axis=(1, 2))
            out = out.reshape(-1, n_bands, *out.shape[1:]).sum(axis=1)
        return out / (total[:, None] if out.ndim == 2 else total)

    def order_by_reason(self) -> NDArray[np.float64]:
        """Share of each type ordered among the patients of each reason, of shape (17, 4).

        This is the «marginal of a year» of each reason: the share to read
        clinically, not the percentage at G = 0 of the file.
        """
        return self._by([np.inf, -np.inf], lambda g, p: p, "reason")

    def any_test_by_reason(self) -> NDArray[np.float64]:
        """Share of the patients of each reason with some test, of shape (17,)."""
        return self._by([np.inf, -np.inf], lambda g, p: 1 - np.prod(1 - p, axis=-1), "reason")

    def order_by_true_level(self) -> NDArray[np.float64]:
        """Share of each type ordered among the patients of each true level, of shape (5, 4)."""
        return self._by(self.level_edges(), lambda g, p: p, "interval")

    def any_test_by_true_level(self) -> NDArray[np.float64]:
        """Share of the patients of each true level with some test, of shape (5,)."""
        return self._by(self.level_edges(), lambda g, p: 1 - np.prod(1 - p, axis=-1), "interval")

    def severity_edges(self, n: int = 5) -> NDArray[np.float64]:
        """Edges of the ``n`` intervals of G of equal mass (``severity_quantile_edges``)."""
        return severity_quantile_edges(self.mixture, n)

    def order_by_severity(self, n: int = 5) -> NDArray[np.float64]:
        """Share of each type ordered within each of ``n`` equal intervals of G, of shape (n, 4).

        Rows go from the most severe interval down, as ``severity_edges``.
        """
        return self._by(self.severity_edges(n), lambda g, p: p, "interval")

    def abnormal_by_severity(self, n: int = 5) -> NDArray[np.float64]:
        """Share of abnormal results of each type within each interval of G, of shape (n, 4).

        Over all the patients, ordered or not: the result is always drawn.
        """
        return self._by(self.severity_edges(n), lambda g, p: self._abnormal(g), "interval")

    def abnormal_among_ordered(self) -> NDArray[np.float64]:
        """Share of abnormal results among the ordered tests of each type, of shape (4,)."""
        g, mass, p = self._all()
        both = (p * self._abnormal(g) * mass[..., None]).sum(axis=(0, 1, 2))
        return both / (p * mass[..., None]).sum(axis=(0, 1, 2))

    def abnormal_among_ordered_by_true_level(self) -> NDArray[np.float64]:
        """Share of abnormal results among the ordered tests, per true level, of shape (5, 4)."""
        g, mass, p = self.nodes(self.level_edges())
        both = (p * self._abnormal(g) * mass[..., None]).sum(axis=(0, 2))
        return both / (p * mass[..., None]).sum(axis=(0, 2))

    def any_abnormal_given_round(self) -> float:
        """Share of the rounds with some abnormal result among the ordered tests."""
        g, mass, p = self._all()
        some = 1 - np.prod(1 - p * self._abnormal(g), axis=-1)
        return float((some * mass).sum()) / self.any_test_share()

    def undertriage_nodes(self):
        """Nodes of the true levels with ``P(undertriage | g)`` at each node.

        A patient of true level n with severity g is undertriaged when ``g +
        ε <= c_n``, the lower edge of its level: ``Φ((c_n - g - bias) /
        noise)``, and 0 for level 5.
        """
        edges = self.level_edges()
        g, mass, p = self.nodes(edges)
        t = self.profiles.triage
        lower = edges[1:][None, :, None]
        under = special.ndtr((lower - g - t.bias) / t.noise)
        return g, mass, p, under

    def undertriage_share(self) -> float:
        """Share of undertriaged patients with the written thresholds, noise and bias."""
        _, mass, _, under = self.undertriage_nodes()
        return float((under * mass).sum())

    def order_given_undertriage(self) -> NDArray[np.float64]:
        """Share of each type ordered among the undertriaged patients, of shape (4,)."""
        _, mass, p, under = self.undertriage_nodes()
        return (p * (under * mass)[..., None]).sum(axis=(0, 1, 2)) / (under * mass).sum()

    def round_share(self) -> float:
        """Share of the patients with a round (some test): ``any_test_share``."""
        return self.any_test_share()

    def round_cdf(self, x: float, factors: Sequence[float] | None = None) -> float:
        """P(turnaround of the round <= x | there is a round), with the factors of a shift band.

        It is ``E[prod_t (1 - P_t + P_t * F_t(x)) - prod_t (1 - P_t)] / P(round)``,
        where ``F_t`` is the lognormal of type t with its factor: given G the
        four tests are independent, and the round is at most x when every
        ordered test is.
        """
        factors = (1.0,) * N_TEST_TYPES if factors is None else factors
        if x <= 0:
            return 0.0
        g, mass, p = self._all()
        cdf = []
        for test, f in zip(self.profiles.diagnostic_tests, factors, strict=True):
            mu, sigma = lognormal_params(*test.turnaround)
            cdf.append(special.ndtr((math.log(x) - math.log(f) - mu) / sigma))
        within = np.prod(1 - p + p * np.array(cdf), axis=-1) - np.prod(1 - p, axis=-1)
        return float((within * mass).sum()) / self.round_share()

    def round_quantile(self, q: float, factors: Sequence[float] | None = None) -> float:
        """The ``q`` quantile of the turnaround of the round, given there is one."""
        return float(
            optimize.brentq(
                lambda x: self.round_cdf(x, factors) - q, 1e-6, 1e6, xtol=1e-10, rtol=1e-14
            )
        )

    def round_mean(self, factors: Sequence[float] | None = None) -> float:
        """Mean turnaround of the round, given there is one: the integral of its survival."""
        # On the scale of ln x: E[R] = ∫ (1 - F(e^u)) e^u du.
        value, _ = integrate.quad(
            lambda u: (1 - self.round_cdf(math.exp(u), factors)) * math.exp(u),
            -10,
            15,
            limit=200,
            epsabs=1e-10,
            epsrel=1e-12,
        )
        return float(value)


def workup_model(profiles: ClinicalProfiles, arrival_profile: ArrivalProfile) -> WorkupModel:
    """The exact model of the tests over a year of the arrival profile.

    Each component (reason m, band b) of ``severity_mixture`` gets its
    intercept ``logit(p_tm) + ln(or_mayor_t) * older_b`` for each type t.
    """
    mixture = severity_mixture(profiles, arrival_profile)
    older = np.array(older_bands(profiles.population), dtype=float)
    pct = np.array([r.test_pct for r in profiles.reasons])  # (17, 4)
    intercepts = np.stack(
        [
            order_logit(test, pct[:, t, None], 0.0, older[None, :]).ravel()
            for t, test in enumerate(profiles.diagnostic_tests)
        ],
        axis=-1,
    )
    return WorkupModel(
        profiles=profiles,
        mixture=mixture,
        thresholds=profiles.triage.thresholds,
        intercepts=intercepts,
    )
