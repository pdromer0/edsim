"""Shifts: the staff of each instant and the reservations that apply it.

Three shifts a day start at ``center.shift_starts`` (8, 15 and 22 h by
default); the last one runs past midnight, so day 0 starts at 0:00 in the
night shift that began at 22 h the day before (docs/specs/hito-3.md, "Turnos,
calentamiento y horizonte").

The capacity of a SimPy resource cannot change. Each staff pool is created
with the largest staff of its shifts, and the places left over in a shift are
taken by **reservations**: requests with ``RESERVATION_PRIORITY``, ahead of any
patient and without displacement. When the staff goes down, a reservation
waits for a professional to finish, so nobody is cut in the middle of a triage
or an assessment. When it goes up, reservations are removed:

- one still waiting is **cancelled** (``request.cancel()``);
- one already granted is **released** (``resource.release(request)``), and
  SimPy gives the place to the head of the queue when it processes the
  release, in the same instant.

``release()`` of a waiting request does nothing, and the request would take a
place later: a ghost reservation that leaves the staff short. That is why the
two cases are told apart, with ``request.triggered`` as ``cancel()`` itself
does (tests/test_simpy_contract.py).

Nothing here draws random numbers: shifts consume no stream.
"""

from bisect import bisect_right
from collections.abc import Sequence

import simpy

from edsim.arrivals.rate import MINUTES_PER_DAY
from edsim.engine.resources import RESERVATION_PRIORITY

MINUTES_PER_HOUR = 60


def shift_at(starts: Sequence[int], minute: float) -> int:
    """Index of the shift in force at ``minute`` of the run.

    The shift of an instant is the last one that started at or before its
    hour of the day. Before the first start of the day it is still the last
    shift, which began the day before: with starts (8, 15, 22), minute 0 is in
    the night (index 2).

    Args:
        starts: Starting hour of each shift, strictly increasing, in 0-23.
        minute: Minutes since the start of the run, at least 0.
    """
    hour = (minute % MINUTES_PER_DAY) / MINUTES_PER_HOUR
    return (bisect_right(starts, hour) - 1) % len(starts)


def shift_changes(starts: Sequence[int], days: int) -> list[tuple[float, int]]:
    """``(minute, shift)`` of every start of a shift in ``(0, days · 1440)``, in order.

    Minute 0 is left out, because the start of the run sets the staff in force
    then; so is the horizon, which does not happen. The minutes are whole
    hours, exact as floats.
    """
    horizon = days * MINUTES_PER_DAY
    changes = [
        (float(day * MINUTES_PER_DAY + hour * MINUTES_PER_HOUR), shift)
        for day in range(days)
        for shift, hour in enumerate(starts)
    ]
    return [(t, shift) for t, shift in changes if 0 < t < horizon]


class Reservations:
    """The shift reservations of one staff pool.

    The effective capacity, ``staff``, is the capacity of the resource minus
    the reservations held, granted or waiting: a waiting reservation already
    counts, because it will take the next place that is freed.

    Args:
        resource: A staff pool, created with the largest staff of its shifts.
    """

    def __init__(self, resource: simpy.PriorityResource) -> None:
        self._resource = resource
        self._held: list[simpy.resources.resource.PriorityRequest] = []

    @property
    def staff(self) -> int:
        """Staff in force: capacity minus reservations."""
        return self._resource.capacity - len(self._held)

    @property
    def granted(self) -> int:
        """Reservations that hold a place."""
        return sum(r.triggered for r in self._held)

    @property
    def waiting(self) -> int:
        """Reservations waiting for a professional to finish."""
        return len(self._held) - self.granted

    def set_staff(self, staff: int) -> None:
        """Make ``staff`` the staff in force, with as many reservations as places left over.

        Going down adds reservations; those that find no free place wait at
        the head of the queue. Going up cancels first the reservations still
        waiting and then releases granted ones, the latest first, so that no
        waiting one is left behind to take a place later.

        Raises:
            RuntimeError: If ``staff`` is not in 1..capacity: a bug in the
                engine, since the center only allows such staffs.
        """
        capacity = self._resource.capacity
        if not 1 <= staff <= capacity:
            raise RuntimeError(f"staff {staff} out of range 1..{capacity}")
        target = capacity - staff
        while len(self._held) < target:
            # PriorityResource ignores preempt; False says that a reservation
            # never displaces.
            request = self._resource.request(priority=RESERVATION_PRIORITY, preempt=False)
            self._held.append(request)
        excess = len(self._held) - target
        waiting = [r for r in reversed(self._held) if not r.triggered]
        granted = [r for r in reversed(self._held) if r.triggered]
        for request in (waiting + granted)[:excess]:
            if request.triggered:
                self._resource.release(request)
            else:
                request.cancel()
            self._held.remove(request)
