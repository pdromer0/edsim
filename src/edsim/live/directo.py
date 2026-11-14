"""The live run: warm up, publish the census and then each event when its time comes.

``run_live`` follows the sequence of docs/specs/hito-6.md, piece 6 (preparing
the topics is task 6.4):

a) **Warm up.** The source runs without waits from minute 0 to the start of
   the live run ``W``; the events are kept in memory, not published.
b) **Census.** The warm-up events of the episodes still open at ``W`` and
   every resource event of the warm-up (``edsim.live.census``). With the
   engine, the open episodes must be exactly its live patient processes.
c) **Announce.** ``sink.start(RunStart)``: identity, ``W``, horizon, speed
   and the size of the census.
d) **Census out**, all at once, without waits.
e) **Live.** The pacer is anchored at (now, ``W``), after the census, and
   each event goes to the sink when its time comes.
f) **End.** After the last event, it waits for the horizon and calls
   ``sink.end(RunEnd)`` with reason ``horizonte``; with an order ``parar``,
   reason ``parar``; with Ctrl+C, reason ``interrupcion`` and the
   ``KeyboardInterrupt`` goes on; if the sink fails (``SinkError``), reason
   ``error`` and the error goes on.

What it publishes is the batch log without the warm-up of the closed
episodes, with the same ``Event`` objects and in the same order, whatever the
orders (piece 7). The pace never changes the content.

Two sources: ``EngineSource``, the stepped engine of a run, and ``LogSource``,
a saved log (the replay of H6-13). ``anchored_start`` gives the start date and
``W`` of a run anchored to the calendar (H6-12).

With ``--registro`` (docs/specs/hito-7.md, task 7.4), the run publishes only what
was written down: the truth goes step by step into a waiting room
(``LiveRecording``), and the census and the live stream are its records, with the
derived ``run_id``.

``RunStart`` and ``RunEnd`` are data here; ``edsim.live.messages`` turns them
into the JSON messages of ``ed.runs``. Their values are in Spanish, as in those
messages.
"""

import math
import numbers
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

from edsim.arrivals.rate import MINUTES_PER_DAY
from edsim.clinical_record import Record, derived_run_id
from edsim.engine.events import SCHEMA_VERSIONS, TIMEZONE, Event, MemorySink
from edsim.finite import to_float
from edsim.live.census import census, open_episodes, recorded_census
from edsim.live.control import ControlSource
from edsim.live.pacer import Pacer

if TYPE_CHECKING:
    from edsim.engine.engine import SteppedED

LIVE = "directo"
REPLAY = "replay"
MODES = (LIVE, REPLAY)
"""Modes of a run: the engine live, or a saved log again."""

REASON_HORIZON = "horizonte"
REASON_STOP = "parar"
REASON_INTERRUPT = "interrupcion"
REASON_ERROR = "error"
"""A message was not delivered (task 6.4)."""


# --- Sources -------------------------------------------------------------------------


class LiveSource(Protocol):
    """Where the events of a live run come from."""

    def peek(self) -> float:
        """Instant of the next step; ``math.inf`` if nothing is left before the horizon."""
        ...

    def step(self) -> list[Event]:
        """Run the next step: its events, all at the instant ``peek()`` gave (maybe none)."""
        ...


class EngineSource:
    """The stepped engine of a run as a source.

    The engine writes its events to the sink it received in ``start_ed``. That
    sink must be ``buffer``, a ``MemorySink`` that this source empties at each
    step: so the warm-up stays in memory and the rest is published, with the
    same ``Event`` objects as in batch::

        buffer = MemorySink()
        source = EngineSource(start_ed(center, profile, days, seed, sink=buffer), buffer)

    ``peek()`` looks first at what is already emitted and not taken (the
    ``staffing_changed`` of minute 0 are emitted when the run is built) and
    then at the engine. Stepping while ``peek() < W`` runs exactly the engine
    events before ``W``, so ``alive_episodes()`` is then the one at ``W``.

    Args:
        ed: The run, from ``start_ed``, before any step.
        buffer: The sink given to ``start_ed``.
    """

    def __init__(self, ed: "SteppedED", buffer: MemorySink) -> None:
        self._ed = ed
        self._buffer = buffer

    @property
    def horizon(self) -> int:
        """The horizon of the run, in minutes."""
        return self._ed.horizon

    def peek(self) -> float:
        if self._buffer.events:
            return self._buffer.events[0].sim_time
        return self._ed.peek()

    def step(self) -> list[Event]:
        """The events already emitted, or else those of one more step of the engine.

        Raises:
            RuntimeError: If nothing is left before the horizon.
        """
        if not self._buffer.events:
            self._ed.step()
        events, self._buffer.events = self._buffer.events, []
        return events

    def alive_episodes(self) -> frozenset[str]:
        """The episodes with a live patient process in the engine now."""
        return self._ed.alive_episodes()


def _check_minutes(name: str, value: object) -> float:
    # bool is a subclass of int in Python; NaN and infinity are no instant.
    if (
        isinstance(value, bool)
        or not isinstance(value, numbers.Real)
        or (number := to_float(value)) is None  # an int such as 10**400
        or not math.isfinite(number)
    ):
        raise ValueError(f"{name} must be a finite number of minutes, got {value!r}")
    return number


class LogSource:
    """A saved log as a source, one event per step (the replay).

    Lazy: it reads one event ahead, so ``read_events`` of a large file is
    never all in memory. The events must be in emission order, which is also
    time order.

    Args:
        events: The events, such as ``read_events(path)``.
        horizon: Horizon of the run in minutes; events at it or later are
            never given, as in the engine.

    Raises:
        ValueError: If ``horizon`` is not a finite number; while stepping, if
            a ``sim_time`` goes back.
    """

    def __init__(self, events: Iterable[Event], horizon: float) -> None:
        self.horizon = _check_minutes("horizon", horizon)
        self._events = iter(events)
        self._next = next(self._events, None)

    def peek(self) -> float:
        if self._next is None or self._next.sim_time >= self.horizon:
            return math.inf
        return self._next.sim_time

    def step(self) -> list[Event]:
        """The next event.

        Raises:
            RuntimeError: If nothing is left before the horizon.
            ValueError: If the event after it goes back in time.
        """
        if self.peek() == math.inf:
            raise RuntimeError(f"no event left before the horizon ({self.horizon} min)")
        event = self._next
        self._next = next(self._events, None)
        if self._next is not None and self._next.sim_time < event.sim_time:
            raise ValueError(
                f"the log goes back in time: {self._next.event_id} at {self._next.sim_time} "
                f"after {event.event_id} at {event.sim_time}"
            )
        return [event]


# --- What was written down (task 7.4) ------------------------------------------------


class LiveRecording(Protocol):
    """What a run published with ``--registro`` does with the truth: its waiting room.

    ``run_live`` hands it every step of the truth with ``add`` and publishes what
    ``ready(source.peek())`` gives: the records nothing still to come can go before, in
    emission order. ``RecordStream`` (``edsim.clinical_record``) records the engine as it
    goes; ``RecordedLog`` holds what ``record`` already gave (the replay).
    """

    def add(self, events: Iterable[Event]) -> None: ...

    def ready(self, bound: float) -> list[Record]: ...


class RecordedLog:
    """The waiting room of a replay: the records of ``record``, already in emission order.

    ``add`` ignores the truth (the records were computed from all of it) and ``ready``
    gives the next records with ``sim_time <= bound``. Records come in emission order, so
    their ``sim_time`` never goes back.

    Args:
        records: The records of a ``Recording``, in emission order.

    Raises:
        ValueError: If a record goes back in time.
    """

    def __init__(self, records: Iterable[Record]) -> None:
        self._records: deque[Record] = deque(records)
        last = -math.inf
        for item in self._records:
            if item.sim_time < last:
                raise ValueError(f"{item.event_id} at {item.sim_time} goes back from {last}")
            last = item.sim_time

    def __len__(self) -> int:
        return len(self._records)

    def add(self, events: Iterable[Event]) -> None:
        """Nothing: the records come from the whole truth."""

    def ready(self, bound: float) -> list[Record]:
        """The next records with ``sim_time <= bound``, in emission order.

        Raises:
            ValueError: If ``bound`` is NaN, as ``RecordStream.ready``.
        """
        if isinstance(bound, bool) or not isinstance(bound, int | float) or math.isnan(bound):
            raise ValueError(f"bound must be a number of minutes, got {bound!r}")
        out = []
        while self._records and self._records[0].sim_time <= bound:
            out.append(self._records.popleft())
        return out


# --- What the run announces ----------------------------------------------------------


def _check_seed(name: str, seed: object) -> int:
    if isinstance(seed, bool) or not isinstance(seed, numbers.Integral) or seed < 0:
        raise ValueError(f"{name} must be an integer >= 0, got {seed!r}")
    return int(seed)


@dataclass(frozen=True, slots=True)
class RecordInfo:
    """What a run published with ``--registro`` is the record of (the block ``registro``).

    Attributes:
        origin: The ``run_id`` of the true run (``origen``).
        profile: The profile of the slips (``perfil``).
        seed: The seed of the recording (``semilla``).

    Raises:
        ValueError: If a field is not valid.
    """

    origin: str
    profile: str
    seed: int

    def __post_init__(self) -> None:
        # Any profile name, as RecordProfile: the CLI limits --registro to the three of the
        # file, but a profile built in code (a test, a notebook) may have its own.
        for name in ("origin", "profile"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string, got {value!r}")
        object.__setattr__(self, "seed", _check_seed("seed of the record", self.seed))


@dataclass(frozen=True, slots=True)
class RunInfo:
    """What the caller knows of the run, for the ``inicio`` of ``ed.runs``.

    Attributes:
        run_id: Identifier of the run, the same as in its events; with ``record``, the
            derived run ``<origen>_<perfil>_s<semilla>``.
        mode: ``"directo"`` or ``"replay"``.
        schema_version: Version of the catalog of its events.
        seed: Seed of the run (``semilla``); with ``record``, the one of the true run.
        start_date: Date of minute 0 (``fecha_inicio``).
        anchored: Whether it is anchored to the calendar (``anclado``).
        record: What it is the record of, if it publishes what was written down
            (docs/specs/hito-7.md, task 7.4); ``None`` if it publishes the truth.

    Raises:
        ValueError: If a field is not valid, or ``run_id`` is not the derived run of
            ``record``.
    """

    run_id: str
    mode: str
    schema_version: int
    seed: int
    start_date: date
    anchored: bool
    record: RecordInfo | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id:
            raise ValueError(f"run_id must be a non-empty string, got {self.run_id!r}")
        if not isinstance(self.mode, str) or self.mode not in MODES:
            raise ValueError(f"mode must be one of {list(MODES)}, got {self.mode!r}")
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version not in SCHEMA_VERSIONS
        ):
            raise ValueError(
                f"schema_version must be one of {sorted(SCHEMA_VERSIONS)}, "
                f"got {self.schema_version!r}"
            )
        seed = _check_seed("seed", self.seed)
        # datetime is a subclass of date: a date-time must not pass as a date.
        if not isinstance(self.start_date, date) or isinstance(self.start_date, datetime):
            raise ValueError(f"start_date must be a date without time, got {self.start_date!r}")
        if not isinstance(self.anchored, bool):
            raise ValueError(f"anchored must be True or False, got {self.anchored!r}")
        if self.record is not None:
            if not isinstance(self.record, RecordInfo):
                raise ValueError(f"record must be a RecordInfo or None, got {self.record!r}")
            info = self.record
            derived = derived_run_id(info.origin, info.profile, info.seed)
            if self.run_id != derived:
                raise ValueError(
                    f"the run_id of the record of {info.origin!r} with {info.profile!r} and "
                    f"seed {info.seed} is {derived!r}, not {self.run_id!r}"
                )
        # The dataclass is frozen: object.__setattr__ is the standard way to set
        # fields during construction.
        object.__setattr__(self, "seed", seed)


@dataclass(frozen=True, slots=True)
class RunStart:
    """The announcement of a run (``inicio``), before the census.

    Attributes:
        info: What the caller knows of the run.
        live_start: Start of the live stream ``W``, in minutes
            (``inicio_directo``): the census is ``sim_time < W``.
        horizon: Horizon in minutes.
        speed: Speed at the start, a float or ``"max"``.
        census_episodes: Episodes open at ``W``.
        census_events: Events of the census.
    """

    info: RunInfo
    live_start: float
    horizon: float
    speed: float | str
    census_episodes: int
    census_events: int


@dataclass(frozen=True, slots=True)
class RunEnd:
    """The end of a run (``fin``).

    Attributes:
        run_id: Identifier of the run.
        reason: ``"horizonte"``, ``"parar"``, ``"interrupcion"`` or ``"error"``.
        sim_time: Simulated minute of the end: the horizon, or where the
            simulated clock was (never past the horizon).
        last_event_id: ``event_id`` of the last event published; ``None``
            if none.
        published: Events published, census included.
    """

    run_id: str
    reason: str
    sim_time: float
    last_event_id: str | None
    published: int


# --- Where the run goes --------------------------------------------------------------


class SinkError(Exception):
    """The sink could not publish: a message was not delivered (H6-8).

    ``run_live`` never goes on with a gap in what it published: it publishes
    the ``fin`` with reason ``error``, saying only what the sink confirmed, and
    raises this error again.

    Args:
        message: What happened.
        delivered: Events whose delivery was confirmed.
        failed: What was not delivered: the ``event_id`` of each event, or
            ``inicio`` and ``fin`` for the messages of the run.
        pending: Messages still waiting for their confirmation.
        last_delivered: ``event_id`` of the confirmed event with the highest
            emission number (confirmations may come in another order); ``None``
            if none.
    """

    def __init__(
        self,
        message: str,
        *,
        delivered: int,
        failed: tuple[str, ...] = (),
        pending: int = 0,
        last_delivered: str | None = None,
    ) -> None:
        super().__init__(message)
        self.delivered = delivered
        self.failed = tuple(failed)
        self.pending = pending
        self.last_delivered = last_delivered


class LiveSink(Protocol):
    """Where a live run publishes: the announcement, the events (or the records) and the end."""

    def start(self, message: RunStart) -> None: ...

    def write(self, event: Event | Record) -> None: ...

    def end(self, message: RunEnd) -> None: ...


class MemoryLiveSink:
    """Keeps everything a live run publishes, in order, for tests and notebooks.

    Attributes:
        items: ``RunStart``, the events (or the records, with ``--registro``) and
            ``RunEnd``, in publication order.
    """

    def __init__(self) -> None:
        self.items: list[RunStart | Event | Record | RunEnd] = []

    def start(self, message: RunStart) -> None:
        self.items.append(message)

    def write(self, event: Event | Record) -> None:
        self.items.append(event)

    def end(self, message: RunEnd) -> None:
        self.items.append(message)

    @property
    def events(self) -> list[Event | Record]:
        """Only the events (or the records), in order: everything but the start and the end."""
        return [item for item in self.items if not isinstance(item, RunStart | RunEnd)]

    @property
    def run_start(self) -> RunStart | None:
        """The ``RunStart``, if published."""
        return next((item for item in self.items if isinstance(item, RunStart)), None)

    @property
    def run_end(self) -> RunEnd | None:
        """The ``RunEnd``, if published."""
        return next((item for item in self.items if isinstance(item, RunEnd)), None)


# --- The run -------------------------------------------------------------------------


class _Publication:
    """Counts what goes to the sink and knows where the simulated clock is."""

    def __init__(self, sink: LiveSink, pacer: Pacer, start: float, horizon: float) -> None:
        self.sink = sink
        self.pacer = pacer
        self.start = start
        self.horizon = horizon
        self.live = False  # the pacer is anchored at W
        self.published = 0
        self.last_event_id: str | None = None

    def write(self, event: Event | Record) -> None:
        self.sink.write(event)
        self.published += 1
        self.last_event_id = event.event_id

    def sim_now(self) -> float:
        # While the census goes out, the simulated clock is at W.
        if not self.live:
            return self.start
        return min(self.pacer.sim_now(), self.horizon)

    def end(self, run_id: str, reason: str, sim_time: float) -> RunEnd:
        return RunEnd(
            run_id=run_id,
            reason=reason,
            sim_time=sim_time,
            last_event_id=self.last_event_id,
            published=self.published,
        )


def _truth_feed(source: LiveSource) -> Callable[[], list[Event] | None]:
    """The next step of the source, to publish as it is; ``None`` when nothing is left."""

    def feed() -> list[Event] | None:
        if source.peek() == math.inf:
            return None
        return source.step()

    return feed


def _recorded_feed(
    source: LiveSource, recording: LiveRecording
) -> Callable[[], list[Record] | None]:
    """The next step of the source into the waiting room, and what it lets out.

    The truth never goes to the sink: only the records ``ready`` gives. Once the source
    has nothing left, ``ready(inf)`` lets out the rest; ``None`` when that is empty too.
    """

    def feed() -> list[Record] | None:
        if source.peek() == math.inf:
            return recording.ready(math.inf) or None
        recording.add(source.step())
        return recording.ready(source.peek())

    return feed


def _publish(
    feed: Callable[[], list[Event] | list[Record] | None],
    control: ControlSource,
    publication: _Publication,
    initial: list[Event] | list[Record],
    pending: deque[Event | Record],
) -> str:
    """Steps d), e) and f): census, live stream and wait for the horizon; the reason.

    Each item waits for its own ``sim_time``: with ``--registro``, the ``sim_time`` written
    down, so a record delayed to 1,031.2 goes out at 1,031.2.
    """
    for event in initial:
        publication.write(event)

    pacer = publication.pacer
    pacer.reanchor(publication.start)
    publication.live = True
    while True:
        if not pending:
            more = feed()
            if more is None:
                break
            pending.extend(more)
            continue
        if pacer.wait_until(pending[0].sim_time, control):
            return REASON_STOP
        publication.write(pending.popleft())

    if pacer.wait_until(publication.horizon, control):
        return REASON_STOP
    return REASON_HORIZON


def run_live(
    source: LiveSource,
    pacer: Pacer,
    control: ControlSource,
    sink: LiveSink,
    *,
    start: float,
    horizon: float,
    run_info: RunInfo,
    recording: LiveRecording | None = None,
) -> RunEnd:
    """Run a live run, from the warm-up to the end (see the module).

    With ``recording`` (``--registro``, task 7.4), only what was written down is published,
    never an event of the truth: every step of the source goes to ``recording``, and the
    census and the live stream are its records. The census is the records with ``sim_time
    < W`` whose episode the *truth* has open at ``W`` (or with no episode); the live stream,
    every record with ``sim_time >= W``. ``censo.episodios`` counts the episodes among the
    records of the census, so no number of the truth reaches the broker. What is published
    is the ``registrado.jsonl`` of ``record`` filtered so, byte for byte.

    Args:
        source: ``EngineSource`` or ``LogSource``, before any step.
        pacer: The pacer, with the speed of the start; it is anchored at
            (now, ``start``) after the census.
        control: Where the orders come from.
        sink: Where the run publishes.
        start: Start of the live stream ``W``, in minutes.
        horizon: Horizon in minutes; the same as the source's, if it has one.
        run_info: Identity of the run, for ``RunStart``; with ``recording``, with its
            ``record`` and the derived ``run_id``.
        recording: The waiting room of what was written down, before any ``add``:
            ``RecordStream`` with the engine, ``RecordedLog`` in a replay.

    Returns:
        The ``RunEnd`` published.

    Raises:
        ValueError: Before doing anything, if ``start`` and ``horizon`` are
            not finite numbers with ``0 <= start < horizon``, the horizon of
            the source is another, ``run_info`` is not a ``RunInfo``, or it has a
            ``record`` without ``recording`` or the other way round.
        RuntimeError: Before publishing anything, if the source is the
            engine and the episodes open at ``start`` are not its live
            patient processes.
        KeyboardInterrupt: After publishing the ``RunEnd`` with reason
            ``interrupcion``, if it arrived after the ``RunStart``.
        SinkError: If the sink fails while publishing the census or the live
            stream, after publishing (if it can) the ``RunEnd`` with reason
            ``error``, with the events the sink confirmed as ``published`` and
            the highest one confirmed as ``last_event_id``. If that end fails
            too, the ``SinkError`` goes on with a note. Also if ``sink.end``
            raises it: a sink that waits for its confirmations (``KafkaSink``)
            publishes a ``fin`` with reason ``error`` instead of the one given and
            raises. That error goes out of ``run_live`` instead of returning
            and, after Ctrl+C, instead of the ``KeyboardInterrupt``, which stays
            as its context: an incomplete run matters more than how it stopped.
    """
    start = _check_minutes("start", start)
    horizon = _check_minutes("horizon", horizon)
    if not 0 <= start < horizon:
        raise ValueError(f"start must be >= 0 and less than the horizon ({horizon}), got {start}")
    source_horizon = getattr(source, "horizon", None)
    if source_horizon is not None and source_horizon != horizon:
        raise ValueError(f"the horizon of the source is {source_horizon}, not {horizon}")
    if not isinstance(run_info, RunInfo):
        raise ValueError(f"run_info must be a RunInfo, got {run_info!r}")
    if (recording is None) != (run_info.record is None):
        raise ValueError(
            "a run with --registro needs both a recording and the record of its run_info"
        )

    # a) Warm-up, without waits and without publishing.
    warmup: list[Event] = []
    while source.peek() < start:
        step = source.step()
        warmup.extend(step)
        if recording is not None:
            recording.add(step)

    # b) Census, checked against the engine when there is one.
    still_open = open_episodes(warmup, start)
    alive_episodes = getattr(source, "alive_episodes", None)
    if alive_episodes is not None:
        alive = alive_episodes()
        if alive != still_open:
            raise RuntimeError(
                f"the episodes open at {start} are not the live patient processes: "
                f"{len(still_open - alive)} open and not alive, "
                f"{len(alive - still_open)} alive and not open"
            )
    pending: deque[Event | Record] = deque()
    if recording is None:
        initial = census(warmup, start)
        census_episodes = len(still_open)
        feed = _truth_feed(source)
    else:
        # Everything before W is out of the room now (W <= peek); what is at W or later,
        # and already out, is the start of the live stream.
        released = recording.ready(source.peek())
        initial = recorded_census(released, still_open, start)
        pending.extend(r for r in released if r.sim_time >= start)
        census_episodes = len({r.episode_id for r in initial if r.episode_id is not None})
        feed = _recorded_feed(source, recording)

    # c) Announce.
    sink.start(
        RunStart(
            info=run_info,
            live_start=start,
            horizon=horizon,
            speed=pacer.speed,
            census_episodes=census_episodes,
            census_events=len(initial),
        )
    )

    # d), e) and f).
    publication = _Publication(sink, pacer, start, horizon)
    try:
        reason = _publish(feed, control, publication, initial, pending)
    except KeyboardInterrupt:
        sink.end(publication.end(run_info.run_id, REASON_INTERRUPT, publication.sim_now()))
        raise
    except SinkError as error:
        # Only what the sink confirmed: this end does not promise that every event
        # before the last one arrived; it says that the run is incomplete.
        end = RunEnd(
            run_id=run_info.run_id,
            reason=REASON_ERROR,
            sim_time=publication.sim_now(),
            last_event_id=error.last_delivered,
            published=error.delivered,
        )
        try:
            sink.end(end)
        except Exception as second:
            error.add_note(f"the end of the run could not be published either: {second!r}")
        raise
    sim_time = horizon if reason == REASON_HORIZON else publication.sim_now()
    end = publication.end(run_info.run_id, reason, sim_time)
    sink.end(end)
    return end


# --- Anchoring to the calendar -------------------------------------------------------


def anchored_start(wall: datetime, warmup_days: int) -> tuple[date, float]:
    """Start date and ``W`` of a run anchored to the calendar (H6-12).

    The run starts ``warmup_days`` before today at 00:00 and warms up until
    now, so the live stream starts at the real time. The day is taken in the
    fixed zone ``+01:00`` of ``event_time``, not in UTC: at 23:30 UTC it is
    already the next day in ``+01:00``.

    Args:
        wall: The date and time now, with time zone (``Clock.wall()``).
        warmup_days: Full days of warm-up before today, an integer >= 0.

    Returns:
        ``(start_date, W)``: the date of minute 0, for
        ``ArrivalProfile.with_start_date``, and the start of the live stream
        in minutes. For 10:30 in ``+01:00`` and 2 days, ``W`` = 2 · 1,440 +
        630 = 3,510.

    Raises:
        ValueError: If ``wall`` has no time zone or ``warmup_days`` is not an
            integer >= 0.
    """
    if not isinstance(wall, datetime) or wall.utcoffset() is None:
        raise ValueError(f"wall must be a datetime with time zone, got {wall!r}")
    if isinstance(warmup_days, bool) or not isinstance(warmup_days, int) or warmup_days < 0:
        raise ValueError(f"warmup_days must be an integer >= 0, got {warmup_days!r}")
    local = wall.astimezone(TIMEZONE)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    start_date = local.date() - timedelta(days=warmup_days)
    return start_date, warmup_days * MINUTES_PER_DAY + (local - midnight) / timedelta(minutes=1)
