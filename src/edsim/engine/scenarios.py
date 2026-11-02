"""Teaching scenarios and model variants, for the notebook and the tests.

As ``arrivals/faults.py`` in milestone 2, these live in the package and are
tested, so that the notebook only calls them and the tests and the notebook
share the same cases.

- ``three_boxes``: the hand-made scenario of the conceptual session (P1 to P5
  in three boxes), with fixed arrivals and draws, so every instant of its log
  is known in advance: a level 1 displaces a level 5 in the middle of its
  assessment, a level 2 gets the box before the displaced patient, and the
  displaced patient resumes with the time it had left.
- ``exponential_triage``: the engine's sampler with an exponential triage of
  the same mean as the lognormal. With the same mean and CV 1 instead of 0.57,
  the M/G/1 of the triage becomes an M/M/1: the factor ``(1 + CV²) / 2`` of
  Pollaczek–Khinchine made visible.
"""

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from edsim.arrivals.thinning import ArrivalRecord
from edsim.engine.center import CenterConfig
from edsim.engine.clinical import PatientDraws, ProvisionalSampler
from edsim.engine.engine import EngineRun, Sampler, run_engine
from edsim.engine.events import Event, EventLog, MemorySink
from edsim.engine.validation import SamplerFactory, flat_profile, mg1_center, pollaczek_khinchine
from edsim.seeds import child_streams

SCENARIO_START = date(2026, 1, 5)
"""Date of minute 0 of the scenarios: a Monday, as the arrival profile."""


def hand_draws(level: int, triage: float, assessment: float, **kwargs: object) -> PatientDraws:
    """Draws chosen by hand: without tests and discharged unless told otherwise.

    Args:
        level: Triage level, 1 to 5.
        triage: Duration of the triage, in minutes.
        assessment: Duration of the first assessment.
        **kwargs: Any other field of ``PatientDraws``; by default
            ``reassessment_time`` 10, ``needs_tests`` false,
            ``test_turnaround`` 60 and ``admitted`` false.
    """
    values = {
        "reassessment_time": 10.0,
        "needs_tests": False,
        "test_turnaround": 60.0,
        "admitted": False,
    } | kwargs
    return PatientDraws(level=level, triage_time=triage, assessment_time=assessment, **values)


@dataclass(frozen=True, slots=True)
class Scenario:
    """Fixed arrivals and draws on a center.

    Attributes:
        center: The center of the scenario.
        patients: ``(arrival time, draws)`` of each patient, in arrival order;
            patient ``i`` is ``arrival_id`` ``i``.
        days: Horizon in full days.
    """

    center: CenterConfig
    patients: tuple[tuple[float, PatientDraws], ...]
    days: int = 1

    @property
    def arrivals(self) -> tuple[ArrivalRecord, ...]:
        """The arrival records, numbered from 0."""
        return tuple(ArrivalRecord(i, t) for i, (t, _) in enumerate(self.patients))

    def sampler(self, arrival: ArrivalRecord) -> PatientDraws:
        """The draws of the patient of ``arrival``, as the engine asks for them."""
        return self.patients[arrival.arrival_id][1]


@dataclass(frozen=True, slots=True)
class ScenarioRun:
    """The log of a scenario and what ``run_engine`` returned.

    Attributes:
        events: The events, in file order.
        run: Ground truth of the episodes and the patients still inside.
    """

    events: list[Event]
    run: EngineRun


def run_scenario(scenario: Scenario, run_id: str = "rescenario") -> ScenarioRun:
    """Simulate a scenario into memory, from ``SCENARIO_START``."""
    sink = MemorySink()
    run = run_engine(
        scenario.center,
        scenario.arrivals,
        scenario.sampler,
        EventLog(run_id, SCENARIO_START, sink),
        scenario.days,
    )
    return ScenarioRun(sink.events, run)


THREE_BOXES_PATIENTS: tuple[tuple[float, PatientDraws], ...] = (
    (0.0, hand_draws(3, 5, 60)),  # P1, EP-000000: box 1 from 5 to 65
    (1.0, hand_draws(4, 5, 60)),  # P2, EP-000001: box 2 from 6 to 66
    (2.0, hand_draws(5, 5, 40)),  # P3, EP-000002: box 3 at 7, assessment 7-47
    (10.0, hand_draws(2, 5, 20)),  # P4, EP-000003: waits for a box from 15
    (15.0, hand_draws(1, 5, 30, admitted=True)),  # P5, EP-000004: triaged at 20
)
"""The patients of the three-box scenario.

P1 (level 3), P2 (level 4) and P3 (level 5) take the three boxes; P4 (level 2)
waits; P5 (level 1) ends its triage at 20 and displaces P3, the highest key,
13 minutes into its 40-minute assessment. P5 leaves at 50 and its box goes to
P4, not to P3, who arrived earlier; P3 gets box 1 when P1 leaves at 65 and
resumes with the 27 minutes it had left, until 92.
"""


def three_boxes(center: CenterConfig) -> Scenario:
    """The three-box scenario on ``center``, with 3 boxes and 3 triage nurses.

    Three nurses in every shift: the scenario starts at minute 0, at night,
    and its instants assume that the first three patients are triaged at once.
    The doctors of ``center`` must be at least 3 at night, so that no patient
    waits for a doctor.
    """
    small = dataclasses.replace(center, boxes=3, triage_nurses=(3, 3, 3))
    return Scenario(small, THREE_BOXES_PATIENTS)


def exponential_triage(center: CenterConfig) -> SamplerFactory:
    """Sampler factory with an exponential triage of the same mean as the lognormal.

    The rest of the draws are the ``ProvisionalSampler``'s, from streams 1 to
    4 of ``child_streams(seed, 6)``; the exponential comes from stream 5, of
    its own, so nothing else changes. For ``check_mg1(...,
    sampler_factory=...)``: the theory still comes from the lognormal, so the
    check must fail.

    Args:
        center: A center with one triage nurse in every shift, such as
            ``mg1_center(...)``, whose triage time gives the mean.
    """
    mean = pollaczek_khinchine(mg1_center(center), flat_profile()).mean_service

    def factory(seed: np.random.SeedSequence) -> Sampler:
        streams: Sequence[np.random.SeedSequence] = child_streams(seed, 6)
        base = ProvisionalSampler(center, streams[1:5])
        rng = np.random.default_rng(streams[5])

        def sampler(arrival: ArrivalRecord) -> PatientDraws:
            return dataclasses.replace(base(arrival), triage_time=float(rng.exponential(mean)))

        return sampler

    return factory
