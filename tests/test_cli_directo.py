"""La CLI `edsim directo` sin broker (tarea 6.5): preparar, lanzar, reemitir y control.

Lo que habla con Kafka se cambia por dobles en `edsim.cli` (connect_producer, KafkaControl
y ensure_topics), como los demás tests de la CLI cambian validate_engine; el reloj del
sistema, por un FakeClock. Así se prueban los códigos de salida, que los errores de uso
salen antes de conectar, el orden en que se crean las piezas y los textos.
"""

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fake_kafka import (
    REFUSED,
    FakeKafkaError,
    FakeProducer,
    install_fake_confluent_kafka,
    log_line,
    stats_json,
)
from test_directo import filtered_batch
from test_launch import REPLAY_DATE, REPLAY_RUN, save_run

from edsim.arrivals.profile import load_profile
from edsim.cli import main
from edsim.engine.center import load_center
from edsim.engine.engine import simulate_ed
from edsim.engine.events import MemorySink, read_events, to_json
from edsim.live.clock import FakeClock
from edsim.live.control import PAUSE, RESUME, SPEED, STOP, Command
from edsim.live.directo import MemoryLiveSink, RunEnd
from edsim.live.kafka import (
    MISSING_EXTRA_MESSAGE,
    BrokerUnavailableError,
    MissingKafkaExtraError,
    MissingTopicsError,
    TopicMismatchError,
    TopicsReport,
)
from edsim.live.messages import control_json
from edsim.live.topics import CONTROL, RUNS, TOPICS
from edsim.profiles.config import load_profiles

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data"
MODEL = [
    "--centro",
    str(DATA / "centro_sala_ejemplo.toml"),
    "--llegadas",
    str(DATA / "llegadas_ejemplo.toml"),
    "--perfiles",
    str(DATA / "perfiles_ejemplo.toml"),
]
LAUNCH = ["directo", "lanzar", *MODEL, "--dias", "2", "--calentamiento", "1"]
"""Un directo pequeño de tests/data: 2 días, W = 1 día."""


def batch_of(run_id: str) -> list:
    """El batch del directo de LAUNCH con ese run_id, filtrado como en la pieza 7."""
    sink = MemorySink()
    simulate_ed(
        load_center(DATA / "centro_sala_ejemplo.toml"),
        load_profile(DATA / "llegadas_ejemplo.toml"),
        2,
        2026,
        sink=sink,
        run_id=run_id,
        profiles=load_profiles(DATA / "perfiles_ejemplo.toml"),
        warmup_days=1,
    )
    return filtered_batch(sink.events, 1440)


@pytest.fixture(scope="module")
def saved(tmp_path_factory):
    """Una ejecución guardada como la de motor simular: 2 días, W 1, del 2026-03-09."""
    root = tmp_path_factory.mktemp("ejecuciones")
    save_run(root, REPLAY_RUN)
    return root


@pytest.fixture
def sin_conexion(monkeypatch):
    """Nada puede conectar con Kafka: si alguien lo intenta, el test falla."""

    def connect(*args, **kwargs):
        pytest.fail("conectó con Kafka")

    for name in ("connect_producer", "KafkaControl", "ensure_topics"):
        monkeypatch.setattr(f"edsim.cli.{name}", connect)


@pytest.fixture
def sinks(monkeypatch):
    """Los MemoryLiveSink que crea la CLI, para ver qué publicó."""
    created = []

    class Recording(MemoryLiveSink):
        def __init__(self):
            super().__init__()
            created.append(self)

    monkeypatch.setattr("edsim.cli.MemoryLiveSink", Recording)
    return created


def use_clock(monkeypatch, clock: FakeClock) -> FakeClock:
    monkeypatch.setattr("edsim.cli.SystemClock", lambda: clock)
    return clock


# --- Errores de uso: código 2, sin conectar -------------------------------------------

USAGE_ERRORS = {
    "lanzar-velocidad-0": ([*LAUNCH, "--velocidad", "0"], "--velocidad"),
    "lanzar-velocidad-negativa": ([*LAUNCH, "--velocidad", "-1"], "--velocidad"),
    "lanzar-velocidad-texto": ([*LAUNCH, "--velocidad", "rápido"], "--velocidad"),
    "lanzar-kafka-sin-puerto": ([*LAUNCH, "--kafka", "localhost"], "HOST:PUERTO"),
    "lanzar-kafka-puerto-texto": ([*LAUNCH, "--kafka", "localhost:puerto"], "HOST:PUERTO"),
    "lanzar-dias-iguales": ([*LAUNCH, "--dias", "2", "--calentamiento", "2"], "warmup"),
    "lanzar-anclado-dias-iguales": (
        [*LAUNCH, "--anclar", "--dias", "2", "--calentamiento", "2"],
        "warmup",
    ),
    "lanzar-provisional-y-perfiles": ([*LAUNCH, "--provisional"], "--provisional"),
    "lanzar-centro-que-no-existe": ([*LAUNCH, "--centro", "/no/existe.toml"], "--centro"),
    "lanzar-run-id-no-valido": ([*LAUNCH, "--run-id", "mal id"], "--run-id"),
    "lanzar-kafka-y-memoria": ([*LAUNCH, "--kafka", "localhost:9092", "--memoria"], "--memoria"),
    "lanzar-semilla-negativa": ([*LAUNCH, "--semilla", "-1"], "--semilla"),
    "reemitir-que-no-existe": (["directo", "reemitir", "rnoexiste", "{root}"], "rnoexiste"),
    "reemitir-velocidad-0": (["directo", "reemitir", REPLAY_RUN, "{root}", "--velocidad", "0"], "--velocidad"),  # noqa: E501
    "reemitir-calentamiento-igual": (["directo", "reemitir", REPLAY_RUN, "{root}", "--calentamiento", "2"], "warmup"),  # noqa: E501
    "reemitir-kafka-sin-puerto": (["directo", "reemitir", REPLAY_RUN, "{root}", "--kafka", "sinpuerto"], "HOST:PUERTO"),  # noqa: E501
    "control-sin-orden": (["directo", "control", "--run", "r1"], "--velocidad"),
    "control-dos-ordenes": (["directo", "control", "--run", "r1", "--pausar", "--parar"], "not allowed"),  # noqa: E501
    "control-velocidad-0": (["directo", "control", "--run", "r1", "--velocidad", "0"], "--velocidad"),  # noqa: E501
    "control-sin-run": (["directo", "control", "--pausar"], "--run"),
    "control-kafka-sin-puerto": (["directo", "control", "--run", "r1", "--parar", "--kafka", "sinpuerto"], "HOST:PUERTO"),  # noqa: E501
    "preparar-kafka-sin-puerto": (["directo", "preparar", "--kafka", "sinpuerto"], "HOST:PUERTO"),
}  # fmt: skip


@pytest.mark.parametrize("case", list(USAGE_ERRORS))
def test_errores_de_uso_antes_de_conectar(case, saved, sin_conexion, capsys):
    argv, message = USAGE_ERRORS[case]
    argv = [
        part for a in argv for part in (["--ejecuciones", str(saved)] if a == "{root}" else [a])
    ]

    with pytest.raises(SystemExit) as raised:
        main(argv)

    assert raised.value.code == 2
    captured = capsys.readouterr()
    assert message in captured.err
    assert captured.out == ""  # ni la cabecera: nada empieza


# --- En memoria ----------------------------------------------------------------------


def test_lanzar_en_memoria_a_velocidad_maxima(sinks, capsys):
    code = main([*LAUNCH, "--memoria", "--velocidad", "max", "--run-id", "rcli"])

    assert code == 0
    [live] = sinks
    expected = batch_of("rcli")
    assert [to_json(e) for e in live.events] == [to_json(e) for e in expected]
    start, end = live.run_start, live.run_end
    assert (end.reason, end.published) == ("horizonte", len(expected))
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "Directo · run_id rcli · velocidad máxima · en memoria"
    assert out[3] == (
        "2 días desde 2026-01-05 (1 de calentamiento) · W = 1440 min · horizonte 2880 min"
        " · semilla 2026"
    )
    assert out[4] == (
        f"Censo en W = 1440 min: {start.census_episodes} episodios abiertos,"
        f" {start.census_events} eventos; empieza el directo"
    )
    assert out[-1] == (
        f"Fin · motivo horizonte · {len(expected)} publicados ({start.census_events} de censo"
        f" y {len(expected) - start.census_events} en directo) · minuto 2880"
        f" · último event_id {expected[-1].event_id}"
    )


def test_lanzar_sin_run_id_usa_la_semilla_y_la_hora(sinks, monkeypatch, capsys):
    use_clock(monkeypatch, FakeClock(wall_start=datetime(2026, 11, 6, 16, 23, tzinfo=UTC)))

    assert main([*LAUNCH, "--memoria", "--velocidad", "max"]) == 0

    [live] = sinks
    assert "run_id r2026_20261106T172300 ·" in capsys.readouterr().out
    assert {e.run_id for e in live.events} == {"r2026_20261106T172300"}


def test_lanzar_anclado_en_memoria(sinks, monkeypatch):
    # 10:30 en +01:00 con 2 días de calentamiento: desde el 9 de marzo, W = 3.510.
    use_clock(monkeypatch, FakeClock(wall_start=datetime(2026, 3, 11, 9, 30, tzinfo=UTC)))
    argv = ["directo", "lanzar", *MODEL, "--dias", "3", "--calentamiento", "2", "--anclar"]

    assert main([*argv, "--memoria", "--velocidad", "max", "--run-id", "ranclado"]) == 0

    [live] = sinks
    start = live.run_start
    assert (start.info.start_date, start.live_start, start.info.anchored) == (
        date(2026, 3, 9),
        3510.0,
        True,
    )


def replay_lines(root: Path, start: float) -> list[str]:
    """Las líneas del eventos.jsonl guardado que publica un replay con ese W, tal cual."""
    path = root / REPLAY_RUN / "eventos.jsonl"
    keep = {e.event_id for e in filtered_batch(list(read_events(path)), start)}
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line for line in lines if json.loads(line)["event_id"] in keep]


def test_reemitir_en_memoria(saved, sinks, capsys):
    argv = ["directo", "reemitir", REPLAY_RUN, "--ejecuciones", str(saved)]

    assert main([*argv, "--memoria", "--velocidad", "max"]) == 0

    [live] = sinks
    assert [to_json(e) for e in live.events] == replay_lines(saved, 1440)
    info = live.run_start.info
    assert (info.mode, info.run_id, info.start_date) == ("replay", REPLAY_RUN, REPLAY_DATE)
    assert live.run_start.live_start == 1440
    out = capsys.readouterr().out
    assert f"Replay · run_id {REPLAY_RUN} · velocidad máxima · en memoria" in out
    assert "2 días desde 2026-03-09 (la fecha del primer evento)" in out


def test_reemitir_con_otro_calentamiento(saved, sinks):
    argv = ["directo", "reemitir", REPLAY_RUN, "--ejecuciones", str(saved)]

    assert main([*argv, "--calentamiento", "0", "--memoria", "--velocidad", "max"]) == 0

    [live] = sinks
    assert live.run_start.census_events == 0
    assert [to_json(e) for e in live.events] == replay_lines(saved, 0)
    assert len(live.events) == len((saved / REPLAY_RUN / "eventos.jsonl").read_text().splitlines())


STATUS = re.compile(
    r"\+(?P<elapsed>\d+) s · (?P<event_time>\S+) \(minuto (?P<minute>[\d.]+)\) · ×60"
    r" · (?P<published>\d+) publicados · retraso (?P<lag>[\d.]+) ms"
)


def test_ctrl_c_en_memoria(sinks, monkeypatch, capsys):
    # A ×60 con el reloj falso, Ctrl+C a los 30 s: salen las líneas de estado de los 10 y
    # 20 s, el fin con motivo interrupcion y el código 130.
    use_clock(monkeypatch, FakeClock(interrupt_at=30))
    expected = batch_of("rctrlc")

    code = main([*LAUNCH, "--memoria", "--velocidad", "60", "--run-id", "rctrlc"])

    assert code == 130
    [live] = sinks
    end = live.items[-1]
    assert isinstance(end, RunEnd)
    assert (end.reason, end.sim_time) == ("interrupcion", 1470.0)
    census = live.run_start.census_events
    out = capsys.readouterr()
    lines = [STATUS.fullmatch(line) for line in out.out.splitlines() if line.startswith("+")]
    assert [m["elapsed"] for m in lines] == ["10", "20"]
    for match, s in zip(lines, (10, 20), strict=True):
        # El pacer duerme tramos de 0,2 s desde el último evento, no desde el 0: la línea
        # sale en el primer poll a partir de los s segundos, como mucho 0,2 s después.
        minute = float(match["minute"])
        assert 1440 + s <= minute <= 1440 + s + 0.2
        assert match["event_time"].startswith("2026-01-06T00:")
        published = int(match["published"])
        assert census + sum(1440 <= e.sim_time < 1440 + s for e in expected) <= published
        assert published <= census + sum(1440 <= e.sim_time <= 1440 + s + 0.2 for e in expected)
        assert match["lag"] == "0.0"
    assert out.out.splitlines()[-1].startswith("Fin · motivo interrupcion ·")
    assert "Ctrl+C" in out.err


# --- Sin el extra kafka --------------------------------------------------------------


@pytest.fixture
def sin_extra(monkeypatch):
    def missing():
        raise MissingKafkaExtraError(MISSING_EXTRA_MESSAGE)

    monkeypatch.setattr("edsim.live.kafka.import_confluent_kafka", missing)


@pytest.mark.parametrize(
    "argv",
    [
        ["directo", "preparar"],
        [*LAUNCH, "--velocidad", "max"],
        ["directo", "reemitir", REPLAY_RUN, "{root}", "--velocidad", "max"],
        ["directo", "control", "--run", "r1", "--parar"],
    ],
    ids=["preparar", "lanzar", "reemitir", "control"],
)
def test_sin_el_extra_sale_con_1_y_dice_como_instalarlo(argv, saved, sin_extra, capsys):
    argv = [
        part for a in argv for part in (["--ejecuciones", str(saved)] if a == "{root}" else [a])
    ]

    assert main(argv) == 1
    assert MISSING_EXTRA_MESSAGE in capsys.readouterr().err


def test_sin_el_extra_lanzar_en_memoria_funciona(sin_extra, sinks):
    assert main([*LAUNCH, "--memoria", "--velocidad", "max", "--run-id", "rsinextra"]) == 0
    assert sinks[0].run_end.reason == "horizonte"


# --- Con Kafka falso -----------------------------------------------------------------


class KafkaFake:
    """Los dobles de Kafka de una ejecución de la CLI, con un registro común en el orden en
    que ocurre cada cosa: ("control",) al crear las órdenes, y los ("produce", topic) y
    ("flush",) del productor falso."""

    def __init__(self, monkeypatch, producer=None, *, missing=(), mismatch=False):
        # FakeProducer tiene __len__: uno vacío es falso, así que no vale «producer or …».
        self.producer = producer if producer is not None else FakeProducer()
        self.ops = self.producer.ops
        self.missing = list(missing)
        self.mismatch = mismatch
        self.ensure_calls = []
        self.controls = []
        self.connects = []
        self.invalid = None
        monkeypatch.setattr("edsim.cli.ensure_topics", self.ensure_topics)
        monkeypatch.setattr("edsim.cli.KafkaControl", self.control)
        monkeypatch.setattr("edsim.cli.connect_producer", self.connect)

    def ensure_topics(
        self, bootstrap, topics, *, create=True, connect_timeout=None, client_config=None
    ):
        self.ensure_calls.append((bootstrap, create, connect_timeout))
        names = [t.name for t in topics]
        if self.mismatch:
            raise TopicMismatchError("topics that differ: ed.runs: 2 partitions, expected 1")
        if self.missing and not create:
            raise MissingTopicsError(
                f"topics missing: {', '.join(self.missing)}; "
                "create them with `edsim directo preparar`"
            )
        # Honesto: con create=True «crea» los que faltan.
        existing = tuple(n for n in names if n not in self.missing)
        return TopicsReport(created=tuple(self.missing), existing=existing)

    def control(self, bootstrap, run_id, on_invalid, *, watch=None):
        if watch is not None and isinstance(self.producer, CutProducer):
            self.producer.clients["órdenes"] = watch.config("órdenes")
        fake = FakeControl(on_invalid, self.invalid)
        self.ops.append(("control",))
        self.controls.append(fake)
        return fake

    def connect(self, bootstrap, client, *, watch=None):
        self.connects.append((bootstrap, client))
        if watch is not None and isinstance(self.producer, CutProducer):
            self.producer.clients["productor"] = watch.config("productor")
        return self.producer

    def runs_messages(self):
        return [
            json.loads(kwargs["value"]) for topic, kwargs in self.producer.calls if topic == RUNS
        ]


class CutProducer(FakeProducer):
    """Un productor falso que simula cortes de Kafka con los callbacks del vigilante.

    En cada poll hace lo que haría librdkafka con los dos clientes (el productor y el
    consumidor de órdenes): en el primero, estadísticas con el broker UP; en el poll
    ``start`` de cada corte, estadísticas sin UP, y hasta el ``end``, un error _TRANSPORT
    y una línea FAIL por cliente; en el ``end``, UP otra vez.
    """

    def __init__(self, cuts, **kwargs):
        super().__init__(**kwargs)
        self.cuts = cuts
        self.clients: dict[str, dict] = {}

    def poll(self, timeout=None):
        n = len(self.polls)
        for config in self.clients.values():
            if n == 0:
                config["stats_cb"](stats_json(True))
            for start, end in self.cuts:
                if n == start:
                    config["stats_cb"](stats_json(False))
                if start <= n < end:
                    config["error_cb"](FakeKafkaError("_TRANSPORT", REFUSED))
                    log_line(config, "FAIL", REFUSED)
                if n == end:
                    config["stats_cb"](stats_json(True))
        return super().poll(timeout)


class FakeControl:
    """Un KafkaControl falso: sin órdenes; con ``invalid``, avisa una vez en el primer poll."""

    def __init__(self, on_invalid, invalid=None):
        self.on_invalid = on_invalid
        self.invalid = invalid
        self.closed = False

    def poll(self):
        if self.invalid is not None:
            self.on_invalid(self.invalid)
            self.invalid = None
        return None

    def close(self):
        self.closed = True


KAFKA_LAUNCH = [*LAUNCH, "--velocidad", "max", "--run-id", "rkafka"]


def test_lanzar_comprueba_los_topics_sin_crearlos(monkeypatch):
    kafka = KafkaFake(monkeypatch)

    assert main(KAFKA_LAUNCH) == 0
    assert kafka.ensure_calls == [("localhost:9092", False, 10.0)]
    assert kafka.connects == [("localhost:9092", "rkafka")]


def test_lanzar_crea_las_ordenes_antes_del_calentamiento(monkeypatch):
    kafka = KafkaFake(monkeypatch)

    assert main(KAFKA_LAUNCH) == 0
    # El inicio va en ed.runs tras el calentamiento: las órdenes ya se escuchaban.
    first_runs = kafka.ops.index(("produce", RUNS))
    assert kafka.ops.index(("control",)) < first_runs
    assert kafka.runs_messages()[0]["tipo"] == "inicio"


def test_lanzar_vacia_el_productor_al_salir(monkeypatch):
    kafka = KafkaFake(monkeypatch)

    assert main(KAFKA_LAUNCH) == 0
    # end hace flush antes del fin; el gestor de contexto, otro después.
    assert kafka.ops[-2:] == [("produce", RUNS), ("flush",)]
    assert kafka.runs_messages()[-1]["motivo"] == "horizonte"
    assert kafka.controls[0].closed


def test_lanzar_imprime_las_ordenes_invalidas(monkeypatch, capsys):
    kafka = KafkaFake(monkeypatch)
    kafka.invalid = "invalid message in ed.control: not JSON"

    assert main(KAFKA_LAUNCH) == 0
    assert "Aviso: invalid message in ed.control: not JSON" in capsys.readouterr().err


def test_lanzar_sin_topics_sale_con_1_y_dice_preparar(monkeypatch, capsys):
    kafka = KafkaFake(monkeypatch, missing=[CONTROL])

    assert main(KAFKA_LAUNCH) == 1
    assert "edsim directo preparar" in capsys.readouterr().err
    assert kafka.controls == [] and kafka.connects == []


def test_lanzar_con_un_topic_distinto_sale_con_1(monkeypatch, capsys):
    kafka = KafkaFake(monkeypatch, mismatch=True)

    assert main(KAFKA_LAUNCH) == 1
    assert "2 partitions, expected 1" in capsys.readouterr().err
    assert kafka.connects == []


def test_lanzar_con_un_mensaje_no_entregado_sale_con_1(monkeypatch, capsys):
    # El décimo mensaje (el inicio y nueve eventos) llega con error: el directo se para y el
    # fin dice error.
    kafka = KafkaFake(monkeypatch, FakeProducer(delivery_errors={10}))

    assert main(KAFKA_LAUNCH) == 1
    end = kafka.runs_messages()[-1]
    assert (end["tipo"], end["motivo"], end["publicados"]) == ("fin", "error", 8)
    assert "un mensaje no se entregó" in capsys.readouterr().err


def test_preparar_dice_que_crea_y_que_ya_estaba(monkeypatch, capsys):
    kafka = KafkaFake(monkeypatch, missing=[CONTROL])

    assert main(["directo", "preparar"]) == 0
    assert kafka.ensure_calls == [("localhost:9092", True, 10.0)]
    others = ", ".join(t.name for t in TOPICS if t.name != CONTROL)
    assert capsys.readouterr().out.splitlines() == [
        "Kafka localhost:9092",
        "Creados: ed.control",
        f"Ya estaban: {others}",
    ]


def test_preparar_con_un_topic_distinto_sale_con_1(monkeypatch, capsys):
    KafkaFake(monkeypatch, mismatch=True)

    assert main(["directo", "preparar"]) == 1
    assert "no son los de EDsim" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["directo", "preparar"],
        [*LAUNCH, "--velocidad", "max"],
        ["directo", "reemitir", REPLAY_RUN, "{root}", "--velocidad", "max"],
        ["directo", "control", "--run", "r1", "--parar"],
    ],
    ids=["preparar", "lanzar", "reemitir", "control"],
)
def test_sin_broker_el_mismo_mensaje(argv, saved, monkeypatch, capsys):
    install_fake_confluent_kafka(monkeypatch)
    kafka = KafkaFake(monkeypatch, FakeProducer(unreachable=True))

    def down(*args, **kwargs):
        raise BrokerUnavailableError("localhost:9092", 10.0)

    kafka.ensure_topics = down
    monkeypatch.setattr("edsim.cli.ensure_topics", down)
    argv = [
        part for a in argv for part in (["--ejecuciones", str(saved)] if a == "{root}" else [a])
    ]

    assert main(argv) == 1
    assert capsys.readouterr().err.strip() == (
        "Error: no responde el broker de Kafka en localhost:9092 en 10 s:"
        " ¿está levantado? docker compose up --wait"
    )


# --- control -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("option", "command", "text"),
    [
        (["--velocidad", "600"], Command(SPEED, 600), "velocidad ×600"),
        (["--pausar"], Command(PAUSE), "pausar"),
        (["--reanudar"], Command(RESUME), "reanudar"),
        (["--parar"], Command(STOP), "parar"),
    ],
    ids=["velocidad", "pausar", "reanudar", "parar"],
)
def test_control_publica_la_orden(option, command, text, monkeypatch, capsys):
    install_fake_confluent_kafka(monkeypatch)
    kafka = KafkaFake(monkeypatch)

    assert main(["directo", "control", "--run", "r2026_x", *option]) == 0
    [(topic, kwargs)] = kafka.producer.calls
    assert (topic, kwargs["key"]) == (CONTROL, b"r2026_x")
    assert kwargs["value"] == control_json("r2026_x", command).encode()
    assert kafka.connects == [("localhost:9092", "orden-r2026_x")]
    assert capsys.readouterr().out.strip() == (
        f"Orden {text} para r2026_x publicada en ed.control (offset 0)"
    )


def test_control_no_entregada_sale_con_1(monkeypatch, capsys):
    install_fake_confluent_kafka(monkeypatch)
    KafkaFake(monkeypatch, FakeProducer(delivery_errors={1}))

    assert main(["directo", "control", "--run", "r1", "--parar"]) == 1
    assert "Message timed out" in capsys.readouterr().err


# --- Cortes de Kafka: los avisos y el resumen de librdkafka (tarea 6.6) ----------------

LOST_WARNING = (
    f"Aviso: se perdió la conexión con Kafka en localhost:9092 ({REFUSED}); librdkafka"
    " reintenta solo y los eventos esperan en la cola del productor"
)


def kafka_warnings(err: str) -> list[str]:
    return [line for line in err.splitlines() if line.startswith("Aviso:") and "Kafka" in line]


def test_lanzar_con_un_corte_avisa_dos_veces(monkeypatch, capsys):
    # A ×60 con el reloj falso, un corte del poll 100 al 200 del productor: 100 errores y
    # 100 líneas de cada cliente, dos avisos en total y las líneas de estado en la salida.
    use_clock(monkeypatch, FakeClock())
    kafka = KafkaFake(monkeypatch, CutProducer(cuts=[(100, 200)]))

    assert main([*LAUNCH, "--velocidad", "60", "--run-id", "rcorte"]) == 0

    out = capsys.readouterr()
    warnings = kafka_warnings(out.err)
    assert len(warnings) == 2
    assert warnings[0] == LOST_WARNING
    assert re.fullmatch(
        r"Aviso: Kafka en localhost:9092 vuelve a responder tras \d+ s", warnings[1]
    )
    assert len([line for line in out.out.splitlines() if line.startswith("+")]) >= 100
    assert REFUSED not in out.out
    assert out.err.count(REFUSED) == 1 + 2  # el aviso y la primera línea de cada cliente
    assert "librdkafka: 200 líneas (órdenes 100, productor 100); 200 errores (_TRANSPORT 200)" in (
        out.err
    )
    assert kafka.runs_messages()[-1]["motivo"] == "horizonte"


def test_lanzar_con_un_corte_y_una_entrega_fallida_sale_con_1(monkeypatch, capsys):
    # El corte no tapa el error: el mensaje 150 no se entrega, el directo se para con fin
    # error y el resumen de librdkafka sale igualmente, tras el error.
    kafka = KafkaFake(monkeypatch, CutProducer(cuts=[(100, 400)], delivery_errors={150}))

    assert main(KAFKA_LAUNCH) == 1

    err = capsys.readouterr().err
    end = kafka.runs_messages()[-1]
    assert (end["tipo"], end["motivo"]) == ("fin", "error")
    assert "Error: un mensaje no se entregó y el directo se paró" in err
    assert err.index("Error: un mensaje no se entregó") < err.index("librdkafka: ")
    assert kafka_warnings(err) == [LOST_WARNING]


def test_control_guarda_las_lineas_de_librdkafka(monkeypatch, tmp_path, capsys):
    install_fake_confluent_kafka(monkeypatch)
    producer = CutProducer(cuts=[(0, 1)])
    kafka = KafkaFake(monkeypatch, producer)
    path = tmp_path / "control.log"

    code = main(["directo", "control", "--run", "r1", "--parar", "--registro-kafka", str(path)])

    assert code == 0
    assert kafka.connects == [("localhost:9092", "orden-r1")]
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and lines[0].endswith(f"productor FAIL [edsim-x#producer-1] {REFUSED}")
    assert f"todas en {path}" in capsys.readouterr().err


def test_preparar_sin_broker_resume_lo_que_escribio_librdkafka(monkeypatch, capsys):
    def down(bootstrap, topics, *, connect_timeout, client_config):
        for _ in range(3):
            log_line(client_config, "FAIL", REFUSED)
        raise BrokerUnavailableError(bootstrap, connect_timeout)

    monkeypatch.setattr("edsim.cli.ensure_topics", down)

    assert main(["directo", "preparar"]) == 1
    err = capsys.readouterr().err.splitlines()
    assert err[0].startswith("Error: no responde el broker de Kafka en localhost:9092")
    assert err[1] == (
        "librdkafka: 3 líneas (administración 3); para guardarlas, --registro-kafka FICHERO"
    )


def test_registro_kafka_con_memoria_es_un_error_de_uso(sin_conexion, capsys):
    with pytest.raises(SystemExit) as exit_:
        main([*LAUNCH, "--memoria", "--registro-kafka", "x.log"])
    assert exit_.value.code == 2
    assert "--registro-kafka" in capsys.readouterr().err
