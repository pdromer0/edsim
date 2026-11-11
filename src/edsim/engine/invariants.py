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

Task 5.1 adds the outcome of milestone 5, only for events of version 4
(``OUTCOME_SCHEMA_VERSION``), so that a log of versions 1 to 3 gives exactly
the violations it gave before: ``patient_left_wbs`` closes an episode in
``conservation`` and ``time`` and frees the box in ``capacity`` and
``displacement``; ``transitions`` follows ``TRANSITIONS_V4``, with the
abandonment before being seen and the wait for a bed in the box or in the
corridor; and two checks are new, ``abandonment`` and ``outcome``. Task 5.3
compares them with the ground truth of the outcome: each abandonment at its
deadline (or at the end of its triage), nobody seen after it nor still waiting
with it passed, the drawn destination and each wait for a bed with the factors
of the center.
Task 4.6a adds the results room (ADR candidate 45): ``box_released`` is an
edge of ``TRANSITIONS`` from the wait for the tests to a room where the
patient holds no box; it frees the box in the capacity and displacement
checks; the box wait after the room counts in "nobody jumps the queue", with
the same key; and ``results_wait`` checks, in logs of version 3, that exactly
the levels of ``espera_resultados_fuera`` leave the box when they order tests.
Task 4.5a adds three checks: ``door`` (a triage at the door is a level 1
classified on arrival), ``schema_version`` (one version per log) and
``clinical`` (the clinical payloads of a clinical log, version 2 or 3, against
the clinical ground truth, and the turnaround of each round against the shift
band of its order). Task 4.1 adds the triage queue to "nobody jumps the queue" and leaves the
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
from datetime import date
from types import MappingProxyType

from edsim.arrivals.rate import MINUTES_PER_DAY
from edsim.engine.center import CenterConfig
from edsim.engine.events import (
    CLINICAL_SCHEMA_VERSIONS,
    CURRENT_CLINICAL_SCHEMA_VERSION,
    DOOR,
    OUTCOME_SCHEMA_VERSION,
    TERMINAL_EVENTS,
    Event,
)
from edsim.engine.ground_truth import EpisodeTruth, GroundTruth
from edsim.profiles.config import TEST_TYPES, ClinicalProfiles
from edsim.profiles.context import context_indices

_RESULTS_ROOM_VERSIONS = frozenset({CURRENT_CLINICAL_SCHEMA_VERSION, OUTCOME_SCHEMA_VERSION})
"""Versions whose model has the results room: 3 (milestone 4) and 4 (milestone 5)."""


def _v4(e: Event) -> bool:
    """Whether an event is of version 4, the one of the outcome of milestone 5."""
    return e.schema_version == OUTCOME_SCHEMA_VERSION


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
      "Departs" is any terminal event of the version of the event
      (``TERMINAL_EVENTS``): ``patient_departed`` and, in version 4, also
      ``patient_left_wbs``. An episode has one terminal event.
    - With a ground truth: each of its episodes has exactly one
      ``patient_arrived``, and the log has no arrival outside it.
    - With ``inside``: the patients inside at the end according to the log
      (arrived and not departed) are as many as the processes alive in SimPy.
    """
    name = "conservation"
    out: list[Violation] = []
    arrived: set[str] = set()
    closed: dict[str, str] = {}  # episode → its first terminal event
    arrivals: Counter[str] = Counter()
    census = 0

    for e in events:
        if e.event_type == "patient_arrived":
            if e.episode_id in arrived:
                out.append(_at(name, e, f"repeated patient_arrived of {e.episode_id}"))
            arrived.add(e.episode_id)
            arrivals[e.episode_id] += 1
            census += 1
        elif e.event_type in TERMINAL_EVENTS[e.schema_version]:
            if e.episode_id not in arrived:
                out.append(_at(name, e, f"{e.event_type} without patient_arrived"))
            first = closed.get(e.episode_id)
            if first == e.event_type:
                out.append(_at(name, e, f"repeated {e.event_type} of {e.episode_id}"))
            elif first is not None:
                out.append(_at(name, e, f"{e.event_type} of {e.episode_id} after its {first}"))
            closed.setdefault(e.episode_id, e.event_type)
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
        inside = len(arrived - closed.keys())
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
    - Version 4: no event of the episode comes after its terminal event
      (``TERMINAL_EVENTS``), reported once per episode. A second terminal
      event is reported by ``conservation``.
    """
    name = "time"
    out: list[Violation] = []
    previous: float | None = None
    arrival: dict[str, float] = {}
    closed: dict[str, str] = {}  # version 4: episode → its terminal event
    reported: set[str] = set()

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

        if not _v4(e):
            continue
        terminal = e.event_type in TERMINAL_EVENTS[e.schema_version]
        if e.episode_id in closed:
            if not terminal and e.episode_id not in reported:
                reported.add(e.episode_id)
                out.append(
                    _at(
                        name,
                        e,
                        f"{e.event_type} of {e.episode_id} after its {closed[e.episode_id]}",
                    )
                )
        elif terminal:
            closed[e.episode_id] = e.event_type
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
            # Results room (task 4.6a): the patient leaves the box right after
            # test_ordered and holds no box until the results are in.
            "box_released": "results_room",
        },
        # In the room, waiting for the results without a box: it cannot be
        # displaced, and it asks for a box again only with the results.
        "results_room": {"test_resulted": "waiting_box_reassessment"},
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

With the results room (task 4.6a), ``box_released`` takes a patient that has
just ordered its tests to ``results_room``; only ``test_resulted`` leaves it,
to ``waiting_box_reassessment``, so the patient is back in a box only after
its results, and the reassessment is always in a box.

There is no final state: a run cut by the horizon leaves episodes anywhere,
and a prefix of a valid path is valid.
"""


_DECISIONS_V4: Mapping[Symbol, str] = MappingProxyType(
    {
        ("disposition_decided", "alta"): "decided",
        ("disposition_decided", "ingreso"): "admission_decided",
        ("disposition_decided", "traslado"): "decided",
        ("disposition_decided", "exitus"): "decided",
    }
)

TRANSITIONS_V4: Mapping[str, Mapping[Symbol, str]] = MappingProxyType(
    {
        **TRANSITIONS,
        # Waiting for a triage nurse: the patient may leave.
        "registered": {"triage_started": "in_triage", "patient_left_wbs": "left"},
        # Triaged, waiting for a box: the patient may leave.
        "triaged": {"box_assigned": "in_box", "patient_left_wbs": "left"},
        # In the box without being seen, waiting for the first doctor: it may
        # leave, and a displacement takes it back to a wait where it still may.
        "in_box": {
            ("assessment_started", "inicial"): "assessing",
            "patient_displaced": "waiting_box_unseen",
            "patient_left_wbs": "left",
        },
        "waiting_box_unseen": {"box_assigned": "in_box", "patient_left_wbs": "left"},
        # Seen (its first assessment started and was cut): it never leaves.
        "waiting_box_initial": {"box_assigned": "in_box_seen"},
        "in_box_seen": {
            ("assessment_started", "inicial"): "assessing",
            "patient_displaced": "waiting_box_initial",
        },
        "assessed": {"test_ordered": "awaiting_tests", **_DECISIONS_V4},
        "reassessed": dict(_DECISIONS_V4),
        # Admitted: it asks for a bed in the instant of the decision and waits
        # for it in its box or, displaced by a level 1, in the corridor.
        "admission_decided": {"bed_requested": "waiting_bed"},
        "waiting_bed": {"bed_assigned": "bed_ready", "patient_displaced": "corridor"},
        "corridor": {"bed_assigned": "bed_ready"},
        "bed_ready": {"patient_departed": "departed"},
        "left": {},
    }
)
"""State machine of an episode of version 4 (task 5.1): ``TRANSITIONS`` plus the outcome.

The waits before being seen (``registered``, ``triaged``, ``in_box`` and
``waiting_box_unseen``) may end in ``patient_left_wbs``; once the first
assessment has started, the states are others (``in_box_seen``,
``waiting_box_initial``) without it. The decision goes by its destination:
discharge, transfer and death depart at once; admission asks for a bed and
departs only with ``bed_assigned``, without another box after a displacement.
"""


def _symbol(e: Event) -> Symbol:
    if e.event_type == "assessment_started":
        return (e.event_type, e.payload["tipo"])
    if e.event_type == "assessment_ended":
        return (e.event_type, e.payload["tipo"], e.payload["interrumpida"])
    if e.event_type == "disposition_decided" and _v4(e):
        return (e.event_type, e.payload["destino"])
    return e.event_type


def check_transitions(events: Sequence[Event], context: InvariantContext) -> list[Violation]:
    """The events of each episode follow ``TRANSITIONS``, or ``TRANSITIONS_V4`` in version 4.

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
        table = TRANSITIONS_V4 if _v4(e) else TRANSITIONS
        # A log that mixes versions (reported by schema_version) may bring an
        # event of versions 1 to 3 to a state that only version 4 has.
        following = table.get(current, {}).get(symbol)
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
      ``patient_departed``, ``patient_displaced`` or ``box_released``, whose
      ``box`` must be the episode's, and, in version 4, by its
      ``patient_left_wbs`` from the box. Assessments happen in the episode's box.
      A patient in the results room holds no box.
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
            case "patient_displaced" | "box_released":
                what = "displaced from" if e.event_type == "patient_displaced" else "released"
                box = box_of.pop(episode, None)
                if box != e.payload["box"]:
                    out.append(
                        _at(
                            name,
                            e,
                            f"{what} box {e.payload['box']}, but the patient is in box {box}",
                        )
                    )
                if box is not None and occupant.get(box) == episode:
                    del occupant[box]
            case "patient_departed" | "patient_left_wbs":
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

    - for a box: from ``triage_completed``, ``patient_displaced`` or, after
      the results room, ``test_resulted`` to ``box_assigned``, always with
      the key of the arrival;
    - for a doctor: holding a box with an assessment to do, from
      ``box_assigned`` or ``test_resulted`` to ``assessment_started`` or
      ``patient_displaced``.

    In version 4, a patient who leaves (``patient_left_wbs``) stops waiting,
    and an admitted patient displaced from its box waits for its bed in the
    corridor, not for a box.

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
    in_room: set[str] = set()  # waiting for the results outside the box
    to_assess: set[str] = set()  # an assessment is next in the box
    admitted: set[str] = set()  # version 4: asked for a bed

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
                elif episode in in_room:
                    in_room.discard(episode)
                    waiting["box"][episode] = e.sim_time
            case "patient_displaced":
                has_box.discard(episode)
                waiting["doctor"].pop(episode, None)
                if episode not in admitted:
                    waiting["box"][episode] = e.sim_time
            case "box_released":
                has_box.discard(episode)
                in_room.add(episode)
            case "patient_departed":
                has_box.discard(episode)
            case "patient_left_wbs":
                waiting_triage.pop(episode, None)
                waiting["box"].pop(episode, None)
                waiting["doctor"].pop(episode, None)
                has_box.discard(episode)
                to_assess.discard(episode)
            case "bed_requested":
                admitted.add(episode)
    return out


def check_displacement(events: Sequence[Event], context: InvariantContext) -> list[Violation]:
    """Only a level 1 displaces, only a higher level, and only when it must.

    - In every ``patient_displaced``, ``desalojado_por`` is a level 1, the
      displaced patient is of a higher level and its ``box`` is the one it
      held; the next ``box_assigned`` of the level 1 is that box, in the same
      instant.
    - Version 4: an admitted patient displaced while it waits for its bed
      (after ``bed_requested``) waits in the corridor and never gets a box
      again.
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
    admitted: set[str] = set()  # version 4: asked for a bed
    corridor: set[str] = set()  # version 4: displaced while waiting for the bed

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
                if episode in corridor:
                    out.append(
                        _at(
                            name,
                            e,
                            f"{episode} was displaced while waiting for its bed and got "
                            f"box {box} again",
                        )
                    )
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
                if episode in admitted:
                    corridor.add(episode)
            case "bed_requested":
                admitted.add(episode)
            case "patient_departed" | "box_released" | "patient_left_wbs":
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
    """The clinical payloads of a clinical log are the ones of its patients.

    Only for a log with events of a clinical version, 2, 3 or 4
    (``CLINICAL_SCHEMA_VERSIONS``):

    - From the log alone: the types of ``resultados`` of each
      ``test_resulted`` are the ``pruebas`` of the episode's ``test_ordered``.
    - With a ground truth: a clinical log needs the clinical ground truth,
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
    clinical_log = any(e.schema_version in CLINICAL_SCHEMA_VERSIONS for e in events)
    ground_truth = context.ground_truth
    truth: dict[str, EpisodeTruth] = {}
    if ground_truth is not None:
        kinds = {e.clinical is not None for e in ground_truth.episodes}
        if clinical_log and False in kinds:
            out.append(Violation(name, "a clinical log with a provisional ground truth"))
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
        if e.schema_version not in CLINICAL_SCHEMA_VERSIONS:
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


def check_results_wait(events: Sequence[Event], context: InvariantContext) -> list[Violation]:
    """Exactly the levels of ``espera_resultados_fuera`` leave the box for the results.

    Only for the events of a log of version 3 (``CURRENT_CLINICAL_SCHEMA_VERSION``) or 4,
    with the levels of the center of the context and the *assigned* level of
    each episode (its ``triage_completed``):

    - the ``test_ordered`` of an episode of one of those levels is followed,
      as the next event of the episode and in the same instant, by its
      ``box_released``;
    - a ``box_released`` comes only right after the ``test_ordered`` of an
      episode of one of those levels.

    The order of ``box_released`` (after ``test_ordered``, from a box, back in
    a box only with the results) is checked by ``transitions`` and
    ``capacity``.
    """
    name = "results_wait"
    levels = set(context.center.results_wait_outside)
    out: list[Violation] = []
    level: dict[str, int] = {}
    ordered: dict[str, Event] = {}  # test_ordered waiting for its box_released

    for e in events:
        episode = e.episode_id
        if e.schema_version not in _RESULTS_ROOM_VERSIONS or episode is None:
            continue
        order = ordered.pop(episode, None)
        if e.event_type == "box_released":
            if order is None:
                out.append(
                    _at(
                        name,
                        e,
                        f"box_released of a level {level.get(episode)} patient not right "
                        f"after its test_ordered (espera_resultados_fuera {sorted(levels)})",
                    )
                )
            elif e.sim_time != order.sim_time:
                out.append(
                    _at(
                        name,
                        e,
                        f"box_released at {e.sim_time!r}, not in the instant of its "
                        f"test_ordered {order.sim_time!r}",
                    )
                )
            continue
        if order is not None:
            out.append(
                _at(
                    name,
                    order,
                    f"a level {level[episode]} patient ordered tests and did not leave its box "
                    f"(espera_resultados_fuera {sorted(levels)})",
                )
            )
        if e.event_type == "triage_completed":
            level[episode] = e.payload["nivel"]
        elif e.event_type == "test_ordered" and level.get(episode) in levels:
            ordered[episode] = e
    for order in ordered.values():
        out.append(
            _at(
                name,
                order,
                f"a level {level[order.episode_id]} patient ordered tests and "
                f"did not leave its box (espera_resultados_fuera {sorted(levels)})",
            )
        )
    return out


@dataclass(slots=True)
class _Waiting:
    """What ``abandonment`` needs of an episode of version 4 to compare it with the truth."""

    arrival: float
    triage_start: float | None = None
    triage_end: float | None = None
    seen: Event | None = None  # its first assessment_started of type inicial
    left: Event | None = None
    departed: bool = False


def _abandonment_with_truth(events: Sequence[Event], context: InvariantContext) -> list[Violation]:
    """The abandonment against the patience of the ground truth (task 5.3).

    For each episode of version 4 whose truth has an outcome and whose assigned
    level is not 1, with deadline = arrival + patience:

    - a ``patient_left_wbs`` happens at its due instant, within
      ``TURNAROUND_TOLERANCE``: the deadline if it is due before the triage
      starts (it leaves waiting for a nurse), or max(deadline, end of the
      triage) if not (a deadline due during the triage waits for its end);
    - its first assessment of type ``inicial`` does not start after the
      deadline, except at the end of a triage during which it was due, when
      the box and the doctor come in that same instant;
    - at the end of the log, an episode without a terminal event and not seen
      has its due instant at the horizon or after (``len(days) × 1440``):
      before it, the engine should have made it leave. One still in its
      triage, with the deadline not due before it started, has no due instant
      yet. Without the days of the ground truth, this one is not checked.

    The arrival is the ``sim_time`` of ``patient_arrived``, where the engine
    starts the deadline.
    """
    ground_truth = context.ground_truth
    if ground_truth is None:
        return []
    truth = {
        e.episode_id: e for e in ground_truth.episodes if e.outcome is not None and e.level != 1
    }
    if not truth:
        return []
    name = "abandonment"
    out: list[Violation] = []
    waiting: dict[str, _Waiting] = {}
    for e in events:
        episode = e.episode_id
        if not _v4(e) or episode not in truth:
            continue
        if e.event_type == "patient_arrived":
            waiting[episode] = _Waiting(e.sim_time)
            continue
        w = waiting.get(episode)
        if w is None:
            continue  # reported by conservation
        match e.event_type:
            case "triage_started":
                w.triage_start = e.sim_time
            case "triage_completed":
                w.triage_end = e.sim_time
            case "assessment_started" if e.payload["tipo"] == "inicial" and w.seen is None:
                w.seen = e
            case "patient_left_wbs":
                w.left = e
            case "patient_departed":
                w.departed = True

    for episode, w in waiting.items():
        deadline = w.arrival + truth[episode].outcome.patience
        # Due before the triage starts: it leaves waiting for the nurse (in a tie the
        # nurse wins). Due during it: at its end. Still in the triage: not known yet.
        before_triage = w.triage_start is None or deadline < w.triage_start
        if before_triage:
            due = deadline
        elif w.triage_end is not None:
            due = max(deadline, w.triage_end)
        else:
            due = None
        if w.left is not None and due is not None:
            if abs(w.left.sim_time - due) > TURNAROUND_TOLERANCE:
                out.append(
                    _at(
                        name,
                        w.left,
                        f"{episode} left at {w.left.sim_time}, but its deadline (arrival "
                        f"{w.arrival} + patience) and its triage give {due}",
                    )
                )
        if w.seen is not None and w.seen.sim_time > deadline + TURNAROUND_TOLERANCE:
            at_triage_end = (
                not before_triage
                and w.triage_end is not None
                and w.triage_end > deadline
                and abs(w.seen.sim_time - w.triage_end) <= TURNAROUND_TOLERANCE
            )
            if not at_triage_end:
                out.append(
                    _at(
                        name,
                        w.seen,
                        f"{episode} seen at {w.seen.sim_time}, after its deadline {deadline}",
                    )
                )
        if (
            ground_truth.days
            and w.left is None
            and not w.departed
            and w.seen is None
            and due is not None
            and due < len(ground_truth.days) * MINUTES_PER_DAY
        ):
            out.append(
                Violation(
                    name,
                    f"{episode} still waits at the end, unseen, with its deadline due at {due}",
                    episode_id=episode,
                )
            )
    return out


def check_abandonment(events: Sequence[Event], context: InvariantContext) -> list[Violation]:
    """Only an unseen patient leaves, never a level 1, and from where it waits.

    Only for the events of version 4 (docs/specs/hito-5.md, H5-3). For each
    ``patient_left_wbs``, one violation at most, the first that applies:

    - not after being seen, that is, after an ``assessment_started`` of type
      ``inicial`` of the episode;
    - not of an assigned level 1 (its ``triage_completed``);
    - not during the triage (a ``triage_started`` without its
      ``triage_completed``);
    - its ``espera`` is where the patient waits: ``triaje`` before its
      ``triage_started``, ``medico`` holding a box, ``box`` triaged and
      without a box.

    With the ground truth of the outcome (task 5.3), see
    ``_abandonment_with_truth``: the instant of each abandonment, that nobody is
    seen after its deadline and that nobody still waits with it passed.
    """
    name = "abandonment"
    out: list[Violation] = []
    started: set[str] = set()
    level: dict[str, int] = {}
    in_box: set[str] = set()
    seen: set[str] = set()

    for e in events:
        episode = e.episode_id
        if not _v4(e) or episode is None:
            continue
        match e.event_type:
            case "triage_started":
                started.add(episode)
            case "triage_completed":
                level[episode] = e.payload["nivel"]
            case "box_assigned":
                in_box.add(episode)
            case "patient_displaced" | "box_released":
                in_box.discard(episode)
            case "assessment_started" if e.payload["tipo"] == "inicial":
                seen.add(episode)
            case "patient_left_wbs":
                if episode in seen:
                    out.append(_at(name, e, f"{episode} left after being seen"))
                elif level.get(episode) == 1:
                    out.append(_at(name, e, f"{episode} of level 1 left; a level 1 never leaves"))
                elif episode in started and episode not in level:
                    out.append(_at(name, e, f"{episode} left during its triage"))
                else:
                    if episode not in started:
                        where = "triaje"
                    elif episode in in_box:
                        where = "medico"
                    else:
                        where = "box"
                    if e.payload["espera"] != where:
                        out.append(
                            _at(
                                name,
                                e,
                                f"patient_left_wbs with espera {e.payload['espera']!r}, "
                                f"but {episode} was waiting for {where!r}",
                            )
                        )
    # The comparisons with the truth after those of the log, in file order (task 5.3).
    return out + _abandonment_with_truth(events, context)


def _expected_bed_wait(
    base: float, requested_at: float, start: date, center: CenterConfig
) -> float:
    """``base × factor_turno × factor_estacion`` of the instant of the request.

    Computed here on its own, with ``context_indices``, the shifts of
    ``[turnos]`` and the factors of ``[camas]`` of the center, not with
    ``BedWaitFactors``, so that an error there shows.
    """
    (shift,), _, (season,) = context_indices([requested_at], start, center.shift_starts)
    return base * center.bed_shift_factors[int(shift)] * center.bed_season_factors[int(season)]


def _outcome_with_truth(events: Sequence[Event], context: InvariantContext) -> list[Violation]:
    """The decision and the wait for a bed against the ground truth (task 5.3).

    For each episode of version 4 whose truth has an outcome:

    - its ``disposition_decided`` has the drawn destination;
    - with a center with ``[camas]`` and the days of the ground truth (day 0
      is the date of minute 0), ``bed_assigned`` comes ``bed_base ×
      factor_turno × factor_estacion`` after ``bed_requested``, with the shift
      and the season of the instant of the request, within
      ``TURNAROUND_TOLERANCE``.
    """
    ground_truth = context.ground_truth
    if ground_truth is None:
        return []
    truth = {e.episode_id: e for e in ground_truth.episodes if e.outcome is not None}
    if not truth:
        return []
    name = "outcome"
    out: list[Violation] = []
    beds = context.center.has_beds and bool(ground_truth.days)
    requested: dict[str, Event] = {}
    for e in events:
        episode = e.episode_id
        if not _v4(e) or episode not in truth:
            continue
        outcome = truth[episode].outcome
        match e.event_type:
            case "disposition_decided" if e.payload["destino"] != outcome.destination:
                out.append(
                    _at(
                        name,
                        e,
                        f"{episode} decided {e.payload['destino']!r}, but its drawn "
                        f"destination is {outcome.destination!r}",
                    )
                )
            case "bed_requested":
                requested[episode] = e
            case "bed_assigned" if beds and episode in requested:
                asked = requested[episode].sim_time
                expected = _expected_bed_wait(
                    outcome.bed_base, asked, ground_truth.days[0].date, context.center
                )
                if abs((e.sim_time - asked) - expected) > TURNAROUND_TOLERANCE:
                    out.append(
                        _at(
                            name,
                            e,
                            f"{episode} waited {e.sim_time - asked} for its bed, but its base "
                            f"{outcome.bed_base} with the factors of {asked} gives {expected}",
                        )
                    )
    return out


def check_outcome(events: Sequence[Event], context: InvariantContext) -> list[Violation]:
    """The decision, the bed and the departure come in their order and instant.

    Only for the events of version 4 (docs/specs/hito-5.md, H5-5 to H5-7):

    - a ``disposition_decided`` with ``ingreso`` is followed, as the next event
      of the episode and in its instant, by ``bed_requested``; with another
      destination, by ``patient_departed``;
    - a ``bed_requested`` comes right after a ``disposition_decided`` with
      ``ingreso`` of the episode, in its instant;
    - a ``bed_assigned`` comes after a ``bed_requested`` of the episode and is
      followed, as the next event of the episode and in its instant, by
      ``patient_departed``;
    - a ``patient_departed`` with ``ingreso`` comes right after its
      ``bed_assigned``.

    That the departure has the destination of the decision is checked by
    ``transitions``, in every version. With the ground truth of the outcome
    (task 5.3), see ``_outcome_with_truth``: the drawn destination and the wait
    for the bed.
    """
    name = "outcome"
    out: list[Violation] = []
    pending: dict[str, tuple[str, Event]] = {}  # episode → (next type expected, cause)
    last: dict[str, Event] = {}  # episode → its previous event
    requested: set[str] = set()

    def right_after(e: Event, event_type: str, destino: str | None = None) -> bool:
        before = last.get(e.episode_id)
        return (
            before is not None
            and before.event_type == event_type
            and before.sim_time == e.sim_time
            and (destino is None or before.payload["destino"] == destino)
        )

    def missing(cause: Event, expected: str) -> Violation:
        return _at(name, cause, f"{cause.event_type} not followed in its instant by {expected}")

    for e in events:
        episode = e.episode_id
        if not _v4(e) or episode is None:
            continue
        need = pending.pop(episode, None)
        if need is not None and (e.event_type != need[0] or e.sim_time != need[1].sim_time):
            out.append(missing(need[1], need[0]))
        match e.event_type:
            case "disposition_decided":
                admitted = e.payload["destino"] == "ingreso"
                pending[episode] = ("bed_requested" if admitted else "patient_departed", e)
            case "bed_requested":
                requested.add(episode)
                if not right_after(e, "disposition_decided", "ingreso"):
                    out.append(
                        _at(
                            name,
                            e,
                            "bed_requested not right after a disposition_decided with "
                            "destino 'ingreso'",
                        )
                    )
            case "bed_assigned":
                if episode not in requested:
                    out.append(_at(name, e, f"bed_assigned of {episode} without bed_requested"))
                pending[episode] = ("patient_departed", e)
            case "patient_departed" if e.payload["destino"] == "ingreso":
                if not right_after(e, "bed_assigned"):
                    out.append(
                        _at(name, e, "patient_departed with 'ingreso' not right after bed_assigned")
                    )
        last[episode] = e
    for expected, cause in pending.values():
        out.append(missing(cause, expected))
    return out + _outcome_with_truth(events, context)


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
        "results_wait": check_results_wait,
        "abandonment": check_abandonment,
        "outcome": check_outcome,
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
