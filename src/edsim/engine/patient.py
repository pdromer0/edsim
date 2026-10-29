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

Everything random was drawn on arrival (``PatientDraws``): the process only
waits and emits. Task 3.3 has no priority nor displacement; task 3.4 adds them.
"""

from collections.abc import Callable, Generator
from functools import partial

import simpy

from edsim.engine.clinical import PatientDraws
from edsim.engine.events import EventLog
from edsim.engine.resources import Pools

Emit = Callable[..., object]


def patient(
    env: simpy.Environment, log: EventLog, pools: Pools, arrival_id: int, draws: PatientDraws
) -> Generator[simpy.Event]:
    """SimPy process of one episode, from the arrival to the departure.

    A patient still inside at the horizon simply stops at its ``yield``: it
    has no ``patient_departed`` and holds its resources until the end.

    Args:
        env: The SimPy environment.
        log: Where the events go.
        pools: Nurses, doctors and boxes of the run.
        arrival_id: Arrival of the patient; gives the episode identifier.
        draws: What the patient drew on arrival.
    """
    emit = partial(log.emit, arrival_id=arrival_id)

    # Arrival and registration: no wait in milestone 3.
    emit("patient_arrived", env.now)
    emit("patient_registered", env.now)

    with pools.nurses.request() as nurse:
        yield nurse
        emit("triage_started", env.now)
        yield env.timeout(draws.triage_time)
        emit("triage_completed", env.now, nivel=draws.level)

    with pools.boxes.request() as box_request:
        yield box_request
        box = pools.box_numbers.take()
        emit("box_assigned", env.now, box=box)

        yield from _assessment(env, pools, emit, "inicial", draws.assessment_time, box)
        if draws.needs_tests:
            # The box stays taken and the doctor is free while the tests run.
            emit("test_ordered", env.now)
            yield env.timeout(draws.test_turnaround)
            emit("test_resulted", env.now)
            yield from _assessment(env, pools, emit, "reevaluacion", draws.reassessment_time, box)

        destino = "ingreso" if draws.admitted else "alta"
        emit("disposition_decided", env.now, destino=destino)
        emit("patient_departed", env.now, destino=destino)
        # Emitted before releasing the box: whoever gets it next resumes later
        # in this same instant, so its box_assigned comes after this departure.
        pools.box_numbers.give(box)


def _assessment(
    env: simpy.Environment, pools: Pools, emit: Emit, tipo: str, duration: float, box: int
) -> Generator[simpy.Event]:
    """One assessment in the patient's box: wait for a doctor, hold it, free it."""
    with pools.doctors.request() as doctor:
        yield doctor
        emit("assessment_started", env.now, tipo=tipo, pool="medicos", box=box)
        yield env.timeout(duration)
        emit("assessment_ended", env.now, tipo=tipo, interrumpida=False)
