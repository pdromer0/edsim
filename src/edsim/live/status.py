"""What a live run is doing, without coupling the pacer to the terminal.

Two wrappers around the pieces of ``run_live``, which do not change what it publishes:

- ``ReportingSink`` wraps the sink: it counts the events written and calls back with the
  ``inicio`` (the census) and the ``fin`` (the summary) once the inner sink has them.
- ``StatusControl`` wraps the control source: the pacer asks it for an order between
  events and in each slice of 0.2 s while it waits, also while paused. On each ``poll``,
  before asking the inner source, it looks at the clock and calls back with a
  ``LiveStatus`` at the first ``poll`` from each point of a fixed grid: every ``interval``
  real seconds from the anchor of the live stream. A line comes at most one slice late, and
  that delay does not add up from one line to the next.

The status reads only public properties of the pacer (``anchor``, ``sim_now()``,
``speed``, ``paused`` and ``lag()``); what has been published and what is pending come as
functions. The texts in Spanish are in ``edsim.live.report``.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from edsim.engine.events import Event, event_time
from edsim.live.clock import Clock
from edsim.live.control import Command, ControlSource
from edsim.live.directo import LiveSink, RunEnd, RunStart
from edsim.live.pacer import Pacer

STATUS_INTERVAL = 10.0
"""Real seconds between two status lines."""


@dataclass(frozen=True, slots=True)
class LiveStatus:
    """A snapshot of a live run.

    Attributes:
        elapsed: Real seconds since the anchor of the live stream.
        sim_time: The simulated minute now, never past the horizon.
        event_time: The clock time of that minute, as in ``event_time``.
        speed: The speed, a float or ``"max"``.
        paused: Whether the pacer is paused.
        published: Events published so far, census included.
        lag: Seconds of delay of the last event released (``Pacer.lag``).
        pending: Messages waiting for their confirmation; ``None`` without a broker.
    """

    elapsed: float
    sim_time: float
    event_time: str
    speed: float | str
    paused: bool
    published: int
    lag: float
    pending: int | None


class ReportingSink:
    """A ``LiveSink`` that counts the events and reports the start and the end.

    Args:
        sink: The sink that publishes.
        on_start: Called with the ``RunStart`` after the inner sink published it.
        on_end: Called with the ``RunStart`` (``None`` if none) and the ``RunEnd`` after the
            inner sink published the end.

    Attributes:
        published: Events the inner sink accepted.
        run_start: The ``RunStart``, once published.
        run_end: The ``RunEnd``, once published.
    """

    def __init__(
        self,
        sink: LiveSink,
        *,
        on_start: Callable[[RunStart], None] | None = None,
        on_end: Callable[[RunStart | None, RunEnd], None] | None = None,
    ) -> None:
        self.sink = sink
        self._on_start = on_start
        self._on_end = on_end
        self.published = 0
        self.run_start: RunStart | None = None
        self.run_end: RunEnd | None = None

    def start(self, message: RunStart) -> None:
        self.sink.start(message)
        self.run_start = message
        if self._on_start is not None:
            self._on_start(message)

    def write(self, event: Event) -> None:
        self.sink.write(event)
        self.published += 1

    def end(self, message: RunEnd) -> None:
        self.sink.end(message)
        self.run_end = message
        if self._on_end is not None:
            self._on_end(self.run_start, message)


class StatusControl:
    """A ``ControlSource`` that reports the status every ``interval`` real seconds.

    Args:
        control: Where the orders come from.
        clock: The clock of the pacer.
        pacer: The pacer of the run.
        start_date: Date of minute 0, for ``event_time``.
        horizon: Horizon of the run in minutes.
        published: How many events have been published.
        on_status: Called with each ``LiveStatus``.
        pending: How many messages wait for their confirmation; ``None`` without a broker.
        interval: Real seconds between two statuses.
    """

    def __init__(
        self,
        control: ControlSource,
        *,
        clock: Clock,
        pacer: Pacer,
        start_date: date,
        horizon: float,
        published: Callable[[], int],
        on_status: Callable[[LiveStatus], None],
        pending: Callable[[], int] | None = None,
        interval: float = STATUS_INTERVAL,
    ) -> None:
        self._control = control
        self._clock = clock
        self._pacer = pacer
        self._start_date = start_date
        self._horizon = horizon
        self._published = published
        self._on_status = on_status
        self._pending = pending
        self._interval = interval
        self._anchor: float | None = None
        self._next = 0.0

    def poll(self) -> Command | None:
        """Report the status if it is due, then give the next order of ``control``.

        The first ``poll`` of ``run_live`` comes right after the pacer is anchored at the
        start of the live stream, before any order is applied: that anchor is where the
        first interval starts. The status is the one before the order of this ``poll``.
        """
        now = self._clock.monotonic()
        if self._anchor is None:
            self._anchor = self._pacer.anchor[0]
            self._next = self._anchor + self._interval
        if now >= self._next:
            self._on_status(self.status(now))
            # A fixed grid from the anchor: a line late by up to one slice does not delay the
            # next one. After a pause or a slow publication that skipped whole intervals, the
            # grid starts again from now.
            self._next += self._interval
            if self._next <= now:
                self._next = now + self._interval
        return self._control.poll()

    def status(self, now: float) -> LiveStatus:
        """The status at the real instant ``now`` of the clock."""
        pacer = self._pacer
        sim_time = min(pacer.sim_now(), self._horizon)
        return LiveStatus(
            elapsed=now - (self._anchor if self._anchor is not None else now),
            sim_time=sim_time,
            event_time=event_time(self._start_date, sim_time),
            speed=pacer.speed,
            paused=pacer.paused,
            published=self._published(),
            lag=pacer.lag(),
            pending=None if self._pending is None else self._pending(),
        )
