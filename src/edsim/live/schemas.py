"""JSON Schema of the events, generated from the catalog (H6-10, task 6.4).

``event_schema(version)`` describes, in JSON Schema 2020-12, exactly what
``Event(**data)`` accepts for an event of that catalog version: one branch of
``oneOf`` per event type, each with the whole envelope and its payload, and
``additionalProperties: false`` on both. The checks of the payload describe
their own schema (``Check.json_schema``), so a new catalog version gets its
schema without touching this module.

Two things ``Event`` refuses and JSON Schema cannot say are listed in
``KNOWN_DIFFERENCES``, written into each schema and tested both ways.

The schemas are derived and written: ``uv run python -m edsim.live.schemas``,
from the root of the repository, writes ``schemas/eventos-v<n>.schema.json``,
and a test checks that the files written are the ones generated. The schemas
of ``ed.runs`` and ``ed.control`` are written by hand in the same folder.

Plain dictionaries: the package does not import ``jsonschema`` (only the tests
validate).
"""

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from edsim.engine.events import (
    CATALOGS,
    EPISODE_SCHEMA,
    PATIENT_SCHEMA,
    SCHEMA_VERSIONS,
    EventSpec,
)

DIALECT = "https://json-schema.org/draft/2020-12/schema"

COMMAND = "uv run python -m edsim.live.schemas"
"""The command that writes the schemas of the events, from the root of the repository."""

DEFAULT_DIRECTORY = Path("schemas")

MAX_DOUBLE = sys.float_info.max
"""Largest finite double, the ``maximum`` of every number.

``json.loads("1e400")`` gives ``inf``, which ``Event`` refuses; without this
limit the schema would accept it.
"""

KNOWN_DIFFERENCES: Mapping[str, str] = MappingProxyType(
    {
        "patient-id": (
            "patient_id debe llevar el número de episode_id (PT-000137 con EP-000137); "
            "el esquema no compara dos campos."
        ),
        "entero-con-decimales": (
            "Un entero escrito con parte decimal (3.0) no vale: en JSON Schema 2020-12 un "
            "número con parte decimal cero es entero, y EDsim lo lee como float y lo rechaza."
        ),
    }
)
"""What ``Event`` refuses and the schema accepts: the only differences between them."""

_TEXT = MappingProxyType({"type": "string", "minLength": 1})
_NULL = MappingProxyType({"type": "null"})


def _envelope_branch(version: int, event_type: str, spec: EventSpec) -> dict[str, object]:
    """The schema of one event type: the whole envelope and its payload."""
    properties: dict[str, object] = {
        "event_id": dict(_TEXT),
        "event_type": {"const": event_type},
        "schema_version": {"const": version},
        "run_id": dict(_TEXT),
        "episode_id": dict(EPISODE_SCHEMA if spec.patient else _NULL),
        "patient_id": dict(PATIENT_SCHEMA if spec.patient else _NULL),
        "source_system": {"const": spec.source_system},
        "sim_time": {"type": "number", "minimum": 0, "maximum": MAX_DOUBLE},
        "event_time": dict(_TEXT),
        "recorded_time": dict(_TEXT),
        "ingest_time": dict(_NULL),
        "payload": {
            "type": "object",
            "properties": {key: check.json_schema() for key, check in spec.payload.items()},
            "required": list(spec.payload),
            "additionalProperties": False,
        },
    }
    return {
        "title": event_type,
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _check_version(version: object) -> int:
    if isinstance(version, bool) or not isinstance(version, int) or version not in SCHEMA_VERSIONS:
        raise ValueError(f"version must be one of {sorted(SCHEMA_VERSIONS)}, got {version!r}")
    return version


def event_schema(version: int) -> dict[str, object]:
    """The JSON Schema 2020-12 of the events of a catalog version.

    Raises:
        ValueError: If ``version`` is not one of ``SCHEMA_VERSIONS``.
    """
    version = _check_version(version)
    differences = " ".join(f"({i}) {text}" for i, text in enumerate(KNOWN_DIFFERENCES.values(), 1))
    return {
        "$schema": DIALECT,
        "title": f"Eventos de EDsim, versión {version} del catálogo",
        "description": (
            "Una línea del log de eventos, que es también el valor de cada mensaje de "
            "ed.patient.events y ed.resource.events. Dice lo mismo que el catálogo de EDsim "
            f"salvo lo que JSON Schema no puede expresar: {differences}"
        ),
        "$comment": f"Generado con «{COMMAND}» desde la raíz del repositorio; no se edita a mano.",
        "oneOf": [
            _envelope_branch(version, event_type, spec)
            for event_type, spec in CATALOGS[version].items()
        ],
    }


def schema_filename(version: int) -> str:
    """Name of the file of the schema of a version, such as ``eventos-v3.schema.json``."""
    return f"eventos-v{_check_version(version)}.schema.json"


def schema_text(version: int) -> str:
    """The schema of a version as written in its file: indent 2, UTF-8 as is, final newline."""
    return json.dumps(event_schema(version), indent=2, ensure_ascii=False) + "\n"


def write_event_schemas(directory: str | Path = DEFAULT_DIRECTORY) -> list[Path]:
    """Write the schema of every catalog version in ``directory``; return the paths."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for version in sorted(SCHEMA_VERSIONS):
        path = directory / schema_filename(version)
        path.write_text(schema_text(version), encoding="utf-8", newline="\n")
        paths.append(path)
    return paths


def main(argv: list[str] | None = None) -> int:
    """``python -m edsim.live.schemas [directory]``: write the schemas (``schemas`` by default)."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) > 1:
        print(f"uso: {COMMAND} [carpeta]", file=sys.stderr)
        return 2
    for path in write_event_schemas(args[0] if args else DEFAULT_DIRECTORY):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
