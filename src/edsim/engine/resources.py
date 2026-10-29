"""The three pools of the center and the numbers of the boxes.

The pools are anonymous (ADR candidate 25): SimPy only counts how many
patients hold each resource. The log, however, needs the number of the box,
so that the occupancy of each box can be rebuilt from it. ``BoxNumbers`` keeps
the free numbers in a heap and always gives the lowest one, so the assignment
is deterministic.

Task 3.3 has no priority, displacement or shifts: three FIFO
``simpy.Resource``, with the largest staff of the day. Task 3.4 turns the boxes
and the doctors into priority resources, and task 3.5 adds the shift
reservations that lower the effective capacity of the staff pools.
"""

import heapq
from dataclasses import dataclass

import simpy

from edsim.engine.center import CenterConfig


class BoxNumbers:
    """Free box numbers, 1 to ``n``; the lowest free one is given first.

    A min-heap gives the lowest number in O(log n). ``list(range(1, n + 1))``
    is already a heap, so it needs no ``heapify``.

    Taking a number is only valid after the box request of SimPy has been
    granted, so there is always a free number; a failure here is a bug in the
    engine, not a wrong input, so it raises ``RuntimeError``.

    Args:
        n: Number of boxes.
    """

    def __init__(self, n: int) -> None:
        self._n = n
        self._free = list(range(1, n + 1))
        self._is_free = [False] + [True] * n  # indexed by box number

    def take(self) -> int:
        """Take the lowest free box number."""
        if not self._free:
            raise RuntimeError("no free box number")
        box = heapq.heappop(self._free)
        self._is_free[box] = False
        return box

    def give(self, box: int) -> None:
        """Give back a box number taken before."""
        if not 1 <= box <= self._n or self._is_free[box]:
            raise RuntimeError(f"box {box} cannot be given back: it was not taken")
        self._is_free[box] = True
        heapq.heappush(self._free, box)


@dataclass(frozen=True, slots=True)
class Pools:
    """The resources of one run.

    Attributes:
        nurses: Triage nurses (``enfermeria_triaje``), held during the triage.
        doctors: Doctors (``medicos``), held during each assessment.
        boxes: Boxes, held from ``box_assigned`` to ``patient_departed``.
        box_numbers: Which box numbers are free.
    """

    nurses: simpy.Resource
    doctors: simpy.Resource
    boxes: simpy.Resource
    box_numbers: BoxNumbers


def make_pools(env: simpy.Environment, center: CenterConfig) -> Pools:
    """Create the pools: staff with the largest staff of its shifts, and the boxes.

    The capacity of a ``simpy.Resource`` cannot change. Task 3.5 will keep this
    maximum and lower the effective capacity with reservations; until then the
    largest staff of the day is on duty all day.
    """
    return Pools(
        nurses=simpy.Resource(env, capacity=max(center.triage_nurses)),
        doctors=simpy.Resource(env, capacity=max(center.doctors)),
        boxes=simpy.Resource(env, capacity=center.boxes),
        box_numbers=BoxNumbers(center.boxes),
    )
