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

Task 4.5a adds three checks: ``door`` (a triage at the door is a level 1
classified on arrival), ``schema_version`` (one version per log) and
``clinical`` (the clinical payloads of a log of version 2 against the clinical
ground truth, and the turnaround of each round against the shift band of its
order). Task 4.1 adds the triage queue to "nobody jumps the queue" and leaves the
triages at the door (a level 1, without a nurse) out of the capacity of the
nurses. Task 3.4 adds displacement: ``patient_displaced`` and interrupted assessments
are edges of ``TRANSITIONS``, ``patient_displaced`` frees the box in the
capacity check, and two checks follow the priority (level, arrival):
"nobody jumps the queue" and displacement. Task 3.5 compares the doctors and
nurses busy with the staff in force, read from ``staffing_changed``: the log
says which staff applies, without asking the configuration.
"""

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from edsim.engine.center import CenterConfig
from edsim.engine.events import CLINICAL_SCHEMA_VERSION, DOOR, Event
from edsim.engine.ground_truth import EpisodeTruth, GroundTruth
from edsim.profiles.config import TEST_TYPES, ClinicalProfiles
from edsim.profiles.context import context_indices

TURNAROUND_TOLERANCE = 1e-8
"""Minutes between the observed and the expected turnaround of a round.

``test_resulted - test_ordered`` comes from SimPy's ``env.now``, which adds
the turnaround to the instant of the order in floating point; over two weeks
the error is about 1e-12 minutes."""


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
        profiles: Clinical profiles of the run; with them and the ground truth,
            ``clinical`` checks the turnaround of each round against the shift
            band of its order. Without them that comparison is not made.
    """

    center: CenterConfig
    ground_truth: GroundTruth | None = None
    inside: int | None = None
    profiles: ClinicalProfiles | None = None


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
        # In the box, waiting for a doctor for the first assessment.
        "in_box": {
            ("assessment_started", "inicial"): "assessing",
            "patient_displaced": "waiting_box_initial",
        },
        "assessing": {
            ("assessment_ended", "inicial", False): "assessed",
            ("assessment_ended", "inicial", True): "cut_initial",
        },
        "cut_initial": {"patient_displaced": "waiting_box_initial"},
        "waiting_box_initial": {"box_assigned": "in_box"},
        # No yield between the end of the assessment and test_ordered or the
        # decision: no displacement in "assessed" nor in "decided".
        "assessed": {
            "test_ordered": "awaiting_tests",
            "disposition_decided": "decided",
        },
        "awaiting_tests": {
            "test_resulted": "tests_resulted",
            "patient_displaced": "waiting_box_tests",
        },
        # The tests keep running while the patient waits for a box.
        "waiting_box_tests": {
            "test_resulted": "waiting_box_reassessment",
            "box_assigned": "awaiting_tests",
        },
        # Results in, in the box, waiting for a doctor for the reassessment.
        "tests_resulted": {
            ("assessment_started", "reevaluacion"): "reassessing",
            "patient_displaced": "waiting_box_reassessment",
        },
        "waiting_box_reassessment": {"box_assigned": "tests_resulted"},
        "reassessing": {
            ("assessment_ended", "reevaluacion", False): "reassessed",
            ("assessment_ended", "reevaluacion", True): "cut_reassessment",
        },
        "cut_reassessment": {"patient_displaced": "waiting_box_reassessment"},
        "reassessed": {"disposition_decided": "decided"},
        "decided": {"patient_departed": "departed"},
        "departed": {},
    }
)
"""State machine of an episode: state → symbol → next state.

A displacement can happen in any state where the patient holds a box and the
process is stopped at a ``yield``: waiting for a doctor (``in_box``,
``tests_resulted``), in an assessment (``assessing``, ``reassessing``, which
first emit ``assessment_ended`` with ``interrumpida`` true) or waiting for the
tests (``awaiting_tests``). After it, the patient waits for a box in a
``waiting_box_*`` state that remembers the stage, and the next
``box_assigned`` takes it back to that stage, so an interrupted assessment
starts again with the same type.

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


@dataclass(slots=True)
class _StaffPool:
    """What ``check_capacity`` knows of one staff pool while reading the log."""

    recurso: str
    label: str
    largest: int
    staff: int | None = None  # in force; None before its first staffing_changed
    busy: int = 0
    unstaffed_reported: bool = False


def check_capacity(events: Sequence[Event], context: InvariantContext) -> list[Violation]:
    """No pool is used beyond its capacity.

    - Boxes: every ``box_assigned`` gives a number in 1..``boxes`` that is
      free, to an episode without a box; the box is freed by the episode's
      ``patient_departed`` or ``patient_displaced``, whose ``box`` must be
      the episode's. Assessments happen in the episode's box.
    - Doctors (``assessment_started`` to ``assessment_ended``) and triage
      nurses (``triage_started`` to ``triage_completed``), with the staff in
      force given by the last ``staffing_changed`` of the pool:

      - no triage or assessment starts with the pool already busy at the
        staff in force;
      - the busy never exceed the largest staff of the shifts (reported only
        when the staff in force does not already catch it: one error, one
        violation);
      - no triage or assessment starts before the first ``staffing_changed``
        of its pool (reported once per pool);
      - the ``anterior`` of each ``staffing_changed`` is the staff in force,
        0 for the first one.

      More busy than the staff after a staff goes down is not a violation:
      nobody is interrupted, the reservations wait for them to finish. Only
      a start is checked.

      A triage with ``circuito`` ``DOOR`` (a level 1 classified at the door)
      uses no nurse, so neither it nor its ``triage_completed`` counts.
    """
    name = "capacity"
    center = context.center
    nurses = _StaffPool("enfermeria_triaje", "triage nurses", max(center.triage_nurses))
    doctors = _StaffPool("medicos", "doctors", max(center.doctors))
    pools = {pool.recurso: pool for pool in (nurses, doctors)}
    out: list[Violation] = []
    occupant: dict[int, str] = {}
    box_of: dict[str, int] = {}
    at_the_door: set[str] = set()

    def start(e: Event, pool: _StaffPool) -> None:
        if pool.staff is None and not pool.unstaffed_reported:
            pool.unstaffed_reported = True
            out.append(
                _at(name, e, f"{e.event_type} before the first staffing_changed of {pool.recurso}")
            )
        if pool.staff is not None and pool.busy >= pool.staff:
            out.append(
                _at(
                    name,
                    e,
                    f"{e.event_type} with {pool.busy} {pool.label} busy, "
                    f"staff in force {pool.staff}",
                )
            )
        elif pool.busy + 1 > pool.largest:
            # Only when the staff in force allowed it: a staff above the largest
            # one, or no staff yet. Otherwise one error would give two violations.
            out.append(
                _at(
                    name,
                    e,
                    f"{pool.busy + 1} {pool.label} busy, above the largest staff {pool.largest}",
                )
            )
        pool.busy += 1

    for e in events:
        episode = e.episode_id
        match e.event_type:
            case "staffing_changed":
                pool = pools[e.payload["recurso"]]
                staff = 0 if pool.staff is None else pool.staff
                if e.payload["anterior"] != staff:
                    out.append(
                        _at(
                            name,
                            e,
                            f"staffing_changed of {pool.recurso} with anterior "
                            f"{e.payload['anterior']}, but the staff in force was {staff}",
                        )
                    )
                pool.staff = e.payload["nueva"]
            case "triage_started" if e.payload["circuito"] == DOOR:
                at_the_door.add(episode)
            case "triage_started":
                start(e, nurses)
            case "triage_completed" if episode in at_the_door:
                at_the_door.discard(episode)
            case "triage_completed":
                nurses.busy -= 1
            case "assessment_started":
                start(e, doctors)
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
                doctors.busy -= 1
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
            case "patient_displaced":
                box = box_of.pop(episode, None)
                if box != e.payload["box"]:
                    out.append(
                        _at(
                            name,
                            e,
                            f"displaced from box {e.payload['box']}, but the patient "
                            f"is in box {box}",
                        )
                    )
                if box is not None and occupant.get(box) == episode:
                    del occupant[box]
            case "patient_departed":
                box = box_of.pop(episode, None)
                if box is not None and occupant.get(box) == episode:
                    del occupant[box]
    return out


def _keys(events: Sequence[Event]) -> dict[str, tuple[int, float]]:
    """Priority (level, arrival) of each triaged episode, from its events."""
    arrival: dict[str, float] = {}
    keys: dict[str, tuple[int, float]] = {}
    for e in events:
        if e.event_type == "patient_arrived":
            arrival.setdefault(e.episode_id, e.sim_time)
        elif e.event_type == "triage_completed" and e.episode_id in arrival:
            keys[e.episode_id] = (e.payload["nivel"], arrival[e.episode_id])
    return keys


def check_nobody_jumps_the_queue(
    events: Sequence[Event], context: InvariantContext
) -> list[Violation]:
    """Boxes and doctors go by the key (level, arrival); the triage nurses, FIFO.

    The triage nurse goes by arrival, without the level, which is not known
    yet: when an episode starts a triage with ``circuito`` ``NURSE``, no
    other episode waiting for a triage since an earlier instant than it is
    still waiting. Everyone waits from ``patient_arrived`` to its
    ``triage_started``. A triage at the door (a level 1) is not checked: it
    takes no nurse, and the level 1 goes ahead of the queue by design.

    When an episode gets a box (``box_assigned``) or a doctor
    (``assessment_started``), no other episode waiting for that resource
    since an earlier instant has a lower key. Who waits, from the log:

    - for a box: from ``triage_completed`` or ``patient_displaced`` to
      ``box_assigned``;
    - for a doctor: holding a box with an assessment to do, from
      ``box_assigned`` or ``test_resulted`` to ``assessment_started`` or
      ``patient_displaced``.

    A wait that began in the same instant does not count: SimPy may have
    granted the resource before the other request was made, even if the
    events of the instant come in another order in the file.
    """
    name = "nobody_jumps_the_queue"
    keys = _keys(events)
    out: list[Violation] = []
    waiting: dict[str, dict[str, float]] = {"box": {}, "doctor": {}}  # episode → since
    waiting_triage: dict[str, float] = {}  # episode → arrival
    has_box: set[str] = set()
    to_assess: set[str] = set()  # an assessment is next in the box

    def check(e: Event, resource: str) -> None:
        mine = keys.get(e.episode_id)
        if mine is None:
            return
        for other, since in waiting[resource].items():
            if other != e.episode_id and since < e.sim_time and keys[other] < mine:
                out.append(
                    _at(
                        name,
                        e,
                        f"{e.episode_id} {keys[e.episode_id]} got a {resource} while "
                        f"{other} {keys[other]} waited for one since {since!r}",
                    )
                )
                return

    def check_triage(e: Event) -> None:
        mine = waiting_triage[e.episode_id]
        for other, since in waiting_triage.items():
            if since < mine:
                out.append(
                    _at(
                        name,
                        e,
                        f"{e.episode_id} (arrived at {mine!r}) got a triage while "
                        f"{other} waited for one since {since!r}",
                    )
                )
                return

    for e in events:
        episode = e.episode_id
        match e.event_type:
            case "patient_arrived":
                waiting_triage.setdefault(episode, e.sim_time)
            case "triage_started":
                if e.payload["circuito"] != DOOR and episode in waiting_triage:
                    check_triage(e)
                waiting_triage.pop(episode, None)
            case "triage_completed":
                waiting["box"][episode] = e.sim_time
                to_assess.add(episode)
            case "box_assigned":
                check(e, "box")
                waiting["box"].pop(episode, None)
                has_box.add(episode)
                if episode in to_assess:
                    waiting["doctor"][episode] = e.sim_time
            case "assessment_started":
                check(e, "doctor")
                waiting["doctor"].pop(episode, None)
                to_assess.discard(episode)
            case "assessment_ended" if e.payload["interrumpida"]:
                to_assess.add(episode)  # resumed when back in a box
            case "test_resulted":
                to_assess.add(episode)
                if episode in has_box:
                    waiting["doctor"][episode] = e.sim_time
            case "patient_displaced":
                has_box.discard(episode)
                waiting["doctor"].pop(episode, None)
                waiting["box"][episode] = e.sim_time
            case "patient_departed":
                has_box.discard(episode)
    return out


def check_displacement(events: Sequence[Event], context: InvariantContext) -> list[Violation]:
    """Only a level 1 displaces, only a higher level, and only when it must.

    - In every ``patient_displaced``, ``desalojado_por`` is a level 1, the
      displaced patient is of a higher level and its ``box`` is the one it
      held; the next ``box_assigned`` of the level 1 is that box, in the same
      instant.
    - At the end of every instant, a level 1 waiting for a box finds every
      box taken, and by levels 1. It is checked when the instant is over
      because a displacement takes several events of one instant
      (``triage_completed`` of the level 1, ``patient_displaced``, its
      ``box_assigned``). Each wait is reported once.
    """
    name = "displacement"
    keys = _keys(events)
    out: list[Violation] = []
    box_of: dict[str, int] = {}
    occupant: dict[int, str] = {}
    owed: dict[str, tuple[int, float]] = {}  # level 1 → box and instant it took
    level1_waiting: set[str] = set()
    reported: set[str] = set()

    def level(episode: str) -> int | None:
        key = keys.get(episode)
        return None if key is None else key[0]

    def end_of_instant(last: Event) -> None:
        for episode in sorted(level1_waiting - reported):
            if len(occupant) < context.center.boxes:
                free = context.center.boxes - len(occupant)
                problem = f"{free} free box(es)"
            else:
                higher = sorted(
                    (box, level(holder)) for box, holder in occupant.items() if level(holder) != 1
                )
                if not higher:
                    continue
                box, other = higher[0]
                problem = f"box {box} held by {occupant[box]}, level {other}"
            reported.add(episode)
            out.append(
                Violation(
                    name,
                    f"level 1 {episode} waits for a box with {problem}",
                    last.event_id,
                    episode,
                    last.sim_time,
                )
            )

    previous: Event | None = None
    for e in events:
        if previous is not None and e.sim_time != previous.sim_time:
            end_of_instant(previous)
        previous = e
        episode = e.episode_id
        match e.event_type:
            case "triage_completed" if e.payload["nivel"] == 1:
                level1_waiting.add(episode)
            case "box_assigned":
                box = e.payload["box"]
                level1_waiting.discard(episode)
                reported.discard(episode)
                if episode in owed:
                    expected, when = owed.pop(episode)
                    if (box, e.sim_time) != (expected, when):
                        out.append(
                            _at(
                                name,
                                e,
                                f"{episode} got box {box} at {e.sim_time!r}, but it "
                                f"displaced the patient of box {expected} at {when!r}",
                            )
                        )
                box_of[episode] = box
                occupant[box] = episode
            case "patient_displaced":
                by = e.payload["desalojado_por"]
                if level(by) != 1:
                    out.append(_at(name, e, f"displaced by {by}, of level {level(by)}, not 1"))
                if level(episode) == 1:
                    out.append(_at(name, e, f"{episode} of level 1 displaced by {by}"))
                held = box_of.pop(episode, None)
                if held != e.payload["box"]:
                    out.append(
                        _at(
                            name,
                            e,
                            f"{episode} displaced from box {e.payload['box']}, "
                            f"but it held box {held}",
                        )
                    )
                if held is not None and occupant.get(held) == episode:
                    del occupant[held]
                owed[by] = (e.payload["box"], e.sim_time)
            case "patient_departed":
                held = box_of.pop(episode, None)
                if held is not None and occupant.get(held) == episode:
                    del occupant[held]
    if previous is not None:
        end_of_instant(previous)

    for by, (box, when) in owed.items():
        out.append(
            Violation(
                name,
                f"{by} displaced the patient of box {box} at {when!r} but never got it",
                episode_id=by,
            )
        )
    return out


def check_door(events: Sequence[Event], context: InvariantContext) -> list[Violation]:
    """A triage at the door is the one of a level 1, in the instant it arrives.

    - A ``triage_started`` with ``circuito`` ``DOOR`` goes with a
      ``triage_completed`` of ``nivel`` 1, and a triage by a nurse with any
      other level: the door is decided by the assigned level, the one in the
      log.
    - At the door, ``triage_started`` and ``triage_completed`` happen in the
      instant of the ``patient_arrived``. Not the other way round: a triage by
      a nurse may also start in the instant of the arrival, when a nurse is
      free.
    """
    name = "door"
    out: list[Violation] = []
    arrival: dict[str, float] = {}
    at_the_door: dict[str, bool] = {}

    def on_arrival(e: Event, what: str) -> None:
        if e.episode_id in arrival and e.sim_time != arrival[e.episode_id]:
            out.append(
                _at(
                    name,
                    e,
                    f"{what} at the door at {e.sim_time!r}, not in the instant of the "
                    f"arrival {arrival[e.episode_id]!r}",
                )
            )

    for e in events:
        episode = e.episode_id
        match e.event_type:
            case "patient_arrived":
                arrival.setdefault(episode, e.sim_time)
            case "triage_started":
                at_the_door[episode] = e.payload["circuito"] == DOOR
                if at_the_door[episode]:
                    on_arrival(e, "triage_started")
            case "triage_completed" if episode in at_the_door:
                level = e.payload["nivel"]
                if at_the_door[episode]:
                    if level != 1:
                        out.append(_at(name, e, f"triage at the door with nivel {level}, not 1"))
                    on_arrival(e, "triage_completed")
                elif level == 1:
                    out.append(_at(name, e, "a level 1 triaged by a nurse, not at the door"))
    return out


def check_schema_version(events: Sequence[Event], context: InvariantContext) -> list[Violation]:
    """Every event of the log has the same ``schema_version``.

    Each event is valid in its own version, but a log is written by one
    ``EventLog``, with one version. The first event of another version than
    the first one gives one violation.
    """
    name = "schema_version"
    if not events:
        return []
    first = events[0].schema_version
    for e in events:
        if e.schema_version != first:
            versions = Counter(x.schema_version for x in events)
            counts = ", ".join(f"{v}: {n}" for v, n in sorted(versions.items()))
            return [
                _at(
                    name,
                    e,
                    f"schema_version {e.schema_version} in a log of version {first} "
                    f"(events by version: {counts})",
                )
            ]
    return []


def _results(truth: EpisodeTruth) -> dict[str, str]:
    """The ``resultados`` that the truth gives: the ordered types, normal or abnormal."""
    workup = truth.clinical.workup
    return {
        t: "alterado" if abnormal else "normal"
        for t, ordered, abnormal in zip(TEST_TYPES, workup.ordered, workup.abnormal, strict=True)
        if ordered
    }


def _expected_turnaround(
    truth: EpisodeTruth, ordered_at: float, ground_truth: GroundTruth, profiles: ClinicalProfiles
) -> float:
    """``max(factor_t(shift band of the order) * base_t)`` over the ordered types.

    Computed here on its own, from the profiles and the instant of the order
    in the log, not with ``ClinicalDraws``, so that an error there shows. Day
    0 of the ground truth is the ``start_date`` of the run.
    """
    start = ground_truth.days[0].date
    (band,), _, _ = context_indices([ordered_at], start, profiles.shift_band_starts)
    workup = truth.clinical.workup
    return max(
        test.turnaround_shift_factors[int(band)] * base
        for test, base, ordered in zip(
            profiles.diagnostic_tests, workup.turnarounds, workup.ordered, strict=True
        )
        if ordered
    )


def check_clinical(events: Sequence[Event], context: InvariantContext) -> list[Violation]:
    """The clinical payloads of a log of version 2 are the ones of its patients.

    Only for a log with events of version 2 (``CLINICAL_SCHEMA_VERSION``):

    - From the log alone: the types of ``resultados`` of each
      ``test_resulted`` are the ``pruebas`` of the episode's ``test_ordered``.
    - With a ground truth: a log of version 2 needs the clinical ground truth,
      and a log of version 1 the provisional one (one violation if not). The
      ``medio``, ``edad``, ``sexo``, ``nivel`` (the assigned level),
      ``motivo``, ``pruebas`` and ``resultados`` of each episode are the ones
      of its truth.
    - With a ground truth and the profiles: the observed turnaround of each
      round (``test_resulted`` minus ``test_ordered``) is the slowest ordered
      test with the factor of the shift band of the order, within
      ``TURNAROUND_TOLERANCE``.
    """
    name = "clinical"
    out: list[Violation] = []
    clinical_log = any(e.schema_version == CLINICAL_SCHEMA_VERSION for e in events)
    ground_truth = context.ground_truth
    truth: dict[str, EpisodeTruth] = {}
    if ground_truth is not None:
        kinds = {e.clinical is not None for e in ground_truth.episodes}
        if clinical_log and False in kinds:
            out.append(Violation(name, "a log of version 2 with a provisional ground truth"))
            return out
        if not clinical_log and True in kinds:
            out.append(Violation(name, "a log of version 1 with a clinical ground truth"))
            return out
        truth = {e.episode_id: e for e in ground_truth.episodes}
    if not clinical_log:
        return out

    def differs(e: Event, key: str, logged: object, expected: object) -> None:
        if logged != expected:
            out.append(_at(name, e, f"{key} {logged!r} in the log, {expected!r} in the truth"))

    ordered: dict[str, Event] = {}
    for e in events:
        if e.schema_version != CLINICAL_SCHEMA_VERSION:
            continue  # reported by schema_version
        episode = e.episode_id
        mine = truth.get(episode)
        payload = e.payload
        match e.event_type:
            case "patient_arrived" if mine is not None:
                medio = "ambulancia" if mine.clinical.person.ambulance else "propios_medios"
                differs(e, "medio", payload["medio"], medio)
            case "patient_registered" if mine is not None:
                differs(e, "edad", payload["edad"], mine.clinical.person.age)
                differs(
                    e, "sexo", payload["sexo"], "mujer" if mine.clinical.person.female else "hombre"
                )
            case "triage_completed" if mine is not None:
                differs(e, "nivel", payload["nivel"], mine.level)
                differs(e, "motivo", payload["motivo"], mine.clinical.reason)
            case "test_ordered":
                ordered[episode] = e
                if mine is not None:
                    pruebas = tuple(
                        t
                        for t, o in zip(TEST_TYPES, mine.clinical.workup.ordered, strict=True)
                        if o
                    )
                    differs(e, "pruebas", payload["pruebas"], pruebas)
            case "test_resulted":
                order = ordered.get(episode)
                if order is None:
                    continue  # reported by transitions
                if tuple(payload["resultados"]) != order.payload["pruebas"]:
                    out.append(
                        _at(
                            name,
                            e,
                            f"resultados of {list(payload['resultados'])}, but the tests "
                            f"ordered were {list(order.payload['pruebas'])}",
                        )
                    )
                if mine is None:
                    continue
                differs(e, "resultados", dict(payload["resultados"]), _results(mine))
                if context.profiles is not None and mine.clinical.workup.has_round:
                    observed = e.sim_time - order.sim_time
                    expected = _expected_turnaround(
                        mine, order.sim_time, ground_truth, context.profiles
                    )
                    if abs(observed - expected) > TURNAROUND_TOLERANCE:
                        out.append(
                            _at(
                                name,
                                e,
                                f"turnaround {observed!r} of the tests ordered at "
                                f"{order.sim_time!r}, expected {expected!r} with the "
                                "shift band of the order",
                            )
                        )
    return out


CHECKS: Mapping[str, Check] = MappingProxyType(
    {
        "conservation": check_conservation,
        "time": check_time,
        "transitions": check_transitions,
        "capacity": check_capacity,
        "nobody_jumps_the_queue": check_nobody_jumps_the_queue,
        "displacement": check_displacement,
        "door": check_door,
        "schema_version": check_schema_version,
        "clinical": check_clinical,
    }
)
"""The invariants, by name, in the order ``check_invariants`` runs them."""


def check_invariants(
    events: Iterable[Event],
    center: CenterConfig,
    *,
    ground_truth: GroundTruth | None = None,
    inside: int | None = None,
    profiles: ClinicalProfiles | None = None,
) -> list[Violation]:
    """Run every check of ``CHECKS`` on a log.

    Args:
        events: The events in file order, such as ``MemorySink.events`` or
            ``read_events(path)``; read once into a list.
        center: Configuration of the run.
        ground_truth: Ground truth of the run, to compare the arrivals with.
        inside: Patient processes alive in SimPy at the end of the run, to
            compare with the patients inside according to the log.
        profiles: Clinical profiles of the run, to check the turnaround of
            each round of a clinical log; needs the ground truth.

    Returns:
        The violations, by check and then in file order; empty if none.
    """
    events = list(events)
    context = InvariantContext(center, ground_truth, inside, profiles)
    return [v for check in CHECKS.values() for v in check(events, context)]
