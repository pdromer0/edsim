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

The model is provisional (docs/specs/hito-3.md). The clinical model of
milestone 4 (``clinical_sampler.ClinicalSampler``) has the same interface and
fills ``PatientDraws.clinical``; the provisional sampler stays for the
validation of the engine, which needs a simple model with known theory.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from edsim.arrivals.thinning import ArrivalRecord
from edsim.engine.center import N_LEVELS, CenterConfig
from edsim.lognormal import Z90 as Z90  # re-exported: imported from here before 4.4
from edsim.lognormal import lognormal_params

if TYPE_CHECKING:
    from edsim.engine.clinical_sampler import ClinicalDraws

N_STREAMS = 4
"""Streams of the sampler: level, durations, tests and destination."""


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


def classified_at_the_door(level: int) -> bool:
    """Whether a patient of this assigned level skips the triage nurse.

    A level 1 is classified at the door and goes straight to a box (ADR
    candidate 39): its triage lasts 0 and its drawn ``triage_time`` is not used,
    like the turnaround of a patient without tests.
    """
    return level == 1


def triage_duration(level: int, triage_time: float) -> float:
    """Minutes of triage the patient actually spends: 0 at the door."""
    return 0.0 if classified_at_the_door(level) else triage_time


@dataclass(frozen=True, slots=True)
class PatientDraws:
    """What a patient draws on arrival; the hidden truth of the episode.

    Values are Python ``int``, ``float`` and ``bool``, not NumPy scalars. The
    engine reads the first seven fields with both models; ``clinical`` exists
    only with the clinical model.

    Attributes:
        level: Triage level, 1 (most urgent) to 5. With the clinical model it
            is the *assigned* level: the priority, the door and the
            destination use it.
        triage_time: Duration of the triage, in minutes; drawn always, not
            used by a level 1 (see ``classified_at_the_door``).
        assessment_time: Duration of the first assessment.
        reassessment_time: Duration of the reassessment, used only if the
            patient has tests.
        needs_tests: Whether the doctor orders tests; with the clinical
            model, whether some type of test is ordered (there is a round).
        test_turnaround: From ordering the tests to their results; drawn
            always, used only if ``needs_tests``. ``None`` with the clinical
            model, whose turnaround depends on the shift band of the order and
            is known only then (``clinical.round_turnaround``).
        admitted: Whether the patient is admitted; otherwise discharged.
        clinical: What the clinical model drew (``ClinicalDraws``), or
            ``None`` with the provisional model.

    Raises:
        ValueError: If ``test_turnaround`` and ``clinical`` are both given or
            both missing, or ``needs_tests`` is not whether the clinical
            patient has a round.
    """

    level: int
    triage_time: float
    assessment_time: float
    reassessment_time: float
    needs_tests: bool
    test_turnaround: float | None
    admitted: bool
    clinical: "ClinicalDraws | None" = None

    def __post_init__(self) -> None:
        if (self.clinical is None) == (self.test_turnaround is None):
            raise ValueError(
                "give test_turnaround with the provisional model, or clinical without it: "
                f"got test_turnaround={self.test_turnaround!r} and clinical={self.clinical!r}"
            )
        if self.clinical is not None and self.needs_tests != self.clinical.truth.workup.has_round:
            raise ValueError(
                f"needs_tests={self.needs_tests!r} but the clinical patient "
                f"{'has' if self.clinical.truth.workup.has_round else 'has no'} round of tests"
            )


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
