"""The patient as a SimPy process that walks the state machine of the design.

Each state is what happens while the process is stopped at a ``yield``: waiting
for a resource or for a timeout. The code between two ``yield`` runs in one
instant, and that is where each transition emits its event, with
``sim_time = env.now`` (docs/specs/hito-3.md, "El paciente como proceso").

The resources are held in different stretches of the stay: the triage nurse
during the triage, the box from ``box_assigned`` to ``patient_departed``, and
a doctor only during each assessment. A level 1 is classified at the door,
without a nurse and in the instant it arrives (docs/specs/hito-4.md). While
the tests are pending, the patient keeps the box and frees the doctor; that is
why the box is usually the bottleneck.

**Results room** (ADR candidate 45, task 4.6a). With the clinical model, a
patient whose *assigned* level is in ``espera_resultados_fuera`` leaves its
box when it orders the tests: right after ``test_ordered``, in the same
instant, it emits ``box_released`` and gives the box back, as a departure
does. It waits for the results in a room without a capacity limit, holding no
resource, so nobody can displace it. With the results it asks for a box again
with its same key, as a displaced patient does, and there it is reassessed,
decided and departs. The provisional model never leaves the box.

Boxes and doctors go by ``priority_key`` = (level, arrival). A level 1 can
displace a patient of a higher level from its box: the displaced patient gets
``simpy.Interrupt`` at the ``yield`` where it is, emits ``patient_displaced``,
asks for a box again with the same key and, when it gets one, resumes the
stage where it was, with the time it had left of an interrupted assessment.
The tests run in a process of their own (``_lab``), so a displacement does not
stop them.

Everything random was drawn on arrival (``PatientDraws``): the process only
waits and emits. With the clinical model (``draws.clinical``), the events
carry the clinical payloads of version 3 of the catalog, and the turnaround of
the tests is computed when they are ordered, with the shift band of that
instant; without it, the process is exactly the one of the provisional model.

**Outcome of milestone 5** (task 5.1, docs/specs/hito-5.md). With
``draws.outcome`` the patient goes through ``_patient_with_outcome`` and writes
version 4 of the catalog; without it, ``patient`` runs the code of milestone 4,
line for line. The patience gives a deadline, arrival plus patience
(``Deadline``, created on arrival; never for an assigned level 1). Before the
first assessment starts, every wait for a nurse, a box or a doctor is "the
resource or the deadline, whichever comes first" (``_granted``): at the
deadline the patient emits ``patient_left_wbs`` with where it waited and, from
a box, gives it back. In a tie the patient stays, because the deadline has the
``LATE`` priority. Nobody leaves during the triage, but the deadline goes on:
if it is due during it, the next wait asks only for what comes in that same
instant. The destination is the one of the outcome.
"""

import enum
from collections.abc import Callable, Generator
from dataclasses import dataclass
from functools import partial

import simpy
from simpy.events import EventPriority
from simpy.resources.resource import Preempted

from edsim.engine.clinical import PatientDraws, classified_at_the_door
from edsim.engine.events import DOOR, NURSE, RESULTS_WAIT, EventLog, episode_id
from edsim.engine.resources import (
    TRIAGE_PRIORITY,
    Holder,
    Pools,
    priority_key,
    should_displace,
)

Emit = Callable[..., object]

LATE = EventPriority(2)
"""Priority of a deadline: after every ``URGENT`` (0) and ``NORMAL`` (1) event of its instant.

SimPy orders the events of one instant by priority and then by creation
(``Environment.schedule`` pushes ``(time, priority, eid, event)``). A release
grants the next request in a chain of ``NORMAL`` events created during the
instant, so a deadline of priority 2 is processed only when that chain is over.
"""


class Deadline(simpy.Event):
    """An event that SimPy processes ``delay`` minutes from now, with ``LATE`` priority.

    The same as a ``simpy.Timeout`` but for the priority: it is triggered from
    its creation (``triggered`` is true at once) and only ``processed`` says
    that its instant has come. The patience of a patient is one (docs/specs/
    hito-5.md, "Reglas del abandono"): if a resource is granted in the instant
    the deadline is due, the grant comes first and the patient stays.

    Raises:
        ValueError: If ``delay`` is negative.
    """

    def __init__(self, env: simpy.Environment, delay: float) -> None:
        if delay < 0:
            raise ValueError(f"negative delay {delay!r}")
        super().__init__(env)
        # As simpy.Timeout does in its __init__: the value is set on creation.
        self._ok = True
        self._value = None
        env.schedule(self, LATE, delay)


def _extra(draws: PatientDraws, event_type: str) -> dict[str, object]:
    """Clinical keys of the payload of ``event_type``: none with the provisional model."""
    if draws.clinical is None:
        return {}
    return draws.clinical.payload(event_type)


class Stage(enum.Enum):
    """What the patient has left to do in the box."""

    INITIAL = enum.auto()  # the first assessment, maybe interrupted
    TESTS = enum.auto()  # waiting for the results
    REASSESSMENT = enum.auto()  # the reassessment, maybe interrupted
    DONE = enum.auto()  # ready for the decision and the departure


@dataclass(slots=True)
class _Stay:
    """State of the stay in the box, kept across displacements.

    Attributes:
        stage: Next thing to do in the box. It moves forward only after the
            event that closes the stage has been emitted.
        pending: Minutes left of the assessment of the stage: the full
            duration, or what was left when it was interrupted.
        results: Triggered by the lab after emitting ``test_resulted``.
        seen: Whether the first assessment has started; from then on the
            patient never leaves (milestone 5).
    """

    stage: Stage
    pending: float
    results: simpy.Event | None = None
    seen: bool = False


RESULTS_ROOM = object()
"""What ``_in_box`` returns when the patient leaves its box for the results room."""

LEFT = object()
"""What ``_assessment`` and ``_in_box`` return when the deadline comes before the first doctor."""


def _granted(
    env: simpy.Environment, request: simpy.Event, deadline: Deadline | None
) -> Generator[simpy.Event, object, bool]:
    """Wait for ``request`` or the deadline, whichever comes first; whether it was granted.

    Without a deadline, or with the request granted on creation, it is a plain
    ``yield request``. Otherwise it waits for ``request | deadline``: the
    deadline, of ``LATE`` priority, comes after any grant of its instant, so in
    a tie the request wins. If the deadline was due while the patient waited
    for nothing (during its triage), a new one in this instant stands for it:
    the patient stays only if the resource comes in this same instant.
    """
    if deadline is None or request.triggered:
        yield request
        return True
    if deadline.processed:
        deadline = Deadline(env, 0)
    yield request | deadline
    return request.triggered


def leaves_for_results(draws: PatientDraws, wait_outside: frozenset[int]) -> bool:
    """Whether the patient waits for its results outside the box.

    Only with the clinical model, and by the assigned level (``draws.level``,
    what the hospital knows), as the priority and the door.
    """
    return draws.clinical is not None and draws.level in wait_outside


def patient(
    env: simpy.Environment,
    log: EventLog,
    pools: Pools,
    arrival_id: int,
    draws: PatientDraws,
    wait_outside: frozenset[int] = frozenset(),
) -> Generator[simpy.Event]:
    """SimPy process of one episode, from the arrival to the departure.

    A patient still inside at the horizon simply stops at its ``yield``: it
    has no ``patient_departed`` and holds its resources until the end.

    No event is lost nor emitted twice:

    - Each event is emitted in one place, and the stage moves forward only
      after it. An interruption can only arrive at a ``yield``, never in the
      middle of a transition.
    - Every ``yield`` made while holding a box handles ``Interrupt`` with what
      its stage needs (see ``_in_box``), and ``patient_displaced`` is emitted
      in one place, here. Back in a box, ``_in_box`` goes on from
      ``stay.stage``: a finished stage is not repeated, an interrupted one
      starts again with ``stay.pending``.
    - Waiting for the triage or for a box, the patient is not a box user, so
      it cannot be displaced, except between SimPy granting the box and the
      process resuming: then it has emitted nothing in the box yet, and it
      just waits again.

    Args:
        env: The SimPy environment.
        log: Where the events go.
        pools: Nurses, doctors and boxes of the run.
        arrival_id: Arrival of the patient; gives the episode identifier.
        draws: What the patient drew on arrival.
        wait_outside: Assigned levels that wait for the results outside the
            box (``CenterConfig.results_wait_outside``); only the clinical
            model uses it.
    """
    if draws.outcome is not None:
        return (yield from _patient_with_outcome(env, log, pools, arrival_id, draws, wait_outside))
    me = env.active_process
    pools.arrival_of[me] = arrival_id
    emit = partial(log.emit, arrival_id=arrival_id)

    # Arrival and registration: no wait in milestone 3. env.now is the
    # sim_time of patient_arrived, so the key matches the log exactly.
    key = priority_key(draws.level, env.now)
    emit("patient_arrived", env.now, **_extra(draws, "patient_arrived"))
    emit("patient_registered", env.now, **_extra(draws, "patient_registered"))

    # draws.level is the assigned level: the door, like the priority, uses what
    # the hospital knows.
    if classified_at_the_door(draws.level):
        # Classified at the door (ADR candidate 39): no nurse and no triage time;
        # the drawn triage_time is not used. Same events, in the same instant.
        emit("triage_started", env.now, circuito=DOOR)
        emit(
            "triage_completed",
            env.now,
            nivel=draws.level,
            **_extra(draws, "triage_completed"),
        )
    else:
        # The same priority for every patient: FIFO (see TRIAGE_PRIORITY).
        with pools.nurses.request(priority=TRIAGE_PRIORITY) as nurse:
            yield nurse
            emit("triage_started", env.now, circuito=NURSE)
            yield env.timeout(draws.triage_time)
            emit(
                "triage_completed",
                env.now,
                nivel=draws.level,
                **_extra(draws, "triage_completed"),
            )

    holder = Holder(me, arrival_id, draws.level)
    stay = _Stay(Stage.INITIAL, draws.assessment_time)
    leaves = leaves_for_results(draws, wait_outside)
    while stay.stage is not Stage.DONE:
        preempt = should_displace(pools.boxes, draws.level)
        with pools.boxes.request(priority=key, preempt=preempt) as box_request:
            try:
                yield box_request
            except simpy.Interrupt as interrupt:
                # Displaced after the grant and before resuming: no box_assigned
                # yet, so nothing to undo; the with releases and it asks again.
                _preempted(interrupt, pools)
                continue
            box = pools.box_numbers.take(holder)
            emit("box_assigned", env.now, box=box)

            cause = yield from _in_box(env, pools, emit, draws, stay, key, box, leaves)
            if cause is RESULTS_ROOM:
                # Right after test_ordered, in the same instant. Emitted before
                # giving the box back, as a departure: whoever gets it next
                # resumes later in this instant, and its box_assigned comes after.
                emit("box_released", env.now, box=box, espera=RESULTS_WAIT)
                pools.box_numbers.give(box)
            elif cause is None:
                destino = "ingreso" if draws.admitted else "alta"
                emit("disposition_decided", env.now, destino=destino)
                emit("patient_departed", env.now, destino=destino)
                # Emitted before releasing the box: whoever gets it next resumes
                # later in this same instant, so its box_assigned comes after.
                pools.box_numbers.give(box)
                del pools.arrival_of[me]
            else:
                by = episode_id(pools.arrival_of[cause.by])
                emit("patient_displaced", env.now, box=box, desalojado_por=by)
                pools.box_numbers.hand_over(box, to=cause.by)
        # Leaving the with releases the box; after a displacement SimPy already
        # removed this request from the users, and the release does nothing.
        if cause is RESULTS_ROOM and not stay.results.triggered:
            # In the room: no resource held, so nobody can displace the patient.
            # With the results it asks for a box again with the same key.
            yield stay.results


def _in_box(
    env: simpy.Environment,
    pools: Pools,
    emit: Emit,
    draws: PatientDraws,
    stay: _Stay,
    key: tuple[int, float],
    box: int,
    leaves: bool = False,
    deadline: Deadline | None = None,
) -> Generator[simpy.Event, object, object]:
    """Go through the stages left in the box.

    Returns ``None`` when they are all done, the ``Preempted`` cause if the
    patient is displaced, ``RESULTS_ROOM`` right after ordering the tests if
    ``leaves`` (the patient waits for the results outside), or ``LEFT`` if the
    deadline comes while it waits for its first doctor (milestone 5; never
    without a ``deadline``). Waiting for the results, a displacement needs
    nothing else: the lab keeps running. Waiting for a doctor or in an
    assessment, ``_assessment`` handles it.
    """
    while stay.stage is not Stage.DONE:
        if stay.stage is Stage.TESTS:
            # test_resulted is emitted before results is triggered: if it is
            # triggered, the event is already in the log.
            if not stay.results.triggered:
                try:
                    yield stay.results
                except simpy.Interrupt as interrupt:
                    return _preempted(interrupt, pools)
            stay.stage, stay.pending = Stage.REASSESSMENT, draws.reassessment_time
            continue

        tipo = "inicial" if stay.stage is Stage.INITIAL else "reevaluacion"
        waiting = None if stay.seen else deadline
        cause = yield from _assessment(env, pools, emit, stay, tipo, key, box, waiting)
        if cause is not None:
            return cause
        if stay.stage is Stage.INITIAL and draws.needs_tests:
            # The box stays taken and the doctor is free while the tests run.
            emit("test_ordered", env.now, **_extra(draws, "test_ordered"))
            if draws.clinical is None:
                # Provisional: the turnaround was drawn on arrival.
                turnaround = draws.test_turnaround
            else:
                # Clinical: the slowest ordered test, with the shift band of the order.
                turnaround = draws.clinical.round_turnaround(env.now)
            stay.results = env.event()
            env.process(_lab(env, emit, turnaround, stay.results, **_extra(draws, "test_resulted")))
            stay.stage = Stage.TESTS
            if leaves:
                return RESULTS_ROOM
        else:
            stay.stage = Stage.DONE
    return None


def _assessment(
    env: simpy.Environment,
    pools: Pools,
    emit: Emit,
    stay: _Stay,
    tipo: str,
    key: tuple[int, float],
    box: int,
    deadline: Deadline | None = None,
) -> Generator[simpy.Event, object, object]:
    """One assessment in the patient's box: wait for a doctor, hold it, free it.

    Lasts ``stay.pending``. If the patient is displaced while waiting for the
    doctor, the request is dropped (the with cancels it, or releases it if it
    was already granted). If it is displaced during the assessment, it emits
    ``assessment_ended`` with ``interrumpida`` true and keeps in
    ``stay.pending`` the time left. Returns the ``Preempted`` cause, ``None``
    if the assessment ended, or ``LEFT`` if the ``deadline`` came before the
    doctor (milestone 5; without a deadline, the wait of milestone 4).
    """
    with pools.doctors.request(priority=key) as doctor:
        try:
            if deadline is None:
                yield doctor
            elif not (yield from _granted(env, doctor, deadline)):
                return LEFT
        except simpy.Interrupt as interrupt:
            return _preempted(interrupt, pools)
        emit("assessment_started", env.now, tipo=tipo, pool="medicos", box=box)
        if tipo == "inicial":
            stay.seen = True
        start = env.now
        try:
            yield env.timeout(stay.pending)
        except simpy.Interrupt as interrupt:
            cause = _preempted(interrupt, pools)
            stay.pending -= env.now - start
            emit("assessment_ended", env.now, tipo=tipo, interrumpida=True)
            return cause
        emit("assessment_ended", env.now, tipo=tipo, interrumpida=False)
    return None


def _patient_with_outcome(
    env: simpy.Environment,
    log: EventLog,
    pools: Pools,
    arrival_id: int,
    draws: PatientDraws,
    wait_outside: frozenset[int],
) -> Generator[simpy.Event]:
    """SimPy process of one episode with the outcome of milestone 5 (version 4).

    The flow of ``patient`` with the deadline of the patience in every wait
    before the first assessment, and the destination of ``draws.outcome``.
    """
    outcome = draws.outcome
    me = env.active_process
    pools.arrival_of[me] = arrival_id
    emit = partial(log.emit, arrival_id=arrival_id)

    def leave(espera: str) -> None:
        emit("patient_left_wbs", env.now, espera=espera)
        del pools.arrival_of[me]

    key = priority_key(draws.level, env.now)
    # Created on arrival, as the patience counts from there. A level 1 never leaves.
    deadline = None if draws.level == 1 else Deadline(env, outcome.patience)
    emit("patient_arrived", env.now, **_extra(draws, "patient_arrived"))
    emit("patient_registered", env.now, **_extra(draws, "patient_registered"))

    if classified_at_the_door(draws.level):
        emit("triage_started", env.now, circuito=DOOR)
        emit("triage_completed", env.now, nivel=draws.level, **_extra(draws, "triage_completed"))
    else:
        with pools.nurses.request(priority=TRIAGE_PRIORITY) as nurse:
            if not (yield from _granted(env, nurse, deadline)):
                leave("triaje")
                return  # the with cancels the request
            emit("triage_started", env.now, circuito=NURSE)
            yield env.timeout(draws.triage_time)
            emit(
                "triage_completed",
                env.now,
                nivel=draws.level,
                **_extra(draws, "triage_completed"),
            )

    holder = Holder(me, arrival_id, draws.level)
    stay = _Stay(Stage.INITIAL, draws.assessment_time)
    leaves = leaves_for_results(draws, wait_outside)
    while stay.stage is not Stage.DONE:
        preempt = should_displace(pools.boxes, draws.level)
        waiting = None if stay.seen else deadline
        with pools.boxes.request(priority=key, preempt=preempt) as box_request:
            try:
                granted = yield from _granted(env, box_request, waiting)
            except simpy.Interrupt as interrupt:
                _preempted(interrupt, pools)
                continue
            if not granted:
                leave("box")
                return  # the with cancels the request
            box = pools.box_numbers.take(holder)
            emit("box_assigned", env.now, box=box)

            cause = yield from _in_box(env, pools, emit, draws, stay, key, box, leaves, waiting)
            if cause is LEFT:
                # As a departure: emitted before giving the box back.
                leave("medico")
                pools.box_numbers.give(box)
                return  # the with releases the box
            if cause is RESULTS_ROOM:
                emit("box_released", env.now, box=box, espera=RESULTS_WAIT)
                pools.box_numbers.give(box)
            elif cause is None:
                destino = outcome.destination
                emit("disposition_decided", env.now, destino=destino)
                emit("patient_departed", env.now, destino=destino)
                pools.box_numbers.give(box)
                del pools.arrival_of[me]
            else:
                by = episode_id(pools.arrival_of[cause.by])
                emit("patient_displaced", env.now, box=box, desalojado_por=by)
                pools.box_numbers.hand_over(box, to=cause.by)
        if cause is RESULTS_ROOM and not stay.results.triggered:
            yield stay.results


def _lab(
    env: simpy.Environment,
    emit: Emit,
    turnaround: float,
    results: simpy.Event,
    **payload: object,
) -> Generator[simpy.Event]:
    """The tests of one patient: they run whatever happens to the patient.

    ``payload`` is the one of ``test_resulted``: empty with the provisional
    model, the results of the ordered tests with the clinical one.
    """
    yield env.timeout(turnaround)
    emit("test_resulted", env.now, **payload)
    results.succeed()


def _preempted(interrupt: simpy.Interrupt, pools: Pools) -> Preempted:
    """The cause of a displacement from a box; any other interrupt is a bug."""
    cause = interrupt.cause
    if not isinstance(cause, Preempted) or cause.resource is not pools.boxes:
        raise RuntimeError(f"unexpected interrupt of a patient: {cause!r}") from interrupt
    return cause
