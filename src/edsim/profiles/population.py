"""The person who arrives: age band, age, sex and arrival mode.

Stream 5 gives seven standard draws per patient, in a fixed order whatever
comes out (ADR candidate 43):

1. four standard Gumbel draws, one per age band: the band is the Gumbel-max
   of the band weights in the context (``mixing.band_weights``);
2. one uniform for the age, integer and uniform within the band:
   ``low + floor(u * (high - low + 1))``, so that both ends are included;
3. one uniform for the sex: a woman if ``u < mujeres[band] / 100``;
4. one uniform for the arrival mode: ambulance if ``u < ambulancia[band] / 100``.

The draws are standard and the parameters transform them, so a patient keeps
the same draws when a parameter changes.
"""

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

from edsim.arrivals.profile import ArrivalProfile
from edsim.profiles.config import MAX_AGE, N_BANDS, ClinicalProfiles, Population
from edsim.profiles.context import ArrivalContext
from edsim.profiles.mixing import band_context_mass, band_weights, gumbel_max

N_PERSON_DRAWS = N_BANDS + 3
"""Standard draws of stream 5 per patient: 4 Gumbel and 3 uniforms."""

OLDER_AGE = 65
"""Lowest age of the «older» patients of the calibration targets."""


@dataclass(frozen=True, slots=True)
class Person:
    """The person of one arrival. Values are Python ``int`` and ``bool``.

    Attributes:
        band: Index of the age band, 0 to 3.
        age: Age in years.
        female: Whether the patient is a woman.
        ambulance: Whether the patient arrives by ambulance.
    """

    band: int
    age: int
    female: bool
    ambulance: bool


def age_range(population: Population, band: int) -> tuple[int, int]:
    """Lowest and highest age of a band, both included, such as ``(80, 99)``."""
    starts = population.band_starts
    high = starts[band + 1] - 1 if band + 1 < len(starts) else MAX_AGE
    return starts[band], high


def draw_person_standard(rng: np.random.Generator) -> NDArray[np.float64]:
    """The seven standard draws of one patient from stream 5: 4 Gumbel, 3 uniforms."""
    return np.concatenate([rng.gumbel(size=N_BANDS), rng.random(3)])


def person_from_draws(population: Population, context: ArrivalContext, draws: ArrayLike) -> Person:
    """The person that the seven standard draws give in a context.

    Raises:
        ValueError: If ``draws`` does not have seven values.
    """
    draws = np.asarray(draws, dtype=float)
    if draws.shape != (N_PERSON_DRAWS,):
        raise ValueError(f"draws must have {N_PERSON_DRAWS} values, got shape {draws.shape}")
    band = gumbel_max(band_weights(population, context), draws[:N_BANDS])
    u_age, u_sex, u_mode = draws[N_BANDS:]
    low, high = age_range(population, band)
    return Person(
        band=band,
        age=low + int(u_age * (high - low + 1)),
        female=bool(u_sex < population.female_pct[band] / 100),
        ambulance=bool(u_mode < population.ambulance_pct[band] / 100),
    )


def global_band_shares(
    profiles: ClinicalProfiles, arrival_profile: ArrivalProfile
) -> NDArray[np.float64]:
    """Share of each age band over a year of the arrival profile, adding up to 1."""
    return band_context_mass(profiles, arrival_profile).sum(axis=(1, 2, 3))


def share_65_plus(profiles: ClinicalProfiles, arrival_profile: ArrivalProfile) -> float:
    """Share of patients aged 65 or more over a year, to compare with its target range.

    Raises:
        ValueError: If 65 is not the lowest age of a band.
    """
    starts = profiles.population.band_starts
    if OLDER_AGE not in starts:
        raise ValueError(f"no age band starts at {OLDER_AGE}: bandas_edad is {list(starts)}")
    shares = global_band_shares(profiles, arrival_profile)
    return float(shares[starts.index(OLDER_AGE) :].sum())
