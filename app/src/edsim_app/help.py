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
            "Las llegadas y el censo usan toda la ventana sin calentamiento, incluidos "
            "los pacientes que siguen dentro al final. Las esperas, estancias, desalojos "
            "e ingresos usan solo episodios que llegan en la ventana y salen. «—» indica "
            "una estadística sin pacientes. El nivel 1 exige atención inmediata (0 minutos). "
            "Manchester mide puerta-médico: exactamente "
            "en el máximo cumple; los días fuera de objetivo tienen menos del 90 % de "
            "pacientes dentro del máximo y se cuentan solo días con pacientes del nivel."
        )
        st.write(
            "Puerta-médico incluye la espera de triaje y el propio triaje. Por eso el "
            "nivel 1 («inmediato», 0 minutos) nunca cumple en el modelo actual: sus "
            "pacientes superan el máximo y sus días con pacientes salen al 100 % fuera "
            "de objetivo. Es el hallazgo del hito 3 sobre el nivel 1 sin prioridad en "
            "el triaje, pendiente de resolver en el hito 4."
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
