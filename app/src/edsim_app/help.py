"""Short explanations of the concepts shown on each app page."""

import streamlit as st


def render_episodes_help() -> None:
    """Explain exclusive cohorts, right censoring and independent laboratory work."""
    with st.expander("¿Qué estoy viendo?"):
        st.write(
            "La tabla incluye todos los episodios: sin terminar si no hay salida; "
            "calentamiento si llegaron antes de su fin y salieron; ventana si llegaron "
            "desde ese límite y salieron. Los filtros se combinan y se conservan entre ejecuciones."
        )
        st.write(
            "Cuando estancia o puerta-médico aún no se conocen, el filtro usa el tiempo "
            "hasta el horizonte como cota inferior: solo pasa si ya supera el umbral. "
            "La tabla conserva «—» en el valor desconocido y muestra el tiempo observado."
        )
        st.write(
            "Los tramos muestran dónde está el paciente y suman su estancia observada. "
            "Las pruebas siguen aunque pierda el box: su banda es independiente y los "
            "rombos marcan desalojos. Todas las horas son UTC+1 fijo, sin horario de verano."
        )
        st.write(
            "«Ver la verdad» compara sorteos con observaciones: suma todas las partes de "
            "una valoración interrumpida. Una etapa puede coincidir, discrepar, ser parcial, "
            "estar pendiente o no usarse. Una etapa parcial no debe superar lo sorteado; "
            "la tolerancia absoluta es 0,00000001 minutos, sin tolerancia relativa."
        )


def render_results_help() -> None:
    """Explain the two populations and the limitations of replaying invariants."""
    with st.expander("¿Qué estoy viendo?"):
        st.write(
            "Las llegadas y el censo incluyen a quienes siguen dentro. Las esperas usan "
            "episodios llegados en la ventana y completados. Los niveles son los asignados. "
            "Los tres relojes miden hasta el primer médico: A desde la puerta, B desde el "
            "inicio del triaje y C desde la clasificación. Manchester se mide con C; "
            "justo en el máximo cumple. Un día está fuera si cumple menos del 90 %."
        )
        st.write(
            "El pretriaje tiene su indicador: 10 minutos o menos (objetivo diario 85 %) "
            "y más de 5 minutos; excluye el nivel 1. El nivel 1 se informa con mediana y p90, "
            "sin porcentaje. «—» significa que no hay pacientes para esa estadística. "
            "El reparto observado incluye las llegadas de la ventana, también sin terminar; "
            "nunca usa niveles reales del ground truth."
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


def render_compare_help() -> None:
    """Explain common random numbers, conditional populations and signed changes."""
    with st.expander("¿Qué estoy viendo?"):
        st.write(
            "A es la referencia y las diferencias son B − A. En tiempos, una diferencia "
            "negativa mejora y una positiva empeora. El cambio relativo divide por A; "
            "«—» indica base cero o dato desconocido. Ingreso cambia en puntos porcentuales."
        )
        st.write(
            "Compartir semilla, perfil, días y calentamiento permite emparejar pacientes. "
            "La verdad comprueba sus llegadas y sorteos: cambiar plantilla conserva los "
            "números aleatorios comunes; cambiar clínica puede cambiar algunos sorteos, "
            "aunque en una muestra pequeña no cambie ninguno."
        )
        st.write(
            "Los KPIs de tiempo y Manchester usan completados de cada lado. La comparación "
            "por paciente usa solo llegados en ventana que terminan en ambas; los excluidos "
            "pueden sesgar el resultado. Igual significa diferencia absoluta de hasta "
            "0,00000001 minutos. Los histogramas muestran solo a quienes mejoran o empeoran; "
            "los iguales se cuentan aparte."
        )
