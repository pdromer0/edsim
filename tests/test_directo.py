"""Directo en memoria (tarea 6.3): fuentes, censo, inicio, directo y fin.

Con el reloj falso, órdenes programadas y un sumidero en memoria que anota el instante
de cada publicación, el directo entero corre en milisegundos (docs/specs/hito-6.md,
piezas 6 y 7). Primero, el anclaje al calendario y las dos fuentes; después, el log a
mano del censo de la 6.2 en directo, con valores calculados a mano.
"""

import hashlib
import math
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from test_census import emit_hand_log
from test_clinical_engine import CLINICAL_LOG_FINGERPRINT_V2

from edsim.arrivals.profile import load_profile
from edsim.engine.center import load_center
from edsim.engine.engine import simulate_ed, start_ed
from edsim.engine.events import EventLog, JsonlSink, MemorySink, read_events, to_json
from edsim.engine.scenarios import SCENARIO_START
from edsim.live.clock import FAKE_WALL_START, FakeClock
from edsim.live.control import PAUSE, RESUME, SPEED, STOP, Command, NoControl, ScriptedControl
from edsim.live.directo import (
    EngineSource,
    LogSource,
    MemoryLiveSink,
    RunEnd,
    RunInfo,
    RunStart,
    SinkError,
    anchored_start,
    run_live,
)
from edsim.live.pacer import MAX_SLICE, Pacer
from edsim.profiles.config import load_profiles

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


class FailingSink(TimedSink):
    """Un sumidero que falla en su k-ésimo write: los anteriores se confirmaron.

    Con ``end_fails``, publicar el fin también falla.
    """

    def __init__(self, clock: FakeClock, k: int, end_fails: bool = False) -> None:
        super().__init__(clock)
        self.k = k
        self.end_fails = end_fails
        self.end_calls = 0

    def write(self, event):
        if len(self.events) == self.k - 1:
            raise SinkError(
                "message not delivered",
                delivered=len(self.events),
                failed=(event.event_id,),
                last_delivered=self.events[-1].event_id,
            )
        super().write(event)

    def end(self, message):
        self.end_calls += 1
        if self.end_fails:
            raise RuntimeError("broker down")
        super().end(message)


def run_failing(sink):
    return run_live(
        LogSource(live_hand_log(), 180),
        Pacer(sink.clock, 60, (0.0, 0.0)),
        NoControl(),
        sink,
        start=120,
        horizon=180,
        run_info=INFO,
    )


def test_sumidero_que_falla_publica_fin_con_error():
    # Falla el 8.º write, la salida de EP-000002 a los 30 s (minuto 150): se confirmaron
    # el censo (6) y la salida de EP-000003.
    clock = FakeClock()
    sink = FailingSink(clock, 8)

    with pytest.raises(SinkError) as raised:
        run_failing(sink)

    assert raised.value.delivered == 7
    assert [describe(i) for i in sink.items] == ["inicio", *CENSUS, LIVE[0], "fin"]
    assert sink.run_end == RunEnd(
        run_id="rcenso",
        reason="error",
        sim_time=approx(150.0),
        last_event_id="rcenso-000000009",  # la salida de EP-000003
        published=7,
    )
    assert sink.times[-1] == approx(30)


def test_si_el_fin_tambien_falla_sale_el_error_original():
    clock = FakeClock()
    sink = FailingSink(clock, 3, end_fails=True)

    with pytest.raises(SinkError) as raised:
        run_failing(sink)

    assert sink.end_calls == 1
    assert sink.run_end is None
    assert any("broker down" in note for note in raised.value.__notes__)


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


# --- Directo = batch -----------------------------------------------------------------

SEED = 2026
DAYS = 3
HORIZON = DAYS * 1440
W = 2 * 1440
RUN_ID = "r2026"  # el mismo en los dos lados: el de simulate_ed por defecto
ANCHOR_WALL = datetime(2026, 3, 11, 9, 30, tzinfo=UTC)  # 10:30 en +01:00: W = 3.510
SCRIPT = [
    (100, Command(SPEED, 10)),
    (200, Command(PAUSE)),
    (260, Command(RESUME)),
    (400, Command(SPEED, "max")),  # la última: a velocidad máxima el reloj falso no avanza
]
"""Órdenes del test central, en segundos del reloj falso desde el arranque."""

ARRIVALS = DATA / "llegadas_ejemplo.toml"
PROFILES = DATA / "perfiles_ejemplo.toml"
CASES = {
    # caso: (centro, con perfiles clínicos, versión, anclado)
    "v1": ("centro_ejemplo.toml", False, 1, False),
    "v2": ("centro_ejemplo.toml", True, 2, False),
    "v3": ("centro_sala_ejemplo.toml", True, 3, False),
    "v3-anclada": ("centro_sala_ejemplo.toml", True, 3, True),
}


def write_v2_log(path: Path) -> Path:
    """Un log de la versión 2: el clínico sin sala con el número de versión de la 2.

    Es el de test_la_version_3_sin_sala_son_los_eventos_de_la_2: se comprueba su huella.
    """
    with JsonlSink(path) as sink:
        simulate_ed(
            load_center(DATA / "centro_ejemplo.toml"),
            load_profile(ARRIVALS),
            DAYS,
            SEED,
            sink=sink,
            profiles=load_profiles(PROFILES),
        )
    text = path.read_bytes()
    assert text.count(b'"schema_version": 3,') == text.count(b"\n")
    as_v2 = text.replace(b'"schema_version": 3,', b'"schema_version": 2,')
    assert hashlib.sha256(as_v2).hexdigest() == CLINICAL_LOG_FINGERPRINT_V2
    path.write_bytes(as_v2)
    return path


@pytest.fixture(scope="module")
def v2_log(tmp_path_factory):
    return write_v2_log(tmp_path_factory.mktemp("v2") / "eventos.jsonl")


def run_case(case: str, v2_path: Path):
    """El batch y el directo de un caso; devuelve lo necesario para compararlos."""
    center_file, clinical, version, anchored = CASES[case]
    clock = FakeClock(wall_start=ANCHOR_WALL if anchored else FAKE_WALL_START)
    profile = load_profile(ARRIVALS)
    start = W
    if anchored:
        start_date, start = anchored_start(clock.wall(), 2)
        profile = profile.with_start_date(start_date)

    if case == "v2":
        batch = list(read_events(v2_path))
        source = LogSource(read_events(v2_path), HORIZON)
    else:
        center = load_center(DATA / center_file)
        profiles = load_profiles(PROFILES) if clinical else None
        sink = MemorySink()
        simulate_ed(center, profile, DAYS, SEED, sink=sink, run_id=RUN_ID, profiles=profiles)
        batch = sink.events
        buffer = MemorySink()
        ed = start_ed(center, profile, DAYS, SEED, sink=buffer, run_id=RUN_ID, profiles=profiles)
        source = EngineSource(ed, buffer)

    info = RunInfo(
        run_id=RUN_ID,
        mode="replay" if case == "v2" else "directo",
        schema_version=version,
        seed=SEED,
        start_date=profile.start_date,
        anchored=anchored,
    )
    control = ScriptedControl(clock, SCRIPT)
    live = MemoryLiveSink()
    end = run_live(
        source,
        Pacer(clock, 60, (0.0, 0.0)),
        control,
        live,
        start=start,
        horizon=HORIZON,
        run_info=info,
    )
    return batch, live, end, control, start


def filtered_batch(batch: list, start: float) -> list:
    """La fórmula de la pieza 7, sin census ni open_episodes: sim_time >= W, sin episodio,
    o episodio abierto en W (llegó antes de W y no salió antes de W)."""
    before = [e for e in batch if e.sim_time < start]
    departed = {e.episode_id for e in before if e.event_type == "patient_departed"}
    still_open = {e.episode_id for e in before if e.episode_id is not None} - departed
    return [
        e
        for e in batch
        if e.sim_time >= start or e.episode_id is None or e.episode_id in still_open
    ]


@pytest.mark.parametrize("case", sorted(CASES))
def test_directo_igual_a_batch(case, v2_log):
    batch, live, end, control, start = run_case(case, v2_log)
    version = CASES[case][2]
    expected = filtered_batch(batch, start)

    assert {e.schema_version for e in batch} == {version}
    assert [to_json(e) for e in live.events] == [to_json(e) for e in expected]
    assert (end.reason, end.sim_time, end.published) == ("horizonte", HORIZON, len(expected))
    assert end.last_event_id == expected[-1].event_id

    # Guardas: el caso ocurre.
    census_size = live.run_start.census_events
    initial, direct = live.events[:census_size], live.events[census_size:]
    assert all(e.sim_time < start for e in initial)
    assert any(e.episode_id is None for e in initial)  # recursos
    assert any(e.episode_id is not None for e in initial)  # pacientes
    assert sum(e.sim_time < start for e in batch) > census_size  # calentamiento excluido
    assert direct
    assert [command for _, _, command in control.delivered] == [c for _, c in SCRIPT]
    assert all(0 <= seen - planned <= MAX_SLICE + TOL for planned, seen, _ in control.delivered)
    if version == 3:
        assert any(e.event_type == "box_released" for e in direct)  # con sala
