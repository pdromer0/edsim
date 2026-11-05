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
The ``ClinicalSampler`` of task 4.5 joins both parts.

The module does not import the engine nor SimPy: ``ArrivalRecord`` is only a
type hint, and the sampler reads nothing but ``arrival.time``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

from edsim.profiles.config import REASON_KEYS, ClinicalProfiles
from edsim.profiles.context import ArrivalContext, arrival_context
from edsim.profiles.mixing import gumbel_max, reason_weight_table
from edsim.profiles.population import Person, draw_person_standard, person_from_draws
from edsim.profiles.severity import severity_from_draw, triage_from_draws, triage_quality

if TYPE_CHECKING:
    from edsim.arrivals.thinning import ArrivalRecord

N_STREAMS = 2
"""Streams of each sampler: population (5) and reason (6), or severity (7) and error (1)."""

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


def _check_streams(streams: Sequence[np.random.SeedSequence]) -> list[np.random.SeedSequence]:
    streams = list(streams)
    if len(streams) != N_STREAMS:
        raise ValueError(f"streams must have {N_STREAMS} SeedSequence, got {len(streams)}")
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
        # Weights of every reason for every band and context, computed once.
        self._weights = reason_weight_table(profiles)

    def __call__(self, arrival: ArrivalRecord) -> PersonAndReason:
        """Person and reason of the patient of ``arrival``, the next one in arrival order."""
        ctx = arrival_context(arrival.time, self._start_date, self._profiles.shift_band_starts)
        # Fixed consumption per patient: draw everything before transforming it.
        person_draws = draw_person_standard(self._population_rng)
        reason_draws = draw_reason_standard(self._reason_rng)

        person = person_from_draws(self._profiles.population, ctx, person_draws)
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
