"""Invariants of the event log: logic errors that no run may have.

Each check is a pure function that reads the events, in file order, and
returns the violations it finds; it never raises. They are the first level of
the validation of the engine (docs/specs/hito-3.md): any run must have zero
violations, and each check must catch a log broken on purpose.

Every check has the same signature, ``check(events, context)``, and is
registered in ``CHECKS``. The context carries the center and, optionally,
sources that do not come from the log (the ground truth, the patient processes
still alive in SimPy). Comparing with them is what makes conservation a real
check: counting arrivals, departures and patients inside from the log alone
would be true by construction.

Milestone 3.3 has no priority, displacement or shifts. Task 3.4 adds the checks
"nobody jumps the queue" and displacement as new entries of ``CHECKS``, and
``patient_displaced`` and interrupted assessments as new edges of
``TRANSITIONS``; task 3.5 will compare with the staffing in force instead of
the maximum.
"""

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from edsim.engine.center import CenterConfig
from edsim.engine.events import Event
from edsim.engine.ground_truth import GroundTruth


@dataclass(frozen=True, slots=True)
class Violation:
    """One broken invariant.

    Attributes:
        check: Name of the check in ``CHECKS``.
        message: What is wrong.
        event_id: Event where it was found, or ``None`` if it is about the
            whole log (such as an episode of the ground truth missing in it).
        episode_id: Episode concerned, if any.
        sim_time: ``sim_time`` of the event, if any.
    """

    check: str
    message: str
    event_id: str | None = None
    episode_id: str | None = None
    sim_time: float | None = None


def _at(check: str, event: Event, message: str) -> Violation:
    return Violation(check, message, event.event_id, event.episode_id, event.sim_time)


@dataclass(frozen=True, slots=True)
class InvariantContext:
    """What the checks know besides the events.

    Attributes:
        center: Configuration of the run: boxes and staff.
        ground_truth: Ground truth of the run; if given, every episode in it
            must have exactly one ``patient_arrived`` in the log, and no other.
        inside: Patient processes still alive in SimPy at the end of the run;
            if given, it must equal the patients inside according to the log.
    """

    center: CenterConfig
    ground_truth: GroundTruth | None = None
    inside: int | None = None


Check = Callable[[Sequence[Event], InvariantContext], list[Violation]]


def check_conservation(events: Sequence[Event], context: InvariantContext) -> list[Violation]:
    """Patients neither appear nor vanish.

    - The census (arrivals minus departures) is never negative.
    - No episode arrives or departs twice, nor departs without arriving.
    - With a ground truth: each of its episodes has exactly one
      ``patient_arrived``, and the log has no arrival outside it.
    - With ``inside``: the patients inside at the end according to the log
      (arrived and not departed) are as many as the processes alive in SimPy.
    """
    name = "conservation"
    out: list[Violation] = []
    arrived: set[str] = set()
    departed: set[str] = set()
    arrivals: Counter[str] = Counter()
    census = 0

    for e in events:
        if e.event_type == "patient_arrived":
            if e.episode_id in arrived:
                out.append(_at(name, e, f"repeated patient_arrived of {e.episode_id}"))
            arrived.add(e.episode_id)
            arrivals[e.episode_id] += 1
            census += 1
        elif e.event_type == "patient_departed":
            if e.episode_id not in arrived:
                out.append(_at(name, e, "patient_departed without patient_arrived"))
            if e.episode_id in departed:
                out.append(_at(name, e, f"repeated patient_departed of {e.episode_id}"))
            departed.add(e.episode_id)
            census -= 1
            if census < 0:
                out.append(_at(name, e, f"negative census: {census}"))

    if context.ground_truth is not None:
        expected = [episode.episode_id for episode in context.ground_truth.episodes]
        for episode in expected:
            if arrivals[episode] != 1:
                out.append(
                    Violation(
                        name,
                        f"{episode} of the ground truth has {arrivals[episode]} "
                        "patient_arrived in the log, not 1",
                        episode_id=episode,
                    )
                )
        for episode in sorted(arrivals.keys() - set(expected)):
            out.append(
                Violation(
                    name,
                    f"{episode} arrived in the log but is not in the ground truth",
                    episode_id=episode,
                )
            )

    if context.inside is not None:
        inside = len(arrived - departed)
        if inside != context.inside:
            out.append(
                Violation(
                    name,
                    f"{inside} patients inside at the end according to the log, "
                    f"but {context.inside} patient processes alive in SimPy",
                )
            )
    return out


def check_time(events: Sequence[Event], context: InvariantContext) -> list[Violation]:
    """Time goes forward.

    - ``sim_time`` never decreases in file order.
    - The first event of each episode is its ``patient_arrived``, and no event
      of the episode has a ``sim_time`` before it.
    """
    name = "time"
    out: list[Violation] = []
    previous: float | None = None
    arrival: dict[str, float] = {}

    for e in events:
        if previous is not None and e.sim_time < previous:
            out.append(_at(name, e, f"sim_time decreased: {e.sim_time!r} after {previous!r}"))
        previous = e.sim_time

        if e.episode_id is None:
            continue
        if e.episode_id not in arrival:
            if e.event_type == "patient_arrived":
                arrival[e.episode_id] = e.sim_time
            else:
                out.append(_at(name, e, f"{e.event_type} before its patient_arrived"))
        elif e.sim_time < arrival[e.episode_id]:
            out.append(
                _at(
                    name,
                    e,
                    f"{e.event_type} at {e.sim_time!r}, before the arrival at "
                    f"{arrival[e.episode_id]!r}",
                )
            )
    return out


# The symbol of an event is its type, with the type of assessment and whether
# it was interrupted for the assessment events: the automaton tells the first
# assessment from the reassessment.
Symbol = str | tuple[str, str] | tuple[str, str, bool]

TRANSITIONS: Mapping[str, Mapping[Symbol, str]] = MappingProxyType(
    {
        "start": {"patient_arrived": "arrived"},
        "arrived": {"patient_registered": "registered"},
        "registered": {"triage_started": "in_triage"},
        "in_triage": {"triage_completed": "triaged"},
        "triaged": {"box_assigned": "in_box"},
        "in_box": {("assessment_started", "inicial"): "assessing"},
        "assessing": {("assessment_ended", "inicial", False): "assessed"},
        "assessed": {
            "test_ordered": "awaiting_tests",
            "disposition_decided": "decided",
        },
        "awaiting_tests": {"test_resulted": "tests_resulted"},
        "tests_resulted": {("assessment_started", "reevaluacion"): "reassessing"},
        "reassessing": {("assessment_ended", "reevaluacion", False): "reassessed"},
        "reassessed": {"disposition_decided": "decided"},
        "decided": {"patient_departed": "departed"},
        "departed": {},
    }
)
"""State machine of an episode without displacement: state → symbol → next state.

There is no final state: a run cut by the horizon leaves episodes anywhere,
and a prefix of a valid path is valid.
"""


def _symbol(e: Event) -> Symbol:
    if e.event_type == "assessment_started":
        return (e.event_type, e.payload["tipo"])
    if e.event_type == "assessment_ended":
        return (e.event_type, e.payload["tipo"], e.payload["interrumpida"])
    return e.event_type


def check_transitions(events: Sequence[Event], context: InvariantContext) -> list[Violation]:
    """The events of each episode follow ``TRANSITIONS``.

    After the first invalid event of an episode, the rest of the episode is not
    checked: one error gives one violation, not a cascade. The ``destino`` of
    ``patient_departed`` must also be the one of ``disposition_decided``.
    """
    name = "transitions"
    out: list[Violation] = []
    state: dict[str, str] = {}
    broken: set[str] = set()
    destination: dict[str, object] = {}

    for e in events:
        episode = e.episode_id
        if episode is None or episode in broken:
            continue
        current = state.get(episode, "start")
        symbol = _symbol(e)
        following = TRANSITIONS[current].get(symbol)
        if following is None:
            out.append(_at(name, e, f"{symbol!r} is not valid in state {current!r}"))
            broken.add(episode)
            continue
        state[episode] = following

        if e.event_type == "disposition_decided":
            destination[episode] = e.payload["destino"]
        elif e.event_type == "patient_departed" and e.payload["destino"] != destination[episode]:
            out.append(
                _at(
                    name,
                    e,
                    f"patient_departed with destino {e.payload['destino']!r}, "
                    f"but disposition_decided said {destination[episode]!r}",
                )
            )
    return out


def check_capacity(events: Sequence[Event], context: InvariantContext) -> list[Violation]:
    """No pool is used beyond its capacity.

    - Boxes: every ``box_assigned`` gives a number in 1..``boxes`` that is
      free, to an episode without a box; the box is freed by the episode's
      ``patient_departed``. Assessments happen in the episode's box.
    - Doctors (``assessment_started`` to ``assessment_ended``) and triage
      nurses (``triage_started`` to ``triage_completed``) busy never exceed
      the largest staff of their shifts. Without shifts, in task 3.3, that is
      the capacity of the pool.
    """
    name = "capacity"
    center = context.center
    doctors, nurses = max(center.doctors), max(center.triage_nurses)
    out: list[Violation] = []
    occupant: dict[int, str] = {}
    box_of: dict[str, int] = {}
    busy_doctors = busy_nurses = 0

    for e in events:
        episode = e.episode_id
        match e.event_type:
            case "triage_started":
                busy_nurses += 1
                if busy_nurses > nurses:
                    out.append(_at(name, e, f"{busy_nurses} triage nurses busy, capacity {nurses}"))
            case "triage_completed":
                busy_nurses -= 1
            case "assessment_started":
                busy_doctors += 1
                if busy_doctors > doctors:
                    out.append(_at(name, e, f"{busy_doctors} doctors busy, capacity {doctors}"))
                box = e.payload["box"]
                if box_of.get(episode) != box:
                    out.append(
                        _at(
                            name,
                            e,
                            f"assessment in box {box}, but the patient is in "
                            f"box {box_of.get(episode)}",
                        )
                    )
            case "assessment_ended":
                busy_doctors -= 1
            case "box_assigned":
                box = e.payload["box"]
                if not 1 <= box <= center.boxes:
                    out.append(_at(name, e, f"box {box} out of range 1..{center.boxes}"))
                if box in occupant:
                    out.append(_at(name, e, f"box {box} already taken by {occupant[box]}"))
                if episode in box_of:
                    out.append(_at(name, e, f"{episode} already in box {box_of[episode]}"))
                occupant[box] = episode
                box_of[episode] = box
            case "patient_departed":
                box = box_of.pop(episode, None)
                if box is not None and occupant.get(box) == episode:
                    del occupant[box]
    return out


CHECKS: Mapping[str, Check] = MappingProxyType(
    {
        "conservation": check_conservation,
        "time": check_time,
        "transitions": check_transitions,
        "capacity": check_capacity,
    }
)
"""The invariants, by name, in the order ``check_invariants`` runs them."""


def check_invariants(
    events: Iterable[Event],
    center: CenterConfig,
    *,
    ground_truth: GroundTruth | None = None,
    inside: int | None = None,
) -> list[Violation]:
    """Run every check of ``CHECKS`` on a log.

    Args:
        events: The events in file order, such as ``MemorySink.events`` or
            ``read_events(path)``; read once into a list.
        center: Configuration of the run.
        ground_truth: Ground truth of the run, to compare the arrivals with.
        inside: Patient processes alive in SimPy at the end of the run, to
            compare with the patients inside according to the log.

    Returns:
        The violations, by check and then in file order; empty if none.
    """
    events = list(events)
    context = InvariantContext(center, ground_truth, inside)
    return [v for check in CHECKS.values() for v in check(events, context)]
