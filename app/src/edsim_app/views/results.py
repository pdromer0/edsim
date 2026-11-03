"""Present one selected run using public core results and read-only caching."""

from collections import Counter
from datetime import datetime

import streamlit as st

from edsim.runs import (
    MAX_VIOLATIONS_SHOWN,
    TIMEZONE,
    RunAnalysisError,
    RunInfo,
    RunReadError,
    RunResults,
    read_run_header,
)
from edsim_app.charts import waits_chart
from edsim_app.frames import format_number, kpis_frame, style_waits, waits_frame
from edsim_app.help import render_results_help
from edsim_app.results import cached_run_results
from edsim_app.state import catalog_store


def render_header(info: RunInfo) -> None:
    """Keep metadata visible even when the event log cannot be analyzed."""
    st.header(info.run_id)
    created = (
        datetime.fromisoformat(info.created_at).astimezone(TIMEZONE).strftime("%d/%m/%Y %H:%M:%S")
    )
    st.write(f"Variante: **{info.variant}** · Huella del centro: `{info.center_fingerprint}`")
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
    st.subheader("Esperas por nivel y Manchester")
    frame = waits_frame(result)
    st.dataframe(style_waits(frame), hide_index=True, width="stretch")
    st.altair_chart(waits_chart(frame), width="stretch")


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
