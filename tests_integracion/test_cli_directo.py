"""La CLI `edsim directo` contra un Kafka real (tarea 6.5).

preparar y «lanzar sin topics» usan topics con nombres únicos (`edsim.cli.TOPICS` cambiado
con monkeypatch), para no tocar los cuatro reales: el borrado de un topic en Kafka es
asíncrono y puede haber un directo en marcha. El extremo a extremo y el Ctrl+C lanzan el
directo en un subproceso (el script `edsim` del entorno) y le mandan órdenes desde otros
procesos con `edsim directo control`, como Pedro desde otra terminal. Cada test usa un
run_id único y lee desde los offsets altos anotados antes de lanzar.

Límites fijados antes de medir: TIMEOUT (30 s) en cada espera, 0,5 s de margen para que
una pausa se aplique, 2 s de silencio en pausa y 1.000 ms entre la orden parar y el fin.
"""

import json
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from confluent_kafka import Consumer, KafkaError, TopicPartition
from kafka_testing import TIMEOUT, deadline
from test_kafka_edsim import filtered_batch, number, read_range, unique, watermarks

from edsim.arrivals.profile import load_profile
from edsim.cli import main
from edsim.engine.center import load_center
from edsim.engine.engine import simulate_ed
from edsim.engine.events import MemorySink, read_events, to_json
from edsim.live.topics import CONTROL, PATIENT_EVENTS, RESOURCE_EVENTS, RUNS, TOPICS, Topic
from edsim.profiles.config import load_profiles

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data"
EDSIM = str(Path(sys.executable).with_name("edsim"))
MODEL = [
    "--centro",
    str(DATA / "centro_sala_ejemplo.toml"),
    "--llegadas",
    str(DATA / "llegadas_ejemplo.toml"),
    "--perfiles",
    str(DATA / "perfiles_ejemplo.toml"),
]
LAUNCH = ["directo", "lanzar", *MODEL, "--dias", "2", "--calentamiento", "1"]
"""Un directo de tests/data con sala: 2 días, W = 1 día, semilla 2026."""

PAUSE_SETTLE = 0.5
PAUSE_SILENCE = 2.0
STOP_TO_END_MS = 1000


def expected_of(run_id: str) -> list:
    """El batch filtrado del directo de LAUNCH con ese run_id."""
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


def new_consumer(bootstrap: str) -> Consumer:
    return Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": unique("test-cli"),
            "enable.auto.commit": False,
        }
    )


def delete_topics(admin, names: list[str]) -> None:
    """Borra los topics que existan de `names`."""
    for future in admin.delete_topics(names, request_timeout=TIMEOUT).values():
        try:
            future.result(timeout=TIMEOUT)
        except Exception as exc:  # un topic que no llegó a crearse no se borra
            if exc.args[0].code() != KafkaError.UNKNOWN_TOPIC_OR_PART:
                raise


def prefixed_topics(name: str) -> tuple[Topic, ...]:
    prefix = f"test.{unique(name)}"
    return tuple(Topic(f"{prefix}.{t.name}", t.partitions, t.key, t.config) for t in TOPICS)


def of_run(messages: list, run_id: str) -> tuple[list, list, list]:
    """Los eventos, los mensajes de ed.runs y las órdenes de ese run_id."""
    key = run_id.encode()
    events = [m for m in messages if m.topic() in (PATIENT_EVENTS, RESOURCE_EVENTS)
              and json.loads(m.value())["run_id"] == run_id]  # fmt: skip
    runs = [m for m in messages if m.topic() == RUNS and m.key() == key]
    orders = [m for m in messages if m.topic() == CONTROL and m.key() == key]
    return events, runs, orders


def assert_prefix(events: list, expected: list) -> None:
    """Lo leído, por número de event_id, es un prefijo del batch filtrado, sin huecos ni
    repetidos, byte a byte."""
    by_number = sorted(events, key=lambda m: number(json.loads(m.value())["event_id"]))
    ids = [json.loads(m.value())["event_id"] for m in by_number]
    assert len(set(ids)) == len(ids)
    assert [m.value() for m in by_number] == [
        to_json(e).encode("utf-8") for e in expected[: len(by_number)]
    ]


# --- preparar ------------------------------------------------------------------------


def test_preparar_con_la_cli_crea_y_despues_no_repite(bootstrap, admin, monkeypatch, capsys):
    topics = prefixed_topics("preparar")
    names = [t.name for t in topics]
    monkeypatch.setattr("edsim.cli.TOPICS", topics)
    try:
        first = main(["directo", "preparar", "--kafka", bootstrap])
        first_out = capsys.readouterr().out.splitlines()
        second = main(["directo", "preparar", "--kafka", bootstrap])
        second_out = capsys.readouterr().out.splitlines()
    finally:
        delete_topics(admin, names)

    assert (first, second) == (0, 0)
    assert first_out[1:] == [f"Creados: {', '.join(names)}", "Ya estaban: ninguno"]
    assert second_out[1:] == ["Creados: ninguno", f"Ya estaban: {', '.join(names)}"]


def test_lanzar_sin_los_topics_no_los_crea(bootstrap, admin, monkeypatch, capsys):
    topics = prefixed_topics("sin-topics")
    names = [t.name for t in topics]
    monkeypatch.setattr("edsim.cli.TOPICS", topics)
    try:
        code = main([*LAUNCH, "--velocidad", "max", "--run-id", unique("test"),
                     "--kafka", bootstrap])  # fmt: skip
        listed = admin.list_topics(timeout=TIMEOUT).topics
    finally:
        delete_topics(admin, names)

    assert code == 1
    assert "edsim directo preparar" in capsys.readouterr().err
    assert not any(name in listed for name in names)


# --- Extremo a extremo y Ctrl+C ------------------------------------------------------


class Watcher:
    """Lee los cuatro topics desde unos offsets y guarda lo de un run_id mientras corre."""

    def __init__(self, bootstrap: str, run_id: str) -> None:
        self.consumer = new_consumer(bootstrap)
        self.before = watermarks(self.consumer)
        self.consumer.assign(
            [TopicPartition(t, p, offset) for (t, p), offset in self.before.items()]
        )
        self.run_id = run_id
        self.events: list = []
        self.runs: list = []

    def pump(self, seconds: float) -> None:
        """Lee durante `seconds` segundos."""
        limit = time.monotonic() + seconds
        while (left := limit - time.monotonic()) > 0:
            message = self.consumer.poll(min(left, 0.1))
            if message is None or message.error():
                continue
            events, runs, _ = of_run([message], self.run_id)
            self.events += events
            self.runs += runs

    def wait_for(self, what: str, condition, timeout: float = TIMEOUT) -> None:
        limit = deadline(timeout)
        while not condition():
            if time.monotonic() > limit:
                pytest.fail(f"No llegó {what} en {timeout:g} s")
            self.pump(0.1)

    def run_message(self, kind: str):
        found = [m for m in self.runs if json.loads(m.value())["tipo"] == kind]
        return found[0] if found else None

    def close(self) -> None:
        self.consumer.close()


def launch(bootstrap: str, run_id: str) -> subprocess.Popen:
    return subprocess.Popen(
        [EDSIM, *LAUNCH, "--velocidad", "60", "--run-id", run_id, "--kafka", bootstrap],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def order(bootstrap: str, run_id: str, *option: str) -> None:
    """`edsim directo control` en otro proceso; espera la confirmación."""
    result = subprocess.run(
        [EDSIM, "directo", "control", "--run", run_id, *option, "--kafka", bootstrap],
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    assert result.returncode == 0, result.stderr


def finish(process: subprocess.Popen) -> tuple[int, str, str]:
    """El código, la salida y los errores del directo, con un límite de TIMEOUT."""
    try:
        out, err = process.communicate(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()
        out, err = process.communicate()
        pytest.fail(f"El directo no terminó en {TIMEOUT:g} s:\n{out}\n{err}")
    return process.returncode, out, err


def test_extremo_a_extremo_con_ordenes(bootstrap, edsim_topics):
    run_id = unique("test")
    expected = expected_of(run_id)
    watcher = Watcher(bootstrap, run_id)
    process = launch(bootstrap, run_id)
    try:
        watcher.wait_for("el inicio", lambda: watcher.run_message("inicio") is not None)
        order(bootstrap, run_id, "--velocidad", "600")
        at_600 = len(watcher.events)
        watcher.pump(1.5)
        fast = len(watcher.events) - at_600

        order(bootstrap, run_id, "--pausar")
        watcher.pump(PAUSE_SETTLE)
        paused = len(watcher.events)
        watcher.pump(PAUSE_SILENCE)
        during_pause = len(watcher.events) - paused
        end_in_pause = watcher.run_message("fin")

        order(bootstrap, run_id, "--reanudar")
        watcher.wait_for("un evento tras reanudar", lambda: len(watcher.events) > paused, 5)

        order(bootstrap, run_id, "--parar")
        watcher.wait_for("el fin", lambda: watcher.run_message("fin") is not None)
        code, out, err = finish(process)
        after = watermarks(watcher.consumer)
    finally:
        if process.poll() is None:
            process.kill()
        watcher.close()

    assert (code, fast > 0, during_pause, end_in_pause) == (0, True, 0, None), err

    consumer = new_consumer(bootstrap)
    try:
        events, runs, orders = of_run(read_range(consumer, watcher.before, after), run_id)
    finally:
        consumer.close()
    start, end = (json.loads(m.value()) for m in runs)
    assert (start["tipo"], start["velocidad"], end["tipo"], end["motivo"]) == (
        "inicio",
        60.0,
        "fin",
        "parar",
    )
    assert [json.loads(m.value())["orden"] for m in orders] == [
        "velocidad",
        "pausar",
        "reanudar",
        "parar",
    ]
    # El fin llega menos de 1 s después de que el broker guardara la orden parar.
    stop_ms, end_ms = orders[-1].timestamp()[1], runs[-1].timestamp()[1]
    assert 0 <= end_ms - stop_ms < STOP_TO_END_MS
    assert end["publicados"] == len(events)
    assert len(events) < len(expected)  # se paró antes del horizonte
    assert_prefix(events, expected)
    assert "Fin · motivo parar" in out


def test_ctrl_c_publica_el_fin(bootstrap, edsim_topics):
    run_id = unique("test")
    expected = expected_of(run_id)
    watcher = Watcher(bootstrap, run_id)
    process = launch(bootstrap, run_id)
    try:
        watcher.wait_for("el inicio", lambda: watcher.run_message("inicio") is not None)
        census = json.loads(watcher.run_message("inicio").value())["censo"]["eventos"]
        watcher.wait_for("un evento del directo", lambda: len(watcher.events) > census)
        process.send_signal(signal.SIGINT)
        code, out, err = finish(process)
        after = watermarks(watcher.consumer)
    finally:
        if process.poll() is None:
            process.kill()
        watcher.close()

    assert code == 130, err
    consumer = new_consumer(bootstrap)
    try:
        events, runs, _ = of_run(read_range(consumer, watcher.before, after), run_id)
    finally:
        consumer.close()
    end = json.loads(runs[-1].value())
    assert (end["tipo"], end["motivo"]) == ("fin", "interrupcion")
    assert end["publicados"] == len(events) > census
    assert_prefix(events, expected)
    assert "Fin · motivo interrupcion" in out


# --- reemitir ------------------------------------------------------------------------


def save_run(root: Path, run_id: str) -> Path:
    """Guarda una ejecución con motor simular (tests/data, 2 días, calentamiento 1)."""
    argv = ["motor", "simular", *MODEL, "--dias", "2", "--calentamiento", "1"]
    assert main([*argv, "--run-id", run_id, "--salida", str(root / run_id)]) == 0
    return root / run_id / "eventos.jsonl"


def test_reemitir_publica_los_mismos_bytes(bootstrap, edsim_topics, tmp_path):
    run_id = unique("test")
    path = save_run(tmp_path, run_id)
    keep = {e.event_id for e in filtered_batch(list(read_events(path)), 1440)}
    lines = [
        line.encode("utf-8")
        for line in path.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["event_id"] in keep
    ]

    consumer = new_consumer(bootstrap)
    try:
        before = watermarks(consumer)
        code = main(["directo", "reemitir", run_id, "--ejecuciones", str(tmp_path),
                     "--velocidad", "max", "--kafka", bootstrap])  # fmt: skip
        events, runs, _ = of_run(read_range(consumer, before, watermarks(consumer)), run_id)
    finally:
        consumer.close()

    assert code == 0
    by_number = sorted(events, key=lambda m: number(json.loads(m.value())["event_id"]))
    assert [m.value() for m in by_number] == lines
    start, end = (json.loads(m.value()) for m in runs)
    assert (start["modo"], start["inicio_directo"]) == ("replay", 1440.0)
    assert (end["motivo"], end["publicados"]) == ("horizonte", len(lines))


# --- Sin broker ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["directo", "preparar"],
        [*LAUNCH, "--velocidad", "max", "--run-id", "rsinbroker"],
        ["directo", "reemitir", "rsinbroker", "{root}", "--velocidad", "max"],
        ["directo", "control", "--run", "rsinbroker", "--parar"],
    ],
    ids=["preparar", "lanzar", "reemitir", "control"],
)
def test_sin_broker_avisa_sin_traza(argv, tmp_path, monkeypatch, capsys):
    if "{root}" in argv:
        save_run(tmp_path, "rsinbroker")
        capsys.readouterr()
        root = ["--ejecuciones", str(tmp_path)]
        argv = [part for a in argv for part in (root if a == "{root}" else [a])]
    monkeypatch.setattr("edsim.cli.CONNECT_TIMEOUT", 1.0)

    started = time.monotonic()
    code = main([*argv, "--kafka", "localhost:1"])
    seconds = time.monotonic() - started

    captured = capsys.readouterr()
    assert code == 1
    assert "no responde el broker de Kafka en localhost:1 en 1 s" in captured.err
    assert "¿está levantado? docker compose up --wait" in captured.err
    assert "Traceback" not in captured.out + captured.err
    assert seconds < 10  # el tiempo corto, no los 30 s
