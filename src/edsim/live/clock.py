"""Clocks for the live mode: the system's and a fake one for tests.

The pacer never calls ``time`` directly: it receives a clock with three
methods (docs/specs/hito-6.md, pieces 1 and 7, H6-5):

- ``monotonic()``: seconds of a clock that never goes back, to wait;
- ``sleep(seconds)``: wait that long;
- ``wall()``: the date and time, with time zone, only to anchor a run to the
  calendar.

``SystemClock`` is the real one. ``FakeClock`` moves forward only when asked
to sleep, at once and without sleeping: a day at x1 is tested in
milliseconds, and each wait can be checked to the nanosecond.

Standard library only: no SimPy, no engine and no Kafka client.
"""

import math
import numbers
import time
from datetime import UTC, datetime, timedelta
from typing import Protocol

NS_PER_SECOND = 1_000_000_000

FAKE_WALL_START = datetime(2026, 1, 5, tzinfo=UTC)
"""Wall time of a ``FakeClock`` at its start, unless another one is given."""


class Clock(Protocol):
    """What the pacer needs from a clock."""

    def monotonic(self) -> float:
        """Seconds of a clock that never goes back; only differences mean something."""
        ...

    def sleep(self, seconds: float) -> None:
        """Wait ``seconds``, a finite number >= 0."""
        ...

    def wall(self) -> datetime:
        """The date and time now, with time zone; only to anchor a run."""
        ...


class SystemClock:
    """The clock of the system: ``time.monotonic``, ``time.sleep`` and the time in UTC."""

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def wall(self) -> datetime:
        return datetime.now(UTC)


def _check_seconds(name: str, seconds: object) -> float:
    # bool is a subclass of int in Python: True must not pass as 1 second.
    if (
        isinstance(seconds, bool)
        or not isinstance(seconds, numbers.Real)
        or not math.isfinite(seconds)
        or seconds < 0
    ):
        raise ValueError(f"{name} must be a finite number of seconds >= 0, got {seconds!r}")
    return float(seconds)


def _to_ns(seconds: float) -> int:
    return round(seconds * NS_PER_SECOND)


class FakeClock:
    """A clock that moves forward only when asked to sleep, without sleeping.

    It keeps the time in whole nanoseconds, as ``time.monotonic_ns``: in
    floating point, 150 waits of 0.2 s add up to 29.999999999999925 s, and an
    order scheduled at 30 s would be seen one wait late. Each ``sleep`` is
    rounded to the nanosecond, and is at least 1 ns if positive, so that a
    tiny wait never leaves a loop stuck.

    Args:
        start: Value of ``monotonic()`` at the start, in seconds.
        wall_start: Value of ``wall()`` at the start, with time zone.
        oversleep: Seconds that each ``sleep`` lasts beyond what was asked,
            as a real ``time.sleep`` does (0.1 to 1 ms in Linux, more in
            Windows).
        interrupt_at: If given, the first ``sleep`` that reaches or passes
            this instant stops there and raises ``KeyboardInterrupt``, as a
            Ctrl+C in the middle of ``time.sleep``. Only once.

    Attributes:
        sleeps: The seconds asked of each ``sleep``, in order (without the
            oversleep).

    Raises:
        ValueError: If ``start`` or ``oversleep`` is not a finite number of
            seconds >= 0, ``interrupt_at`` is not one or ``None``, or
            ``wall_start`` has no time zone.
    """

    def __init__(
        self,
        start: float = 0.0,
        *,
        wall_start: datetime = FAKE_WALL_START,
        oversleep: float = 0.0,
        interrupt_at: float | None = None,
    ) -> None:
        if not isinstance(wall_start, datetime) or wall_start.utcoffset() is None:
            raise ValueError(f"wall_start must be a datetime with time zone, got {wall_start!r}")
        self._start_ns = self._now_ns = _to_ns(_check_seconds("start", start))
        self._wall_start = wall_start
        self._oversleep_ns = _to_ns(_check_seconds("oversleep", oversleep))
        self._interrupt_ns = (
            None if interrupt_at is None else _to_ns(_check_seconds("interrupt_at", interrupt_at))
        )
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self._now_ns / NS_PER_SECOND

    def sleep(self, seconds: float) -> None:
        """Move forward ``seconds`` plus the oversleep, at once.

        Raises:
            ValueError: If ``seconds`` is not a finite number >= 0.
            KeyboardInterrupt: If this wait reaches ``interrupt_at``; the
                clock stays at that instant.
        """
        seconds = _check_seconds("sleep", seconds)
        self.sleeps.append(seconds)
        asked = _to_ns(seconds)
        if seconds > 0:
            asked = max(asked, 1)
        end = self._now_ns + asked + self._oversleep_ns
        if self._interrupt_ns is not None and end >= self._interrupt_ns:
            self._now_ns = max(self._now_ns, self._interrupt_ns)
            self._interrupt_ns = None
            raise KeyboardInterrupt
        self._now_ns = end

    def wall(self) -> datetime:
        """``wall_start`` plus the time slept since the start, to the microsecond."""
        elapsed_us = (self._now_ns - self._start_ns) // 1000
        return self._wall_start + timedelta(microseconds=elapsed_us)
