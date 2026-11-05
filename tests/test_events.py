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
    CATALOG_V1,
    CATALOG_V2,
    CATALOGS,
    CLINICAL_SCHEMA_VERSION,
    PROVISIONAL_SCHEMA_VERSION,
    SCHEMA_VERSIONS,
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
    "triage_started": {"circuito": "enfermeria"},
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
    assert e.schema_version == PROVISIONAL_SCHEMA_VERSION == 1
    assert SCHEMA_VERSIONS == {1, 2}
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
        dataclasses.replace(e, schema_version=3)
    with pytest.raises(ValueError, match="schema_version"):
        dataclasses.replace(e, schema_version=True)
    # Con la versión 2, el mismo payload se valida con su catálogo: le falta el motivo.
    with pytest.raises(ValueError, match="triage_completed: missing payload keys: motivo"):
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


# --- circuito de triage_started (tarea 4.1) -------------------------------------------


def test_circuito_de_triaje():
    # Puerta para el nivel 1 y enfermería para los demás; nada más.
    log = EventLog(RUN, START, MemorySink())
    for circuito in ("puerta", "enfermeria"):
        assert log.emit("triage_started", 1.0, arrival_id=0, circuito=circuito)
    with pytest.raises(ValueError, match=r"triage_started: missing payload keys: circuito"):
        log.emit("triage_started", 1.0, arrival_id=0)
    with pytest.raises(ValueError, match=r"triage_started: payload circuito"):
        log.emit("triage_started", 1.0, arrival_id=0, circuito="box")


def test_lee_un_log_anterior_sin_circuito(tmp_path):
    # Antes de la tarea 4.1 triage_started no tenía payload: todos los triajes eran de
    # enfermería. Leerlo da circuito "enfermeria"; la versión del esquema sigue en 1.
    sink = MemorySink()
    EventLog(RUN, START, sink).emit("triage_started", 2.0, arrival_id=0, circuito="enfermeria")
    line = json.loads(to_json(sink.events[0]))
    line["payload"] = {}
    path = tmp_path / "eventos.jsonl"
    path.write_text(json.dumps(line) + "\n", encoding="utf-8")

    (event,) = read_events(path)

    assert event == sink.events[0]
    assert event.payload == {"circuito": "enfermeria"} and event.schema_version == 1


def test_solo_la_lectura_admite_triage_started_sin_circuito():
    # La construcción directa sigue exigiendo la clave: la tolerancia es de from_json.
    event = EventLog(RUN, START, MemorySink()).emit(
        "triage_started", 2.0, arrival_id=0, circuito="enfermeria"
    )
    with pytest.raises(ValueError, match=r"missing payload keys: circuito"):
        dataclasses.replace(event, payload={})


# --- Versiones del esquema y catálogo 2 (tarea 4.5a) -----------------------------------

# Un payload válido de cada tipo del catálogo 2, en el orden de la especificación.
SAMPLES_V2 = {
    **SAMPLES,
    "patient_arrived": {"medio": "ambulancia"},
    "patient_registered": {"edad": 83, "sexo": "mujer"},
    "triage_completed": {"nivel": 2, "motivo": "disnea"},
    "test_ordered": {"pruebas": ["analitica", "ecg"]},
    "test_resulted": {"resultados": {"analitica": "alterado", "ecg": "normal"}},
}


def clinical_log(sink=None) -> tuple[EventLog, MemorySink]:
    sink = MemorySink() if sink is None else sink
    return EventLog(RUN, START, sink, schema_version=CLINICAL_SCHEMA_VERSION), sink


def emit_all_v2(log: EventLog) -> None:
    times = [0.0, 0.0, 0.1 + 0.2, 1 / 3, 739.02, 739.02, 1000.000001, 1439.9999999]
    times += [2000.5, 2880.0, 3000.25, 4321.123456789, 5000.0]
    for event_type, t in zip(SAMPLES_V2, times, strict=True):
        kwargs = {"arrival_id": 137} if CATALOG_V2[event_type].patient else {}
        log.emit(event_type, t, **kwargs, **SAMPLES_V2[event_type])


def test_schema_version_ya_no_existe():
    # Ajuste de la aprobación: un uso antiguo falla al importar, en vez de comparar
    # un int con el conjunto de versiones.
    with pytest.raises(ImportError):
        from edsim.engine.events import SCHEMA_VERSION  # noqa: F401


def test_catalogos_por_version():
    assert dict(CATALOGS) == {1: CATALOG_V1, 2: CATALOG_V2}
    assert CATALOG is CATALOG_V1
    assert SCHEMA_VERSIONS == frozenset({PROVISIONAL_SCHEMA_VERSION, CLINICAL_SCHEMA_VERSION})
    with pytest.raises(TypeError):
        CATALOGS[3] = CATALOG_V2


def test_catalogo_2_literal():
    # La versión 2 es la 1 con los payloads clínicos: mismos tipos, mismo orden,
    # mismos sistemas de origen, y estas claves.
    assert list(CATALOG_V2) == list(CATALOG_V1)
    for name, spec in CATALOG_V2.items():
        assert spec.source_system == CATALOG_V1[name].source_system
        assert spec.patient == CATALOG_V1[name].patient
    keys = {name: list(spec.payload) for name, spec in CATALOG_V2.items()}
    assert keys == {
        "patient_arrived": ["medio"],
        "patient_registered": ["edad", "sexo"],
        "triage_started": ["circuito"],
        "triage_completed": ["nivel", "motivo"],
        "box_assigned": ["box"],
        "patient_displaced": ["box", "desalojado_por"],
        "assessment_started": ["tipo", "pool", "box"],
        "assessment_ended": ["tipo", "interrumpida"],
        "test_ordered": ["pruebas"],
        "test_resulted": ["resultados"],
        "disposition_decided": ["destino"],
        "patient_departed": ["destino"],
        "staffing_changed": ["recurso", "anterior", "nueva"],
    }
    # Los de la versión 1 no cambian.
    for name in ("triage_started", "box_assigned", "staffing_changed"):
        assert CATALOG_V2[name] is CATALOG_V1[name]


FORBIDDEN = {
    "gravedad",
    "severidad",
    "g",
    "z",
    "nivel_real",
    "calidad",
    "calidad_triaje",
    "salto",
    "banda",
    "banda_edad",
    "respuesta",
    "respuestas",
    "respuesta_base",
    "tiempo_respuesta",
}


@pytest.mark.parametrize("version", sorted(SCHEMA_VERSIONS))
def test_ningun_catalogo_lleva_lo_oculto(version):
    # G, z, nivel real, calidad, salto, banda y respuestas son ground truth.
    keys = {key for spec in CATALOGS[version].values() for key in spec.payload}
    assert not keys & FORBIDDEN


def test_eventlog_con_version():
    log, sink = clinical_log()
    e = log.emit("patient_arrived", 0.0, arrival_id=0, medio="propios_medios")

    assert log.schema_version == 2 and e.schema_version == 2
    assert e.payload == {"medio": "propios_medios"}
    assert EventLog(RUN, START, MemorySink()).schema_version == 1


@pytest.mark.parametrize("version", [0, 3, True, 2.0, "2", None])
def test_eventlog_con_version_invalida(version):
    with pytest.raises(ValueError, match="schema_version"):
        EventLog(RUN, START, MemorySink(), schema_version=version)


def test_cada_log_con_su_catalogo():
    v1, _ = memory_log()
    v2, _ = clinical_log()
    with pytest.raises(ValueError, match="patient_arrived: unknown payload keys: medio"):
        v1.emit("patient_arrived", 0.0, arrival_id=0, medio="ambulancia")
    with pytest.raises(ValueError, match="patient_arrived: missing payload keys: medio"):
        v2.emit("patient_arrived", 0.0, arrival_id=0)
    with pytest.raises(ValueError, match="test_ordered: missing payload keys: pruebas"):
        v2.emit("test_ordered", 0.0, arrival_id=0)


@pytest.mark.parametrize(
    ("event_type", "payload", "match"),
    [
        ("patient_arrived", {"medio": "helicoptero"}, "payload medio"),
        ("patient_registered", {"edad": -1, "sexo": "mujer"}, "payload edad"),
        ("patient_registered", {"edad": 40.0, "sexo": "mujer"}, "payload edad"),
        ("patient_registered", {"edad": True, "sexo": "mujer"}, "payload edad"),
        ("patient_registered", {"edad": 40, "sexo": "otro"}, "payload sexo"),
        ("triage_completed", {"nivel": 3, "motivo": "gripe"}, "payload motivo"),
        ("test_ordered", {"pruebas": []}, "non-empty list"),
        ("test_ordered", {"pruebas": "analitica"}, "non-empty list"),
        ("test_ordered", {"pruebas": {"analitica": 1}}, "non-empty list"),
        ("test_ordered", {"pruebas": ["analitica", "analitica"]}, "without repeats"),
        ("test_ordered", {"pruebas": ["ecg", "analitica"]}, "order"),
        ("test_ordered", {"pruebas": ["tac"]}, "must hold types"),
        ("test_ordered", {"pruebas": [1]}, "must hold types"),
        ("test_resulted", {"resultados": {}}, "non-empty object"),
        ("test_resulted", {"resultados": ["analitica"]}, "non-empty object"),
        ("test_resulted", {"resultados": {"tac": "normal"}}, "as keys"),
        ("test_resulted", {"resultados": {"ecg": "dudoso"}}, "map each type"),
        ("test_resulted", {"resultados": {"ecg": True}}, "map each type"),
    ],
)
def test_payloads_clinicos_invalidos(event_type, payload, match):
    log, _ = clinical_log()
    with pytest.raises(ValueError, match=match):
        log.emit(event_type, 1.0, arrival_id=0, **payload)


def test_pruebas_y_resultados_inmutables_y_normalizados():
    log, _ = clinical_log()
    pruebas = ["analitica", "radiografia", "imagen"]
    resultados = {"imagen": "normal", "analitica": "alterado"}
    ordered = log.emit("test_ordered", 1.0, arrival_id=0, pruebas=pruebas)
    resulted = log.emit("test_resulted", 2.0, arrival_id=0, resultados=resultados)
    pruebas.append("ecg")
    resultados["ecg"] = "normal"

    assert ordered.payload["pruebas"] == ("analitica", "radiografia", "imagen")
    assert type(ordered.payload["pruebas"]) is tuple
    assert isinstance(resulted.payload["resultados"], MappingProxyType)
    # Claves en el orden de TEST_TYPES, sea cual sea el de quien llama.
    assert list(resulted.payload["resultados"]) == ["analitica", "imagen"]
    assert resulted.payload["resultados"] == {"analitica": "alterado", "imagen": "normal"}
    with pytest.raises(TypeError):
        resulted.payload["resultados"]["ecg"] = "normal"
    assert '"resultados": {"analitica": "alterado", "imagen": "normal"}' in to_json(resulted)
    assert '"pruebas": ["analitica", "radiografia", "imagen"]' in to_json(ordered)


@pytest.mark.parametrize("event_type", list(SAMPLES_V2))
def test_pickle_y_deepcopy_v2(event_type):
    log, _ = clinical_log()
    kwargs = {"arrival_id": 137} if CATALOG_V2[event_type].patient else {}
    e = log.emit(event_type, 739.02, **kwargs, **SAMPLES_V2[event_type])

    for copied in (pickle.loads(pickle.dumps(e)), copy.deepcopy(e)):
        assert copied == e
        assert copied is not e
        assert copied.schema_version == 2
        assert isinstance(copied.payload, MappingProxyType)
        for value in copied.payload.values():
            assert isinstance(value, int | str | bool | tuple | MappingProxyType)


def test_ida_y_vuelta_v2(tmp_path):
    # JSON escribe listas y objetos; al leer, la lista vuelve a ser una tupla y el
    # objeto un mapping de solo lectura: los eventos leídos son iguales a los emitidos.
    path = tmp_path / "eventos.jsonl"
    _memory, sink = clinical_log()
    emit_all_v2(_memory)
    with JsonlSink(path) as jsonl:
        emit_all_v2(clinical_log(jsonl)[0])

    read = list(read_events(path))

    assert read == sink.events
    assert all(e.schema_version == 2 for e in read)
    ordered = next(e for e in read if e.event_type == "test_ordered")
    resulted = next(e for e in read if e.event_type == "test_resulted")
    assert type(ordered.payload["pruebas"]) is tuple
    assert isinstance(resulted.payload["resultados"], MappingProxyType)
    assert [to_json(e) for e in read] == [to_json(e) for e in sink.events]


def test_un_fichero_con_versiones_mezcladas_se_lee(tmp_path):
    # Cada evento se valida con el catálogo de su versión; la mezcla la señala la
    # invariante schema_version, no la lectura.
    v1, s1 = memory_log()
    v2, s2 = clinical_log()
    v1.emit("box_assigned", 1.0, arrival_id=0, box=1)
    v2.emit("patient_arrived", 2.0, arrival_id=1, medio="ambulancia")
    path = tmp_path / "eventos.jsonl"
    path.write_text(to_json(s1.events[0]) + "\n" + to_json(s2.events[0]) + "\n", encoding="utf-8")

    assert [e.schema_version for e in read_events(path)] == [1, 2]


def test_upgrade_solo_en_la_version_1(tmp_path):
    # Un triage_started de la versión 2 sin circuito no se completa: falla al leer.
    log, sink = clinical_log()
    log.emit("triage_started", 2.0, arrival_id=0, circuito="enfermeria")
    line = json.loads(to_json(sink.events[0]))
    line["payload"] = {}
    path = tmp_path / "eventos.jsonl"
    path.write_text(json.dumps(line) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"eventos\.jsonl:1: .*missing payload keys: circuito"):
        list(read_events(path))


def test_lectura_con_version_desconocida(tmp_path):
    path = write_with(tmp_path, lambda d: d.update(schema_version=3))
    events = read_events(path)
    next(events)
    with pytest.raises(ValueError, match=r"eventos\.jsonl:2: .*schema_version"):
        next(events)
