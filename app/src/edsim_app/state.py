"""Share catalog choices across pages and mirror the selection in the URL."""

import os
from pathlib import Path

import streamlit as st

from edsim.runs import RunReadError, RunStore, read_run_header
from edsim_app.episodes import sync_episode_query

RUN_KEYS = ("selected_run_id", "compare_a", "compare_b")


def catalog_store() -> RunStore:
    """Resolve the catalog relative to the directory that launched the app."""
    return RunStore(Path(os.environ.get("EDSIM_EJECUCIONES", "resultados/ejecuciones")).resolve())


def forget_run(run_id: str) -> None:
    """Clear references to one run without selecting a replacement."""
    for key in RUN_KEYS:
        if st.session_state.get(key) == run_id:
            st.session_state[key] = None
    for key in ("run_choice", "pending_delete"):
        if st.session_state.get(key) == run_id:
            st.session_state.pop(key, None)
    positions = st.session_state.get("replay_positions", {})
    for identity in list(positions):
        if identity[1] == run_id:
            del positions[identity]
    choices = st.session_state.get("episode_choices", {})
    for identity in list(choices):
        if identity[1] == run_id:
            del choices[identity]


def sync_run_query() -> None:
    """Restore the selected run after navigation clears query parameters."""
    selected = st.session_state.selected_run_id
    if selected is None:
        st.query_params.pop("run", None)
    else:
        st.query_params["run"] = selected


def initialize_state(store: RunStore) -> None:
    """Read an initial link and drop references removed outside this session."""
    for key in RUN_KEYS:
        st.session_state.setdefault(key, None)
    if not st.session_state.get("catalog_initialized"):
        requested = st.query_params.get("run")
        if requested is not None and "episodio" in st.query_params:
            st.session_state.episode_initial_link = (requested, st.query_params["episodio"])
        if requested is not None:
            try:
                read_run_header(store, requested)
            except RunReadError as error:
                st.warning(
                    f"La ejecución «{requested}» no está en el catálogo. Se limpia el enlace. "
                    f"Motivo: {error}"
                )
            else:
                st.session_state.selected_run_id = requested
        st.session_state.catalog_initialized = True

    fingerprint = None
    if selected := st.session_state.selected_run_id:
        try:
            _, fingerprint = read_run_header(store, selected)
        except RunReadError as error:
            forget_run(selected)
            st.warning(
                f"La ejecución «{selected}» ya no está en el catálogo o no se puede abrir. "
                f"Se han limpiado su selección y sus marcas. Motivo: {error}"
            )

    missing = {
        run_id
        for key in RUN_KEYS
        if (run_id := st.session_state[key]) is not None and not store.exists(run_id)
    }
    for run_id in sorted(missing):
        forget_run(run_id)
        st.warning(
            f"La ejecución «{run_id}» ya no está en el catálogo. "
            "Se han limpiado su selección y sus marcas."
        )
    sync_run_query()
    if st.session_state.selected_run_id is not None and fingerprint is not None:
        sync_episode_query(str(store.root), st.session_state.selected_run_id, fingerprint)
    else:
        st.query_params.pop("episodio", None)


def choose_run() -> None:
    """Copy the page widget value into session state that survives navigation."""
    st.session_state.selected_run_id = st.session_state.run_choice
    st.session_state.pop("pending_delete", None)


def render_sidebar() -> None:
    """Show the current selection and comparison marks on every page."""
    with st.sidebar:
        st.subheader("Ejecución elegida")
        st.write(st.session_state.selected_run_id or "Ninguna")
        st.write(f"Marca A: {st.session_state.compare_a or 'Ninguna'}")
        st.write(f"Marca B: {st.session_state.compare_b or 'Ninguna'}")
