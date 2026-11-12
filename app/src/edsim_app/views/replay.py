"""Inspect a saved service state and play only the plan and status as a fragment."""

from datetime import datetime, time, timedelta

import pandas as pd
import streamlit as st

from edsim.runs import (
    TIMEZONE,
    RunAnalysisError,
    RunReadError,
    RunStore,
    curve_steps,
    observed_profiles,
    read_replay_state,
    read_run_header,
    replay_counts,
    shift_at,
)
from edsim_app.charts import replay_census_chart
from edsim_app.episodes import open_replay_episode
from edsim_app.frames import (
    episode_events_frame,
    episode_state_label,
    observed_profile_row,
    wall_times,
)
from edsim_app.plan import render_plan
from edsim_app.replay import (
    advance_playback,
    cached_replay_index,
    clock,
    pause_replays_except,
    replay_position,
    start_playback,
    step_position,
)
from edsim_app.results import cached_episode_events, cached_run_results
from edsim_app.state import catalog_store


def stamp(result, t):
    """Show seconds only when the selected simulation minute is fractional."""
    value = datetime.combine(result.start_date, time(), TIMEZONE) + timedelta(minutes=t)
    return value.strftime("%d/%m/%Y %H:%M:%S" if t % 1 else "%d/%m/%Y %H:%M")


def choose_replay_run():
    """Share the run selector and pause the previous execution."""
    st.session_state.selected_run_id = st.session_state.replay_run_widget
    pause_replays_except(st.session_state.selected_run_id)


def render_controls(position, days, horizon):
    """Hydrate widgets only during full runs; callbacks operate on the live position."""

    def change_day():
        position.time = float(st.session_state.replay_day_widget * 1440)
        position.playing = False

    def change_minute():
        position.time = float(
            int(position.time // 1440) * 1440 + st.session_state.replay_minute_widget
        )
        position.playing = False

    def change_speed():
        position.speed = st.session_state.replay_speed_widget
        position.origin = int(position.time)
        position.started_at = clock()

    def pause():
        position.playing = False

    terminal = position.time == horizon
    st.session_state.replay_day_widget = int(position.time // 1440)
    st.selectbox(
        "Día",
        list(range(days + 1)),
        key="replay_day_widget",
        format_func=lambda d: f"Fin de ejecución · día {d}, 00:00" if d == days else f"Día {d}",
        disabled=position.playing,
        on_change=change_day,
    )
    st.session_state.replay_minute_widget = int(position.time % 1440)
    # A time-valued slider gives HH:MM labels without exposing implementation minutes.
    st.session_state.replay_clock_widget = time(
        int(position.time % 1440) // 60, int(position.time % 60)
    )

    def change_clock():
        value = st.session_state.replay_clock_widget
        st.session_state.replay_minute_widget = value.hour * 60 + value.minute
        change_minute()

    st.slider(
        "Minuto",
        min_value=time(0, 0),
        max_value=time(23, 59),
        step=timedelta(minutes=1),
        format="HH:mm",
        key="replay_clock_widget",
        disabled=position.playing or terminal,
        on_change=change_clock,
    )
    if position.playing:
        st.caption("En reproducción: pausa para elegir un minuto")
    columns = st.columns(6)
    for column, amount in zip(columns[:4], (-10, -1, 1, 10), strict=True):
        column.button(
            f"{amount:+d} min",
            key=f"replay_step_{amount}",
            disabled=(position.time == 0 if amount < 0 else terminal),
            on_click=step_position,
            args=(position, amount, horizon),
        )
    columns[4].button(
        "Reproducir",
        key="replay_play",
        disabled=terminal or position.playing,
        on_click=start_playback,
        args=(position, horizon),
    )
    columns[5].button("Pausar", key="replay_pause", disabled=not position.playing, on_click=pause)
    st.session_state.replay_speed_widget = position.speed
    st.selectbox(
        "Velocidad (minutos simulados por segundo)",
        [1, 5, 15, 60],
        key="replay_speed_widget",
        on_change=change_speed,
    )


def render_details(result, identity, index, t):
    """Refresh the chart, raw events and patient browser only on full page runs."""
    state = read_replay_state(RunStore(identity[0]), identity[1], index, t)
    suffix = "; se actualizan al pausar" if replay_position(identity).playing else ""
    st.caption(
        f"Detalles de las {stamp(result, t).split(' ', 1)[1]} del día {int(t // 1440)}{suffix}"
    )
    day = min(int(t // 1440), result.info.days - 1)
    start, end = day * 1440, (day + 1) * 1440
    steps = curve_steps(result.analysis.curves, "census", start, end)
    frame = pd.DataFrame(
        {
            "Fecha y hora": wall_times(result, steps.edges),
            "Censo": [*steps.values, steps.values[-1]],
        }
    )
    st.altair_chart(replay_census_chart(frame, wall_times(result, [t])[0]), width="stretch")
    st.subheader("Últimos 15 eventos")
    st.dataframe(episode_events_frame(state.last_events), hide_index=True, width="stretch")
    st.subheader("Pacientes dentro")
    frame = pd.DataFrame(
        [
            {
                "Episodio": p.episode_id,
                "Nivel": p.level,
                "Estado": episode_state_label(
                    p.state, results_room=p.results_room, hallway=p.hallway
                ),
                "Box": p.box,
                "Llegada (UTC+1)": wall_times(result, [p.arrival])[0],
            }
            for p in state.patients
        ],
        columns=["Episodio", "Nivel", "Estado", "Box", "Llegada (UTC+1)"],
    )
    st.dataframe(frame, hide_index=True, width="stretch")
    selected = st.selectbox(
        "Paciente dentro",
        [p.episode_id for p in state.patients],
        index=None,
        key="replay_patient_widget",
        placeholder="Elige un episodio",
    )
    if selected is not None and result.profiles is not None:
        events = cached_episode_events(identity[0], identity[1], identity[2], selected)
        observed = observed_profiles(
            (event for event in events if event.sim_time <= t), result.profiles.population
        )[selected]
        row = observed_profile_row(observed, result.profiles)
        st.subheader(f"Ficha del paciente {selected}")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Edad": row["Edad"],
                        "Motivo": row["Motivo"] or "Sin observar",
                    }
                ]
            ),
            hide_index=True,
        )
    if st.button("Abrir ficha", key="replay_open_episode", disabled=selected is None):
        open_replay_episode(identity, selected)


def render_live(result, identity, index, position):
    """A frame contains only bounded reconstruction, the status and SVG presentation."""
    if advance_playback(position, index.horizon):
        st.rerun()
    try:
        state = read_replay_state(RunStore(identity[0]), identity[1], index, position.time)
    except RunReadError as error:
        position.playing = False
        st.error(str(error))
        return
    counts = replay_counts(result, position.time)
    shift = ("Mañana", "Tarde", "Noche")[shift_at(result.center.shift_starts, position.time)]
    status = f"{stamp(result, position.time)} (UTC+1) · {shift} · Censo: {counts.census}"
    status += (
        f" · Triaje: {counts.nurses_busy} / {counts.nurses_staff}"
        f" · Médicos: {counts.doctors_busy} / {counts.doctors_staff}"
    )
    if result.outcome is not None:
        status += (
            f" · Boxes con ingresados esperando cama: {counts.boxes_waiting_bed}"
            f" · Pasillo: {counts.hallway}"
        )
    if position.time < result.info.warmup_days * 1440:
        status += " · Calentamiento"
    if position.time == index.horizon:
        status += " · Fin de la ejecución: pacientes que siguen dentro"
    st.markdown(status)
    st.html(
        render_plan(
            state,
            counts,
            start_date=result.start_date,
            highlighted_episode=position.highlighted_episode,
        )
    )


st.title("Replay")
store = catalog_store()
choices = [None, *[info.run_id for info in store.list()]]
st.session_state.replay_run_widget = st.session_state.selected_run_id
st.selectbox(
    "Ejecución",
    choices,
    key="replay_run_widget",
    format_func=lambda r: r or "Sin elegir",
    on_change=choose_replay_run,
)
selected = st.session_state.selected_run_id
if selected is None:
    st.info("Elige una ejecución para ver el servicio minuto a minuto.")
    st.stop()
try:
    info, fingerprint = read_run_header(store, selected)
    st.header(info.run_id)
    with st.spinner("Leyendo los resultados y construyendo el índice del replay…"):
        result = cached_run_results(str(store.root), selected, fingerprint)
        index = cached_replay_index(str(store.root), selected, fingerprint)
except (RunReadError, RunAnalysisError) as error:
    st.error(str(error))
    st.stop()
identity = (str(store.root), selected, fingerprint)
position = replay_position(identity)
with st.expander("¿Qué estoy viendo?"):
    st.write(
        "El plano reconstruye el log hasta el instante elegido, incluidos sus eventos. "
        "Los contadores usan las mismas curvas que Resultados. El triaje atiende por "
        "llegada y la cola de box por nivel y llegada; solo el nivel 1 puede desalojar."
    )
    st.write(
        "La edad y el motivo de la ficha solo aparecen cuando ya constan en el log. "
        "Los colores muestran el nivel asignado, nunca el real. La sala de resultados "
        "está fuera del box; su etiqueta distingue espera de pruebas y vuelta al box. "
        "El laboratorio sigue trabajando si el paciente pierde su box. Los bordes "
        "marcan desalojos de los últimos 60 minutos. Ocupados / plantilla puede "
        "superar 1 al bajar la plantilla: nadie se interrumpe. Horas UTC+1 fijo."
    )
render_controls(position, info.days, index.horizon)
st.fragment(run_every=1.0 if position.playing else None, key="replay_live")(render_live)(
    result, identity, index, position
)
try:
    render_details(result, identity, index, position.time)
except RunReadError as error:
    position.playing = False
    st.error(str(error))
