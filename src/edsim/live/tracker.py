"""What a consumer of a live run keeps: the census in real time, without Kafka (task 6.6).

A ``LiveTracker`` is fed the same way by a live run in memory (it is a ``LiveSink``, so
``run_prepared`` can publish straight into it) and by the reading of Kafka
(``edsim.live.kafka.read_run``, which adds each event with its topic, partition, offset
and broker timestamp). It keeps:

- **The state of each episode**, with the ``LocationState`` reducer of the Replay of the
  app (``edsim.runs._location``): the open episodes and how many are in each location, now
  or at any simulated instant. The census and the live stream go through the same code
  (H6-11, event sourcing). With version 4 (task 5.4, H5-11), ``waiting_bed`` with the mark
  of the hallway, and the abandonment as a closing counted apart from the departures; an
  episode is closed by any event of ``TERMINAL_EVENTS`` of its version.
- **Idempotence** (H6-8): an ``event_id`` already seen is counted as repeated and changes
  nothing. With at-least-once delivery, a repeated event is normal, not an error.
- **The end**: the ``fin`` of ``ed.runs`` says how many events were published; the run is
  complete when that many distinct events have arrived. The ``fin`` travels in another
  topic and can arrive before the last events.
- **Order and partitions**: events received by partition; the order by ``sim_time``
  within each episode, which the key guarantees (``episode_order_errors`` must be 0); and
  the inversions between partitions, which nothing forbids.
- **Latency** from the broker to the consumer: the time of reception minus the
  ``LogAppendTime`` timestamp, the arrival time at the broker (H6-9).

No Kafka client. ``LocationState`` is reused as it is, from ``edsim.runs._location``, so
importing this module loads the ``edsim.runs`` package (and SimPy with it), as the app does.
"""

import math
import statistics
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import get_args

from edsim.engine.events import TERMINAL_EVENTS, Event
from edsim.live.directo import RunEnd, RunStart
from edsim.runs._location import EpisodeState, LocationState

LOCATIONS: tuple[str, ...] = get_args(EpisodeState)
"""The locations of ``LocationState.location()``, in the order of a patient's way."""


@dataclass(frozen=True, slots=True)
class ReceivedEvent:
    """An event as a consumer receives it.

    Attributes:
        event: The event.
        topic: Topic it was read from; ``None`` in memory.
        partition: Partition it was read from; ``None`` in memory.
        offset: Its offset in the partition; ``None`` in memory.
        broker_ms: The ``LogAppendTime`` timestamp, in milliseconds since the epoch;
            ``None`` in memory or with another type of timestamp.
        received: When the consumer got it, in seconds since the epoch (``time.time()``).
    """

    event: Event
    topic: str | None = None
    partition: int | None = None
    offset: int | None = None
    broker_ms: int | None = None
    received: float | None = None


@dataclass(frozen=True, slots=True)
class Occupancy:
    """How many open episodes there are in each location.

    Attributes:
        at: The simulated instant (after every event at it or before); ``None`` for now.
        open: Open episodes.
        by_location: Open episodes by location, every one of ``LOCATIONS``.
        results_room: Those of them in the results room (out of their box between their
            two box stays): a subset, not one more location.
        hallway: Those of them waiting for a bed in the hallway, after a displacement
            (version 4): a subset of ``waiting_bed``, not one more location.
        departed: Episodes closed by ``patient_departed`` until then.
        left: Episodes closed by ``patient_left_wbs`` until then: the abandonment,
            counted apart (H5-11).
    """

    at: float | None
    open: int
    by_location: Mapping[str, int]
    results_room: int
    hallway: int = 0
    departed: int = 0
    left: int = 0


@dataclass(frozen=True, slots=True)
class LatencySummary:
    """Latency from the broker to the consumer, in milliseconds."""

    count: int
    median_ms: float
    p95_ms: float
    max_ms: float


def fold_states(events: Iterable[Event]) -> dict[str, LocationState]:
    """The state of each episode after its events, in order: the reference of the batch."""
    states: dict[str, LocationState] = {}
    for event in events:
        if event.episode_id is not None:
            states[event.episode_id] = states.get(event.episode_id, LocationState()).apply(event)
    return states


def _occupancy(
    at: float | None, states: Mapping[str, LocationState], closed: set[str]
) -> Occupancy:
    still_open = [state for episode, state in states.items() if episode not in closed]
    ended = [states[episode] for episode in closed]
    counts = Counter(state.location() for state in still_open)
    return Occupancy(
        at=at,
        open=len(still_open),
        by_location=MappingProxyType({place: counts.get(place, 0) for place in LOCATIONS}),
        results_room=sum(state.results_room for state in still_open),
        hallway=sum(state.hallway for state in still_open),
        departed=sum(state.departed for state in ended),
        left=sum(state.left for state in ended),
    )


def _terminal(event: Event) -> bool:
    return event.event_type in TERMINAL_EVENTS[event.schema_version]


class LiveTracker:
    """The state a consumer derives from the events of one run (see the module).

    It is a ``LiveSink`` (``start``, ``write`` and ``end``), and ``add`` takes an event with
    the details of Kafka.

    Args:
        run_id: The run; if ``None``, the one of the first message or event.

    Raises:
        ValueError: From ``start``, ``end``, ``write`` or ``add``, with a message or an
            event of another run.

    Attributes:
        run_start: The ``inicio``, once received.
        run_end: The ``fin``, once received.
        duplicates: Events received again (an ``event_id`` already seen).
        states: The state of each episode seen.
        staff: The staff in force of each resource (``staffing_changed``).
        by_partition: Distinct events received by ``(topic, partition)``.
        episode_order_errors: Events with a ``sim_time`` less than the previous one of
            their episode; the key of Kafka makes it 0.
        cross_partition_inversions: Events with a ``sim_time`` less than the highest one
            already received in another partition.
        latencies_ms: Reception time minus broker timestamp, of each distinct event that
            has both.
    """

    def __init__(self, run_id: str | None = None) -> None:
        self.run_id = run_id
        self.run_start: RunStart | None = None
        self.run_end: RunEnd | None = None
        self.duplicates = 0
        self.states: dict[str, LocationState] = {}
        self.staff: dict[str, int] = {}
        self.by_partition: Counter[tuple[str | None, int | None]] = Counter()
        self.episode_order_errors = 0
        self.cross_partition_inversions = 0
        self.latencies_ms: list[float] = []
        self._seen: set[str] = set()
        self._events: list[Event] = []  # distinct, in order of reception
        self._closed: set[str] = set()
        self._last_time: dict[str, float] = {}
        self._partition_max: dict[tuple[str | None, int | None], float] = {}

    # -- LiveSink ---------------------------------------------------------------------

    def start(self, message: RunStart) -> None:
        self._check_run("RunStart", message.info.run_id)
        self.run_start = message

    def write(self, event: Event) -> None:
        self.add(ReceivedEvent(event))

    def end(self, message: RunEnd) -> None:
        self._check_run("RunEnd", message.run_id)
        self.run_end = message

    # -- Events -----------------------------------------------------------------------

    def add(self, received: ReceivedEvent) -> bool:
        """Take one event; ``False`` if its ``event_id`` was already seen (nothing changes)."""
        event = received.event
        self._check_run("event", event.run_id)
        if event.event_id in self._seen:
            self.duplicates += 1
            return False
        self._seen.add(event.event_id)
        self._events.append(event)

        key = (received.topic, received.partition)
        self.by_partition[key] += 1
        others = (t for k, t in self._partition_max.items() if k != key)
        if event.sim_time < max(others, default=-math.inf):
            self.cross_partition_inversions += 1
        self._partition_max[key] = max(self._partition_max.get(key, -math.inf), event.sim_time)

        episode = event.episode_id
        if episode is not None:
            last = self._last_time.get(episode)
            if last is not None and event.sim_time < last:
                self.episode_order_errors += 1
            self._last_time[episode] = event.sim_time
            self.states[episode] = self.states.get(episode, LocationState()).apply(event)
            if _terminal(event):
                self._closed.add(episode)
        elif event.event_type == "staffing_changed":
            self.staff[event.payload["recurso"]] = event.payload["nueva"]

        if received.broker_ms is not None and received.received is not None:
            self.latencies_ms.append(received.received * 1000 - received.broker_ms)
        return True

    # -- What it knows ----------------------------------------------------------------

    @property
    def distinct(self) -> int:
        """Distinct events received."""
        return len(self._seen)

    @property
    def events(self) -> list[Event]:
        """The distinct events, in the order they were received."""
        return list(self._events)

    @property
    def complete(self) -> bool:
        """Whether the ``fin`` has arrived and as many distinct events as it published."""
        return self.run_end is not None and self.distinct >= self.run_end.published

    @property
    def missing(self) -> int | None:
        """Events published and not received yet; ``None`` before the ``fin``."""
        if self.run_end is None:
            return None
        return max(self.run_end.published - self.distinct, 0)

    def open_episodes(self) -> frozenset[str]:
        """The episodes seen without their terminal event."""
        return frozenset(self.states) - self._closed

    def occupancy(self) -> Occupancy:
        """How many open episodes there are in each location now."""
        return _occupancy(None, self.states, self._closed)

    def occupancy_at(self, t: float) -> Occupancy:
        """How many open episodes there were in each location at the simulated minute
        ``t``, after every event at ``t`` or before."""
        states: dict[str, LocationState] = {}
        closed: set[str] = set()
        for event in self._events:
            episode = event.episode_id
            if episode is None or event.sim_time > t:
                continue
            states[episode] = states.get(episode, LocationState()).apply(event)
            if _terminal(event):
                closed.add(episode)
        return _occupancy(t, states, closed)

    def latency_summary(self) -> LatencySummary | None:
        """Median, 95th percentile and maximum of the latencies; ``None`` without any."""
        values = self.latencies_ms
        if not values:
            return None
        p95 = (
            values[0]
            if len(values) == 1
            else statistics.quantiles(values, n=20, method="inclusive")[18]
        )
        return LatencySummary(len(values), statistics.median(values), p95, max(values))

    def _check_run(self, what: str, run_id: str) -> None:
        if self.run_id is None:
            self.run_id = run_id
        elif run_id != self.run_id:
            raise ValueError(f"{what} of run {run_id!r} in the tracker of run {self.run_id!r}")
