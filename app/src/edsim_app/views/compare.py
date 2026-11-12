"""Choose independent runs and present core-computed comparison summaries."""

import pandas as pd
import streamlit as st

from edsim.runs import (
    PairingCheckError,
    RunAnalysisError,
    RunComparison,
    RunReadError,
    RunResults,
    RunStore,
    RunSummaryComparison,
    compare_run_summary,
    pairing_blockers,
    pairing_category,
    profiles_diff,
    read_run_header,
    read_run_profiles_values,
)
from edsim_app.charts import difference_histogram_chart
from edsim_app.comparison import cached_run_comparison
from edsim_app.comparison_frames import (
    DRAW_LABELS,
    METADATA_LABELS,
    affected_episodes_frame,
    clinical_differences_frame,
    comparison_configuration_frames,
    comparison_kpis_frame,
    comparison_levels_frame,
    difference_histogram_frame,
    draw_differences_frame,
    profiles_differences_frame,
)
from edsim_app.episodes import open_comparison_episode
from edsim_app.frames import format_number, kpis_frame, model_label
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
        st.caption(f"Modelo: {model_label(info)}")
        if info.is_clinical:
            st.caption(f"Perfiles: {info.clinical_profiles_path}")
            st.caption(f"Huella de perfiles clínicos: {info.clinical_profiles_fingerprint}")
        result = cached_run_results(str(store.root), marked, fingerprint)
    except (RunReadError, RunAnalysisError) as error:
        st.error(f"Lado {side.upper()}: {error}")
        return None
    return result, fingerprint


def render_summary(
    summary: RunSummaryComparison,
    a_id: str,
    b_id: str,
    *,
    clinical: bool = False,
    profiles: pd.DataFrame | None = None,
) -> None:
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
    st.subheader("Esperas por nivel y Manchester desde la clasificación (C)")
    st.dataframe(comparison_levels_frame(summary), hide_index=True, width="stretch")
    metadata, center = comparison_configuration_frames(summary, clinical=clinical)
    with st.expander("Diferencias de configuración y metadatos", expanded=True):
        if metadata.empty:
            st.caption("Metadatos idénticos.")
        else:
            st.dataframe(metadata, hide_index=True, width="stretch")
        if center.empty:
            st.caption("Centro idéntico.")
        else:
            st.dataframe(center, hide_index=True, width="stretch")
        if profiles is not None:
            if profiles.empty:
                st.caption("Perfiles clínicos idénticos.")
            else:
                st.dataframe(profiles, hide_index=True, width="stretch")


@st.fragment(key="comparison_patients")
def render_patients(
    comparison: RunComparison,
    identity_a: tuple[str, str, str],
    identity_b: tuple[str, str, str],
) -> None:
    """Render supplied patient differences; links navigate without recomputing the pair."""
    st.subheader("Paciente a paciente")
    excluded = comparison.excluded
    st.caption(
        f"Terminan solo en A: {excluded.only_a} · "
        f"Terminan solo en B: {excluded.only_b} · "
        f"No terminan en ninguna: {excluded.neither}."
    )
    if excluded.only_a or excluded.only_b or excluded.neither:
        st.warning(
            "Los excluidos no entran en las diferencias. Quienes siguen dentro "
            "en la ejecución más saturada suelen ser los peores: excluirlos sesga "
            "la comparación de quienes sí terminaron."
        )
    if not comparison.episodes:
        st.info("No hay episodios llegados en la ventana que terminen en ambas ejecuciones.")
        return
    for difference in comparison.differences:
        label = "Estancia" if difference.measure == "stay" else "Puerta-médico"
        st.subheader(f"Diferencia de {label.lower()}: B − A")
        st.caption(f"{difference.n} pacientes completados en ambas.")
        for column, title, count, share in zip(
            st.columns(3),
            ("Mejoran", "Empeoran", "Iguales"),
            (difference.improved, difference.worsened, difference.unchanged),
            (difference.improved_share, difference.worsened_share, difference.unchanged_share),
            strict=True,
        ):
            column.metric(f"{label}: {title}", f"{count} ({format_number(share, percentage=True)})")
        if difference.histogram:
            st.altair_chart(
                difference_histogram_chart(difference_histogram_frame(difference)), width="stretch"
            )
        else:
            st.info(f"{label}: todos quedan iguales dentro de la tolerancia.")
    st.subheader("Los 10 más afectados por estancia")
    st.dataframe(affected_episodes_frame(comparison), hide_index=True, width="stretch")
    for episode in comparison.most_affected:
        label, left, right = st.columns([3, 1, 1])
        label.write(episode.episode_id)
        for side, column, identity in (("A", left, identity_a), ("B", right, identity_b)):
            if column.button(f"Abrir en {side}", key=f"compare_open_{side}_{episode.episode_id}"):
                open_comparison_episode(identity, episode.episode_id)


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
category = pairing_category(a, b)
blockers = pairing_blockers(a, b)
st.caption(
    "Tipo de emparejamiento: "
    + {
        "template": "Plantilla · mismos pacientes",
        "clinical": "Clínico · mismos sorteos estándar con otros perfiles",
        "unpaired": "Sin emparejar · solo el resumen",
    }[category]
)
if category == "unpaired":
    st.info(
        "No emparejada. Difieren: "
        + "; ".join(f"{METADATA_LABELS[d.field]}: {d.a} → {d.b}" for d in blockers)
        + ". Solo se comparan agregados: los identificadores no representan al mismo paciente."
    )
comparison = None
if category == "unpaired":
    summary = compare_run_summary(a, b)
else:
    try:
        comparison = cached_run_comparison(
            str(store.root),
            a.info.run_id,
            fingerprint_a,
            b.info.run_id,
            fingerprint_b,
        )
    except (RunReadError, PairingCheckError) as error:
        st.error(
            f"No se ha podido comprobar el emparejamiento: {error}. "
            "simulate_run siempre escribe el ground truth; "
            "la carpeta se ha modificado fuera de la app. "
            "Se conservan los agregados del log; la comparación por paciente queda bloqueada."
        )
        summary = compare_run_summary(a, b)
    else:
        summary = comparison.summary
        if category == "clinical":
            st.success(
                "Emparejada clínicamente: mismos sorteos estándar con otros perfiles, "
                "comprobados con la verdad."
            )
            st.warning("La diferencia puede mezclar los efectos de los perfiles y de la plantilla.")
        elif comparison.pairing.kind == "same_draws":
            st.success("Emparejada con los mismos sorteos, comprobados con la verdad.")
        else:
            st.success("Emparejada con sorteos distintos, comprobados con la verdad.")
            changed = [
                f"{DRAW_LABELS[d.field]}: {d.changed} pacientes"
                for d in comparison.pairing.draw_differences
                if d.changed
            ]
            st.warning(
                "La diferencia mezcla el efecto de los parámetros clínicos "
                "y de la plantilla. Sorteos que cambian: "
                + ("; ".join(changed) if changed else "ninguno en esta muestra (0 pacientes)")
                + ". La categoría se conserva por los parámetros modificados."
            )
both_clinical = a.info.is_clinical and b.info.is_clinical
profiles = None
if both_clinical:
    try:
        profiles = profiles_differences_frame(
            profiles_diff(
                read_run_profiles_values(store, a.info.run_id),
                read_run_profiles_values(store, b.info.run_id),
            )
        )
    except RunReadError as error:
        st.error(str(error))
render_summary(summary, a.info.run_id, b.info.run_id, clinical=both_clinical, profiles=profiles)
if comparison is not None:
    st.subheader("Comprobación de los sorteos (verdad)")
    if comparison.pairing.clinical_differences:
        st.dataframe(
            clinical_differences_frame(comparison.pairing), hide_index=True, width="stretch"
        )
    st.dataframe(draw_differences_frame(comparison.pairing), hide_index=True, width="stretch")
    render_patients(
        comparison,
        (str(store.root), a.info.run_id, fingerprint_a),
        (str(store.root), b.info.run_id, fingerprint_b),
    )
