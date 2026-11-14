"""Los esquemas de lo registrado, `schemas/registro-v*.schema.json` (tarea 7.1).

- **Escritos = generados**, como los `eventos-v*`.
- **Los registros validan:** los del escenario L y los de cada despiste, con un campo a
  `null` y con `record_corrected`, contra el esquema de su versión.
- **Lo que no es un registro no valida:** una clave de más, una corrección con dos campos
  o con un campo que no puede ser erróneo.
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from test_clinical_record import (
    START,
    make_profile,
    make_roll,
    one_patient,
    run_l,
    run_one,
)

from edsim.clinical_record import record_json
from edsim.clinical_record.schemas import COMMAND, record_schema, schema_filename, schema_text
from edsim.engine.events import SCHEMA_VERSIONS, EventLog, MemorySink
from edsim.live.schemas import event_schema

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"
VERSIONS = sorted(SCHEMA_VERSIONS)


def validator(version: int) -> Draft202012Validator:
    return Draft202012Validator(record_schema(version))


@pytest.mark.parametrize("version", VERSIONS)
def test_escritos_iguales_a_los_generados(version):
    # Si falla: uv run python -m edsim.clinical_record.schemas, desde la raíz.
    written = (SCHEMAS / schema_filename(version)).read_text(encoding="utf-8")
    assert written == schema_text(version)
    schema = json.loads(written)
    assert COMMAND in schema["$comment"]
    Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("version", VERSIONS)
def test_una_rama_por_tipo_mas_record_corrected(version):
    """Las ramas de eventos-v<n> con el payload anulable, y la de record_corrected al final."""
    events = event_schema(version)["oneOf"]
    branches = record_schema(version)["oneOf"]

    assert [b["title"] for b in branches] == [b["title"] for b in events] + ["record_corrected"]
    for event, branch in zip(events, branches, strict=False):
        payload = branch["properties"]["payload"]["properties"]
        for key, schema in event["properties"]["payload"]["properties"].items():
            assert payload[key] == {"anyOf": [schema, {"type": "null"}]}
    # Título y description propios: los de eventos-v<n> hablan del log de eventos.
    assert record_schema(version)["description"] != event_schema(version)["description"]
    assert "registrado.jsonl" in record_schema(version)["description"]
    assert record_schema(version)["title"].startswith("Registros de EDsim")


def test_los_registros_del_escenario_l_validan():
    recording = run_l()
    v4 = validator(4)

    for r in recording.records:
        v4.validate(json.loads(record_json(r)))
    assert recording.records[-1].event_type == "record_corrected"


@pytest.mark.parametrize("version", [1, 4])
def test_cada_despiste_valida_en_su_version(version):
    """Valor erróneo, vacío, corrección y duplicado, en los eventos de un paciente.

    El último evento (el alta) solo lleva el vacío: en la versión 1, el valor erróneo del
    alta dejaría sin campo para el vacío.
    """
    everything = make_roll(u_delay=0.0, u_wrong=0.0, u_empty=0.0, u_correction=0.0, u_duplicate=0.0)
    events = one_patient(version)
    rolls = [everything] * (len(events) - 1) + [make_roll(u_empty=0.0, u_duplicate=0.0)]
    recording = run_one(events, rolls)

    kinds = {r.event_type for r in recording.records}
    assert "record_corrected" in kinds
    assert any(None in r.payload.values() for r in recording.records)
    check = validator(version)
    for r in recording.records:
        check.validate(json.loads(record_json(r)))


def corrected_line() -> dict:
    recording = run_l()
    return json.loads(record_json(recording.records[-1]))


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(extra=1),
        lambda d: d["payload"]["campos"].update(motivo="disnea"),
        lambda d: d["payload"].update(campos={"sexo": "mujer"}),
        lambda d: d["payload"].update(campos={"nivel": None}),
        lambda d: d["payload"].update(campos={}),
        lambda d: d.update(source_system="lab"),
    ],
    ids=["clave-de-mas", "dos-campos", "campo-no-erroneo", "valor-nulo", "sin-campos", "lab"],
)
def test_lo_que_no_es_una_correccion_no_valida(change):
    data = corrected_line()
    assert validator(4).is_valid(data)
    change(data)
    assert not validator(4).is_valid(data)


def test_la_correccion_de_la_version_1_solo_admite_nivel_y_destino():
    branch = record_schema(1)["oneOf"][-1]

    assert list(branch["properties"]["payload"]["properties"]["campos"]["properties"]) == [
        "nivel",
        "destino",
    ]
    assert branch["properties"]["source_system"] == {"enum": ["triaje", "his"]}
    v4 = record_schema(4)["oneOf"][-1]
    assert list(v4["properties"]["payload"]["properties"]["campos"]["properties"]) == [
        "nivel",
        "edad",
        "motivo",
        "destino",
    ]


def test_un_evento_de_recursos_valida_como_registro():
    sink = MemorySink()
    EventLog("r2026", START, sink, schema_version=4).emit(
        "staffing_changed", 0.0, recurso="medicos", anterior=0, nueva=3
    )
    recording = run_one(sink.events, [], profile=make_profile())

    validator(4).validate(json.loads(record_json(recording.records[0])))
