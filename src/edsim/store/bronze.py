"""From a Kafka message to a row of the bronze layer, without connecting to anything.

Bronze keeps what arrives as it came (docs/specs/hito-7.md, piece 3, H7-7). A message of the
event topics becomes a row of ``bronce.eventos``: the envelope in columns, the ``payload`` as
JSON and the message itself in ``valor``. A message of ``ed.runs`` becomes a row of
``bronce.ejecuciones``. What cannot be read goes to ``bronce.rechazados`` with the reason.

**Not the catalog.** What is recorded has fields set to ``null`` and events of its own, such
as ``record_corrected``, that ``Event`` would reject. A row only needs the keys that fill its
columns, with the types of the columns; any other key stays in ``valor``, untouched.

**Nothing that breaks the INSERT.** The consumer saves a batch in one transaction: a value
Postgres refuses would roll the batch back, and the consumer would read it again forever. So
everything Postgres is known to refuse goes to ``rechazados`` here: an integer out of
``integer``, NaN and infinity (``json.loads`` accepts them), the NUL character and lone
surrogates (neither ``text`` nor ``jsonb`` take them), invalid UTF-8 and times without a time
zone (``timestamptz`` would read them in the session's zone). What nobody foresaw is caught
by the safety net of ``edsim.store.consumer``.

**The arrival time** is the ``LogAppendTime`` timestamp of the message, set by the broker
(H6-9): ``ingest_time`` in the value is ignored. A message with another kind of timestamp
means the topic is misconfigured, and that stops the consumer (``TimestampTypeError``).

Standard library only.
"""

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from edsim.live.topics import RUNS

LOG_APPEND_TIME = 2
"""``confluent_kafka.TIMESTAMP_LOG_APPEND_TIME``, which this module cannot import (a test of
the integration checks that they are equal)."""

MAX_INTEGER = 2**31 - 1
"""The largest value of a Postgres ``integer``."""

MAX_BIGINT = 2**63 - 1
"""The largest value of a Postgres ``bigint``."""

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

_TEXT_KEYS = ("event_id", "event_type", "run_id", "source_system")
_OPTIONAL_TEXT_KEYS = ("episode_id", "patient_id")
_TIME_KEYS = ("event_time", "recorded_time")
REQUIRED_KEYS = (
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
    "payload",
)
"""The keys of the envelope a row of ``bronce.eventos`` needs; ``ingest_time`` is not one."""

RUN_TYPES = ("inicio", "fin")


@dataclass(frozen=True, slots=True)
class KafkaMessage:
    """What bronze takes from a Kafka message: its coordinates, its timestamp and its value.

    Attributes:
        topic: The topic.
        partition: The partition.
        offset: The offset in the partition.
        timestamp_type: The kind of timestamp, as ``Message.timestamp()[0]``.
        timestamp_ms: Milliseconds since the epoch, as ``Message.timestamp()[1]``.
        value: The value, as it came; ``None`` if it has none.
    """

    topic: str
    partition: int
    offset: int
    timestamp_type: int
    timestamp_ms: int
    value: bytes | None


@dataclass(frozen=True, slots=True)
class EventRow:
    """A row of ``bronce.eventos``; the columns in the order of the table."""

    event_id: str
    event_type: str
    schema_version: int
    run_id: str
    episode_id: str | None
    patient_id: str | None
    source_system: str
    sim_time: float
    event_time: datetime
    recorded_time: datetime
    ingest_time: datetime
    payload: str
    kafka_topic: str
    kafka_particion: int
    kafka_offset: int
    valor: str


@dataclass(frozen=True, slots=True)
class RunRow:
    """A row of ``bronce.ejecuciones``: an ``inicio`` or a ``fin`` of ``ed.runs``."""

    run_id: str
    tipo: str
    mensaje: str
    ingest_time: datetime
    kafka_offset: int


@dataclass(frozen=True, slots=True)
class RejectedRow:
    """A row of ``bronce.rechazados``: a message that cannot be read, and why."""

    valor: str
    motivo: str
    kafka_topic: str
    kafka_particion: int
    kafka_offset: int
    ingest_time: datetime


Row = EventRow | RunRow | RejectedRow


class TimestampTypeError(RuntimeError):
    """A message whose timestamp is not ``LogAppendTime``: the topic is misconfigured."""

    def __init__(self, message: KafkaMessage) -> None:
        self.message = message
        super().__init__(
            f"el mensaje {message.topic}[{message.partition}]@{message.offset} no lleva la marca "
            f"LogAppendTime del broker (tipo {message.timestamp_type}): el topic está mal "
            "configurado; «edsim directo preparar» comprueba la marca de los topics"
        )


class _Unreadable(ValueError):
    """Why a value cannot go to bronze; the text is the ``motivo``."""


def ingest_time(message: KafkaMessage) -> datetime:
    """The arrival time of ``message``: its ``LogAppendTime`` timestamp, in UTC.

    The milliseconds are added to the epoch as an integer ``timedelta``, without going through
    a float of seconds.

    Raises:
        TimestampTypeError: If the timestamp is not ``LogAppendTime``.
    """
    if message.timestamp_type != LOG_APPEND_TIME:
        raise TimestampTypeError(message)
    return _EPOCH + timedelta(milliseconds=message.timestamp_ms)


def to_row(message: KafkaMessage) -> Row:
    """The row of bronze for ``message``: an event, a message of ``ed.runs`` or a rejection.

    Raises:
        TimestampTypeError: If the timestamp is not ``LogAppendTime``; it is checked first,
            for every message.
    """
    arrival = ingest_time(message)
    try:
        text, data = _decode(message.value)
        if message.topic == RUNS:
            return _run_row(message, arrival, data)
        return _event_row(message, arrival, text, data)
    except _Unreadable as reason:
        return RejectedRow(
            valor=printable(message.value),
            motivo=str(reason),
            kafka_topic=message.topic,
            kafka_particion=message.partition,
            kafka_offset=message.offset,
            ingest_time=arrival,
        )


def printable(value: bytes | None) -> str:
    """``value`` as text that a ``text`` column takes: invalid UTF-8 and NUL, escaped."""
    if value is None:
        return ""
    return value.decode("utf-8", "backslashreplace").replace("\x00", "\\x00")


def _reject_constant(name: str) -> object:
    raise _Unreadable(f"{name} no es JSON")


def _decode(value: bytes | None) -> tuple[str, dict]:
    if value is None:
        raise _Unreadable("mensaje sin valor")
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError as error:
        raise _Unreadable(f"no es UTF-8 ({error.reason} en el byte {error.start})") from None
    try:
        data = json.loads(text, parse_constant=_reject_constant)
    except ValueError as error:
        if isinstance(error, _Unreadable):
            raise
        raise _Unreadable(f"JSON roto: {error}") from None
    if not isinstance(data, dict):
        raise _Unreadable(f"no es un objeto JSON, sino {type(data).__name__}")
    _check_strings(data)
    return text, data


def _check_strings(value: object) -> None:
    """Refuse the characters Postgres does not store: NUL and lone surrogates, in any string."""
    if isinstance(value, str):
        if "\x00" in value:
            raise _Unreadable("lleva el carácter NUL (\\u0000), que Postgres no guarda")
        if any("\ud800" <= char <= "\udfff" for char in value):
            raise _Unreadable("lleva un sustituto UTF-16 suelto, que Postgres no guarda")
    elif isinstance(value, dict):
        for key, item in value.items():
            _check_strings(key)
            _check_strings(item)
    elif isinstance(value, list):
        for item in value:
            _check_strings(item)
    elif isinstance(value, float) and not math.isfinite(value):
        # 1e400 is valid JSON and reads as infinity.
        raise _Unreadable(f"lleva un número que no es finito ({value})")


def _event_row(message: KafkaMessage, arrival: datetime, text: str, data: dict) -> EventRow:
    missing = [key for key in REQUIRED_KEYS if key not in data]
    if missing:
        raise _Unreadable(f"sobre incompleto: faltan {', '.join(missing)}")
    for key in _TEXT_KEYS:
        if not isinstance(data[key], str) or not data[key]:
            raise _Unreadable(f"{key} debe ser un texto no vacío, no {data[key]!r}")
    for key in _OPTIONAL_TEXT_KEYS:
        if data[key] is not None and not isinstance(data[key], str):
            raise _Unreadable(f"{key} debe ser un texto o null, no {data[key]!r}")
    version = data["schema_version"]
    if isinstance(version, bool) or not isinstance(version, int) or not 1 <= version <= MAX_INTEGER:
        raise _Unreadable(f"schema_version debe ser un entero de 1 a {MAX_INTEGER}, no {version!r}")
    payload = data["payload"]
    if not isinstance(payload, dict):
        raise _Unreadable(f"payload debe ser un objeto, no {payload!r}")
    return EventRow(
        event_id=data["event_id"],
        event_type=data["event_type"],
        schema_version=version,
        run_id=data["run_id"],
        episode_id=data["episode_id"],
        patient_id=data["patient_id"],
        source_system=data["source_system"],
        sim_time=_finite(data["sim_time"]),
        event_time=_time(data, "event_time"),
        recorded_time=_time(data, "recorded_time"),
        ingest_time=arrival,
        payload=json.dumps(payload, ensure_ascii=False, allow_nan=False),
        kafka_topic=message.topic,
        kafka_particion=message.partition,
        kafka_offset=message.offset,
        valor=text,
    )


def _finite(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _Unreadable(f"sim_time debe ser un número, no {value!r}")
    try:
        number = float(value)
    except OverflowError:
        raise _Unreadable(f"sim_time no cabe en un double: {value}") from None
    if not math.isfinite(number):
        raise _Unreadable(f"sim_time debe ser finito, no {value!r}")
    return number


def _time(data: dict, key: str) -> datetime:
    value = data[key]
    if not isinstance(value, str):
        raise _Unreadable(f"{key} debe ser una hora ISO 8601, no {value!r}")
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise _Unreadable(f"{key} no se interpreta como hora ISO 8601: {value!r}") from None
    if moment.tzinfo is None:
        raise _Unreadable(f"{key} no lleva zona horaria: {value!r}")
    return moment


def _run_row(message: KafkaMessage, arrival: datetime, data: dict) -> RunRow:
    kind = data.get("tipo")
    if kind not in RUN_TYPES:
        raise _Unreadable(f"un mensaje de {RUNS} tiene tipo inicio o fin, no {kind!r}")
    run_id = data.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise _Unreadable(f"run_id debe ser un texto no vacío, no {run_id!r}")
    if kind == "fin":
        published = data.get("publicados")
        if (
            isinstance(published, bool)
            or not isinstance(published, int)
            or not 0 <= published <= MAX_BIGINT
        ):
            raise _Unreadable(f"el fin necesita publicados, un entero >= 0, no {published!r}")
    return RunRow(
        run_id=run_id,
        tipo=kind,
        mensaje=json.dumps(data, ensure_ascii=False, allow_nan=False),
        ingest_time=arrival,
        kafka_offset=message.offset,
    )
