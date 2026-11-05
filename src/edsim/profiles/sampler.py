"""Person and reason of each arrival, from streams 5 and 6.

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

if TYPE_CHECKING:
    from edsim.arrivals.thinning import ArrivalRecord

N_STREAMS = 2
"""Streams of the sampler: population (5) and reason (6)."""

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
        streams = list(streams)
        if len(streams) != N_STREAMS:
            raise ValueError(f"streams must have {N_STREAMS} SeedSequence, got {len(streams)}")
        for i, stream in enumerate(streams):
            if not isinstance(stream, np.random.SeedSequence):
                raise ValueError(f"streams[{i}] must be a SeedSequence, got {stream!r}")
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
