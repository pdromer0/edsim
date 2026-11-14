"""`edsim registro comparar --postgres` contra un Postgres real (tarea 7.3, H7-10).

Cada test dice qué pilla que no pille un rápido: el SQL de `READ_LINES` (la última publicación de
una ejecución, con `DISTINCT ON`, `COALESCE` y el orden de emisión) solo se ejecuta aquí, y el
criterio del hito («`registro comparar` da la misma conciliación con ficheros que con
`--postgres`») también.

No hace falta Kafka: lo que hace el consumidor se imita metiendo en bronce, con `to_row` y
`save_batch` (los de `edsim almacen consumir`), los mensajes que publicaría `directo --registro`
(la 7.4): un `inicio`, un registro por línea de `registrado.jsonl` y un `fin`, cada uno con su
marca `LogAppendTime`. Las ejecuciones son de 2 días con los ejemplos del hito 5, registradas con
`config/registro_clinico.toml` (perfil realista), y cada test usa un `run_id` único.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from test_kafka_edsim import unique

from edsim.cli import main
from edsim.live.topics import PATIENT_EVENTS, RESOURCE_EVENTS, RUNS
from edsim.runs import (
    RunStore,
    read_recorded_records,
    read_recorded_run,
    record_run,
    simulate_run,
)
from edsim.store.bronze import LOG_APPEND_TIME, KafkaMessage, to_row
from edsim.store.consumer import save_batch
from edsim.store.postgres import (
    PostgresBronze,
    connect,
    read_bronze_lines,
    read_bronze_records,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data"
PROFILES_FILE = ROOT / "config" / "registro_clinico.toml"
FIRST = 1_767_225_600_000  # 2026-01-01T00:00:00Z en ms: la primera publicación
SECOND = FIRST + 3_600_000  # una hora más tarde: la segunda


@dataclass(frozen=True)
class Recorded:
    """Una ejecución con sus registros de la semilla 7, 8 y 9 (perfil realista)."""

    store: RunStore
    run_id: str

    def derived(self, seed: int) -> str:
        return f"{self.run_id}_realista_s{seed}"

    def lines(self, seed: int) -> list[str]:
        path = (
            self.store.root / self.run_id / "registros" / f"realista-s{seed}" / "registrado.jsonl"
        )
        return [line for line in path.read_text(encoding="utf-8").split("\n") if line]

    def compare_cli(self, seed: int, capsys, *extra: str) -> tuple[int, str, str]:
        argv = ["registro", "comparar", self.run_id, "--perfil", "realista", "--semilla", str(seed)]
        code = main([*argv, "--ejecuciones", str(self.store.root), *extra])
        captured = capsys.readouterr()
        return code, captured.out, captured.err


@pytest.fixture(scope="module")
def recorded(tmp_path_factory) -> Recorded:
    """Una ejecución de 2 días con tres registros realistas de la misma verdad: la semilla 7 la
    usa el test de la última publicación, la 8 el de la publicación cortada y la 9 nunca se
    publica."""
    root = tmp_path_factory.mktemp("comparar-integracion")
    run_id = unique("cmp")
    simulate_run(
        DATA / "centro_h5_ejemplo.toml",
        DATA / "llegadas_ejemplo.toml",
        2,
        7,
        output_dir=root / run_id,
        run_id=run_id,
        warmup_days=1,
        origin="cli",
        profiles=DATA / "perfiles_h5_ejemplo.toml",
    )
    store = RunStore(root)
    for seed in (7, 8, 9):
        record_run(store, run_id, "realista", seed, profiles_file=PROFILES_FILE)
    return Recorded(store, run_id)


def publish(connection, derived: str, lines: list[str], started_ms: int, *, complete=True) -> None:
    """Mete en bronce una publicación de `derived`: `inicio`, las líneas y, si está completa, `fin`.

    Cada mensaje lleva la marca `started_ms` más su posición, como `LogAppendTime`: el `inicio`
    llega antes que los registros, y el `fin` después.
    """
    start = json.dumps({"tipo": "inicio", "run_id": derived}).encode()
    messages = [KafkaMessage(RUNS, 0, started_ms, LOG_APPEND_TIME, started_ms, start)]
    for position, line in enumerate(lines, start=1):
        topic = RESOURCE_EVENTS if json.loads(line)["episode_id"] is None else PATIENT_EVENTS
        stamp = started_ms + position
        messages.append(KafkaMessage(topic, 0, stamp, LOG_APPEND_TIME, stamp, line.encode()))
    if complete:
        end = started_ms + len(lines) + 1
        fin = json.dumps({"tipo": "fin", "run_id": derived, "publicados": len(lines)}).encode()
        messages.append(KafkaMessage(RUNS, 0, end, LOG_APPEND_TIME, end, fin))
    batch = [(message, to_row(message)) for message in messages]
    for start_at in range(0, len(batch), 500):
        save_batch(PostgresBronze(connection), batch[start_at : start_at + 500])


def without_origin(text: str) -> list[str]:
    """El informe sin la línea que dice de dónde sale lo registrado, la única que cambia."""
    return [line for line in text.split("\n") if "lo registrado sale de" not in line]


def test_la_misma_conciliacion_con_ficheros_que_con_postgres_leyendo_la_ultima_publicacion(
    recorded, bronze_url, capsys
):
    """La ejecución se publicó dos veces: la primera, cortada y con otro mes en cada hora; la
    segunda, completa. `comparar --postgres` da lo mismo que con ficheros (el criterio del
    hito), y los registros leídos son los de `registrado.jsonl`, uno a uno y en su orden. Pilla
    un SQL que lee la primera publicación (V31: la cuenta no cuadraría), uno que mezcla las dos
    y uno que no ordena por emisión."""
    lines = recorded.lines(7)
    derived = recorded.derived(7)
    # La primera publicación: sin las diez últimas y, en las demás, con otro mes (un contenido
    # distinto y válido para los mismos event_id; con una hora ilegible, bronce la rechazaría).
    old = [line.replace("2026-01-0", "2026-02-0") for line in lines[:-10]]
    assert old != lines[:-10]
    with connect(bronze_url) as connection:
        publish(connection, derived, old, FIRST)
        publish(connection, derived, lines, SECOND)
    assert len(lines) > 1000  # no es un test vacío: hay una ejecución de verdad

    run = read_recorded_run(recorded.store, recorded.run_id, "realista", 7)
    from_files = read_recorded_records(run)
    from_bronze = read_bronze_records(bronze_url, derived)

    assert read_bronze_lines(bronze_url, derived) == lines
    assert from_bronze == list(from_files)
    assert run.compare(from_bronze) == run.compare(from_files)
    code, files, err = recorded.compare_cli(7, capsys)
    assert code == 0, err
    code, postgres, err = recorded.compare_cli(7, capsys, "--postgres", bronze_url)
    assert code == 0, err
    assert "lo registrado sale de ficheros" in files
    assert "lo registrado sale de Postgres" in postgres
    assert without_origin(files) == without_origin(postgres)


def test_una_publicacion_cortada_es_un_error_no_la_publicacion_anterior(
    recorded, bronze_url, capsys
):
    """La ejecución se publicó entera y después se republicó a medias: bronce tiene la completa y
    la parcial. `comparar --postgres` lee la última y, como falta lo que no llegó, la cuenta no
    cuadra y dice que falta consumir; no «arregla» el hueco con la publicación anterior."""
    lines = recorded.lines(8)
    derived = recorded.derived(8)
    with connect(bronze_url) as connection:
        publish(connection, derived, lines, FIRST)
        publish(connection, derived, lines[: len(lines) // 2], SECOND, complete=False)

    code, out, err = recorded.compare_cli(8, capsys, "--postgres", bronze_url)

    assert code == 1
    assert out == ""
    assert "la cuenta no cuadra" in err
    assert f"edsim almacen consumir --run {derived}" in err
    assert len(read_bronze_lines(bronze_url, derived)) == len(lines) // 2


def test_una_ejecucion_que_bronce_no_tiene_es_un_error_no_un_informe_de_ceros(
    recorded, bronze_url, capsys
):
    """Sin nada de la ejecución en bronce, `read_bronze_lines` da una lista vacía y la cuenta
    dice que faltan todos los registros (código 1)."""
    assert read_bronze_lines(bronze_url, recorded.derived(9)) == []

    code, out, err = recorded.compare_cli(9, capsys, "--postgres", bronze_url)

    assert code == 1
    assert out == ""
    assert "la cuenta no cuadra" in err
