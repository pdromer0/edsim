"""The rule of the equivalent staff: one number u per knob (docs/specs/hito-4.md).

A knob has a staff per shift (morning, afternoon, night). Searching the three
numbers of each knob freely would be a search in three dimensions, hard to
explain and easy to overfit. The rule ties them together with one number u,
a target occupancy of the shift:

    staff of the shift = ⌈load of the shift / u⌉

where the load is the mean number of the staff that the demand of the shift
keeps busy, without queues (an offered load in the sense of milestone 3):

- triage nurses: arrivals per hour × (1 − p₁) × mean triage / 60, with p₁ the
  share of assigned level 1, classified at the door without a nurse;
- doctors: arrivals per hour × load of the doctor per patient / 60, the
  assessment plus the reassessments that happen (``physician_load``).

The arrivals per hour of a shift are those of the mean day of the profile:
``base_diaria`` × (share of the day in the hours of the shift) / hours. The
weekday and month factors are left out: the staff is the same every day.

Each staff of the rule covers an interval of u, so a sweep over a grid of u
gives a short list of different staffs (``rule_staffings``): those are the
candidates of the calibration, and nothing outside the rule is searched.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from edsim.arrivals.profile import ArrivalProfile
from edsim.engine.center import N_SHIFTS
from edsim.profiles.config import ClinicalProfiles
from edsim.profiles.durations import duration_params, lognormal_mean, physician_load
from edsim.profiles.severity import assigned_shares, severity_mixture

HOURS_PER_DAY = 24
MINUTES_PER_HOUR = 60

NURSES = "enfermeria_triaje"
"""The knob of the triage nurses, by its key in ``[recursos]``."""

DOCTORS = "medicos"
"""The knob of the doctors, by its key in ``[recursos]``."""

KNOBS = (NURSES, DOCTORS)
"""The two knobs, in the order they are fitted (ADR candidate 41, revised)."""

U_MIN = 0.55
"""Lowest u of the sweep: well below any realistic occupancy."""

U_MAX = 0.99
"""Highest u of the sweep: just below saturation on the mean day."""

U_STEP = 0.0025
"""Step of the grid of u."""


def shift_hours(shift_starts: Sequence[int]) -> tuple[tuple[int, ...], ...]:
    """The clock hours of each shift; the last one runs past midnight into the first."""
    starts = tuple(shift_starts)
    out = []
    for i, start in enumerate(starts):
        end = starts[(i + 1) % len(starts)]
        length = (end - start) % HOURS_PER_DAY
        out.append(tuple((start + h) % HOURS_PER_DAY for h in range(length)))
    return tuple(out)


def shift_arrival_rates(
    arrival_profile: ArrivalProfile, shift_starts: Sequence[int]
) -> tuple[float, ...]:
    """Arrivals per hour of each shift on the mean day of the profile.

    ``hour_factors`` have mean 1 over the day, so the share of the day in an
    hour is its factor over 24: the rate of a shift is
    ``daily_base × Σ factor / 24 / hours`` (with ``config/``, 17.36, 16.5 and
    6.3 arrivals per hour).
    """
    factors = arrival_profile.hour_factors
    return tuple(
        arrival_profile.daily_base * sum(factors[h] for h in hours) / HOURS_PER_DAY / len(hours)
        for hours in shift_hours(shift_starts)
    )


def door_share(profiles: ClinicalProfiles, arrival_profile: ArrivalProfile) -> float:
    """p₁: exact share of assigned level 1 over a year, the patients without a nurse."""
    triage = profiles.triage
    shares = assigned_shares(
        severity_mixture(profiles, arrival_profile), triage.thresholds, triage.noise, triage.bias
    )
    return float(shares[0])


def mean_triage_time(profiles: ClinicalProfiles) -> float:
    """Mean of the triage lognormal, in minutes: ``median · exp(σ² / 2)``."""
    return lognormal_mean(*duration_params(*profiles.triage.duration))


def nurse_loads(
    profiles: ClinicalProfiles, arrival_profile: ArrivalProfile, shift_starts: Sequence[int]
) -> tuple[float, ...]:
    """Mean triage nurses busy in each shift, without queues."""
    p1 = door_share(profiles, arrival_profile)
    triage = mean_triage_time(profiles)
    return tuple(
        rate * (1 - p1) * triage / MINUTES_PER_HOUR
        for rate in shift_arrival_rates(arrival_profile, shift_starts)
    )


def doctor_loads(
    profiles: ClinicalProfiles, arrival_profile: ArrivalProfile, shift_starts: Sequence[int]
) -> tuple[float, ...]:
    """Mean doctors busy in each shift, without queues."""
    load = physician_load(profiles, arrival_profile).load
    return tuple(
        rate * load / MINUTES_PER_HOUR
        for rate in shift_arrival_rates(arrival_profile, shift_starts)
    )


def knob_loads(
    knob: str,
    profiles: ClinicalProfiles,
    arrival_profile: ArrivalProfile,
    shift_starts: Sequence[int],
) -> tuple[float, ...]:
    """The loads of ``knob`` (``NURSES`` or ``DOCTORS``)."""
    if knob == NURSES:
        return nurse_loads(profiles, arrival_profile, shift_starts)
    if knob == DOCTORS:
        return doctor_loads(profiles, arrival_profile, shift_starts)
    raise ValueError(f"knob must be one of {KNOBS}, got {knob!r}")


def _check_u(u: object) -> float:
    if isinstance(u, bool) or not isinstance(u, int | float) or not 0 < u <= 1:
        raise ValueError(f"u must be a number in (0, 1], got {u!r}")
    return float(u)


def equivalent_staff(loads: Sequence[float], u: float) -> tuple[int, ...]:
    """The staff of each shift: ``⌈load / u⌉``, at least 1.

    Raises:
        ValueError: If ``u`` is not in (0, 1] or there are not three loads.
    """
    u = _check_u(u)
    if len(loads) != N_SHIFTS:
        raise ValueError(f"need {N_SHIFTS} loads, one per shift, got {len(loads)}")
    return tuple(max(1, math.ceil(load / u)) for load in loads)


@dataclass(frozen=True, slots=True)
class RuleStaffing:
    """One staff of the rule and the interval of u of the grid that gives it.

    Attributes:
        staff: Staff of each shift.
        u_low: Lowest u of the grid that gives it.
        u_high: Highest u of the grid that gives it.
    """

    staff: tuple[int, ...]
    u_low: float
    u_high: float


def u_grid(u_min: float = U_MIN, u_max: float = U_MAX, step: float = U_STEP) -> tuple[float, ...]:
    """The grid ``u_min, u_min + step, …, u_max``, from whole multiples of the step.

    Each point is ``u_min + k · step`` rounded to 10 decimals, so that adding
    the step many times does not accumulate floating-point error.
    """
    u_min, u_max = _check_u(u_min), _check_u(u_max)
    if isinstance(step, bool) or not isinstance(step, int | float) or not step > 0:
        raise ValueError(f"step must be a number > 0, got {step!r}")
    if not u_min <= u_max:
        raise ValueError(f"need u_min <= u_max, got {u_min} and {u_max}")
    n = math.floor((u_max - u_min) / step + 1e-9)
    return tuple(round(u_min + k * step, 10) for k in range(n + 1))


def rule_staffings(
    loads: Sequence[float], u_min: float = U_MIN, u_max: float = U_MAX, step: float = U_STEP
) -> tuple[RuleStaffing, ...]:
    """The different staffs of the rule on the grid of u, from the lowest u.

    A lower u gives more staff, so the list goes from the largest staff to the
    smallest; each comes with the interval of the grid that gives it.
    """
    out: list[RuleStaffing] = []
    for u in u_grid(u_min, u_max, step):
        staff = equivalent_staff(loads, u)
        if out and out[-1].staff == staff:
            out[-1] = RuleStaffing(staff, out[-1].u_low, u)
        else:
            out.append(RuleStaffing(staff, u, u))
    return tuple(out)
