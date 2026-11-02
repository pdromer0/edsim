"""Waits by day and level, and the days out of the Manchester maximum times.

An average over weeks hides the bad days: near saturation the waits grow in a
non-linear way, so a center with a mean occupancy of 70 % can have a few days
in which the low levels wait for hours (finding of task 3.7). The design asks
to look at percentiles and at the share of days out of target, not only at
means (docs/diseno.md, "Métricas").

The day of an episode is the day of its arrival, and only the episodes that
arrive in the stretch and depart count, the same rule as ``window_metrics``
(``completed_in_window``).
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from edsim.arrivals.rate import MINUTES_PER_DAY
from edsim.engine.analysis import MEASURES, EpisodeRecord, completed_in_window
from edsim.engine.center import N_LEVELS

MANCHESTER_MAX_WAIT: tuple[float, ...] = (0.0, 10.0, 60.0, 120.0, 240.0)
"""Maximum time to medical attention by triage level, 1 to 5, in minutes.

Immediate, 10, 60, 120 and 240 minutes: the five categories of the Manchester
Triage System (Manchester Triage Group, *Emergency Triage*, Mackway-Jones et
al.), as in the table of calibration targets of docs/diseno.md ("Manual del
sistema Manchester"). "Immediate" is 0: any wait misses it.
"""

COMPLIANCE_TARGET = 0.90
"""Share of the patients of a level and day that must see a doctor within the
maximum time; a day below it is out of target for that level."""


def _check_days(first_day: object, end_day: object) -> tuple[int, int]:
    for name, value in (("first_day", first_day), ("end_day", end_day)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be an integer >= 0, got {value!r}")
    if not first_day < end_day:
        raise ValueError(f"need first_day < end_day, got {first_day} and {end_day}")
    return first_day, end_day


def _by_day_and_level(
    table: Sequence[EpisodeRecord], measure: str, first_day: int, end_day: int
) -> list[list[list[float]]]:
    """The values of ``measure``, by day of the stretch and level."""
    out: list[list[list[float]]] = [
        [[] for _ in range(N_LEVELS)] for _ in range(first_day, end_day)
    ]
    done = completed_in_window(table, first_day * MINUTES_PER_DAY, end_day * MINUTES_PER_DAY)
    for e in done:
        value = getattr(e, measure)
        if value is None:
            raise ValueError(f"{e.episode_id} departed without a {measure}")
        out[math.floor(e.arrival / MINUTES_PER_DAY) - first_day][e.level - 1].append(value)
    return out


@dataclass(frozen=True)
class DailyWaits:
    """One wait (or the stay) by day and level.

    Attributes:
        measure: A name of ``MEASURES``, such as ``box_wait``.
        days: Day of each row, counted from day 0 of the run.
        n: Episodes of each day and level, shape ``(days, 5)``.
        mean: Mean of each day and level; ``nan`` without episodes.
    """

    measure: str
    days: np.ndarray
    n: np.ndarray
    mean: np.ndarray


def daily_waits(
    table: Sequence[EpisodeRecord], measure: str, first_day: int, end_day: int
) -> DailyWaits:
    """Mean of ``measure`` by day of arrival and level, in days ``[first_day, end_day)``.

    Args:
        table: The episodes of the log, from ``episode_table``.
        measure: A name of ``MEASURES``.
        first_day: First day, such as the warm-up days.
        end_day: Day after the last, such as the horizon in days.

    Raises:
        ValueError: If ``measure`` is unknown or the days are not valid.
    """
    if measure not in MEASURES:
        raise ValueError(f"measure must be one of {MEASURES}, got {measure!r}")
    first_day, end_day = _check_days(first_day, end_day)
    values = _by_day_and_level(table, measure, first_day, end_day)
    n = np.array([[len(v) for v in day] for day in values], dtype=np.int64)
    mean = np.array([[np.mean(v) if v else np.nan for v in day] for day in values], dtype=float)
    return DailyWaits(measure, np.arange(first_day, end_day), n, mean)


@dataclass(frozen=True)
class Compliance:
    """Door to doctor against the Manchester maximum times, by day and level.

    Attributes:
        days: Day of each row, counted from day 0 of the run.
        n: Episodes of each day and level, shape ``(days, 5)``.
        within: Share of them that saw a doctor within the maximum time;
            ``nan`` without episodes.
        out: Whether the day is out of target for the level: ``within`` below
            ``target``. ``False`` without episodes.
        max_wait: The maximum time of each level, in minutes.
        target: The share required.
    """

    days: np.ndarray
    n: np.ndarray
    within: np.ndarray
    out: np.ndarray
    max_wait: tuple[float, ...]
    target: float

    @property
    def days_with_patients(self) -> np.ndarray:
        """Days with some episode of each level, shape ``(5,)``."""
        return (self.n > 0).sum(axis=0)

    @property
    def share_out(self) -> np.ndarray:
        """Share of the days with patients of each level that are out of target;
        ``nan`` for a level without patients in the stretch."""
        with np.errstate(invalid="ignore", divide="ignore"):
            return self.out.sum(axis=0) / self.days_with_patients


def manchester_compliance(
    table: Sequence[EpisodeRecord],
    first_day: int,
    end_day: int,
    *,
    max_wait: Sequence[float] = MANCHESTER_MAX_WAIT,
    target: float = COMPLIANCE_TARGET,
) -> Compliance:
    """Share of patients within the maximum door-to-doctor time, by day and level.

    A patient complies if its ``door_to_doctor`` is at most the maximum of its
    level (exactly at the maximum complies). A day is out of target for a
    level if the share of its patients that comply is below ``target``; a day
    without patients of the level is not counted.

    Args:
        table: The episodes of the log, from ``episode_table``.
        first_day: First day, such as the warm-up days.
        end_day: Day after the last, such as the horizon in days.
        max_wait: Maximum time of each level, 1 to 5.
        target: Share of the patients required, in (0, 1].

    Raises:
        ValueError: If the days, ``max_wait`` or ``target`` are not valid.
    """
    first_day, end_day = _check_days(first_day, end_day)
    max_wait = tuple(float(m) for m in max_wait)
    if len(max_wait) != N_LEVELS or any(not m >= 0 for m in max_wait):
        raise ValueError(f"max_wait must be {N_LEVELS} values >= 0, got {max_wait}")
    if not 0 < target <= 1:
        raise ValueError(f"target must be in (0, 1], got {target!r}")

    values = _by_day_and_level(table, "door_to_doctor", first_day, end_day)
    n = np.array([[len(v) for v in day] for day in values], dtype=np.int64)
    within = np.array(
        [
            [np.mean(np.array(v) <= max_wait[k]) if v else np.nan for k, v in enumerate(day)]
            for day in values
        ],
        dtype=float,
    )
    out = (n > 0) & ~(within >= target)
    return Compliance(np.arange(first_day, end_day), n, within, out, max_wait, float(target))
