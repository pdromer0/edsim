"""Teaching scenarios and model variants, for the notebook and the tests.

As ``arrivals/faults.py`` in milestone 2, these live in the package and are
tested, so that the notebook only calls them and the tests and the notebook
share the same cases.

- ``three_boxes``: the hand-made scenario of the conceptual session (P1 to P5
  in three boxes), with fixed arrivals and draws, so every instant of its log
  is known in advance: a level 1 displaces a level 5 in the middle of its
  assessment, a level 2 gets the box before the displaced patient, and the
  displaced patient resumes with the time it had left.
- The scenarios of milestone 5 (task 5.1, docs/specs/hito-5.md), with
  patients of version 4 made by hand (``outcome_draws``): the abandonment from
  its three places and the tie (``abandonment``, M in the specification), the
  deadline due during the triage (``late_triage``, T), the displacement
  before and after being seen (``unseen_displacement``, X), a level 1 that
  waits without leaving (``level1_waits``, L), a patient who leaves no
  more after being seen (``seen_in_room``, S), the wait for a bed in the box
  and in the corridor (``admission``, C), the shift of the request
  (``bed_shift``) and the departures without a wait (``destinations``, D).
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
from edsim.engine.clinical import BedWaitFactors, OutcomeDraws, PatientDraws, ProvisionalSampler
from edsim.engine.clinical_sampler import ClinicalDraws, ClinicalTruth, TurnaroundShifts
from edsim.engine.engine import EngineRun, Sampler, run_engine
from edsim.engine.events import (
    OUTCOME_SCHEMA_VERSION,
    PROVISIONAL_SCHEMA_VERSION,
    Event,
    EventLog,
    MemorySink,
)
from edsim.engine.validation import SamplerFactory, flat_profile, mg1_center, pollaczek_khinchine
from edsim.profiles.config import N_SHIFT_BANDS, TEST_TYPES
from edsim.profiles.context import ArrivalContext
from edsim.profiles.population import Person
from edsim.profiles.sampler import SeverityAndTriage
from edsim.profiles.severity import triage_quality
from edsim.profiles.workup import Workup
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
        schema_version: Version of the log: 1 for the provisional patients,
            ``OUTCOME_SCHEMA_VERSION`` (4) for those of ``outcome_draws``.
    """

    center: CenterConfig
    patients: tuple[tuple[float, PatientDraws], ...]
    days: int = 1
    schema_version: int = PROVISIONAL_SCHEMA_VERSION

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
        EventLog(run_id, SCENARIO_START, sink, schema_version=scenario.schema_version),
        scenario.days,
    )
    return ScenarioRun(sink.events, run)


THREE_BOXES_PATIENTS: tuple[tuple[float, PatientDraws], ...] = (
    (0.0, hand_draws(3, 5, 60)),  # P1, EP-000000: box 1 from 5 to 65
    (1.0, hand_draws(4, 5, 60)),  # P2, EP-000001: box 2 from 6 to 66
    (2.0, hand_draws(5, 5, 40)),  # P3, EP-000002: box 3 at 7, assessment 7-47
    (10.0, hand_draws(2, 5, 20)),  # P4, EP-000003: waits for a box from 15
    (20.0, hand_draws(1, 5, 30, admitted=True)),  # P5, EP-000004: at the door at 20
)
"""The patients of the three-box scenario.

P1 (level 3), P2 (level 4) and P3 (level 5) take the three boxes; P4 (level 2)
waits; P5 (level 1) arrives at 20, is classified at the door in that instant
(task 4.1; it arrived at 15 and was triaged until 20 in milestone 3, so every
other instant is the same) and displaces P3, the highest key, 13 minutes into
its 40-minute assessment. P5 leaves at 50 and its box goes to
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


# --- Milestone 5: patients of version 4 by hand (task 5.1) ---------------------------

SCENARIO_SHIFT_STARTS = (8, 15, 22)
"""Shift starts of the scenarios of milestone 5: those of ``tests/data/centro_ejemplo.toml``."""

SCENARIO_BEDS = BedWaitFactors(SCENARIO_START, SCENARIO_SHIFT_STARTS, (0.8, 1.0, 1.5))
"""Factors of the bed of the scenarios: 0.8 in the morning, 1 in the afternoon, 1.5 at
night (docs/specs/hito-5.md, scenario C), and 1 in every season."""

HAND_PATIENCE = 10_000.0
"""Patience of a hand-made patient unless told otherwise: it never runs out in a day."""

_ONE_FACTORS = TurnaroundShifts(
    SCENARIO_START, SCENARIO_SHIFT_STARTS, ((1.0,) * len(TEST_TYPES),) * N_SHIFT_BANDS
)
"""Turnaround factors 1 in every shift band: a round lasts its base turnaround."""


def outcome_draws(
    level: int,
    triage: float,
    assessment: float,
    *,
    patience: float = HAND_PATIENCE,
    destination: str = "alta",
    bed_base: float = 100.0,
    turnaround: float | None = None,
    reassessment: float = 10.0,
    beds: BedWaitFactors = SCENARIO_BEDS,
) -> PatientDraws:
    """Draws of a patient of version 4 chosen by hand, without profiles.

    The clinical part is fixed and plays no role in the scenarios: a woman of
    50 who came by her own means with ``otros``, its true level the assigned
    one. Only its tests matter: with ``turnaround`` the patient orders a blood
    test (``analitica``) whose results take exactly those minutes, as the
    factors of the shift bands are 1.

    Args:
        level: Assigned (and true) level, 1 to 5.
        triage: Duration of the triage; not used by a level 1.
        assessment: Duration of the first assessment.
        patience: Minutes from the arrival before leaving without being seen.
        destination: One of ``DESTINATIONS``.
        bed_base: Wait for a bed with factor 1; used only with ``ingreso``.
        turnaround: Minutes of the round of tests, or ``None`` for no tests.
        reassessment: Duration of the reassessment, with tests.
        beds: Factors of the bed by shift and season.
    """
    ordered = tuple(t == "analitica" and turnaround is not None for t in TEST_TYPES)
    turnarounds = tuple(
        turnaround if t == "analitica" and turnaround is not None else 60.0 for t in TEST_TYPES
    )
    quality, jump = triage_quality(level, level)
    truth = ClinicalTruth(
        context=ArrivalContext(0, 0, 0),
        person=Person(band=1, age=50, female=True, ambulance=False),
        reason="otros",
        triage=SeverityAndTriage(
            z=0.0, severity=0.0, level=level, true_level=level, quality=quality, jump=jump
        ),
        workup=Workup(
            ordered=ordered,
            abnormal=(False,) * len(TEST_TYPES),
            turnarounds=turnarounds,
            draws=(0.0,) * 12,
        ),
    )
    return PatientDraws(
        level=level,
        triage_time=float(triage),
        assessment_time=float(assessment),
        reassessment_time=float(reassessment),
        needs_tests=turnaround is not None,
        test_turnaround=None,
        admitted=destination == "ingreso",
        clinical=ClinicalDraws(truth=truth, shifts=_ONE_FACTORS),
        outcome=OutcomeDraws(patience, destination, bed_base, beds),
    )


def _staffed(
    center: CenterConfig,
    *,
    nurses: int,
    boxes: int,
    doctors: int,
    wait_outside: tuple[int, ...] = (),
) -> CenterConfig:
    """``center`` with the same staff in every shift, so no shift change gets in the way."""
    return dataclasses.replace(
        center,
        boxes=boxes,
        triage_nurses=(nurses,) * 3,
        doctors=(doctors,) * 3,
        results_wait_outside=wait_outside,
    )


def _outcome_scenario(center: CenterConfig, patients) -> Scenario:
    return Scenario(center, tuple(patients), schema_version=OUTCOME_SCHEMA_VERSION)


def abandonment(center: CenterConfig, *, q3_patience: float = 43.0, boxes: int = 2) -> Scenario:
    """Scenario M: the three places of the abandonment and the tie.

    Two nurses, two boxes (one in the variant of the place ``box``) and one
    doctor; triages of 5 minutes. Q1 (level 3) holds the doctor from 5 to 45.
    Q2 (level 4, patience 25) waits for it in box 2 and leaves at 26 with
    ``medico``; Q3 (level 4) gets box 2 then and the doctor at 45, the instant
    its deadline 2 + 43 is due: it stays (with patience 42 it leaves at 44).
    Q4 (level 5, patience 1) leaves at 4 waiting for a nurse.
    """
    return _outcome_scenario(
        _staffed(center, nurses=2, boxes=boxes, doctors=1),
        [
            (0.0, outcome_draws(3, 5, 40)),  # Q1, EP-000000
            (1.0, outcome_draws(4, 5, 20, patience=25)),  # Q2, EP-000001
            (2.0, outcome_draws(4, 5, 20, patience=q3_patience)),  # Q3, EP-000002
            (3.0, outcome_draws(5, 5, 20, patience=1)),  # Q4, EP-000003
        ],
    )


def late_triage(center: CenterConfig, *, boxes: int = 1, doctors: int = 1) -> Scenario:
    """Scenario T: the deadline is due during the triage.

    One nurse. T0 (level 3) is triaged from 0 to 55 and assessed from 55 to
    115. T1 (level 5, patience 60) arrives at 1, is triaged from 55 to 62 and
    its deadline 61 is due in the triage: at 62 it leaves waiting for a box
    (one box), for a doctor (two boxes), or stays if it gets both (two boxes
    and two doctors).
    """
    return _outcome_scenario(
        _staffed(center, nurses=1, boxes=boxes, doctors=doctors),
        [
            (0.0, outcome_draws(3, 55, 60)),  # T0, EP-000000
            (1.0, outcome_draws(5, 7, 10, patience=60)),  # T1, EP-000001
        ],
    )


def unseen_displacement(center: CenterConfig, *, seen: bool = False) -> Scenario:
    """Scenario X: a displacement before being seen, and after (``seen``).

    One nurse, two boxes and one doctor (two if ``seen``); triages of 5. X1
    (level 3) holds box 1 and the doctor from 5 to 45. X2 (level 4) gets box 2
    at 10; X3 (level 1) displaces it at 20. Unseen (patience 30), X2 waits for
    a box and leaves at 31. Seen (two doctors, patience 15, assessment of 30
    from 10), its assessment is cut at 20 and it goes on from 30 to 50 in box
    2, after X3: it does not leave although its deadline was due at 16.
    """
    x2 = outcome_draws(4, 5, 30, patience=15) if seen else outcome_draws(4, 5, 20, patience=30)
    return _outcome_scenario(
        _staffed(center, nurses=1, boxes=2, doctors=2 if seen else 1),
        [
            (0.0, outcome_draws(3, 5, 40)),  # X1, EP-000000
            (1.0, x2),  # X2, EP-000001
            (20.0, outcome_draws(1, 5, 10)),  # X3, EP-000002
        ],
    )


def level1_waits(center: CenterConfig) -> Scenario:
    """Scenario L: two levels 1 with patience 0 and one box; neither leaves.

    L0 holds the box from 0 to 30; L1, arrived at 1, cannot displace another
    level 1 and waits for the box until 30.
    """
    return _outcome_scenario(
        _staffed(center, nurses=1, boxes=1, doctors=1),
        [
            (0.0, outcome_draws(1, 5, 30, patience=0)),  # L0, EP-000000
            (1.0, outcome_draws(1, 5, 10, patience=0)),  # L1, EP-000001
        ],
    )


def seen_in_room(center: CenterConfig) -> Scenario:
    """Scenario S: a patient seen at 20 does not leave, though its deadline is due at 50.

    One nurse, two boxes and one doctor; levels 4 and 5 wait for the results
    outside. P (level 4, patience 50) is assessed from 20 to 30 and waits for
    its results in the room until 90; S (level 3), arrived at 70, holds the
    doctor from 75 to 105, so P waits for its reassessment until 105.
    """
    return _outcome_scenario(
        _staffed(center, nurses=1, boxes=2, doctors=1, wait_outside=(4, 5)),
        [
            (0.0, outcome_draws(4, 20, 10, patience=50, turnaround=60)),  # P, EP-000000
            (70.0, outcome_draws(3, 5, 30)),  # S, EP-000001
        ],
    )


def admission(center: CenterConfig, *, r3_arrival: float | None = 60.0) -> Scenario:
    """Scenario C: the wait for a bed in the box and, displaced, in the corridor.

    One nurse, one box and one doctor; minute 0 is 0:00, at night. R1 (level
    3) is assessed from 5 to 35 and admitted: it asks for a bed at 0:35, night,
    so it waits 100 × 1.5 = 150, until 185, keeping its box. R2 (level 4)
    waits for the box from 15. R3 (level 1, patience 0), arrived at
    ``r3_arrival``, displaces R1, which waits for the bed in the corridor; R2
    gets the box when R3 leaves, at 80. Without R3 (``None``), R2 gets the box
    at 185, when R1 departs.
    """
    patients = [
        (0.0, outcome_draws(3, 5, 30, destination="ingreso", bed_base=100)),  # R1
        (10.0, outcome_draws(4, 5, 20)),  # R2, EP-000001
    ]
    if r3_arrival is not None:
        patients.append((r3_arrival, outcome_draws(1, 5, 20, patience=0)))  # R3
    return _outcome_scenario(_staffed(center, nurses=1, boxes=1, doctors=1), patients)


def bed_shift(center: CenterConfig) -> Scenario:
    """A patient who arrives at 7:30, at night, and asks for a bed at 8:10, in the morning.

    Its bed waits 100 × 0.8 = 80 minutes, the factor of the shift of the
    request, not of the arrival.
    """
    return _outcome_scenario(
        _staffed(center, nurses=1, boxes=1, doctors=1),
        [(450.0, outcome_draws(3, 5, 35, destination="ingreso", bed_base=100))],
    )


def destinations(center: CenterConfig) -> Scenario:
    """Scenario D: transfer, death and discharge depart in the instant of the decision.

    Three nurses, three boxes and three doctors, so nobody waits: each patient
    departs 5 + 10 minutes after arriving, at 15, 16 and 17.
    """
    return _outcome_scenario(
        _staffed(center, nurses=3, boxes=3, doctors=3),
        [
            (0.0, outcome_draws(3, 5, 10, destination="traslado")),
            (1.0, outcome_draws(3, 5, 10, destination="exitus")),
            (2.0, outcome_draws(3, 5, 10, destination="alta")),
        ],
    )


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
