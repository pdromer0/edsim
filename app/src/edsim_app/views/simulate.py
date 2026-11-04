"""Edit raw center variants and inspect their derived clinical parameters."""

import re
from pathlib import Path

import streamlit as st

from edsim.runs import (
    MAX_VARIANT_NAME_LENGTH,
    RunConfigurationError,
    center_diff,
    center_from_values,
    list_variants,
    load_center,
    simulate_run,
    summarize_center,
    validate_center_values,
    validate_run_id,
    write_variant,
)
from edsim_app import defaults
from edsim_app.charts import duration_chart, offered_chart
from edsim_app.draft import (
    CenterDraft,
    accept_source,
    cancel_pending,
    choose_source,
    edit_run_id,
    execution_settings,
    load_source,
    source_is_current,
    update_setting,
    update_value,
    update_variant_name,
    use_run_suggestion,
)
from edsim_app.frames import (
    FIELDS,
    POOL_LABELS,
    SHIFTS,
    format_change_value,
    offered_frame,
    style_utilization,
    utilization_frame,
)
from edsim_app.help import render_simulate_help
from edsim_app.preview import preview_work
from edsim_app.state import catalog_store, sync_run_query


def decimal(value: float, digits: int = 1) -> str:
    """Format presentation numbers with a decimal comma."""
    return f"{value:.{digits}f}".replace(".", ",")


def has_editable_values(values: dict[str, object]) -> bool:
    """Check widget representations; semantic validation stays in the core."""
    for key, _, integer, labels in FIELDS:
        if key not in values:
            return False
        value = values[key]
        if labels:
            if not isinstance(value, list | tuple) or len(value) != len(labels):
                return False
            items = value
        else:
            items = (value,)
        allowed_types = (int,) if integer else (int, float)
        if any(type(item) not in allowed_types for item in items):
            return False
    return True


def render_number(
    draft: CenterDraft, key: str, label: str, integer: bool, index: int | None
) -> None:
    """Hydrate one widget with its fixed numeric type, without a value argument."""
    widget = f"edit_{key}_{index}"
    raw = draft.values[key] if index is None else draft.values[key][index]
    st.session_state[widget] = int(raw) if integer else float(raw)
    st.number_input(
        label,
        key=widget,
        step=1 if integer else (0.01 if "probabilidad" in key else 0.1),
        format="%d" if integer else "%.15g",
        on_change=update_value,
        args=(key, index, widget),
    )


def render_staff(draft: CenterDraft, errors: dict[str, str]) -> None:
    """Display three shift rows and the two staff columns."""
    st.subheader("Plantilla por turno")
    staff = (
        ("recursos.enfermeria_triaje", "Enfermería de triaje"),
        ("recursos.medicos", "Médicos"),
    )
    for column, label in zip(st.columns((1, 2, 2)), ("Turno", *(s[1] for s in staff)), strict=True):
        column.write(label)
    for index, shift in enumerate(SHIFTS):
        label_column, *columns = st.columns((1, 2, 2))
        label_column.write(shift.capitalize())
        for column, (key, label) in zip(columns, staff, strict=True):
            with column:
                render_number(draft, key, f"{label} · {shift}", True, index)
    _, *columns = st.columns((1, 2, 2))
    for column, (key, _) in zip(columns, staff, strict=True):
        if key in errors:
            column.error(errors[key])


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


def save_draft(draft: CenterDraft, destination: Path, overwrite: bool = False) -> None:
    """Publish from the source text and adopt the saved destination as source."""
    try:
        write_variant(draft.source, draft.values, destination, overwrite=overwrite)
    except FileExistsError:
        st.session_state.pending_overwrite = destination
    else:
        load_source(destination)
        st.session_state.draft_notice = f"Se ha guardado la variante «{destination.stem}»."
    st.rerun()


def render_center() -> tuple[CenterDraft, bool]:
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
    # Reject incompatible types before any int()/float() widget conversion.
    if not has_editable_values(draft.values):
        for message in errors.values():
            st.error(message)
        st.info(
            "Corrige los valores o la estructura del fichero fuera de la app "
            "y vuelve a cargar su origen."
        )
        st.stop()
    summary = summarize_center(draft.values) if not errors else None
    duration_summaries = {d.key: d for d in summary.durations} if summary else {}
    for key, label, integer, labels in FIELDS:
        if key == "recursos.enfermeria_triaje":
            render_staff(draft, errors)
            continue
        if key == "recursos.medicos":
            continue
        st.subheader(label)
        indices = range(len(labels)) if labels else (None,)
        columns = st.columns(len(labels)) if labels else (st.container(),)
        for column, index in zip(columns, indices, strict=True):
            with column:
                render_number(
                    draft,
                    key,
                    label if index is None else f"{label} · {labels[index]}",
                    integer,
                    index,
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
                field_labels = {key: label for key, label, _, _ in FIELDS}
                for change in differences:
                    st.write(
                        f"**{field_labels[change.key]}** · `{change.key}`: "
                        f"{format_change_value(change.before)} → "
                        f"{format_change_value(change.after)}"
                    )
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


def render_execution(draft: CenterDraft, blocked: bool, profile_valid: bool) -> None:
    """Simulate only a valid, current and saved on-disk configuration."""
    st.header("3. La ejecución")
    st.caption(f"Perfil de llegadas: {defaults.PROFILE_PATH}")
    settings = execution_settings()
    for field, label, widget, maximum in (
        ("days", "Días", "days_widget", 60),
        ("warmup_days", "Calentamiento (días)", "warmup_widget", settings["days"] - 1),
    ):
        st.session_state[widget] = settings[field]
        st.number_input(
            label,
            min_value=1 if field == "days" else 0,
            max_value=maximum,
            step=1,
            format="%d",
            key=widget,
            on_change=update_setting,
            args=(field, widget),
        )
    st.session_state.seed_widget = settings["seed"]
    seed_text = st.text_input(
        "Semilla", key="seed_widget", on_change=update_setting, args=("seed", "seed_widget")
    )
    seed_valid = re.fullmatch(r"[0-9]{1,20}", seed_text) is not None
    if not seed_valid:
        st.error(
            "La semilla debe contener entre 1 y 20 cifras ASCII (0–9), sin espacios ni signos."
        )
    store = catalog_store()
    suggestion = None
    if seed_valid:
        preferred = f"{draft.source.stem}-r{int(seed_text)}"
        suggestion = store.suggest_run_id(preferred)
        if suggestion is None:
            st.warning(
                "El identificador propuesto ya existe y no cabe un sufijo; escribe uno más corto."
            )
        elif suggestion != preferred:
            st.info(f"El identificador «{preferred}» ya existe. Se propone «{suggestion}».")
        if settings["run_id_mode"] == "automatic":
            settings["run_id"] = suggestion if suggestion is not None else preferred
    st.session_state.run_id_widget = settings["run_id"]
    run_id = st.text_input("Identificador de ejecución", key="run_id_widget", on_change=edit_run_id)
    st.caption(
        "Identificador automático"
        if settings["run_id_mode"] == "automatic"
        else "Identificador manual"
    )
    if settings["run_id_mode"] == "manual" and suggestion is not None and run_id != suggestion:
        st.caption(f"Propuesta actual: {suggestion}")
    st.button(
        "Usar propuesta",
        key="use_run_suggestion",
        disabled=suggestion is None,
        on_click=use_run_suggestion,
        args=(suggestion,),
    )
    try:
        validate_run_id(run_id)
    except ValueError as error:
        id_error = str(error)
    else:
        id_error = (
            f"El identificador «{run_id}» ya existe en el catálogo."
            if store.exists(run_id)
            else None
        )
    if id_error:
        st.error(id_error)
    if draft.dirty:
        st.info("Hay cambios sin guardar. Guarda una variante antes de simular.")
    if st.button(
        "Simular",
        key="simulate_run",
        type="primary",
        disabled=blocked or draft.dirty or not seed_valid or bool(id_error) or not profile_valid,
    ):
        with st.status("Simulando, guardando y comprobando la ejecución…", expanded=True) as status:
            try:
                result = simulate_run(
                    draft.source,
                    defaults.PROFILE_PATH,
                    settings["days"],
                    int(seed_text),
                    output_dir=store.root / run_id,
                    warmup_days=settings["warmup_days"],
                    run_id=run_id,
                    origin="app",
                )
            except FileExistsError:
                st.error(f"No se ha creado la ejecución: el identificador «{run_id}» ya existe.")
                status.update(label="No se ha creado la ejecución", state="error")
            except RunConfigurationError as error:
                st.error(f"No se ha podido cargar la configuración: {error}")
                status.update(label="Configuración no válida", state="error")
            else:
                status.update(label="Ejecución creada", state="complete", expanded=False)
                st.session_state.simulation_summary = result.info
                st.session_state.selected_run_id = result.info.run_id
                sync_run_query()
                st.rerun()
    if info := st.session_state.get("simulation_summary"):
        st.success(f"Ejecución creada: {info.run_id}")
        st.metric("Llegadas de la ventana", str(info.window_arrivals))
        st.metric("Violaciones", str(info.invariant_violations))
        st.metric("Segundos de simulación", decimal(info.simulation_seconds, 3))
        if st.button("Ver resultados", key="view_results"):
            st.session_state.selected_run_id = info.run_id
            st.switch_page("views/results.py", query_params={"run": info.run_id})


st.title("Simular")
draft, blocked = render_center()

st.header("2. La carga prevista")
profile_valid = False
if not validate_center_values(draft.values):
    try:
        work = preview_work(draft.values, defaults.PROFILE_PATH)
    except RunConfigurationError as error:
        st.error(f"No se puede cargar el perfil de llegadas: {error}")
        render_simulate_help()
    else:
        profile_valid = True
        st.caption(
            f"Perfil: {defaults.PROFILE_PATH}. Ventana prevista: 7 días; medias de 15 minutos."
        )
        pool = st.selectbox(
            "Recurso", list(POOL_LABELS), format_func=POOL_LABELS.get, key="preview_pool"
        )
        st.altair_chart(offered_chart(offered_frame(work, pool)), width="stretch")
        st.dataframe(style_utilization(utilization_frame(work)), hide_index=True, width="stretch")
        render_simulate_help(work.prior_days)
else:
    st.info("Corrige los errores del centro para calcular la carga prevista.")
    render_simulate_help()

render_execution(draft, blocked, profile_valid)
