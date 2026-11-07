"""Browse persisted runs and act on an explicitly selected catalog entry."""

from functools import partial

import streamlit as st

from edsim.runs import RunConfigurationError, RunStore, simulate_run, validate_run_id
from edsim_app import defaults
from edsim_app.frames import runs_frame, style_runs
from edsim_app.help import render_runs_help
from edsim_app.state import catalog_store, choose_run, forget_run


def mark_run(key: str, run_id: str) -> None:
    """Remember a comparison choice independently of the selection widget."""
    st.session_state[key] = run_id


def request_delete(run_id: str) -> None:
    """Keep the exact identifier that the user must confirm."""
    st.session_state.pending_delete = run_id


def cancel_delete() -> None:
    """Discard the pending deletion without touching the catalog."""
    st.session_state.pop("pending_delete", None)


def delete_run(store: RunStore, run_id: str) -> None:
    """Delete through the public store and clear only references to this run."""
    store.delete(run_id)
    forget_run(run_id)
    st.session_state.catalog_notice = f"Se ha borrado la ejecución «{run_id}»."


def render_invalid(store: RunStore) -> None:
    """Show diagnostics and offer deletion only for admissible directory names."""
    invalid = store.invalid()
    if not invalid:
        return
    with st.expander("Carpetas no válidas"):
        for name, reason in invalid:
            st.write(f"**{name}** — Motivo: {reason}")
            try:
                validate_run_id(name)
            except ValueError:
                allowed = False
            else:
                allowed = not (store.root / name).is_symlink()
            if allowed:
                st.button(
                    f"Borrar carpeta «{name}»",
                    key=f"delete_invalid_{name}",
                    on_click=request_delete,
                    args=(name,),
                )
            else:
                st.caption(
                    "Esta carpeta tiene un nombre fuera de la regla o es un enlace simbólico. "
                    "Debes borrarla a mano fuera de la app."
                )


st.title("Ejecuciones")
store = catalog_store()
st.caption(f"Carpeta del catálogo: {store.root}")
render_runs_help()
if notice := st.session_state.pop("catalog_notice", None):
    st.success(notice)

runs = store.list()
if runs:
    st.dataframe(style_runs(runs_frame(runs)), hide_index=True, width="stretch")
    run_ids = [info.run_id for info in runs]
    selected = st.session_state.selected_run_id
    st.selectbox(
        "Ejecución",
        run_ids,
        index=run_ids.index(selected) if selected in run_ids else None,
        placeholder="Elige una ejecución",
        key="run_choice",
        on_change=choose_run,
    )
    if selected in run_ids:
        for title, filename in (
            ("Resultados", "results"),
            ("Episodios", "episodes"),
            ("Replay", "replay"),
        ):
            if st.button(f"Abrir en {title}", key=f"open_{filename}"):
                st.switch_page(f"views/{filename}.py", query_params={"run": selected})
        st.button("Marcar como A", key="mark_a", on_click=mark_run, args=("compare_a", selected))
        st.button("Marcar como B", key="mark_b", on_click=mark_run, args=("compare_b", selected))
        st.download_button(
            "Descargar zip",
            data=partial(store.archive, selected),
            file_name=f"{selected}.zip",
            mime="application/zip",
            on_click="ignore",
            key="download_run",
        )
        st.button("Borrar ejecución", key="delete_run", on_click=request_delete, args=(selected,))
else:
    st.info("No hay ejecuciones válidas en este catálogo.")
    if st.button(
        f"Simular el centro base ({defaults.BASE_DAYS} días, semilla 2026)",
        key="simulate_base",
        type="primary",
    ):
        with st.status("Simulando y guardando el centro base…", expanded=True) as status:
            try:
                result = simulate_run(
                    "config/centro.toml",
                    "config/llegadas.toml",
                    defaults.BASE_DAYS,
                    2026,
                    output_dir=store.root / "r2026",
                    warmup_days=defaults.BASE_WARMUP_DAYS,
                    run_id="r2026",
                    origin="app",
                    profiles="config/perfiles.toml",
                )
            except FileExistsError:
                st.error(
                    "No se ha creado la ejecución: el nombre «r2026» ya existe en el catálogo."
                )
                status.update(label="No se ha creado la ejecución", state="error")
            except RunConfigurationError as error:
                st.error(f"No se ha podido cargar la configuración: {error}")
                status.update(label="Configuración no válida", state="error")
            else:
                status.update(label="Ejecución creada", state="complete", expanded=False)
                st.session_state.selected_run_id = result.info.run_id
                st.session_state.catalog_notice = (
                    f"Se ha creado la ejecución «{result.info.run_id}»."
                )
                st.rerun()

render_invalid(store)
if pending := st.session_state.get("pending_delete"):
    with st.container(border=True):
        st.warning(f"¿Borrar «{pending}» y todos sus ficheros? Esta acción es definitiva.")
        st.button(
            "Confirmar borrado",
            key="confirm_delete",
            on_click=delete_run,
            args=(store, pending),
        )
        st.button("Cancelar", key="cancel_delete", on_click=cancel_delete)
