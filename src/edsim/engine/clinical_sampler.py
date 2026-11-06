"""Clinical model in the engine: the ``ClinicalSampler`` and what it gives to each patient.

The ``ClinicalSampler`` has the contract of the ``ProvisionalSampler``,
``sampler(arrival) -> PatientDraws``: it joins the three samplers of
``edsim.profiles.sampler`` and the provisional destination, in a fixed order,
with one stream per source (ADR candidate 43, docs/specs/hito-4.md). The
streams are children 1 to 7 of ``child_streams(seed, 8)``; child 0 is for the
arrivals, as in the provisional model, so the arrivals do not change.

On each arrival, in this order, each with a fixed number of draws whatever
comes out:

1. context, person and reason: streams 5 (4 Gumbel and 3 uniforms) and 6 (17
   Gumbel);
2. latent severity G and triage: streams 7 (the ``z`` of G) and 1 (the error
   of the nurse), one normal each;
3. tests and durations, with G and the true level: streams 3 (12 draws) and 2
   (3 normals);
4. provisional destination: stream 4, one uniform, admitted if it is below
   ``probabilidad_ingreso`` of the *assigned* level (the hospital's decision
   uses what the hospital knows).

The engine reads the same fields of ``PatientDraws`` as with the provisional
model. The turnaround of the round is not known on arrival: it is the slowest
of the ordered tests with the factor of the shift band of the order
(``ClinicalDraws.round_turnaround``), so ``test_turnaround`` is ``None`` and
the patient process asks ``draws.clinical`` when it orders the tests.

The module lives in the engine and not in ``profiles`` because it needs
``PatientDraws`` and the destination of ``CenterConfig``, and ``profiles``
does not import the engine.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from edsim.arrivals.thinning import ArrivalRecord
from edsim.engine.center import N_LEVELS, CenterConfig
from edsim.engine.clinical import PatientDraws
from edsim.engine.events import ARRIVAL_MODES, SEXES, TEST_RESULTS
from edsim.profiles.config import N_SHIFT_BANDS, TEST_TYPES, ClinicalProfiles
from edsim.profiles.context import ArrivalContext, arrival_context
from edsim.profiles.population import Person
from edsim.profiles.sampler import (
    PersonReasonSampler,
    SeverityAndTriage,
    SeverityTriageSampler,
    WorkupDurationSampler,
)
from edsim.profiles.workup import Workup, turnaround_shift_factors

N_SAMPLER_STREAMS = 7
"""Streams of the ``ClinicalSampler``: 1 to 7 of ``child_streams(seed, 8)``."""

CLINICAL_EVENTS = (
    "patient_arrived",
    "patient_registered",
    "triage_completed",
    "test_ordered",
    "test_resulted",
)
"""Event types with a clinical payload in versions 2 and 3 of the catalog."""


@dataclass(frozen=True, slots=True)
class TurnaroundShifts:
    """The factor of each type of test on its turnaround, by shift band of the order.

    One per run, shared by every patient: the shift bands of the profiles
    (not the shifts of the center) and the ``respuesta_franja`` of each type.

    Attributes:
        start_date: Date of minute 0, the arrival profile's ``start_date``.
        shift_band_starts: Starting hours of the morning, afternoon and night.
        factors: For each shift band, the factor of each type in the order of
            ``TEST_TYPES`` (``turnaround_shift_factors``).
    """

    start_date: date
    shift_band_starts: tuple[int, ...]
    factors: tuple[tuple[float, ...], ...]

    @classmethod
    def from_profiles(cls, profiles: ClinicalProfiles, start_date: date) -> "TurnaroundShifts":
        """The factors of ``profiles`` for a run that starts on ``start_date``."""
        return cls(
            start_date=start_date,
            shift_band_starts=tuple(profiles.shift_band_starts),
            factors=tuple(turnaround_shift_factors(profiles, b) for b in range(N_SHIFT_BANDS)),
        )

    def shift_band_at(self, t: float) -> int:
        """Shift band (0 morning, 1 afternoon, 2 night) of the instant ``t``."""
        return arrival_context(t, self.start_date, self.shift_band_starts).shift_band

    def factors_at(self, t: float) -> tuple[float, ...]:
        """Factor of each type for tests ordered at the instant ``t``."""
        return self.factors[self.shift_band_at(t)]


@dataclass(frozen=True, slots=True)
class ClinicalTruth:
    """What the clinical model drew for one patient: the clinical part of its ground truth.

    It is built from the frozen results of the samplers of ``profiles``. Of
    the standard draws it keeps the ``z`` of the severity (in ``triage``) and
    the 12 of the tests (in ``workup``); the other ones (7 of the person, 17
    of the reason and 3 of the durations) can be rebuilt with the seed and the
    assignment of streams.

    Attributes:
        context: Shift band, day type and season of the arrival.
        person: Age band, age, sex and arrival mode.
        reason: Key of the reason for consultation.
        triage: ``z``, the latent severity G, the assigned and true levels,
            the quality of the triage and the jump.
        workup: Whether each type of test is ordered, its result, its base
            turnaround (factor 1) and the 12 standard draws.
    """

    context: ArrivalContext
    person: Person
    reason: str
    triage: SeverityAndTriage
    workup: Workup

    @property
    def arrival_mode(self) -> str:
        """``medio`` of ``patient_arrived``: ``ambulancia`` or ``propios_medios``."""
        ambulance, own = ARRIVAL_MODES
        return ambulance if self.person.ambulance else own

    @property
    def sex(self) -> str:
        """``sexo`` of ``patient_registered``: ``mujer`` or ``hombre``."""
        female, male = SEXES
        return female if self.person.female else male

    @property
    def results(self) -> dict[str, str]:
        """``resultados`` of ``test_resulted``: each ordered type, normal or abnormal."""
        normal, abnormal = TEST_RESULTS
        return {
            t: abnormal if a else normal
            for t, o, a in zip(TEST_TYPES, self.workup.ordered, self.workup.abnormal, strict=True)
            if o
        }


@dataclass(frozen=True, slots=True)
class ClinicalDraws:
    """The clinical part of ``PatientDraws``: the truth and how to time the round.

    Attributes:
        truth: What the patient drew; it goes to the ground truth.
        shifts: The factors of the turnaround by shift band, of the run.
    """

    truth: ClinicalTruth
    shifts: TurnaroundShifts

    def round_turnaround(self, t: float) -> float:
        """Minutes from ordering the tests at ``t`` to their results.

        The slowest of the ordered tests, with the factor of the shift band of
        ``t``, the instant of the order, not of the arrival.

        Raises:
            ValueError: If the patient has no round of tests.
        """
        turnaround = self.truth.workup.round_turnaround(self.shifts.factors_at(t))
        if turnaround is None:
            raise ValueError("the patient has no round of tests")
        return turnaround

    def payload(self, event_type: str) -> dict[str, object]:
        """The clinical keys of the payload of ``event_type`` in versions 2 and 3.

        ``triage_completed`` gets only ``motivo``: its ``nivel`` is the
        engine's, the assigned level.

        Raises:
            ValueError: If ``event_type`` has no clinical payload.
        """
        truth = self.truth
        match event_type:
            case "patient_arrived":
                return {"medio": truth.arrival_mode}
            case "patient_registered":
                return {"edad": truth.person.age, "sexo": truth.sex}
            case "triage_completed":
                return {"motivo": truth.reason}
            case "test_ordered":
                return {"pruebas": truth.workup.ordered_types}
            case "test_resulted":
                return {"resultados": truth.results}
        raise ValueError(f"{event_type!r} has no clinical payload; one of {CLINICAL_EVENTS}")


def admitted_from_draw(u: float, level: int, probabilities: Sequence[float]) -> bool:
    """Provisional destination: admitted if ``u`` is below the probability of ``level``.

    Args:
        u: The uniform of stream 4.
        level: The *assigned* level, 1 to 5: the hospital decides with what it
            knows.
        probabilities: ``probabilidad_ingreso`` of the center, one per level.
    """
    return bool(u < probabilities[level - 1])


class ClinicalSampler:
    """Draws of each patient on arrival, with the clinical profiles (task 4.5a).

    Call it once per arrival, in arrival order. Each call consumes a fixed
    amount of numbers from each stream (see the module docstring).

    Args:
        profiles: The clinical profiles.
        start_date: Date of minute 0 of the arrivals, the arrival profile's
            ``start_date``.
        center: The center, for ``probabilidad_ingreso`` of the provisional
            destination.
        streams: Exactly seven ``numpy.random.SeedSequence``, streams 1 to 7:
            the engine passes children 1 to 7 of ``child_streams(seed, 8)``.
            The objects are not modified, so the same ones give the same
            draws.

    Raises:
        ValueError: If ``streams`` is not seven ``SeedSequence``.
    """

    def __init__(
        self,
        profiles: ClinicalProfiles,
        start_date: date,
        center: CenterConfig,
        streams: Sequence[np.random.SeedSequence],
    ) -> None:
        streams = list(streams)
        if len(streams) != N_SAMPLER_STREAMS:
            raise ValueError(
                f"streams must have {N_SAMPLER_STREAMS} SeedSequence, got {len(streams)}"
            )
        for i, stream in enumerate(streams):
            if not isinstance(stream, np.random.SeedSequence):
                raise ValueError(f"streams[{i}] must be a SeedSequence, got {stream!r}")
        # streams[i] is stream i + 1.
        triage, durations, tests, destination, population, reason, severity = streams
        self._person_reason = PersonReasonSampler(profiles, start_date, [population, reason])
        self._severity_triage = SeverityTriageSampler(profiles, [severity, triage])
        self._workup_durations = WorkupDurationSampler(profiles, [tests, durations])
        self._destination_rng = np.random.default_rng(destination)
        self._admission_probability = tuple(center.admission_probability)
        assert len(self._admission_probability) == N_LEVELS
        self._shifts = TurnaroundShifts.from_profiles(profiles, start_date)

    @property
    def shifts(self) -> TurnaroundShifts:
        """The factors of the turnaround by shift band, shared by every patient."""
        return self._shifts

    def __call__(self, arrival: ArrivalRecord) -> PatientDraws:
        """Draws of the patient of ``arrival``, the next one in arrival order."""
        person_reason = self._person_reason(arrival)
        severity_triage = self._severity_triage(person_reason)
        workup_durations = self._workup_durations(person_reason, severity_triage)
        u = float(self._destination_rng.random())

        workup, durations = workup_durations.workup, workup_durations.durations
        truth = ClinicalTruth(
            context=person_reason.context,
            person=person_reason.person,
            reason=person_reason.reason,
            triage=severity_triage,
            workup=workup,
        )
        return PatientDraws(
            level=severity_triage.level,
            triage_time=durations.triage_time,
            assessment_time=durations.assessment_time,
            reassessment_time=durations.reassessment_time,
            needs_tests=workup.has_round,
            test_turnaround=None,
            admitted=admitted_from_draw(u, severity_triage.level, self._admission_probability),
            clinical=ClinicalDraws(truth=truth, shifts=self._shifts),
        )
