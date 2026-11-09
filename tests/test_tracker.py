"""El estado del consumidor del directo (tarea 6.6): censo en vivo, idempotencia y orden.

El LiveTracker se alimenta igual con un directo en memoria (es un LiveSink) que con la
lectura de Kafka (add con el topic, la partición, el offset y la marca del broker). Primero,
con un log a mano de cuatro episodios que pasan por las siete ubicaciones de LocationState
y por la sala de resultados, con valores calculados a mano en el plan. Después, la prueba
central: «consumidor = batch», el estado final de cada episodio leído en vivo es el del
batch filtrado con el mismo run_id.
"""

from pathlib import Path

import pytest

from edsim.arrivals.profile import load_profile
from edsim.engine.center import load_center
from edsim.engine.engine import simulate_ed
from edsim.engine.events import EventLog, MemorySink
from edsim.engine.scenarios import SCENARIO_START
from edsim.live.census import census, live_events
from edsim.live.clock import FakeClock
from edsim.live.control import MAX_SPEED, NoControl
from edsim.live.directo import LIVE, LogSource, MemoryLiveSink, RunInfo, run_live
from edsim.live.launch import prepare_live, run_prepared
from edsim.live.pacer import Pacer
from edsim.live.tracker import LOCATIONS, LiveTracker, ReceivedEvent, fold_states
from edsim.profiles.config import load_profiles

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data"

# --- El log a mano -------------------------------------------------------------------

A, D, B, C = "EP-000001", "EP-000002", "EP-000003", "EP-000004"


def occupancy_log() -> list:
    """Los 36 eventos del plan, en orden de emisión (catálogo 3).

    A llega en 0, triaje de 5 a 10, box 1 en 20, valoración inicial de 30 a 40, en 40 pide
    pruebas y deja el box (sala de resultados), resultado en 60, box 2 en 70, reevaluación
    de 75 a 85 y sale en 85. D llega en 2, triaje de 3 a 8, box 2 y valoración en 9, y sale
    en 19. B llega en 12, triaje de 15 a 25, box 1 en 40, valoración de 45 a 55 y en 55
    pide pruebas sin dejar el box. C llega en 50 y no se clasifica. Al salir de un box, como
    el motor: assessment_ended, disposition_decided y patient_departed en el mismo instante,
    sin box_released.
    """
    sink = MemorySink()
    log = EventLog("rocupa", SCENARIO_START, sink, schema_version=3)
    a, d, b, c = 1, 2, 3, 4
    person = {"edad": 50, "sexo": "mujer"}

    def arrive(who, t):
        log.emit("patient_arrived", t, arrival_id=who, medio="propios_medios")
        log.emit("patient_registered", t, arrival_id=who, **person)

    def leave(who, t, tipo):
        log.emit("assessment_ended", t, arrival_id=who, tipo=tipo, interrumpida=False)
        log.emit("disposition_decided", t, arrival_id=who, destino="alta")
        log.emit("patient_departed", t, arrival_id=who, destino="alta")

    def assess(who, t, tipo, box):
        log.emit("assessment_started", t, arrival_id=who, tipo=tipo, pool="medicos", box=box)

    def triaged(who, t):
        log.emit("triage_completed", t, arrival_id=who, nivel=4, motivo="otros")

    log.emit("staffing_changed", 0.0, recurso="enfermeria_triaje", anterior=0, nueva=2)  # 1
    log.emit("staffing_changed", 0.0, recurso="medicos", anterior=0, nueva=3)  # 2
    arrive(a, 0.0)  # 3, 4
    arrive(d, 2.0)  # 5, 6
    log.emit("triage_started", 3.0, arrival_id=d, circuito="enfermeria")  # 7
    log.emit("triage_started", 5.0, arrival_id=a, circuito="enfermeria")  # 8
    triaged(d, 8.0)  # 9
    log.emit("box_assigned", 9.0, arrival_id=d, box=2)  # 10
    assess(d, 9.0, "inicial", 2)  # 11
    triaged(a, 10.0)  # 12
    arrive(b, 12.0)  # 13, 14
    log.emit("triage_started", 15.0, arrival_id=b, circuito="enfermeria")  # 15
    leave(d, 19.0, "inicial")  # 16, 17, 18
    log.emit("box_assigned", 20.0, arrival_id=a, box=1)  # 19
    triaged(b, 25.0)  # 20
    assess(a, 30.0, "inicial", 1)  # 21
    log.emit("assessment_ended", 40.0, arrival_id=a, tipo="inicial", interrumpida=False)  # 22
    log.emit("test_ordered", 40.0, arrival_id=a, pruebas=["ecg"])  # 23
    log.emit("box_released", 40.0, arrival_id=a, box=1, espera="resultados")  # 24
    log.emit("box_assigned", 40.0, arrival_id=b, box=1)  # 25
    assess(b, 45.0, "inicial", 1)  # 26
    arrive(c, 50.0)  # 27, 28
    log.emit("assessment_ended", 55.0, arrival_id=b, tipo="inicial", interrumpida=False)  # 29
    log.emit("test_ordered", 55.0, arrival_id=b, pruebas=["analitica"])  # 30
    log.emit("test_resulted", 60.0, arrival_id=a, resultados={"ecg": "normal"})  # 31
    log.emit("box_assigned", 70.0, arrival_id=a, box=2)  # 32
    assess(a, 75.0, "reevaluacion", 2)  # 33
    leave(a, 85.0, "reevaluacion")  # 34, 35, 36
    return sink.events


def test_el_log_a_mano_es_el_del_plan():
    events = occupancy_log()
    assert len(events) == 36
    by_episode = {ep: sum(e.episode_id == ep for e in events) for ep in (A, D, B, C)}
    assert by_episode == {A: 15, D: 9, B: 8, C: 2}


def row(**counts) -> dict:
    return {place: counts.get(place, 0) for place in LOCATIONS}


@pytest.mark.parametrize(
    ("t", "expected", "still_open", "room"),
    [
        (12, row(waiting_triage=1, waiting_box=1, assessment=1), 3, 0),
        (22, row(triage=1, waiting_doctor=1), 2, 0),
        (50, row(waiting_triage=1, assessment=1, waiting_tests=1), 3, 1),
        (80, row(waiting_triage=1, reassessment=1, waiting_tests=1), 3, 0),
    ],
)
def test_ocupacion_a_mano_en_cuatro_instantes(t, expected, still_open, room):
    tracker = LiveTracker()
    for event in occupancy_log():
        tracker.write(event)

    occupancy = tracker.occupancy_at(t)

    assert dict(occupancy.by_location) == expected
    assert (occupancy.at, occupancy.open, occupancy.results_room) == (t, still_open, room)


def test_cada_ubicacion_aparece_en_la_tabla():
    # Guarda: los cuatro instantes cubren las siete ubicaciones de LocationState.
    tracker = LiveTracker()
    for event in occupancy_log():
        tracker.write(event)
    seen = {
        p for t in (12, 22, 50, 80) for p, n in tracker.occupancy_at(t).by_location.items() if n
    }
    assert seen == set(LOCATIONS)


def test_estado_final_y_abiertos():
    tracker = LiveTracker()
    for event in occupancy_log():
        tracker.write(event)

    assert tracker.open_episodes() == {B, C}
    assert tracker.states[B].location() == "waiting_tests" and tracker.states[B].box == 1
    assert tracker.states[C].location() == "waiting_triage"
    assert tracker.states[A].departed and not tracker.states[A].results_room
    final = tracker.occupancy()
    assert dict(final.by_location) == row(waiting_triage=1, waiting_tests=1)
    assert (final.at, final.open, final.results_room) == (None, 2, 0)
    assert tracker.staff == {"enfermeria_triaje": 2, "medicos": 3}
    assert tracker.episode_order_errors == 0


# --- Un directo del log a mano: idempotencia y fin adelantado -------------------------

W_HAND, HORIZON_HAND = 30, 90


def hand_run() -> MemoryLiveSink:
    """El directo del log de ocupación con W = 30 y horizonte 90, a velocidad máxima."""
    clock = FakeClock()
    sink = MemoryLiveSink()
    info = RunInfo("rocupa", LIVE, 3, 2026, SCENARIO_START, False)
    run_live(
        LogSource(occupancy_log(), HORIZON_HAND),
        Pacer(clock, MAX_SPEED, (0.0, 0.0)),
        NoControl(),
        sink,
        start=W_HAND,
        horizon=HORIZON_HAND,
        run_info=info,
    )
    return sink


def number(event) -> int:
    """El número del evento en el log a mano (#1 a #36)."""
    return int(event.event_id.rsplit("-", 1)[1]) + 1


def test_el_directo_a_mano_publica_11_de_censo_y_16_en_directo():
    sink = hand_run()
    assert (sink.run_start.census_events, sink.run_start.census_episodes) == (11, 2)
    assert [number(e) for e in sink.events[:11]] == [1, 2, 3, 4, 8, 12, 13, 14, 15, 19, 20]
    assert sink.run_end.published == 27 == len(sink.events)


def feed(tracker: LiveTracker, items) -> None:
    for item in items:
        if isinstance(item, ReceivedEvent):
            tracker.add(item)
        elif hasattr(item, "event_id"):
            tracker.write(item)
        elif hasattr(item, "info"):
            tracker.start(item)
        else:
            tracker.end(item)


def test_los_repetidos_no_cambian_el_estado():
    sink = hand_run()
    clean = LiveTracker()
    feed(clean, sink.items)

    # Se repiten al final, como una relectura tras reiniciar el consumidor: el box_assigned
    # de A en 20 (#19, del censo), su box_released en 40 (#24, en directo) y su salida (#36).
    by_number = {number(e): e for e in sink.events}
    tracker = LiveTracker()
    feed(tracker, [*sink.items, by_number[19], by_number[24], by_number[36]])

    assert tracker.duplicates == 3
    assert (tracker.distinct, tracker.complete, tracker.missing) == (27, True, 0)
    assert tracker.states == clean.states
    assert not tracker.states[A].results_room  # sin descartar, A acabaría en la sala
    assert tracker.episode_order_errors == 0


def test_el_fin_antes_que_los_dos_ultimos():
    sink = hand_run()
    start, *events, end = sink.items
    tracker = LiveTracker()
    feed(tracker, [start, *events[:-2], end])

    assert (tracker.complete, tracker.missing) == (False, 2)
    feed(tracker, events[-2:])
    assert (tracker.complete, tracker.missing) == (True, 0)


def test_antes_del_fin_no_se_sabe_lo_que_falta():
    tracker = LiveTracker()
    feed(tracker, hand_run().items[:-1])
    assert (tracker.complete, tracker.missing) == (False, None)


# --- Latencias y particiones, a mano -------------------------------------------------


def test_latencias_a_mano():
    events = occupancy_log()
    tracker = LiveTracker()
    marks = [(1_000_000, 1000.010), (1_000_250, 1000.300), (1_000_500, 1000.520)]
    for event, (broker_ms, received) in zip(events, marks, strict=False):
        tracker.add(ReceivedEvent(event, broker_ms=broker_ms, received=received))

    assert tracker.latencies_ms == [pytest.approx(10), pytest.approx(50), pytest.approx(20)]
    summary = tracker.latency_summary()
    assert summary.count == 3
    assert summary.median_ms == pytest.approx(20)
    assert summary.p95_ms == pytest.approx(47)  # 20 + 0,9 × (50 − 20)
    assert summary.max_ms == pytest.approx(50)


def test_sin_marcas_no_hay_latencias():
    tracker = LiveTracker()
    tracker.write(occupancy_log()[0])
    assert tracker.latency_summary() is None


def partition_events() -> dict:
    """E1 a E4 con sus instantes, emitidos en orden de sim_time."""
    sink = MemorySink()
    log = EventLog("rparticion", SCENARIO_START, sink, schema_version=3)
    for who, t in ((4, 5), (1, 10), (2, 15), (1, 20), (3, 25), (2, 30), (1, 35), (2, 38), (4, 40)):
        log.emit("patient_arrived", float(t), arrival_id=who, medio="propios_medios")
    return {(e.episode_id, e.sim_time): e for e in sink.events}


def test_particiones_a_mano():
    by = partition_events()
    topic = "ed.patient.events"
    received = [  # (partición, offset, episodio, sim_time), en orden de recepción
        (0, 0, 1, 10), (0, 1, 1, 20), (1, 0, 2, 15), (1, 1, 2, 30), (0, 2, 3, 25),
        (2, 0, 4, 5), (2, 1, 4, 40), (0, 3, 1, 35), (1, 2, 2, 38),
    ]  # fmt: skip
    tracker = LiveTracker()
    for partition, offset, who, t in received:
        event = by[f"EP-{who:06d}", float(t)]
        tracker.add(ReceivedEvent(event, topic, partition, offset))

    assert dict(tracker.by_partition) == {(topic, 0): 4, (topic, 1): 3, (topic, 2): 2}
    assert tracker.episode_order_errors == 0
    # Inversiones contra el máximo ya recibido en otra partición: el 3.º, 5.º, 6.º, 8.º y
    # 9.º. Contra el anterior serían 4: el 9.º (38) llega tras el 35.
    assert tracker.cross_partition_inversions == 5


def test_un_orden_roto_dentro_de_un_episodio_se_cuenta():
    by = partition_events()
    tracker = LiveTracker()
    tracker.add(ReceivedEvent(by["EP-000001", 20.0], "t", 0, 0))
    tracker.add(ReceivedEvent(by["EP-000001", 10.0], "t", 0, 1))
    assert tracker.episode_order_errors == 1


def test_un_evento_de_otra_ejecucion():
    tracker = LiveTracker("rotra")
    with pytest.raises(ValueError, match="rocupa"):
        tracker.write(occupancy_log()[0])


# --- Consumidor = batch ---------------------------------------------------------------

SEED, DAYS, WARMUP = 2026, 3, 2
W = WARMUP * 1440
MODELS = {
    1: (DATA / "centro_ejemplo.toml", None),
    3: (DATA / "centro_sala_ejemplo.toml", DATA / "perfiles_ejemplo.toml"),
}


def live_and_batch(version: int, run_id: str):
    """El directo en memoria sobre un LiveTracker y el batch filtrado del mismo run_id."""
    center_path, profiles_path = MODELS[version]
    center = load_center(center_path)
    profile = load_profile(DATA / "llegadas_ejemplo.toml")
    profiles = None if profiles_path is None else load_profiles(profiles_path)
    prepared = prepare_live(
        center, profile, DAYS, SEED, warmup_days=WARMUP, run_id=run_id, profiles=profiles
    )
    tracker = LiveTracker()
    run_prepared(prepared, clock=FakeClock(), speed=MAX_SPEED, control=NoControl(), sink=tracker)
    batch = MemorySink()
    simulate_ed(
        center, profile, DAYS, SEED, sink=batch, warmup_days=WARMUP, run_id=run_id,
        profiles=profiles,
    )  # fmt: skip
    return tracker, census(batch.events, W) + live_events(batch.events, W)


@pytest.mark.parametrize("version", [1, 3])
def test_consumidor_igual_a_batch(version):
    tracker, filtered = live_and_batch(version, f"rconsumidor{version}")

    assert {e.schema_version for e in filtered} == {version}
    assert tracker.complete and tracker.duplicates == 0
    assert tracker.states == fold_states(filtered)
    assert tracker.episode_order_errors == 0
    if version == 3:  # guarda: el caso de la sala de resultados ocurre
        assert any(e.event_type == "box_released" for e in filtered)


def test_el_orden_entre_particiones_no_cambia_el_estado():
    # Los mismos publicados repartidos en 3 «particiones» por episodio y leídos por turnos:
    # el estado final es el mismo, porque cada episodio sigue en su orden.
    tracker, filtered = live_and_batch(3, "rparticiones")
    partitions = [[], [], []]
    for e in filtered:
        key = 0 if e.episode_id is None else int(e.episode_id[3:]) % 3
        partitions[key].append(e)
    interleaved = []
    while any(partitions):
        for p in partitions:
            if p:
                interleaved.append(p.pop(0))
    assert interleaved != filtered

    shuffled = LiveTracker()
    for i, event in enumerate(interleaved):
        shuffled.add(ReceivedEvent(event, "t", i % 3))

    assert shuffled.states == tracker.states
    assert shuffled.episode_order_errors == 0
    assert shuffled.cross_partition_inversions > 0
