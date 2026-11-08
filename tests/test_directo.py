"""Directo en memoria (tarea 6.3): fuentes, censo, inicio, directo y fin.

Con el reloj falso, órdenes programadas y un sumidero en memoria que anota el instante
de cada publicación, el directo entero corre en milisegundos (docs/specs/hito-6.md,
piezas 6 y 7). Primero, el anclaje al calendario y las dos fuentes; después, el log a
mano del censo de la 6.2 en directo, con valores calculados a mano.
"""

import math
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from test_census import emit_hand_log

from edsim.arrivals.profile import load_profile
from edsim.engine.center import load_center
from edsim.engine.engine import simulate_ed, start_ed
from edsim.engine.events import EventLog, MemorySink, to_json
from edsim.engine.scenarios import SCENARIO_START
from edsim.live.clock import FakeClock
from edsim.live.control import STOP, Command, NoControl, ScriptedControl
from edsim.live.directo import (
    EngineSource,
    LogSource,
    MemoryLiveSink,
    RunEnd,
    RunInfo,
    RunStart,
    anchored_start,
    run_live,
)
from edsim.live.pacer import Pacer

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data"
TOL = 1e-9


def approx(x):
    return pytest.approx(x, abs=TOL)


# --- Anclaje al calendario -----------------------------------------------------------


@pytest.mark.parametrize(
    ("wall", "expected"),
    [
        # 10:30 en +01:00: dos días antes, y W = 2 × 1.440 + 630.
        (datetime(2026, 3, 11, 9, 30, tzinfo=UTC), (date(2026, 3, 9), 3510.0)),
        # Las 0:30 del 11 en +01:00: el día se toma en +01:00, no en UTC.
        (datetime(2026, 3, 10, 23, 30, tzinfo=UTC), (date(2026, 3, 9), 2910.0)),
    ],
)
def test_anclaje(wall, expected):
    assert anchored_start(wall, 2) == expected


def test_anclaje_con_otra_zona_y_segundos():
    tokyo = timezone(timedelta(hours=9))
    wall = datetime(2026, 3, 11, 18, 30, 15, 500_000, tzinfo=tokyo)  # 10:30:15,5 en +01:00
    assert anchored_start(wall, 0) == (date(2026, 3, 11), 630 + 15.5 / 60)


@pytest.mark.parametrize(
    ("wall", "days", "match"),
    [
        (datetime(2026, 3, 11, 10, 30), 2, "wall"),
        ("2026-03-11T09:30:00Z", 2, "wall"),
        (datetime(2026, 3, 11, 9, 30, tzinfo=UTC), -1, "warmup_days"),
        (datetime(2026, 3, 11, 9, 30, tzinfo=UTC), 2.0, "warmup_days"),
        (datetime(2026, 3, 11, 9, 30, tzinfo=UTC), True, "warmup_days"),
    ],
)
def test_anclaje_no_valido(wall, days, match):
    with pytest.raises(ValueError, match=match):
        anchored_start(wall, days)


# --- Fuentes -------------------------------------------------------------------------


def live_hand_log() -> list:
    """El log a mano del censo de la 6.2, más la salida de EP-000002 en 150 y la llegada
    de EP-000004 en 170, con la numeración del mismo log."""
    sink = MemorySink()
    log = EventLog("rcenso", SCENARIO_START, sink, schema_version=3)
    emit_hand_log(log)
    log.emit("patient_departed", 150.0, arrival_id=2, destino="alta")
    log.emit("patient_arrived", 170.0, arrival_id=4, medio="propios_medios")
    return sink.events


def test_fuente_de_log():
    events = live_hand_log()
    source = LogSource(iter(events), 120)

    got = []
    while (t := source.peek()) < math.inf:
        step = source.step()
        assert [e.sim_time for e in step] == [t]
        got += step

    # Los del instante del horizonte o después no salen, como en el motor.
    assert got == [e for e in events if e.sim_time < 120]
    with pytest.raises(RuntimeError, match="horizon"):
        source.step()


def test_fuente_de_log_vacia():
    source = LogSource([], 10)
    assert source.peek() == math.inf


def test_fuente_de_log_que_retrocede():
    events = live_hand_log()
    source = LogSource([events[-1], events[0]], 1000)
    with pytest.raises(ValueError, match="back in time"):
        source.step()


def test_fuente_del_motor_da_los_eventos_de_cada_paso():
    center = load_center(DATA / "centro_ejemplo.toml")
    profile = load_profile(DATA / "llegadas_ejemplo.toml")
    batch = MemorySink()
    simulate_ed(center, profile, 1, 2026, sink=batch, warmup_days=0)
    buffer = MemorySink()
    ed = start_ed(center, profile, 1, 2026, sink=buffer, warmup_days=0)
    source = EngineSource(ed, buffer)
    assert source.horizon == 1440

    got, empty_steps = [], 0
    while (t := source.peek()) < math.inf:
        step = source.step()
        assert all(e.sim_time == t for e in step)
        empty_steps += not step
        got += step

    assert [to_json(e) for e in got] == [to_json(e) for e in batch.events]
    assert got[0].event_type == "staffing_changed"  # emitido al construir, en el minuto 0
    assert empty_steps > 0  # guarda: hay pasos del motor sin eventos


# --- El directo con un log a mano ----------------------------------------------------

INFO = RunInfo(
    run_id="rcenso",
    mode="replay",
    schema_version=3,
    seed=2026,
    start_date=SCENARIO_START,
    anchored=False,
)

CENSUS = [
    ("staffing_changed", None, 0.0),
    ("staffing_changed", None, 0.0),
    ("patient_arrived", "EP-000002", 50.0),
    ("patient_registered", "EP-000002", 50.0),
    ("patient_arrived", "EP-000003", 60.0),
    ("patient_registered", "EP-000003", 60.0),
]
LIVE = [
    ("patient_departed", "EP-000003", 120.0),
    ("patient_departed", "EP-000002", 150.0),
    ("patient_arrived", "EP-000004", 170.0),
]


class TimedSink(MemoryLiveSink):
    """Un MemoryLiveSink que anota el instante del reloj de cada publicación y puede
    tardar ``delay`` segundos en cada evento, como un broker lento."""

    def __init__(self, clock: FakeClock, delay: float = 0.0) -> None:
        super().__init__()
        self.clock = clock
        self.delay = delay
        self.times: list[float] = []

    def start(self, message):
        self.times.append(self.clock.monotonic())
        super().start(message)

    def write(self, event):
        self.times.append(self.clock.monotonic())
        super().write(event)
        if self.delay:
            self.clock.sleep(self.delay)

    def end(self, message):
        self.times.append(self.clock.monotonic())
        super().end(message)


def describe(item):
    if isinstance(item, RunStart):
        return "inicio"
    if isinstance(item, RunEnd):
        return "fin"
    return (item.event_type, item.episode_id, item.sim_time)


def run_hand(*, events=None, script=(), interrupt_at=None, delay=0.0):
    """El directo del log a mano: W = 120, horizonte 180, ×60 desde el instante 0 s."""
    clock = FakeClock(interrupt_at=interrupt_at)
    sink = TimedSink(clock, delay)
    pacer = Pacer(clock, 60, (0.0, 0.0))
    source = LogSource(live_hand_log() if events is None else events, 180)
    end = run_live(
        source,
        pacer,
        ScriptedControl(clock, script),
        sink,
        start=120,
        horizon=180,
        run_info=INFO,
    )
    return end, sink


def test_directo_a_mano_hasta_el_horizonte():
    events = live_hand_log()
    end, sink = run_hand(events=events)

    assert [describe(i) for i in sink.items] == ["inicio", *CENSUS, *LIVE, "fin"]
    # El censo, de golpe en 0 s; la salida en W también en 0 s; luego cuando toca a ×60.
    assert sink.times == [approx(t) for t in [0, 0, 0, 0, 0, 0, 0, 0, 30, 50, 60]]

    assert sink.run_start == RunStart(
        info=INFO,
        live_start=120.0,
        horizon=180.0,
        speed=60.0,
        census_episodes=2,
        census_events=6,
    )
    assert (
        end
        == sink.run_end
        == RunEnd(
            run_id="rcenso",
            reason="horizonte",
            sim_time=180.0,
            last_event_id=events[-1].event_id,
            published=6 + 3,
        )
    )
    # Los mismos objetos Event que el log, no copias.
    assert all(any(e is f for f in events) for e in sink.events)


def test_directo_a_mano_con_parar():
    end, sink = run_hand(script=[(40.1, Command(STOP))])

    assert [describe(i) for i in sink.items] == ["inicio", *CENSUS, *LIVE[:2], "fin"]
    assert sink.times[-1] == approx(40.2)  # el primer tramo después de la orden
    assert end.reason == "parar"
    assert end.sim_time == approx(160.2)
    assert end.published == 6 + 2
    assert end.last_event_id == sink.events[-1].event_id


def test_directo_a_mano_con_ctrl_c():
    with pytest.raises(KeyboardInterrupt):
        run_hand(interrupt_at=45)


def test_directo_a_mano_con_ctrl_c_publica_fin():
    clock = FakeClock(interrupt_at=45)
    sink = TimedSink(clock)
    with pytest.raises(KeyboardInterrupt):
        run_live(
            LogSource(live_hand_log(), 180),
            Pacer(clock, 60, (0.0, 0.0)),
            NoControl(),
            sink,
            start=120,
            horizon=180,
            run_info=INFO,
        )

    assert [describe(i) for i in sink.items] == ["inicio", *CENSUS, *LIVE[:2], "fin"]
    assert sink.times[-1] == approx(45)
    end = sink.run_end
    assert end.reason == "interrupcion"
    assert end.sim_time == approx(165)
    assert end.published == 6 + 2


def test_el_ancla_es_tras_publicar_el_censo():
    # Publicar cada evento tarda 1 s: el censo acaba a los 6 s, y el directo se ancla ahí,
    # en (6 s, minuto 120), no en el arranque.
    _, sink = run_hand(delay=1.0)

    live_times = [t for t, i in zip(sink.times, sink.items, strict=True) if i in sink.events[6:]]
    assert live_times == [approx(6), approx(36), approx(56)]


def test_parar_con_retraso_no_pasa_del_horizonte():
    # Minutos 1, 2 y 3 con horizonte 4, a ×60 desde 0 s, y publicar cuesta 2 s: a los 7 s el
    # reloj simulado va por el minuto 7. La orden parar de los 6,5 s llega al esperar el
    # horizonte (objetivo pasado), y fin no pasa del horizonte.
    sink_log = MemorySink()
    log = EventLog("rretraso", SCENARIO_START, sink_log, schema_version=3)
    for i in (1, 2, 3):
        log.emit("patient_arrived", float(i), arrival_id=i, medio="ambulancia")
    clock = FakeClock()
    sink = TimedSink(clock, 2.0)
    info = RunInfo("rretraso", "replay", 3, 2026, SCENARIO_START, False)

    end = run_live(
        LogSource(sink_log.events, 4),
        Pacer(clock, 60, (0.0, 0.0)),
        ScriptedControl(clock, [(6.5, Command(STOP))]),
        sink,
        start=0,
        horizon=4,
        run_info=info,
    )

    assert sink.times[1:-1] == [approx(1), approx(3), approx(5)]
    assert end.reason == "parar"
    assert end.sim_time == 4.0
    assert end.published == 3


class WrongAliveSource(LogSource):
    """Un log con alive_episodes que no coincide con los abiertos en W, como un motor roto."""

    def alive_episodes(self) -> frozenset[str]:
        return frozenset({"EP-000002"})


def test_abiertos_distintos_de_vivos_es_un_error():
    clock = FakeClock()
    sink = MemoryLiveSink()
    with pytest.raises(RuntimeError, match="1 open and not alive"):
        run_live(
            WrongAliveSource(live_hand_log(), 180),
            Pacer(clock, 60, (0.0, 0.0)),
            NoControl(),
            sink,
            start=120,
            horizon=180,
            run_info=INFO,
        )
    assert sink.items == []


def engine_source_three_days():
    buffer = MemorySink()
    ed = start_ed(
        load_center(DATA / "centro_ejemplo.toml"),
        load_profile(DATA / "llegadas_ejemplo.toml"),
        3,
        2026,
        sink=buffer,
    )
    return EngineSource(ed, buffer)


@pytest.mark.parametrize(
    ("make_source", "horizon"),
    [(engine_source_three_days, 2880.0), (lambda: LogSource(live_hand_log(), 180), 200.0)],
    ids=["motor", "log"],
)
def test_horizonte_distinto_del_de_la_fuente(make_source, horizon):
    source = make_source()
    before = source.peek()
    sink = MemoryLiveSink()

    with pytest.raises(ValueError, match="horizon of the source"):
        run_live(
            source,
            Pacer(FakeClock(), 60, (0.0, 0.0)),
            NoControl(),
            sink,
            start=120,
            horizon=horizon,
            run_info=INFO,
        )
    assert sink.items == []
    assert source.peek() == before  # sin avanzar
    assert source.step()  # y sigue entera


@pytest.mark.parametrize(
    ("start", "horizon", "match"),
    [
        (-1, 180, "start must be"),
        (180, 180, "start must be"),
        (math.nan, 180, "start"),
        (120, math.inf, "horizon"),
        (True, 180, "start"),
    ],
)
def test_inicio_u_horizonte_no_validos(start, horizon, match):
    with pytest.raises(ValueError, match=match):
        run_live(
            LogSource([], 180),
            Pacer(FakeClock(), 60, (0.0, 0.0)),
            NoControl(),
            MemoryLiveSink(),
            start=start,
            horizon=horizon,
            run_info=INFO,
        )


def test_datos_de_la_ejecucion_no_validos_en_run_live():
    with pytest.raises(ValueError, match="run_info"):
        run_live(
            LogSource([], 180),
            Pacer(FakeClock(), 60, (0.0, 0.0)),
            NoControl(),
            MemoryLiveSink(),
            start=120,
            horizon=180,
            run_info={"run_id": "rcenso"},
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("run_id", ""),
        ("mode", "batch"),
        ("schema_version", 4),
        ("schema_version", True),
        ("schema_version", "3"),
        ("seed", -1),
        ("seed", 2026.0),
        ("start_date", datetime(2026, 1, 5)),
        ("anchored", 1),
    ],
)
def test_datos_de_la_ejecucion_no_validos(field, value):
    values = {
        "run_id": "rcenso",
        "mode": "directo",
        "schema_version": 3,
        "seed": 2026,
        "start_date": SCENARIO_START,
        "anchored": False,
    }
    with pytest.raises(ValueError, match=field):
        RunInfo(**{**values, field: value})
