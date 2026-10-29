"""Deliberately wrong versions of the arrivals, for power tests and teaching.

A validation is only worth something if it fails with a wrong generator. The
functions here turn correct records into the records a known bug would give,
without changing the generator, so that the bug can be studied with many
seeds while the real code stays correct.

**C′, the midnight bug** (found while testing task 2.2). When a candidate
falls past midnight, the wrong generator starts the next day at that
candidate's time instead of at 00:00. The overshoot past midnight is the
remainder of an exponential gap of mean ``1 / bound`` of the day before; by
the memorylessness of the exponential, it is itself exponential with that
mean and independent of the arrivals. So deleting the arrivals of
``[00:00, 00:00 + E)`` of each day of a correct run, with ``E`` exponential of
mean ``1 / bound`` of the previous day, gives the same distribution as the
bug. The expected loss is about ``lambda(00:00) / bound`` per day, some 0.44
arrivals with the base profile: invisible in a year's total, visible only
around midnight.
"""

import dataclasses
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from edsim.arrivals.rate import MINUTES_PER_DAY
from edsim.arrivals.thinning import ArrivalRecord, DayRecord


def _check_consecutive(days: Sequence[DayRecord]) -> None:
    if not days or [d.day for d in days] != list(range(len(days))):
        raise ValueError("days must be the day records of one run, consecutive from day 0")


def midnight_lags(
    days: Sequence[DayRecord], seed: int | np.random.SeedSequence
) -> NDArray[np.float64]:
    """Lag after each midnight that the C′ bug leaves without arrivals.

    Day 0 starts at 00:00 also with the bug, so its lag is 0. From day 1 on,
    the lag of day ``d`` is exponential with mean ``1 / days[d - 1].bound``,
    drawn in order of the days from the fault's own stream.

    Args:
        days: Day records of one run, consecutive from day 0, for the bounds.
        seed: Seed of the fault: an integer or a ``numpy.random.SeedSequence``.
            It must not be the seed of the run; use, for instance, one child
            of ``child_streams`` for the run and another for the fault.

    Returns:
        The lag of each day, in minutes.

    Raises:
        ValueError: If ``days`` is empty or not consecutive from day 0.
    """
    _check_consecutive(days)
    rng = np.random.default_rng(seed)
    bounds = np.array([d.bound for d in days[:-1]], dtype=float)
    # numpy's exponential takes the scale (mean = 1 / rate), not the rate.
    return np.concatenate([[0.0], rng.exponential(1 / bounds)])


def midnight_restart_fault(
    arrivals: Sequence[ArrivalRecord],
    days: Sequence[DayRecord],
    seed: int | np.random.SeedSequence,
) -> tuple[tuple[ArrivalRecord, ...], tuple[DayRecord, ...]]:
    """The records of a correct run as the C′ midnight bug would give them.

    Deletes the arrivals of ``[00:00, 00:00 + lag)`` of each day, with the
    lags of ``midnight_lags``, and renumbers the rest from 0, as the faulty
    generator would. Each ``DayRecord`` keeps its fields except ``accepted``,
    which counts the arrivals left: tests a and d use it. ``candidates`` stays
    as in the correct run, because the records do not say which rejected
    candidates fell in the deleted span.

    Args:
        arrivals: Arrivals of one correct run.
        days: Day records of the same run, consecutive from day 0.
        seed: Seed of the fault, as in ``midnight_lags``.

    Returns:
        The arrivals and the day records with the bug. The inputs are not
        changed.

    Raises:
        ValueError: If ``days`` is not consecutive from day 0, or an arrival
            falls outside its days.
    """
    lags = midnight_lags(days, seed)
    times = np.array([a.time for a in arrivals], dtype=float)
    day_of = np.floor(times / MINUTES_PER_DAY).astype(np.int64)
    if day_of.size and (day_of.min() < 0 or day_of.max() >= len(days)):
        raise ValueError("every arrival must fall on one of the days")

    keep = times - day_of * MINUTES_PER_DAY >= lags[day_of]
    kept_times = times[keep]
    accepted = np.bincount(day_of[keep], minlength=len(days))

    faulty = tuple(ArrivalRecord(arrival_id=i, time=float(t)) for i, t in enumerate(kept_times))
    faulty_days = tuple(
        dataclasses.replace(d, accepted=int(n)) for d, n in zip(days, accepted, strict=True)
    )
    return faulty, faulty_days
