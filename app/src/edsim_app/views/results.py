"""Present one selected run using public core results and read-only caching."""

from collections import Counter
from functools import partial

import streamlit as st

from edsim.runs import (
    MAX_VIOLATIONS_SHOWN,
    RunAnalysisError,
    RunInfo,
    RunReadError,
    RunResults,
    RunStore,
    WindowOutcome,
    read_run_header,
    true_level_abandonment,
    true_level_window_compliance,
)
from edsim_app.charts import curve_chart, hourly_census_chart, occupancy_chart, waits_chart
from edsim_app.frames import (
    CURVE_LABELS,
    clocks_frame,
    curve_frame,
    format_created_at,
    format_number,
    hourly_census_frame,
    kpis_frame,
    level_one_clocks_frame,
    little_frame,
    observed_distribution_frames,
    occupancy_frame,
    pretriage_frame,
    style_little,
    style_waits,
    waits_frame,
    wall_times,
)
from edsim_app.help import render_results_help
from edsim_app.outcome_frames import (
    OUTCOME_CURVE_LABELS,
    destination_frames,
    format_censored_minutes,
    left_frames,
    stay_frame,
    threshold_frame,
    true_level_abandonment_frames,
    true_level_compliance_frame,
)
from edsim_app.results import cached_episode_truth, cached_run_results
from edsim_app.state import catalog_store


def render_header(info: RunInfo) -> None:
    """Keep metadata visible even when the event log cannot be analyzed."""
    st.header(info.run_id)
    created = format_created_at(info.created_at)
    st.write(f"Variante: **{info.variant}** · Huella del centro: `{info.center_fingerprint}`")
    st.caption(f"Modelo: {'Clínico' if info.is_clinical else 'Provisional'}")
    if info.is_clinical:
        st.caption(
            f"Perfiles: {info.clinical_profiles_path} · "
            f"Huella: {info.clinical_profiles_fingerprint}"
        )
    st.caption(f"Días: {info.days} · Calentamiento: {info.warmup_days} días · Semilla: {info.seed}")
    st.caption(f"Fecha de creación (UTC+1): {created} · Versión de EDsim: {info.edsim_version}")


def render_invariants(result: RunResults) -> None:
    """Show the saved count and the first ten log-only violations when rechecked."""
    st.subheader("Invariantes")
    saved = result.info.invariant_violations
    if saved == 0:
        st.success("Invariantes: 0 violaciones")
        return
    violations = result.violations
    st.error(f"Invariantes: {saved} violaciones guardadas")
    if len(violations) != saved:
        st.warning(f"El recuento recalculado ({len(violations)}) difiere del guardado ({saved}).")
    counts = Counter(v.check for v in violations)
    st.write(
        "Recuento por comprobación: "
        + (", ".join(f"{name}: {count}" for name, count in counts.items()) or "0 violaciones")
    )
    for violation in violations[:MAX_VIOLATIONS_SHOWN]:
        where = (
            "—" if violation.sim_time is None else f"minuto {format_number(violation.sim_time, 4)}"
        )
        st.write(f"{violation.check} · {violation.event_id or '—'} · {where} · {violation.message}")
    if len(violations) > MAX_VIOLATIONS_SHOWN:
        st.caption(f"… y {len(violations) - MAX_VIOLATIONS_SHOWN} más")


def render_kpis_and_waits(result: RunResults) -> None:
    """Display supplied values with Spanish formatting and explicit populations."""
    st.subheader("KPIs de la ventana")
    st.caption(
        f"Ventana: [día {result.info.warmup_days}, día {result.info.days}). "
        f"Episodios completados: {result.kpis.n}."
    )
    rows = list(kpis_frame(result.kpis).itertuples(index=False, name=None))
    for offset in range(0, len(rows), 3):
        for column, (label, value, unit, digits, percentage) in zip(
            st.columns(3), rows[offset : offset + 3], strict=True
        ):
            column.metric(
                label,
                format_number(value, digits, percentage=percentage)
                + (f" {unit}" if unit != "%" else ""),
            )
    st.subheader("Esperas por nivel y Manchester desde la clasificación (C)")
    frame = waits_frame(result).query("Nivel != 1").reset_index(drop=True)
    st.dataframe(style_waits(frame), hide_index=True, width="stretch")
    st.altair_chart(waits_chart(frame), width="stretch")


def remember_plot(field: str, widget: str) -> None:
    """Keep plot choices independent of widget keys removed by page navigation."""
    st.session_state[field] = st.session_state[widget]


def render_analysis(result: RunResults) -> None:
    """Present occupancy, one weekly curve, daily census and Little's law."""
    st.subheader("Ocupación por recurso y turno")
    frame = occupancy_frame(result)
    st.altair_chart(occupancy_chart(frame), width="stretch")
    st.caption("La ocupación puede superar 1 al bajar la plantilla: nadie se interrumpe.")
    with st.expander("Valores de ocupación"):
        st.dataframe(
            frame.drop(columns="Etiqueta").style.format({"Ocupación": "{:.1%}"}, decimal=","),
            hide_index=True,
            width="stretch",
        )

    st.subheader("Curvas por semana")
    weeks = list(range((result.info.days + 6) // 7))
    st.session_state.results_week = min(st.session_state.get("results_week", 0), weeks[-1])
    # The curves of the beds exist only with a log of version 4 (task 5.4).
    curves = CURVE_LABELS | (OUTCOME_CURVE_LABELS if result.outcome is not None else {})
    if st.session_state.get("results_curve") not in curves:
        st.session_state.results_curve = "census"
    for field, label, options, formatter in (
        (
            "results_week",
            "Semana",
            weeks,
            lambda week: (
                f"Semana {week + 1} · [día {week * 7}, día {min((week + 1) * 7, result.info.days)})"
            ),
        ),
        ("results_curve", "Curva", list(curves), curves.get),
    ):
        widget = f"{field}_widget"
        st.session_state[widget] = st.session_state[field]
        st.selectbox(
            label,
            options,
            key=widget,
            format_func=formatter,
            on_change=remember_plot,
            args=(field, widget),
        )
    frame = curve_frame(result, st.session_state.results_curve, st.session_state.results_week)
    warmup_end = wall_times(result, [result.info.warmup_days * 1440])[0]
    st.altair_chart(curve_chart(frame, warmup_end), width="stretch")
    st.caption("Media y máximo por bloques de 15 minutos. La zona sombreada es el calentamiento.")
    st.subheader("Perfil diario del censo")
    st.altair_chart(hourly_census_chart(hourly_census_frame(result)), width="stretch")
    st.subheader("Ley de Little")
    st.dataframe(style_little(little_frame(result)), hide_index=True, width="stretch")


def render_outcome(outcome: WindowOutcome) -> None:
    """The observable indicators of milestone 5, from the log of the window (H5-8)."""
    st.subheader("Desenlace: abandono, destinos y espera de cama")
    st.caption(
        "Sobre las llegadas de la ventana; por nivel, sobre los clasificados con ese nivel. "
        "«≥» es una cota inferior: hay pacientes que siguen esperando al final."
    )
    overall, by_wait, by_level = left_frames(outcome)
    st.dataframe(overall, hide_index=True)
    st.dataframe(by_wait, hide_index=True)
    st.dataframe(by_level, hide_index=True)
    overall, by_level = destination_frames(outcome)
    st.dataframe(overall, hide_index=True)
    st.dataframe(by_level, hide_index=True)
    bed = outcome.bed_wait
    st.markdown("**Espera de cama de los ingresados**")
    for column, (label, value) in zip(
        st.columns(5),
        (
            ("Pedidos de cama", str(bed.requests)),
            ("Con cama", str(bed.completed)),
            ("Siguen esperando", str(bed.censored)),
            ("Mediana", format_censored_minutes(bed.median)),
            ("p90", format_censored_minutes(bed.p90)),
        ),
        strict=True,
    ):
        column.metric(label, value)
    st.dataframe(threshold_frame(bed.over), hide_index=True)
    st.markdown("**Estancia en urgencias por destino**")
    st.dataframe(stay_frame(outcome), hide_index=True, width="stretch")
    st.caption(
        f"Ingresados con más de {format_number(outcome.stay.admitted_over.minutes / 60, 0)} h:"
    )
    st.dataframe(threshold_frame((outcome.stay.admitted_over,)), hide_index=True)
    beds = outcome.beds
    for column, (label, value) in zip(
        st.columns(4),
        (
            ("Boxes con ingresados esperando cama (media)", format_number(beds.boxes_mean, 2)),
            ("Boxes con ingresados esperando cama (máximo)", str(beds.boxes_max)),
            ("Pacientes en el pasillo (media)", format_number(beds.hallway_mean, 4)),
            ("Pacientes en el pasillo (máximo)", str(beds.hallway_max)),
        ),
        strict=True,
    ):
        column.metric(label, value)


def render_truth(result: RunResults, root: str, fingerprint: str) -> None:
    """Indicators that only the ground truth gives, never next to the observable ones."""
    st.subheader("Ver la verdad")
    if not result.info.is_clinical:
        st.caption("Las ejecuciones del modelo provisional no tienen nivel real.")
        return
    if not st.toggle("Ver la verdad", key="results_truth_widget"):
        st.caption("Indicadores del ground truth: nunca forman parte de los KPI observables.")
        return
    try:
        truth = cached_episode_truth(root, result.info.run_id, fingerprint)
    except RunReadError as error:
        st.error(str(error))
        return
    try:
        compliance = true_level_window_compliance(
            result.analysis.table, truth, result.info.warmup_days, result.info.days
        )
        abandonment = (
            None
            if result.outcome is None
            else true_level_abandonment(
                result.analysis.table, truth, result.outcome.start, result.outcome.end
            )
        )
    except ValueError as error:
        # The truth lacks an episode of the window, or its clinical part or outcome:
        # the folder was changed outside the app (simulate_run always writes it whole).
        st.error(f"ground_truth_episodios.csv no casa con el log: {error}")
        return
    st.markdown("**Cumplimiento Manchester por nivel real (reloj C)**")
    st.dataframe(true_level_compliance_frame(compliance), hide_index=True, width="stretch")
    if abandonment is not None:
        st.markdown("**Abandono por nivel real**")
        by_level, harm = true_level_abandonment_frames(abandonment)
        st.dataframe(by_level, hide_index=True)
        st.dataframe(harm, hide_index=True)


def render_downloads(store: RunStore, run_id: str, clinical: bool = False) -> None:
    """Defer each format-file read until its download button is activated."""
    st.subheader("Descargas")
    downloads = (
        ("eventos.jsonl", "Log de eventos", "application/x-ndjson"),
        ("ground_truth_episodios.csv", "Ground truth de episodios", "text/csv"),
        ("ground_truth_dias.csv", "Ground truth de días", "text/csv"),
        ("centro.toml", "Configuración del centro", "application/toml"),
        ("llegadas.toml", "Perfil de llegadas", "application/toml"),
    )
    if clinical:
        downloads += (("perfiles.toml", "Perfiles clínicos", "application/toml"),)
    for filename, label, mime in downloads:
        st.download_button(
            label,
            data=partial(store.read_file, run_id, filename),
            file_name=filename,
            mime=mime,
            on_click="ignore",
            key=f"download_result_{filename}",
        )


st.title("Resultados")
selected = st.session_state.selected_run_id
if selected is None:
    st.info("Elige una ejecución en Ejecuciones para ver sus resultados.")
    st.stop()
store = catalog_store()
try:
    info, fingerprint = read_run_header(store, selected)
except RunReadError as error:
    st.error(f"No se puede abrir la ejecución: {error}")
    st.stop()
render_header(info)
try:
    result = cached_run_results(str(store.root), selected, fingerprint)
except (RunReadError, RunAnalysisError) as error:
    st.error(str(error))
    st.stop()
render_results_help()
render_invariants(result)
render_kpis_and_waits(result)
if result.outcome is not None:
    render_outcome(result.outcome)
render_analysis(result)
st.subheader("Los tres relojes · niveles asignados 2–5")
st.dataframe(clocks_frame(result), hide_index=True)
st.subheader("Nivel 1 · atención inmediata")
st.caption("Mediana y p90; sin porcentaje de cumplimiento.")
st.dataframe(level_one_clocks_frame(result), hide_index=True)
st.subheader("Pretriaje · sin el nivel 1")
st.dataframe(
    pretriage_frame(result).style.format(
        {"10 min o menos": "{:.1%}", "Más de 5 min": "{:.1%}"}, decimal=",", na_rep="—"
    ),
    hide_index=True,
)
if result.model == "clinico":
    st.subheader("Reparto observado de las llegadas de la ventana")
    st.caption(
        "Sin calentamiento; incluye episodios sin terminar. Sin observar: aún no consta en el log."
    )
    for frame in observed_distribution_frames(result):
        st.dataframe(frame.style.format({"Proporción": "{:.1%}"}, decimal=","), hide_index=True)
render_truth(result, str(store.root), fingerprint)
render_downloads(store, selected, result.info.is_clinical)
