import copy
import dataclasses
import hashlib
import json
import math
import pickle
import re
from datetime import date, datetime
from types import MappingProxyType

import pytest

from edsim.engine.events import (
    CATALOG,
    SCHEMA_VERSION,
    Event,
    EventLog,
    JsonlSink,
    MemorySink,
    episode_id,
    event_time,
    patient_id,
    read_events,
    to_json,
)

START = date(2026, 1, 5)
RUN = "r2026"

# Un payload válido de cada tipo del catálogo, en el orden de la especificación.
SAMPLES = {
    "patient_arrived": {},
    "patient_registered": {},
    "triage_started": {},
    "triage_completed": {"nivel": 3},
    "box_assigned": {"box": 7},
    "patient_displaced": {"box": 7, "desalojado_por": "EP-000140"},
    "assessment_started": {"tipo": "inicial", "pool": "medicos", "box": 7},
    "assessment_ended": {"tipo": "reevaluacion", "interrumpida": False},
    "test_ordered": {},
    "test_resulted": {},
    "disposition_decided": {"destino": "ingreso"},
    "patient_departed": {"destino": "alta"},
    "staffing_changed": {"recurso": "medicos", "anterior": 12, "nueva": 7},
}

ENVELOPE = [
    "event_id",
    "event_type",
    "schema_version",
    "run_id",
    "episode_id",
    "patient_id",
    "source_system",
    "sim_time",
    "event_time",
    "recorded_time",
    "ingest_time",
    "payload",
]


def emit_sample(log: EventLog, event_type: str, sim_time: float, arrival_id: int = 137) -> Event:
    """Emit the sample payload of ``event_type``, with ``arrival_id`` only for patients."""
    kwargs = {"arrival_id": arrival_id} if CATALOG[event_type].patient else {}
    return log.emit(event_type, sim_time, **kwargs, **SAMPLES[event_type])


def emit_all(log: EventLog) -> None:
    """One event of each type, with awkward times and two at the same instant."""
    times = [0.0, 0.0, 0.1 + 0.2, 1 / 3, 739.02, 739.02, 1000.000001, 1439.9999999]
    times += [2000.5, 2880.0, 3000.25, 4321.123456789, 5000.0]
    for event_type, t in zip(SAMPLES, times, strict=True):
        emit_sample(log, event_type, t)


def memory_log(run_id: str = RUN, start_date: date = START) -> tuple[EventLog, MemorySink]:
    sink = MemorySink()
    return EventLog(run_id, start_date, sink), sink


# --- Catálogo ----------------------------------------------------------------


def test_catalogo_de_la_especificacion():
    sources = {name: spec.source_system for name, spec in CATALOG.items()}

    assert list(CATALOG) == list(SAMPLES)
    assert sources == {
        "patient_arrived": "admision",
        "patient_registered": "admision",
        "triage_started": "triaje",
        "triage_completed": "triaje",
        "box_assigned": "his",
        "patient_displaced": "his",
        "assessment_started": "his",
        "assessment_ended": "his",
        "test_ordered": "his",
        "test_resulted": "lab",
        "disposition_decided": "his",
        "patient_departed": "his",
        "staffing_changed": "rrhh",
    }
    assert [n for n, spec in CATALOG.items() if not spec.patient] == ["staffing_changed"]
    for name, spec in CATALOG.items():
        assert set(spec.payload) == set(SAMPLES[name]), name


def test_catalogo_inmutable():
    with pytest.raises(TypeError):
        CATALOG["nuevo"] = CATALOG["test_ordered"]


# --- event_time ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "sim_time", "expected"),
    [
        (START, 0.0, "2026-01-05T00:00:00.000+01:00"),
        (START, 739.02, "2026-01-05T12:19:01.200+01:00"),
        # 86399999.994 ms: se trunca a ...999, no se redondea al día siguiente.
        (START, 1439.9999999, "2026-01-05T23:59:59.999+01:00"),
        # 3599999.9999999995 ms: sigue siendo la hora 0.
        (START, 59.99999999999999, "2026-01-05T00:59:59.999+01:00"),
        (date(2026, 1, 31), 1440.0, "2026-02-01T00:00:00.000+01:00"),
        (date(2026, 12, 31), 1500.5, "2027-01-01T01:00:30.000+01:00"),
        # Sin cambio de hora (decisión 20): el 29 de marzo sigue en +01:00.
        (date(2026, 3, 29), 180.0, "2026-03-29T03:00:00.000+01:00"),
    ],
)
def test_event_time_a_mano(start, sim_time, expected):
    assert event_time(start, sim_time) == expected


def test_event_time_rechaza_datetime():
    with pytest.raises(ValueError, match="start_date"):
        event_time(datetime(2026, 1, 5), 0.0)


# --- Identificadores ----------------------------------------------------------


@pytest.mark.parametrize(
    ("arrival_id", "episode", "patient"),
    [
        (0, "EP-000000", "PT-000000"),
        (137, "EP-000137", "PT-000137"),
        (999_999, "EP-999999", "PT-999999"),
    ],
)
def test_identificadores(arrival_id, episode, patient):
    assert episode_id(arrival_id) == episode
    assert patient_id(arrival_id) == patient


@pytest.mark.parametrize("arrival_id", [-1, 1_000_000, True, 3.0, "137"])
def test_identificadores_invalidos(arrival_id):
    with pytest.raises(ValueError, match="arrival_id"):
        episode_id(arrival_id)
    with pytest.raises(ValueError, match="arrival_id"):
        patient_id(arrival_id)


# --- Sobre y event_id ----------------------------------------------------------


def test_sobre_completo():
    log, _ = memory_log()
    e = log.emit("triage_completed", 739.02, arrival_id=137, nivel=3)

    assert [f.name for f in dataclasses.fields(Event)] == ENVELOPE
    assert e.event_id == "r2026-000000000"
    assert e.event_type == "triage_completed"
    assert e.schema_version == SCHEMA_VERSION == 1
    assert e.run_id == RUN
    assert (e.episode_id, e.patient_id) == ("EP-000137", "PT-000137")
    assert e.source_system == "triaje"
    assert e.sim_time == 739.02 and type(e.sim_time) is float
    assert e.event_time == "2026-01-05T12:19:01.200+01:00"
    assert e.recorded_time == e.event_time
    assert e.ingest_time is None
    assert e.payload == {"nivel": 3}


def test_ejemplo_de_la_especificacion():
    # La línea del sobre común en docs/specs/hito-3.md, salvo el número del evento.
    log, _ = memory_log()
    e = log.emit("triage_completed", 739.02, arrival_id=137, nivel=3)

    assert to_json(e) == (
        '{"event_id": "r2026-000000000", "event_type": "triage_completed", '
        '"schema_version": 1, "run_id": "r2026", "episode_id": "EP-000137", '
        '"patient_id": "PT-000137", "source_system": "triaje", "sim_time": 739.02, '
        '"event_time": "2026-01-05T12:19:01.200+01:00", '
        '"recorded_time": "2026-01-05T12:19:01.200+01:00", "ingest_time": null, '
        '"payload": {"nivel": 3}}'
    )


def test_evento_de_recursos_sin_episodio():
    log, _ = memory_log()
    e = log.emit("staffing_changed", 480.0, recurso="medicos", anterior=7, nueva=12)

    assert (e.episode_id, e.patient_id) == (None, None)
    assert e.source_system == "rrhh"


def test_event_id_sigue_el_orden_de_emision():
    log, sink = memory_log()
    emit_all(log)

    ids = [e.event_id for e in sink.events]
    assert all(re.fullmatch(r"r2026-\d{9}", i) for i in ids)
    assert ids == [f"r2026-{n:09d}" for n in range(len(SAMPLES))]


def test_emit_fallido_no_consume_numero_ni_tiempo():
    log, sink = memory_log()
    log.emit("patient_arrived", 10.0, arrival_id=0)
    with pytest.raises(ValueError):
        log.emit("triage_completed", 20.0, arrival_id=0, nivel=9)
    log.emit("patient_registered", 10.0, arrival_id=0)

    assert [e.event_id for e in sink.events] == ["r2026-000000000", "r2026-000000001"]


def test_contador_agotado(monkeypatch):
    log, _ = memory_log()
    monkeypatch.setattr(log, "_next_number", 10**9)

    with pytest.raises(RuntimeError, match="event_id"):
        log.emit("patient_arrived", 0.0, arrival_id=0)


def test_tiempo_que_decrece():
    log, _ = memory_log()
    log.emit("patient_arrived", 10.0, arrival_id=0)

    with pytest.raises(RuntimeError, match="sim_time decreased"):
        log.emit("patient_registered", 9.999, arrival_id=0)


@pytest.mark.parametrize(
    ("run_id", "start_date", "match"),
    [
        ("", START, "run_id"),
        (2026, START, "run_id"),
        (RUN, datetime(2026, 1, 5), "start_date"),
        (RUN, "2026-01-05", "start_date"),
    ],
)
def test_eventlog_valida_sus_argumentos(run_id, start_date, match):
    with pytest.raises(ValueError, match=match):
        EventLog(run_id, start_date, MemorySink())


# --- Errores de emit -----------------------------------------------------------

PATIENT = {"arrival_id": 137}


@pytest.mark.parametrize(
    ("event_type", "sim_time", "kwargs", "match"),
    [
        ("patient_left", 1.0, PATIENT, r"unknown event_type 'patient_left'"),
        ("triage_completed", 1.0, PATIENT, r"triage_completed: missing payload keys: nivel"),
        (
            "patient_arrived",
            1.0,
            PATIENT | {"nivel": 3},
            r"patient_arrived: unknown payload keys: nivel",
        ),
        ("triage_completed", 1.0, PATIENT | {"nivel": 0}, r"triage_completed: payload nivel"),
        ("triage_completed", 1.0, PATIENT | {"nivel": 6}, r"triage_completed: payload nivel"),
        ("triage_completed", 1.0, PATIENT | {"nivel": "3"}, r"triage_completed: payload nivel"),
        ("triage_completed", 1.0, PATIENT | {"nivel": True}, r"triage_completed: payload nivel"),
        ("triage_completed", 1.0, PATIENT | {"nivel": 3.0}, r"triage_completed: payload nivel"),
        ("box_assigned", 1.0, PATIENT | {"box": 0}, r"box_assigned: payload box"),
        (
            "patient_displaced",
            1.0,
            PATIENT | {"box": 1, "desalojado_por": "EP-140"},
            r"patient_displaced: payload desalojado_por",
        ),
        (
            "patient_displaced",
            1.0,
            PATIENT | {"box": 1, "desalojado_por": 140},
            r"patient_displaced: payload desalojado_por",
        ),
        (
            "assessment_started",
            1.0,
            PATIENT | {"tipo": "final", "pool": "medicos", "box": 1},
            r"assessment_started: payload tipo",
        ),
        (
            "assessment_started",
            1.0,
            PATIENT | {"tipo": "inicial", "pool": "boxes", "box": 1},
            r"assessment_started: payload pool",
        ),
        (
            "assessment_ended",
            1.0,
            PATIENT | {"tipo": "inicial", "interrumpida": 1},
            r"assessment_ended: payload interrumpida",
        ),
        (
            "disposition_decided",
            1.0,
            PATIENT | {"destino": "fuga"},
            r"disposition_decided: payload destino",
        ),
        (
            "staffing_changed",
            1.0,
            {"recurso": "boxes", "anterior": 1, "nueva": 2},
            r"staffing_changed: payload recurso",
        ),
        (
            "staffing_changed",
            1.0,
            {"recurso": "medicos", "anterior": -1, "nueva": 2},
            r"staffing_changed: payload anterior",
        ),
        ("patient_arrived", 1.0, {}, r"patient_arrived: .*arrival_id"),
        (
            "staffing_changed",
            1.0,
            {"arrival_id": 1, "recurso": "medicos", "anterior": 1, "nueva": 2},
            r"staffing_changed: .*arrival_id",
        ),
        ("patient_arrived", 1.0, {"arrival_id": -1}, r"patient_arrived: .*arrival_id"),
        ("patient_arrived", -1.0, PATIENT, r"patient_arrived: sim_time"),
        ("patient_arrived", math.nan, PATIENT, r"patient_arrived: sim_time"),
        ("patient_arrived", math.inf, PATIENT, r"patient_arrived: sim_time"),
        ("patient_arrived", True, PATIENT, r"patient_arrived: sim_time"),
        ("patient_arrived", "1.0", PATIENT, r"patient_arrived: sim_time"),
    ],
)
def test_errores_de_emit(event_type, sim_time, kwargs, match):
    log, sink = memory_log()

    with pytest.raises(ValueError, match=match):
        log.emit(event_type, sim_time, **kwargs)
    assert sink.events == []


# --- Inmutabilidad, pickle y copia ---------------------------------------------


def test_evento_inmutable():
    payload = {"nivel": 3}
    log, _ = memory_log()
    e = log.emit("triage_completed", 1.0, arrival_id=1, **payload)

    with pytest.raises(dataclasses.FrozenInstanceError):
        e.sim_time = 2.0
    with pytest.raises(TypeError):
        e.payload["nivel"] = 1
    assert isinstance(e.payload, MappingProxyType)


def test_payload_copiado_al_construir():
    payload = {"nivel": 3}
    log, _ = memory_log()
    e = log.emit("triage_completed", 1.0, arrival_id=1, **payload)
    built = dataclasses.replace(e, payload=payload)
    payload["nivel"] = 1

    assert e.payload == {"nivel": 3}
    assert built.payload == {"nivel": 3}


def test_construccion_directa_tambien_valida():
    log, _ = memory_log()
    e = log.emit("triage_completed", 1.0, arrival_id=1, nivel=3)

    with pytest.raises(ValueError, match="triage_completed: payload nivel"):
        dataclasses.replace(e, payload={"nivel": 7})
    with pytest.raises(ValueError, match="source_system"):
        dataclasses.replace(e, source_system="his")
    with pytest.raises(ValueError, match="patient_id"):
        dataclasses.replace(e, patient_id="PT-000002")
    with pytest.raises(ValueError, match="schema_version"):
        dataclasses.replace(e, schema_version=2)


@pytest.mark.parametrize("event_type", list(SAMPLES))
def test_pickle_y_deepcopy(event_type):
    log, _ = memory_log()
    e = emit_sample(log, event_type, 739.02)

    for copied in (pickle.loads(pickle.dumps(e)), copy.deepcopy(e)):
        assert copied == e
        assert copied is not e
        assert isinstance(copied.payload, MappingProxyType)


# --- JSONL: ida y vuelta y bytes -----------------------------------------------


def test_ida_y_vuelta(tmp_path):
    path = tmp_path / "eventos.jsonl"
    memory, sink = memory_log()
    emit_all(memory)
    with JsonlSink(path) as jsonl:
        emit_all(EventLog(RUN, START, jsonl))

    read = list(read_events(path))

    assert len(read) == len(SAMPLES)
    for original, back in zip(sink.events, read, strict=True):
        for field in ENVELOPE:
            assert getattr(back, field) == getattr(original, field), field
        assert back.sim_time.hex() == original.sim_time.hex()
        assert isinstance(back.payload, MappingProxyType)


def test_memoria_y_fichero_reciben_los_mismos_eventos(tmp_path):
    path = tmp_path / "eventos.jsonl"
    memory, sink = memory_log()
    emit_all(memory)
    with JsonlSink(path) as jsonl:
        emit_all(EventLog(RUN, START, jsonl))

    assert sink.events == list(read_events(path))


def test_mismos_eventos_mismos_bytes(tmp_path):
    run_id = "prueba-reevaluación"
    digests = []
    for name in ("a.jsonl", "b.jsonl"):
        with JsonlSink(tmp_path / name) as sink:
            emit_all(EventLog(run_id, START, sink))
        digests.append(hashlib.sha256((tmp_path / name).read_bytes()).hexdigest())
    data = (tmp_path / "a.jsonl").read_bytes()

    assert digests[0] == digests[1]
    assert "reevaluación".encode() in data
    assert b"\\u" not in data
    assert data.count(b"\n") == len(SAMPLES) and data.endswith(b"\n")


def test_una_linea_por_evento_con_el_orden_del_sobre(tmp_path):
    path = tmp_path / "eventos.jsonl"
    with JsonlSink(path) as sink:
        emit_all(EventLog(RUN, START, sink))

    for line in path.read_text(encoding="utf-8").splitlines():
        assert list(json.loads(line)) == ENVELOPE


def test_jsonl_fuera_del_with(tmp_path):
    sink = JsonlSink(tmp_path / "eventos.jsonl")
    log = EventLog(RUN, START, sink)

    with pytest.raises(RuntimeError, match="with"):
        log.emit("patient_arrived", 0.0, arrival_id=0)


# --- read_events rechaza ficheros fuera del catálogo ----------------------------


def write_with(tmp_path, change) -> object:
    """Write two valid events and apply ``change`` to the dict of the second one."""
    log, sink = memory_log()
    log.emit("patient_arrived", 0.0, arrival_id=0)
    log.emit("triage_completed", 5.0, arrival_id=0, nivel=3)
    lines = [json.loads(to_json(e)) for e in sink.events]
    change(lines[1])
    path = tmp_path / "eventos.jsonl"
    # json.dumps por defecto admite NaN: así se puede escribir un fichero roto.
    path.write_text("".join(json.dumps(d) + "\n" for d in lines), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (
            lambda d: d["payload"].update(gravedad=0.7),
            r"triage_completed: unknown payload keys: gravedad",
        ),
        (lambda d: d["payload"].pop("nivel"), r"missing payload keys: nivel"),
        (lambda d: d.update(oculto=1), r"envelope.*oculto"),
        (lambda d: d.pop("ingest_time"), r"envelope.*ingest_time"),
        (lambda d: d.update(event_type="patient_left"), r"unknown event_type"),
        (lambda d: d.update(sim_time=math.nan), r"sim_time"),
        (lambda d: d.update(sim_time=math.inf), r"sim_time"),
        (lambda d: d.update(ingest_time="2026-01-05T00:00:05.000+01:00"), r"ingest_time"),
    ],
)
def test_read_events_rechaza(tmp_path, change, match):
    path = write_with(tmp_path, change)
    events = read_events(path)

    assert next(events).event_type == "patient_arrived"  # perezoso: la primera línea vale
    with pytest.raises(ValueError, match=rf"eventos\.jsonl:2: .*{match}"):
        next(events)


def test_read_events_rechaza_json_invalido(tmp_path):
    path = tmp_path / "eventos.jsonl"
    path.write_text("{no es json}\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"eventos\.jsonl:1"):
        list(read_events(path))
