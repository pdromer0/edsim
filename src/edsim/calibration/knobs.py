"""The two knobs of milestone 5: the wait for a bed and the patience (task 5.6, H5-9).

The knobs of milestone 4 are staffs, searched through the rule of the equivalent
staff (``calibration.staffing``). These two are one number each, on a grid:

- ``espera_cama``: the median m of the wait for a bed (``camas.espera``), with the
  p90 at ``BED_P90_RATIO`` times it (the ratio, by criterion) and the factors of
  shift and season as they are. It fits ``estancia_ingresados``.
- ``paciencia``: a common factor k on the medians and the p90 of the patience of the
  five true levels (``abandono.paciencia``). Moving both by k moves the lognormal
  and keeps its shape: σ = ln(p90 / median) / z₀.₉ does not change. The age factors
  stay. It fits ``abandono``.

The factor k is relative to the profiles it is applied to: with the starting values
of ``perfiles.toml``, k = 1 is them. The values are rounded to 3 decimals, so the
pairs written in a TOML file load back bit for bit; with a grid of 3 decimals and
integer starting values the ratio of each pair stays exact in decimal.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass

from edsim.engine.center import CenterConfig
from edsim.profiles.config import ClinicalProfiles

BED_WAIT = "espera_cama"
"""The knob of the median of the wait for a bed, by its name in the CLI."""

PATIENCE = "paciencia"
"""The knob of the factor of the patience, by its name in the CLI."""

VALUE_KNOBS = (BED_WAIT, PATIENCE)
"""The knobs of one number, in the order they are fitted: the bed first, with the
patience of start, then the patience (docs/specs/hito-5.md, piece 5)."""

BED_P90_RATIO = 3
"""p90 / median of the wait for a bed, by criterion (docs/specs/hito-5.md)."""

BED_GRID: tuple[float, ...] = tuple(float(m) for m in range(120, 361, 15))
"""Medians of the wait for a bed of the sensitivity, in minutes: 120 to 360 every 15."""

PATIENCE_GRID: tuple[float, ...] = tuple(round(2 ** (i / 4), 3) for i in range(13))
"""Factors of the patience of the sensitivity: a geometric grid from 1 to 8, four
steps per doubling (1, 1.189, 1.414, …, 8)."""

DEFAULT_GRIDS = {BED_WAIT: BED_GRID, PATIENCE: PATIENCE_GRID}

MAX_VALUES = {BED_WAIT: 7 * 1440.0, PATIENCE: 100.0}
"""Largest value of each knob: a week of median wait for a bed, a factor of 100."""

DECIMALS = 3
"""Decimals of the values written: the patience pairs ``round(k · value, 3)``."""


@dataclass(frozen=True, slots=True)
class KnobValue:
    """One value of a knob of one number, as a candidate of the sensitivity.

    Attributes:
        value: The median of the wait for a bed, in minutes, or the factor of
            the patience.
    """

    value: float


def check_knob_value(knob: str, value: object) -> float:
    """``value`` as a valid value of ``knob``: finite, positive and at most its maximum.

    Raises:
        ValueError: If the knob is not one of ``VALUE_KNOBS`` or the value is not valid.
    """
    if knob not in VALUE_KNOBS:
        raise ValueError(f"knob must be one of {VALUE_KNOBS}, got {knob!r}")
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"a value of {knob} must be a finite number, got {value!r}")
    if not 0 < value <= MAX_VALUES[knob]:
        raise ValueError(f"a value of {knob} must be in (0, {MAX_VALUES[knob]:g}], got {value!r}")
    return float(value)


def bed_wait_center(center: CenterConfig, median: float) -> CenterConfig:
    """``center`` with the wait for a bed ``[median, BED_P90_RATIO · median]``; the factors
    of shift and season, and everything else, as they are.

    Raises:
        ValueError: If the center has no ``[camas]`` or the median is not valid.
    """
    median = check_knob_value(BED_WAIT, median)
    if not center.has_beds:
        raise ValueError(f"the knob {BED_WAIT} needs a center with [camas] (milestone 5)")
    return dataclasses.replace(center, bed_wait=(median, BED_P90_RATIO * median))


def scaled_patience(profiles: ClinicalProfiles, factor: float) -> ClinicalProfiles:
    """``profiles`` with the median and the p90 of the patience of every true level times
    ``factor``, rounded to ``DECIMALS``; σ, the age factors and everything else, as they
    are.

    Raises:
        ValueError: If the profiles have no milestone 5 block or the factor is not valid.
    """
    factor = check_knob_value(PATIENCE, factor)
    outcome = profiles.outcome
    if outcome is None:
        raise ValueError(f"the knob {PATIENCE} needs profiles with [abandono] (milestone 5)")
    patience = tuple(
        (round(factor * median, DECIMALS), round(factor * p90, DECIMALS))
        for median, p90 in outcome.abandonment.patience
    )
    abandonment = dataclasses.replace(outcome.abandonment, patience=patience)
    return dataclasses.replace(
        profiles, outcome=dataclasses.replace(outcome, abandonment=abandonment)
    )


def knob_inputs(
    center: CenterConfig, profiles: ClinicalProfiles, knob: str, value: float
) -> tuple[CenterConfig, ClinicalProfiles]:
    """The center and the profiles of one value of ``knob``: only its knob changes."""
    if knob == BED_WAIT:
        return bed_wait_center(center, value), profiles
    if knob == PATIENCE:
        return center, scaled_patience(profiles, value)
    raise ValueError(f"knob must be one of {VALUE_KNOBS}, got {knob!r}")
