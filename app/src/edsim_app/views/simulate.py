"""Edit raw center variants and inspect their derived clinical parameters."""

from pathlib import Path

import streamlit as st

from edsim.runs import (
    MAX_VARIANT_NAME_LENGTH,
    center_diff,
    center_from_values,
    list_variants,
    load_center,
    summarize_center,
    validate_center_values,
    validate_run_id,
    write_variant,
)
from edsim_app import defaults
from edsim_app.charts import duration_chart
from edsim_app.draft import (
    accept_source,
    cancel_pending,
    choose_source,
    load_source,
    source_is_current,
    update_value,
    update_variant_name,
)

SHIFTS = ("mañana", "tarde", "noche")
LEVELS = tuple(f"nivel {i}" for i in range(1, 6))
FIELDS = (
    ("turnos.inicio", "Inicio de los turnos (horas)", True, SHIFTS),
    ("recursos.enfermeria_triaje", "Enfermería de triaje", True, SHIFTS),
    ("recursos.medicos", "Médicos", True, SHIFTS),
    ("recursos.boxes", "Boxes", True, ()),
    ("triaje.reparto_niveles", "Reparto de triaje (pesos)", False, LEVELS),
    ("duraciones.triaje", "Duración de triaje (min)", False, ("mediana", "p90")),
    ("duraciones.valoracion", "Duración de valoración (min)", False, ("mediana", "p90")),
    ("duraciones.reevaluacion", "Duración de reevaluación (min)", False, ("mediana", "p90")),
    ("duraciones.respuesta_pruebas", "Respuesta de pruebas (min)", False, ("mediana", "p90")),
    ("pruebas.probabilidad", "Probabilidad de pruebas", False, LEVELS),
    ("destino.probabilidad_ingreso", "Probabilidad de ingreso", False, LEVELS),
)


def decimal(value: float, digits: int = 1) -> str:
    """Format presentation numbers with a decimal comma."""
    return f"{value:.{digits}f}".replace(".", ",")


def variant_error(name: str) -> str | None:
    """Adapt public filename rules and reserve the base center's name."""
    if name == "centro":
        return "El nombre «centro» está reservado al centro base; elige otro nombre."
    try:
        validate_run_id(name)
    except ValueError as error:
        return str(error)
    if len(name) > MAX_VARIANT_NAME_LENGTH:
        return f"El nombre debe tener como máximo {MAX_VARIANT_NAME_LENGTH} caracteres."
    return None


def save_draft(draft, destination: Path, overwrite: bool = False) -> None:
    """Publish from the source text and adopt the saved destination as source."""
    try:
        write_variant(draft.source, draft.values, destination, overwrite=overwrite)
    except FileExistsError:
        st.session_state.pending_overwrite = destination
    else:
        load_source(destination)
        st.session_state.draft_notice = f"Se ha guardado la variante «{destination.stem}»."
    st.rerun()


def render_center():
    """Render the durable raw draft and return its current blocking state."""
    st.header("1. El centro")
    if "center_draft" not in st.session_state:
        try:
            load_source(defaults.CENTER_PATH)
        except (OSError, ValueError) as error:
            st.error(f"No se puede leer el centro base: {error}")
            st.stop()
    draft = st.session_state.center_draft
    sources = [defaults.CENTER_PATH, *list_variants(defaults.VARIANTS_DIR)]
    if draft.source not in sources:
        sources.append(draft.source)
    st.session_state.source_widget = str(draft.source)
    st.selectbox(
        "Origen del centro",
        [str(p) for p in sources],
        key="source_widget",
        format_func=lambda p: "Centro base" if Path(p) == defaults.CENTER_PATH else Path(p).stem,
        on_change=choose_source,
    )
    if pending := st.session_state.get("pending_source"):
        st.warning(f"Hay cambios sin guardar. ¿Descartarlos y cargar «{pending.stem}»?")
        st.button(
            "Descartar cambios y cambiar",
            key="confirm_source",
            on_click=accept_source,
            args=(pending,),
        )
        st.button(
            "Cancelar cambio de origen",
            key="cancel_source",
            on_click=cancel_pending,
            args=("pending_source",),
        )
    if notice := st.session_state.pop("source_notice", None):
        st.error(notice)
    if notice := st.session_state.pop("draft_notice", None):
        st.success(notice)
    current = source_is_current(draft)
    if not current:
        st.warning(
            "El origen ha cambiado, no existe o no se puede leer fuera de la app. "
            "Se conserva el borrador; cambia de origen para cargar una copia actual."
        )
    st.caption(f"Fichero de origen: {draft.source}")
    st.caption("Cambios sin guardar" if draft.dirty else "Todos los cambios están guardados")
    errors = validate_center_values(draft.values)
    # A malformed external TOML cannot be represented by the fixed editor.
    if any(
        key not in draft.values
        or (
            labels
            and (
                not isinstance(draft.values[key], list | tuple)
                or len(draft.values[key]) != len(labels)
            )
        )
        for key, _, _, labels in FIELDS
    ):
        for message in errors.values():
            st.error(message)
        st.info("Corrige la estructura del fichero fuera de la app y vuelve a cargar su origen.")
        st.stop()
    summary = summarize_center(draft.values) if not errors else None
    duration_summaries = {d.key: d for d in summary.durations} if summary else {}
    for key, label, integer, labels in FIELDS:
        st.subheader(label)
        indices = range(len(labels)) if labels else (None,)
        columns = st.columns(len(labels)) if labels else (st.container(),)
        for column, index in zip(columns, indices, strict=True):
            with column:
                widget = f"edit_{key}_{index}"
                raw = draft.values[key] if index is None else draft.values[key][index]
                st.session_state[widget] = int(raw) if integer else float(raw)
                step = 1 if integer else (0.01 if "probabilidad" in key else 0.1)
                st.number_input(
                    label if index is None else f"{label} · {labels[index]}",
                    key=widget,
                    step=step,
                    format="%d" if integer else "%.17g",
                    on_change=update_value,
                    args=(key, index, widget),
                )
        if key in errors:
            st.error(errors[key])
        if key in duration_summaries:
            duration = duration_summaries[key]
            st.caption(f"Media: {decimal(duration.mean_minutes)} min")
            st.altair_chart(duration_chart(duration), width="stretch")
    for key in errors.keys() - {field[0] for field in FIELDS}:
        st.error(errors[key])
    if summary:
        st.write(f"Suma del reparto: {decimal(summary.raw_share_total)}")
        st.write(
            "Reparto normalizado: "
            + "; ".join(f"{s:.3%}".replace(".", ",") for s in summary.normalized_level_shares)
        )
        st.metric("Pruebas globales", f"{decimal(summary.tests_percentage, 3)} %")
        st.metric("Ingreso global", f"{decimal(summary.admission_percentage, 3)} %")
        st.subheader("Cambios frente al centro base")
        try:
            base = load_center(defaults.CENTER_PATH)
        except (OSError, ValueError) as error:
            st.error(f"No se puede comparar con el centro base: {error}")
        else:
            differences = center_diff(base, center_from_values(draft.values))
            if differences:
                for change in differences:
                    st.write(f"{change.key}: {change.before} → {change.after}")
            else:
                st.info("No hay diferencias frente al centro base.")
    else:
        st.info("Corrige los errores para mostrar los números derivados y la carga prevista.")
    st.session_state.variant_name_widget = st.session_state.variant_name
    name = st.text_input(
        "Nombre de la variante", key="variant_name_widget", on_change=update_variant_name
    )
    name_error = variant_error(name)
    if name_error and name:
        st.error(name_error)
    blocked = bool(errors) or not current
    if st.button("Guardar como variante", key="save_variant", disabled=blocked or bool(name_error)):
        destination = defaults.VARIANTS_DIR / f"{name}.toml"
        if destination.exists() or destination.is_symlink():
            st.session_state.pending_overwrite = destination
            st.rerun()
        save_draft(draft, destination)
    if pending := st.session_state.get("pending_overwrite"):
        st.warning(f"Ya existe «{pending.stem}». ¿Sobrescribir esta variante?")
        if st.button("Confirmar sobrescritura", key="confirm_overwrite", disabled=blocked):
            save_draft(draft, pending, overwrite=True)
        st.button(
            "Cancelar sobrescritura",
            key="cancel_overwrite",
            on_click=cancel_pending,
            args=("pending_overwrite",),
        )
    return draft, blocked


st.title("Simular")
draft, blocked = render_center()
