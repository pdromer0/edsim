"""Durations of each patient: triage, assessment and reassessment.

Each duration is a lognormal given by ``[mediana, p90]`` in minutes, with
``mu = ln(median)`` and ``sigma = (ln p90 - ln median) / Z90``, as in
milestone 3 (``edsim.lognormal``):

- **triage** (``[triaje] duracion``): one lognormal for levels 2 to 5, with no
  factor per reason. It is drawn for every patient; a level 1 is classified at
  the door and the engine does not use it (``engine.clinical.triage_duration``).
- **assessment and reassessment** (``[duraciones]``): a base per *true*
  level, because the doctor sees the patient in front of them, and the factor
  k of the reason (``duracion``) on the median: ``mu = ln(k * median_n)``,
  ``sigma = sigma_n``. Multiplying the median by k moves the lognormal without
  changing sigma, so the mean is multiplied by k too. The reassessment is
  drawn always and used only when there is a round of tests.

**Fixed consumption** (stream 2, ADR candidate 43): three standard normals per
patient, in that order, whatever comes out.

**Exact values.** ``DurationModel`` gives, over the mixture of a year, the
share of each reason and true level, the means, the distribution functions
(mixtures of lognormals) and their quantiles, and the load of the doctor per
patient: ``E[assessment] + E[reassessment · 1{some test}]``, with G inside the
integral because it moves both the level and the tests. These are the
hypotheses of ``validation.check_durations``.
"""

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy import optimize, special

from edsim.arrivals.profile import ArrivalProfile
from edsim.lognormal import lognormal_params
from edsim.profiles.config import N_LEVELS, ClinicalProfiles, ReasonProfile
from edsim.profiles.workup import WorkupModel, workup_model

N_DURATION_DRAWS = 3
"""Standard normals of stream 2 per patient: triage, assessment and reassessment."""

ASSESSMENT = "valoracion"
"""Name of the assessment in the exact functions, as in ``[duraciones]``."""

REASSESSMENT = "reevaluacion"
"""Name of the reassessment in the exact functions, as in ``[duraciones]``."""

_FIELDS = {ASSESSMENT: "assessment", REASSESSMENT: "reassessment"}


def duration_params(median: float, p90: float, factor: float = 1.0) -> tuple[float, float]:
    """``(mu, sigma)`` of a lognormal ``[median, p90]`` with its median times ``factor``.

    ``mu = ln(factor * median)`` and ``sigma`` does not change. The sampler and
    the exact values share it.
    """
    mu, sigma = lognormal_params(median, p90)
    return mu + math.log(factor), sigma


def lognormal_mean(mu: float, sigma: float) -> float:
    """Mean of the lognormal: ``exp(mu + sigma² / 2)``."""
    return math.exp(mu + sigma**2 / 2)


def draw_durations_standard(rng: np.random.Generator) -> NDArray[np.float64]:
    """The three standard normals of one patient from stream 2: triage, assessment, reassessment."""
    return np.array([rng.standard_normal() for _ in range(N_DURATION_DRAWS)])


@dataclass(frozen=True, slots=True)
class PatientDurations:
    """The durations of one patient in minutes, for the engine and the ground truth.

    Attributes:
        triage_time: Triage by the nurse; not used by a level 1.
        assessment_time: First assessment by the doctor.
        reassessment_time: Reassessment after the tests; used only if there
            is a round.
        draws: The three standard normals of stream 2.
    """

    triage_time: float
    assessment_time: float
    reassessment_time: float
    draws: tuple[float, ...]


def durations_from_draws(
    profiles: ClinicalProfiles, reason: ReasonProfile, true_level: int, draws: ArrayLike
) -> PatientDurations:
    """The durations that the three standard normals give to a patient.

    Args:
        profiles: The profiles, for ``[triaje] duracion`` and ``[duraciones]``.
        reason: The patient's reason, for its factor k (``duracion``).
        true_level: The true level, 1 to 5 (not the assigned one).
        draws: The three normals of ``draw_durations_standard``.

    Raises:
        ValueError: If ``draws`` does not have three values or the level is
            not 1 to 5.
    """
    draws = np.asarray(draws, dtype=float)
    if draws.shape != (N_DURATION_DRAWS,):
        raise ValueError(f"draws must have {N_DURATION_DRAWS} values, got shape {draws.shape}")
    if (
        isinstance(true_level, bool)
        or not isinstance(true_level, int | np.integer)
        or not 1 <= true_level <= N_LEVELS
    ):
        raise ValueError(f"true_level must be 1 to {N_LEVELS}, got {true_level!r}")
    z_triage, z_assessment, z_reassessment = (float(z) for z in draws)
    k, d = reason.duration_factor, profiles.durations

    def draw(pair: tuple[float, float], z: float, factor: float = 1.0) -> float:
        mu, sigma = duration_params(*pair, factor)
        return math.exp(mu + sigma * z)

    return PatientDurations(
        triage_time=draw(profiles.triage.duration, z_triage),
        assessment_time=draw(d.assessment[true_level - 1], z_assessment, k),
        reassessment_time=draw(d.reassessment[true_level - 1], z_reassessment, k),
        draws=(z_triage, z_assessment, z_reassessment),
    )


@dataclass(frozen=True, slots=True)
class PhysicianLoad:
    """Minutes of doctor per patient over a year, exact.

    Attributes:
        assessment: Mean assessment, with the factors k.
        reassessment: Mean reassessment of every patient (drawn always).
        reassessment_with_tests: ``E[reassessment · 1{some test}]``: only the
            patients with a round are reassessed.
        k_ratio: Mean assessment with the factors k over the mean without
            them: the rule of the k is 1 ± 0.05.
        mean_k: Simple mean of k per patient, ``sum over reasons of share × k``.
    """

    assessment: float
    reassessment: float
    reassessment_with_tests: float
    k_ratio: float
    mean_k: float

    @property
    def load(self) -> float:
        """Minutes of doctor per patient: assessment plus the reassessments that happen."""
        return self.assessment + self.reassessment_with_tests


@dataclass(frozen=True, slots=True, eq=False)
class DurationModel:
    """The exact durations over the mixture of G of a year. Built with ``duration_model``.

    Attributes:
        workup: The exact model of the tests, with the mixture and the
            written thresholds.
        reason_level: Share of the patients of a year with each reason (rows)
            and true level (columns), of shape (17, 5), adding up to 1.
    """

    workup: WorkupModel
    reason_level: NDArray[np.float64]

    @property
    def profiles(self) -> ClinicalProfiles:
        return self.workup.profiles

    def _k(self) -> NDArray[np.float64]:
        return np.array([r.duration_factor for r in self.profiles.reasons])

    def params(self, which: str, k: ArrayLike | None = None):
        """``mu`` of shape (17, 5) and ``sigma`` of shape (5,) for each reason and level."""
        pairs = getattr(self.profiles.durations, _FIELDS[which])
        k = self._k() if k is None else np.asarray(k, dtype=float)
        mu = np.array([[duration_params(*pair, f)[0] for pair in pairs] for f in k])
        sigma = np.array([duration_params(*pair)[1] for pair in pairs])
        return mu, sigma

    def _means(self, which: str, k=None) -> NDArray[np.float64]:
        mu, sigma = self.params(which, k)
        return np.exp(mu + sigma**2 / 2)  # (17, 5)

    def mean(self, which: str) -> float:
        """Mean of the duration over the patients of a year, with the factors k."""
        return float((self.reason_level * self._means(which)).sum())

    def mean_by_level(self, which: str) -> NDArray[np.float64]:
        """Mean of the duration per true level, of shape (5,)."""
        return (self.reason_level * self._means(which)).sum(axis=0) / self.reason_level.sum(axis=0)

    def mean_by_reason(self, which: str) -> NDArray[np.float64]:
        """Mean of the duration per reason, of shape (17,)."""
        return (self.reason_level * self._means(which)).sum(axis=1) / self.reason_level.sum(axis=1)

    def _mixture(self, level: int | None, reason: int | None) -> NDArray[np.float64]:
        """Weights of the (reason, level) lognormals within the group asked for."""
        w = np.zeros_like(self.reason_level)
        if level is not None and reason is None:
            w[:, level - 1] = self.reason_level[:, level - 1]
        elif reason is not None and level is None:
            w[reason] = self.reason_level[reason]
        else:
            raise ValueError("give either a true level (1 to 5) or a reason index, not both")
        return w / w.sum()

    def cdf(self, which: str, x: float, *, level: int | None = None, reason: int | None = None):
        """P(duration <= x) among the patients of one true level or of one reason.

        A mixture of lognormals: one per reason within a level, or one per
        level within a reason, weighted by their share of the year.
        """
        if x <= 0:
            return 0.0
        mu, sigma = self.params(which)
        w = self._mixture(level, reason)
        return float((w * special.ndtr((math.log(x) - mu) / sigma)).sum())

    def quantile(
        self, which: str, q: float, *, level: int | None = None, reason: int | None = None
    ) -> float:
        """The ``q`` quantile of the duration among one true level or one reason."""
        return float(
            optimize.brentq(
                lambda x: self.cdf(which, x, level=level, reason=reason) - q,
                1e-6,
                1e6,
                xtol=1e-12,
                rtol=1e-14,
            )
        )

    def physician_load(self) -> PhysicianLoad:
        """The load of the doctor per patient, with the reassessment only after a round."""
        g, mass, p = self.workup.nodes(self.workup.level_edges())  # (68, 5, nodes)
        some_test = 1 - np.prod(1 - p, axis=-1)
        n_bands = self.workup.mixture.weights.shape[1]
        # E[1{some test}] per (reason, level): sum over bands and nodes.
        tests = (some_test * mass).sum(axis=2).reshape(-1, n_bands, N_LEVELS).sum(axis=1)
        reassessment = self._means(REASSESSMENT)
        shares = self.reason_level.sum(axis=1)
        return PhysicianLoad(
            assessment=self.mean(ASSESSMENT),
            reassessment=self.mean(REASSESSMENT),
            reassessment_with_tests=float((tests * reassessment).sum()),
            k_ratio=self.mean(ASSESSMENT)
            / float((self.reason_level * self._means(ASSESSMENT, np.ones(len(shares)))).sum()),
            mean_k=float(shares @ self._k()),
        )


def duration_model(profiles: ClinicalProfiles, arrival_profile: ArrivalProfile) -> DurationModel:
    """The exact model of the durations over a year of the arrival profile."""
    workup = workup_model(profiles, arrival_profile)
    _, mass, _ = workup.nodes(workup.level_edges())
    n_bands = workup.mixture.weights.shape[1]
    reason_level = mass.sum(axis=2).reshape(-1, n_bands, N_LEVELS).sum(axis=1)
    return DurationModel(workup=workup, reason_level=reason_level)


def physician_load(profiles: ClinicalProfiles, arrival_profile: ArrivalProfile) -> PhysicianLoad:
    """The load of the doctor per patient over a year: ``duration_model(...).physician_load()``."""
    return duration_model(profiles, arrival_profile).physician_load()
