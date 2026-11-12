"""Short explanations of the concepts shown on each app page."""

import streamlit as st


def render_episodes_help() -> None:
    """Explain exclusive cohorts, right censoring and independent laboratory work."""
    with st.expander("¿Qué estoy viendo?"):
        st.write(
            "El nivel mostrado es el asignado; el real y G solo aparecen al ver la verdad. "
            "Edad, sexo, medio, motivo y pruebas proceden del log. "
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
            "La sala de resultados está fuera del box; se distinguen la espera inicial "
            "de box y la espera al volver. "
            "Las pruebas siguen aunque pierda el box: su banda es independiente y los "
            "rombos marcan desalojos. Todas las horas son UTC+1 fijo, sin horario de verano."
        )
        st.write(
            "«Ver la verdad» compara sorteos con observaciones: suma todas las partes de "
            "una valoración interrumpida. Una etapa puede coincidir, discrepar, ser parcial, "
            "estar pendiente o no usarse. Una etapa parcial no debe superar lo sorteado; "
            "la tolerancia absoluta es 0,00000001 minutos, sin tolerancia relativa."
        )
        st.write(
            "Con el modelo del hito 5, un paciente puede irse sin ser visto antes del primer "
            "médico: esperando el triaje, esperando box o esperando médico en el box. Sus "
            "relojes quedan vacíos y lo que ya no alcanzará (valoración, pruebas, destino) "
            "sale como «no usada»: su destino sorteado es el que habría tenido. Un ingresado "
            "pide cama y la espera en su box, que queda bloqueado; si un nivel 1 lo desaloja, "
            "la espera en el pasillo. Los filtros del desenlace solo aparecen con esas ejecuciones."
        )


def render_results_help() -> None:
    """Explain the two populations and the limitations of replaying invariants."""
    with st.expander("¿Qué estoy viendo?"):
        st.write(
            "Las llegadas y el censo incluyen a quienes siguen dentro. Las esperas usan "
            "episodios llegados en la ventana y completados. Los niveles son los asignados. "
            "Los tres relojes miden hasta el primer médico: A desde la puerta, B desde el "
            "inicio del triaje y C desde la clasificación. Manchester se mide con C; "
            "quien ve al médico justo en el máximo cumple. Un día está fuera si cumple menos "
            "del 90 %."
        )
        st.write(
            "Con el abandono del hito 5, las medias de los relojes son de los atendidos. En el "
            "cumplimiento, quien se va después de su máximo (o justo en él) cuenta como "
            "incumplimiento; quien se va antes no cuenta: está censurado, porque no sabemos si "
            "lo habrían visto a tiempo. Ejemplo: tres pacientes de nivel 4 (máximo 120 min) "
            "ven al médico a los 30 y a los 90 y el tercero se va a los 150. El cumplimiento "
            "es 2 de 3, el 66,7 %; quitarlo daría un 100 %, como si irse mejorara el servicio."
        )
        st.write(
            "El desenlace da el abandono sobre las llegadas (antes y después del triaje, los "
            "dos indicadores de SEMES), los destinos, la espera de cama y la estancia por "
            "destino. «≥» marca una cota inferior: hay ingresados que siguen esperando cama al "
            "final y su espera será mayor. En los umbrales (6, 12 y 24 h) el porcentaje es "
            "sobre los conocidos; los que siguen esperando sin haber llegado al umbral van "
            "aparte, «sin saber». «Ver la verdad» enseña lo que solo sabe el simulador: el "
            "nivel real, los graves que se fueron y los que habrían ingresado."
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
            "Cada ejecución muestra el modelo que usó y guarda los eventos, la verdad "
            "del simulador y los metadatos. Conserva una copia exacta de la configuración "
            "para poder reproducirla aunque cambien los originales; una clínica guarda "
            "también la copia de sus perfiles y su huella."
        )
        st.write(
            "Las ejecuciones provisionales del hito 3 se siguen abriendo, pero la app "
            "ya no las crea. Una carpeta no válida no se puede abrir porque sus metadatos "
            "faltan, no son compatibles o su ruta no cumple las reglas."
        )


def render_simulate_help(prior_days: int | None = None) -> None:
    """Distinguish regime predictions from a run that starts empty."""
    with st.expander("¿Qué estoy viendo?"):
        st.write(
            "Las ejecuciones nuevas usan el modelo clínico. Cada paciente sale de los "
            "perfiles: edad, sexo, medio de llegada, motivo, gravedad, triaje con error, "
            "pruebas y duraciones."
        )
        st.write(
            "Del centro solo cuentan turnos, plantilla, boxes, los niveles que esperan "
            "los resultados fuera del box y la probabilidad de ingreso o, con un centro del "
            "hito 5 ([camas]), la espera de cama: [mediana, p90] y el factor del turno del "
            "pedido (y de la estación, si el fichero lo trae). El resumen de los "
            "perfiles muestra su expectativa anual, no lo que dará una ejecución."
        )
        st.write(
            "La carga prevista sale de una muestra de pacientes del modelo clínico. "
            "Tarda unos segundos la primera vez y se reutiliza al cambiar la plantilla. "
            "Quien espera los resultados fuera no ocupa box durante esa espera."
        )
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
            "Compartir semilla, perfil de llegadas, días, calentamiento y modelo permite "
            "emparejar pacientes. Plantilla conserva los mismos pacientes; el emparejamiento "
            "clínico usa los mismos sorteos estándar con otros perfiles y puede cambiar "
            "los valores clínicos; la tabla de perfiles dice qué claves cambian. Modelos "
            "distintos quedan sin emparejar, también un hito 4 frente a un hito 5 (otra "
            "versión del catálogo). "
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


def render_replay_help() -> None:
    """Explain the plan's zones, the hallway mark and the abandonment as a separate closure."""
    with st.expander("¿Qué estoy viendo?"):
        st.write(
            "El plano reconstruye el servicio en el instante elegido: colas, triaje, boxes, "
            "médicos y las salidas de la última hora. Los colores son el nivel asignado."
        )
        st.write(
            "Con el modelo del hito 5, un ingresado espera la cama en su box («Esperando "
            "cama»), que sigue ocupado. Si un nivel 1 lo desaloja, la espera en el pasillo: "
            "el estado dice qué hace y la marca, dónde está. Quien se va sin ser visto no es "
            "una salida: se cuenta aparte, en la última hora."
        )
