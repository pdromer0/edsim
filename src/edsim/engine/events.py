"""Event log: the common envelope, the catalogs of each schema version and JSONL.

The log is the only output of the engine: every transition of a patient, and
every staffing change, is one event. State and metrics are derived from it
later (event sourcing), so the log must be exact, reproducible bit for bit and
closed: no key outside the catalog can get into it (ADR candidate 28).

Each event is an envelope with the same fields for every type, plus a
``payload`` with what is specific to its type (docs/specs/hito-3.md):

- ``event_id``: ``run_id``, a hyphen and the emission number with nine digits.
  Deterministic: a ``uuid4`` would break reproducibility.
- ``episode_id`` and ``patient_id``: ``EP-`` and ``PT-`` with the arrival
  number in six digits; ``None`` in resource events.
- ``sim_time``: minutes of simulation, exact. Invariants and metrics use it.
- ``event_time``: ``start_date`` at 00:00 plus ``sim_time``, truncated to the
  millisecond, in ISO 8601 with the fixed offset ``+01:00`` (no daylight
  saving time). ``recorded_time`` is equal to it until milestone 7, and
  ``ingest_time`` is ``None`` until there is a broker in milestone 6.

Field names of the envelope are in English, as in the design; payload keys and
values are in Spanish, as the configuration keys.

The same ``EventLog`` writes to memory (``MemorySink``, for tests and
notebooks) or to a JSONL file (``JsonlSink``), one JSON object per line.
``read_events`` reads the file back, line by line, and validates every event
against the catalog of its version.

**Schema versions** (docs/specs/hito-4.md, task 4.5a). There is one catalog per
version, in ``CATALOGS``:

- version 1 is the catalog of milestone 3 with the ``circuito`` of task 4.1,
  without clinical payloads; the provisional model writes it;
- version 2 is version 1 plus the payloads of the clinical model: ``medio``,
  ``edad``, ``sexo``, ``motivo``, ``pruebas`` and ``resultados``;
- version 3 is version 2 plus ``box_released`` (task 4.6a): a patient of a
  level of ``espera_resultados_fuera`` leaves its box when the tests are
  ordered and waits for the results outside, still inside the department.
  The clinical model writes it, whatever that list holds: one version per
  model, not per configuration.
- version 4 is version 3 plus the outcome of milestone 5 (task 5.1, H5-7):
  ``patient_left_wbs`` (the patient leaves without being seen),
  ``bed_requested`` and ``bed_assigned`` (the wait for a ward bed) and four
  destinations. The model of milestone 5 writes it.

A log has one version, the one of its ``EventLog``; the invariant
``schema_version`` checks it. Nothing hidden from the hospital (the latent
severity, the true level, the quality of the triage, the age band, the
turnarounds) is in any catalog.
"""

import dataclasses
import itertools
import json
import math
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, Self, TextIO

from edsim.finite import to_float

# DESTINATIONS lives in the profiles, which cannot import the engine; it is
# offered here too, as the ``destino`` of version 4.
from edsim.profiles.config import DESTINATIONS, REASON_KEYS, TEST_TYPES

PROVISIONAL_SCHEMA_VERSION = 1
"""Version of the logs of the provisional model: the catalog without clinical payloads."""

CURRENT_CLINICAL_SCHEMA_VERSION = 3
"""Version the clinical model writes since task 4.6a: version 2 plus ``box_released``.

It replaces ``CLINICAL_SCHEMA_VERSION`` (2), which is gone so that an old use
fails on import instead of missing the logs of version 3.
"""

OUTCOME_SCHEMA_VERSION = 4
"""Version the model of milestone 5 writes: version 3 plus the outcome (task 5.1).

``CURRENT_CLINICAL_SCHEMA_VERSION`` keeps its value and its meaning, the
version of the model of milestone 4: a new meaning under the same name would
break its readers without a word.
"""

CLINICAL_SCHEMA_VERSIONS: frozenset[int] = frozenset({2, 3, OUTCOME_SCHEMA_VERSION})
"""Versions with the clinical payloads: 2 (tasks 4.5a and 4.5b), 3 and 4."""

TIMEZONE = timezone(timedelta(hours=1))
"""Fixed offset of ``event_time``: +01:00 all year (ADR candidate 20)."""

MAX_ARRIVAL_ID = 999_999
"""Largest ``arrival_id`` that fits the six digits of the episode identifier."""

_MAX_EVENTS = 10**9
"""Events per run that fit the nine digits of ``event_id``."""

_EPISODE = re.compile(r"EP-[0-9]{6}")
_PATIENT = re.compile(r"PT-[0-9]{6}")


class Check(Protocol):
    """A payload check of the catalog: it validates a value and describes its JSON Schema.

    Called with the event type and the key, to name them in errors, it returns
    the value to keep: the same one, or an immutable copy of a container.
    ``json_schema()`` says the same in JSON Schema 2020-12, for the JSON value
    (``edsim.live.schemas``, task 6.4).
    """

    def __call__(self, event_type: str, key: str, value: object) -> object: ...

    def json_schema(self) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class _IntRange:
    """An integer (not a bool) in ``[low, high]``; no upper limit if ``high`` is None."""

    low: int
    high: int | None = None

    def __call__(self, event_type: str, key: str, value: object) -> object:
        low, high = self.low, self.high
        limit = f">= {low}" if high is None else f"between {low} and {high}"
        # bool is a subclass of int in Python: True must not pass as 1.
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < low
            or (high is not None and value > high)
        ):
            raise ValueError(
                f"{event_type}: payload {key} must be an integer {limit}, got {value!r}"
            )
        return value

    def json_schema(self) -> dict[str, object]:
        schema: dict[str, object] = {"type": "integer", "minimum": self.low}
        if self.high is not None:
            schema["maximum"] = self.high
        return schema


def _int_range(low: int, high: int | None = None) -> Check:
    """An integer (not a bool) in ``[low, high]``; no upper limit if ``high`` is None."""
    return _IntRange(low, high)


@dataclass(frozen=True, slots=True)
class _Choice:
    """One of a fixed set of strings."""

    values: tuple[str, ...]

    def __call__(self, event_type: str, key: str, value: object) -> object:
        values = self.values
        if not isinstance(value, str) or value not in values:
            raise ValueError(
                f"{event_type}: payload {key} must be one of {values!r}, got {value!r}"
            )
        return value

    def json_schema(self) -> dict[str, object]:
        return {"enum": list(self.values)}


def _choice(*values: str) -> Check:
    """One of a fixed set of strings."""
    return _Choice(values)


@dataclass(frozen=True, slots=True)
class _Bool:
    """``True`` or ``False``; 0 and 1 are not."""

    def __call__(self, event_type: str, key: str, value: object) -> object:
        if not isinstance(value, bool):
            raise ValueError(f"{event_type}: payload {key} must be true or false, got {value!r}")
        return value

    def json_schema(self) -> dict[str, object]:
        return {"type": "boolean"}


_bool = _Bool()

EPISODE_SCHEMA: Mapping[str, object] = MappingProxyType(
    {"type": "string", "pattern": "^EP-[0-9]{6}$", "maxLength": 9}
)
"""JSON Schema of an episode identifier.

``maxLength`` is not redundant: ``jsonschema`` checks ``pattern`` with Python's
``re.search``, where ``$`` also matches before a final newline, so
``"EP-000137\n"`` would pass the pattern alone (``Event`` refuses it).
"""

PATIENT_SCHEMA: Mapping[str, object] = MappingProxyType(
    {"type": "string", "pattern": "^PT-[0-9]{6}$", "maxLength": 9}
)
"""JSON Schema of a patient identifier; ``maxLength`` as in ``EPISODE_SCHEMA``."""


@dataclass(frozen=True, slots=True)
class _EpisodeRef:
    """An episode identifier, such as ``EP-000137``."""

    def __call__(self, event_type: str, key: str, value: object) -> object:
        if not isinstance(value, str) or not _EPISODE.fullmatch(value):
            raise ValueError(
                f"{event_type}: payload {key} must be an episode_id such as 'EP-000137', "
                f"got {value!r}"
            )
        return value

    def json_schema(self) -> dict[str, object]:
        return dict(EPISODE_SCHEMA)


_episode = _EpisodeRef()


@dataclass(frozen=True, slots=True)
class EventSpec:
    """What the catalog says about one event type.

    Attributes:
        source_system: System that records the event: ``admision``,
            ``triaje``, ``his``, ``lab`` or ``rrhh``.
        patient: Whether the event belongs to an episode (and so has
            ``episode_id`` and ``patient_id``) or to a resource.
        payload: Payload keys, in order, with the check of each value.
    """

    source_system: str
    patient: bool
    payload: Mapping[str, Check]


def _spec(source_system: str, patient: bool = True, **payload: Check) -> EventSpec:
    return EventSpec(source_system, patient, MappingProxyType(payload))


DOOR = "puerta"
"""``circuito`` of a triage done at the door: a level 1, without a nurse and
with duration 0 (ADR candidate 39, docs/specs/hito-4.md)."""

NURSE = "enfermeria"
"""``circuito`` of a triage done by a triage nurse: every level but 1."""

ARRIVAL_MODES = ("ambulancia", "propios_medios")
"""``medio`` of ``patient_arrived`` in version 2."""

SEXES = ("mujer", "hombre")
"""``sexo`` of ``patient_registered`` in version 2."""

TEST_RESULTS = ("normal", "alterado")
"""Values of ``resultados`` in ``test_resulted``, version 2."""

RESULTS_WAIT = "resultados"
"""``espera`` of ``box_released``, version 3: the patient leaves the box to wait
for the results of its tests outside it (ADR candidate 45)."""

LWBS_WAITS = ("triaje", "box", "medico")
"""``espera`` of ``patient_left_wbs``, version 4: where the patient was waiting.

``triaje`` for a triage nurse, ``box`` for a box (also after a displacement
before being seen) and ``medico`` in a box, for the first assessment.
"""

WARD = "planta"
"""``servicio`` of ``bed_requested`` and ``bed_assigned``, version 4: the only one yet."""

_TIPO = _choice("inicial", "reevaluacion")
_BOX = _int_range(1)
_DESTINO = _choice("alta", "ingreso")


@dataclass(frozen=True, slots=True)
class _TestTypes:
    """A non-empty list of types of test, in the order of ``TEST_TYPES``, without repeats.

    Kept as a tuple, so that the event stays immutable; JSON writes it as a
    list. The order is strict: the engine writes it so, and a list is data.
    """

    def __call__(self, event_type: str, key: str, value: object) -> tuple[str, ...]:
        if isinstance(value, str) or not isinstance(value, list | tuple) or not value:
            raise ValueError(
                f"{event_type}: payload {key} must be a non-empty list of {TEST_TYPES!r}, "
                f"got {value!r}"
            )
        for item in value:
            if not isinstance(item, str) or item not in TEST_TYPES:
                raise ValueError(
                    f"{event_type}: payload {key} must hold types of {TEST_TYPES!r}, got {item!r}"
                )
        positions = [TEST_TYPES.index(item) for item in value]
        if any(b <= a for a, b in zip(positions, positions[1:], strict=False)):
            raise ValueError(
                f"{event_type}: payload {key} must follow the order of {TEST_TYPES!r} "
                f"without repeats, got {value!r}"
            )
        return tuple(value)

    def json_schema(self) -> dict[str, object]:
        # Every non-empty list in the order of TEST_TYPES, without repeats: 2**4 - 1 = 15.
        # JSON Schema cannot say "in this order" for items, so the lists are written out,
        # shortest first.
        lists = [
            list(combination)
            for size in range(1, len(TEST_TYPES) + 1)
            for combination in itertools.combinations(TEST_TYPES, size)
        ]
        return {"enum": lists}


_test_types = _TestTypes()


@dataclass(frozen=True, slots=True)
class _TestResults:
    """A non-empty mapping from types of test to ``normal`` or ``alterado``.

    Kept as a read-only mapping with the keys in the order of ``TEST_TYPES``:
    the order of the keys of a JSON object means nothing, so it is normalized
    and the JSON written does not depend on the caller.
    """

    def __call__(self, event_type: str, key: str, value: object) -> Mapping[str, str]:
        if not isinstance(value, Mapping) or not value:
            raise ValueError(
                f"{event_type}: payload {key} must be a non-empty object of results, got {value!r}"
            )
        for test, result in value.items():
            if not isinstance(test, str) or test not in TEST_TYPES:
                raise ValueError(
                    f"{event_type}: payload {key} must have types of {TEST_TYPES!r} as keys, "
                    f"got {test!r}"
                )
            if not isinstance(result, str) or result not in TEST_RESULTS:
                raise ValueError(
                    f"{event_type}: payload {key} must map each type to one of "
                    f"{TEST_RESULTS!r}, got {result!r} for {test!r}"
                )
        return MappingProxyType({t: value[t] for t in TEST_TYPES if t in value})

    def json_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "minProperties": 1,
            "properties": {test: {"enum": list(TEST_RESULTS)} for test in TEST_TYPES},
            "additionalProperties": False,
        }


_test_results = _TestResults()


CATALOG_V1: Mapping[str, EventSpec] = MappingProxyType(
    {
        "patient_arrived": _spec("admision"),
        "patient_registered": _spec("admision"),
        "triage_started": _spec("triaje", circuito=_choice(DOOR, NURSE)),
        "triage_completed": _spec("triaje", nivel=_int_range(1, 5)),
        "box_assigned": _spec("his", box=_BOX),
        "patient_displaced": _spec("his", box=_BOX, desalojado_por=_episode),
        "assessment_started": _spec("his", tipo=_TIPO, pool=_choice("medicos"), box=_BOX),
        "assessment_ended": _spec("his", tipo=_TIPO, interrumpida=_bool),
        "test_ordered": _spec("his"),
        "test_resulted": _spec("lab"),
        "disposition_decided": _spec("his", destino=_DESTINO),
        "patient_departed": _spec("his", destino=_DESTINO),
        "staffing_changed": _spec(
            "rrhh",
            patient=False,
            recurso=_choice("enfermeria_triaje", "medicos"),
            anterior=_int_range(0),
            nueva=_int_range(0),
        ),
    }
)
"""Version 1: the event types of milestone 3, in the order of the specification,
with the ``circuito`` of ``triage_started`` of task 4.1."""

CATALOG_V2: Mapping[str, EventSpec] = MappingProxyType(
    {
        **CATALOG_V1,
        "patient_arrived": _spec("admision", medio=_choice(*ARRIVAL_MODES)),
        "patient_registered": _spec("admision", edad=_int_range(0), sexo=_choice(*SEXES)),
        "triage_completed": _spec("triaje", nivel=_int_range(1, 5), motivo=_choice(*REASON_KEYS)),
        "test_ordered": _spec("his", pruebas=_test_types),
        "test_resulted": _spec("lab", resultados=_test_results),
    }
)
"""Version 2: version 1 plus the payloads of the clinical model (task 4.5a)."""

CATALOG_V3: Mapping[str, EventSpec] = MappingProxyType(
    {
        **CATALOG_V2,
        "box_released": _spec("his", box=_BOX, espera=_choice(RESULTS_WAIT)),
    }
)
"""Version 3: version 2 plus ``box_released`` (task 4.6a).

``box`` is the box the patient leaves and ``espera`` why: to wait for its
results, still inside (it has no ``patient_departed``). It comes right after
the ``test_ordered`` of the patient, in the same instant; with the results the
patient asks for a box again with its original priority (``box_assigned``).
"""

_DESTINO_V4 = _choice(*DESTINATIONS)
_SERVICIO = _choice(WARD)

CATALOG_V4: Mapping[str, EventSpec] = MappingProxyType(
    {
        **CATALOG_V3,
        "disposition_decided": _spec("his", destino=_DESTINO_V4),
        "patient_departed": _spec("his", destino=_DESTINO_V4),
        "patient_left_wbs": _spec("his", espera=_choice(*LWBS_WAITS)),
        "bed_requested": _spec("his", servicio=_SERVICIO),
        "bed_assigned": _spec("admision", servicio=_SERVICIO),
    }
)
"""Version 4: version 3 plus the outcome of milestone 5 (task 5.1, H5-7).

- ``patient_left_wbs``: the patience runs out before the first assessment;
  ``espera`` says where the patient was waiting (``LWBS_WAITS``). It closes the
  episode, without a decision.
- ``bed_requested``: in the instant of a ``disposition_decided`` with
  ``ingreso``; the patient keeps its box while it waits for the bed.
- ``bed_assigned``: when the bed is ready, followed by ``patient_departed`` in
  the same instant, in the box or, after a displacement, in the corridor.
- ``destino``: one of ``DESTINATIONS``.
"""

CATALOGS: Mapping[int, Mapping[str, EventSpec]] = MappingProxyType(
    {
        PROVISIONAL_SCHEMA_VERSION: CATALOG_V1,
        2: CATALOG_V2,
        CURRENT_CLINICAL_SCHEMA_VERSION: CATALOG_V3,
        OUTCOME_SCHEMA_VERSION: CATALOG_V4,
    }
)
"""The catalog of each schema version."""

SCHEMA_VERSIONS: frozenset[int] = frozenset(CATALOGS)
"""The schema versions a log can have: 1, 2, 3 and 4."""

TERMINAL_EVENTS: Mapping[int, frozenset[str]] = MappingProxyType(
    {
        PROVISIONAL_SCHEMA_VERSION: frozenset({"patient_departed"}),
        2: frozenset({"patient_departed"}),
        CURRENT_CLINICAL_SCHEMA_VERSION: frozenset({"patient_departed"}),
        OUTCOME_SCHEMA_VERSION: frozenset({"patient_departed", "patient_left_wbs"}),
    }
)
"""The event types that close an episode, for each schema version.

An episode is open at an instant if it has events before it and none of these
(docs/specs/hito-6.md, H6-11): the live mode publishes the warm-up of the open
episodes as its initial census. In versions 1 to 3 only ``patient_departed``
closes one; in version 4, also ``patient_left_wbs``.
"""

CATALOG = CATALOG_V1
"""The catalog of version 1, as before task 4.5a."""


def _check_schema_version(where: str, schema_version: object) -> int:
    # bool is a subclass of int in Python: True must not pass as 1.
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version not in SCHEMA_VERSIONS
    ):
        raise ValueError(
            f"{where}: schema_version must be one of {sorted(SCHEMA_VERSIONS)}, "
            f"got {schema_version!r}"
        )
    return schema_version


def _check_arrival_id(arrival_id: object) -> int:
    if (
        isinstance(arrival_id, bool)
        or not isinstance(arrival_id, int)
        or not 0 <= arrival_id <= MAX_ARRIVAL_ID
    ):
        raise ValueError(
            f"arrival_id must be an integer between 0 and {MAX_ARRIVAL_ID}, got {arrival_id!r}"
        )
    return arrival_id


def episode_id(arrival_id: int) -> str:
    """Episode identifier of an arrival: ``EP-`` and the number with six digits.

    Six digits allow 1,000,000 episodes per run (``arrival_id`` 0 to
    999,999): about 9 years at 300 arrivals a day. A longer run would need a
    new format, so it raises instead of writing seven digits.

    Raises:
        ValueError: If ``arrival_id`` is not an integer between 0 and 999,999.
    """
    return f"EP-{_check_arrival_id(arrival_id):06d}"


def patient_id(arrival_id: int) -> str:
    """Patient identifier of an arrival: ``PT-`` and the same number as the episode.

    Without return visits in milestone 3, a patient has one episode. The
    limit is the one of ``episode_id``.
    """
    return f"PT-{_check_arrival_id(arrival_id):06d}"


def _check_sim_time(where: str, sim_time: object) -> float:
    """``sim_time`` as a float if it is a finite number >= 0.

    The only check of ``sim_time``, used by ``EventLog.emit``, ``Event`` and
    ``event_time``. NaN and infinity cannot go into JSON (``allow_nan=False``
    would refuse them anyway) nor into a date.
    """
    if (
        isinstance(sim_time, bool)
        or not isinstance(sim_time, int | float)
        or (value := to_float(sim_time)) is None  # an int such as 10**400
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{where}: sim_time must be a finite number >= 0, got {sim_time!r}")
    return value


def _check_start_date(start_date: object) -> date:
    # datetime is a subclass of date: a date-time must not pass as a date.
    if not isinstance(start_date, date) or isinstance(start_date, datetime):
        raise ValueError(f"start_date must be a date without time, got {start_date!r}")
    return start_date


def event_time(start_date: date, sim_time: float) -> str:
    """Clock time of ``sim_time``, as ISO 8601 with milliseconds and ``+01:00``.

    The milliseconds are truncated, never rounded: ``floor(sim_time * 60000)``.
    Rounding could move an event at 23:59:59.9996 to the next day, or past an
    event that happened after it. From the floor on, everything is integer
    arithmetic, without adding floats in a ``timedelta``.

    Args:
        start_date: Date of minute 0, at 00:00 (``fecha_inicio`` of the
            arrival profile).
        sim_time: Minutes since then; a finite number >= 0.

    Returns:
        Such as ``"2026-01-05T12:19:01.200+01:00"`` for 739.02 minutes.

    Raises:
        ValueError: If ``start_date`` is not a date or ``sim_time`` is not a
            finite number >= 0.
    """
    start = datetime.combine(_check_start_date(start_date), time(), TIMEZONE)
    ms = math.floor(_check_sim_time("event_time", sim_time) * 60_000)
    return (start + timedelta(milliseconds=ms)).isoformat(timespec="milliseconds")


def _check_str(name: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string, got {value!r}")
    return value


@dataclass(frozen=True, slots=True)
class Event:
    """One event of the log: the common envelope and the payload.

    As ``CenterConfig``, an event can only exist valid: construction checks
    it against the catalog, whether it comes from ``EventLog.emit``, from
    ``read_events`` or is built directly. The payload is copied into a
    read-only mapping, so neither the event nor the caller's dict can change
    it later. Values in the payload are ``int``, ``str`` or ``bool``, which
    are immutable themselves, or, in version 2, a tuple of strings
    (``pruebas``) and a read-only mapping of strings (``resultados``).

    Events compare with ``==`` field by field, but are not hashable: the
    payload is a mapping. They pickle and deep-copy (see ``__reduce__``).

    Attributes:
        event_id: ``run_id``, a hyphen and the emission number with nine digits.
        event_type: A key of the catalog of ``schema_version``.
        schema_version: One of ``SCHEMA_VERSIONS``; it chooses the catalog.
        run_id: Identifier of the run, ``r`` and the seed by default.
        episode_id: Such as ``EP-000137``; ``None`` in resource events.
        patient_id: Such as ``PT-000137``, with the episode's number; ``None``
            in resource events.
        source_system: The one of the catalog for ``event_type``.
        sim_time: Minutes of simulation, a finite float >= 0.
        event_time: Clock time of ``sim_time`` (see ``event_time``).
        recorded_time: When it was recorded; equal to ``event_time`` until
            milestone 7.
        ingest_time: When it reached the broker; ``None`` until milestone 6.
        payload: Exactly the keys of the catalog of its version for ``event_type``.
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
        event_type = self.event_type
        catalog = CATALOGS[_check_schema_version(str(event_type), self.schema_version)]
        if not isinstance(event_type, str) or event_type not in catalog:
            raise ValueError(f"unknown event_type {event_type!r}")
        spec = catalog[event_type]

        _check_str("event_id", self.event_id)
        _check_str("run_id", self.run_id)
        _check_str("event_time", self.event_time)
        _check_str("recorded_time", self.recorded_time)
        if self.source_system != spec.source_system:
            raise ValueError(
                f"{event_type}: source_system must be {spec.source_system!r}, "
                f"got {self.source_system!r}"
            )
        if self.ingest_time is not None:
            raise ValueError(f"{event_type}: ingest_time must be null, got {self.ingest_time!r}")
        self._check_ids(spec)

        # The dataclass is frozen: object.__setattr__ is the standard way to
        # set fields during construction.
        object.__setattr__(self, "sim_time", _check_sim_time(event_type, self.sim_time))
        object.__setattr__(self, "payload", _check_payload(event_type, spec, self.payload))

    def _check_ids(self, spec: EventSpec) -> None:
        event_type = self.event_type
        if not spec.patient:
            if self.episode_id is not None or self.patient_id is not None:
                raise ValueError(f"{event_type}: episode_id and patient_id must be null")
            return
        if not isinstance(self.episode_id, str) or not _EPISODE.fullmatch(self.episode_id):
            raise ValueError(
                f"{event_type}: episode_id must be like 'EP-000137', got {self.episode_id!r}"
            )
        if not isinstance(self.patient_id, str) or not _PATIENT.fullmatch(self.patient_id):
            raise ValueError(
                f"{event_type}: patient_id must be like 'PT-000137', got {self.patient_id!r}"
            )
        if self.patient_id[3:] != self.episode_id[3:]:
            raise ValueError(
                f"{event_type}: patient_id {self.patient_id!r} does not match "
                f"episode_id {self.episode_id!r}"
            )

    def __reduce__(self):
        # pickle cannot handle a mappingproxy. Rebuild the event from its
        # fields, with the payload as a dict, so that it goes through
        # __post_init__ again (validation and the read-only copy).
        values = [getattr(self, f.name) for f in dataclasses.fields(self)]
        values[-1] = _plain(self.payload)
        return (Event, tuple(values))


def _check_payload(event_type: str, spec: EventSpec, payload: object) -> Mapping[str, object]:
    """Check the payload against the catalog and return a read-only copy."""
    if not isinstance(payload, Mapping):
        raise ValueError(f"{event_type}: payload must be a mapping, got {payload!r}")
    missing = sorted(spec.payload.keys() - payload.keys())
    unknown = sorted(str(k) for k in payload.keys() - spec.payload.keys())
    if missing or unknown:
        problems = []
        if missing:
            problems.append(f"missing payload keys: {', '.join(missing)}")
        if unknown:
            problems.append(f"unknown payload keys: {', '.join(unknown)}")
        raise ValueError(f"{event_type}: {'; '.join(problems)}")
    # In the order of the catalog, so the JSON does not depend on the caller.
    return MappingProxyType(
        {key: check(event_type, key, payload[key]) for key, check in spec.payload.items()}
    )


def _plain(value: object) -> object:
    """A payload value as plain JSON types: tuples as lists, mappings as dicts.

    The payload keeps containers immutable (a tuple, a read-only mapping), but
    neither ``json`` nor ``pickle`` handles a ``mappingproxy``. Scalars are
    returned as they are, so a payload without containers is unchanged.
    """
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, tuple | list):
        return [_plain(v) for v in value]
    return value


class EventSink(Protocol):
    """Where an ``EventLog`` puts its events."""

    def write(self, event: Event) -> None: ...


class MemorySink:
    """Keeps the events in a list, for tests and notebooks.

    Attributes:
        events: The events, in emission order.
    """

    def __init__(self) -> None:
        self.events: list[Event] = []

    def write(self, event: Event) -> None:
        self.events.append(event)


class JsonlSink:
    """Writes the events to a JSONL file, one line per event, in UTF-8.

    Use it as a context manager: the file is created (or overwritten) on
    entering the ``with`` and closed on leaving it::

        with JsonlSink("eventos.jsonl") as sink:
            log = EventLog("r2026", start_date, sink)
            ...

    Args:
        path: Path of the file.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._file: TextIO | None = None

    def __enter__(self) -> Self:
        # newline="\n": the same bytes on every system.
        self._file = self.path.open("w", encoding="utf-8", newline="\n")
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def write(self, event: Event) -> None:
        if self._file is None:
            raise RuntimeError(f"JsonlSink({str(self.path)!r}) must be used inside a with block")
        self._file.write(to_json(event) + "\n")


class EventLog:
    """Builds the events of one run and passes them to a sink.

    It fills in what does not depend on the caller: ``event_id``,
    ``schema_version``, ``source_system`` from the catalog, the identifiers
    from ``arrival_id`` and the clock times from ``sim_time``. Every event of
    the log has its ``schema_version`` and is checked with its catalog.

    Args:
        run_id: Identifier of the run, such as ``"r2026"``.
        start_date: Date of minute 0, at 00:00 (``fecha_inicio``).
        sink: ``MemorySink``, ``JsonlSink`` or anything with ``write(event)``.
        schema_version: Version of the log, one of ``SCHEMA_VERSIONS``:
            ``PROVISIONAL_SCHEMA_VERSION`` (1) by default, or
            ``CURRENT_CLINICAL_SCHEMA_VERSION`` (3) for the clinical model
            of milestone 4, ``OUTCOME_SCHEMA_VERSION`` (4) for the one of
            milestone 5; 2 is the clinical version of tasks 4.5a and 4.5b.

    Raises:
        ValueError: If ``run_id`` is not a non-empty string, ``start_date``
            is not a date without time, or ``schema_version`` is not a
            version of ``SCHEMA_VERSIONS``.
    """

    def __init__(
        self,
        run_id: str,
        start_date: date,
        sink: EventSink,
        *,
        schema_version: int = PROVISIONAL_SCHEMA_VERSION,
    ) -> None:
        self.run_id = _check_str("run_id", run_id)
        self.start_date = _check_start_date(start_date)
        self.schema_version = _check_schema_version("EventLog", schema_version)
        self._catalog = CATALOGS[self.schema_version]
        self.sink = sink
        self._next_number = 0
        self._last_time = 0.0

    def emit(
        self, event_type: str, sim_time: float, *, arrival_id: int | None = None, **payload: object
    ) -> Event:
        """Build the next event, pass it to the sink and return it.

        Everything is checked before anything is written: an event that fails
        uses no number and does not move the clock of the log.

        Args:
            event_type: A key of the catalog of the log's version.
            sim_time: Minutes of simulation, such as SimPy's ``env.now``; not
                less than the previous event's.
            arrival_id: Arrival of the patient, for patient events; must be
                ``None`` for resource events.
            **payload: Exactly the payload keys of the log's catalog for the type.

        Returns:
            The event.

        Raises:
            ValueError: If the type is unknown, ``arrival_id`` is missing,
                extra or invalid, ``sim_time`` is not a finite number >= 0, or
                the payload does not match the catalog.
            RuntimeError: If ``sim_time`` is less than the previous event's,
                or the run already has 10**9 events. Both are broken internal
                rules of the engine, not wrong inputs.
        """
        if not isinstance(event_type, str) or event_type not in self._catalog:
            raise ValueError(f"unknown event_type {event_type!r}")
        spec = self._catalog[event_type]

        if spec.patient:
            if arrival_id is None:
                raise ValueError(f"{event_type}: patient events need an arrival_id")
            try:
                episode, patient = episode_id(arrival_id), patient_id(arrival_id)
            except ValueError as e:
                raise ValueError(f"{event_type}: {e}") from None
        else:
            if arrival_id is not None:
                raise ValueError(f"{event_type}: resource events take no arrival_id")
            episode = patient = None

        sim_time = _check_sim_time(event_type, sim_time)
        if sim_time < self._last_time:
            raise RuntimeError(
                f"{event_type}: sim_time decreased: {sim_time!r} after {self._last_time!r}"
            )
        if self._next_number >= _MAX_EVENTS:
            raise RuntimeError(f"no event_id left: a run has at most {_MAX_EVENTS} events")

        clock = event_time(self.start_date, sim_time)
        event = Event(
            event_id=f"{self.run_id}-{self._next_number:09d}",
            event_type=event_type,
            schema_version=self.schema_version,
            run_id=self.run_id,
            episode_id=episode,
            patient_id=patient,
            source_system=spec.source_system,
            sim_time=sim_time,
            event_time=clock,
            recorded_time=clock,
            ingest_time=None,
            payload=payload,
        )
        self.sink.write(event)
        self._next_number += 1
        self._last_time = sim_time
        return event


_ENVELOPE = tuple(f.name for f in dataclasses.fields(Event))


def to_json(event: Event) -> str:
    """One line of JSONL: the envelope in its order, without a final newline.

    ``ensure_ascii=False`` keeps accents readable, and ``allow_nan=False``
    refuses NaN and infinity, which are not JSON. ``sim_time`` is written with
    the shortest repr of the float, which reads back to the same bits.
    """
    data = {name: getattr(event, name) for name in _ENVELOPE}
    data["payload"] = _plain(event.payload)
    return json.dumps(data, ensure_ascii=False, allow_nan=False)


def from_json(line: str) -> Event:
    """Parse one line of JSONL into a validated ``Event``.

    Raises:
        ValueError: If the line is not a JSON object with exactly the
            envelope keys, or the event does not match the catalog.
    """
    data = json.loads(line)
    if not isinstance(data, dict):
        raise ValueError(f"an event must be a JSON object, got {data!r}")
    missing = [k for k in _ENVELOPE if k not in data]
    unknown = sorted(data.keys() - set(_ENVELOPE))
    if missing or unknown:
        problems = []
        if missing:
            problems.append(f"missing keys: {', '.join(missing)}")
        if unknown:
            problems.append(f"unknown keys: {', '.join(unknown)}")
        raise ValueError(f"envelope: {'; '.join(problems)}")
    return Event(**_upgrade(data))


def _upgrade(data: dict) -> dict:
    """Fill in what logs of version 1 written before task 4.1 do not have.

    Their ``triage_started`` has no ``circuito``: every triage went through a
    nurse then, so the value is ``NURSE``. Only reading tolerates it;
    ``EventLog.emit`` and ``Event`` still require the key. The version stays
    1 (docs/specs/hito-4.md, task 4.1). A log of version 2 or 3 was always
    written with ``circuito``, so it is never upgraded.
    """
    payload = data["payload"]
    if (
        data["schema_version"] == PROVISIONAL_SCHEMA_VERSION
        and not isinstance(data["schema_version"], bool)
        and data["event_type"] == "triage_started"
        and isinstance(payload, dict)
        and "circuito" not in payload
    ):
        data = {**data, "payload": {**payload, "circuito": NURSE}}
    return data


def read_events(path: str | Path) -> Iterator[Event]:
    """Read a JSONL log lazily, one validated ``Event`` per line.

    Args:
        path: Path of the file, such as one written by ``JsonlSink``.

    Yields:
        The events in file order.

    Each event is validated with the catalog of its own ``schema_version``;
    a file that mixes versions reads, and the invariant ``schema_version``
    reports it.

    Raises:
        ValueError: While iterating, at the first line that is not a valid
            event; the message starts with ``path:line``.
    """
    path = Path(path)
    with path.open(encoding="utf-8") as f:
        for number, line in enumerate(f, start=1):
            try:
                event = from_json(line)
            except ValueError as e:
                raise ValueError(f"{path}:{number}: {e}") from e
            yield event
