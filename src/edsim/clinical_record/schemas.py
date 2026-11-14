"""JSON Schema of the records, derived from the catalog (task 7.1, decision 57).

``record_schema(version)`` takes the branches of ``edsim.live.schemas.event_schema``
(one per event type, with the whole envelope) and changes two things:

- every field of the ``payload`` also admits ``null``, the empty field;
- a branch ``record_corrected`` is added: ``{"corrige": <event_id>,
  "campos": {<campo>: <valor verdadero>}}``, with exactly one field among those
  that can get a wrong value in that version, and its true, non-null value.

The schemas are derived and written: ``uv run python -m edsim.clinical_record.schemas``,
from the root of the repository, writes ``schemas/registro-v<n>.schema.json``, and a
test checks that the files written are the ones generated. The schemas
``eventos-v*`` do not change.
"""

import copy
import json
import sys
from pathlib import Path

from edsim.clinical_record.record import WRONG_FIELDS
from edsim.clinical_record.records import RECORD_CORRECTED
from edsim.engine.events import CATALOGS, SCHEMA_VERSIONS
from edsim.live.schemas import DIALECT, event_schema

COMMAND = "uv run python -m edsim.clinical_record.schemas"
"""The command that writes the schemas of the records, from the root of the repository."""

DEFAULT_DIRECTORY = Path("schemas")

_NULL = {"type": "null"}
_TEXT = {"type": "string", "minLength": 1}


def _check_version(version: object) -> int:
    if isinstance(version, bool) or not isinstance(version, int) or version not in SCHEMA_VERSIONS:
        raise ValueError(f"version must be one of {sorted(SCHEMA_VERSIONS)}, got {version!r}")
    return version


def _nullable(branch: dict[str, object]) -> dict[str, object]:
    """An event branch whose payload fields also admit ``null``."""
    branch = copy.deepcopy(branch)
    payload = branch["properties"]["payload"]
    payload["properties"] = {
        key: {"anyOf": [schema, dict(_NULL)]} for key, schema in payload["properties"].items()
    }
    return branch


def _correction_branch(version: int) -> dict[str, object]:
    """The branch of ``record_corrected``: one wrong field of its version, with its true value.

    It is the branch of a patient event with another type, system and payload, so
    that the envelope is written in one place, ``edsim.live.schemas``.
    """
    fields: dict[str, object] = {}
    systems: list[str] = []
    for spec in CATALOGS[version].values():
        for key, check in spec.payload.items():
            if key in WRONG_FIELDS:
                fields.setdefault(key, check.json_schema())
                if spec.source_system not in systems:
                    systems.append(spec.source_system)
    fields = {key: fields[key] for key in WRONG_FIELDS if key in fields}
    patient = next(
        branch
        for branch, spec in zip(
            event_schema(version)["oneOf"], CATALOGS[version].values(), strict=True
        )
        if spec.patient
    )
    branch = copy.deepcopy(patient)
    branch["title"] = RECORD_CORRECTED
    properties = branch["properties"]
    properties["event_type"] = {"const": RECORD_CORRECTED}
    properties["source_system"] = {"enum": systems}
    properties["payload"] = {
        "type": "object",
        "properties": {
            "corrige": dict(_TEXT),
            "campos": {
                "type": "object",
                "properties": fields,
                "minProperties": 1,
                "maxProperties": 1,
                "additionalProperties": False,
            },
        },
        "required": ["corrige", "campos"],
        "additionalProperties": False,
    }
    return branch


def record_schema(version: int) -> dict[str, object]:
    """The JSON Schema 2020-12 of the records of a catalog version.

    Raises:
        ValueError: If ``version`` is not one of ``SCHEMA_VERSIONS``.
    """
    version = _check_version(version)
    return {
        "$schema": DIALECT,
        "title": f"Registros de EDsim, versión {version} del catálogo",
        "description": (
            "Una línea de registrado.jsonl: lo que el hospital anotó de un evento verdadero, "
            "con el sobre del log de eventos. Cada campo del payload puede quedar a null (un "
            "campo vacío), y record_corrected es la corrección tardía de un valor erróneo. "
            "No se valida contra el catálogo: un registro puede llevar valores erróneos."
        ),
        "$comment": f"Generado con «{COMMAND}» desde la raíz del repositorio; no se edita a mano.",
        "oneOf": [
            *(_nullable(branch) for branch in event_schema(version)["oneOf"]),
            _correction_branch(version),
        ],
    }


def schema_filename(version: int) -> str:
    """Name of the file of the schema of a version, such as ``registro-v4.schema.json``."""
    return f"registro-v{_check_version(version)}.schema.json"


def schema_text(version: int) -> str:
    """The schema of a version as written in its file: indent 2, UTF-8 as is, final newline."""
    return json.dumps(record_schema(version), indent=2, ensure_ascii=False) + "\n"


def write_record_schemas(directory: str | Path = DEFAULT_DIRECTORY) -> list[Path]:
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
    """``python -m edsim.clinical_record.schemas [carpeta]``: write the schemas."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) > 1:
        print(f"uso: {COMMAND} [carpeta]", file=sys.stderr)
        return 2
    for path in write_record_schemas(args[0] if args else DEFAULT_DIRECTORY):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
