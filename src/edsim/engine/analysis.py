"""State and metrics derived from the event log (event sourcing).

The engine writes facts; everything here folds them back into state and
metrics, with pure functions that take the events in file order
(docs/specs/hito-3.md, "Estado y métricas derivados del log"). The CLI and the
notebook only call them (decision 16).

- ``episode_table``: one row per episode, with the instants of its milestones
  and its waits.
- ``step_curves``: census, queues, busy staff and boxes, and the staff in
  force, as step functions of time that change only at events.
- ``window_metrics``: waits and stay by level, time averages, occupancy by pool
  and shift, and throughput, in the window [warm-up, horizon].
- ``little_laws`` and ``utilization_identities``: operational laws, which
  compare two ways of computing the same thing on one run.

The window follows the rules of ``mm1_metrics`` (milestone 1):

- per-episode values (waits, stay) average the episodes that arrive inside the
  window and depart before its end; the others are left out, because their
  times are not known or belong to the warm-up;
- time averages and areas clip each curve to the window; whoever is still
  inside at the end counts until the horizon;
- the throughput is the arrivals inside the window over its length.

The waits of an episode follow the same rules as the invariant "nobody jumps
the queue" (``check_nobody_jumps_the_queue``):

- waiting for a box: from ``triage_completed`` and from every
  ``patient_displaced`` to the next ``box_assigned``;
- waiting for a doctor: holding a box with an assessment to do, from
  ``box_assigned`` or ``test_resulted`` to ``assessment_started`` or
  ``patient_displaced``.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from edsim.arrivals.rate import MINUTES_PER_DAY
from edsim.engine.center import N_LEVELS, CenterConfig
from edsim.engine.events import Event
from edsim.engine.shifts import MINUTES_PER_HOUR, shift_at
from edsim.queueing.analysis import sample_step, step_time_average

# --- Episode table ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EpisodeRecord:
    """What happened to one episode, from its events.

    ``None`` means it did not happen before the end of the log: nothing is made
    up for the episodes the horizon cuts.

    Attributes:
        episode_id: Such as ``EP-000137``.
        arrival: ``sim_time`` of ``patient_arrived``.
        triage_start: Start of the triage.
        triage_end: End of the triage (``triage_completed``).
        level: Triage level, 1 to 5.
        first_box: First ``box_assigned``; later ones, after a displacement,
            do not change it.
        first_assessment: First ``assessment_started``.
        decision: ``disposition_decided``.
        departure: ``patient_departed``.
        destination: ``alta`` or ``ingreso``.
        displacements: Times the episode was displaced from a box.
        triage_wait: From the arrival to the start of the triage.
        box_wait: Total time waiting for a box: after the triage and after
            each displacement. Final only at the departure, ``None`` before.
        doctor_wait: Total time holding a box and waiting for a doctor, for
            the first assessment, the reassessment and the resumptions after
            a displacement. Final only at the departure, ``None`` before.
        initial_doctor_wait: Time holding a box and waiting for a doctor
            before the first ``assessment_started``, from the first
            ``box_assigned`` on.
        door_to_doctor: From the arrival to the first ``assessment_started``,
            the KPI of the Manchester maximum times.
    """

    episode_id: str
    arrival: float
    triage_start: float | None
    triage_end: float | None
    level: int | None
    first_box: float | None
    first_assessment: float | None
    decision: float | None
    departure: float | None
    destination: str | None
    displacements: int
    triage_wait: float | None
    box_wait: float | None
    doctor_wait: float | None
    initial_doctor_wait: float | None
    door_to_doctor: float | None

    @property
    def stay(self) -> float | None:
        """From the arrival to the departure; ``None`` if still inside."""
        return None if self.departure is None else self.departure - self.arrival


@dataclass(slots=True)
class _Episode:
    """What ``episode_table`` knows of one episode while reading the log."""

    episode_id: str
    arrival: float
    triage_start: float | None = None
    triage_end: float | None = None
    level: int | None = None
    first_box: float | None = None
    first_assessment: float | None = None
    decision: float | None = None
    departure: float | None = None
    destination: str | None = None
    displacements: int = 0
    box_wait: float = 0.0
    doctor_wait: float = 0.0
    initial_doctor_wait: float | None = None
    waiting_box_since: float | None = None
    waiting_doctor_since: float | None = None
    has_box: bool = False
    to_assess: bool = False  # an assessment is next once in a box

    def close_doctor_wait(self, now: float) -> None:
        if self.waiting_doctor_since is not None:
            self.doctor_wait += now - self.waiting_doctor_since
            self.waiting_doctor_since = None

    def record(self) -> EpisodeRecord:
        departed = self.departure is not None
        return EpisodeRecord(
            episode_id=self.episode_id,
            arrival=self.arrival,
            triage_start=self.triage_start,
            triage_end=self.triage_end,
            level=self.level,
            first_box=self.first_box,
            first_assessment=self.first_assessment,
            decision=self.decision,
            departure=self.departure,
            destination=self.destination,
            displacements=self.displacements,
            triage_wait=None if self.triage_start is None else self.triage_start - self.arrival,
            box_wait=self.box_wait if departed else None,
            doctor_wait=self.doctor_wait if departed else None,
            initial_doctor_wait=self.initial_doctor_wait,
            door_to_doctor=(
                None if self.first_assessment is None else self.first_assessment - self.arrival
            ),
        )


def episode_table(events: Sequence[Event]) -> tuple[EpisodeRecord, ...]:
    """One record per episode of the log, in arrival order.

    Args:
        events: The events in file order, such as ``MemorySink.events``.

    Returns:
        The records, in the order of the ``patient_arrived`` events.
    """
    episodes: dict[str, _Episode] = {}
    for e in events:
        if e.episode_id is None:
            continue
        now = e.sim_time
        if e.event_type == "patient_arrived":
            episodes[e.episode_id] = _Episode(e.episode_id, now)
            continue
        ep = episodes[e.episode_id]
        match e.event_type:
            case "triage_started":
                ep.triage_start = now
            case "triage_completed":
                ep.triage_end = now
                ep.level = e.payload["nivel"]
                ep.waiting_box_since = now
                ep.to_assess = True
            case "box_assigned":
                if ep.first_box is None:
                    ep.first_box = now
                if ep.waiting_box_since is not None:
                    ep.box_wait += now - ep.waiting_box_since
                    ep.waiting_box_since = None
                ep.has_box = True
                if ep.to_assess:
                    ep.waiting_doctor_since = now
            case "assessment_started":
                ep.close_doctor_wait(now)
                if ep.first_assessment is None:
                    ep.first_assessment = now
                    ep.initial_doctor_wait = ep.doctor_wait
                ep.to_assess = False
            case "assessment_ended" if e.payload["interrumpida"]:
                ep.to_assess = True  # resumed when back in a box
            case "test_resulted":
                ep.to_assess = True
                if ep.has_box:
                    ep.waiting_doctor_since = now
            case "patient_displaced":
                ep.close_doctor_wait(now)
                ep.has_box = False
                ep.displacements += 1
                ep.waiting_box_since = now
            case "disposition_decided":
                ep.decision = now
            case "patient_departed":
                ep.departure = now
                ep.destination = e.payload["destino"]
                ep.has_box = False
    return tuple(ep.record() for ep in episodes.values())


# --- Step curves ----------------------------------------------------------------------

# How each event changes each curve. A patient waits for a box after the triage
# and again after a displacement; the staff curves move by nueva - anterior.
_DELTAS: dict[str, dict[str, int]] = {
    "patient_arrived": {"census": 1, "waiting_triage": 1},
    "triage_started": {"waiting_triage": -1, "nurses_busy": 1},
    "triage_completed": {"nurses_busy": -1, "waiting_box": 1},
    "box_assigned": {"waiting_box": -1, "boxes_busy": 1},
    "patient_displaced": {"boxes_busy": -1, "waiting_box": 1},
    "assessment_started": {"doctors_busy": 1},
    "assessment_ended": {"doctors_busy": -1},
    "patient_departed": {"census": -1, "boxes_busy": -1},
}

_STAFF_CURVE = {"enfermeria_triaje": "nurses_staff", "medicos": "doctors_staff"}

CURVES = (
    "census",
    "waiting_triage",
    "waiting_box",
    "nurses_busy",
    "doctors_busy",
    "boxes_busy",
    "nurses_staff",
    "doctors_staff",
)
"""Names of the step curves, as keys of ``StepCurves.values``."""


@dataclass(frozen=True)
class StepCurves:
    """State of the center as step functions of time, derived from the log.

    Value ``i`` of each curve holds from ``times[i]`` until ``times[i + 1]``
    (the last one until ``horizon``), after every event of instant
    ``times[i]``. ``times`` is strictly increasing and starts at 0.

    Attributes:
        times: Instants at which some curve may change, from 0.
        values: One integer array per name of ``CURVES``.
        horizon: End of the log.
    """

    times: np.ndarray
    values: MappingProxyType
    horizon: float

    def __getitem__(self, name: str) -> np.ndarray:
        return self.values[name]

    @property
    def edges(self) -> np.ndarray:
        """Step edges, ``times`` followed by ``horizon``, as ``ax.stairs`` expects."""
        return np.append(self.times, self.horizon)

    def value(self, name: str, t: float) -> int:
        """Value of a curve at instant ``t``, after the events of ``t``."""
        return int(sample_step(self.times, self.values[name], [t])[0])

    def area(self, name: str, start: float, end: float) -> float:
        """Area of a curve over ``[start, end]``, within ``[0, horizon]``.

        The same sum as ``queueing.analysis.step_time_average``, without
        dividing by the length: the identity of utilization compares areas
        with a relative tolerance of 1e-9.
        """
        self._check_interval(start, end)
        t = self.times
        next_t = np.append(t[1:], self.horizon)
        covered = np.clip(np.minimum(next_t, end) - np.maximum(t, start), 0.0, None)
        return float(np.sum(covered * self.values[name]))

    def mean(self, name: str, start: float, end: float) -> float:
        """Time average of a curve over ``[start, end]``, within ``[0, horizon]``."""
        self._check_interval(start, end)
        return step_time_average(self.times, self.values[name], start, end)

    def _check_interval(self, start: float, end: float) -> None:
        if not 0 <= start < end <= self.horizon:
            raise ValueError(
                f"need 0 <= start < end <= horizon ({self.horizon}), got {start=} and {end=}"
            )


def step_curves(events: Sequence[Event], horizon: float) -> StepCurves:
    """Build the step curves of a log.

    The changes of each instant are added up and then accumulated in time
    order (as ``queueing.analysis.occupancy``), so the curves show the state
    after every event of an instant, not the passing states inside it.

    Args:
        events: The events in file order.
        horizon: End of the log, such as ``days * 1440``.

    Returns:
        The curves.

    Raises:
        ValueError: If an event happens after ``horizon``.
    """
    index = {name: i for i, name in enumerate(CURVES)}
    times = [0.0]  # the instants, with 0 so that every curve starts there
    changes: list[tuple[int, int, int]] = []  # (position in times, curve, delta)
    for e in events:
        if e.event_type == "staffing_changed":
            change = {
                _STAFF_CURVE[e.payload["recurso"]]: e.payload["nueva"] - e.payload["anterior"]
            }
        else:
            change = _DELTAS.get(e.event_type)
            if change is None:
                continue
        times.append(e.sim_time)
        changes.extend((len(times) - 1, index[name], delta) for name, delta in change.items())

    unique, group = np.unique(np.array(times), return_inverse=True)
    if unique[-1] > horizon:
        raise ValueError(f"an event happens at {unique[-1]}, after the horizon {horizon}")
    per_instant = np.zeros((unique.size, len(CURVES)), dtype=np.int64)
    if changes:
        position, curve, delta = np.array(changes).T
        np.add.at(per_instant, (group[position], curve), delta)
    cumulative = np.cumsum(per_instant, axis=0)
    values = MappingProxyType({name: cumulative[:, i] for name, i in index.items()})
    return StepCurves(times=unique, values=values, horizon=float(horizon))


# --- Metrics in the window ------------------------------------------------------------

MEASURES = (
    "triage_wait",
    "box_wait",
    "doctor_wait",
    "initial_doctor_wait",
    "door_to_doctor",
    "stay",
)
"""Per-episode values summarized by level: the waits and the stay."""

SHIFTS = ("morning", "afternoon", "night")
"""Shifts in the order of the configuration (``turnos.inicio``)."""

# Pool → (busy curve, staff curve or None for the boxes, whose capacity is fixed).
POOLS: Mapping[str, tuple[str, str | None]] = MappingProxyType(
    {
        "enfermeria_triaje": ("nurses_busy", "nurses_staff"),
        "medicos": ("doctors_busy", "doctors_staff"),
        "boxes": ("boxes_busy", None),
    }
)
"""Pools by their TOML key, as in ``staffing_changed``, with their curves."""


@dataclass(frozen=True, slots=True)
class LevelMetrics:
    """Waits and stay of the episodes of one level, or of all of them.

    Attributes:
        level: Triage level, or ``None`` for all the episodes.
        n: Episodes that arrived inside the window and departed.
        mean: Mean of each name of ``MEASURES``; ``None`` if ``n`` is 0.
        p90: 90th percentile of each, with linear interpolation
            (``numpy.percentile``); ``None`` if ``n`` is 0.
    """

    level: int | None
    n: int
    mean: Mapping[str, float | None]
    p90: Mapping[str, float | None]


@dataclass(frozen=True, slots=True)
class ShiftOccupancy:
    """Occupancy of one pool in one shift, inside the window.

    Attributes:
        pool: ``enfermeria_triaje``, ``medicos`` or ``boxes``.
        shift: ``morning``, ``afternoon`` or ``night``.
        busy_area: Area of the busy curve in the stretches of the shift.
        staff_area: Area of the staff in force in the same stretches; for the
            boxes, their number times the length.
    """

    pool: str
    shift: str
    busy_area: float
    staff_area: float

    @property
    def ratio(self) -> float:
        """Busy over staff. It may exceed 1 after the staff goes down: nobody
        is interrupted, the reservations wait for them to finish."""
        return self.busy_area / self.staff_area


@dataclass(frozen=True, slots=True)
class WindowMetrics:
    """Metrics of one run in the window ``[start, end]``.

    Attributes:
        start: Start of the window, in minutes (the end of the warm-up).
        end: End of the window, the horizon.
        arrivals: Episodes that arrived in ``[start, end)``.
        throughput: ``arrivals / (end - start)``, the observed rate in
            arrivals per minute.
        by_level: One ``LevelMetrics`` per level, 1 to 5.
        overall: The same for all the levels together.
        time_averages: Mean of each curve of ``CURVES`` over the window.
        occupancy: One ``ShiftOccupancy`` per pool and shift.
    """

    start: float
    end: float
    arrivals: int
    throughput: float
    by_level: tuple[LevelMetrics, ...]
    overall: LevelMetrics
    time_averages: Mapping[str, float]
    occupancy: tuple[ShiftOccupancy, ...]


def _check_window(start: float, end: float, horizon: float) -> None:
    if not 0 <= start < end <= horizon:
        raise ValueError(
            f"the window needs 0 <= start < end <= horizon ({horizon}), got {start=} and {end=}"
        )


def completed_in_window(
    table: Sequence[EpisodeRecord], start: float, end: float
) -> list[EpisodeRecord]:
    """Episodes that arrived in ``[start, end)`` and departed: the ones whose
    waits and stay are averaged, as the customers of ``mm1_metrics``."""
    return [e for e in table if start <= e.arrival < end and e.departure is not None]


def _level_metrics(level: int | None, episodes: Sequence[EpisodeRecord]) -> LevelMetrics:
    mean: dict[str, float | None] = {}
    p90: dict[str, float | None] = {}
    for name in MEASURES:
        values = np.array([getattr(e, name) for e in episodes], dtype=float)
        mean[name] = float(values.mean()) if values.size else None
        p90[name] = float(np.percentile(values, 90)) if values.size else None
    return LevelMetrics(level, len(episodes), MappingProxyType(mean), MappingProxyType(p90))


def _shift_stretches(starts: Sequence[int], start: float, end: float) -> list[tuple[float, float]]:
    """Cut ``[start, end]`` at every start of a shift; each stretch is in one shift."""
    first_day = math.floor(start / MINUTES_PER_DAY)
    last_day = math.ceil(end / MINUTES_PER_DAY)
    cuts = {
        float(day * MINUTES_PER_DAY + hour * MINUTES_PER_HOUR)
        for day in range(first_day, last_day + 1)
        for hour in starts
    }
    edges = sorted({start, end} | {t for t in cuts if start < t < end})
    return list(zip(edges[:-1], edges[1:], strict=True))


def _occupancy(
    curves: StepCurves, center: CenterConfig, start: float, end: float
) -> tuple[ShiftOccupancy, ...]:
    stretches = _shift_stretches(center.shift_starts, start, end)
    out = []
    for pool, (busy, staff) in POOLS.items():
        busy_area = dict.fromkeys(range(len(SHIFTS)), 0.0)
        staff_area = dict.fromkeys(range(len(SHIFTS)), 0.0)
        for a, b in stretches:
            shift = shift_at(center.shift_starts, a)
            busy_area[shift] += curves.area(busy, a, b)
            staff_area[shift] += (
                center.boxes * (b - a) if staff is None else curves.area(staff, a, b)
            )
        out += [
            ShiftOccupancy(pool, name, busy_area[i], staff_area[i]) for i, name in enumerate(SHIFTS)
        ]
    return tuple(out)


def window_metrics(
    table: Sequence[EpisodeRecord],
    curves: StepCurves,
    center: CenterConfig,
    start: float,
    end: float,
) -> WindowMetrics:
    """Metrics of a run in the window ``[start, end]``.

    Args:
        table: The episodes of the log, from ``episode_table``.
        curves: The curves of the same log, from ``step_curves``.
        center: The configuration of the run: shift starts and boxes.
        start: Start of the window in minutes, such as ``warmup_days * 1440``.
        end: End of the window, at most the horizon of the curves.

    Returns:
        The metrics.

    Raises:
        ValueError: If the window is not inside ``[0, horizon]`` or is empty.
    """
    _check_window(start, end, curves.horizon)
    done = completed_in_window(table, start, end)
    arrivals = sum(start <= e.arrival < end for e in table)
    return WindowMetrics(
        start=float(start),
        end=float(end),
        arrivals=arrivals,
        throughput=arrivals / (end - start),
        by_level=tuple(
            _level_metrics(level, [e for e in done if e.level == level])
            for level in range(1, N_LEVELS + 1)
        ),
        overall=_level_metrics(None, done),
        time_averages=MappingProxyType({name: curves.mean(name, start, end) for name in CURVES}),
        occupancy=_occupancy(curves, center, start, end),
    )


# --- Little's law -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LittleLaw:
    """Little's law ``L = λ·W`` on one run, in the window.

    Attributes:
        name: ``system``, ``triage_queue`` or ``box_queue``.
        l: Time average of the number inside (census or queue).
        lam: Observed arrival rate in the window (``throughput``).
        w: Mean time per episode inside, over the episodes that arrived in the
            window and departed. For the box queue, the total time waiting
            for a box, after the triage and after every displacement: Little
            holds with the total time a customer spends in a queue, however
            many times it enters it.
        relative_error: ``|L - λ·W| / L``; 0 if both are 0.
    """

    name: str
    # `l` is the standard queueing notation for the mean number in system.
    l: float  # noqa: E741
    lam: float
    w: float
    relative_error: float


# Law → (curve of the number inside, per-episode time inside).
_LITTLE = {
    "system": ("census", "stay"),
    "triage_queue": ("waiting_triage", "triage_wait"),
    "box_queue": ("waiting_box", "box_wait"),
}


def _relative_error(reference: float, other: float) -> float:
    if reference == other:
        return 0.0
    return abs(reference - other) / abs(reference) if reference else math.inf


def little_laws(
    table: Sequence[EpisodeRecord], curves: StepCurves, start: float, end: float
) -> tuple[LittleLaw, ...]:
    """Little's law for the whole system and for the triage and box queues.

    It is not exact on a finite window: the episodes inside at its edges are
    in ``L`` for part of their time and out of ``W``. Without anybody inside
    at the edges, ``L·T`` is exactly the sum of the times, so ``L = λ̂·W``.

    Raises:
        ValueError: If the window is not inside ``[0, horizon]`` or no
            episode arrived and departed inside it.
    """
    _check_window(start, end, curves.horizon)
    done = completed_in_window(table, start, end)
    if not done:
        raise ValueError("no episode arrived and departed inside the window")
    lam = sum(start <= e.arrival < end for e in table) / (end - start)
    out = []
    for name, (curve, measure) in _LITTLE.items():
        l = curves.mean(curve, start, end)  # noqa: E741
        w = float(np.mean([getattr(e, measure) for e in done]))
        out.append(LittleLaw(name, l, lam, w, _relative_error(l, lam * w)))
    return tuple(out)


# --- Identity of utilization ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UtilizationIdentity:
    """Two ways of computing the busy time of a pool in the window.

    Attributes:
        pool: ``enfermeria_triaje``, ``medicos`` or ``boxes``.
        curve_area: Area of the busy curve, from ``step_curves``.
        interval_area: Sum of the service intervals, each one clipped to the
            window, from ``busy_intervals``.
        relative_error: ``|curve - intervals| / curve``; 0 if both are 0.
    """

    pool: str
    curve_area: float
    interval_area: float
    relative_error: float


def busy_intervals(events: Sequence[Event], horizon: float) -> dict[str, list[tuple[float, float]]]:
    """The service intervals of each pool, in the order they end.

    - Triage nurses: ``triage_started`` to ``triage_completed``.
    - Doctors: ``assessment_started`` to ``assessment_ended``.
    - Boxes: ``box_assigned`` to ``patient_departed`` or ``patient_displaced``.

    Intervals still open at the end of the log end at ``horizon``.
    """
    opening = {"triage_started": "enfermeria_triaje", "assessment_started": "medicos"}
    closing = {"triage_completed": "enfermeria_triaje", "assessment_ended": "medicos"}
    out: dict[str, list[tuple[float, float]]] = {pool: [] for pool in POOLS}
    open_since: dict[tuple[str, str], float] = {}
    for e in events:
        episode, kind = e.episode_id, e.event_type
        if kind in opening:
            open_since[(opening[kind], episode)] = e.sim_time
        elif kind == "box_assigned":
            open_since[("boxes", episode)] = e.sim_time
        elif kind in closing or kind in ("patient_departed", "patient_displaced"):
            pool = closing.get(kind, "boxes")
            start = open_since.pop((pool, episode), None)
            if start is not None:
                out[pool].append((start, e.sim_time))
    for (pool, _), start in open_since.items():
        out[pool].append((start, float(horizon)))
    return out


def _time_in_window(start: float, end: float, window_start: float, window_end: float) -> float:
    """Length of ``[start, end]`` inside the window: the rule of ``mm1_metrics``.

    Written again because the one in ``queueing.mm1`` is private.
    """
    return max(0.0, min(end, window_end) - max(start, window_start))


def utilization_identities(
    events: Sequence[Event], curves: StepCurves, start: float, end: float
) -> tuple[UtilizationIdentity, ...]:
    """Area of each busy curve against the sum of the clipped service intervals.

    Both come from the same log by different paths: the curve adds up the
    changes of each instant, and the intervals pair each start with its end.
    They must agree up to rounding.
    """
    _check_window(start, end, curves.horizon)
    intervals = busy_intervals(events, curves.horizon)
    out = []
    for pool, (busy, _) in POOLS.items():
        curve_area = curves.area(busy, start, end)
        interval_area = math.fsum(_time_in_window(a, b, start, end) for a, b in intervals[pool])
        out.append(
            UtilizationIdentity(
                pool, curve_area, interval_area, _relative_error(curve_area, interval_area)
            )
        )
    return tuple(out)


# --- A whole run ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunAnalysis:
    """Everything derived from the log of one run.

    Attributes:
        table: One record per episode.
        curves: The step curves.
        metrics: The metrics in the window.
        little: Little's law, system and queues.
        utilization: The identity of utilization of each pool.
    """

    table: tuple[EpisodeRecord, ...]
    curves: StepCurves
    metrics: WindowMetrics
    little: tuple[LittleLaw, ...]
    utilization: tuple[UtilizationIdentity, ...]


def analyze_run(
    events: Sequence[Event], center: CenterConfig, days: int, warmup_days: int
) -> RunAnalysis:
    """Analyze a run in the window ``[warmup_days · 1440, days · 1440]``.

    The table and the curves are built once and shared by the rest.

    Args:
        events: The events of the run, in file order.
        center: The configuration of the run.
        days: Horizon in full days, as given to ``simulate_ed``.
        warmup_days: Warm-up in full days, such as ``EDResult.warmup_days``.
    """
    horizon = float(days * MINUTES_PER_DAY)
    start = float(warmup_days * MINUTES_PER_DAY)
    table = episode_table(events)
    curves = step_curves(events, horizon)
    return RunAnalysis(
        table=table,
        curves=curves,
        metrics=window_metrics(table, curves, center, start, horizon),
        little=little_laws(table, curves, start, horizon),
        utilization=utilization_identities(events, curves, start, horizon),
    )
