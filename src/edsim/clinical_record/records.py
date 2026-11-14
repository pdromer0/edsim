"""What the hospital wrote down: ``Record``, the envelope of an event without the catalog.

A record has the same fields as ``edsim.engine.events.Event``, in the same order,
but its ``payload`` is not checked against the catalog: a field left empty is
``None``, which ``Event`` refuses, and ``record_corrected`` is not an event type
of any catalog (docs/specs/hito-7.md, «Especificación: el registro clínico»).

``record_json`` writes a record as ``to_json`` writes an event: the envelope in
its order and the payload with tuples as lists and mappings as objects.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

RECORD_CORRECTED = "record_corrected"
"""Event type of a late correction: ``{"corrige": <event_id>, "campos": {<campo>: <valor>}}``."""


@dataclass(frozen=True, slots=True)
class Record:
    """One record of what was written down: the envelope of ``Event`` and a free payload.

    The payload is copied into a read-only mapping, in the order given; its
    values are whatever the record holds (``None`` for an empty field). Nothing
    else is checked: ``record`` builds every record from a valid event.

    Attributes:
        event_id: ``run_id`` of the derived run, a hyphen and the emission
            number with nine digits, from 1.
        event_type: The type of the true event, or ``RECORD_CORRECTED``.
        schema_version: The catalog version of the true event.
        run_id: The derived run, ``<run_id>_<perfil>_s<semilla>``.
        episode_id: As in the true event; ``None`` in resource events.
        patient_id: As in the true event; ``None`` in resource events.
        source_system: The system that wrote it down.
        sim_time: Minutes of simulation at which it was written down.
        event_time: When it happened, by the clock of its system.
        recorded_time: When it was written down, by the clock of its system.
        ingest_time: Always ``None``, as in every message.
        payload: The payload as written down.
    """

    event_id: str
    event_type: str
    schema_version: int
    run_id: str
    episode_id: str | None
    patient_id: str | None
    source_system: str
    sim_time: float
    event_time: str
    recorded_time: str
    ingest_time: str | None
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.payload, Mapping):
            raise ValueError(f"{self.event_type}: payload must be a mapping, got {self.payload!r}")
        # The dataclass is frozen: object.__setattr__ is the standard way to set
        # fields during construction.
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


def _plain(value: object) -> object:
    """A payload value as plain JSON types: tuples as lists, mappings as dicts."""
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, tuple | list):
        return [_plain(v) for v in value]
    return value


_ENVELOPE = tuple(Record.__dataclass_fields__)


def record_json(record: Record) -> str:
    """One line of ``registrado.jsonl``: the envelope in the order of ``to_json``, no newline.

    ``ensure_ascii=False`` and ``allow_nan=False``, as ``to_json``.
    """
    data = {name: getattr(record, name) for name in _ENVELOPE}
    data["payload"] = _plain(record.payload)
    return json.dumps(data, ensure_ascii=False, allow_nan=False)
