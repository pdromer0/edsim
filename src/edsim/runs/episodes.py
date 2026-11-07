"""Physical episode states, independent laboratory work, displacements and observed profiles."""

import math
from bisect import bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import groupby
from types import MappingProxyType

from edsim.engine.events import Event
from edsim.profiles.config import Population
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


# --- The observable profile of each episode (task 4.8a) ---------------------------------


@dataclass(frozen=True, slots=True)
class ObservedProfile:
    """What the log of a clinical run says of a patient, never its ground truth.

    Each value is None until its event happens: ``arrival_mode`` (``medio``)
    comes with ``patient_arrived``, ``age`` and ``sex`` with
    ``patient_registered``, ``reason`` (``motivo``) with ``triage_completed``
    and ``tests`` (``pruebas``, in the order of ``TEST_TYPES``) with
    ``test_ordered``; ``tests`` is empty without a round. ``age_band`` is the
    index of the band of the age, with the band limits of the run's profiles,
    which are public configuration, not truth.
    """

    episode_id: str
    age: int | None = None
    age_band: int | None = None
    sex: str | None = None
    arrival_mode: str | None = None
    reason: str | None = None
    tests: tuple[str, ...] = ()


def _band(age: int, population: Population) -> int:
    band = bisect_right(population.band_starts, age) - 1
    if band < 0:
        raise ValueError(f"age {age} is below the first band ({population.band_starts[0]})")
    return band


def observed_profiles(
    events: Iterable[Event], population: Population
) -> Mapping[str, ObservedProfile]:
    """The observable profile of every episode of a clinical log, by episode, read-only.

    Read from ``patient_arrived``, ``patient_registered``, ``triage_completed``
    and ``test_ordered``, in log order; the other events are ignored.

    Raises:
        ValueError: If an age is below the first band of ``population``.
    """
    profiles: dict[str, ObservedProfile] = {}
    for event in events:
        episode = event.episode_id
        match event.event_type:
            case "patient_arrived":
                profiles[episode] = ObservedProfile(episode, arrival_mode=event.payload["medio"])
            case "patient_registered":
                age = event.payload["edad"]
                profiles[episode] = replace(
                    profiles[episode],
                    age=age,
                    age_band=_band(age, population),
                    sex=event.payload["sexo"],
                )
            case "triage_completed":
                profiles[episode] = replace(profiles[episode], reason=event.payload["motivo"])
            case "test_ordered":
                profiles[episode] = replace(
                    profiles[episode], tests=tuple(event.payload["pruebas"])
                )
    return MappingProxyType(profiles)
