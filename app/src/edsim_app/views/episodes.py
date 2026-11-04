"""Explore the selected run with pure core filters and persistent choices."""

import pandas as pd
import streamlit as st

from edsim.runs import (
    EpisodeFilters,
    RunAnalysisError,
    RunReadError,
    filter_episodes,
    read_run_header,
)
from edsim_app.episodes import (
    episode_filter_values,
    episode_identity,
    remember_episode,
    remember_episode_filter,
)
from edsim_app.frames import episodes_frame, style_episodes
from edsim_app.results import cached_run_results
from edsim_app.state import catalog_store


def render_filters(days: int) -> EpisodeFilters:
    """Collect common filters independently of navigation-cleaned widget keys."""
    values = episode_filter_values(days - 1)
    with st.expander("Filtros", expanded=True):
        for field, label, options, formatter in (
            (
                "level",
                "Nivel",
                [None, 1, 2, 3, 4, 5],
                lambda value: "Todos" if value is None else str(value),
            ),
            (
                "destination",
                "Destino",
                [None, "alta", "ingreso"],
                lambda value: "Todos" if value is None else value.capitalize(),
            ),
            (
                "displaced",
                "Desalojado",
                [None, True, False],
                lambda value: "Todos" if value is None else "Sí" if value else "No",
            ),
            (
                "arrival_day",
                "Día de llegada",
                [None, *range(days)],
                lambda value: "Todos" if value is None else f"Día {value}",
            ),
            (
                "period",
                "Tramo",
                [None, "warmup", "window", "unfinished"],
                lambda value: {
                    None: "Todos",
                    "warmup": "Calentamiento",
                    "window": "Ventana",
                    "unfinished": "Sin terminar",
                }[value],
            ),
        ):
            widget = f"episode_filter_{field}_widget"
            st.session_state[widget] = values[field]
            st.selectbox(
                label,
                options,
                format_func=formatter,
                key=widget,
                on_change=remember_episode_filter,
                args=(field, widget),
            )
        for field, label in (
            ("door_to_doctor_gt", "Puerta-médico mayor que (min)"),
            ("stay_gt", "Estancia mayor que (min)"),
        ):
            widget = f"episode_filter_{field}_widget"
            st.session_state[widget] = values[field]
            st.number_input(
                label,
                min_value=0.0,
                value=None,
                step=5.0,
                key=widget,
                on_change=remember_episode_filter,
                args=(field, widget),
            )
    return EpisodeFilters(**values)


st.title("Episodios")
selected = st.session_state.selected_run_id
if selected is None:
    st.info("Elige una ejecución en Ejecuciones para explorar sus episodios.")
    st.stop()
store = catalog_store()
try:
    info, fingerprint = read_run_header(store, selected)
    st.header(info.run_id)
    result = cached_run_results(str(store.root), selected, fingerprint)
except (RunReadError, RunAnalysisError) as error:
    st.error(str(error))
    st.stop()
filters = render_filters(info.days)
filtered = filter_episodes(
    result.analysis.table,
    filters,
    warmup_end=info.warmup_days * 1440,
    horizon=result.analysis.curves.horizon,
)
st.caption(f"{len(filtered)} de {len(result.analysis.table)} episodios pasan los filtros.")
frame = episodes_frame(filtered, result)
# Styler's default cell limit is smaller than a valid 60-day table.
with pd.option_context("styler.render.max_elements", max(262144, frame.size)):
    st.dataframe(style_episodes(frame), hide_index=True, width="stretch")
identity = episode_identity(str(store.root), selected, fingerprint)
requested = st.session_state.episode_choices.get(identity)
identifiers = [record.episode_id for record in filtered]
st.session_state.episode_choice_widget = requested if requested in identifiers else None
st.selectbox(
    "Episodio",
    identifiers,
    index=None,
    key="episode_choice_widget",
    placeholder="Elige un episodio",
    on_change=remember_episode,
    args=(identity,),
)
if requested is not None and requested not in identifiers:
    exists = any(record.episode_id == requested for record in result.analysis.table)
    st.warning(
        f"El episodio «{requested}» "
        + ("no pasa los filtros actuales." if exists else "no existe en esta ejecución.")
    )
    st.stop()
if requested is not None:
    st.caption(f"Episodio elegido: {requested}")
