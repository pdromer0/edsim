"""The texts of a live run in the terminal, in Spanish as the rest of the CLI.

``edsim directo lanzar`` and ``reemitir`` print the census when the run is announced,
a status line every 10 real seconds and a summary at the end.
"""

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
