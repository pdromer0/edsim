"""Bronce sin Kafka (tarea 8.8): los mensajes que habría guardado el consumidor.

`bronze_messages` es lo que usan la punta a punta del hito 8 y el notebook 08 para llenar bronce
sin Kafka. La escritura (`write_bronze`) la prueba la punta a punta contra un Postgres real; aquí
va la parte pura, con un registro de verdad: un log a mano con una fila de recursos, dos
pacientes en el calentamiento (uno sigue dentro en W) y uno después, registrado con el perfil
`limpio` de `config/`. Cada test pilla un fallo que no pilla ningún otro.
"""

import json
from datetime import date
from pathlib import Path

from edsim.clinical_record import load_record_profiles, record, record_json
from edsim.engine.events import EventLog, MemorySink
from edsim.live.directo import REPLAY, RecordInfo, RunInfo
from edsim.live.topics import PATIENT_EVENTS, RESOURCE_EVENTS, RUNS
from edsim.store.bronze import RunRow, to_row
from edsim.store.offline import bronze_messages

CONFIG = Path(__file__).resolve().parents[1] / "config"
ORIGIN = "rbronce"
SEED = 7
W, H = 120.0, 1440.0
STARTED_MS = 1_767_225_600_000  # 2026-01-01T00:00:00Z


def recorded_lines() -> list[str]:
    """Lo registrado con el perfil `limpio` (sin despistes: un registro por hecho, en orden)."""
    sink = MemorySink()
    log = EventLog(ORIGIN, date(2026, 1, 5), sink, schema_version=4)
    log.emit("staffing_changed", 0.0, recurso="medicos", anterior=0, nueva=3)
    log.emit("patient_arrived", 10.0, arrival_id=1, medio="propios_medios")
    log.emit("patient_departed", 60.0, arrival_id=1, destino="alta")
    log.emit("patient_arrived", 90.0, arrival_id=2, medio="ambulancia")
    log.emit("patient_arrived", 200.0, arrival_id=3, medio="propios_medios")
    clean = load_record_profiles(CONFIG / "registro_clinico.toml")["limpio"]
    recording = record(sink.events, clean, SEED, horizon=H, run_id=ORIGIN)
    return [record_json(r) for r in recording.records]


def info() -> RunInfo:
    return RunInfo(
        run_id=f"{ORIGIN}_limpio_s{SEED}",
        mode=REPLAY,
        schema_version=4,
        seed=SEED,
        start_date=date(2026, 1, 5),
        anchored=False,
        record=RecordInfo(ORIGIN, "limpio", SEED),
    )


def test_el_inicio_lleva_el_bloque_registro():
    """Sin el bloque `registro`, `preparacion.parametros` no marca la ejecución como registrada
    y no sale en la variable de Urgencias ni en la tabla de tres columnas (D2 de la 8.6). El
    `inicio` lleva también W y H: el notebook y la punta a punta cuentan en esa ventana."""
    messages = bronze_messages(info(), recorded_lines(), warmup=W, horizon=H, started_ms=STARTED_MS)

    row = to_row(messages[0])

    assert isinstance(row, RunRow) and row.tipo == "inicio"
    start = json.loads(row.mensaje)
    assert start["registro"] == {"origen": ORIGIN, "perfil": "limpio", "semilla": SEED}
    assert (start["inicio_directo"], start["horizonte"]) == (W, H)
    assert start["run_id"] == f"{ORIGIN}_limpio_s{SEED}"


def test_el_calentamiento_va_entero():
    """A diferencia de una reemisión, que del calentamiento solo publica el censo según la
    verdad, aquí van todas las líneas, en su orden: también las de antes de W. Sin ellas, una
    salida olvidada del calentamiento no llegaría a bronce y faltaría su fantasma en el censo.
    Cada una, en el topic de su clase: los recursos no tienen episodio."""
    lines = recorded_lines()
    early = [line for line in lines if json.loads(line)["sim_time"] < W]
    assert len(early) == 4  # no es un test vacío: hay calentamiento, con la fila de recursos

    messages = bronze_messages(info(), lines, warmup=W, horizon=H, started_ms=STARTED_MS)

    events = messages[1:-1]
    assert [m.value.decode() for m in events] == lines
    assert [m.topic for m in events] == [RESOURCE_EVENTS] + [PATIENT_EVENTS] * 4


def test_las_marcas_crecen_y_el_fin_va_el_ultimo():
    """`ultimo_inicio` y `ultimo_fin` del proyecto dbt eligen por `ingest_time`, que es la marca:
    con marcas repetidas o un `fin` antes de un evento, `parametros` no vería la ejecución
    terminada. El `fin` dice cuántas líneas se publicaron y cuál fue la última; sin líneas,
    quedan el `inicio` y el `fin`, sin último evento."""
    lines = recorded_lines()

    messages = bronze_messages(info(), lines, warmup=W, horizon=H, started_ms=STARTED_MS)
    empty = bronze_messages(info(), [], warmup=W, horizon=H, started_ms=STARTED_MS)

    stamps = [m.timestamp_ms for m in messages]
    assert stamps == list(range(STARTED_MS, STARTED_MS + len(lines) + 2))
    assert [m.offset for m in messages] == stamps
    assert (messages[0].topic, messages[-1].topic) == (RUNS, RUNS)
    end = json.loads(messages[-1].value)
    assert (end["tipo"], end["sim_time"], end["publicados"]) == ("fin", H, len(lines))
    assert end["ultimo_event_id"] == json.loads(lines[-1])["event_id"]
    assert [m.topic for m in empty] == [RUNS, RUNS]
    assert json.loads(empty[-1].value)["ultimo_event_id"] is None
