"""Initial census of a live run: the warm-up events the live stream still needs.

A live run warms up without publishing, from minute 0 to its start ``W``, and
then publishes in real time. A consumer that starts at ``W`` would see patients
already inside without their arrival, so before going live the run publishes
the **census**: the warm-up events of the episodes still open at ``W`` and
every resource event of the warm-up (the staff in force), in their original
order (docs/specs/hito-6.md, piece 6, H6-11). It is made of events of the log,
not of a summary of the state: no new contract, valid for any version of the
catalog, and the consumer derives the state with the same code for the census
and for the live stream.

The instant ``W`` splits the log: events with ``sim_time < W`` are the warm-up
and those with ``sim_time >= W`` are live. A patient who leaves exactly at
``W`` is open: its departure is live. ``census`` followed by ``live_events``
is the log without the warm-up of the closed episodes (piece 7).

Pure functions over events: no SimPy, no engine and no Kafka client.
"""

import math
import numbers
from collections.abc import Iterable

from edsim.engine.events import TERMINAL_EVENTS, Event


def _check_start(start: object) -> float:
    # bool is a subclass of int in Python; NaN would leave every event out without a word.
    if isinstance(start, bool) or not isinstance(start, numbers.Real) or math.isnan(start):
        raise ValueError(f"start must be a number of minutes, got {start!r}")
    return float(start)


def open_episodes(events: Iterable[Event], start: float) -> frozenset[str]:
    """Episodes open at ``start``: with some event before it and no terminal event before it.

    The terminal events are those of ``TERMINAL_EVENTS`` for the version of
    each event. Events at ``start`` or later are ignored.

    Raises:
        ValueError: If ``start`` is not a number or is NaN.
    """
    start = _check_start(start)
    seen: set[str] = set()
    closed: set[str] = set()
    for event in events:
        if event.episode_id is None or not event.sim_time < start:
            continue
        seen.add(event.episode_id)
        if event.event_type in TERMINAL_EVENTS[event.schema_version]:
            closed.add(event.episode_id)
    return frozenset(seen - closed)


def census(events: Iterable[Event], start: float) -> list[Event]:
    """The census at ``start``: the warm-up events of the open episodes and of the resources.

    Every event with ``sim_time < start`` whose episode is open at ``start``
    (``open_episodes``) or that has no episode, in the original order.

    Raises:
        ValueError: If ``start`` is not a number or is NaN.
    """
    events = list(events)  # read twice: once for the open episodes, once to filter
    still_open = open_episodes(events, start)
    return [
        e
        for e in events
        if e.sim_time < start and (e.episode_id is None or e.episode_id in still_open)
    ]


def live_events(events: Iterable[Event], start: float) -> list[Event]:
    """The events of the live stream: those with ``sim_time >= start``, in the original order.

    Raises:
        ValueError: If ``start`` is not a number or is NaN.
    """
    start = _check_start(start)
    return [e for e in events if e.sim_time >= start]
