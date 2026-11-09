"""Topics del modo directo y regla de reparto (tarea 6.4, H6-7).

La tabla del código se compara con una copia literal de la especificación
(docs/specs/hito-6.md, «Especificación: topics y mensajes»). El reparto se prueba con
valores a mano; el caso de un catálogo que aún no existe está en test_kafka_sink.py,
donde se ve el mensaje entero.
"""

from edsim.engine.events import EventLog, MemorySink
from edsim.engine.scenarios import SCENARIO_START
from edsim.live.topics import (
    PATIENT_EVENTS,
    REPLICATION_FACTOR,
    RESOURCE_EVENTS,
    TOPIC_CONFIG,
    TOPICS,
    route,
)

# Copia literal de la tabla de la especificación: topic, particiones y clave.
SPEC_TABLE = [
    ("ed.patient.events", 3, "episode_id"),
    ("ed.resource.events", 1, "recurso"),
    ("ed.runs", 1, "run_id"),
    ("ed.control", 1, "run_id"),
]
# «Configuración de los cuatro: message.timestamp.type=LogAppendTime, cleanup.policy=delete
# y la retención por defecto».
SPEC_CONFIG = {"message.timestamp.type": "LogAppendTime", "cleanup.policy": "delete"}


def test_tabla_de_topics_igual_a_la_especificacion():
    assert [(t.name, t.partitions, t.key) for t in TOPICS] == SPEC_TABLE
    assert all(dict(t.config) == SPEC_CONFIG for t in TOPICS)
    assert dict(TOPIC_CONFIG) == SPEC_CONFIG
    assert REPLICATION_FACTOR == 1


def test_reparto_a_mano():
    sink = MemorySink()
    log = EventLog("r2026", SCENARIO_START, sink, schema_version=3)
    staffing = log.emit("staffing_changed", 0.0, recurso="medicos", anterior=0, nueva=7)
    triage = log.emit("triage_completed", 10.0, arrival_id=137, nivel=3, motivo="dolor_toracico")

    assert route(staffing) == (RESOURCE_EVENTS, b"medicos")
    assert route(triage) == (PATIENT_EVENTS, b"EP-000137")
