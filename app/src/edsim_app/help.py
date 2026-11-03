"""Short explanations of the concepts shown on each app page."""

import streamlit as st


def render_results_help() -> None:
    """Explain the two populations and the limitations of replaying invariants."""
    with st.expander("¿Qué estoy viendo?"):
        st.write(
            "Las llegadas y el censo usan toda la ventana sin calentamiento, incluidos "
            "los pacientes que siguen dentro al final. Las esperas, estancias, desalojos "
            "e ingresos usan solo episodios que llegan en la ventana y salen. «—» indica "
            "una estadística sin pacientes. El nivel 1 exige atención inmediata (0 minutos). "
            "Manchester mide puerta-médico: exactamente "
            "en el máximo cumple; los días fuera de objetivo tienen menos del 90 % de "
            "pacientes dentro del máximo y se cuentan solo días con pacientes del nivel."
        )
        st.write(
            "Dos subcomprobaciones de conservación solo existen durante la simulación: "
            "llegadas frente al ground truth y procesos vivos en SimPy (inside). Al "
            "recalcular desde el log no se pueden repetir; el recuento puede diferir "
            "del guardado. El cero guardado conserva la comprobación completa original."
        )
        st.write(
            "La ley de Little compara L (pacientes medios) con λ·W (llegadas por minuto "
            "por tiempo medio en minutos). Una ventana finita puede dar diferencias "
            "porque sus bordes cortan episodios."
        )


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
