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
"""

from collections.abc import Generator

import pytest
import simpy
from simpy.resources.resource import Preempted

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
