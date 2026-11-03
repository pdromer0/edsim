"""Minute-by-minute offered work with finite-sample prehistory."""

import math
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from edsim.arrivals.profile import ArrivalProfile
from edsim.arrivals.rate import MINUTES_PER_DAY
from edsim.checks import check_count
from edsim.engine.center import CenterConfig
from edsim.engine.shifts import shift_at
from edsim.engine.validation import _held_intervals, draws_sample, offered_load_by_pool

_POOLS = ("medicos", "boxes", "enfermeria_triaje")


@dataclass(frozen=True, slots=True)
class OfferedWork:
    """Offered load in regime, not an execution starting empty.

    ``minutes`` includes both endpoints, 0 and ``days * 1440``, relative to
    ``start_date``. ``prior_days`` precede that date and are not in the arrays.
    ``load`` counts busy professionals/boxes without queues, ``capacity`` is
    the scheduled capacity at each instant, and ``utilization`` holds the
    mean load/capacity by morning, afternoon and night, in that order.
    Pool names are ``medicos``, ``boxes`` and ``enfermeria_triaje``.
    """

    start_date: date
    days: int
    prior_days: int
    minutes: NDArray[np.int64]
    load: dict[str, NDArray[np.float64]]
    capacity: dict[str, NDArray[np.int64]]
    utilization: dict[str, tuple[float, ...]]
    window_kind: Literal["offered_in_regime"] = field(default="offered_in_regime", init=False)


def offered_work(
    center: CenterConfig,
    profile: ArrivalProfile,
    days: int = 7,
    *,
    sample_size: int = 50_000,
    sample_seed: int = 73_001,
) -> OfferedWork:
    """Predict offered work without waits or daily random effects, from start_date.

    Sample patients with a fixed seed independent of an execution's seed.
    Reuse the engine validation's held intervals and midpoint convolution.
    Prehistory is ``max(1, ceil(maximum_sample_occupation_age / 1440))`` days,
    calculated with a profile dated earlier, preserving the actual calendar.
    It removes the empty-start truncation exactly for the finite sample. The
    maximum, and therefore the number of prior days, may grow with sample size.

    This is offered load in regime from ``profile.start_date``. A real run
    starts empty at minute 0 and has its own warmup days. With constant or
    daily-periodic arrival rates, its full-day mean equals mean arrival rate
    times sample mean occupation, up to one-minute discretization. This is
    generally only an approximation with weekly/monthly factors: work crosses
    both edges of the window. Box load excludes waits while holding a box.

    Shift utilization integrates load with one-minute trapezoids and divides
    by the shift's constant scheduled capacity, including night across midnight.
    """
    days = check_count("days", days, 1)
    sample_size = check_count("sample_size", sample_size, 1)
    sample_seed = check_count("sample_seed", sample_seed, 0)
    draws = draws_sample(center, sample_size, seed=sample_seed)
    maximum_age = max(
        end
        for draw in draws
        for intervals in _held_intervals(draw).values()
        for _, end in intervals
    )
    prior_days = max(1, math.ceil(maximum_age / MINUTES_PER_DAY))
    previous_profile = replace(profile, start_date=profile.start_date - timedelta(days=prior_days))
    offset = prior_days * MINUTES_PER_DAY
    horizon = days * MINUTES_PER_DAY
    curves = offered_load_by_pool(previous_profile, draws, horizon=offset + horizon)
    minutes = np.arange(horizon + 1, dtype=np.int64)
    shifts = np.fromiter(
        (shift_at(center.shift_starts, int(t)) for t in minutes),
        dtype=np.int64,
        count=minutes.size,
    )
    staff = {
        "medicos": center.doctors,
        "boxes": (center.boxes,) * 3,
        "enfermeria_triaje": center.triage_nurses,
    }
    load = {pool: curves[pool][offset : offset + horizon + 1].copy() for pool in _POOLS}
    capacity = {pool: np.asarray(staff[pool], dtype=np.int64)[shifts] for pool in _POOLS}
    utilization = {}
    for pool in _POOLS:
        per_minute = (load[pool][:-1] + load[pool][1:]) / 2
        utilization[pool] = tuple(
            float(per_minute[shifts[:-1] == shift].mean() / staff[pool][shift])
            for shift in range(3)
        )
    return OfferedWork(profile.start_date, days, prior_days, minutes, load, capacity, utilization)
