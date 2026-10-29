"""Provisional clinical model: what each patient draws on arrival.

Everything random about a patient is drawn when the patient arrives, in a fixed
order, even what will not be used (the test turnaround of a patient without
tests, for instance). Each source of randomness has its own stream, and each
patient consumes the same amount of numbers from each stream. So patient k
gets the same values whatever the staffing or the queues: only the waits
change (common random numbers). Changing one parameter, such as the
probability of tests, does not shift the numbers of the other sources.

Numbers drawn per patient, from each of the four streams:

1. level: one uniform;
2. durations: three lognormals (triage, assessment, reassessment);
3. tests: one uniform (whether there are tests) and one lognormal (turnaround);
4. destination: one uniform (admission or discharge).

The model is provisional (docs/specs/hito-3.md): milestone 4 will replace the
inside of the sampler, with latent severity and reasons for consultation,
without changing its interface.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import NormalDist

import numpy as np

from edsim.arrivals.thinning import ArrivalRecord
from edsim.engine.center import N_LEVELS, CenterConfig

Z90 = NormalDist().inv_cdf(0.9)
"""90th percentile of the standard normal, 1.2815515..."""

N_STREAMS = 4
"""Streams of the sampler: level, durations, tests and destination."""


def lognormal_params(median: float, p90: float) -> tuple[float, float]:
    """Parameters ``(mu, sigma)`` of the normal behind a lognormal.

    If ``X = exp(Y)`` with ``Y ~ Normal(mu, sigma)``, the median of ``X`` is
    ``exp(mu)`` and its 90th percentile is ``exp(mu + Z90 * sigma)``. Solving
    for both gives ``mu = ln(median)`` and
    ``sigma = (ln(p90) - ln(median)) / Z90``.

    These are what ``numpy.random.Generator.lognormal(mean, sigma)`` expects:
    the mean and the standard deviation of the normal, not of the lognormal.

    Args:
        median: Median of the lognormal; positive.
        p90: 90th percentile; greater than the median.

    Returns:
        ``(mu, sigma)``.

    Raises:
        ValueError: If the median is not positive or ``p90 <= median``.
    """
    if not median > 0:
        raise ValueError(f"median must be positive, got {median!r}")
    if not p90 > median:
        raise ValueError(f"p90 must be greater than the median, got {p90!r} <= {median!r}")
    mu = math.log(median)
    return mu, (math.log(p90) - mu) / Z90


def cumulative_shares(shares: Sequence[float]) -> tuple[float, ...]:
    """Cumulative sum of the level shares, for ``searchsorted``.

    With a uniform ``u`` in [0, 1), the level is
    ``searchsorted(cum, u, side="right") + 1``: the first level whose
    cumulative share is greater than ``u``. A level with share 0 has the same
    cumulative value as the previous one, so it is never chosen.

    In floating point the cumulative sum may stop just below 1, such as
    0.9999999999999999 with ``[0.3, 12.1, 33.6, 52.6, 0]`` normalized. A ``u``
    in that gap would choose the next level even with share 0. So every value
    from the last level with a positive share on is set to exactly 1.0.

    Args:
        shares: Non-negative shares that add up to 1 (up to rounding), with at
            least one positive.

    Returns:
        The cumulative shares, non-decreasing and ending in exactly 1.0.
    """
    cum = list(np.cumsum(shares, dtype=float))
    last = max(i for i, x in enumerate(shares) if x > 0)
    for i in range(last, len(cum)):
        cum[i] = 1.0
    return tuple(float(x) for x in cum)


@dataclass(frozen=True, slots=True)
class PatientDraws:
    """What a patient draws on arrival; the hidden truth of the episode.

    Values are Python ``int``, ``float`` and ``bool``, not NumPy scalars.

    Attributes:
        level: Triage level, 1 (most urgent) to 5.
        triage_time: Duration of the triage, in minutes.
        assessment_time: Duration of the first assessment.
        reassessment_time: Duration of the reassessment, used only if the
            patient has tests.
        needs_tests: Whether the doctor orders tests.
        test_turnaround: From ordering the tests to their results; drawn
            always, used only if ``needs_tests``.
        admitted: Whether the patient is admitted; otherwise discharged.
    """

    level: int
    triage_time: float
    assessment_time: float
    reassessment_time: float
    needs_tests: bool
    test_turnaround: float
    admitted: bool


class ProvisionalSampler:
    """Draws of each patient on arrival, with the provisional model of milestone 3.

    Call it once per arrival, in arrival order, to get the draws of that
    patient. Each stream gets its own ``numpy.random.Generator``, and each call
    consumes a fixed amount of numbers from each one (see the module
    docstring).

    The sampler receives the arrival but does not use it yet. In milestone 4
    the case mix (level, reasons for consultation) will depend on the hour and
    the season of the arrival; with this signature the engine will not change.

    Args:
        center: Configuration with the level shares, durations, and
            probabilities of tests and admission.
        streams: Exactly four ``numpy.random.SeedSequence``: level, durations,
            tests and destination. The engine passes children 1 to 4 of
            ``child_streams(seed, 5)`` (child 0 is for the arrivals). The
            objects are not modified, so the same ones give the same draws.

    Raises:
        ValueError: If ``streams`` is not four ``SeedSequence``.
    """

    def __init__(self, center: CenterConfig, streams: Sequence[np.random.SeedSequence]) -> None:
        streams = list(streams)
        if len(streams) != N_STREAMS:
            raise ValueError(f"streams must have {N_STREAMS} SeedSequence, got {len(streams)}")
        for i, stream in enumerate(streams):
            if not isinstance(stream, np.random.SeedSequence):
                raise ValueError(f"streams[{i}] must be a SeedSequence, got {stream!r}")
        self._level_rng, self._duration_rng, self._test_rng, self._destination_rng = (
            np.random.default_rng(s) for s in streams
        )

        self._cum_shares = np.array(cumulative_shares(center.level_shares))
        self._triage = lognormal_params(*center.triage_time)
        self._assessment = lognormal_params(*center.assessment_time)
        self._reassessment = lognormal_params(*center.reassessment_time)
        self._turnaround = lognormal_params(*center.test_turnaround)
        self._test_probability = center.test_probability
        self._admission_probability = center.admission_probability

    def __call__(self, arrival: ArrivalRecord) -> PatientDraws:
        """Draws of the patient of ``arrival``, the next one in arrival order."""
        # Fixed consumption per patient: never skip a draw, even if unused.
        u_level = self._level_rng.random()
        level = int(np.searchsorted(self._cum_shares, u_level, side="right")) + 1
        assert 1 <= level <= N_LEVELS  # guaranteed by cumulative_shares

        triage_time = self._duration_rng.lognormal(*self._triage)
        assessment_time = self._duration_rng.lognormal(*self._assessment)
        reassessment_time = self._duration_rng.lognormal(*self._reassessment)

        needs_tests = self._test_rng.random() < self._test_probability[level - 1]
        test_turnaround = self._test_rng.lognormal(*self._turnaround)

        admitted = self._destination_rng.random() < self._admission_probability[level - 1]

        return PatientDraws(
            level=level,
            triage_time=float(triage_time),
            assessment_time=float(assessment_time),
            reassessment_time=float(reassessment_time),
            needs_tests=bool(needs_tests),
            test_turnaround=float(test_turnaround),
            admitted=bool(admitted),
        )
