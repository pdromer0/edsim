"""Waits by day and level, the days out of the Manchester maximum times and the pretriage.

The Manchester compliance is measured with a clock to the doctor, C (from
the classification) by default; the pretriage, from the arrival to the start
of the triage, has its own indicator, without the level 1, classified at the
door (docs/specs/hito-4.md, "Relojes y cumplimiento").

An average over weeks hides the bad days: near saturation the waits grow in a
non-linear way, so a center with a mean occupancy of 70 % can have a few days
in which the low levels wait for hours (finding of task 3.7). The design asks
to look at percentiles and at the share of days out of target, not only at
means (docs/diseno.md, "Métricas").

The day of an episode is the day of its arrival, and only the episodes that
arrive in the stretch and depart count, the same rule as ``window_metrics``
(``completed_in_window``).

**With the abandonment** (version 4, H5-8, task 5.4), each measure follows the
rule of its source:

- the waits and the clocks (their means and quantiles) are those of the
  patients seen by a doctor, the ones that depart;
- the Manchester compliance counts the sure misses: whoever leaves without
  being seen once its clock already reached its maximum misses it, and whoever
  leaves before is censored and does not count (``compliance_cases``). Whoever
  leaves before its triage has no level and is out of every compliance, with
  any clock and also with the true level;
- the pretriage counts the triaged patients, also those who leave after the
  triage.

Without abandonment (versions 1 to 3) every function gives exactly the values
of before.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal

import numpy as np

from edsim.arrivals.rate import MINUTES_PER_DAY
from edsim.engine.analysis import (
    MEASURES,
    EpisodeRecord,
    completed_in_window,
    ended_in_window,
)
from edsim.engine.center import N_LEVELS
from edsim.engine.ground_truth import GroundTruth

MANCHESTER_MAX_WAIT: tuple[float, ...] = (0.0, 10.0, 60.0, 120.0, 240.0)
"""Maximum time to medical attention by triage level, 1 to 5, in minutes.

Immediate, 10, 60, 120 and 240 minutes: the five categories of the Manchester
Triage System (Manchester Triage Group, *Emergency Triage*, Mackway-Jones et
al.), as in the table of calibration targets of docs/diseno.md ("Manual del
sistema Manchester"). "Immediate" is 0: any wait misses it.
"""

CLOCKS = ("door_to_doctor", "triage_start_to_doctor", "classified_to_doctor")
"""The three clocks to the first doctor (docs/specs/hito-4.md, "Relojes y
cumplimiento"): from the arrival (A), from the start of the triage (B) and
from the classification (C)."""

COMPLIANCE_MEASURE = "classified_to_doctor"
"""Clock of the Manchester compliance: C. Before the triage there is no level,
and a maximum not assigned yet cannot be missed (ADR candidate 40)."""

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
    table: Sequence[EpisodeRecord],
    measure: str,
    first_day: int,
    end_day: int,
    level_of: Mapping[str, int] | None = None,
    *,
    triaged: bool = False,
) -> list[list[list[float]]]:
    """The values of ``measure``, by day of the stretch and level.

    The level is the episode's own, the assigned one; with ``level_of``, the
    one it gives to each ``episode_id``, such as the true level. The episodes
    are those that depart; with ``triaged``, also those who leave without
    being seen after their triage (the pretriage counts the triaged, H5-8).
    """
    out: list[list[list[float]]] = [
        [[] for _ in range(N_LEVELS)] for _ in range(first_day, end_day)
    ]
    start, end = first_day * MINUTES_PER_DAY, end_day * MINUTES_PER_DAY
    done = (
        [e for e in ended_in_window(table, start, end) if e.level is not None]
        if triaged
        else completed_in_window(table, start, end)
    )
    for e in done:
        value = getattr(e, measure)
        if value is None:
            raise ValueError(f"{e.episode_id} departed without a {measure}")
        level = e.level if level_of is None else _level_in(level_of, e.episode_id)
        out[math.floor(e.arrival / MINUTES_PER_DAY) - first_day][level - 1].append(value)
    return out


def _level_in(level_of: Mapping[str, int], episode_id: str) -> int:
    if episode_id not in level_of:
        raise ValueError(f"{episode_id} is not in the ground truth")
    return level_of[episode_id]


# --- Compliance with censoring (task 5.4) ---------------------------------------------

ComplianceStatus = Literal["within", "exceeded", "censored"]
"""How a patient counts in the Manchester compliance (H5-8)."""

_CLOCK_START = MappingProxyType(
    {
        "door_to_doctor": "arrival",
        "triage_start_to_doctor": "triage_start",
        "classified_to_doctor": "triage_end",
    }
)
"""Where each clock of ``CLOCKS`` starts, as a field of ``EpisodeRecord``."""


@dataclass(frozen=True, slots=True)
class ComplianceCase:
    """One patient of the Manchester compliance and how it counts.

    Attributes:
        episode: The episode.
        day: Index of its day of arrival in the stretch, from 0.
        level: The level of its maximum: the assigned one, or the one of
            ``level_of`` (such as the true level).
        clock: Its clock: until the doctor if it was seen; until it left, if it
            left without being seen.
        status: ``within`` (seen within the maximum, exactly at it complies),
            ``exceeded`` (seen after it, or left at it or after it) or
            ``censored`` (left before reaching it: it is not known whether it
            would have been seen in time, so it does not count).
    """

    episode: EpisodeRecord
    day: int
    level: int
    clock: float
    status: ComplianceStatus


def _left_clock(e: EpisodeRecord, measure: str) -> float:
    """The clock ``measure`` of a patient who left without being seen, at its departure.

    From the arrival (A), from the start of the triage (B) or from the
    classification (C) to ``patient_left_wbs``.
    """
    return e.left - getattr(e, _CLOCK_START[measure])


def compliance_cases(
    table: Sequence[EpisodeRecord],
    first_day: int,
    end_day: int,
    max_wait: Sequence[float],
    *,
    measure: str = "classified_to_doctor",
    level_of: Mapping[str, int] | None = None,
) -> list[ComplianceCase]:
    """The patients of the Manchester compliance in days ``[first_day, end_day)``, classified.

    The patients that arrive in the stretch and end there or later: those who
    depart (all of them seen by a doctor), with their clock to the doctor, and
    those who leave without being seen after their triage, with their clock
    until they leave. A patient who leaves at instant t was not seen at t
    (with the tie it stays, H5-4), so its clock to the doctor would be more
    than the one until it left: if that one reached the maximum, it is a sure
    miss; if not, censored. Whoever leaves before its triage is out: it has no
    classification, and it counts in the abandonment before the triage.
    Without abandonment, the patients of ``completed_in_window``, each
    ``within`` or ``exceeded`` as before.

    Args:
        table: The episodes of the log, from ``episode_table``.
        first_day: First day of the stretch.
        end_day: Day after the last.
        max_wait: Maximum time of each level, 1 to 5.
        measure: The clock, a name of ``CLOCKS``.
        level_of: The level of each ``episode_id`` instead of the assigned one,
            such as the true level.

    Raises:
        ValueError: If the measure, the days or ``max_wait`` are not valid, a
            seen patient has no ``measure`` or, with ``level_of``, a counted
            episode is not in it.
    """
    first_day, end_day, max_wait = _check_compliance_args(
        measure, first_day, end_day, max_wait, COMPLIANCE_TARGET
    )
    start, end = first_day * MINUTES_PER_DAY, end_day * MINUTES_PER_DAY
    out = []
    for e in ended_in_window(table, start, end):
        if e.departure is None and e.triage_end is None:
            continue  # left before its triage: no level, no clock C
        level = e.level if level_of is None else _level_in(level_of, e.episode_id)
        maximum = max_wait[level - 1]
        day = math.floor(e.arrival / MINUTES_PER_DAY) - first_day
        if e.departure is not None:
            clock = getattr(e, measure)
            if clock is None:
                raise ValueError(f"{e.episode_id} departed without a {measure}")
            status: ComplianceStatus = "within" if clock <= maximum else "exceeded"
        else:
            clock = _left_clock(e, measure)
            status = "exceeded" if clock >= maximum else "censored"
        out.append(ComplianceCase(e, day, level, clock, status))
    return out


def _check_compliance_args(
    measure: str, first_day: object, end_day: object, max_wait: Sequence[float], target: float
) -> tuple[int, int, tuple[float, ...]]:
    if measure not in CLOCKS:
        raise ValueError(f"measure must be one of {CLOCKS}, got {measure!r}")
    first_day, end_day = _check_days(first_day, end_day)
    max_wait = tuple(float(m) for m in max_wait)
    if len(max_wait) != N_LEVELS or any(not m >= 0 for m in max_wait):
        raise ValueError(f"max_wait must be {N_LEVELS} values >= 0, got {max_wait}")
    if not 0 < target <= 1:
        raise ValueError(f"target must be in (0, 1], got {target!r}")
    return first_day, end_day, max_wait


def compliance_from_cases(
    cases: Sequence[ComplianceCase],
    first_day: int,
    end_day: int,
    *,
    measure: str = COMPLIANCE_MEASURE,
    max_wait: Sequence[float] = MANCHESTER_MAX_WAIT,
    target: float = COMPLIANCE_TARGET,
) -> "Compliance":
    """The daily compliance of the cases of ``compliance_cases``, already classified.

    For whoever needs both the cases and the days, such as ``window_compliance``,
    without classifying the table twice; ``manchester_compliance`` is this on
    the cases of a table. The arguments must be those of the cases.

    Raises:
        ValueError: If the measure, the days, ``max_wait`` or ``target`` are
            not valid.
    """
    first_day, end_day, max_wait = _check_compliance_args(
        measure, first_day, end_day, max_wait, target
    )
    return _daily_compliance(cases, measure, first_day, end_day, max_wait, target)


def _daily_compliance(
    cases: Sequence[ComplianceCase],
    measure: str,
    first_day: int,
    end_day: int,
    max_wait: tuple[float, ...],
    target: float,
) -> "Compliance":
    """Count the cases by day and level into a ``Compliance``.

    ``within`` is the count within over ``n`` (the cases that count), the
    same float as the mean of the booleans of before.
    """
    shape = (end_day - first_day, N_LEVELS)
    n = np.zeros(shape, dtype=np.int64)
    n_within = np.zeros(shape, dtype=np.int64)
    left_late = np.zeros(shape, dtype=np.int64)
    censored = np.zeros(shape, dtype=np.int64)
    for c in cases:
        k = c.level - 1
        if c.status == "censored":
            censored[c.day, k] += 1
            continue
        n[c.day, k] += 1
        if c.status == "within":
            n_within[c.day, k] += 1
        elif c.episode.departure is None:
            left_late[c.day, k] += 1
    with np.errstate(invalid="ignore", divide="ignore"):
        within = np.where(n > 0, n_within / np.where(n > 0, n, 1), np.nan)
    out = (n > 0) & ~(within >= target)
    return Compliance(
        measure,
        np.arange(first_day, end_day),
        n,
        within,
        out,
        max_wait,
        float(target),
        left_late,
        censored,
    )


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
    """A clock to the doctor against the Manchester maximum times, by day and level.

    Attributes:
        measure: The clock, a name of ``CLOCKS``.
        days: Day of each row, counted from day 0 of the run.
        n: Episodes of each day and level that count, shape ``(days, 5)``:
            the seen ones and those who left after their maximum.
        within: Share of them that saw a doctor within the maximum time;
            ``nan`` without episodes.
        out: Whether the day is out of target for the level: ``within`` below
            ``target``. ``False`` without episodes.
        max_wait: The maximum time of each level, in minutes.
        target: The share required.
        left_late: Of ``n``, those who left without being seen once their clock
            reached the maximum: sure misses (task 5.4). ``None`` only if built
            by hand.
        censored: Those who left before reaching it, not in ``n`` (task 5.4).
            ``None`` only if built by hand.
    """

    measure: str
    days: np.ndarray
    n: np.ndarray
    within: np.ndarray
    out: np.ndarray
    max_wait: tuple[float, ...]
    target: float
    left_late: np.ndarray | None = field(default=None)
    censored: np.ndarray | None = field(default=None)

    @property
    def days_with_patients(self) -> np.ndarray:
        """Days with some episode of each level, shape ``(5,)``."""
        return (self.n > 0).sum(axis=0)

    @property
    def pooled_within(self) -> np.ndarray:
        """Share within the maximum of all the episodes of each level in the
        stretch, shape ``(5,)``; ``nan`` for a level without patients."""
        counts = np.rint(np.where(self.n > 0, self.within, 0) * self.n)
        with np.errstate(invalid="ignore", divide="ignore"):
            return counts.sum(axis=0) / self.n.sum(axis=0)

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
    measure: str = COMPLIANCE_MEASURE,
    max_wait: Sequence[float] = MANCHESTER_MAX_WAIT,
    target: float = COMPLIANCE_TARGET,
) -> Compliance:
    """Share of patients within the maximum time to the doctor, by day and level.

    A patient complies if its ``measure`` is at most the maximum of its level
    (exactly at the maximum complies). The default is clock C, from the
    classification, which ``runs/`` and the app use too. Notebook 03 passes
    ``door_to_doctor`` (clock A) to compare with milestone 3. A day is out of
    target for a level if the share of its patients that comply is below
    ``target``; a day without patients of the level is not counted.

    With the abandonment, the rule of the censoring (``compliance_cases``):
    whoever leaves without being seen with its clock at or above the maximum
    misses it, and whoever leaves before is censored (H5-8). Leaving never
    hides a sure miss, as removing those who leave would. A patient who would
    have been seen late and leaves before its maximum is censored, though, so
    the share of those that comply may still go up: censoring is the
    estimate of what is known, not a bound against abandonment.

    Args:
        table: The episodes of the log, from ``episode_table``.
        first_day: First day, such as the warm-up days.
        end_day: Day after the last, such as the horizon in days.
        measure: The clock, a name of ``CLOCKS``.
        max_wait: Maximum time of each level, 1 to 5.
        target: Share of the patients required, in (0, 1].

    Raises:
        ValueError: If the measure, the days, ``max_wait`` or ``target`` are
            not valid.
    """
    first_day, end_day, max_wait = _check_compliance_args(
        measure, first_day, end_day, max_wait, target
    )
    cases = compliance_cases(table, first_day, end_day, max_wait, measure=measure)
    return _daily_compliance(cases, measure, first_day, end_day, max_wait, target)


# --- Compliance by true level (only with the ground truth) ------------------------------


def true_levels(ground_truth: GroundTruth) -> Mapping[str, int]:
    """The true level of each episode of the ground truth, by ``episode_id``.

    Raises:
        ValueError: If an episode has no clinical truth (the provisional
            model has no true level apart from the assigned one).
    """
    out = {}
    for e in ground_truth.episodes:
        if e.clinical is None:
            raise ValueError(
                f"{e.episode_id} has no clinical truth: the true level needs the clinical model"
            )
        out[e.episode_id] = e.clinical.triage.true_level
    return MappingProxyType(out)


def true_level_compliance(
    table: Sequence[EpisodeRecord],
    ground_truth: GroundTruth,
    first_day: int,
    end_day: int,
    *,
    measure: str = COMPLIANCE_MEASURE,
    max_wait: Sequence[float] = MANCHESTER_MAX_WAIT,
    target: float = COMPLIANCE_TARGET,
) -> Compliance:
    """``manchester_compliance`` with the true level of each patient instead of the assigned one.

    The same rule, with the true level both to group the patients and to
    choose their maximum: an undertriaged level 2 assigned as 3 that sees a
    doctor in 30 minutes complies with its assigned level (60) and not with
    its true one (10). The difference with the observable compliance is the
    cost of the undertriage measured in time (docs/specs/hito-4.md, "Relojes
    y cumplimiento"). It needs the ground truth: it never goes into the log
    nor into the observable KPIs.

    Args:
        table: The episodes of the log, from ``episode_table``.
        ground_truth: The ground truth of the same run, with the clinical
            model.
        first_day: First day, such as the warm-up days.
        end_day: Day after the last, such as the horizon in days.
        measure: The clock, a name of ``CLOCKS``.
        max_wait: Maximum time of each level, 1 to 5.
        target: Share of the patients required, in (0, 1].

    The rule of the censoring is the same (``compliance_cases``): whoever
    leaves before its triage is out, although its truth has a level.

    Raises:
        ValueError: As ``manchester_compliance``, or if an episode has no
            clinical truth or a counted episode is not in the ground truth.
    """
    first_day, end_day, max_wait = _check_compliance_args(
        measure, first_day, end_day, max_wait, target
    )
    cases = compliance_cases(
        table, first_day, end_day, max_wait, measure=measure, level_of=true_levels(ground_truth)
    )
    return _daily_compliance(cases, measure, first_day, end_day, max_wait, target)


@dataclass(frozen=True)
class TrueLevelWaits:
    """One measure of the episodes of a stretch, with their assigned and true levels.

    Attributes:
        measure: A name of ``MEASURES``.
        episode_ids: The episodes, in the order of the table.
        assigned: Their assigned level, the one of the log.
        true: Their true level, from the ground truth.
        values: The measure of each one.
    """

    measure: str
    episode_ids: tuple[str, ...]
    assigned: np.ndarray
    true: np.ndarray
    values: np.ndarray


def true_level_waits(
    table: Sequence[EpisodeRecord],
    ground_truth: GroundTruth,
    measure: str,
    first_day: int,
    end_day: int,
) -> TrueLevelWaits:
    """One measure with both levels of each episode, in days ``[first_day, end_day)``.

    Only the episodes that arrive in the stretch and depart count
    (``completed_in_window``); each is paired with its truth by
    ``episode_id``.

    Raises:
        ValueError: If ``measure`` is unknown, the days are not valid, an
            episode has no clinical truth or a counted one is not in the
            ground truth.
    """
    if measure not in MEASURES:
        raise ValueError(f"measure must be one of {MEASURES}, got {measure!r}")
    first_day, end_day = _check_days(first_day, end_day)
    level_of = true_levels(ground_truth)
    done = completed_in_window(table, first_day * MINUTES_PER_DAY, end_day * MINUTES_PER_DAY)
    values = []
    for e in done:
        value = getattr(e, measure)
        if value is None:
            raise ValueError(f"{e.episode_id} departed without a {measure}")
        values.append(value)
    return TrueLevelWaits(
        measure=measure,
        episode_ids=tuple(e.episode_id for e in done),
        assigned=np.array([e.level for e in done], dtype=np.int64),
        true=np.array([_level_in(level_of, e.episode_id) for e in done], dtype=np.int64),
        values=np.array(values, dtype=float),
    )


def classified_late(
    table: Sequence[EpisodeRecord],
    first_day: int,
    end_day: int,
    *,
    max_wait: Sequence[float] = MANCHESTER_MAX_WAIT,
) -> np.ndarray:
    """Share of each level already above its maximum, counted from the arrival, when classified.

    For these patients the pretriage and the triage alone, from the arrival to
    ``triage_end``, take longer than the maximum of their assigned level, so
    no doctor can make them comply with clock A: with a maximum of 10
    minutes, level 2 misses it for every patient whose classification comes
    after minute 10 (exactly at 10 is not late). A level 1 classified at the
    door is classified on arrival, at 0. The same episodes as
    ``manchester_compliance``: those who arrive in the stretch and depart.

    Returns:
        One share per level, 1 to 5; ``nan`` for a level without patients.

    Raises:
        ValueError: If the days or ``max_wait`` are not valid.
    """
    first_day, end_day = _check_days(first_day, end_day)
    max_wait = tuple(float(m) for m in max_wait)
    if len(max_wait) != N_LEVELS or any(not m >= 0 for m in max_wait):
        raise ValueError(f"max_wait must be {N_LEVELS} values >= 0, got {max_wait}")
    done = completed_in_window(table, first_day * MINUTES_PER_DAY, end_day * MINUTES_PER_DAY)
    out = np.full(N_LEVELS, np.nan)
    for k in range(N_LEVELS):
        episodes = [e for e in done if e.level == k + 1]
        if episodes:
            out[k] = np.mean([e.triage_end - e.arrival > max_wait[k] for e in episodes])
    return out


# --- Clocks by level ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LevelClocks:
    """Median and 90th percentile of the three clocks of one level.

    Attributes:
        level: Triage level, 1 to 5.
        n: Episodes that arrived in the stretch and departed.
        median: Median of each name of ``CLOCKS``; ``None`` if ``n`` is 0.
        p90: 90th percentile, with linear interpolation (``numpy.percentile``,
            as ``LevelMetrics``); ``None`` if ``n`` is 0.
    """

    level: int
    n: int
    median: Mapping[str, float | None]
    p90: Mapping[str, float | None]


def clock_quantiles(
    table: Sequence[EpisodeRecord], first_day: int, end_day: int
) -> tuple[LevelClocks, ...]:
    """Median and p90 of the clocks A, B and C by level, in days ``[first_day, end_day)``.

    The level 1 is reported with these alone: its maximum is 0, so a share of
    compliance would always be 0 % (docs/specs/hito-4.md).

    Raises:
        ValueError: If the days are not valid.
    """
    first_day, end_day = _check_days(first_day, end_day)
    done = completed_in_window(table, first_day * MINUTES_PER_DAY, end_day * MINUTES_PER_DAY)
    out = []
    for level in range(1, N_LEVELS + 1):
        episodes = [e for e in done if e.level == level]
        median: dict[str, float | None] = {}
        p90: dict[str, float | None] = {}
        for name in CLOCKS:
            values = np.array([getattr(e, name) for e in episodes], dtype=float)
            median[name] = float(np.median(values)) if values.size else None
            p90[name] = float(np.percentile(values, 90)) if values.size else None
        out.append(
            LevelClocks(level, len(episodes), MappingProxyType(median), MappingProxyType(p90))
        )
    return tuple(out)


# --- Pretriage ---------------------------------------------------------------------------

PRETRIAGE_MAX_WAIT = 10.0
"""Maximum minutes from the arrival to the start of the triage: the standard
"admission to triage in less than 10 minutes" (docs/specs/hito-4.md)."""

PRETRIAGE_TARGET = 0.85
"""Share of the patients of a day that must start the triage within
``PRETRIAGE_MAX_WAIT``; a day below it is out of target."""

PRETRIAGE_LONG_WAIT = 5.0
"""A pretriage above it counts in the TECLA indicator of the SAS (share of
patients waiting more than 5 minutes to be classified)."""

PRETRIAGE_GROUPS: tuple[int | None, ...] = (2, 3, 4, 5, None)
"""Columns of ``Pretriage``: levels 2 to 5 and, as ``None``, all of them. A
level 1 is classified at the door and does not count."""


def _check_minutes(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not value >= 0:
        raise ValueError(f"{name} must be a number >= 0, got {value!r}")
    return float(value)


@dataclass(frozen=True)
class Pretriage:
    """The pretriage (``triage_wait``) by day and level, levels 2 to 5.

    Every array has one row per day and one column per group of
    ``PRETRIAGE_GROUPS``: levels 2, 3, 4 and 5, and the four together.

    Attributes:
        days: Day of each row, counted from day 0 of the run.
        groups: ``PRETRIAGE_GROUPS``.
        n: Episodes of each day and group.
        n_within: Of them, how many started the triage within ``max_wait``
            (exactly at the maximum complies).
        n_over: How many waited more than ``long_wait``.
        max_wait: The maximum pretriage, in minutes.
        long_wait: The threshold of the long waits, in minutes.
        target: Share of ``n_within`` required.
    """

    days: np.ndarray
    groups: tuple[int | None, ...]
    n: np.ndarray
    n_within: np.ndarray
    n_over: np.ndarray
    max_wait: float
    long_wait: float
    target: float

    @property
    def within(self) -> np.ndarray:
        """Share within ``max_wait``; ``nan`` without episodes."""
        with np.errstate(invalid="ignore", divide="ignore"):
            return self.n_within / self.n

    @property
    def over(self) -> np.ndarray:
        """Share above ``long_wait``; ``nan`` without episodes."""
        with np.errstate(invalid="ignore", divide="ignore"):
            return self.n_over / self.n

    @property
    def out(self) -> np.ndarray:
        """Whether the day is out of target: ``within`` below ``target``.
        ``False`` without episodes."""
        return (self.n > 0) & ~(self.within >= self.target)

    @property
    def days_with_patients(self) -> np.ndarray:
        """Days with some episode of each group."""
        return (self.n > 0).sum(axis=0)

    @property
    def share_out(self) -> np.ndarray:
        """Share of the days with patients that are out of target; ``nan``
        for a group without patients in the stretch."""
        with np.errstate(invalid="ignore", divide="ignore"):
            return self.out.sum(axis=0) / self.days_with_patients

    @property
    def pooled_n(self) -> np.ndarray:
        """Episodes of each group in the whole stretch."""
        return self.n.sum(axis=0)

    @property
    def pooled_within(self) -> np.ndarray:
        """Share within ``max_wait`` of all the episodes of the stretch."""
        with np.errstate(invalid="ignore", divide="ignore"):
            return self.n_within.sum(axis=0) / self.pooled_n

    @property
    def pooled_over(self) -> np.ndarray:
        """Share above ``long_wait`` of all the episodes of the stretch."""
        with np.errstate(invalid="ignore", divide="ignore"):
            return self.n_over.sum(axis=0) / self.pooled_n


def pretriage(
    table: Sequence[EpisodeRecord],
    first_day: int,
    end_day: int,
    *,
    max_wait: float = PRETRIAGE_MAX_WAIT,
    long_wait: float = PRETRIAGE_LONG_WAIT,
    target: float = PRETRIAGE_TARGET,
) -> Pretriage:
    """The pretriage indicator by day and level, without the level 1.

    The same rule of days as ``manchester_compliance`` (task 3.8): the day of
    an episode is the day of its arrival, and only the episodes that arrive
    in the stretch and end there count: those who depart and, with the
    abandonment (task 5.4), those who leave after their triage, because the
    pretriage is of the triaged patients (H5-8).

    Args:
        table: The episodes of the log, from ``episode_table``.
        first_day: First day, such as the warm-up days.
        end_day: Day after the last, such as the horizon in days.
        max_wait: Maximum pretriage, in minutes.
        long_wait: Threshold of the long waits, in minutes.
        target: Share of the patients required, in (0, 1].

    Raises:
        ValueError: If the days, the minutes or ``target`` are not valid.
    """
    first_day, end_day = _check_days(first_day, end_day)
    max_wait = _check_minutes("max_wait", max_wait)
    long_wait = _check_minutes("long_wait", long_wait)
    if not 0 < target <= 1:
        raise ValueError(f"target must be in (0, 1], got {target!r}")

    values = _by_day_and_level(table, "triage_wait", first_day, end_day, triaged=True)
    shape = (end_day - first_day, len(PRETRIAGE_GROUPS))
    n = np.zeros(shape, dtype=np.int64)
    n_within = np.zeros(shape, dtype=np.int64)
    n_over = np.zeros(shape, dtype=np.int64)
    for d, day in enumerate(values):
        for g, level in enumerate(PRETRIAGE_GROUPS):
            levels = range(2, N_LEVELS + 1) if level is None else (level,)
            waits = np.array([w for lv in levels for w in day[lv - 1]], dtype=float)
            n[d, g] = waits.size
            n_within[d, g] = np.sum(waits <= max_wait)
            n_over[d, g] = np.sum(waits > long_wait)
    return Pretriage(
        days=np.arange(first_day, end_day),
        groups=PRETRIAGE_GROUPS,
        n=n,
        n_within=n_within,
        n_over=n_over,
        max_wait=max_wait,
        long_wait=long_wait,
        target=float(target),
    )
