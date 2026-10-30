"""The patient as a SimPy process that walks the state machine of the design.

Each state is what happens while the process is stopped at a ``yield``: waiting
for a resource or for a timeout. The code between two ``yield`` runs in one
instant, and that is where each transition emits its event, with
``sim_time = env.now`` (docs/specs/hito-3.md, "El paciente como proceso").

The resources are held in different stretches of the stay: the triage nurse
during the triage, the box from ``box_assigned`` to ``patient_departed``, and
a doctor only during each assessment. While the tests are pending, the patient
keeps the box and frees the doctor; that is why the box is usually the
bottleneck.

Boxes and doctors go by ``priority_key`` = (level, arrival). A level 1 can
displace a patient of a higher level from its box: the displaced patient gets
``simpy.Interrupt`` at the ``yield`` where it is, emits ``patient_displaced``,
asks for a box again with the same key and, when it gets one, resumes the
stage where it was, with the time it had left of an interrupted assessment.
The tests run in a process of their own (``_lab``), so a displacement does not
stop them.

Everything random was drawn on arrival (``PatientDraws``): the process only
waits and emits.
"""

import enum
from collections.abc import Callable, Generator
from dataclasses import dataclass
from functools import partial

import simpy
from simpy.resources.resource import Preempted

from edsim.engine.clinical import PatientDraws
from edsim.engine.events import EventLog, episode_id
from edsim.engine.resources import Holder, Pools, priority_key, should_displace

Emit = Callable[..., object]


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
    """

    stage: Stage
    pending: float
    results: simpy.Event | None = None


def patient(
    env: simpy.Environment, log: EventLog, pools: Pools, arrival_id: int, draws: PatientDraws
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
    """
    me = env.active_process
    pools.arrival_of[me] = arrival_id
    emit = partial(log.emit, arrival_id=arrival_id)

    # Arrival and registration: no wait in milestone 3. env.now is the
    # sim_time of patient_arrived, so the key matches the log exactly.
    key = priority_key(draws.level, env.now)
    emit("patient_arrived", env.now)
    emit("patient_registered", env.now)

    with pools.nurses.request() as nurse:
        yield nurse
        emit("triage_started", env.now)
        yield env.timeout(draws.triage_time)
        emit("triage_completed", env.now, nivel=draws.level)

    holder = Holder(me, arrival_id, draws.level)
    stay = _Stay(Stage.INITIAL, draws.assessment_time)
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

            cause = yield from _in_box(env, pools, emit, draws, stay, key, box)
            if cause is None:
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


def _in_box(
    env: simpy.Environment,
    pools: Pools,
    emit: Emit,
    draws: PatientDraws,
    stay: _Stay,
    key: tuple[int, float],
    box: int,
) -> Generator[simpy.Event, object, Preempted | None]:
    """Go through the stages left in the box.

    Returns ``None`` when they are all done, or the ``Preempted`` cause if the
    patient is displaced. Waiting for the results, a displacement needs
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
        cause = yield from _assessment(env, pools, emit, stay, tipo, key, box)
        if cause is not None:
            return cause
        if stay.stage is Stage.INITIAL and draws.needs_tests:
            # The box stays taken and the doctor is free while the tests run.
            emit("test_ordered", env.now)
            stay.results = env.event()
            env.process(_lab(env, emit, draws.test_turnaround, stay.results))
            stay.stage = Stage.TESTS
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
) -> Generator[simpy.Event, object, Preempted | None]:
    """One assessment in the patient's box: wait for a doctor, hold it, free it.

    Lasts ``stay.pending``. If the patient is displaced while waiting for the
    doctor, the request is dropped (the with cancels it, or releases it if it
    was already granted). If it is displaced during the assessment, it emits
    ``assessment_ended`` with ``interrumpida`` true and keeps in
    ``stay.pending`` the time left. Returns the ``Preempted`` cause, or
    ``None`` if the assessment ended.
    """
    with pools.doctors.request(priority=key) as doctor:
        try:
            yield doctor
        except simpy.Interrupt as interrupt:
            return _preempted(interrupt, pools)
        emit("assessment_started", env.now, tipo=tipo, pool="medicos", box=box)
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


def _lab(
    env: simpy.Environment, emit: Emit, turnaround: float, results: simpy.Event
) -> Generator[simpy.Event]:
    """The tests of one patient: they run whatever happens to the patient."""
    yield env.timeout(turnaround)
    emit("test_resulted", env.now)
    results.succeed()


def _preempted(interrupt: simpy.Interrupt, pools: Pools) -> Preempted:
    """The cause of a displacement from a box; any other interrupt is a bug."""
    cause = interrupt.cause
    if not isinstance(cause, Preempted) or cause.resource is not pools.boxes:
        raise RuntimeError(f"unexpected interrupt of a patient: {cause!r}") from interrupt
    return cause
