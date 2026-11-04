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
