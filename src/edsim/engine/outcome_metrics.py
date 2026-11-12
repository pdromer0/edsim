"""Indicators of the outcome of milestone 5, from the event log (task 5.4, H5-8).

The observable indicators of the abandonment, the destinations and the wait for
a bed (docs/specs/hito-5.md, piece 4), as pure functions of the episode table
and the step curves of a log of version 4, like ``analysis.py``:

- ``left_without_being_seen_shares``: the abandonment, overall, before and
  after the triage (the two indicators of SEMES), by place and by assigned
  level;
- ``destination_shares``: admission, transfer, death and discharge, overall and
  by assigned level;
- ``bed_wait_quantiles``: median, p90 and shares above 6, 12 and 24 hours of
  the wait for a bed;
- ``stay_by_destination``: the stay by destination, with those who leave apart
  with their time until they leave, and the share of admitted patients above 4
  hours;
- ``bed_occupancy``: boxes held by admitted patients waiting for a bed, and
  patients in the hallway;
- ``window_outcome``: all of them for one window.

The closing of the flow (task 5.7) adds what the notebook 05 teaches:
``kaplan_meier`` (the survival estimate with censoring), ``abandonment_by_arrival_hour``
(the abandonment against the wait of each hour of arrival) and ``bed_little`` (both
sides of ``L = λ · W`` for the wait for a bed).

**Censoring.** A patient still waiting for a bed at the horizon, or still
inside, only tells that its wait is at least what it has waited until then.
Leaving it out would make the waits shorter than they are. The statistics take
it with that lower bound (``censored_quantile``, ``censored_mean``): any
quantile grows when one of its values grows, so with the censored values at
their bounds it is the least it can be, and with them above every value, the
most; if both agree it is **exact**, and if not, the value is a **lower
bound** (``≥``). A share above a threshold counts a censored value above it as
above, and one at or below it as unknown (it may still reach it).

The denominators: the arrivals of the window for the overall shares, as the
``objetivo`` of ``perfiles.toml``; for the shares by assigned level, the
patients classified with that level, since only they have one. Who is still
inside at the end counts in the arrivals: the abandonment and the destinations
are what is known at the horizon.

The indicators of the true level (abandonment by true level, the severe
patients who left, those who would have been admitted) need the ground truth:
they are in ``edsim.runs.truth``, never here.
"""

import math
from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from edsim.arrivals.rate import MINUTES_PER_DAY
from edsim.engine.analysis import EpisodeRecord, StepCurves
from edsim.engine.center import N_LEVELS
from edsim.engine.events import LWBS_WAITS
from edsim.profiles.config import DESTINATIONS

BED_WAIT_THRESHOLDS: tuple[float, ...] = (360.0, 720.0, 1440.0)
"""The wait for a bed above 6, 12 and 24 hours, in minutes (piece 4)."""

ADMITTED_LONG_STAY = 240.0
"""The stay of the admitted patients above 4 hours, in minutes (piece 4)."""

ADMISSION = "ingreso"


def _check_window(start: float, end: float, horizon: float) -> None:
    if not 0 <= start < end <= horizon or not math.isfinite(horizon):
        raise ValueError(
            f"the window needs 0 <= start < end <= horizon ({horizon}), got {start=} and {end=}"
        )


def _arrived(table: Sequence[EpisodeRecord], start: float, end: float) -> list[EpisodeRecord]:
    return [e for e in table if start <= e.arrival < end]


def _share(count: int, n: int) -> float | None:
    return count / n if n else None


# --- Values with censoring ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CensoredValue:
    """A statistic of values some of which are censored.

    Attributes:
        value: The statistic with the censored values at their lower bounds:
            exact if ``exact``, a lower bound (``≥``) if not.
        exact: Whether the censored values cannot change it.
    """

    value: float
    exact: bool


def _check_values(name: str, values: Sequence[float]) -> list[float]:
    out = [float(v) for v in values]
    if any(not math.isfinite(v) or v < 0 for v in out):
        raise ValueError(f"{name} must be finite numbers >= 0, got {values!r}")
    return out


def censored_quantile(
    values: Sequence[float], censored: Sequence[float], percent: float
) -> CensoredValue | None:
    """The ``percent`` percentile of complete and right-censored values.

    Linear interpolation, as ``numpy.percentile``. With the censored values at
    their bounds it is the least the percentile can be; with them above every
    value (a finite ``H``, so that the interpolation never meets an infinity),
    the most. Exact if both are the same.

    Args:
        values: The complete values, such as the waits that ended.
        censored: The lower bounds of the censored values, such as the time
            waited until the horizon.
        percent: The percentile, in [0, 100]: 50 for the median.

    Returns:
        The percentile, or ``None`` without any value.

    Raises:
        ValueError: If a value is not finite or is negative, or ``percent`` is
            not in [0, 100].
    """
    if not 0 <= percent <= 100:
        raise ValueError(f"percent must be in [0, 100], got {percent!r}")
    known = _check_values("values", values)
    bounds = _check_values("censored", censored)
    if not known and not bounds:
        return None
    least = float(np.percentile(known + bounds, percent))
    if not bounds:
        return CensoredValue(least, True)
    above = max(known + bounds) + 1.0
    most = float(np.percentile(known + [above] * len(bounds), percent))
    return CensoredValue(least, least == most)


def censored_mean(values: Sequence[float], censored: Sequence[float]) -> CensoredValue | None:
    """The mean of complete and right-censored values.

    With the censored values at their bounds, a lower bound; exact only
    without censored values, since any of them may still grow.

    Returns:
        The mean, or ``None`` without any value.
    """
    known = _check_values("values", values)
    bounds = _check_values("censored", censored)
    if not known and not bounds:
        return None
    return CensoredValue(float(np.mean(known + bounds)), not bounds)


@dataclass(frozen=True, slots=True)
class OverThreshold:
    """How many values are above a threshold, with censoring.

    Attributes:
        minutes: The threshold; above means strictly above.
        over: Values known to be above it: complete above it, and censored
            whose bound is already above it.
        known: Values whose side is known: all but ``unknown``.
        unknown: Censored values at or below it: they may still pass it.
    """

    minutes: float
    over: int
    known: int
    unknown: int

    @property
    def share(self) -> float | None:
        """``over / known``; ``None`` if no side is known."""
        return _share(self.over, self.known)


def over_threshold(
    values: Sequence[float], censored: Sequence[float], minutes: float
) -> OverThreshold:
    """Count the values above ``minutes``; a censored one at or below it is unknown."""
    known = _check_values("values", values)
    bounds = _check_values("censored", censored)
    unknown = sum(b <= minutes for b in bounds)
    over = sum(v > minutes for v in known) + sum(b > minutes for b in bounds)
    return OverThreshold(float(minutes), over, len(known) + len(bounds) - unknown, unknown)


# --- Abandonment ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LevelCount:
    """How many of the patients classified with a level did something.

    Attributes:
        level: Assigned level, 1 to 5.
        classified: Patients of the window classified with it.
        count: Of them, those who did it (left, or departed to a destination).
    """

    level: int
    classified: int
    count: int

    @property
    def share(self) -> float | None:
        """``count / classified``; ``None`` without patients of the level."""
        return _share(self.count, self.classified)


@dataclass(frozen=True, slots=True)
class LeftWithoutBeingSeen:
    """The abandonment of the patients that arrive in a window (piece 4).

    Attributes:
        arrivals: Patients that arrive in the window.
        by_wait: Those who left, by ``espera``, in the order of ``LWBS_WAITS``.
        by_level: Those who left after their triage, by assigned level, over
            the patients classified with it.
    """

    arrivals: int
    by_wait: Mapping[str, int]
    by_level: tuple[LevelCount, ...]

    @property
    def left(self) -> int:
        """Patients who left without being seen."""
        return sum(self.by_wait.values())

    @property
    def before_triage(self) -> int:
        """Those who left before their triage (``triaje``)."""
        return self.by_wait["triaje"]

    @property
    def after_triage(self) -> int:
        """Those who left after their triage, waiting for a box or a doctor."""
        return self.left - self.before_triage

    @property
    def share(self) -> float | None:
        """Share of the arrivals who left; ``None`` without arrivals."""
        return _share(self.left, self.arrivals)

    @property
    def before_triage_share(self) -> float | None:
        """Share of the arrivals who left before the triage (SEMES)."""
        return _share(self.before_triage, self.arrivals)

    @property
    def after_triage_share(self) -> float | None:
        """Share of the arrivals who left after the triage (SEMES); with the
        one before it, the overall share."""
        return _share(self.after_triage, self.arrivals)


def left_without_being_seen_shares(
    table: Sequence[EpisodeRecord], start: float, end: float
) -> LeftWithoutBeingSeen:
    """The abandonment of the patients that arrive in ``[start, end)``.

    Each leaves once, whenever it is: also after ``end``, if the log goes on.
    """
    arrived = _arrived(table, start, end)
    by_wait = dict.fromkeys(LWBS_WAITS, 0)
    for e in arrived:
        if e.left_from is not None:
            by_wait[e.left_from] += 1
    by_level = tuple(
        LevelCount(
            level,
            sum(e.level == level for e in arrived),
            sum(e.level == level and e.left is not None for e in arrived),
        )
        for level in range(1, N_LEVELS + 1)
    )
    return LeftWithoutBeingSeen(len(arrived), MappingProxyType(by_wait), by_level)


# --- Destinations -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LevelDestinations:
    """The destinations of the patients classified with one level.

    Attributes:
        level: Assigned level, 1 to 5.
        classified: Patients of the window classified with it.
        counts: Those who departed, by destination, in the order of
            ``DESTINATIONS``.
    """

    level: int
    classified: int
    counts: Mapping[str, int]

    def share(self, destination: str) -> float | None:
        """Share of the classified patients of the level who departed to ``destination``."""
        return _share(self.counts[destination], self.classified)


@dataclass(frozen=True, slots=True)
class DestinationShares:
    """The destinations of the patients that arrive in a window (piece 4).

    Attributes:
        arrivals: Patients that arrive in the window.
        counts: Those who departed, by destination, in the order of
            ``DESTINATIONS``.
        by_level: The same by assigned level, over the patients classified
            with it.
    """

    arrivals: int
    counts: Mapping[str, int]
    by_level: tuple[LevelDestinations, ...]

    def share(self, destination: str) -> float | None:
        """Share of the arrivals who departed to ``destination``; ``None`` without arrivals."""
        return _share(self.counts[destination], self.arrivals)


def destination_shares(
    table: Sequence[EpisodeRecord], start: float, end: float
) -> DestinationShares:
    """Admission, transfer, death and discharge of the patients that arrive in ``[start, end)``."""
    arrived = _arrived(table, start, end)

    def counts(episodes: Sequence[EpisodeRecord]) -> Mapping[str, int]:
        out = dict.fromkeys(DESTINATIONS, 0)
        for e in episodes:
            if e.destination is not None:
                out[e.destination] += 1
        return MappingProxyType(out)

    by_level = []
    for level in range(1, N_LEVELS + 1):
        classified = [e for e in arrived if e.level == level]
        by_level.append(LevelDestinations(level, len(classified), counts(classified)))
    return DestinationShares(len(arrived), counts(arrived), tuple(by_level))


# --- The wait for a bed -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BedWait:
    """The wait for a bed of the patients that arrive in a window (piece 4).

    Attributes:
        requests: Patients who asked for a bed.
        completed: Of them, those who got it before the horizon.
        censored: Those still waiting at the horizon: their wait is at least
            the horizon minus their ``bed_requested``.
        median: The median, with censoring; ``None`` without requests.
        p90: The 90th percentile, with censoring; ``None`` without requests.
        over: Above each of ``BED_WAIT_THRESHOLDS``.
    """

    requests: int
    completed: int
    censored: int
    median: CensoredValue | None
    p90: CensoredValue | None
    over: tuple[OverThreshold, ...]


def bed_wait_quantiles(
    table: Sequence[EpisodeRecord], start: float, end: float, horizon: float
) -> BedWait:
    """The wait for a bed of the patients that arrive in ``[start, end)``.

    Args:
        table: The episodes of the log, from ``episode_table``.
        start: Start of the window, in minutes.
        end: End of the window.
        horizon: End of the log: the bound of who is still waiting.

    Raises:
        ValueError: If the window is not inside ``[0, horizon]``.
    """
    _check_window(start, end, horizon)
    asked = [e for e in _arrived(table, start, end) if e.bed_requested is not None]
    waits = [e.bed_wait for e in asked if e.bed_wait is not None]
    bounds = [horizon - e.bed_requested for e in asked if e.bed_wait is None]
    return BedWait(
        requests=len(asked),
        completed=len(waits),
        censored=len(bounds),
        median=censored_quantile(waits, bounds, 50),
        p90=censored_quantile(waits, bounds, 90),
        over=tuple(over_threshold(waits, bounds, m) for m in BED_WAIT_THRESHOLDS),
    )


# --- The stay by destination --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StaySummary:
    """A stay, with censoring.

    Attributes:
        n: Patients whose stay ended.
        censored: Patients still inside at the horizon, with their time inside
            until then as a lower bound.
        mean: The mean; ``None`` without patients.
        median: The median; ``None`` without patients.
        p90: The 90th percentile; ``None`` without patients.
    """

    n: int
    censored: int
    mean: CensoredValue | None
    median: CensoredValue | None
    p90: CensoredValue | None


def _stay_summary(values: Sequence[float], bounds: Sequence[float]) -> StaySummary:
    return StaySummary(
        len(values),
        len(bounds),
        censored_mean(values, bounds),
        censored_quantile(values, bounds, 50),
        censored_quantile(values, bounds, 90),
    )


@dataclass(frozen=True, slots=True)
class StayByDestination:
    """The stay of the patients that arrive in a window, by destination (piece 4).

    Attributes:
        by_destination: The stay of those who departed to each destination,
            in the order of ``DESTINATIONS``. Only the admitted can be inside
            with a destination (waiting for a bed): they are its censored ones.
        left: Those who left without being seen, apart: their time until they
            left, never censored.
        inside_without_destination: Patients still inside at the horizon
            without a destination yet.
        admitted_over: Admitted patients with a stay above
            ``ADMITTED_LONG_STAY``, with the censored ones.
    """

    by_destination: Mapping[str, StaySummary]
    left: StaySummary
    inside_without_destination: int
    admitted_over: OverThreshold


def stay_by_destination(
    table: Sequence[EpisodeRecord], start: float, end: float, horizon: float
) -> StayByDestination:
    """The stay by destination of the patients that arrive in ``[start, end)``.

    Raises:
        ValueError: If the window is not inside ``[0, horizon]``.
    """
    _check_window(start, end, horizon)
    arrived = _arrived(table, start, end)
    inside = [e for e in arrived if e.end is None]
    # Only the admitted can be inside with a destination: waiting for their bed.
    censored = {
        d: [horizon - e.arrival for e in inside if e.bed_requested is not None]
        if d == ADMISSION
        else []
        for d in DESTINATIONS
    }
    stays = {d: [e.stay for e in arrived if e.destination == d] for d in DESTINATIONS}
    return StayByDestination(
        by_destination=MappingProxyType(
            {d: _stay_summary(stays[d], censored[d]) for d in DESTINATIONS}
        ),
        left=_stay_summary([e.time_to_leave for e in arrived if e.left is not None], []),
        inside_without_destination=sum(e.bed_requested is None for e in inside),
        admitted_over=over_threshold(stays[ADMISSION], censored[ADMISSION], ADMITTED_LONG_STAY),
    )


# --- Boxes blocked by the wait for a bed ----------------------------------------------


@dataclass(frozen=True, slots=True)
class BedOccupancy:
    """Admitted patients waiting for a bed, in the window (piece 4).

    Attributes:
        boxes_mean: Time average of the boxes they hold (``boxes_waiting_bed``).
        boxes_max: The most of them at once in the window.
        hallway_mean: Time average of those in the hallway (``hallway``).
        hallway_max: The most of them at once in the window.
    """

    boxes_mean: float
    boxes_max: int
    hallway_mean: float
    hallway_max: int


def _window_max(curves: StepCurves, name: str, start: float, end: float) -> int:
    """The highest value of a curve over ``[start, end)``."""
    times = curves.times
    next_t = np.append(times[1:], curves.horizon)
    alive = (next_t > start) & (times < end)
    return int(curves[name][alive].max())


def bed_occupancy(curves: StepCurves, start: float, end: float) -> BedOccupancy:
    """Boxes held by admitted patients waiting for a bed, and patients in the hallway.

    Raises:
        ValueError: If the window is not inside ``[0, horizon]``.
    """
    _check_window(start, end, curves.horizon)
    return BedOccupancy(
        boxes_mean=curves.mean("boxes_waiting_bed", start, end),
        boxes_max=_window_max(curves, "boxes_waiting_bed", start, end),
        hallway_mean=curves.mean("hallway", start, end),
        hallway_max=_window_max(curves, "hallway", start, end),
    )


# --- Survival of the patience, the arrival hour and the law of Little (task 5.7) -----------


@dataclass(frozen=True, slots=True)
class KaplanMeier:
    """The Kaplan–Meier estimate of a survival function from right-censored times.

    Attributes:
        times: The distinct times with at least one event, increasing.
        at_risk: At each of them, the observations whose time is at least it:
            a censoring at the same time still counts (the event goes first).
        events: Events at each of them.
        survival: ``S(t)`` after each of them: the product of ``1 - d / n``.
        n: Observations, events and censored.
        observed: Times of all the observations, increasing: the risk set at
            any ``t`` is read from them (``at_risk_at``).

    Above the largest observed time the estimate says nothing: ``at`` stays at
    its last value and ``at_risk_at`` is 0.
    """

    times: tuple[float, ...]
    at_risk: tuple[int, ...]
    events: tuple[int, ...]
    survival: tuple[float, ...]
    n: int
    observed: tuple[float, ...]

    def at(self, t: float) -> float:
        """``S(t)``: 1 before the first event, a step function continuous on the right."""
        _check_time(t)
        i = bisect_right(self.times, t)
        return 1.0 if i == 0 else self.survival[i - 1]

    def at_risk_at(self, t: float) -> int:
        """The observations whose time is at least ``t``: 0 above the largest."""
        _check_time(t)
        return self.n - bisect_left(self.observed, t)


def _check_time(t: float) -> None:
    if not math.isfinite(t):
        raise ValueError(f"t must be finite, got {t!r}")


def kaplan_meier(times: Sequence[float], events: Sequence[bool]) -> KaplanMeier:
    """Estimate ``S(t) = P(T > t)`` from times that may be right-censored.

    A censored time says only that the event had not happened by then. The
    convention for a tie of an event and a censoring is the usual one: the
    event goes first, so the censored observation is still at risk at that time.
    Done with sorting alone (``O(n log n)``), without a loop over the observations.

    Args:
        times: The time of each observation, finite and not negative.
        events: Whether each observation is an event (``True``) or censored.

    Raises:
        ValueError: If the lists have different lengths, or a time is NaN,
            infinite or negative.
    """
    t = np.asarray(times, dtype=float)
    d = np.asarray(events, dtype=bool)
    if t.ndim != 1 or d.shape != t.shape:
        raise ValueError(f"times and events need the same length, got {t.shape} and {d.shape}")
    if not np.all(np.isfinite(t)) or np.any(t < 0):
        raise ValueError("times must be finite numbers >= 0")
    order = np.argsort(t, kind="stable")
    t, d = t[order], d[order]
    n = len(t)
    event_times = t[d]
    distinct = np.unique(event_times)
    at_risk = n - np.searchsorted(t, distinct, side="left")
    counts = np.searchsorted(event_times, distinct, side="right") - np.searchsorted(
        event_times, distinct, side="left"
    )
    survival = np.cumprod(1.0 - counts / at_risk) if len(distinct) else np.empty(0)
    return KaplanMeier(
        times=tuple(float(x) for x in distinct),
        at_risk=tuple(int(x) for x in at_risk),
        events=tuple(int(x) for x in counts),
        survival=tuple(float(x) for x in survival),
        n=int(n),
        observed=tuple(float(x) for x in t),
    )


@dataclass(frozen=True, slots=True)
class HourlyAbandonment:
    """The patients that arrive in one hour of the day, over the whole window.

    Attributes:
        hour: Hour of the day of the arrival, 0 to 23.
        arrivals: Patients that arrived in that hour.
        left: Of them, those who left without being seen.
        attended: Of them, those who saw a doctor.
        mean_wait_attended: Mean of clock A (arrival to first doctor) of the
            attended; ``None`` if there are none. It leaves out whoever left,
            who waited more: a survivor bias.
        mean_queue_time: Mean time until being seen or leaving, of everyone
            who did either; ``None`` if there are none. Whoever still waits at
            the horizon is left out.
    """

    hour: int
    arrivals: int
    left: int
    attended: int
    mean_wait_attended: float | None
    mean_queue_time: float | None

    @property
    def left_share(self) -> float | None:
        """``left / arrivals``; ``None`` without arrivals."""
        return _share(self.left, self.arrivals)


def abandonment_by_arrival_hour(
    table: Sequence[EpisodeRecord], start: float, end: float
) -> tuple[HourlyAbandonment, ...]:
    """The abandonment and the wait by hour of arrival, 24 rows (piece 1, exercise).

    The hour is ``int(arrival % 1440 // 60)``: the clock of the simulation starts
    at 0:00, so all the days of the window are folded onto one.
    """
    if not 0 <= start < end:
        raise ValueError(f"need 0 <= start < end, got {start=} and {end=}")
    rows = []
    arrived = _arrived(table, start, end)
    for hour in range(24):
        group = [e for e in arrived if int(e.arrival % MINUTES_PER_DAY // 60) == hour]
        waits = [e.door_to_doctor for e in group if e.door_to_doctor is not None]
        queue = waits + [e.time_to_leave for e in group if e.time_to_leave is not None]
        rows.append(
            HourlyAbandonment(
                hour=hour,
                arrivals=len(group),
                left=sum(e.left is not None for e in group),
                attended=len(waits),
                mean_wait_attended=float(np.mean(waits)) if waits else None,
                mean_queue_time=float(np.mean(queue)) if queue else None,
            )
        )
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class BedLittle:
    """The law of Little for the patients waiting for a bed: ``L = λ · W``.

    Attributes:
        requests: Patients of the window who asked for a bed.
        rate: ``λ``: requests per minute of the window.
        mean_wait: ``W``: mean wait of those patients, with whoever still waits
            at the horizon cut there (a lower bound); ``None`` without requests.
        by_little: ``λ · W``, the mean number waiting, which equals the sum of
            the waits over the length of the window.
        boxes_mean: Mean of the curve ``boxes_waiting_bed`` over the window.
        hallway_mean: Mean of the curve ``hallway`` over the window.
    """

    requests: int
    rate: float
    mean_wait: float | None
    by_little: float
    boxes_mean: float
    hallway_mean: float

    @property
    def by_curves(self) -> float:
        """Everybody waiting for a bed by the curves: in a box and in the hallway."""
        return self.boxes_mean + self.hallway_mean


def bed_little(
    table: Sequence[EpisodeRecord], curves: StepCurves, start: float, end: float
) -> BedLittle:
    """Both sides of the law of Little for the wait for a bed in one run.

    ``λ`` and ``W`` are those of the patients that arrive in ``[start, end)`` and
    ask for a bed; the curves count whoever waits in the window, wherever they
    arrived. The two agree up to the edges of the window.

    Raises:
        ValueError: If the window is not inside ``[0, horizon]``.
    """
    horizon = curves.horizon
    _check_window(start, end, horizon)
    waits = [
        e.bed_wait if e.bed_wait is not None else horizon - e.bed_requested
        for e in _arrived(table, start, end)
        if e.bed_requested is not None
    ]
    rate = len(waits) / (end - start)
    mean_wait = float(np.mean(waits)) if waits else None
    return BedLittle(
        requests=len(waits),
        rate=rate,
        mean_wait=mean_wait,
        by_little=rate * mean_wait if mean_wait is not None else 0.0,
        boxes_mean=curves.mean("boxes_waiting_bed", start, end),
        hallway_mean=curves.mean("hallway", start, end),
    )


# --- A window -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WindowOutcome:
    """The indicators of the outcome of milestone 5 in a window.

    Attributes:
        start: Start of the window, in minutes.
        end: End of the window, the horizon.
        left: The abandonment.
        destinations: The destinations.
        bed_wait: The wait for a bed.
        stay: The stay by destination.
        beds: Boxes blocked and patients in the hallway.
    """

    start: float
    end: float
    left: LeftWithoutBeingSeen
    destinations: DestinationShares
    bed_wait: BedWait
    stay: StayByDestination
    beds: BedOccupancy


def window_outcome(
    table: Sequence[EpisodeRecord], curves: StepCurves, start: float, end: float
) -> WindowOutcome:
    """Every indicator of the outcome in ``[start, end]``, with the horizon of ``curves``.

    Args:
        table: The episodes of the log, from ``episode_table``.
        curves: The curves of the same log, from ``step_curves``.
        start: Start of the window in minutes, such as ``warmup_days * 1440``.
        end: End of the window, at most the horizon of the curves.

    Raises:
        ValueError: If the window is not inside ``[0, horizon]``.
    """
    horizon = curves.horizon
    _check_window(start, end, horizon)
    return WindowOutcome(
        start=float(start),
        end=float(end),
        left=left_without_being_seen_shares(table, start, end),
        destinations=destination_shares(table, start, end),
        bed_wait=bed_wait_quantiles(table, start, end, horizon),
        stay=stay_by_destination(table, start, end, horizon),
        beds=bed_occupancy(curves, start, end),
    )
