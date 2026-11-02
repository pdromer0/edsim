"""Timelines from the event log: the stay of one episode and the Gantt of a stretch.

Like ``analysis.py``, these are pure functions that fold the events in file
order (event sourcing); the notebook only draws what they return.

- ``episode_timeline``: the states an episode goes through, as segments of
  time, from its events alone.
- ``gantt``: who holds each box and when, and the assessments spread over
  doctor lanes. The pools are anonymous, so the log does not say which doctor
  did each assessment: the lanes are the smallest set of rows in which no two
  assessments overlap, not real doctors. Sorting the assessments by start and
  giving each one the lowest free lane uses exactly as many lanes as the most
  assessments at once (the greedy algorithm of interval partitioning).
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from edsim.engine.events import Event

STATES = (
    "waiting_triage",
    "triage",
    "waiting_box",
    "waiting_doctor",
    "assessment",
    "tests",
    "reassessment",
)
"""States of ``episode_timeline``, in the order of a stay."""


@dataclass(frozen=True, slots=True)
class Segment:
    """One state of an episode, from ``start`` to ``end``.

    Attributes:
        state: A name of ``STATES``.
        start: Start, in minutes of simulation.
        end: End; the departure, the next state or the horizon.
    """

    state: str
    start: float
    end: float


@dataclass(slots=True)
class _Flags:
    """What is known of an episode after the events of one instant."""

    triage_started: bool = False
    triaged: bool = False
    has_box: bool = False
    assessment: str | None = None  # tipo of the assessment in progress
    tests_pending: bool = False
    departed: bool = False

    def apply(self, e: Event) -> None:
        match e.event_type:
            case "triage_started":
                self.triage_started = True
            case "triage_completed":
                self.triaged = True
            case "box_assigned":
                self.has_box = True
            case "assessment_started":
                self.assessment = e.payload["tipo"]
            case "assessment_ended":
                self.assessment = None
            case "test_ordered":
                self.tests_pending = True
            case "test_resulted":
                self.tests_pending = False
            case "patient_displaced":
                self.has_box = False
            case "patient_departed":
                self.departed = True
                self.has_box = False

    def state(self) -> str:
        if not self.triage_started:
            return "waiting_triage"
        if not self.triaged:
            return "triage"
        if not self.has_box:
            # Also while the tests run with the patient out of its box.
            return "waiting_box"
        if self.assessment is not None:
            return "assessment" if self.assessment == "inicial" else "reassessment"
        if self.tests_pending:
            return "tests"
        return "waiting_doctor"


def episode_timeline(
    events: Sequence[Event], episode_id: str, horizon: float
) -> tuple[Segment, ...]:
    """The states of one episode, as consecutive segments of time.

    The state of each stretch is the one after every event of the episode at
    its start; stretches of length 0 (such as getting a box and a doctor in
    the same instant) do not appear, and two stretches in a row with the same
    state are joined (results that arrive while waiting for a box). Waiting
    for a box after a displacement is ``waiting_box`` again, whether or not
    the tests are still running.

    Args:
        events: The events in file order.
        episode_id: Such as ``EP-000137``.
        horizon: End of the log: the last segment of a patient still inside
            ends here.

    Returns:
        The segments, from the arrival to the departure or the horizon.

    Raises:
        ValueError: If the episode has no events in the log.
    """
    own = [e for e in events if e.episode_id == episode_id]
    if not own:
        raise ValueError(f"no events of {episode_id} in the log")
    flags = _Flags()
    segments: list[Segment] = []
    i = 0
    while i < len(own):
        now = own[i].sim_time
        while i < len(own) and own[i].sim_time == now:
            flags.apply(own[i])
            i += 1
        if flags.departed:
            break
        end = own[i].sim_time if i < len(own) else float(horizon)
        state = flags.state()
        if segments and segments[-1].state == state and segments[-1].end == now:
            segments[-1] = Segment(state, segments[-1].start, end)
        else:
            segments.append(Segment(state, now, end))
    return tuple(s for s in segments if s.end > s.start)


# --- Gantt --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Bar:
    """One stretch in which a box or a doctor is held by an episode.

    Attributes:
        start: Start, clipped to the stretch of the Gantt.
        end: End, clipped likewise.
        episode_id: The episode.
        level: Its triage level.
        tipo: For an assessment, ``inicial`` or ``reevaluacion``; ``None`` for
            a box.
        interrupted: For an assessment, whether a displacement cut it.
    """

    start: float
    end: float
    episode_id: str
    level: int
    tipo: str | None = None
    interrupted: bool = False


@dataclass(frozen=True, slots=True)
class Gantt:
    """The boxes and the doctor lanes of a stretch ``[start, end]``.

    Attributes:
        start: Start of the stretch, in minutes.
        end: End of the stretch.
        boxes: The bars of each box number held in the stretch, in time order.
        doctors: One tuple of bars per doctor lane, in time order; lane ``i``
            of the list is row ``i``.
    """

    start: float
    end: float
    boxes: Mapping[int, tuple[Bar, ...]]
    doctors: tuple[tuple[Bar, ...], ...]


def _clip(start: float, end: float, window: tuple[float, float]) -> tuple[float, float] | None:
    a, b = max(start, window[0]), min(end, window[1])
    return (a, b) if a < b else None


def gantt(events: Sequence[Event], start: float, end: float) -> Gantt:
    """Who holds each box and the assessments in doctor lanes, in ``[start, end]``.

    A box is held from ``box_assigned`` to ``patient_departed`` or
    ``patient_displaced``; a doctor, from ``assessment_started`` to
    ``assessment_ended``. Holds still open at the end of the log last until
    ``end``. Every bar is clipped to the stretch, and those outside it are
    left out.

    The assessments are sorted by their clipped start and, at the same
    instant, by the order in which they end in the file; each goes to the lowest lane whose last
    bar ends at or before its start. Bars that touch (one ends at t, another
    starts at t) can share a lane, as the step curves count them: the number
    of lanes is the largest value of ``doctors_busy`` in the stretch.

    Args:
        events: The events in file order.
        start: Start of the stretch, in minutes.
        end: End of the stretch, greater than ``start``.

    Raises:
        ValueError: If ``end <= start``.
    """
    if not end > start:
        raise ValueError(f"need start < end, got {start=} and {end=}")
    window = (float(start), float(end))
    level: dict[str, int] = {}
    open_box: dict[str, tuple[int, float]] = {}
    open_doctor: dict[str, tuple[float, str]] = {}
    boxes: dict[int, list[Bar]] = {}
    assessments: list[Bar] = []

    def close_box(episode: str, t: float) -> None:
        box, since = open_box.pop(episode)
        clipped = _clip(since, t, window)
        if clipped is not None:
            boxes.setdefault(box, []).append(Bar(*clipped, episode, level[episode]))

    def close_doctor(episode: str, t: float, interrupted: bool) -> None:
        since, tipo = open_doctor.pop(episode)
        clipped = _clip(since, t, window)
        if clipped is not None:
            assessments.append(Bar(*clipped, episode, level[episode], tipo, interrupted))

    for e in events:
        episode = e.episode_id
        match e.event_type:
            case "triage_completed":
                level[episode] = e.payload["nivel"]
            case "box_assigned":
                open_box[episode] = (e.payload["box"], e.sim_time)
            case "patient_displaced" | "patient_departed":
                close_box(episode, e.sim_time)
            case "assessment_started":
                open_doctor[episode] = (e.sim_time, e.payload["tipo"])
            case "assessment_ended":
                close_doctor(episode, e.sim_time, e.payload["interrumpida"])
    for episode in list(open_box):
        close_box(episode, math.inf)
    for episode in list(open_doctor):
        close_doctor(episode, math.inf, False)

    # Python's sort is stable: at the same start, the order in which they ended
    # in the file, which is deterministic.
    lanes: list[list[Bar]] = []
    for bar in sorted(assessments, key=lambda b: b.start):
        lane = next((lane for lane in lanes if lane[-1].end <= bar.start), None)
        if lane is None:
            lanes.append([bar])
        else:
            lane.append(bar)

    return Gantt(
        start=window[0],
        end=window[1],
        boxes=MappingProxyType(
            {box: tuple(sorted(bars, key=lambda b: b.start)) for box, bars in sorted(boxes.items())}
        ),
        doctors=tuple(tuple(lane) for lane in lanes),
    )
