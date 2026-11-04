"""Replay resource cache and per-run presentation state, independent of widgets."""

import math
import time
from dataclasses import dataclass

import streamlit as st

from edsim.runs import ReplayIndex, RunStore, build_replay_index

Identity = tuple[str, str, str]


@dataclass
class ReplayPosition:
    """Retain position and clock anchors outside navigation-cleaned widget state."""

    time: float = 0.0
    speed: int = 1
    highlighted_episode: str | None = None
    playing: bool = False
    origin: int = 0
    started_at: float = 0.0


def clock() -> float:
    """Use elapsed monotonic seconds; tests replace this clock without sleeping."""
    return time.monotonic()


@st.cache_resource(max_entries=4, show_spinner="Leyendo y validando el índice del replay…")
def cached_replay_index(root: str, run_id: str, fingerprint: str) -> ReplayIndex:
    """Share an immutable index by catalog and exact run.json fingerprint."""
    return build_replay_index(RunStore(root), run_id)


def replay_position(identity: Identity) -> ReplayPosition:
    """Restore each immutable run's own position, speed and highlight."""
    return st.session_state.setdefault("replay_positions", {}).setdefault(
        identity, ReplayPosition()
    )


def pause_replays_except(run_id: str | None) -> None:
    """Leaving Replay or changing runs pauses without counting time away."""
    for identity, position in st.session_state.get("replay_positions", {}).items():
        if identity[1] != run_id:
            position.playing = False


def step_position(position: ReplayPosition, amount: int, horizon: float) -> None:
    """Move to the integer grid from the last displayed instant and pause."""
    position.time = float(
        min(
            horizon,
            max(
                0,
                math.floor(position.time) + amount
                if amount > 0
                else math.ceil(position.time) + amount,
            ),
        )
    )
    position.playing = False


def start_playback(position: ReplayPosition, horizon: float) -> None:
    """Align to the next minute once, then advance by elapsed seconds."""
    position.time = float(min(horizon, math.ceil(position.time)))
    position.origin = int(position.time)
    position.started_at = clock()
    position.playing = position.time < horizon


def advance_playback(position: ReplayPosition, horizon: float) -> bool:
    """Update a live frame; return whether automatic pause needs a full rerun."""
    if not position.playing:
        return False
    elapsed = max(0.0, clock() - position.started_at)
    position.time = float(min(horizon, position.origin + math.floor(elapsed * position.speed)))
    if position.time >= horizon:
        position.playing = False
        return True
    return False
