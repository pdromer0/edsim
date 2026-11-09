"""The texts of a live run in the terminal, in Spanish as the rest of the CLI.

``edsim directo lanzar`` and ``reemitir`` print the census when the run is announced,
a status line every 10 real seconds and a summary at the end; with Kafka, a warning when
the connection with the broker is lost and when it is back, and what librdkafka wrote.
"""

from collections import Counter
from collections.abc import Mapping
from pathlib import Path

from edsim.live.control import MAX_SPEED
from edsim.live.directo import RunEnd, RunStart
from edsim.live.status import LiveStatus


def format_speed(speed: float | str) -> str:
    """``×60``, ``×2.5`` or ``máxima``."""
    return "máxima" if speed == MAX_SPEED else f"×{speed:g}"


def format_status(status: LiveStatus) -> str:
    """One status line: time since the start of the live stream, simulated time, speed,
    published, delay of the pacer and, with a broker, pending messages."""
    parts = [
        f"+{status.elapsed:.0f} s",
        f"{status.event_time} (minuto {status.sim_time:.1f})",
        "en pausa" if status.paused else format_speed(status.speed),
        f"{status.published} publicados",
        f"retraso {status.lag * 1000:.1f} ms",
    ]
    if status.pending is not None:
        parts.append(f"{status.pending} pendientes")
    return " · ".join(parts)


def format_census(start: RunStart) -> str:
    """The census, when the run is announced."""
    return (
        f"Censo en W = {start.live_start:g} min: {start.census_episodes} episodios abiertos,"
        f" {start.census_events} eventos; empieza el directo"
    )


def format_end(start: RunStart | None, end: RunEnd) -> str:
    """The summary of the end: reason, published (census and live), minute and last event."""
    published = f"{end.published} publicados"
    if start is not None:
        census = min(end.published, start.census_events)
        published += f" ({census} de censo y {end.published - census} en directo)"
    return (
        f"Fin · motivo {end.reason} · {published} · minuto {end.sim_time:g}"
        f" · último event_id {end.last_event_id or '—'}"
    )


# --- Kafka: the connection and what librdkafka wrote (task 6.6) ------------------------


def format_broker_lost(bootstrap: str, detail: str) -> str:
    """The warning when the connection with the broker is lost."""
    return (
        f"se perdió la conexión con Kafka en {bootstrap} ({detail}); librdkafka reintenta"
        " solo y los eventos esperan en la cola del productor"
    )


def format_broker_back(bootstrap: str, seconds: float) -> str:
    """The warning when every client is connected again."""
    return f"Kafka en {bootstrap} vuelve a responder tras {seconds:.0f} s"


def format_kafka_error(client: str, name: str, detail: str) -> str:
    """The warning of the first error of a code that is not of a lost connection."""
    return (
        f"error de Kafka en el cliente {client}: {name} ({detail});"
        " los repetidos se cuentan al final"
    )


def format_kafka_log_summary(
    lines: Mapping[tuple[str, str], int],
    first_lines: Mapping[tuple[str, str], str],
    errors: Mapping[tuple[str, str], int],
    log_path: Path | None,
) -> str | None:
    """What librdkafka wrote during a command, for its end; ``None`` if nothing.

    The count by client, by type of line and by error code, and the first line of each
    type, so that a rare one is not hidden behind a number.
    """
    if not lines and not errors:
        return None
    by_client: Counter[str] = Counter()
    for (client, _), n in lines.items():
        by_client[client] += n
    total = sum(by_client.values())
    head = f"librdkafka: {total} líneas"
    if by_client:
        head += " (" + ", ".join(f"{c} {n}" for c, n in by_client.most_common()) + ")"
    if errors:
        by_code: Counter[str] = Counter()
        for (_, code), n in errors.items():
            by_code[code] += n
        head += (
            f"; {sum(by_code.values())} errores ("
            + ", ".join(f"{code} {n}" for code, n in by_code.most_common())
            + ")"
        )
    head += (
        f"; todas en {log_path}"
        if log_path is not None
        else "; para guardarlas, --registro-kafka FICHERO"
    )
    detail = [
        f"  {client} · {kind} × {n}: {first_lines[client, kind]}"
        for (client, kind), n in sorted(lines.items(), key=lambda item: -item[1])
    ]
    return "\n".join([head, *detail])
