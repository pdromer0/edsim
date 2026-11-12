"""Explore the selected run with pure core filters and persistent choices."""

import pandas as pd
import streamlit as st

from edsim.runs import (
    EpisodeFilters,
    EpisodeRecord,
    RunAnalysisError,
    RunReadError,
    RunResults,
    compare_episode_truth,
    episode_clinical_truth,
    episode_observed_time,
    episode_outcome_truth,
    episode_segments,
    filter_episodes,
    read_run_header,
)
from edsim_app.charts import episode_chart
from edsim_app.episodes import (
    episode_filter_values,
    episode_identity,
    open_episode_replay,
    remember_episode,
    remember_episode_filter,
)
from edsim_app.frames import (
    LEFT_FROM_LABELS,
    clinical_truth_frames,
    episode_events_frame,
    episode_timeline_frames,
    episode_truth_frame,
    episodes_frame,
    format_number,
    observed_profile_row,
    style_episodes,
    wall_times,
)
from edsim_app.help import render_episodes_help
from edsim_app.outcome_frames import outcome_truth_frame
from edsim_app.results import (
    cached_episode_event_index,
    cached_episode_events,
    cached_episode_truth,
    cached_run_results,
)
from edsim_app.state import catalog_store


def render_filters(result: RunResults) -> EpisodeFilters:
    """Collect common filters independently of navigation-cleaned widget keys."""
    days = result.info.days
    values = episode_filter_values(days - 1)
    profile_choices = {}
    if result.profiles is not None:
        population = result.profiles.population
        bands = population.band_starts
        profile_choices = {
            "age_band": (
                "Banda de edad",
                {
                    i: f"{age}–{bands[i + 1] - 1} años"
                    if i + 1 < len(bands)
                    else f"{age} años o más"
                    for i, age in enumerate(bands)
                },
            ),
            "sex": ("Sexo", {"mujer": "Mujer", "hombre": "Hombre"}),
            "arrival_mode": (
                "Medio de llegada",
                {"ambulancia": "Ambulancia", "propios_medios": "Medios propios"},
            ),
            "reason": ("Motivo", {r.key: r.name for r in result.profiles.reasons}),
            "test": (
                "Prueba pedida",
                {t.key: t.key.capitalize() for t in result.profiles.diagnostic_tests},
            ),
        }
    outcome_choices = {}
    if result.outcome is not None:
        yes_no = {True: "Sí", False: "No"}
        outcome_choices = {
            "left": ("Se va sin ser visto", yes_no),
            "left_from": ("Se va desde", LEFT_FROM_LABELS),
            "bed": ("Pide cama", yes_no),
            "hallway": ("Espera la cama en el pasillo", yes_no),
        }
    # Transfers and deaths exist only with the milestone 5 model (H5-5).
    destinations = [None, "alta", "ingreso"] + (
        ["traslado", "exitus"] if result.outcome is not None else []
    )
    if values["destination"] not in destinations:
        values["destination"] = None
        st.info("Se ha quitado el filtro de destino: esta ejecución solo tiene alta e ingreso.")
    for field in ("left", "left_from", "bed", "hallway"):
        if values[field] is not None and field not in outcome_choices:
            values[field] = None
            st.info(
                "Se ha quitado un filtro del desenlace, que solo tienen las ejecuciones del hito 5."
            )
    for field in ("age_band", "sex", "arrival_mode", "reason", "test"):
        if values[field] is not None and (
            field not in profile_choices or values[field] not in profile_choices[field][1]
        ):
            values[field] = None
            st.info("Se ha quitado un filtro clínico que no está disponible en esta ejecución.")
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
                destinations,
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
        for field, (label, choices) in (profile_choices | outcome_choices).items():
            widget = f"episode_filter_{field}_widget"
            st.session_state[widget] = values[field]
            st.selectbox(
                label,
                [None, *choices],
                key=widget,
                format_func=lambda value, choices=choices: (
                    "Todos" if value is None else choices[value]
                ),
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


def render_card(record: EpisodeRecord, result: RunResults, root: str, fingerprint: str) -> None:
    """Present a validated card and lazily compare its exact draws on request."""
    try:
        events = cached_episode_events(root, result.info.run_id, fingerprint, record.episode_id)
    except RunReadError as error:
        st.error(str(error))
        return
    timeline = episode_segments(events, result.analysis.curves.horizon)
    st.subheader(f"Ficha del episodio {record.episode_id}")
    columns = st.columns(4)
    columns[0].metric(
        "Llegada (UTC+1)", wall_times(result, [record.arrival])[0].strftime("%d/%m/%Y %H:%M:%S")
    )
    columns[1].metric("Nivel", format_number(record.level, 0))
    columns[2].metric("Destino", record.destination.capitalize() if record.destination else "—")
    columns[3].metric(
        "Estancia", "—" if record.stay is None else f"{format_number(record.stay)} min"
    )
    for label, value in (
        ("Espera inicial de box", record.initial_box_wait),
        ("Espera de box al volver", record.results_box_wait),
    ):
        st.metric(label, "—" if value is None else f"{format_number(value)} min")
    if result.observed is not None:
        for label, value in observed_profile_row(
            result.observed[record.episode_id], result.profiles
        ).items():
            st.write(f"**{label}:** {value if value is not None else '—'}")
    if record.left is not None:
        st.metric(
            "Se va sin ser visto (UTC+1)",
            wall_times(result, [record.left])[0].strftime("%d/%m/%Y %H:%M:%S"),
        )
        st.write(f"**Desde:** {LEFT_FROM_LABELS[record.left_from]}")
        st.caption(
            "Se fue antes de ver al médico: sus relojes quedan vacíos y su destino nunca se "
            "decidió. En el cumplimiento, si ya había pasado su máximo cuenta como incumplimiento; "
            "si no, queda censurado."
        )
    if record.bed_requested is not None:
        st.metric(
            "Espera de cama",
            "Sigue esperando"
            if record.bed_wait is None
            else f"{format_number(record.bed_wait)} min",
        )
        if record.hallway:
            st.write(
                "**Pasillo:** sí; un nivel 1 lo desalojó del box y esperó la cama en el pasillo."
            )
    if record.end is None:
        observed = episode_observed_time(record, result.analysis.curves.horizon)
        st.caption(
            f"Sin terminar. Tiempo observado: {format_number(observed)} min; "
            "cota inferior de la estancia."
        )
    st.altair_chart(episode_chart(*episode_timeline_frames(timeline, result)), width="stretch")
    st.caption(
        "Recorrido: ubicación del paciente. Pruebas: trabajo del laboratorio. Rombos: desalojos."
    )
    with st.expander("Eventos del log"):
        st.dataframe(episode_events_frame(events), hide_index=True, width="stretch")
    if st.button("Ver en el replay", key="episode_open_replay"):
        open_episode_replay(
            (root, result.info.run_id, fingerprint), record.episode_id, record.arrival
        )
    if st.toggle("Ver la verdad", key="episode_truth_widget"):
        try:
            truth = cached_episode_truth(root, result.info.run_id, fingerprint)
        except RunReadError as error:
            st.error(str(error))
            return
        if record.episode_id not in truth:
            st.error(f"ground_truth_episodios.csv: no contiene el episodio {record.episode_id}.")
            return
        if result.profiles is not None:
            clinical = episode_clinical_truth(
                events,
                truth[record.episode_id],
                profiles=result.profiles,
                start_date=result.start_date,
            )
            st.subheader("Verdad clínica del episodio")
            for frame in clinical_truth_frames(clinical):
                st.dataframe(frame, hide_index=True)
        rows = compare_episode_truth(
            events,
            timeline,
            truth[record.episode_id],
            profiles=result.profiles,
            start_date=result.start_date,
            center=result.center,
        )
        st.subheader("Lo sorteado frente a lo observado")
        st.dataframe(episode_truth_frame(rows), hide_index=True, width="stretch")
        if result.outcome is not None and truth[record.episode_id].outcome is not None:
            st.subheader("Desenlace sorteado")
            view = episode_outcome_truth(
                events, truth[record.episode_id], center=result.center, start_date=result.start_date
            )
            st.dataframe(outcome_truth_frame(view), hide_index=True, width="stretch")
        if any(row.status == "mismatch" for row in rows):
            st.warning("Hay discrepancias entre lo sorteado y lo observado.")


@st.fragment(key="episode_card")
def render_episode_browser(
    result: RunResults,
    filtered: tuple[EpisodeRecord, ...],
    identity: tuple[str, str, str],
) -> None:
    """Rerun selection and card widgets without rebuilding the episode table."""
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
        return
    if requested is not None:
        record = next(record for record in result.analysis.table if record.episode_id == requested)
        render_card(record, result, identity[0], identity[2])


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
render_episodes_help()
if notice := st.session_state.pop("episode_filter_notice", None):
    st.info(notice)
try:
    cached_episode_event_index(str(store.root), selected, fingerprint)
except RunReadError as error:
    st.error(str(error))
    st.stop()
filters = render_filters(result)
filtered = filter_episodes(
    result.analysis.table,
    filters,
    warmup_end=info.warmup_days * 1440,
    horizon=result.analysis.curves.horizon,
    observed=result.observed,
)
st.caption(f"{len(filtered)} de {len(result.analysis.table)} episodios pasan los filtros.")
frame = episodes_frame(filtered, result)
# Styler's default cell limit is smaller than a valid 60-day table.
with pd.option_context("styler.render.max_elements", max(262144, frame.size)):
    st.dataframe(style_episodes(frame), hide_index=True, width="stretch")
identity = episode_identity(str(store.root), selected, fingerprint)
render_episode_browser(result, filtered, identity)
