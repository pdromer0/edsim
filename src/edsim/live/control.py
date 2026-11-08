"""Orders to a live run: change the speed, pause, resume and stop.

The orders only change the pace, never the model: the live run publishes the
same events with any sequence of orders (docs/specs/hito-6.md, piece 6,
H6-6). In milestone 6 they arrive through the topic ``ed.control``
(``KafkaControl``, task 6.4); here are the order itself, the source that
gives none and a scripted source for tests and notebooks, which delivers each
order at an instant of a clock.

The names of the orders are the values of the messages of ``ed.control``, in
Spanish: ``velocidad`` (with a value), ``pausar``, ``reanudar`` and
``parar``.

Standard library only: no SimPy, no engine and no Kafka client.
"""

import math
import numbers
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from edsim.live.clock import Clock

SPEED = "velocidad"
PAUSE = "pausar"
RESUME = "reanudar"
STOP = "parar"
ORDERS = (SPEED, PAUSE, RESUME, STOP)
"""The orders of ``ed.control``."""

MAX_SPEED = "max"
"""Speed without waits: the engine runs as in batch."""


def check_speed(speed: object) -> float | str:
    """A speed as a float, or ``MAX_SPEED``.

    A speed is how many simulated minutes last one real minute: 60 means a
    simulated hour per real minute.

    Raises:
        ValueError: If ``speed`` is not a positive, finite real number nor
            ``"max"``. ``True`` is not 1.
    """
    if speed == MAX_SPEED and isinstance(speed, str):
        return MAX_SPEED
    if (
        isinstance(speed, bool)
        or not isinstance(speed, numbers.Real)
        or not math.isfinite(speed)
        or speed <= 0
    ):
        raise ValueError(f"speed must be a positive finite number or {MAX_SPEED!r}, got {speed!r}")
    return float(speed)


@dataclass(frozen=True, slots=True)
class Command:
    """One order to the live run.

    Attributes:
        order: One of ``ORDERS``.
        value: The speed, for ``velocidad`` (a float or ``"max"``); ``None``
            for the rest.

    Raises:
        ValueError: If the order is unknown, ``velocidad`` has no valid
            speed, or another order has a value.
    """

    order: str
    value: float | str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.order, str) or self.order not in ORDERS:
            raise ValueError(f"order must be one of {list(ORDERS)}, got {self.order!r}")
        if self.order == SPEED:
            # The dataclass is frozen: object.__setattr__ is the standard way
            # to set fields during construction.
            object.__setattr__(self, "value", check_speed(self.value))
        elif self.value is not None:
            raise ValueError(f"{self.order} takes no value, got {self.value!r}")


class ControlSource(Protocol):
    """Where the orders come from."""

    def poll(self) -> Command | None:
        """The next order, if one has arrived; ``None`` otherwise. Never waits."""
        ...


class NoControl:
    """A source that never gives an order."""

    def poll(self) -> Command | None:
        return None


def _check_instant(instant: object) -> float:
    if (
        isinstance(instant, bool)
        or not isinstance(instant, numbers.Real)
        or not math.isfinite(instant)
    ):
        raise ValueError(f"the instant of an order must be a finite number, got {instant!r}")
    return float(instant)


class ScriptedControl:
    """Orders at given instants of a clock, such as a ``FakeClock``.

    ``poll()`` gives at most one order: the oldest of those whose instant has
    come (``instant <= clock.monotonic()``). Orders at the same instant come
    out one per ``poll``, in the order of the script.

    Args:
        clock: The clock that decides when an order is due.
        script: Pairs ``(instant in seconds, Command)``, in any order; they
            are sorted by instant, keeping the order of ties.

    Attributes:
        delivered: For each order given by ``poll``: its instant in the
            script, the instant of the clock when it was given, and the
            order. The difference is how late it was seen.

    Raises:
        ValueError: If an instant is not a finite number or an item is not a
            ``Command``.
    """

    def __init__(self, clock: Clock, script: Iterable[tuple[float, Command]]) -> None:
        checked = []
        for instant, command in script:
            if not isinstance(command, Command):
                raise ValueError(f"each order of the script must be a Command, got {command!r}")
            checked.append((_check_instant(instant), command))
        self._clock = clock
        self._pending = sorted(checked, key=lambda item: item[0])  # stable: ties keep order
        self._next = 0
        self.delivered: list[tuple[float, float, Command]] = []

    @property
    def pending(self) -> int:
        """Orders not given yet."""
        return len(self._pending) - self._next

    def poll(self) -> Command | None:
        if self._next == len(self._pending):
            return None
        instant, command = self._pending[self._next]
        now = self._clock.monotonic()
        if instant > now:
            return None
        self._next += 1
        self.delivered.append((instant, now, command))
        return command
