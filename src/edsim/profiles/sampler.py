"""Person, reason, severity and triage of each arrival, from streams 5, 6, 7 and 1.

``PersonReasonSampler`` is the first part of the ``ClinicalSampler`` of task
4.5: it turns an arrival into its context, a person (age band, age, sex and
arrival mode) and a reason for consultation. Each patient consumes a fixed
number of standard draws, whatever comes out (ADR candidate 43):

- stream 5 (population): 4 Gumbel draws for the band and 3 uniforms for the
  age, the sex and the arrival mode (``population.draw_person_standard``);
- stream 6 (reason): 17 Gumbel draws, one per reason; the reason is the
  Gumbel-max of its weights for the band and the context.

So patient k gets the same draws whatever the weights, and raising one
reason's weight only moves patients into that reason.

``SeverityTriageSampler`` is the second part: from the person and the reason
it draws the latent severity and the triage, with one standard normal from
each of two streams per patient:

- stream 7 (severity): ``z``, so that ``G = media + por_edad[band] +
  desviacion * z`` (``severity.severity_from_draw``);
- stream 1 (triage): ``z_e``, the error of the nurse ``ε = sesgo + ruido *
  z_e``; the assigned level cuts ``G + ε`` and the true level cuts ``G``
  with the thresholds written in the profiles (``severity.triage_from_draws``).

With another noise, every patient keeps its G and its true level; with
another mean of one reason, only the patients of that reason change their G.

``WorkupDurationSampler`` is the third part: from the person, the reason and
the severity it draws the tests and the durations, with the true severity
and the true level, never what the nurse sees:

- stream 3 (tests): 12 draws, per type in the order of ``TEST_TYPES`` a
  uniform to order it, a uniform for its result and a normal for its base
  turnaround (``workup.workup_from_draws``), whether it is ordered or not;
- stream 2 (durations): 3 normals, for the triage, the assessment and the
  reassessment (``durations.durations_from_draws``).

The ``ClinicalSampler`` of the engine (``edsim.engine.clinical_sampler``,
task 4.5a) joins the three parts with the provisional destination.

``OutcomeSampler`` is the outcome of milestone 5 (task 5.2): from the person,
the reason, the severity and the tests it draws the patience, the destination
and the base wait for a bed, with three streams and a fixed consumption:

- stream 4 (destination): 4 Gumbel draws, one per destination in the order of
  ``DESTINATIONS``; the destination is the Gumbel-max of its odds, with the
  true severity G and the abnormal tests among the ordered ones;
- stream 8 (patience): 1 normal, with the true level and the age band;
- stream 9 (wait for a bed): 1 normal, whether the patient is admitted or not.

The engine of task 5.3 turns its ``Outcome`` into ``engine.clinical.OutcomeDraws``.

The module does not import the engine nor SimPy: ``ArrivalRecord`` is only a
type hint, and the sampler reads nothing but ``arrival.time``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import ArrayLike, NDArray

from edsim.profiles.config import N_DESTINATIONS, REASON_KEYS, ClinicalProfiles, _check_median_p90
from edsim.profiles.context import ArrivalContext, all_contexts, arrival_context
from edsim.profiles.durations import PatientDurations, draw_durations_standard, durations_from_draws
from edsim.profiles.mixing import band_weights, gumbel_max, reason_weight_table
from edsim.profiles.outcome import (
    bed_wait_from_draw,
    destination_from_draws,
    patience_from_draw,
    require_outcome,
)
from edsim.profiles.population import Person, draw_person_standard, person_from_draws
from edsim.profiles.severity import severity_from_draw, triage_from_draws, triage_quality
from edsim.profiles.workup import Workup, draw_workup_standard, older_bands, workup_from_draws

if TYPE_CHECKING:
    from edsim.arrivals.thinning import ArrivalRecord

N_STREAMS = 2
"""Streams of each sampler: population (5) and reason (6), severity (7) and error (1),
or tests (3) and durations (2)."""

N_REASON_DRAWS = len(REASON_KEYS)
"""Standard Gumbel draws of stream 6 per patient: one per reason."""


@dataclass(frozen=True, slots=True)
class PersonAndReason:
    """What streams 5 and 6 give for one arrival.

    Attributes:
        context: Shift band, day type and season of the arrival.
        person: Band, age, sex and arrival mode.
        reason: Key of the reason for consultation, one of ``REASON_KEYS``.
    """

    context: ArrivalContext
    person: Person
    reason: str


def _check_streams(
    streams: Sequence[np.random.SeedSequence], n: int = N_STREAMS
) -> list[np.random.SeedSequence]:
    streams = list(streams)
    if len(streams) != n:
        raise ValueError(f"streams must have {n} SeedSequence, got {len(streams)}")
    for i, stream in enumerate(streams):
        if not isinstance(stream, np.random.SeedSequence):
            raise ValueError(f"streams[{i}] must be a SeedSequence, got {stream!r}")
    return streams


def draw_reason_standard(rng: np.random.Generator) -> NDArray[np.float64]:
    """The 17 standard Gumbel draws of one patient from stream 6."""
    return rng.gumbel(size=N_REASON_DRAWS)


class PersonReasonSampler:
    """Person and reason of each patient on arrival.

    Call it once per arrival, in arrival order. Each stream gets its own
    ``numpy.random.Generator``, and each call consumes 7 numbers from stream
    5 and 17 from stream 6 (see the module docstring).

    Args:
        profiles: The clinical profiles.
        start_date: Date of minute 0 of the arrivals, the arrival profile's
            ``start_date``.
        streams: Exactly two ``numpy.random.SeedSequence``: population and
            reason. The engine will pass children 5 and 6 of
            ``child_streams(seed, 8)``. The objects are not modified, so the
            same ones give the same draws.

    Raises:
        ValueError: If ``streams`` is not two ``SeedSequence``.
    """

    def __init__(
        self,
        profiles: ClinicalProfiles,
        start_date: date,
        streams: Sequence[np.random.SeedSequence],
    ) -> None:
        streams = _check_streams(streams)
        self._population_rng, self._reason_rng = (np.random.default_rng(s) for s in streams)
        self._profiles = profiles
        self._start_date = start_date
        # Weights of every reason for every band and context, and of every band
        # for every context, computed once.
        self._weights = reason_weight_table(profiles)
        self._band_weights = {c: band_weights(profiles.population, c) for c in all_contexts()}

    def __call__(self, arrival: ArrivalRecord) -> PersonAndReason:
        """Person and reason of the patient of ``arrival``, the next one in arrival order."""
        ctx = arrival_context(arrival.time, self._start_date, self._profiles.shift_band_starts)
        # Fixed consumption per patient: draw everything before transforming it.
        person_draws = draw_person_standard(self._population_rng)
        reason_draws = draw_reason_standard(self._reason_rng)

        person = person_from_draws(
            self._profiles.population, ctx, person_draws, self._band_weights[ctx]
        )
        weights = self._weights[:, person.band, ctx.shift_band, ctx.day_type, ctx.season]
        reason = REASON_KEYS[gumbel_max(weights, reason_draws)]
        return PersonAndReason(context=ctx, person=person, reason=reason)


def draw_severity_standard(rng: np.random.Generator) -> float:
    """One standard normal draw: ``z`` of stream 7 or ``z_e`` of stream 1."""
    return float(rng.standard_normal())


@dataclass(frozen=True, slots=True)
class SeverityAndTriage:
    """What streams 7 and 1 give for one patient, for the log and the ground truth.

    Only ``level`` is known to the hospital; the rest is ground truth.

    Attributes:
        z: The standard normal draw of the severity (stream 7).
        severity: The latent severity G.
        level: The assigned triage level, 1 to 5: ``G + ε`` cut by the thresholds.
        true_level: The true level: ``G`` cut by the same thresholds.
        quality: ``"correcto"``, ``"infratriaje"`` or ``"sobretriaje"``.
        jump: ``|level - true_level|``.
    """

    z: float
    severity: float
    level: int
    true_level: int
    quality: str
    jump: int


class SeverityTriageSampler:
    """Latent severity and triage of each patient, given its person and reason.

    Call it once per patient, in arrival order, with the ``PersonAndReason``
    of ``PersonReasonSampler``. Each call consumes one standard normal from
    stream 7 and one from stream 1, whatever comes out. The thresholds, the
    noise and the bias are the ones written in ``profiles.triage``: they are
    never recomputed, so that a scenario with more severity gives more
    urgent levels.

    Args:
        profiles: The clinical profiles.
        streams: Exactly two ``numpy.random.SeedSequence``: severity and triage
            error. The engine will pass children 7 and 1 of
            ``child_streams(seed, 8)``, in that order. The objects are not
            modified.

    Raises:
        ValueError: If ``streams`` is not two ``SeedSequence``.
    """

    def __init__(
        self, profiles: ClinicalProfiles, streams: Sequence[np.random.SeedSequence]
    ) -> None:
        streams = _check_streams(streams)
        self._severity_rng, self._noise_rng = (np.random.default_rng(s) for s in streams)
        self._severities = {r.key: r.severity for r in profiles.reasons}
        self._triage = profiles.triage

    def __call__(self, person_and_reason: PersonAndReason) -> SeverityAndTriage:
        """Severity and triage of the next patient, with its person and reason."""
        # Fixed consumption per patient: draw everything before transforming it.
        z = draw_severity_standard(self._severity_rng)
        z_noise = draw_severity_standard(self._noise_rng)

        severity = self._severities[person_and_reason.reason]
        g = severity_from_draw(severity, person_and_reason.person.band, z)
        t = self._triage
        level, true_level = triage_from_draws(g, z_noise, t.thresholds, t.noise, t.bias)
        quality, jump = triage_quality(level, true_level)
        return SeverityAndTriage(
            z=z, severity=g, level=level, true_level=true_level, quality=quality, jump=jump
        )


@dataclass(frozen=True, slots=True)
class WorkupAndDurations:
    """What streams 3 and 2 give for one patient.

    Attributes:
        workup: Whether each type of test is ordered, its result and its base
            turnaround, with the 12 standard draws; ``workup.has_round`` says
            whether there is a round.
        durations: Triage, assessment and reassessment, with the 3 standard
            draws.
    """

    workup: Workup
    durations: PatientDurations


class WorkupDurationSampler:
    """Tests and durations of each patient, given its person, reason and severity.

    Call it once per patient, in arrival order, with the ``PersonAndReason``
    of ``PersonReasonSampler`` and the ``SeverityAndTriage`` of
    ``SeverityTriageSampler``. Each call consumes 12 numbers from stream 3 and
    3 normals from stream 2, whatever comes out: the draws are all made before
    they are transformed. The tests use the true severity G and the
    durations the true level, not the assigned one.

    Args:
        profiles: The clinical profiles.
        streams: Exactly two ``numpy.random.SeedSequence``: tests and
            durations. The engine will pass children 3 and 2 of
            ``child_streams(seed, 8)``, in that order. The objects are not
            modified.

    Raises:
        ValueError: If ``streams`` is not two ``SeedSequence``.
    """

    def __init__(
        self, profiles: ClinicalProfiles, streams: Sequence[np.random.SeedSequence]
    ) -> None:
        streams = _check_streams(streams)
        self._test_rng, self._duration_rng = (np.random.default_rng(s) for s in streams)
        self._profiles = profiles
        self._tests = profiles.diagnostic_tests
        self._reasons = {r.key: r for r in profiles.reasons}
        self._older = older_bands(profiles.population)

    def __call__(
        self, person_and_reason: PersonAndReason, severity_and_triage: SeverityAndTriage
    ) -> WorkupAndDurations:
        """Tests and durations of the next patient."""
        # Fixed consumption per patient: draw everything before transforming it.
        test_draws = draw_workup_standard(self._test_rng)
        duration_draws = draw_durations_standard(self._duration_rng)

        reason = self._reasons[person_and_reason.reason]
        workup = workup_from_draws(
            self._tests,
            reason.test_pct,
            severity_and_triage.severity,
            self._older[person_and_reason.person.band],
            test_draws,
        )
        durations = durations_from_draws(
            self._profiles, reason, severity_and_triage.true_level, duration_draws
        )
        return WorkupAndDurations(workup=workup, durations=durations)


N_OUTCOME_STREAMS = 3
"""Streams of ``OutcomeSampler``: destination (4), patience (8) and wait for a bed (9)."""


def draw_outcome_standard(
    destination_rng: np.random.Generator,
    patience_rng: np.random.Generator,
    bed_rng: np.random.Generator,
) -> tuple[NDArray[np.float64], float, float]:
    """The standard draws of one patient: 4 Gumbel (stream 4), 1 normal (8) and 1 normal (9)."""
    gumbels = destination_rng.gumbel(size=N_DESTINATIONS)
    return gumbels, float(patience_rng.standard_normal()), float(bed_rng.standard_normal())


def abnormal_count(workup: Workup) -> int:
    """Number of abnormal tests among the ordered ones, 0 to 4.

    The result of a type that is not ordered is drawn too (decision 34), but
    nobody sees it: it does not count.
    """
    return sum(o and a for o, a in zip(workup.ordered, workup.abnormal, strict=True))


@dataclass(frozen=True, slots=True)
class Outcome:
    """What streams 4, 8 and 9 give for one patient (task 5.2).

    Attributes:
        destination_draws: The 4 standard Gumbel draws, in the order of
            ``DESTINATIONS``.
        destination: The destination, one of ``DESTINATIONS``; drawn always,
            also for a patient who will leave without being seen.
        patience_z: The standard normal draw of the patience.
        patience: Minutes from the arrival the patient waits before leaving.
        bed_z: The standard normal draw of the wait for a bed.
        bed_base: The wait for a bed with factor 1, in minutes; drawn always,
            used only if the patient is admitted.
    """

    destination_draws: tuple[float, ...]
    destination: str
    patience_z: float
    patience: float
    bed_z: float
    bed_base: float


def outcome_from_draws(
    profiles: ClinicalProfiles,
    bed_wait: tuple[float, float],
    person_and_reason: PersonAndReason,
    severity_and_triage: SeverityAndTriage,
    workup: Workup,
    draws: tuple[ArrayLike, float, float],
) -> Outcome:
    """The outcome that the standard draws give to a patient.

    The destination uses the true severity G, the band (older or not), the
    reason and the abnormal tests among the ordered ones; the patience, the
    true level and the band. Neither uses what the nurse sees.

    Args:
        profiles: The profiles, with the milestone 5 block.
        bed_wait: ``[mediana, p90]`` of the wait for a bed (``camas.espera``).
        person_and_reason: The person and the reason of the patient.
        severity_and_triage: Its severity and triage.
        workup: Its tests.
        draws: The 4 Gumbel draws and the two normals of ``draw_outcome_standard``.
    """
    outcome = require_outcome(profiles)
    gumbels, patience_z, bed_z = draws
    band = person_and_reason.person.band
    destination = destination_from_draws(
        outcome,
        profiles.reason(person_and_reason.reason).admission_pct,
        older_bands(profiles.population)[band],
        severity_and_triage.severity,
        abnormal_count(workup),
        gumbels,
    )
    return Outcome(
        destination_draws=tuple(float(g) for g in gumbels),
        destination=destination,
        patience_z=float(patience_z),
        patience=patience_from_draw(
            outcome.abandonment, severity_and_triage.true_level, band, patience_z
        ),
        bed_z=float(bed_z),
        bed_base=bed_wait_from_draw(bed_wait, bed_z),
    )


class OutcomeSampler:
    """Patience, destination and base wait for a bed of each patient, on arrival.

    Call it once per patient, in arrival order, with its ``PersonAndReason``,
    ``SeverityAndTriage`` and ``Workup``. Each call consumes 4 Gumbel draws
    from stream 4, 1 normal from stream 8 and 1 from stream 9, whatever comes
    out: the draws are all made before they are transformed.

    Args:
        profiles: The profiles, with the milestone 5 block.
        bed_wait: ``[mediana, p90]`` of the wait for a bed, from ``[camas]`` of
            the center, as two numbers: the sampler does not read the center.
        streams: Exactly three ``numpy.random.SeedSequence``: destination,
            patience and wait for a bed. The engine will pass children 4, 8
            and 9 of ``child_streams(seed, 10)``, in that order. The objects
            are not modified.

    Raises:
        ValueError: If the profiles have no milestone 5 block, ``bed_wait`` is
            not a valid ``[mediana, p90]`` or ``streams`` is not three
            ``SeedSequence``.
    """

    def __init__(
        self,
        profiles: ClinicalProfiles,
        bed_wait: tuple[float, float],
        streams: Sequence[np.random.SeedSequence],
    ) -> None:
        require_outcome(profiles)
        self._bed_wait = _check_median_p90("camas.espera", bed_wait)
        streams = _check_streams(streams, N_OUTCOME_STREAMS)
        self._destination_rng, self._patience_rng, self._bed_rng = (
            np.random.default_rng(s) for s in streams
        )
        self._profiles = profiles

    def __call__(
        self,
        person_and_reason: PersonAndReason,
        severity_and_triage: SeverityAndTriage,
        workup: Workup,
    ) -> Outcome:
        """Outcome of the next patient."""
        # Fixed consumption per patient: draw everything before transforming it.
        draws = draw_outcome_standard(self._destination_rng, self._patience_rng, self._bed_rng)
        return outcome_from_draws(
            self._profiles, self._bed_wait, person_and_reason, severity_and_triage, workup, draws
        )
