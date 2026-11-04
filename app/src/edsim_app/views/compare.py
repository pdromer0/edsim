"""Choose independent runs and present core-computed comparison summaries."""

import streamlit as st

from edsim.runs import (
    RunAnalysisError,
    RunReadError,
    RunResults,
    RunStore,
    RunSummaryComparison,
    compare_run_summary,
    pairing_blockers,
    read_run_header,
)
from edsim_app.comparison_frames import (
    METADATA_LABELS,
    comparison_configuration_frames,
    comparison_kpis_frame,
    comparison_levels_frame,
)
from edsim_app.frames import kpis_frame
from edsim_app.help import render_compare_help
from edsim_app.results import cached_run_results
from edsim_app.state import catalog_store


def remember_side(side: str) -> None:
    """Copy a selector into the persistent comparison mark before main reruns."""
    st.session_state[f"compare_{side}"] = st.session_state[f"compare_{side}_widget"]


def render_side(store: RunStore, side: str, choices: list[str]) -> tuple[RunResults, str] | None:
    """Read each header independently, keeping the other side usable on failure."""
    marked = st.session_state[f"compare_{side}"]
    options = [None, *choices]
    if marked is not None and marked not in options:
        options.append(marked)
    widget = f"compare_{side}_widget"
    st.session_state[widget] = marked
    st.selectbox(
        f"Ejecución {side.upper()}",
        options,
        key=widget,
        format_func=lambda value: value or "Sin elegir",
        on_change=remember_side,
        args=(side,),
    )
    if marked is None:
        st.info(f"Elige la ejecución {side.upper()}.")
        return None
    st.header(f"{side.upper()}: {marked}")
    try:
        info, fingerprint = read_run_header(store, marked)
        st.caption(
            f"Variante: {info.variant} · Semilla: {info.seed} · "
            f"Días: {info.days} · Calentamiento: {info.warmup_days}"
        )
        result = cached_run_results(str(store.root), marked, fingerprint)
    except (RunReadError, RunAnalysisError) as error:
        st.error(f"Lado {side.upper()}: {error}")
        return None
    return result, fingerprint


def render_summary(summary: RunSummaryComparison, a_id: str, b_id: str) -> None:
    """Render populations beside KPIs, then supplied configuration and level differences."""
    st.subheader("KPIs de la ventana")
    st.caption(
        f"A ({a_id}): {summary.completed_a} completados; "
        f"sin terminar: {summary.unfinished_a}. "
        f"B ({b_id}): {summary.completed_b} completados; "
        f"sin terminar: {summary.unfinished_b}."
    )
    if summary.unfinished_a or summary.unfinished_b:
        st.warning(
            "Las estancias y puerta-médico solo incluyen a quienes terminaron. "
            "Los que siguen dentro suelen ser los peores y quedan fuera: "
            "hay sesgo hacia abajo en las estancias observadas."
        )
    if summary.unfinished_a != summary.unfinished_b:
        side = "A" if summary.unfinished_a > summary.unfinished_b else "B"
        st.warning(
            f"{side} tiene más pacientes sin terminar; su estancia media "
            "está sesgada hacia abajo. No interpretes una media menor como mejora sin más."
        )
    st.dataframe(comparison_kpis_frame(summary), hide_index=True, width="stretch")
    st.subheader("Esperas por nivel y Manchester")
    st.dataframe(comparison_levels_frame(summary), hide_index=True, width="stretch")
    metadata, center = comparison_configuration_frames(summary)
    with st.expander("Diferencias de configuración y metadatos", expanded=True):
        if metadata.empty:
            st.caption("Metadatos idénticos.")
        else:
            st.dataframe(metadata, hide_index=True, width="stretch")
        if center.empty:
            st.caption("Centro idéntico.")
        else:
            st.dataframe(center, hide_index=True, width="stretch")


st.title("Comparar")
st.warning("Una sola réplica de cada lado. Los intervalos de confianza llegan en el hito 9.")
render_compare_help()
store = catalog_store()
choices = [info.run_id for info in store.list()]
left, right = st.columns(2)
with left:
    loaded_a = render_side(store, "a", choices)
with right:
    loaded_b = render_side(store, "b", choices)
if loaded_a is None or loaded_b is None:
    for side, loaded in (("A", loaded_a), ("B", loaded_b)):
        if loaded is not None:
            st.subheader(f"Resultados disponibles de {side}")
            st.dataframe(
                kpis_frame(loaded[0].kpis)[["Indicador", "Valor", "Unidad"]],
                hide_index=True,
                width="stretch",
            )
    st.stop()
a, fingerprint_a = loaded_a
b, fingerprint_b = loaded_b
blockers = pairing_blockers(a, b)
if blockers:
    st.info(
        "No emparejada. Difieren: "
        + "; ".join(f"{METADATA_LABELS[d.field]}: {d.a} → {d.b}" for d in blockers)
        + ". Solo se comparan agregados: los identificadores no representan al mismo paciente."
    )
summary = compare_run_summary(a, b)
render_summary(summary, a.info.run_id, b.info.run_id)
