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

The model of milestone 5 adds the outcome (``OutcomeDraws``, task 5.1): the
patience, the destination and the base wait for a ward bed. Task 5.1 injects
it by hand in the scenarios of ``engine.scenarios``; the sampler of task 5.2
draws it.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING

import numpy as np

from edsim.arrivals.thinning import ArrivalRecord
from edsim.engine.center import (
    N_LEVELS,
    N_SHIFTS,
    CenterConfig,
    _check_shift_starts,
    require_destination,
    require_provisional,
)
from edsim.engine.events import DESTINATIONS
from edsim.finite import to_float
from edsim.lognormal import Z90 as Z90  # re-exported: imported from here before 4.4
from edsim.lognormal import lognormal_params
from edsim.profiles.config import N_SEASONS
from edsim.profiles.context import arrival_context
from edsim.profiles.sampler import Outcome

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


def _finite(name: str, value: object, *, positive: bool = False) -> float:
    """``value`` as a float if it is a finite number >= 0 (> 0 if ``positive``).

    ``to_float`` turns an int too large for a float, such as ``10**400``, into
    ``None``, so it fails here with a ``ValueError`` and not an ``OverflowError``.
    """
    limit = "> 0" if positive else ">= 0"
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or (number := to_float(value)) is None
        or not math.isfinite(number)
        or number < 0
        or (positive and number == 0)
    ):
        raise ValueError(f"{name} must be a finite number {limit}, got {value!r}")
    return number


def _factors(name: str, values: object, n: int) -> tuple[float, ...]:
    if isinstance(values, str) or not isinstance(values, list | tuple) or len(values) != n:
        raise ValueError(f"{name} must be {n} factors, got {values!r}")
    return tuple(_finite(f"{name}[{i}]", v, positive=True) for i, v in enumerate(values))


@dataclass(frozen=True, slots=True)
class BedWaitFactors:
    """The factors of the wait for a bed by the instant it is requested (H5-6).

    One per run, shared by every patient, as ``TurnaroundShifts`` for the tests:
    the shift is the one of the center (``[turnos]``) and the
    season the one of the date (``arrival_context``), both of the instant of
    ``bed_requested``, not of the arrival.

    Attributes:
        start_date: Date of minute 0, at 00:00.
        shift_starts: Starting hour of the morning, afternoon and night shifts.
        shift_factors: Factor of each shift, in that order.
        season_factors: Factor of each season: winter, spring, summer, autumn.

    Raises:
        ValueError: If a value is not valid: ``start_date`` must be a date
            without time, the shift starts three increasing hours in 0-23, and
            the factors finite and positive.
    """

    start_date: date
    shift_starts: tuple[int, ...]
    shift_factors: tuple[float, ...]
    season_factors: tuple[float, ...] = (1.0,) * N_SEASONS

    def __post_init__(self) -> None:
        # datetime is a subclass of date: a date-time must not pass as a date.
        if not isinstance(self.start_date, date) or isinstance(self.start_date, datetime):
            raise ValueError(f"start_date must be a date without time, got {self.start_date!r}")
        # The same rule as turnos.inicio of the center.
        object.__setattr__(
            self, "shift_starts", _check_shift_starts("shift_starts", self.shift_starts)
        )
        object.__setattr__(
            self, "shift_factors", _factors("shift_factors", self.shift_factors, N_SHIFTS)
        )
        object.__setattr__(
            self, "season_factors", _factors("season_factors", self.season_factors, N_SEASONS)
        )

    def factor_at(self, t: float) -> float:
        """``factor_turno × factor_estacion`` of the instant ``t``, in minutes since minute 0.

        One calendar computation: the shift band of ``arrival_context`` with the
        shift starts of the center is its shift, as ``shifts.shift_at`` gives it.
        """
        context = arrival_context(t, self.start_date, self.shift_starts)
        return self.shift_factors[context.shift_band] * self.season_factors[context.season]


@dataclass(frozen=True, slots=True)
class OutcomeDraws:
    """What a patient of milestone 5 drew for its outcome (task 5.1).

    Attributes:
        patience: Minutes from the arrival the patient waits before leaving
            without being seen (H5-4). A level 1 never leaves, whatever it is.
        destination: One of ``DESTINATIONS``; used only if the patient stays.
        bed_base: Wait for a bed with factor 1, in minutes; used only if
            the patient is admitted.
        beds: The factors of the run by the instant of the request.
        truth: Everything the outcome sampler drew for the patient (task 5.3),
            also what is not used, for the ground truth; ``None`` for the
            patients written by hand in the scenarios of the engine.

    Raises:
        ValueError: If ``patience`` or ``bed_base`` is not a finite number
            >= 0, ``destination`` is not one of ``DESTINATIONS``, or ``truth``
            does not have the same patience, destination and base wait.
    """

    patience: float
    destination: str
    bed_base: float
    beds: BedWaitFactors
    truth: Outcome | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "patience", _finite("patience", self.patience))
        object.__setattr__(self, "bed_base", _finite("bed_base", self.bed_base))
        if not isinstance(self.destination, str) or self.destination not in DESTINATIONS:
            raise ValueError(
                f"destination must be one of {DESTINATIONS!r}, got {self.destination!r}"
            )
        if not isinstance(self.beds, BedWaitFactors):
            raise ValueError(f"beds must be a BedWaitFactors, got {self.beds!r}")
        if self.truth is not None:
            if not isinstance(self.truth, Outcome):
                raise ValueError(f"truth must be an Outcome, got {self.truth!r}")
            drawn = (self.truth.patience, self.truth.destination, self.truth.bed_base)
            if (self.patience, self.destination, self.bed_base) != drawn:
                raise ValueError(
                    "patience, destination and bed_base must be those of truth: got "
                    f"{(self.patience, self.destination, self.bed_base)!r}, drawn {drawn!r}"
                )

    @classmethod
    def from_outcome(cls, outcome: Outcome, beds: BedWaitFactors) -> "OutcomeDraws":
        """What the engine reads of what ``OutcomeSampler`` drew, which it keeps as truth."""
        return cls(
            patience=outcome.patience,
            destination=outcome.destination,
            bed_base=outcome.bed_base,
            beds=beds,
            truth=outcome,
        )

    def bed_wait(self, t: float) -> float:
        """Minutes from asking for a bed at ``t`` to getting it.

        ``bed_base × factor_turno × factor_estacion``, with the shift and the
        season of ``t``, the instant of ``bed_requested``, not of the arrival.
        """
        return self.bed_base * self.beds.factor_at(t)


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
        outcome: The outcome of milestone 5 (``OutcomeDraws``), or ``None``
            with the provisional model and the one of milestone 4. With it,
            the destination is ``outcome.destination`` and ``admitted`` is
            only kept consistent with it.

    Raises:
        ValueError: If ``test_turnaround`` and ``clinical`` are both given or
            both missing, ``needs_tests`` is not whether the clinical patient
            has a round, ``outcome`` comes without ``clinical`` (version 4 of
            the catalog has the clinical payloads), or ``admitted`` is not
            whether the destination of ``outcome`` is ``ingreso``.
    """

    level: int
    triage_time: float
    assessment_time: float
    reassessment_time: float
    needs_tests: bool
    test_turnaround: float | None
    admitted: bool
    clinical: "ClinicalDraws | None" = None
    outcome: OutcomeDraws | None = None

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
        if self.outcome is not None:
            if self.clinical is None:
                raise ValueError("an outcome needs the clinical draws: version 4 is clinical")
            if self.admitted != (self.outcome.destination == "ingreso"):
                raise ValueError(
                    f"admitted={self.admitted!r} but the destination of the outcome is "
                    f"{self.outcome.destination!r}"
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
            probabilities of tests and admission: it needs the provisional
            block (``[triaje]``, ``[duraciones]`` and ``[pruebas]``), as
            ``tests/data/centro_ejemplo.toml``.
        streams: Exactly four ``numpy.random.SeedSequence``: level, durations,
            tests and destination. The engine passes children 1 to 4 of
            ``child_streams(seed, 5)`` (child 0 is for the arrivals). The
            objects are not modified, so the same ones give the same draws.

    Raises:
        ValueError: If the center has no provisional block or no ``[destino]``,
            or ``streams`` is not four ``SeedSequence``.
    """

    def __init__(self, center: CenterConfig, streams: Sequence[np.random.SeedSequence]) -> None:
        require_provisional(center)
        require_destination(center)
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
