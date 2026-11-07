"""Turnos: calendario, reservas de capacidad y proceso de turnos.

El calendario (shift_at, shift_changes) se prueba sin SimPy. Las reservas se prueban
con un PriorityResource a mano, con pacientes que piden con TRIAGE_PRIORITY o con su
clave: así se ve cada caso (bajar con plazas libres o con todos ocupados, subir
cancelando las que esperan o liberando las concedidas) sin el resto del motor.
"""

import dataclasses
from collections.abc import Generator
from datetime import date
from pathlib import Path

import pytest
import simpy

from edsim.arrivals.profile import ArrivalProfile, load_profile
from edsim.arrivals.thinning import ArrivalRecord
from edsim.engine.center import CenterConfig, load_center
from edsim.engine.clinical import PatientDraws
from edsim.engine.engine import run_engine, simulate_ed
from edsim.engine.events import Event, EventLog, MemorySink
from edsim.engine.ground_truth import GroundTruth
from edsim.engine.invariants import check_invariants
from edsim.engine.resources import RESERVATION_PRIORITY, TRIAGE_PRIORITY, make_pools
from edsim.engine.shifts import Reservations, shift_at, shift_changes, start_shifts

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


# --- Proceso de turnos en el motor ------------------------------------------------------

DATA = Path(__file__).parent / "data"
CONFIG = Path(__file__).parent.parent / "config"
START = date(2026, 1, 5)


@pytest.fixture(scope="module")
def center() -> CenterConfig:
    return load_center(DATA / "centro_ejemplo.toml")


def draws(level: int, triage: float, assessment: float) -> PatientDraws:
    """Sorteos a mano, sin pruebas y con alta."""
    return PatientDraws(
        level=level,
        triage_time=triage,
        assessment_time=assessment,
        reassessment_time=10.0,
        needs_tests=False,
        test_turnaround=60.0,
        admitted=False,
    )


def simulate(
    center: CenterConfig, patients: list[tuple[float, PatientDraws]], days: int = 1
) -> list[Event]:
    """Motor con llegadas y sorteos a mano; comprueba las invariantes al terminar."""
    arrivals = [ArrivalRecord(i, t) for i, (t, _) in enumerate(patients)]
    sink = MemorySink()
    run = run_engine(
        center,
        arrivals,
        lambda arrival: patients[arrival.arrival_id][1],
        EventLog("rtest", START, sink),
        days,
    )
    truth = GroundTruth(episodes=run.episodes, days=())
    assert check_invariants(sink.events, center, ground_truth=truth, inside=run.inside) == []
    return sink.events


def staffing(events: list[Event]) -> list[tuple]:
    return [
        (e.sim_time, e.payload["recurso"], e.payload["anterior"], e.payload["nueva"])
        for e in events
        if e.event_type == "staffing_changed"
    ]


def starts(events: list[Event], event_type: str) -> list[tuple[str, float]]:
    return [(e.episode_id, e.sim_time) for e in events if e.event_type == event_type]


def busy_after(events: list[Event], time: float, pool: str = "medicos") -> int:
    """Ocupados del pool al acabar el instante ``time``, según el log."""
    start, end = POOL_EVENTS[pool]
    return sum(
        (e.event_type == start) - (e.event_type == end) for e in events if e.sim_time <= time
    )


POOL_EVENTS = {
    "medicos": ("assessment_started", "assessment_ended"),
    "enfermeria_triaje": ("triage_started", "triage_completed"),
}
ENF, MED = "enfermeria_triaje", "medicos"


def test_staffing_changed_en_el_minuto_0_y_en_cada_cambio(center):
    # Centro de ejemplo: enfermeras (3, 3, 2) y médicos (12, 12, 7). De 12 a 12 y de 3
    # a 3 (a las 15 h) no hay evento.
    events = simulate(center, [], days=2)

    assert staffing(events) == [
        (0.0, ENF, 0, 2),
        (0.0, MED, 0, 7),
        (480.0, ENF, 2, 3),
        (480.0, MED, 7, 12),
        (1320.0, ENF, 3, 2),
        (1320.0, MED, 12, 7),
        (1920.0, ENF, 2, 3),
        (1920.0, MED, 7, 12),
        (2760.0, ENF, 3, 2),
        (2760.0, MED, 12, 7),
    ]
    assert all(e.source_system == "rrhh" and e.episode_id is None for e in events)


def test_el_minuto_0_va_antes_que_una_llegada_en_el_minuto_0(center):
    events = simulate(center, [(0.0, draws(3, 5, 20))])

    assert [(e.event_type, e.sim_time) for e in events[:3]] == [
        ("staffing_changed", 0.0),
        ("staffing_changed", 0.0),
        ("patient_arrived", 0.0),
    ]


def test_plantilla_constante_solo_el_minuto_0(center):
    flat = dataclasses.replace(center, triage_nurses=(3, 3, 3), doctors=(12, 12, 12))

    assert staffing(simulate(flat, [], days=3)) == [(0.0, ENF, 0, 3), (0.0, MED, 0, 12)]


@pytest.fixture(scope="module")
def three_to_one(center) -> CenterConfig:
    """Médicos 3 de día y 1 de noche; enfermeras y boxes de sobra."""
    return dataclasses.replace(center, triage_nurses=(5, 5, 5), doctors=(3, 3, 1))


def test_bajada_con_todos_ocupados_espera_a_que_terminen(three_to_one):
    # Tres valoraciones terminan a las 22:10, 22:20 y 22:30; un nivel 2 y un nivel 5
    # esperan médico desde las 21:55. A las 22:00 la plantilla baja de 3 a 1: las dos
    # reservas toman las plazas de las 22:10 y 22:20, y el nivel 2 empieza a las 22:30,
    # cuando los ocupados bajan de 1. Nadie es interrumpido.
    patients = [
        (1300.0, draws(3, 5, 25)),  # EP-0: valoración 1305-1330
        (1301.0, draws(4, 5, 34)),  # EP-1: 1306-1340
        (1302.0, draws(5, 5, 43)),  # EP-2: 1307-1350
        (1310.0, draws(2, 5, 20)),  # EP-3: espera médico desde 1315
        (1311.0, draws(5, 5, 20)),  # EP-4: espera médico desde 1316
    ]

    events = simulate(three_to_one, patients)

    assert staffing(events)[-1] == (1320.0, MED, 3, 1)
    assert starts(events, "assessment_started") == [
        ("EP-000000", 1305.0),
        ("EP-000001", 1306.0),
        ("EP-000002", 1307.0),
        ("EP-000003", 1350.0),
        ("EP-000004", 1370.0),
    ]
    ended = [e for e in events if e.event_type == "assessment_ended"]
    assert [e.sim_time for e in ended[:3]] == [1330.0, 1340.0, 1350.0]
    assert not any(e.payload["interrumpida"] for e in ended)


def test_la_plaza_que_se_libera_justo_en_el_cambio_va_a_la_reserva(three_to_one):
    # EP-0 termina su valoración justo a las 22:00 (1320). release() lo saca de users en
    # el acto, pero la plaza se reparte al procesarse el Release, que se programa en
    # 1320 y va detrás del cambio de turno: la reserva se la queda, no el nivel 2.
    patients = [
        (880.0, draws(3, 5, 435)),  # EP-0: valoración 885-1320
        (1300.0, draws(4, 5, 35)),  # EP-1: 1305-1340
        (1301.0, draws(4, 5, 34)),  # EP-2: 1306-1340
        (1310.0, draws(2, 5, 20)),  # EP-3: espera médico desde 1315
    ]

    events = simulate(three_to_one, patients)

    assert ("EP-000003", 1340.0) in starts(events, "assessment_started")
    assert busy_after(events, 1320.0) == 2


def test_cada_cambio_de_turno_es_el_primer_evento_de_su_instante(center):
    # Un timeout a las 22:00 creado en el minuto 0, justo después de start_shifts, se
    # procesa después del cambio de turno: los timeouts de los cambios se crearon antes.
    # Si cada cambio programara el siguiente, el de las 22:00 se crearía a las 8:00 y
    # este timeout iría primero.
    env = simpy.Environment()
    sink = MemorySink()
    pools = make_pools(env, center)
    start_shifts(env, EventLog("rtest", START, sink), pools, center, days=1)
    seen: list[tuple] = []

    def other() -> Generator[simpy.Event]:
        yield env.timeout(1320)
        seen.append(staffing(sink.events)[-1])

    env.process(other())
    env.run(until=1321)

    assert seen == [(1320.0, MED, 12, 7)]


def test_bajada_de_enfermeras_con_todas_ocupadas(center):
    nurses = dataclasses.replace(center, triage_nurses=(3, 3, 1), doctors=(12, 12, 12))
    patients = [
        (1300.0, draws(3, 30, 20)),  # triaje 1300-1330
        (1301.0, draws(3, 39, 20)),  # 1301-1340
        (1302.0, draws(3, 48, 20)),  # 1302-1350
        (1310.0, draws(3, 5, 20)),  # espera triaje desde 1310
    ]

    events = simulate(nurses, patients)

    assert (1320.0, ENF, 3, 1) in staffing(events)
    assert starts(events, "triage_started")[-1] == ("EP-000003", 1350.0)


def test_subida_con_cola(three_to_one):
    # De noche hay 1 médico, ocupado hasta las 10:05; cuatro pacientes esperan médico
    # desde las 7:25. A las 8:00 la plantilla sube a 3: empiezan exactamente 2.
    patients = [(400.0, draws(3, 5, 200))] + [(440.0 + i, draws(3, 5, 30)) for i in range(4)]

    events = simulate(three_to_one, patients)

    assert (480.0, MED, 1, 3) in staffing(events)
    started_at_480 = [ep for ep, t in starts(events, "assessment_started") if t == 480.0]
    assert started_at_480 == ["EP-000001", "EP-000002"]
    assert busy_after(events, 480.0) == 3


def test_subida_con_reservas_sin_conceder(center):
    # Turnos 8, 12 y 22; médicos 1 de 8 a 12 y 4 el resto. A las 8:00 se baja de 4 a 1
    # con los 4 ocupados: 3 reservas esperan. EP-0 termina a las 10:00 y una reserva
    # queda concedida (1 concedida y 2 en espera). A las 12:00 se sube a 4: se cancelan
    # las 2 en espera y se libera la concedida, así que empieza EP-4 y hay 4 ocupados;
    # EP-5 empieza en cuanto termina el siguiente (EP-1, a las 13:26).
    short = dataclasses.replace(
        center, shift_starts=(8, 12, 22), triage_nurses=(6, 6, 6), doctors=(1, 4, 4)
    )
    patients = [
        (400.0, draws(3, 5, 195)),  # EP-0: valoración 405-600
        (401.0, draws(3, 5, 400)),  # EP-1: 406-806
        (402.0, draws(3, 5, 400)),  # EP-2: 407-807
        (403.0, draws(3, 5, 400)),  # EP-3: 408-808
        (410.0, draws(3, 5, 200)),  # EP-4: espera médico desde 415
        (411.0, draws(3, 5, 30)),  # EP-5: espera médico desde 416
    ]

    events = simulate(short, patients)

    assert staffing(events)[2:4] == [(480.0, MED, 4, 1), (720.0, MED, 1, 4)]
    assert busy_after(events, 600.0) == 3
    assert ("EP-000004", 720.0) in starts(events, "assessment_started")
    assert busy_after(events, 720.0) == 4
    assert ("EP-000005", 806.0) in starts(events, "assessment_started")


# --- Ejecuciones con la semilla -------------------------------------------------------


@pytest.fixture(scope="module")
def real() -> tuple[CenterConfig, ArrivalProfile]:
    # Modelo provisional con su centro, tests/data/centro_ejemplo.toml: la plantilla del
    # hito 3 y el bloque provisional, que config/centro.toml no tiene (tarea 4.9).
    center = load_center(Path(__file__).parent / "data" / "centro_ejemplo.toml")
    return center, load_profile(CONFIG / "llegadas.toml")


def run(center: CenterConfig, profile: ArrivalProfile, days: int, seed: int):
    sink = MemorySink()
    result = simulate_ed(center, profile, days, seed, sink=sink, warmup_days=0)
    return sink.events, result


def drops_with_more_busy(events: list[Event]) -> int:
    """Bajadas de plantilla con más ocupados que la plantilla nueva en el instante del cambio."""
    busy = dict.fromkeys(POOL_EVENTS, 0)
    count = 0
    for e in events:
        for pool, (start, end) in POOL_EVENTS.items():
            busy[pool] += (e.event_type == start) - (e.event_type == end)
        if e.event_type == "staffing_changed":
            new, pool = e.payload["nueva"], e.payload["recurso"]
            count += new < e.payload["anterior"] and busy[pool] > new
    return count


def test_triaje_en_orden_de_llegada(real):
    # Los triajes de enfermería van en orden de llegada, con los cambios de turno. Los
    # niveles 1 se clasifican en la puerta al llegar, delante de quien espera enfermera.
    events, _ = run(*real, days=7, seed=2026)

    arrival = dict(starts(events, "patient_arrived"))
    door = {
        e.episode_id
        for e in events
        if e.event_type == "triage_started" and e.payload["circuito"] == "puerta"
    }
    nurse_triaged = [ep for ep, _ in starts(events, "triage_started") if ep not in door]
    arrived = [ep for ep in arrival if ep not in door]
    assert nurse_triaged == arrived[: len(nurse_triaged)]

    door_starts = [(ep, t) for ep, t in starts(events, "triage_started") if ep in door]
    assert door_starts and all(t == arrival[ep] for ep, t in door_starts)
    # No es vacío: algún nivel 1 se clasificó mientras otro, llegado antes, esperaba.
    first_start = dict(starts(events, "triage_started"))
    assert any(
        arrival[other] < arrival[ep] < first_start[other] for ep in door for other in arrived
    )


def test_otra_plantilla_por_turno_mismo_ground_truth(real):
    center, profile = real
    other = dataclasses.replace(center, triage_nurses=(1, 3, 2), doctors=(6, 12, 3))

    events_a, result_a = run(center, profile, days=4, seed=2026)
    events_b, result_b = run(other, profile, days=4, seed=2026)

    assert result_a.ground_truth == result_b.ground_truth
    assert staffing(events_a) != staffing(events_b)
    assert starts(events_a, "assessment_started") != starts(events_b, "assessment_started")


@pytest.mark.parametrize("seed", [2026, 7, 31])
def test_sin_violaciones_con_el_centro_real(real, seed):
    center, profile = real
    events, result = run(center, profile, days=7, seed=seed)

    violations = check_invariants(
        events, center, ground_truth=result.ground_truth, inside=result.inside
    )
    assert violations == []


def test_sin_violaciones_con_cambios_de_plantilla_grandes(real):
    center, profile = real
    big = dataclasses.replace(center, triage_nurses=(3, 1, 1), doctors=(12, 4, 1))
    events, result = run(big, profile, days=4, seed=2026)

    violations = check_invariants(
        events, big, ground_truth=result.ground_truth, inside=result.inside
    )
    assert violations == []
    # Control: la prueba ejercita bajadas con el pool por encima de la plantilla nueva.
    assert drops_with_more_busy(events) >= 4
