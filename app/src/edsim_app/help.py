"""Short explanations of the concepts shown on each app page."""

import streamlit as st


def render_runs_help() -> None:
    """Explain persisted runs, reproducibility, and invalid catalog entries."""
    with st.expander("¿Qué estoy viendo?"):
        st.write(
            "Una ejecución guarda los eventos, la verdad del simulador y los metadatos "
            "de una simulación. Conserva una copia exacta de la configuración para "
            "poder reproducirla aunque cambien los originales. Una carpeta no válida "
            "no se puede abrir como ejecución porque sus metadatos faltan, no son "
            "compatibles o su ruta no cumple las reglas."
        )
