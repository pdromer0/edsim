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

- waiting for a box: from ``triage_completed``, from every
  ``patient_displaced`` and, after the results room, from ``test_resulted``
  to the next ``box_assigned``;
- waiting for a doctor: holding a box with an assessment to do, from
  ``box_assigned`` or ``test_resulted`` to ``assessment_started`` or
  ``patient_displaced``.

**Results room** (task 4.6a). ``box_released`` frees the box (``boxes_busy``
goes down) and the patient waits for its results outside, still in the
census; with the results it joins the box queue (``waiting_box``) until its
``box_assigned``. ``box_wait`` stays the total wait for a box, so Little's law
of the box queue still holds; ``initial_box_wait`` and ``results_box_wait``
split out the first wait and the one after the room.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from edsim.arrivals.rate import MINUTES_PER_DAY
from edsim.engine.center import N_LEVELS, CenterConfig
from edsim.engine.events import DOOR, LWBS_WAITS, Event
from edsim.engine.shifts import MINUTES_PER_HOUR, shift_at
from edsim.profiles.config import DESTINATIONS
from edsim.queueing.analysis import sample_step, step_time_average
from edsim.queueing.mm1 import time_in_window

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
        box_wait: Total time waiting for a box: after the triage, after each
            displacement and after the results room. Final only at the
            departure, ``None`` before.
        doctor_wait: Total time holding a box and waiting for a doctor, for
            the first assessment, the reassessment and the resumptions after
            a displacement. Final only at the departure, ``None`` before.
        initial_doctor_wait: Time holding a box and waiting for a doctor
            before the first ``assessment_started``, from the first
            ``box_assigned`` on.
        door_to_doctor: From the arrival to the first ``assessment_started``
            (clock A, comparable with the TPAM of the SAS).
        triage_start_to_doctor: From ``triage_started`` to the first
            ``assessment_started`` (clock B, comparable with the TEA of the SAS).
        classified_to_doctor: From ``triage_completed``, when the level is
            assigned, to the first ``assessment_started`` (clock C, the one of
            the Manchester compliance; docs/specs/hito-4.md).
        initial_box_wait: From ``triage_completed`` to the first
            ``box_assigned``; ``None`` until it happens (task 4.6a).
        results_box_wait: Time waiting for a box after the results room, from
            ``test_resulted`` to the ``box_assigned`` of the reassessment; 0 if
            the patient did not wait outside. Final only at the departure,
            ``None`` before (task 4.6a).
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
    triage_start_to_doctor: float | None
    classified_to_doctor: float | None
    initial_box_wait: float | None
    results_box_wait: float | None

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
    initial_box_wait: float | None = None
    results_box_wait: float = 0.0
    in_room: bool = False  # waiting for the results outside the box
    back_from_room: bool = False  # waiting for a box after the results room

    def close_doctor_wait(self, now: float) -> None:
        if self.waiting_doctor_since is not None:
            self.doctor_wait += now - self.waiting_doctor_since
            self.waiting_doctor_since = None

    def since(self, start: float | None) -> float | None:
        """From ``start`` to the first assessment; ``None`` until it happens."""
        if self.first_assessment is None or start is None:
            return None
        return self.first_assessment - start

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
            door_to_doctor=self.since(self.arrival),
            triage_start_to_doctor=self.since(self.triage_start),
            classified_to_doctor=self.since(self.triage_end),
            initial_box_wait=self.initial_box_wait,
            results_box_wait=self.results_box_wait if departed else None,
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
                if ep.waiting_box_since is not None:
                    wait = now - ep.waiting_box_since
                    ep.box_wait += wait
                    if ep.first_box is None:
                        ep.initial_box_wait = wait
                    if ep.back_from_room:
                        ep.results_box_wait += wait
                    ep.waiting_box_since = None
                if ep.first_box is None:
                    ep.first_box = now
                ep.back_from_room = False
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
                elif ep.in_room:
                    ep.in_room = False
                    ep.back_from_room = True
                    ep.waiting_box_since = now
            case "box_released":
                ep.close_doctor_wait(now)
                ep.has_box = False
                ep.in_room = True
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


# --- Outcome counts (milestone 5) ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OutcomeCounts:
    """How the episodes that arrive in a window end, in a log of version 4 (task 5.3).

    A count, not a metric: the means and the compliance with the abandonment
    (censoring, H5-8) are task 5.4. Each episode is counted once, by its
    terminal event, also if it comes after the window.

    Attributes:
        arrivals: Episodes that arrive in ``[start, end)``.
        left: Of them, those that leave without being seen, by ``espera``, in
            the order of ``LWBS_WAITS`` (``triaje``, ``box``, ``medico``).
        departed: Those that depart, by destination, in the order of
            ``DESTINATIONS`` (``alta``, ``ingreso``, ``traslado``, ``exitus``).
        inside: Those still inside at the end of the log.
    """

    arrivals: int
    left: tuple[int, ...]
    departed: tuple[int, ...]
    inside: int

    @property
    def left_total(self) -> int:
        """Patients who left without being seen."""
        return sum(self.left)


def outcome_counts(events: Sequence[Event], start: float, end: float) -> OutcomeCounts:
    """Count the arrivals of ``[start, end)``, their abandonments and their destinations.

    Args:
        events: The events of the run, in file order; ``patient_left_wbs``
            exists only in version 4, so with an older log nobody leaves.
        start: Start of the window, in minutes.
        end: End of the window, in minutes.
    """
    arrived: set[str] = set()
    left = dict.fromkeys(LWBS_WAITS, 0)
    departed = dict.fromkeys(DESTINATIONS, 0)
    for e in events:
        match e.event_type:
            case "patient_arrived" if start <= e.sim_time < end:
                arrived.add(e.episode_id)
            case "patient_left_wbs" if e.episode_id in arrived:
                left[e.payload["espera"]] += 1
            case "patient_departed" if e.episode_id in arrived:
                departed[e.payload["destino"]] += 1
    finished = sum(left.values()) + sum(departed.values())
    return OutcomeCounts(
        arrivals=len(arrived),
        left=tuple(left.values()),
        departed=tuple(departed.values()),
        inside=len(arrived) - finished,
    )


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

# A triage at the door (a level 1) leaves the triage queue and joins the box
# queue, but takes no nurse.
_DOOR_DELTAS: dict[str, dict[str, int]] = {
    "triage_started": {"waiting_triage": -1},
    "triage_completed": {"waiting_box": 1},
}

# Results room (task 4.6a): box_released frees the box, and the results of a
# patient in the room put it back in the box queue. It stays in the census.
_ROOM_DELTAS: dict[str, dict[str, int]] = {
    "box_released": {"boxes_busy": -1},
    "test_resulted": {"waiting_box": 1},
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
    at_the_door: set[str] = set()
    in_room: set[str] = set()
    for e in events:
        if e.event_type == "box_released":
            in_room.add(e.episode_id)
            change = _ROOM_DELTAS["box_released"]
        elif e.event_type == "test_resulted" and e.episode_id in in_room:
            in_room.discard(e.episode_id)
            change = _ROOM_DELTAS["test_resulted"]
        elif e.event_type == "staffing_changed":
            change = {
                _STAFF_CURVE[e.payload["recurso"]]: e.payload["nueva"] - e.payload["anterior"]
            }
        elif e.event_type == "triage_started" and e.payload["circuito"] == DOOR:
            at_the_door.add(e.episode_id)
            change = _DOOR_DELTAS["triage_started"]
        elif e.event_type == "triage_completed" and e.episode_id in at_the_door:
            at_the_door.discard(e.episode_id)
            change = _DOOR_DELTAS["triage_completed"]
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
    "initial_box_wait",
    "results_box_wait",
    "doctor_wait",
    "initial_doctor_wait",
    "door_to_doctor",
    "triage_start_to_doctor",
    "classified_to_doctor",
    "stay",
)
"""Per-episode values summarized by level: the waits, the three clocks to the
doctor and the stay."""

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

    - Triage nurses: ``triage_started`` to ``triage_completed``, except the
      triages at the door, which take no nurse.
    - Doctors: ``assessment_started`` to ``assessment_ended``.
    - Boxes: ``box_assigned`` to ``patient_departed``, ``patient_displaced``
      or ``box_released``.

    Intervals still open at the end of the log end at ``horizon``.
    """
    opening = {"triage_started": "enfermeria_triaje", "assessment_started": "medicos"}
    closing = {"triage_completed": "enfermeria_triaje", "assessment_ended": "medicos"}
    out: dict[str, list[tuple[float, float]]] = {pool: [] for pool in POOLS}
    open_since: dict[tuple[str, str], float] = {}
    for e in events:
        episode, kind = e.episode_id, e.event_type
        if kind == "triage_started" and e.payload["circuito"] == DOOR:
            continue  # its triage_completed then finds nothing open
        if kind in opening:
            open_since[(opening[kind], episode)] = e.sim_time
        elif kind == "box_assigned":
            open_since[("boxes", episode)] = e.sim_time
        elif kind in closing or kind in ("patient_departed", "patient_displaced", "box_released"):
            pool = closing.get(kind, "boxes")
            start = open_since.pop((pool, episode), None)
            if start is not None:
                out[pool].append((start, e.sim_time))
    for (pool, _), start in open_since.items():
        out[pool].append((start, float(horizon)))
    return out


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
        interval_area = math.fsum(time_in_window(a, b, start, end) for a, b in intervals[pool])
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


# --- By day and by hour of the clock ------------------------------------------------------

HOURS_PER_DAY = 24


def _check_whole_days(curves: StepCurves, start: float, end: float) -> None:
    _check_window(start, end, curves.horizon)
    if start % MINUTES_PER_DAY or end % MINUTES_PER_DAY:
        raise ValueError(f"start and end must be whole days in minutes, got {start=} and {end=}")


def hourly_means_by_day(curves: StepCurves, name: str, start: float, end: float) -> np.ndarray:
    """Mean of a curve in each hour of each day of ``[start, end]``.

    Exact: the area of a step function up to any instant is the linear
    interpolation of its cumulative area at the steps.

    Args:
        curves: The step curves of a log.
        name: A name of ``CURVES``.
        start: Start, a whole day in minutes.
        end: End, a whole day in minutes, at most the horizon.

    Returns:
        Shape ``(days, 24)``: row ``d`` is day ``start / 1440 + d``, column
        ``h`` the hour ``h`` of the clock.

    Raises:
        ValueError: If the window is not inside ``[0, horizon]`` or its ends
            are not whole days.
    """
    _check_whole_days(curves, start, end)
    edges = curves.edges
    cumulative = np.concatenate([[0.0], np.cumsum(np.diff(edges) * curves[name])])
    hours = np.arange(start, end + 1, MINUTES_PER_HOUR, dtype=float)
    area = np.diff(np.interp(hours, edges, cumulative))
    return (area / MINUTES_PER_HOUR).reshape(-1, HOURS_PER_DAY)


def daily_means(curves: StepCurves, name: str, first_day: int, end_day: int) -> np.ndarray:
    """Time average of a curve over each day of ``[first_day, end_day)``.

    Raises:
        ValueError: If the days are not inside the log.
    """
    _check_window(first_day * MINUTES_PER_DAY, end_day * MINUTES_PER_DAY, curves.horizon)
    return np.array(
        [
            curves.mean(name, d * MINUTES_PER_DAY, (d + 1) * MINUTES_PER_DAY)
            for d in range(first_day, end_day)
        ]
    )


# --- Paired runs ----------------------------------------------------------------------------


@dataclass(frozen=True)
class PairedWaits:
    """One measure of the same episodes in two runs with the same seed.

    Attributes:
        measure: A name of ``MEASURES``.
        episode_ids: The episodes paired, in arrival order.
        levels: Their triage level.
        arrivals: Their arrival, in minutes.
        base: The measure in the first run.
        other: The measure in the second run.
    """

    measure: str
    episode_ids: tuple[str, ...]
    levels: np.ndarray
    arrivals: np.ndarray
    base: np.ndarray
    other: np.ndarray

    @property
    def difference(self) -> np.ndarray:
        """``other - base``, episode by episode."""
        return self.other - self.base


def paired_waits(
    base: Sequence[EpisodeRecord],
    other: Sequence[EpisodeRecord],
    measure: str,
    start: float,
    end: float,
) -> PairedWaits:
    """Pair, episode by episode, one measure of two runs with the same patients.

    With the same seed every patient arrives at the same instant and draws
    the same values (common random numbers): only the waits change. The
    episodes are paired by ``episode_id``, among those that arrive in
    ``[start, end)`` and depart in both runs (``completed_in_window``): an
    episode still inside in one run is left out of both.

    Args:
        base: The episodes of the first run, from ``episode_table``.
        other: Those of the second run.
        measure: A name of ``MEASURES``.
        start: Start of the window, in minutes.
        end: End of the window.

    Raises:
        ValueError: If ``measure`` is unknown, or an episode arrives at
            different instants in both runs: they are not the same patients.
    """
    if measure not in MEASURES:
        raise ValueError(f"measure must be one of {MEASURES}, got {measure!r}")
    other_by_id = {e.episode_id: e for e in completed_in_window(other, start, end)}
    arrival_of = {e.episode_id: e.arrival for e in other}
    pairs = []
    for b in completed_in_window(base, start, end):
        if b.episode_id in arrival_of and arrival_of[b.episode_id] != b.arrival:
            raise ValueError(
                f"{b.episode_id} arrives at {b.arrival} and at {arrival_of[b.episode_id]}:"
                " the runs do not have the same patients"
            )
        o = other_by_id.get(b.episode_id)
        if o is not None:
            pairs.append((b, o))
    return PairedWaits(
        measure=measure,
        episode_ids=tuple(b.episode_id for b, _ in pairs),
        levels=np.array([b.level for b, _ in pairs], dtype=np.int64),
        arrivals=np.array([b.arrival for b, _ in pairs], dtype=float),
        base=np.array([getattr(b, measure) for b, _ in pairs], dtype=float),
        other=np.array([getattr(o, measure) for _, o in pairs], dtype=float),
    )
