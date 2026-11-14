"""El directo con lo registrado: `run_live(..., recording=…)` (tarea 7.4).

Con `--registro`, por el sumidero solo pasa lo registrado: la verdad va paso a paso a la sala
de espera, y el censo y el directo son sus registros, con el `run_id` derivado. Aquí, con el
escenario L de la 7.1 como «motor falso» (`LogSource`), el reloj falso y un sumidero en
memoria que anota el instante de cada publicación, con valores calculados a mano.

Cada test dice qué error pilla:

- solo viaja lo registrado, y cada registro sale a la hora de su `sim_time` registrado (V12;
  y el pacer, si esperase a la hora verdadera);
- el censo con `W` = 1.140: los abiertos son los de la verdad (V32) y los números son los de
  la grabación entera, con huecos (V33); una corrección de un episodio cerrado va al directo;
- la reemisión (`RecordedLog`) publica lo mismo que la sala;
- `parar` con registros en la sala: el `fin` cuenta solo lo publicado;
- los errores de uso: sala sin `registro` en el `inicio`, o al revés;
- el lanzador: la reemisión con registro es lo registrado por lotes, con y sin carpeta, y una
  carpeta que no coincide es un error (V35); el directo se anuncia con el derivado;
- el lento, «directo = lotes» de lo registrado por versión del catálogo, con un motor de verdad
  y el perfil realista: el único que pilla la sala de espera con miles de hechos (V11).
"""

import re
import shutil
from datetime import date
from pathlib import Path

import pytest
from registro_factory import (
    DERIVED,
    HORIZON,
    RUN,
    SEED,
    START,
    make_profile,
    run_l,
    scenario_l,
    scenario_l_dice,
)
from runaway import check_calls
from test_directo import ARRIVALS, CASES, DAYS, RUN_ID, SCRIPT, write_v2_log
from test_directo import HORIZON as HORIZON_3D
from test_directo import SEED as SEED_3D
from test_directo import W as W_3D
from test_launch import REPLAY_RUN, save_run

from edsim.arrivals.profile import load_profile
from edsim.clinical_record import (
    CORRECTION,
    DUPLICATE,
    LOST,
    WITH_SLIPS,
    Record,
    RecordStream,
    load_record_profiles,
    record,
    record_from_json,
    record_json,
)
from edsim.engine.center import load_center
from edsim.engine.engine import simulate_ed, start_ed
from edsim.engine.events import MemorySink, read_events, to_json
from edsim.live.clock import FAKE_WALL_START, FakeClock
from edsim.live.control import STOP, Command, NoControl, ScriptedControl
from edsim.live.directo import (
    EngineSource,
    LogSource,
    MemoryLiveSink,
    RecordedLog,
    RecordInfo,
    RunEnd,
    RunInfo,
    RunStart,
    run_live,
)
from edsim.live.launch import prepare_live, prepare_replay, run_prepared, with_recording
from edsim.live.pacer import Pacer
from edsim.profiles.config import load_profiles
from edsim.runs import RecordingMismatchError, RunStore, record_run
from edsim.runs.recorded import RunLogError

RECORD_INFO = RecordInfo(RUN, "prueba", SEED)
INFO = RunInfo(DERIVED, "replay", 4, 2026, START, False, RECORD_INFO)
TRUE_INFO = RunInfo(RUN, "replay", 4, 2026, START, False)


class TimedSink(MemoryLiveSink):
    """Un MemoryLiveSink que anota el instante del reloj de cada publicación, con tope."""

    def __init__(self, clock: FakeClock, limit: int = 100_000) -> None:
        super().__init__()
        self.clock = clock
        self.limit = limit
        self.times: list[float] = []

    def _note(self) -> None:
        check_calls(len(self.times) + 1, self.limit, "TimedSink")
        self.times.append(round(self.clock.monotonic(), 6))

    def start(self, message):
        self._note()
        super().start(message)

    def write(self, event):
        self._note()
        super().write(event)

    def end(self, message):
        self._note()
        super().end(message)


def l_recording():
    return RecordStream(make_profile(), SEED, horizon=HORIZON, run_id=RUN, dice=scenario_l_dice())


def run_l_live(start: float, *, recording=None, script=(), info=INFO):
    """El escenario L en directo, ×60 (un minuto simulado por segundo real) desde 0 s."""
    clock = FakeClock()
    sink = TimedSink(clock)
    end = run_live(
        LogSource(scenario_l(), HORIZON),
        Pacer(clock, 60, (0.0, 0.0)),
        ScriptedControl(clock, script),
        sink,
        start=start,
        horizon=HORIZON,
        run_info=info,
        recording=l_recording() if recording is None else recording,
    )
    return end, sink


def numbers(items) -> list[str]:
    return [item.event_id.removeprefix(f"{DERIVED}-").lstrip("0") for item in items]


def test_solo_viaja_lo_registrado_y_cada_registro_sale_a_su_hora():
    """Con `W` = 1.000, todo es directo: los siete registros, ninguno de la verdad (V12), y el
    triaje de L3 sale a 1.031,2 (31,2 s), su hora registrada, detrás de la llegada de 1.028,0."""
    end, sink = run_l_live(1000.0)

    assert all(isinstance(item, Record) for item in sink.events)
    assert {item.run_id for item in sink.events} == {DERIVED}
    assert [record_json(r) for r in sink.events] == [record_json(r) for r in run_l().records]
    assert numbers(sink.events) == ["1", "2", "3", "4", "5", "6", "7"]
    assert sink.times == [0.0, 20.0, 22.5, 28.0, 31.2, 60.0, 60.5, 166.2, 440.0]
    assert sink.run_start.info == INFO
    assert (sink.run_start.census_episodes, sink.run_start.census_events) == (0, 0)
    assert end == RunEnd(DERIVED, "horizonte", HORIZON, f"{DERIVED}-000000007", 7)


def test_el_censo_de_lo_registrado_sale_de_los_abiertos_de_la_verdad():
    """`W` = 1.140: EP-000001 salió en 1.135 (cerrado en la verdad, aunque su salida se olvidó);
    EP-000002 sigue dentro. Censo = el registro 3 (la llegada de EP-000002), con su número de
    la grabación entera; directo = la corrección 7, de un episodio ya cerrado (V32, V33)."""
    end, sink = run_l_live(1140.0)

    items = sink.items
    assert isinstance(items[0], RunStart) and isinstance(items[-1], RunEnd)
    assert numbers(sink.events) == ["3", "7"]
    assert [(r.event_type, r.episode_id) for r in sink.events] == [
        ("patient_arrived", "EP-000002"),
        ("record_corrected", "EP-000001"),
    ]
    assert (sink.run_start.census_episodes, sink.run_start.census_events) == (1, 1)
    assert sink.times == [0.0, 0.0, 26.2, 300.0]
    assert end == RunEnd(DERIVED, "horizonte", HORIZON, f"{DERIVED}-000000007", 2)


@pytest.mark.parametrize("start", [1000.0, 1140.0])
def test_la_reemision_publica_lo_mismo_que_la_sala(start):
    """`RecordedLog` (los registros de `record`, ya ordenados) frente a `RecordStream`."""
    _, from_room = run_l_live(start)
    _, from_log = run_l_live(start, recording=RecordedLog(run_l().records))

    assert from_log.items == from_room.items
    assert from_log.times == from_room.times


def test_parar_con_registros_en_la_sala_solo_cuenta_lo_publicado():
    """Parar a los 25 s (minuto 1.025): han salido el 1 y el 2; los demás no se publican."""
    end, sink = run_l_live(1000.0, script=[(25.0, Command(STOP))])

    assert numbers(sink.events) == ["1", "2"]
    assert end.reason == "parar"
    assert end.published == 2
    assert end.last_event_id == f"{DERIVED}-000000002"
    assert end.sim_time == pytest.approx(1025.0, abs=0.25)  # la orden se ve en un tramo de 0,2 s


def test_lo_registrado_y_el_bloque_registro_van_juntos():
    with pytest.raises(ValueError, match="needs both"):
        run_l_live(1000.0, info=TRUE_INFO)
    with pytest.raises(ValueError, match="needs both"):
        run_live(
            LogSource(scenario_l(), HORIZON),
            Pacer(FakeClock(), 60, (0.0, 0.0)),
            NoControl(),
            MemoryLiveSink(),
            start=1000.0,
            horizon=HORIZON,
            run_info=INFO,
        )


def test_una_cota_nan_es_un_error_tambien_en_la_reemision():
    """Como `RecordStream.ready`: con NaN, toda comparación es falsa y no saldría nada."""
    with pytest.raises(ValueError, match="bound must be a number"):
        RecordedLog(run_l().records).ready(float("nan"))


def test_un_registro_que_retrocede_no_vale_en_la_reemision():
    records = run_l().records
    with pytest.raises(ValueError, match="goes back"):
        RecordedLog([records[3], records[2]])


# --- Lanzar y reemitir con registro (launch) --------------------------------------------

PROFILES_FILE = Path(__file__).resolve().parent.parent / "config" / "registro_clinico.toml"
DATA = Path(__file__).resolve().parent / "data"


def filtered_records(records, truth, start: float) -> list:
    """La fórmula de «filtrado igual», sin `census`, `open_episodes` ni `recorded_census`: los
    registros con `sim_time` >= W, sin episodio, o de un episodio que la *verdad* tiene abierto
    en W (llegó antes de W y no salió antes de W, ni yéndose sin ser visto)."""
    before = [e for e in truth if e.sim_time < start]
    departed = {
        e.episode_id for e in before if e.event_type in ("patient_departed", "patient_left_wbs")
    }
    still_open = {e.episode_id for e in before if e.episode_id is not None} - departed
    return [
        r
        for r in records
        if r.sim_time >= start or r.episode_id is None or r.episode_id in still_open
    ]


def replay(root, **options) -> tuple:
    prepared = prepare_replay(
        root, REPLAY_RUN, record_profile="realista", profiles_file=PROFILES_FILE, **options
    )
    sink = TimedSink(FakeClock())
    run_prepared(prepared, clock=FakeClock(), speed="max", control=NoControl(), sink=sink)
    return prepared, sink


@pytest.fixture(scope="module")
def saved_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("ejecuciones")
    save_run(root, REPLAY_RUN)
    return root


@pytest.fixture
def root(saved_root, tmp_path):
    """Una copia de la ejecución guardada, para escribir su carpeta de registros."""
    copy = tmp_path / "ejecuciones"
    shutil.copytree(saved_root, copy)
    return copy


def test_la_reemision_con_registro_es_lo_registrado_por_lotes_con_y_sin_carpeta(root):
    """Sin carpeta, lo calculado con `record`; con ella (`registro generar`), lo mismo, tras
    compararla byte a byte. Las dos, `registrado.jsonl` filtrado como el directo."""
    without, sink_without = replay(root)
    result = record_run(RunStore(root), REPLAY_RUN, "realista", profiles_file=PROFILES_FILE)
    with_folder, sink_with = replay(root)

    lines = (result.path / "registrado.jsonl").read_text(encoding="utf-8").splitlines()
    records = [record_from_json(line) for line in lines]
    truth = list(read_events(root / REPLAY_RUN / "eventos.jsonl"))
    expected = [record_json(r) for r in filtered_records(records, truth, 1440.0)]
    assert [record_json(r) for r in sink_with.events] == expected
    assert sink_without.items == sink_with.items
    assert (without.replayed.checked, with_folder.replayed.checked) == (None, result.path)
    derived = f"{REPLAY_RUN}_realista_s2026"
    assert with_folder.info.run_id == sink_with.run_end.run_id == derived
    assert with_folder.info.record == RecordInfo(REPLAY_RUN, "realista", 2026)
    # Guardas: hay censo, el calentamiento de los cerrados se queda fuera y hay directo.
    census = sink_with.run_start.census_events
    assert 0 < census < sum(r.sim_time < 1440.0 for r in records)
    assert len(sink_with.events) > census


@pytest.mark.parametrize("change", ["una-linea-de-menos", "otros-perfiles"])
def test_una_carpeta_que_no_coincide_es_un_error(root, tmp_path, change):
    """La reemisión nunca publica algo distinto de lo registrado por lotes (V35)."""
    result = record_run(RunStore(root), REPLAY_RUN, "realista", profiles_file=PROFILES_FILE)
    profiles = PROFILES_FILE
    if change == "una-linea-de-menos":
        path = result.path / "registrado.jsonl"
        path.write_text("".join(path.read_text(encoding="utf-8").splitlines(True)[:-1]))
    else:
        text = PROFILES_FILE.read_text(encoding="utf-8")
        profiles = tmp_path / "otros.toml"
        assert text.count("olvido = 0.005") == 1
        profiles.write_text(text.replace("olvido = 0.005", "olvido = 0.006"), encoding="utf-8")

    with pytest.raises(RecordingMismatchError, match="is not what record gives") as caught:
        prepare_replay(root, REPLAY_RUN, record_profile="realista", profiles_file=profiles)
    fingerprints = re.findall(r"fingerprint (\S+?)\)?;?(?: |$)", str(caught.value))
    assert len(fingerprints) == 2
    assert (fingerprints[0] == fingerprints[1]) == (change == "una-linea-de-menos")


@pytest.mark.parametrize("broken", ["sin-registrado", "fichero"])
def test_una_carpeta_que_no_es_un_registro_es_un_error_de_datos(root, broken):
    """Si `registros/realista-s2026` existe y no es un registro (le falta `registrado.jsonl`, o
    es un fichero), es un `RunLogError`, de los datos (código 1), no un `OSError` (código 2)."""
    result = record_run(RunStore(root), REPLAY_RUN, "realista", profiles_file=PROFILES_FILE)
    if broken == "sin-registrado":
        (result.path / "registrado.jsonl").unlink()
    else:
        shutil.rmtree(result.path)
        result.path.write_text("no es una carpeta")

    with pytest.raises(RunLogError, match="is not a recording"):
        prepare_replay(root, REPLAY_RUN, record_profile="realista", profiles_file=PROFILES_FILE)


@pytest.fixture(scope="module")
def models():
    return {
        "centro": load_center(DATA / "centro_sala_ejemplo.toml"),
        "llegadas": load_profile(DATA / "llegadas_ejemplo.toml"),
        "perfiles": load_profiles(DATA / "perfiles_ejemplo.toml"),
    }


def live_prepared(models, run_id="rdirecto"):
    return prepare_live(
        models["centro"],
        models["llegadas"],
        2,
        2026,
        warmup_days=1,
        run_id=run_id,
        profiles=models["perfiles"],
    )


def test_con_registro_el_directo_se_anuncia_con_el_run_id_derivado(models):
    realista = load_record_profiles(PROFILES_FILE)["realista"]
    prepared = with_recording(live_prepared(models), realista, 7)

    assert prepared.info == RunInfo(
        "rdirecto_realista_s7", "directo", 3, 2026, date(2026, 1, 5), False,
        RecordInfo("rdirecto", "realista", 7),
    )  # fmt: skip
    assert isinstance(prepared.recording, RecordStream)
    assert prepared.recording.run_id == prepared.info.run_id
    with pytest.raises(ValueError, match="already publishes"):
        with_recording(prepared, realista, 7)
    # Un --run-id de 50 caracteres: el derivado tendría 65.
    with pytest.raises(ValueError, match="derived run_id"):
        with_recording(live_prepared(models, "x" * 50), realista, 2026)


# --- Directo = lotes de lo registrado (lento, por versión del catálogo) --------------------

SLOW_CASES = ("v1", "v2", "v3", "v4")
"""Los casos de «directo = batch» del hito 6, uno por versión: v1, v3 y v4 con el motor y
v2 con un log (`LogSource`); los cuatro con la sala de espera, `RecordStream`."""


@pytest.fixture(scope="module")
def v2_log(tmp_path_factory):
    return write_v2_log(tmp_path_factory.mktemp("v2") / "eventos.jsonl")


def run_recorded_case(case: str, v2_path: Path):
    """Lo registrado por lotes y en directo de un caso, con el perfil realista de `config/`."""
    center_file, profiles_file, version, anchored = CASES[case]
    assert not anchored
    clock = FakeClock(wall_start=FAKE_WALL_START)
    profile = load_profile(ARRIVALS)
    if case == "v2":
        batch = list(read_events(v2_path))
        source = LogSource(read_events(v2_path), HORIZON_3D)
    else:
        center = load_center(DATA / center_file)
        profiles = None if profiles_file is None else load_profiles(profiles_file)
        sink = MemorySink()
        simulate_ed(center, profile, DAYS, SEED_3D, sink=sink, run_id=RUN_ID, profiles=profiles)
        batch = sink.events
        buffer = MemorySink()
        ed = start_ed(center, profile, DAYS, SEED_3D, sink=buffer, run_id=RUN_ID, profiles=profiles)
        source = EngineSource(ed, buffer)

    realista = load_record_profiles(PROFILES_FILE)["realista"]
    recording = record(batch, realista, SEED_3D, horizon=HORIZON_3D, run_id=RUN_ID)
    room = RecordStream(realista, SEED_3D, horizon=HORIZON_3D, run_id=RUN_ID)
    info = RunInfo(
        recording.run_id,
        "replay" if case == "v2" else "directo",
        version,
        SEED_3D,
        profile.start_date,
        False,
        RecordInfo(RUN_ID, "realista", SEED_3D),
    )
    control = ScriptedControl(clock, SCRIPT)
    live = TimedSink(clock)
    end = run_live(
        source,
        Pacer(clock, 60, (0.0, 0.0)),
        control,
        live,
        start=W_3D,
        horizon=HORIZON_3D,
        run_info=info,
        recording=room,
    )
    return batch, recording, live, end, control


def line(item) -> str:
    """La línea de lo publicado: la de `registrado.jsonl` de un registro, o la de la verdad."""
    return record_json(item) if isinstance(item, Record) else to_json(item)


@pytest.mark.slow
@pytest.mark.parametrize("case", SLOW_CASES)
def test_directo_igual_a_lotes_de_lo_registrado(case, v2_log):
    """Con la misma verdad, el perfil realista y la semilla 2026, lo publicado (censo y
    directo) es `registrado.jsonl` filtrado como el directo, byte a byte, con las órdenes del
    hito 6 en medio. Es el único test que pilla los errores de la sala de espera con un motor
    de verdad (V11) y que la verdad no viaja (V12) con los cuatro catálogos."""
    batch, recording, live, end, control = run_recorded_case(case, v2_log)
    expected = filtered_records(recording.records, batch, W_3D)

    assert {e.schema_version for e in batch} == {CASES[case][2]}
    assert [line(i) for i in live.events] == [record_json(r) for r in expected]
    assert (end.reason, end.sim_time, end.published) == ("horizonte", HORIZON_3D, len(expected))
    assert end.run_id == recording.run_id
    assert end.last_event_id == expected[-1].event_id
    assert [command for _, _, command in control.delivered] == [c for _, c in SCRIPT]

    # Guardas: el caso ocurre.
    census_size = live.run_start.census_events
    initial, direct = live.events[:census_size], live.events[census_size:]
    assert any(r.episode_id is None for r in initial)  # recursos
    assert any(r.episode_id is not None for r in initial)  # pacientes
    rows = {row.record_id: row for row in recording.notebook if row.record_id is not None}
    kinds = {rows[r.event_id].kind for r in direct}
    assert {DUPLICATE, CORRECTION, WITH_SLIPS} <= kinds
    assert any(row.kind == LOST for row in recording.notebook)
    # Desorden: dentro de un episodio, un registro sale detrás de otro de un hecho posterior.
    fact = {r.event_id: int(rows[r.event_id].fact_id[-9:]) for r in direct}
    last: dict[str, int] = {}
    disorder = False
    for r in direct:
        if r.episode_id is not None and rows[r.event_id].kind != CORRECTION:
            disorder |= fact[r.event_id] < last.get(r.episode_id, -1)
            last[r.episode_id] = max(last.get(r.episode_id, -1), fact[r.event_id])
    assert disorder
    # Un registro de un episodio que la verdad cerró antes de W, en el directo (retrasado,
    # duplicado o corregido después de W).
    before = [e for e in batch if e.sim_time < W_3D]
    terminal = ("patient_departed", "patient_left_wbs")
    closed = {e.episode_id for e in before if e.event_type in terminal}
    assert any(r.episode_id in closed for r in direct)
    # V32: un episodio cerrado en la verdad antes de W sin su salida registrada antes de W
    # (olvidada o retrasada): con los abiertos de lo registrado entraría en el censo.
    departed_written = {
        r.episode_id for r in recording.records if r.event_type in terminal and r.sim_time < W_3D
    }
    assert closed - departed_written
