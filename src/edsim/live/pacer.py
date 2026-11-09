"""The pacer: simulated minutes to real seconds (docs/specs/hito-6.md, piece 1, H6-5).

Before each event, the live run asks the pacer to wait until the real instant
of the event. With an anchor ``(w0, s0)`` (real seconds, simulated minutes)
and a speed ``v`` (simulated minutes per real minute), the target of an event
at ``t`` is::

    target(t) = w0 + 60 * (t - s0) / v

**Absolute targets.** The pacer waits until that instant, not "the
difference with the previous event": the excess of each ``sleep`` is
corrected by the next wait, so the delay never grows beyond one excess.

**Re-anchoring.** On a change of speed at real instant ``w``, the simulated
clock is at ``s_now = s0 + v * (w - w0) / 60`` and the anchor becomes ``(w,
s_now)``: the simulated clock neither jumps nor goes back. Pausing freezes
``s_now``; resuming re-anchors at ``(instant of the resumption, s_now)``.
Changing the speed while paused does not resume. At the maximum speed there
is no formula: the simulated clock is at the ``sim_time`` of the last event
released, and that is where a finite speed re-anchors.

**Waiting while listening.** The pacer sleeps in slices of at most 0.2 s and
asks the control source for an order before each slice, also when it does
not need to wait (target already passed, or maximum speed): so an order is
seen in less than 0.2 s, and at maximum speed once per event.

**Never skips events.** If it is late (publishing took longer than the gap
between events), the target has passed and the event goes at once; the next
target, which is absolute, lets it catch up. ``lag()`` says how late.

It knows nothing of the engine nor of Kafka: a clock, a control source and
instants. Standard library only.
"""

import math
import numbers

from edsim.finite import to_float
from edsim.live.clock import Clock
from edsim.live.control import (
    MAX_SPEED,
    PAUSE,
    RESUME,
    SPEED,
    STOP,
    Command,
    ControlSource,
    check_speed,
)

MAX_SLICE = 0.2
"""Longest single sleep, in seconds: the pacer answers an order within this time."""


def _check_minutes(name: str, value: object) -> float:
    # bool is a subclass of int; NaN or infinity would make every target meaningless.
    if (
        isinstance(value, bool)
        or not isinstance(value, numbers.Real)
        or (number := to_float(value)) is None  # an int such as 10**400
        or not math.isfinite(number)
    ):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return number


def _check_anchor(anchor: object) -> tuple[float, float]:
    if not isinstance(anchor, tuple) or len(anchor) != 2:
        raise ValueError(f"anchor must be a pair (real seconds, simulated minutes), got {anchor!r}")
    return _check_minutes("anchor[0]", anchor[0]), _check_minutes("anchor[1]", anchor[1])


class Pacer:
    """Waits until the real instant of each event, at a speed that can change.

    Args:
        clock: Where the time comes from and where it sleeps.
        speed: Simulated minutes per real minute, a positive finite number,
            or ``"max"`` (no waits).
        anchor: ``(w0, s0)``: the real second ``w0`` of the clock corresponds
            to the simulated minute ``s0``.

    Raises:
        ValueError: If ``speed`` or ``anchor`` is not valid.
    """

    def __init__(self, clock: Clock, speed: float | str, anchor: tuple[float, float]) -> None:
        self._clock = clock
        self._speed = check_speed(speed)
        self._anchor = _check_anchor(anchor)
        self._paused = False
        self._frozen = 0.0  # the simulated minute while paused
        self._last = self._anchor[1]  # sim_time of the last event released
        self._lag = 0.0

    @property
    def speed(self) -> float | str:
        """The current speed: a float or ``"max"``."""
        return self._speed

    @property
    def paused(self) -> bool:
        """Whether the pacer is paused."""
        return self._paused

    @property
    def anchor(self) -> tuple[float, float]:
        """The current anchor ``(w0, s0)``."""
        return self._anchor

    def sim_now(self) -> float:
        """The simulated minute now (``s_now``).

        Frozen while paused; at maximum speed, the ``sim_time`` of the last
        event released; otherwise, ``s0 + v * (now - w0) / 60``. When late, it
        may be ahead of the last event released.
        """
        if self._paused:
            return self._frozen
        if self._speed == MAX_SPEED:
            return self._last
        w0, s0 = self._anchor
        return s0 + self._speed * (self._clock.monotonic() - w0) / 60

    def target(self, sim_time: float) -> float:
        """Real instant of ``sim_time`` with the current anchor and finite speed.

        Raises:
            ValueError: At maximum speed, which has no target.
        """
        if self._speed == MAX_SPEED:
            raise ValueError("at maximum speed there is no target")
        w0, s0 = self._anchor
        return w0 + 60 * (sim_time - s0) / self._speed

    def lag(self) -> float:
        """Seconds between the target of the last event released and when it was released.

        0 if it was on time or at maximum speed.
        """
        return self._lag

    def set_speed(self, speed: float | str) -> None:
        """Change the speed, re-anchoring at the simulated minute now.

        While paused, only the speed changes: it does not resume.

        Raises:
            ValueError: If ``speed`` is not valid.
        """
        speed = check_speed(speed)
        if not self._paused:
            self._anchor = (self._clock.monotonic(), self.sim_now())
        self._speed = speed

    def pause(self) -> None:
        """Freeze the simulated clock. Nothing if already paused."""
        if not self._paused:
            self._frozen = self.sim_now()
            self._paused = True

    def resume(self) -> None:
        """Re-anchor at (now, the frozen minute). Nothing if not paused."""
        if self._paused:
            self._anchor = (self._clock.monotonic(), self._frozen)
            self._last = self._frozen
            self._paused = False

    def reanchor(self, sim_time: float) -> None:
        """Make ``sim_time`` the simulated minute now (the live run, at its start ``W``).

        Raises:
            ValueError: If ``sim_time`` is not a finite number.
        """
        sim_time = _check_minutes("sim_time", sim_time)
        if self._paused:
            self._frozen = sim_time
        else:
            self._anchor = (self._clock.monotonic(), sim_time)
        self._last = sim_time

    def apply(self, command: Command) -> bool:
        """Apply an order; ``True`` if it is ``parar``."""
        if command.order == STOP:
            return True
        if command.order == SPEED:
            self.set_speed(command.value)
        elif command.order == PAUSE:
            self.pause()
        elif command.order == RESUME:
            self.resume()
        return False

    def wait_until(self, sim_time: float, control: ControlSource) -> bool:
        """Wait until the real instant of ``sim_time``, attending the orders.

        Each turn of the loop asks ``control`` for one order and applies it,
        then: paused, sleeps one slice; at maximum speed, releases; otherwise
        releases if the target has come, or sleeps ``min(0.2, target -
        now)``. Never skips: it always ends by releasing or by stopping.

        Returns:
            ``True`` if a ``parar`` arrived (the event is not released);
            ``False`` when the event is released.

        Raises:
            ValueError: If ``sim_time`` is not a finite number.
        """
        sim_time = _check_minutes("sim_time", sim_time)
        clock = self._clock
        while True:
            command = control.poll()
            if command is not None and self.apply(command):
                return True
            if self._paused:
                clock.sleep(MAX_SLICE)
                continue
            if self._speed == MAX_SPEED:
                self._release(sim_time, 0.0)
                return False
            remaining = self.target(sim_time) - clock.monotonic()
            if remaining <= 0:
                self._release(sim_time, -remaining)
                return False
            clock.sleep(min(MAX_SLICE, remaining))

    def _release(self, sim_time: float, lag: float) -> None:
        self._last = sim_time
        self._lag = lag
