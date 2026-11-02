"""Turnos: calendario, reservas de capacidad y proceso de turnos.

El calendario (shift_at, shift_changes) se prueba sin SimPy. Las reservas se prueban
con un PriorityResource a mano, con pacientes que piden con TRIAGE_PRIORITY o con su
clave: así se ve cada caso (bajar con plazas libres o con todos ocupados, subir
cancelando las que esperan o liberando las concedidas) sin el resto del motor.
"""

from collections.abc import Generator

import pytest
import simpy

from edsim.engine.resources import RESERVATION_PRIORITY, TRIAGE_PRIORITY
from edsim.engine.shifts import Reservations, shift_at, shift_changes

STARTS = (8, 15, 22)
MORNING, AFTERNOON, NIGHT = 0, 1, 2


# --- Calendario -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hour", "expected"),
    [(h, NIGHT) for h in range(0, 8)]
    + [(h, MORNING) for h in range(8, 15)]
    + [(h, AFTERNOON) for h in range(15, 22)]
    + [(h, NIGHT) for h in range(22, 24)],
)
def test_turno_de_cada_hora(hour, expected):
    # En el minuto de inicio de la hora y en el último antes de la siguiente.
    assert shift_at(STARTS, hour * 60) == expected
    assert shift_at(STARTS, hour * 60 + 59.999) == expected


@pytest.mark.parametrize(
    ("minute", "expected"),
    [
        (0.0, NIGHT),  # el día 0 empieza en la noche que empezó a las 22 h
        (479.999, NIGHT),
        (480.0, MORNING),
        (899.999, MORNING),
        (900.0, AFTERNOON),
        (1319.999, AFTERNOON),
        (1320.0, NIGHT),
        (1439.999, NIGHT),
        (1440.0, NIGHT),  # medianoche: la misma noche sigue
        (1440.0 + 480.0, MORNING),
        (6 * 1440.0 + 1320.0, NIGHT),
    ],
)
def test_turno_en_los_bordes_y_otros_dias(minute, expected):
    assert shift_at(STARTS, minute) == expected


def test_sin_noche_que_cruce_la_medianoche():
    # Con un turno que empieza a las 0 h, el minuto 0 es de ese turno.
    starts = (0, 8, 16)

    assert [shift_at(starts, h * 60) for h in (0, 7, 8, 15, 16, 23)] == [0, 0, 1, 1, 2, 2]


def test_cambios_de_turno():
    changes = shift_changes(STARTS, 2)

    assert changes == [
        (480.0, MORNING),
        (900.0, AFTERNOON),
        (1320.0, NIGHT),
        (1920.0, MORNING),
        (2340.0, AFTERNOON),
        (2760.0, NIGHT),
    ]
    assert all(type(t) is float for t, _ in changes)
    assert all(shift_at(STARTS, t) == shift for t, shift in changes)


def test_cambios_sin_el_minuto_0_ni_el_horizonte():
    # El minuto 0 lo pone el arranque; el horizonte (1440 · días) no ocurre.
    starts = (0, 8, 16)

    assert shift_changes(starts, 1) == [(480.0, 1), (960.0, 2)]
    assert shift_changes(starts, 2) == [
        (480.0, 1),
        (960.0, 2),
        (1440.0, 0),
        (1920.0, 1),
        (2400.0, 2),
    ]


# --- Reservas -------------------------------------------------------------------------


def busy(resource: simpy.PriorityResource) -> int:
    """Plazas ocupadas por pacientes (no por reservas)."""
    return sum(r.priority != RESERVATION_PRIORITY for r in resource.users)


def patient(
    env: simpy.Environment,
    resource: simpy.PriorityResource,
    duration: float,
    marks: list,
    name: str,
    *,
    at: float = 0.0,
) -> Generator[simpy.Event]:
    """Pide en ``at`` con TRIAGE_PRIORITY y retiene el recurso ``duration``."""
    yield env.timeout(at)
    with resource.request(priority=TRIAGE_PRIORITY) as request:
        yield request
        marks.append((name, "empieza", env.now))
        yield env.timeout(duration)
        marks.append((name, "termina", env.now))


def test_sin_reservas_la_plantilla_es_la_capacidad():
    env = simpy.Environment()
    reservations = Reservations(simpy.PriorityResource(env, capacity=4))

    assert (reservations.staff, reservations.granted, reservations.waiting) == (4, 0, 0)


def test_bajar_con_plazas_libres():
    env = simpy.Environment()
    resource = simpy.PriorityResource(env, capacity=4)
    reservations = Reservations(resource)

    reservations.set_staff(2)

    assert (reservations.staff, reservations.granted, reservations.waiting) == (2, 2, 0)
    assert resource.count == 2
    assert all(r.priority == RESERVATION_PRIORITY and not r.preempt for r in resource.users)


def test_bajar_con_todos_ocupados_espera_a_que_terminen():
    # 4 ocupados hasta 10, 20, 30 y 40; en 5 la plantilla baja a 2 y llega un quinto
    # paciente. Las 2 reservas esperan y toman las plazas de 10 y 20; el quinto empieza
    # en 30, cuando los ocupados bajan de 2. Nadie es interrumpido.
    env = simpy.Environment()
    resource = simpy.PriorityResource(env, capacity=4)
    reservations = Reservations(resource)
    marks: list = []
    for i, duration in enumerate([10, 20, 30, 40]):
        env.process(patient(env, resource, duration, marks, f"p{i}"))
    env.process(patient(env, resource, 5, marks, "p4", at=5))

    env.run(until=5)
    reservations.set_staff(2)

    assert (reservations.staff, reservations.granted, reservations.waiting) == (2, 0, 2)
    assert resource.queue[:2] == [r for r in resource.queue if r.priority == RESERVATION_PRIORITY]

    env.run(until=25)
    assert (reservations.granted, reservations.waiting) == (2, 0)
    assert busy(resource) == 2

    env.run()
    assert ("p4", "empieza", 30) in marks
    assert [m for m in marks if m[1] == "termina" and m[0] != "p4"] == [
        ("p0", "termina", 10),
        ("p1", "termina", 20),
        ("p2", "termina", 30),
        ("p3", "termina", 40),
    ]


def test_subir_cancela_las_que_esperan():
    # Todos ocupados y 3 reservas esperando; al subir de 1 a 3 se cancelan 2 y queda 1
    # en la cola. Cuando termina un paciente, la plaza va a esa reserva.
    env = simpy.Environment()
    resource = simpy.PriorityResource(env, capacity=4)
    reservations = Reservations(resource)
    marks: list = []
    for i in range(4):
        env.process(patient(env, resource, 10 * (i + 1), marks, f"p{i}"))
    env.run(until=1)
    reservations.set_staff(1)
    assert reservations.waiting == 3

    reservations.set_staff(3)

    assert (reservations.staff, reservations.granted, reservations.waiting) == (3, 0, 1)
    assert [r.priority for r in resource.queue] == [RESERVATION_PRIORITY]
    env.run(until=15)
    assert (reservations.granted, reservations.waiting) == (1, 0)


def test_subir_libera_las_concedidas_y_la_plaza_va_a_la_cola():
    # Plantilla 1 con 3 reservas concedidas y 2 pacientes en cola; al subir a 3 se
    # liberan 2 y los 2 pacientes empiezan en ese mismo instante.
    env = simpy.Environment()
    resource = simpy.PriorityResource(env, capacity=4)
    reservations = Reservations(resource)
    marks: list = []
    reservations.set_staff(1)
    env.process(patient(env, resource, 100, marks, "p0"))
    env.process(patient(env, resource, 100, marks, "p1", at=1))
    env.process(patient(env, resource, 100, marks, "p2", at=2))
    env.run(until=10)
    assert busy(resource) == 1

    reservations.set_staff(3)
    env.run(until=11)

    assert (reservations.staff, reservations.granted, reservations.waiting) == (3, 1, 0)
    assert ("p1", "empieza", 10) in marks
    assert ("p2", "empieza", 10) in marks
    assert busy(resource) == 3


def test_subir_con_concedidas_y_en_espera():
    # G = 1 y W = 2; al subir 3 plazas se cancelan las 2 que esperan y se libera la
    # concedida: la plaza va al paciente en cola, no a una reserva.
    env = simpy.Environment()
    resource = simpy.PriorityResource(env, capacity=4)
    reservations = Reservations(resource)
    marks: list = []
    for i, duration in enumerate([10, 100, 100, 100]):
        env.process(patient(env, resource, duration, marks, f"p{i}"))
    env.process(patient(env, resource, 100, marks, "cola", at=1))
    env.run(until=5)
    reservations.set_staff(1)  # 3 reservas esperando
    env.run(until=15)  # p0 termina en 10: una reserva concedida
    assert (reservations.granted, reservations.waiting) == (1, 2)

    reservations.set_staff(4)
    env.run(until=16)

    assert (reservations.staff, reservations.granted, reservations.waiting) == (4, 0, 0)
    assert ("cola", "empieza", 15) in marks
    assert busy(resource) == 4
    assert resource.queue == []


def test_misma_plantilla_no_hace_nada():
    env = simpy.Environment()
    resource = simpy.PriorityResource(env, capacity=4)
    reservations = Reservations(resource)
    reservations.set_staff(2)
    before = list(resource.users)

    reservations.set_staff(2)

    assert resource.users == before
    assert resource.queue == []


@pytest.mark.parametrize("staff", [0, 5])
def test_plantilla_fuera_de_rango(staff):
    env = simpy.Environment()
    reservations = Reservations(simpy.PriorityResource(env, capacity=4))

    with pytest.raises(RuntimeError, match="staff"):
        reservations.set_staff(staff)
