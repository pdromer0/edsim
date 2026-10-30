"""The three pools of the center, the priority key and the numbers of the boxes.

The pools are anonymous (ADR candidate 25): SimPy only counts how many
patients hold each resource. The log, however, needs the number of the box,
so that the occupancy of each box can be rebuilt from it. ``BoxNumbers`` keeps
the free numbers in a heap and always gives the lowest one, so the assignment
is deterministic, and knows who holds each box and with which level.

Task 3.4: the boxes are a ``PreemptiveResource`` and the doctors a
``PriorityResource``, both ordered by ``priority_key`` = (level, arrival);
only a level 1 displaces, and only patients of a higher level. The triage
nurses stay a FIFO ``Resource``: the level is not known before the triage.
Task 3.5 adds the shift reservations that lower the effective capacity of the
staff pools.
"""

import heapq
from dataclasses import dataclass

import simpy

from edsim.engine.center import CenterConfig

Priority = tuple[int, float]


def priority_key(level: int, arrival_time: float) -> Priority:
    """Priority of a patient for boxes and doctors: lower goes first.

    By level and, within a level, by arrival. SimPy breaks ties by the time of
    the request, but with the arrival inside the key the order is the one of
    the design even when the request comes late: a reassessment, or the box
    asked again after a displacement (docs/specs/hito-3.md).

    Args:
        level: Triage level, 1 (most urgent) to 5.
        arrival_time: ``sim_time`` of the patient's ``patient_arrived``.
    """
    return (level, arrival_time)


def should_displace(boxes: simpy.PreemptiveResource, level: int) -> bool:
    """Whether a box request of this level must be made with ``preempt=True``.

    Only a level 1, and only if some box is held by a level higher than 1.
    SimPy alone would also let a level 1 displace another level 1 who arrived
    later, because it only compares keys; a level 1 never displaces another.

    It reads ``boxes.users``, the requests SimPy counts as holders, and not
    ``BoxNumbers``: between SimPy granting a box and the patient resuming to
    take its number, in the same instant, the user is already in ``users``
    but has no number yet. Deciding with the numbers could let a level 1 wait
    while a level 3 already granted takes the box.

    Deciding once, when asking, is enough:

    - SimPy only displaces when it tries a request, and a new request with
      the lowest key is tried at once (``Put.__init__``), so with
      ``preempt=True`` it displaces and is granted in that same call: it
      never stays in the queue.
    - With ``preempt=False`` every box is held by a level 1. While it waits
      its key is lower than any level above 1, so every box freed goes to a
      level 1 first: no higher level can come in, and "every box held by a
      level 1" stays true until it gets one.
    """
    return level == 1 and any(request.priority[0] > 1 for request in boxes.users)


@dataclass(frozen=True, slots=True)
class Holder:
    """Who holds a box.

    Attributes:
        process: The patient's SimPy process; a box handed over after a
            displacement is kept for it.
        arrival_id: Arrival of the patient.
        level: Triage level of the patient.
    """

    process: simpy.Event
    arrival_id: int
    level: int


class BoxNumbers:
    """Box numbers 1 to ``n``: who holds each one and which are free.

    A min-heap gives the lowest free number in O(log n).
    ``list(range(1, n + 1))`` is already a heap, so it needs no ``heapify``.

    When a patient is displaced, its box is not freed: it is handed over to
    the process that displaced it, which takes that number when it resumes.
    Other events of the same instant can run between the interruption of the
    displaced patient and the resumption of the level 1, and one of them could
    free a lower number; the hand-over makes the level 1 get the box it took.

    Taking a number is only valid after the box request of SimPy has been
    granted, so there is always one; a failure here is a bug in the engine,
    not a wrong input, so it raises ``RuntimeError``.

    Args:
        n: Number of boxes.
    """

    def __init__(self, n: int) -> None:
        self._n = n
        self._free = list(range(1, n + 1))
        self._holders: dict[int, Holder | None] = {}  # taken boxes
        self._handed: dict[simpy.Event, int] = {}  # process → box kept for it

    def take(self, holder: Holder | None = None) -> int:
        """Take the box handed over to the holder's process, or the lowest free one."""
        if holder is not None and holder.process in self._handed:
            box = self._handed.pop(holder.process)
        elif self._free:
            box = heapq.heappop(self._free)
        else:
            raise RuntimeError("no free box number")
        self._holders[box] = holder
        return box

    def give(self, box: int) -> None:
        """Give back a box number taken before: it is free again."""
        self._check_taken(box)
        del self._holders[box]
        heapq.heappush(self._free, box)

    def hand_over(self, box: int, to: simpy.Event) -> None:
        """Keep a taken box for the process that displaced its holder."""
        self._check_taken(box)
        del self._holders[box]
        self._handed[to] = box

    def holder(self, box: int) -> Holder | None:
        """Who holds a box; ``None`` if it is free, handed over or taken without holder."""
        return self._holders.get(box)

    def _check_taken(self, box: int) -> None:
        if box not in self._holders:
            raise RuntimeError(f"box {box} cannot be given back: it was not taken")


@dataclass(frozen=True, slots=True)
class Pools:
    """The resources of one run.

    Attributes:
        nurses: Triage nurses (``enfermeria_triaje``), FIFO, held during the
            triage.
        doctors: Doctors (``medicos``), by priority without displacement,
            held during each assessment.
        boxes: Boxes, by priority with displacement by a level 1, held from
            ``box_assigned`` to ``patient_departed`` or ``patient_displaced``.
        box_numbers: Which box numbers are free and who holds the others.
        arrival_of: Arrival of each patient process inside, to name who
            displaced whom (``Preempted.by`` is a process).
    """

    nurses: simpy.Resource
    doctors: simpy.PriorityResource
    boxes: simpy.PreemptiveResource
    box_numbers: BoxNumbers
    arrival_of: dict[simpy.Event, int]


def make_pools(env: simpy.Environment, center: CenterConfig) -> Pools:
    """Create the pools: staff with the largest staff of its shifts, and the boxes.

    The capacity of a ``simpy.Resource`` cannot change. Task 3.5 will keep this
    maximum and lower the effective capacity with reservations; until then the
    largest staff of the day is on duty all day.
    """
    return Pools(
        nurses=simpy.Resource(env, capacity=max(center.triage_nurses)),
        doctors=simpy.PriorityResource(env, capacity=max(center.doctors)),
        boxes=simpy.PreemptiveResource(env, capacity=center.boxes),
        box_numbers=BoxNumbers(center.boxes),
        arrival_of={},
    )
