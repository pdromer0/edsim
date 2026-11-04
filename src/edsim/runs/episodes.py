"""Physical episode states, independent laboratory work and displacement instants."""

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from itertools import groupby

from edsim.engine.events import Event
from edsim.runs._location import EpisodeState, LocationState


@dataclass(frozen=True, slots=True)
class EpisodeSegment:
    """A positive half-open physical state interval in simulation minutes."""

    state: EpisodeState
    start: float
    end: float
    box: int | None


@dataclass(frozen=True, slots=True)
class TestBand:
    """Laboratory work from order to result or horizon, in simulation minutes."""

    start: float
    end: float
    completed: bool


@dataclass(frozen=True, slots=True)
class Displacement:
    """An observed displacement instant and the patient who took the box."""

    time: float
    box: int
    displaced_by: str


@dataclass(frozen=True, slots=True)
class EpisodeSegments:
    """One episode's location, independent tests and observed displacements."""

    episode_id: str
    segments: tuple[EpisodeSegment, ...]
    tests: TestBand | None
    displacements: tuple[Displacement, ...]


def episode_segments(events: Sequence[Event], horizon: float) -> EpisodeSegments:
    """Fold one episode in log order, grouping simultaneous transitions.

    Horizon and interval endpoints are simulation minutes. The input must start
    with this episode's arrival, contain no other episode, be time ordered and
    end no later than the finite horizon. Invalid inputs raise ValueError.
    Completed episodes end on departure; unfinished ones end at the horizon.
    A grant preempted before process resumption emits nothing and changes no
    observed location. Test results outside a box never end the box wait.
    """
    if isinstance(horizon, bool) or not math.isfinite(horizon) or horizon < 0:
        raise ValueError("horizon must be finite and non-negative")
    if not events or events[0].event_type != "patient_arrived":
        raise ValueError("episode events must start with patient_arrived")
    episode_id = events[0].episode_id
    if any(event.episode_id != episode_id for event in events):
        raise ValueError("events must belong to a single episode")
    if any(a.sim_time > b.sim_time for a, b in zip(events, events[1:], strict=False)):
        raise ValueError("episode events must be time ordered")
    if events[-1].sim_time > horizon:
        raise ValueError("episode events exceed horizon")
    state = LocationState()
    segments: list[EpisodeSegment] = []
    displacements = []
    test_start = test_end = None
    previous = events[0].sim_time

    def extend(end: float) -> None:
        if end <= previous:
            return
        current = EpisodeSegment(state.location(), previous, end, state.box)
        if segments and (segments[-1].state, segments[-1].box) == (current.state, current.box):
            segments[-1] = replace(segments[-1], end=end)
        else:
            segments.append(current)

    for now, simultaneous in groupby(events, key=lambda event: event.sim_time):
        extend(now)
        for event in simultaneous:
            state = state.apply(event)
            if event.event_type == "test_ordered":
                test_start = now
            elif event.event_type == "test_resulted":
                test_end = now
            elif event.event_type == "patient_displaced":
                displacements.append(
                    Displacement(now, event.payload["box"], event.payload["desalojado_por"])
                )
        previous = now
        if state.departed:
            break
    if not state.departed:
        extend(float(horizon))
    tests = (
        None
        if test_start is None
        else TestBand(
            test_start, float(horizon) if test_end is None else test_end, test_end is not None
        )
    )
    return EpisodeSegments(episode_id, tuple(segments), tests, tuple(displacements))
