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


def render_simulate_help(prior_days: int | None = None) -> None:
    """Distinguish regime predictions from a run that starts empty."""
    with st.expander("¿Qué estoy viendo?"):
        st.write(
            "La carga prevista muestra los recursos que la demanda ocuparía sin colas, "
            "en régimen y sin el efecto diario aleatorio Z. Una ejecución empieza vacía "
            "y utiliza sus propios días de calentamiento; la carga de boxes no incluye "
            "las esperas que mantienen un box ocupado. Entre 0,85 y 1 las esperas pueden "
            "crecer deprisa (umbral orientativo); por encima de 1 la carga supera la capacidad."
        )
        if prior_days is not None and prior_days > 1:
            st.write(
                f"Se han calculado {prior_days} días previos para incluir el trabajo de "
                "pacientes llegados antes de la ventana: un solo día no bastaría para "
                "las duraciones más largas de la muestra."
            )
