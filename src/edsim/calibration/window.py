"""The window of the calibration: when each replication starts (task 4.6c).

The targets of the SAS are yearly means, so the replications of a candidate
must represent the year, not one stretch of it. With the **annual** window
there are 12 replications, one per month: replication m (m = 0…11) starts at
00:00 of the first Monday of month m + 1 of the year of ``fecha_inicio`` and
uses child m of the seed. Starting on a Monday gives every replication the same
weekdays (in the window ``[2, 14)``, Wednesday to Sunday twice and Monday and
Tuesday once). The arrival profile keeps everything but its ``start_date``, so
each replication has the monthly factor, the weekdays and the clinical context
(month and season) of its month. ``with_start_date`` changes only the date:
``dataclasses.replace`` would normalize the factors again and move them in the
last bit, and January would no longer be the replication 0 of task 4.6b bit
for bit.

The **start** window is the one of task 4.6b: every replication starts on
``fecha_inicio``. It stays to reproduce the old calibration log.
"""

from __future__ import annotations

import copy
from datetime import date, datetime, timedelta

from edsim.arrivals.profile import ArrivalProfile

ANNUAL = "anual"
"""One replication per month, from the first Monday of each month."""

START = "inicio"
"""Every replication starts on ``fecha_inicio`` (task 4.6b)."""

WINDOWS = (ANNUAL, START)

ANNUAL_REPLICAS = 12
"""Replications of the annual window: one per month."""

START_REPLICAS = 10
"""Default replications of the start window, as in task 4.6b."""

MONTHS = 12
DAYS_PER_WEEK = 7


def first_mondays(year: int) -> tuple[date, ...]:
    """The first Monday of each month of ``year``, January to December."""
    out = []
    for month in range(1, MONTHS + 1):
        first = date(year, month, 1)
        out.append(first + timedelta(days=(DAYS_PER_WEEK - first.weekday()) % DAYS_PER_WEEK))
    return tuple(out)


def with_start_date(arrival_profile: ArrivalProfile, start_date: date) -> ArrivalProfile:
    """``arrival_profile`` with another ``start_date`` and its factors exactly as they are.

    ``dataclasses.replace`` runs the normalization of the profile again, which
    leaves the factors equal only up to the last bit; this copy keeps them bit
    for bit, so a replication that starts on ``fecha_inicio`` is the same as
    one without a start date.

    Raises:
        ValueError: If ``start_date`` is not a date without time.
    """
    # datetime is a subclass of date, as in ArrivalProfile.
    if not isinstance(start_date, date) or isinstance(start_date, datetime):
        raise ValueError(f"start_date must be a date without time, got {start_date!r}")
    out = copy.copy(arrival_profile)
    # The profile is frozen; its fields are set with object.__setattr__, as in its
    # own __post_init__. Only the date changes, so it stays valid and normalized.
    object.__setattr__(out, "start_date", start_date)
    return out


def _check_window(window: str) -> str:
    if window not in WINDOWS:
        raise ValueError(f"window must be one of {WINDOWS}, got {window!r}")
    return window


def window_replicas(window: str, replicas: int | None) -> int:
    """The replications of ``window``; ``None`` takes its default.

    Raises:
        ValueError: If the window is unknown, or ``replicas`` is not 12 with
            the annual window.
    """
    if _check_window(window) == ANNUAL:
        if replicas is not None and replicas != ANNUAL_REPLICAS:
            raise ValueError(
                f"the annual window has {ANNUAL_REPLICAS} replicas, one per month: got"
                f" {replicas} (the start window takes any number)"
            )
        return ANNUAL_REPLICAS
    return START_REPLICAS if replicas is None else replicas


def window_start_dates(window: str, arrival_profile: ArrivalProfile) -> tuple[date, ...] | None:
    """The start date of each replication of ``window``; ``None`` with the start
    window, whose replications all start on the profile's ``start_date``.

    Raises:
        ValueError: If the window is unknown.
    """
    if _check_window(window) == ANNUAL:
        return first_mondays(arrival_profile.start_date.year)
    return None


def replica_start_dates(
    window: str, arrival_profile: ArrivalProfile, replicas: int
) -> tuple[date, ...]:
    """The date on which each of the ``replicas`` replications of ``window`` starts,
    for the reports: the start window repeats the profile's ``start_date``.

    Raises:
        ValueError: If the window is unknown or the annual window does not have 12
            replications.
    """
    replicas = window_replicas(window, replicas)
    dates = window_start_dates(window, arrival_profile)
    return dates if dates is not None else (arrival_profile.start_date,) * replicas
