"""Keep shared episode filters and per-run selections outside widget state."""

from dataclasses import asdict

import streamlit as st

from edsim.runs import EpisodeFilters


def episode_identity(root: str, run_id: str, fingerprint: str) -> tuple[str, str, str]:
    """Identify an immutable run independently of its display name."""
    return root, run_id, fingerprint


def sync_episode_query(root: str, run_id: str, fingerprint: str) -> None:
    """Preserve the requested card across sidebar navigation and URL clearing."""
    choices = st.session_state.setdefault("episode_choices", {})
    identity = episode_identity(root, run_id, fingerprint)
    initial = st.session_state.pop("episode_initial_link", None)
    if initial is not None and initial[0] == run_id:
        choices[identity] = initial[1]
    requested = choices.get(identity)
    if requested is None:
        st.query_params.pop("episodio", None)
    else:
        st.query_params["episodio"] = requested


def remember_episode(identity: tuple[str, str, str]) -> None:
    """Persist selection and update its URL even during a fragment-only rerun."""
    st.session_state.episode_choices[identity] = st.session_state.episode_choice_widget
    sync_episode_query(*identity)


def episode_filter_values(last_day: int) -> dict:
    """Keep common filters, clamping an out-of-range arrival day with a notice."""
    values = st.session_state.setdefault("episode_filters", asdict(EpisodeFilters()))
    day = values["arrival_day"]
    if day is not None and day > last_day:
        values["arrival_day"] = last_day
        st.info(
            f"El día de llegada {day} queda fuera de esta ejecución; se ajusta al día {last_day}."
        )
    return values


def remember_episode_filter(field: str, widget: str) -> None:
    """Copy one filter into persistent state before a page rerun."""
    st.session_state.episode_filters[field] = st.session_state[widget]


def _open_episode(identity: tuple[str, str, str], episode_id: str, source: str) -> None:
    """Select an exact card and clear common filters before multipage navigation."""
    st.session_state.selected_run_id = identity[1]
    st.session_state.setdefault("episode_choices", {})[identity] = episode_id
    st.session_state.episode_filters = asdict(EpisodeFilters())
    st.session_state.episode_filter_notice = (
        f"Se han quitado los filtros de Episodios para mostrar la ficha desde {source}."
    )
    st.switch_page("views/episodes.py", query_params={"run": identity[1], "episodio": episode_id})


def open_comparison_episode(identity: tuple[str, str, str], episode_id: str) -> None:
    """Open an exact card from the comparison without preserving incompatible filters."""
    _open_episode(identity, episode_id, "Comparar")


def open_replay_episode(identity: tuple[str, str, str], episode_id: str) -> None:
    """Open an exact card from replay without preserving incompatible filters."""
    _open_episode(identity, episode_id, "Replay")


def open_episode_replay(identity: tuple[str, str, str], episode_id: str, arrival: float) -> None:
    """Open the exact observed arrival paused, even for sub-minute episodes."""
    from edsim_app.replay import replay_position

    position = replay_position(identity)
    position.time = arrival
    position.highlighted_episode = episode_id
    position.playing = False
    st.session_state.selected_run_id = identity[1]
    st.switch_page("views/replay.py", query_params={"run": identity[1], "episodio": episode_id})
