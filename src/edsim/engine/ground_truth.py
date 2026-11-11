"""Ground truth of a run: what the hospital does not see.

The event log only has what the hospital records. What each patient drew on
arrival, and the daily effect and the counts of the arrival generator, go
apart, here, and are used only to validate (ADR candidate 28). Keeping them out
of the log avoids data leakage into the analytics lab.

In milestone 3 the triage has no error, so the level and the destination of an
episode are also in the log. With the clinical model of milestone 4, an episode
also has its clinical truth (``ClinicalTruth``): the latent severity, the true
level and the quality of the triage, the age band and the turnarounds are only
here, never in the log.
"""

from dataclasses import dataclass, fields
from typing import Self

from edsim.arrivals.thinning import ArrivalRecord, DayRecord
from edsim.engine.clinical import PatientDraws
from edsim.engine.clinical_sampler import ClinicalTruth
from edsim.engine.events import episode_id

# The outcome of milestone 5 is not in the ground truth yet: task 5.3 adds it.
_DRAW_FIELDS = tuple(f.name for f in fields(PatientDraws) if f.name not in ("clinical", "outcome"))


@dataclass(frozen=True, slots=True)
class EpisodeTruth:
    """What one episode drew on arrival, with its arrival.

    Attributes:
        episode_id: Such as ``EP-000137``, as in the log.
        arrival_id: Arrival order, starting at 0.
        arrival_time: ``time`` of the ``ArrivalRecord``, bit for bit as
            ``iter_arrivals`` generated it. The ``sim_time`` of
            ``patient_arrived`` in the log is SimPy's ``env.now``, which may
            differ from it in the last bit (see ``arrival_source``).
        level: Triage level, 1 to 5; the assigned one with the clinical model.
        triage_time: Duration of the triage, in minutes.
        assessment_time: Duration of the first assessment.
        reassessment_time: Duration of the reassessment; used only with tests.
        needs_tests: Whether the doctor orders tests.
        test_turnaround: From ordering the tests to their results; used only
            with tests. ``None`` with the clinical model: its turnaround
            depends on the shift band of the order, and the clinical truth
            keeps the base turnaround of each type.
        admitted: Whether the patient is admitted; otherwise discharged.
        clinical: The clinical truth of the episode, or ``None`` with the
            provisional model.
    """

    episode_id: str
    arrival_id: int
    arrival_time: float
    level: int
    triage_time: float
    assessment_time: float
    reassessment_time: float
    needs_tests: bool
    test_turnaround: float | None
    admitted: bool
    clinical: ClinicalTruth | None = None

    @classmethod
    def from_draws(cls, arrival: ArrivalRecord, draws: PatientDraws) -> Self:
        """The truth of the episode of ``arrival``, with the draws of its patient."""
        return cls(
            episode_id=episode_id(arrival.arrival_id),
            arrival_id=arrival.arrival_id,
            arrival_time=arrival.time,
            **{name: getattr(draws, name) for name in _DRAW_FIELDS},
            clinical=None if draws.clinical is None else draws.clinical.truth,
        )


@dataclass(frozen=True, slots=True)
class GroundTruth:
    """The ground truth of one run.

    Attributes:
        episodes: One per arrival, in arrival order, including the patients
            still inside at the end.
        days: The ``DayRecord`` of each simulated day, from the arrival
            generator.
    """

    episodes: tuple[EpisodeTruth, ...]
    days: tuple[DayRecord, ...]
