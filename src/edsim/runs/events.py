"""Index episode locations cheaply; validate events only when reading a card."""

import json
from array import array
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np
from numpy.typing import NDArray

from edsim.engine.events import Event, from_json
from edsim.runs.results import RunReadError
from edsim.runs.store import RunStore


@dataclass(frozen=True, slots=True)
class EpisodeEventIndex:
    """Read-only uint64 rows (byte offset, physical line number) per episode."""

    run_id: str
    positions: Mapping[str, NDArray[np.uint64]]


def build_episode_event_index(store: RunStore, run_id: str) -> EpisodeEventIndex:
    """Locate episodes in one binary pass, without constructing validated Events.

    Offsets count the original UTF-8 bytes including LF or CRLF. Line numbers
    start at one and include resource events. Blank lines are invalid events,
    as with read_events. Only JSON and identifier field types are checked here;
    full catalog and run/episode validation belongs to read_episode_events.
    """
    path = store.root / run_id / "eventos.jsonl"
    number = 0
    locations: dict[str, array] = {}
    try:
        with store._file(run_id, "eventos.jsonl").open("rb") as source:
            while True:
                offset = source.tell()
                raw = source.readline()
                if not raw:
                    break
                number += 1
                data = json.loads(raw.decode("utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("event JSON must be an object")
                episode = data["episode_id"]
                if not isinstance(data["run_id"], str) or (
                    episode is not None and not isinstance(episode, str)
                ):
                    raise ValueError("invalid run_id or episode_id field type")
                if episode is not None:
                    if episode not in locations:
                        locations[episode] = array("Q")
                    locations[episode].extend((offset, number))
    except (OSError, ValueError, KeyError) as error:
        where = str(path) if not number else f"{path}:{number}"
        raise RunReadError(f"{where}: {error}") from error
    # Immutable bytes backing prevents callers from enabling write access again.
    positions = {
        episode: np.frombuffer(packed.tobytes(), dtype=np.uint64).reshape(-1, 2)
        for episode, packed in locations.items()
    }
    return EpisodeEventIndex(run_id, MappingProxyType(positions))


def read_episode_events(
    store: RunStore, run_id: str, episode_id: str, index: EpisodeEventIndex
) -> tuple[Event, ...]:
    """Seek and validate only one episode's lines, in their original log order.

    Raises KeyError for an episode absent from the index, and RunReadError for
    read failures or lines that no longer belong to the requested run/episode.
    Runs are immutable; callers cache the index by the metadata fingerprint.
    """
    path = store.root / run_id / "eventos.jsonl"
    if index.run_id != run_id:
        raise RunReadError(f"{path}: index belongs to run {index.run_id!r}")
    positions = index.positions[episode_id]
    number = None
    events = []
    try:
        with store._file(run_id, "eventos.jsonl").open("rb") as source:
            for offset, line_number in positions:
                number = int(line_number)
                source.seek(int(offset))
                event = from_json(source.readline().decode("utf-8"))
                if event.run_id != run_id or event.episode_id != episode_id:
                    raise ValueError("indexed event does not match run or episode")
                events.append(event)
    except (OSError, ValueError) as error:
        where = str(path) if number is None else f"{path}:{number}"
        raise RunReadError(f"{where}: {error}") from error
    return tuple(events)
