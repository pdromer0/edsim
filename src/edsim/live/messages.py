"""The messages of ``ed.runs`` and ``ed.control`` (docs/specs/hito-6.md, H6-7).

``ed.runs`` carries one ``inicio`` and one ``fin`` per run published: with
them, a consumer knows the catalog version it will read and where the census
ends. ``ed.control`` carries the orders to a live run. Both have their own
format, versioned apart from the catalog (``"version": 1``), and their keys
and values are in Spanish, as the specification and the configuration.

The text is written as ``to_json`` writes an event: ``ensure_ascii=False``
and ``allow_nan=False``, with the keys in the order of the specification.
Their JSON Schema is written by hand in ``schemas/ed-runs-v1.schema.json`` and
``schemas/ed-control-v1.schema.json``.

Standard library only: no Kafka client.
"""

import json
from collections.abc import Callable, Mapping
from types import MappingProxyType

from edsim.live.control import ORDERS, SPEED, Command
from edsim.live.directo import RunEnd, RunStart

FORMAT_VERSION = 1
"""Version of the format of the messages of ``ed.runs`` and ``ed.control``."""

START = "inicio"
END = "fin"

KNOWN_CONTROL_DIFFERENCES: Mapping[str, str] = MappingProxyType(
    {
        "run-id-ajeno": (
            "Una orden de otro run_id es válida para el esquema; parse_control la ignora "
            "sin aviso, porque no es para esta ejecución."
        ),
    }
)
"""Where ``parse_control`` and ``schemas/ed-control-v1.schema.json`` disagree, on purpose.

Everything else they decide the same: a test passes one collection of messages
through both. A ``version`` written ``1.0`` is valid for both: in JSON Schema
2020-12 a number with a zero fractional part is an integer, and ``parse_control``
compares the number.
"""


def _dumps(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, allow_nan=False)


def run_start_json(message: RunStart) -> str:
    """The ``inicio`` of ``ed.runs``, one line of JSON without a final newline.

    ``velocidad`` is a number or ``"max"``; ``inicio_directo`` and
    ``horizonte`` are simulated minutes.
    """
    info = message.info
    return _dumps(
        {
            "tipo": START,
            "version": FORMAT_VERSION,
            "run_id": info.run_id,
            "modo": info.mode,
            "schema_version": info.schema_version,
            "semilla": info.seed,
            "fecha_inicio": info.start_date.isoformat(),
            "inicio_directo": message.live_start,
            "horizonte": message.horizon,
            "velocidad": message.speed,
            "anclado": info.anchored,
            "censo": {"episodios": message.census_episodes, "eventos": message.census_events},
        }
    )


def run_end_json(message: RunEnd) -> str:
    """The ``fin`` of ``ed.runs``, one line of JSON without a final newline.

    ``ultimo_event_id`` is ``null`` if nothing was published.
    """
    return _dumps(
        {
            "tipo": END,
            "version": FORMAT_VERSION,
            "run_id": message.run_id,
            "motivo": message.reason,
            "sim_time": message.sim_time,
            "ultimo_event_id": message.last_event_id,
            "publicados": message.published,
        }
    )


def control_json(run_id: str, command: Command) -> str:
    """An order to the run ``run_id`` for ``ed.control``; ``valor`` only with ``velocidad``."""
    data: dict[str, object] = {"version": FORMAT_VERSION, "run_id": run_id, "orden": command.order}
    if command.order == SPEED:
        data["valor"] = command.value
    return _dumps(data)


def parse_control(
    text: bytes | str, run_id: str, on_invalid: Callable[[str], None]
) -> Command | None:
    """The order in a message of ``ed.control``, if it is for ``run_id``.

    The checks go in this order: UTF-8, JSON, an object, its ``run_id`` (a
    non-empty string; if it is another run's, the message is not for this one
    and is ignored without a warning, whatever else it holds), ``version`` 1,
    exactly the keys of the order (``valor`` only with ``velocidad``) and the
    order itself (``Command``).

    Args:
        text: The value of the message, bytes in UTF-8 or text.
        run_id: The run that reads.
        on_invalid: Called with the reason when the message is invalid; the
            run goes on.

    Returns:
        The ``Command``, or ``None`` if the message is another run's or invalid.
    """

    def invalid(reason: str) -> None:
        on_invalid(f"invalid message in ed.control: {reason}")

    if isinstance(text, bytes | bytearray):
        try:
            text = bytes(text).decode("utf-8")
        except UnicodeDecodeError as exc:
            return invalid(f"not UTF-8 ({exc})")
    try:
        data = json.loads(text)
    except ValueError as exc:
        return invalid(f"not JSON ({exc})")
    if not isinstance(data, dict):
        return invalid(f"not a JSON object: {text!r}")

    owner = data.get("run_id")
    if not isinstance(owner, str) or not owner:
        return invalid(f"run_id must be a non-empty string, got {owner!r}")
    if owner != run_id:
        return None

    version = data.get("version")
    if isinstance(version, bool) or version != FORMAT_VERSION:
        return invalid(f"unknown version {version!r}")
    order = data.get("orden")
    if not isinstance(order, str) or order not in ORDERS:
        return invalid(f"orden must be one of {list(ORDERS)}, got {order!r}")
    expected = {"version", "run_id", "orden"} | ({"valor"} if order == SPEED else set())
    if data.keys() != expected:
        missing = sorted(expected - data.keys())
        unknown = sorted(data.keys() - expected)
        return invalid(f"{order}: missing keys {missing}, unknown keys {unknown}")
    try:
        return Command(order, data.get("valor"))
    except ValueError as exc:
        return invalid(str(exc))
