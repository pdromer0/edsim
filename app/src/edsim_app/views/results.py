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
    read_run_header,
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
from edsim_app.results import cached_run_results
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
    st.session_state.setdefault("results_curve", "census")
    for field, label, options, formatter in (
        (
            "results_week",
            "Semana",
            weeks,
            lambda week: (
                f"Semana {week + 1} · [día {week * 7}, día {min((week + 1) * 7, result.info.days)})"
            ),
        ),
        ("results_curve", "Curva", list(CURVE_LABELS), CURVE_LABELS.get),
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
render_downloads(store, selected, result.info.is_clinical)
