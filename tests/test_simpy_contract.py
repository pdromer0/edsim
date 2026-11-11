"""Contrato de SimPy 4.1.2: el comportamiento de los recursos en el que se apoya el motor.

Como test_spawn_de_numpy_muta_el_objeto en el hito 2, estos tests no prueban código
de EDsim: fijan lo que hace la biblioteca instalada, leído en su código
(simpy/resources/resource.py, simpy/resources/base.py y simpy/events.py). Si una
versión nueva cambia algo, fallan aquí y no, de forma confusa, en el motor.

- La clave de una petición es (priority, instante de la petición, not preempt) y la
  cola se ordena por ella; con priority = (nivel, llegada) se comparan tuplas.
- PreemptiveResource desaloja al usuario de clave mayor, solo si es mayor que la del
  que pide, y concede la plaza en la misma llamada.
- La interrupción es URGENT y la concesión NORMAL: el desalojado reacciona antes,
  pero otros eventos del instante pueden ejecutarse entre ambos.
- Salir del with cancela una petición en cola y libera una concedida; liberar a un
  usuario ya desalojado no falla.
- Solo se intenta conceder la cabeza de la cola.
- Fuera de un with (reservas de turno): cancel() solo quita una petición que espera;
  release() solo quita una concedida, y la plaza pasa al siguiente al procesarse el
  Release. release() de una petición que espera no hace nada: hay que cancelarla.
- Con la misma prioridad para todos, PriorityResource concede en el orden de Resource.
- Hito 5 (tarea 5.1): en un instante, los eventos van por prioridad y después por orden
  de creación (simpy/core.py, Environment.schedule). Un Timeout recibe su orden al
  crearse, así que un plazo creado antes gana a una liberación del mismo instante; el
  plazo del paciente (Deadline, prioridad LATE = 2) va después de toda la cascada NORMAL
  de liberación, concesión y AnyOf. Un Timeout o un Deadline están triggered desde que se
  crean: su vencimiento se ve con processed. Un Timeout pendiente se puede volver a
  esperar después de un Interrupt.
"""

from collections.abc import Generator

import pytest
import simpy
from simpy.resources.resource import Preempted

from edsim.engine.patient import LATE, Deadline

Priority = tuple[int, float]


def hold(
    env: simpy.Environment,
    resource: simpy.PriorityResource,
    priority: Priority,
    duration: float,
    marks: list,
    *,
    at: float = 0.0,
    preempt: bool = False,
) -> Generator[simpy.Event]:
    """Espera hasta ``at``, pide el recurso, lo retiene ``duration`` y lo suelta.

    Anota en ``marks`` (prioridad, instante) al recibirlo y
    (prioridad, "desalojado", instante, causa) si lo desalojan.
    """
    yield env.timeout(at)
    with resource.request(priority=priority, preempt=preempt) as request:
        yield request
        marks.append((priority, env.now))
        try:
            yield env.timeout(duration)
        except simpy.Interrupt as interrupt:
            marks.append((priority, "desalojado", env.now, interrupt.cause))


# --- Clave y orden de la cola ------------------------------------------------------


def test_clave_de_la_peticion():
    env = simpy.Environment()
    resource = simpy.PriorityResource(env, capacity=1)
    env.run(until=7.0)

    request = resource.request(priority=(3, 2.5), preempt=True)

    assert request.key == ((3, 2.5), 7.0, False)
    assert resource.request(priority=(3, 2.5), preempt=False).key == ((3, 2.5), 7.0, True)


def test_cola_ordenada_por_la_tupla_aunque_se_pida_tarde():
    # Un usuario ocupa el recurso de 0 a 100. Luego piden, por este orden:
    # (5, 50) en 1, (3, 40) en 2, (3, 20) en 3 y (5, 30) en 4. Mismo nivel: por
    # llegada, aunque (3, 20) pida después que (3, 40). Distinto nivel: por nivel.
    env = simpy.Environment()
    resource = simpy.PriorityResource(env, capacity=1)
    marks: list = []
    env.process(hold(env, resource, (0, 0.0), 100, marks))
    for at, priority in [(1, (5, 50.0)), (2, (3, 40.0)), (3, (3, 20.0)), (4, (5, 30.0))]:
        env.process(hold(env, resource, priority, 10, marks, at=at))

    env.run(until=5)
    assert [r.priority for r in resource.queue] == [(3, 20.0), (3, 40.0), (5, 30.0), (5, 50.0)]

    env.run()
    assert marks == [
        ((0, 0.0), 0),
        ((3, 20.0), 100),
        ((3, 40.0), 110),
        ((5, 30.0), 120),
        ((5, 50.0), 130),
    ]


def test_empate_por_instante_de_la_peticion_y_luego_por_desalojo():
    # Misma prioridad: primero quien pidió antes. Misma prioridad y mismo instante:
    # primero la petición con preempt=True, aunque se creara después.
    env = simpy.Environment()
    resource = simpy.PriorityResource(env, capacity=1)
    resource.request(priority=(0, 0.0))  # ocupa el recurso
    env.run(until=1)
    first = resource.request(priority=(4, 7.0), preempt=False)
    env.run(until=2)
    late = resource.request(priority=(4, 7.0), preempt=False)
    late_preempt = resource.request(priority=(4, 7.0), preempt=True)

    assert resource.queue == [first, late_preempt, late]


# --- A quién desaloja PreemptiveResource --------------------------------------------


def test_desaloja_al_usuario_de_clave_mayor():
    # Tres boxes con niveles 3, 4 y 5; llega un nivel 1 con preempt=True y echa al
    # de clave mayor, el nivel 5, que recibe Preempted con el proceso que desaloja.
    env = simpy.Environment()
    boxes = simpy.PreemptiveResource(env, capacity=3)
    marks: list = []
    for i, level in enumerate([3, 4, 5]):
        env.process(hold(env, boxes, (level, float(i)), 100, marks, at=i))
    level1 = env.process(hold(env, boxes, (1, 15.0), 30, marks, at=15, preempt=True))

    env.run(until=16)

    (displaced,) = [m for m in marks if m[1] == "desalojado"]
    priority, _, now, cause = displaced
    assert (priority, now) == ((5, 2.0), 15)
    assert isinstance(cause, Preempted)
    assert cause.by is level1
    assert cause.resource is boxes
    assert cause.usage_since == 2
    assert ((1, 15.0), 15) in marks
    assert sorted(r.priority for r in boxes.users) == [(1, 15.0), (3, 0.0), (4, 1.0)]


def test_no_desaloja_a_quien_tiene_clave_menor():
    # Un nivel 1 que llegó en 0 ocupa el único box; otro nivel 1 que llegó en 5
    # pide con preempt=True: su clave es mayor, así que espera.
    env = simpy.Environment()
    boxes = simpy.PreemptiveResource(env, capacity=1)
    marks: list = []
    env.process(hold(env, boxes, (1, 0.0), 100, marks))
    env.process(hold(env, boxes, (1, 5.0), 10, marks, at=5, preempt=True))

    env.run()

    assert marks == [((1, 0.0), 0), ((1, 5.0), 100)]


def test_desaloja_a_un_nivel_1_que_llego_despues():
    # El motivo de que el motor decida preempt: SimPy solo compara claves, así que un
    # nivel 1 que llegó antes (0) echa a otro nivel 1 que llegó después (5) y ya
    # tenía el box.
    env = simpy.Environment()
    boxes = simpy.PreemptiveResource(env, capacity=1)
    marks: list = []
    env.process(hold(env, boxes, (1, 5.0), 100, marks, at=5))
    env.process(hold(env, boxes, (1, 0.0), 10, marks, at=8, preempt=True))

    env.run(until=9)

    (displaced,) = [m for m in marks if m[1] == "desalojado"]
    assert displaced[:3] == ((1, 5.0), "desalojado", 8)
    assert isinstance(displaced[3], Preempted)
    assert ((1, 0.0), 8) in marks


def test_sin_preempt_nunca_desaloja():
    env = simpy.Environment()
    boxes = simpy.PreemptiveResource(env, capacity=1)
    marks: list = []
    env.process(hold(env, boxes, (5, 0.0), 100, marks))
    env.process(hold(env, boxes, (1, 1.0), 10, marks, at=1, preempt=False))

    env.run()

    assert marks == [((5, 0.0), 0), ((1, 1.0), 100)]


# --- Orden en el mismo instante -------------------------------------------------------


def test_la_interrupcion_se_procesa_antes_que_la_concesion():
    # En t = 10 se ejecutan, por este orden de programación: el timeout del que
    # desaloja y el de un tercer proceso, ambos NORMAL. Al pedir, el desalojo
    # programa la interrupción (URGENT) y la concesión (NORMAL). Orden resultante:
    # pide, el desalojado atrapa Interrupt (URGENT, antes que el tercero aunque se
    # programó después), el tercero y, por último, la concesión. Por eso el motor
    # traspasa el número de box: otros eventos del instante caben entre medias.
    env = simpy.Environment()
    boxes = simpy.PreemptiveResource(env, capacity=1)
    marks: list[str] = []

    def victim() -> Generator[simpy.Event]:
        with boxes.request(priority=(5, 0.0), preempt=False) as request:
            yield request
            try:
                yield env.timeout(100)
            except simpy.Interrupt:
                marks.append("desalojado")

    def preemptor() -> Generator[simpy.Event]:
        yield env.timeout(10)
        marks.append("pide")
        with boxes.request(priority=(1, 10.0), preempt=True) as request:
            yield request
            marks.append("concedido")

    def other() -> Generator[simpy.Event]:
        yield env.timeout(10)
        marks.append("otro evento del instante")

    env.process(victim())
    env.process(preemptor())
    env.process(other())
    env.run()

    assert marks == ["pide", "desalojado", "otro evento del instante", "concedido"]


# --- Salir del with --------------------------------------------------------------------


def test_salir_del_with_sin_concesion_cancela_la_peticion():
    env = simpy.Environment()
    resource = simpy.PriorityResource(env, capacity=1)
    marks: list = []
    env.process(hold(env, resource, (0, 0.0), 100, marks))

    def waiter() -> Generator[simpy.Event]:
        yield env.timeout(1)  # pide cuando el titular ya tiene el recurso
        with resource.request(priority=(3, 1.0)) as request:
            try:
                yield request
            except simpy.Interrupt:
                marks.append(("interrumpido", len(resource.queue)))
        marks.append(("fuera del with", len(resource.queue)))

    process = env.process(waiter())
    env.run(until=5)
    process.interrupt("desalojo")
    env.run()

    assert marks[1:] == [("interrumpido", 1), ("fuera del with", 0)]


def test_liberar_un_usuario_ya_desalojado_no_falla():
    env = simpy.Environment()
    boxes = simpy.PreemptiveResource(env, capacity=1)
    held: dict[str, simpy.Event] = {}
    marks: list = []

    def victim() -> Generator[simpy.Event]:
        with boxes.request(priority=(5, 0.0), preempt=False) as request:
            held["victim"] = request
            yield request
            try:
                yield env.timeout(100)
            except simpy.Interrupt:
                marks.append(request in boxes.users)
        # El with ya llamó a release; una segunda liberación tampoco falla.
        yield boxes.release(request)
        marks.append([r.priority for r in boxes.users])

    env.process(victim())
    env.process(hold(env, boxes, (1, 5.0), 50, marks, at=5, preempt=True))
    env.run(until=6)

    assert marks[0] is False
    assert marks[-1] == [(1, 5.0)]
    assert boxes.count == 1


def test_interrupcion_con_la_peticion_concedida_sin_reanudar():
    # El titular suelta el recurso en 10; al procesarse la liberación, SimPy concede
    # la plaza a W (succeed), pero W aún no se ha reanudado. Si W recibe Interrupt en
    # ese hueco, cancel() no hace nada (ya está concedida) y release() la quita de
    # users: al salir del with el recurso queda libre igualmente.
    env = simpy.Environment()
    resource = simpy.PriorityResource(env, capacity=1)
    held: dict[str, simpy.Event] = {}
    marks: list = []

    def waiter() -> Generator[simpy.Event]:
        with resource.request(priority=(3, 1.0)) as request:
            held["w"] = request
            try:
                yield request
            except simpy.Interrupt:
                marks.append(("interrumpido", request.triggered, request in resource.users))
        marks.append(("fuera del with", resource.count))

    def holder() -> Generator[simpy.Event]:
        request = resource.request(priority=(0, 0.0))
        yield request
        yield env.timeout(10)
        yield resource.release(request)
        # La liberación ya se procesó: W tiene la plaza, pero no se ha reanudado.
        marks.append(("concedida sin reanudar", held["w"].triggered, held["w"].processed))
        w_process.interrupt("desalojo")

    env.process(holder())
    w_process = env.process(waiter())
    env.run()

    assert marks == [
        ("concedida sin reanudar", True, False),
        ("interrumpido", True, True),
        ("fuera del with", 0),
    ]


# --- Solo la cabeza de la cola ----------------------------------------------------------


def test_solo_se_intenta_la_cabeza_de_la_cola():
    # U (5, 0) ocupa el único box. A (1, 1) espera sin desalojo y queda en cabeza.
    # B (2, 2) pide con preempt=True: su clave es menor que la de U, pero queda detrás
    # de A, y _trigger_put solo intenta la cabeza, así que B no desaloja a nadie.
    env = simpy.Environment()
    boxes = simpy.PreemptiveResource(env, capacity=1)
    marks: list = []
    env.process(hold(env, boxes, (5, 0.0), 100, marks))
    env.process(hold(env, boxes, (1, 1.0), 10, marks, at=1, preempt=False))
    env.process(hold(env, boxes, (2, 2.0), 10, marks, at=2, preempt=True))

    env.run()

    assert marks == [((5, 0.0), 0), ((1, 1.0), 100), ((2, 2.0), 110)]


@pytest.mark.parametrize("resource_type", [simpy.PriorityResource, simpy.PreemptiveResource])
def test_tuplas_con_enteros_y_reales_se_comparan_sin_error(resource_type):
    env = simpy.Environment()
    resource = resource_type(env, capacity=1)
    resource.request(priority=(0, 0.0))
    for priority in [(5, 3.25), (5, 3), (1, 10.0), (5, 2.0)]:
        resource.request(priority=priority, preempt=False)

    assert [r.priority for r in resource.queue] == [(1, 10.0), (5, 2.0), (5, 3), (5, 3.25)]


# --- Reservas de turno: cancelar y liberar fuera de un with -------------------------------
#
# Las reservas de turno (tarea 3.5) son peticiones creadas por el proceso de turnos, sin
# with y sin que nadie las espere con yield. Para quitarlas al subir la plantilla, la que
# aún espera se cancela y la concedida se libera; estos tests fijan por qué.


def test_cancelar_una_peticion_en_cola_la_quita_sin_conceder_nada():
    env = simpy.Environment()
    resource = simpy.PriorityResource(env, capacity=1)
    holder = resource.request(priority=(1, 0.0))
    waiting = resource.request(priority=(0, 0.0), preempt=False)
    assert resource.queue == [waiting]

    waiting.cancel()
    env.run()

    assert resource.queue == []
    assert resource.users == [holder]
    assert not waiting.triggered


def test_cancelar_una_peticion_concedida_no_hace_nada():
    env = simpy.Environment()
    resource = simpy.PriorityResource(env, capacity=1)
    granted = resource.request(priority=(0, 0.0), preempt=False)
    assert granted.triggered

    granted.cancel()
    env.run()

    assert resource.users == [granted]


def test_liberar_fuera_del_with_concede_al_procesarse_la_liberacion():
    # release() quita la petición de users en la misma llamada, pero el siguiente de la
    # cola recibe la plaza cuando SimPy procesa el evento Release: más tarde en el mismo
    # instante, no dentro de la llamada.
    env = simpy.Environment()
    resource = simpy.PriorityResource(env, capacity=1)
    reservation = resource.request(priority=(0, 0.0), preempt=False)
    marks: list = []

    def patient() -> Generator[simpy.Event]:
        with resource.request(priority=(1, 0.0)) as request:
            yield request
            marks.append(("concedido", env.now))

    def shift() -> Generator[simpy.Event]:
        yield env.timeout(480)
        resource.release(reservation)
        marks.append(("tras release", reservation in resource.users, len(resource.queue)))

    env.process(patient())
    env.process(shift())
    env.run()

    assert marks == [("tras release", False, 1), ("concedido", 480)]


def test_liberar_una_peticion_en_cola_no_la_quita():
    # La trampa: release() de una petición que espera no hace nada (users.remove falla en
    # silencio) y la petición sigue en la cola. En cuanto se libera una plaza, la ocupa:
    # una reserva fantasma que deja la plantilla corta. Por eso se cancela.
    env = simpy.Environment()
    resource = simpy.PriorityResource(env, capacity=1)
    holder = resource.request(priority=(1, 0.0))
    waiting = resource.request(priority=(0, 0.0), preempt=False)

    resource.release(waiting)
    env.run(until=1)
    assert resource.queue == [waiting]

    resource.release(holder)
    env.run(until=2)
    assert resource.users == [waiting]


@pytest.mark.parametrize("cancel_first", [True, False])
def test_el_orden_de_cancelar_y_liberar_en_un_instante_no_importa(cancel_first):
    # Una reserva concedida y otra en cola; se quitan las dos en el mismo instante. Como la
    # concesión llega al procesarse el Release, la plaza va al paciente en ambos órdenes.
    env = simpy.Environment()
    resource = simpy.PriorityResource(env, capacity=1)
    granted = resource.request(priority=(0, 0.0), preempt=False)
    env.run(until=1)
    waiting = resource.request(priority=(0, 0.0), preempt=False)
    patient = resource.request(priority=(1, 1.0))

    if cancel_first:
        waiting.cancel()
        resource.release(granted)
    else:
        resource.release(granted)
        waiting.cancel()
    env.run(until=2)

    assert resource.users == [patient]
    assert resource.queue == []


def grant_order(resource_type: type, requests: list[tuple[float, str]]) -> list[str]:
    """Orden en que un recurso de una plaza concede peticiones hechas en ``at``."""
    env = simpy.Environment()
    resource = resource_type(env, capacity=1)
    kwargs = {} if resource_type is simpy.Resource else {"priority": (1, 0.0)}
    order: list[str] = []

    def user(at: float, name: str) -> Generator[simpy.Event]:
        yield env.timeout(at)
        with resource.request(**kwargs) as request:
            yield request
            order.append(name)
            yield env.timeout(10)

    for at, name in requests:
        env.process(user(at, name))
    env.run()
    return order


def test_prioridad_igual_concede_en_el_orden_de_resource():
    # Con la misma prioridad para todos, PriorityResource ordena por el instante de la
    # petición y, en el mismo instante, conserva el orden de llegada a la cola (sort
    # estable): el mismo orden FIFO que Resource.
    requests = [(1.0, "a"), (1.0, "b"), (2.0, "c"), (2.0, "d"), (2.0, "e"), (3.0, "f")]

    fifo = grant_order(simpy.Resource, requests)

    assert fifo == ["a", "b", "c", "d", "e", "f"]
    assert grant_order(simpy.PriorityResource, requests) == fifo


def test_la_reserva_adelanta_a_quien_pidio_antes():
    # (0, 0.0) va por delante de cualquier (nivel, llegada) con nivel >= 1 y de la
    # prioridad de triaje (1, 0.0), aunque esas peticiones se hicieran antes.
    env = simpy.Environment()
    resource = simpy.PriorityResource(env, capacity=1)
    resource.request(priority=(1, 0.0))  # ocupa el recurso
    env.run(until=1)
    early = [resource.request(priority=p) for p in [(1, 0.0), (1, 0.5), (5, 0.0)]]
    env.run(until=2)
    reservation = resource.request(priority=(0, 0.0), preempt=False)

    assert resource.queue == [reservation, *early]


# --- El plazo del paciente (hito 5) --------------------------------------------------


def wait_with_deadline(
    env: simpy.Environment, resource: simpy.Resource, deadline: simpy.Event, marks: list
) -> Generator[simpy.Event]:
    """Pide el recurso y espera «el recurso o el plazo»; anota si lo recibió."""
    with resource.request() as request:
        yield request | deadline
        marks.append((env.now, request.triggered, deadline.processed))


def hold_until(
    env: simpy.Environment, resource: simpy.Resource, until: float
) -> Generator[simpy.Event]:
    with resource.request() as request:
        yield request
        yield env.timeout(until - env.now)


def tie(deadline_factory) -> list:
    """Un recurso que se libera en 10 y un plazo que vence en 10, creado antes que la
    liberación (el orden de creación decide entre eventos de la misma prioridad)."""
    env = simpy.Environment()
    resource = simpy.Resource(env, capacity=1)
    marks: list = []
    deadline = deadline_factory(env, 10)  # creado en 0, antes que nada
    env.process(hold_until(env, resource, 10))
    env.process(wait_with_deadline(env, resource, deadline, marks))
    env.run()
    return marks


def test_con_un_timeout_normal_el_empate_lo_gana_el_plazo():
    # La trampa que evita LATE: el plazo, creado antes, se procesa antes que la liberación.
    assert tie(lambda env, d: env.timeout(d)) == [(10, False, True)]


def test_con_un_deadline_el_empate_lo_gana_el_recurso():
    # Liberación, concesión y AnyOf son NORMAL y se crean en el instante 10; el Deadline,
    # de prioridad 2, va después aunque se creó antes.
    assert tie(lambda env, d: Deadline(env, d)) == [(10, True, False)]


def test_deadline_va_despues_de_lo_normal_creado_en_su_instante():
    env = simpy.Environment()
    order: list = []
    deadline = Deadline(env, 5)
    deadline.callbacks.append(lambda _: order.append("plazo"))

    def chain() -> Generator[simpy.Event]:
        yield env.timeout(5)
        order.append("normal")
        yield env.timeout(0)  # creado en 5, después del plazo
        order.append("normal creado en 5")

    env.process(chain())
    env.run()
    assert order == ["normal", "normal creado en 5", "plazo"]
    assert LATE == 2


@pytest.mark.parametrize("factory", [simpy.Environment.timeout, Deadline])
def test_triggered_desde_su_creacion_y_processed_al_vencer(factory):
    env = simpy.Environment()
    event = factory(env, 5)
    assert (event.triggered, event.processed) == (True, False)
    env.run(until=4)
    assert event.processed is False
    env.run(until=6)
    assert event.processed is True


def test_deadline_con_retardo_negativo_falla():
    with pytest.raises(ValueError, match="negative delay"):
        Deadline(simpy.Environment(), -1)


def test_un_timeout_pendiente_se_vuelve_a_esperar_tras_un_interrupt():
    # La cama del ingresado: el desalojo interrumpe la espera, pero el Timeout sigue en la
    # cola, y el paciente lo espera otra vez en el pasillo.
    env = simpy.Environment()
    marks: list = []

    def patient() -> Generator[simpy.Event]:
        bed = env.timeout(10)
        try:
            yield bed
        except simpy.Interrupt:
            marks.append(("interrumpido", env.now, bed.processed))
            yield bed
        marks.append(("cama", env.now))

    def displacer(process: simpy.Process) -> Generator[simpy.Event]:
        yield env.timeout(3)
        process.interrupt("desalojo")

    process = env.process(patient())
    env.process(displacer(process))
    env.run()
    assert marks == [("interrumpido", 3, False), ("cama", 10)]
