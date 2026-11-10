# App web — fase 1

La app web de EDsim crece por fases: una app local en Streamlit al cerrar el hito 3, un paso pequeño en cada hito y una aplicación completa, con API y frontend propio, después de la v0. Esta pestaña recoge esa decisión y especifica la fase 1.

## Decisión y estrategia

La app no espera a la v0, pero tampoco se construye entera ahora: empieza pequeña al cerrar el hito 3 y crece con el modelo (decisión candidata 31). Así se ve el modelo pronto, sin rehacer la app cuando los hitos 4, 5 y 6 cambien el paciente, los eventos y la arquitectura.

- **A favor de empezar pronto:** ver el servicio descubre fallos que una tabla de métricas esconde, obliga a mantener la lógica en el paquete y da un resultado visible en cada hito.
- **En contra de hacerla completa ahora:** el retrabajo, y que un frontend propio (React, WebSockets) es otro stack que desviaría el foco de la simulación y la estadística.

| Fase | Cuándo | Qué es | Tecnología |
| --- | --- | --- | --- |
| 1 | Al cerrar el hito 3 | App local por lotes: ejecuciones, simular, resultados, episodios, comparar y replay | Streamlit sobre el paquete, sin API |
| Incrementos | Una tarea en los hitos 4, 5, 7, 9 y 10 | Lo nuevo de cada hito, en la misma app | Streamlit |
| 2 | Tras el hito 6, o al terminar la v0 | Aplicación completa con sala de control en vivo | API de FastAPI y frontend propio (por decidir) |

Cada incremento será una tarea más en la especificación de su hito, como el notebook:

| Hito | Qué añade a la app |
| --- | --- |
| 4 — Perfiles clínicos | Edad, motivo y gravedad en episodios y resultados; calidad del triaje (nivel asignado frente a gravedad real); editor de motivos |
| 5 — Cierre del flujo | Abandono, boarding y destinos nuevos en KPIs y replay; paciencia en «ver la verdad» |
| 6 — Tiempo real | Empieza la fase 2: sala de control en vivo con el pacer; la app de fase 1 sigue para lo batch |
| 7 — Persistencia | Perfil de defectos (limpio, realista, hostil) y comparación entre lo observado y la verdad |
| 8 — Analítica | Enlaces a Grafana; la app no duplica sus paneles |
| 9 — Experimentos | Asistente de A/B y barridos con intervalos de confianza |
| 10 — Modelos | Laboratorio de modelos con evaluación frente al ground truth |

## Objetivo y alcance de la fase 1

Al terminar la fase 1, Pedro abre una app en el navegador de su portátil y, sin tocar la terminal, ajusta el centro, simula, mira los resultados, sigue a un paciente, compara dos plantillas con los mismos pacientes y reproduce el servicio minuto a minuto. Todo sale del motor del hito 3 y de las funciones del paquete.

**Dentro del alcance**

- Catálogo de ejecuciones guardadas en disco, con su configuración, su huella y el resultado de las invariantes.
- Lanzador: editor del centro con validación en vivo, variantes guardadas en TOML, carga ofrecida antes de simular y ejecución.
- Resultados de una ejecución: KPIs, esperas por nivel frente a Manchester, ocupación por turno, censo, ley de Little e invariantes.
- Explorador de episodios: tabla filtrable, línea temporal de un episodio y su ground truth.
- Comparación de dos ejecuciones, emparejada paciente a paciente cuando comparten semilla, perfil y horizonte.
- Replay del log: plano del servicio en un minuto elegido, con reproducción a varias velocidades.
- Un formato de ejecución en disco común a la app y a `edsim motor simular`.
- Ayuda breve en cada página («¿Qué estoy viendo?») con el concepto que hay detrás.

**Fuera del alcance**

- Directo con pacer, Kafka, shocks y API de control: hito 6 y fase 2.
- Motivos, edad, gravedad latente, abandono y boarding: llegan con los incrementos de los hitos 4 y 5.
- Réplicas con intervalos de confianza, barridos y MLflow: hito 9. La fase 1 compara dos ejecuciones sueltas.
- Validación completa del motor (`edsim motor validar`, unos 90 s): sigue en la CLI.
- Varios usuarios, autenticación y despliegue: la app corre solo en local.

## Principios

1. **Capa fina.** La app solo muestra y recoge datos; la lógica vive en el núcleo (`edsim`), con tests. Si una página necesita calcular algo, falta una función en el núcleo. La app es un paquete aparte, `edsim-app`, que depende del núcleo; el núcleo nunca depende de la app ni importa Streamlit.
2. **Los ficheros son la verdad.** Una ejecución es una carpeta con su log, su ground truth y una copia exacta de su configuración. La app no tiene base de datos ni estado oculto: cerrarla y abrirla deja todo igual.
3. **Reproducible.** Cada ejecución guarda la semilla, las huellas del centro y del perfil y la versión de EDsim; con eso, la CLI produce el mismo log byte a byte.
4. **Lo derivado sale del log.** Resultados, episodios, comparación y replay se calculan desde `eventos.jsonl`, como en el hito 3. El ground truth solo aparece donde se muestra como verdad.
5. **Local y para aprender.** Un solo usuario, en `localhost`. Cada página explica en dos o tres frases qué se ve y qué concepto hay detrás.
6. **Convención de idiomas.** Código en inglés; textos de la interfaz, en español, como la CLI.

## Diseño funcional

La app tiene seis páginas en dos grupos de la barra lateral: **Ejecutar** (Ejecuciones y Simular) y **Analizar** (Resultados, Episodios, Comparar y Replay). La ejecución seleccionada se comparte entre páginas y va en la URL (`?run=<run_id>`), así que un enlace abre la misma vista.

| Página | Para qué sirve | Pregunta que responde |
| --- | --- | --- |
| Ejecuciones | Ver, abrir, descargar y borrar ejecuciones | ¿Qué he simulado ya? |
| Simular | Ajustar el centro, prever la carga y simular | ¿Qué pasa si cambio la plantilla? |
| Resultados | KPIs, esperas, ocupación, censo e invariantes de una ejecución | ¿Cómo ha ido el servicio? |
| Episodios | Buscar pacientes y ver su recorrido | ¿Qué le pasó a este paciente? |
| Comparar | Dos ejecuciones lado a lado, paciente a paciente | ¿Qué cambia con un médico más? |
| Replay | El servicio minuto a minuto | ¿Cómo se ve un lunes por la mañana? |

### Ejecuciones (página de inicio)

- Tabla con una fila por ejecución, la más reciente arriba: `run_id`, variante del centro, fecha de creación, días y calentamiento, semilla, huella del centro (8 caracteres), llegadas por día, invariantes (correctas o número de violaciones) y origen (app o CLI).
- Acciones sobre la fila elegida: abrir en Resultados, Episodios o Replay; marcar como A o B para Comparar; descargar la carpeta en un zip; borrar, con confirmación.
- Sin ejecuciones, la página ofrece un botón: «Simular el centro base (14 días, semilla 2026)».
- También aparecen las ejecuciones de la CLI, que guarda por defecto en `resultados/ejecuciones/<run_id>`.

**Detalles de la A.2b** (decididos el 3 de noviembre de 2026, con lo aprendido en la A.2a):

- **Selección:** un `st.selectbox` con los `run_id` elige la ejecución; la tabla solo muestra. `AppTest` no puede pulsar filas de `st.dataframe`, y así la selección se prueba.
- **`?run=`:** Streamlit borra los parámetros de la URL al cambiar de página. Durante la sesión manda el estado de sesión; `main.py` vuelve a escribir `?run=` en cada recarga y `st.switch_page` lo pasa con `query_params`. Un enlace con un `?run=` que no existe avisa y lo limpia.
- **Barra lateral:** en todas las páginas muestra la ejecución elegida y las marcas A y B.
- **Carpeta del catálogo:** `resultados/ejecuciones`, relativa a la carpeta desde la que se lanza la app; la variable de entorno `EDSIM_EJECUCIONES` la cambia (la usan los tests). La página muestra la ruta.
- **Columnas:** las llegadas por día son una propiedad del núcleo, `RunInfo.arrivals_per_day` (llegadas de la ventana entre los días de la ventana); la fecha se muestra en la zona del log (UTC+1).
- **Zip:** lo crea una función del núcleo, `RunStore.archive(run_id) -> bytes`, con los seis ficheros en la raíz del zip. `st.download_button` la recibe como función, que solo se ejecuta al pulsar, para no comprimir hasta 80 MB en cada recarga.
- **Carpetas no válidas:** un desplegable con el nombre y el motivo de cada una. Las que tienen un nombre válido se pueden borrar con confirmación; un nombre fuera de la regla o un enlace simbólico se borra a mano, y la página lo explica.
- **Centro base:** el botón llama a `simulate_run` con `config/centro.toml` y `config/llegadas.toml`, 14 días, semilla 2026 y origen `app`, dentro de un `st.status`.

### Simular

Tres pasos en la misma página, de arriba abajo.

**1. El centro.** Se parte de `config/centro.toml` o de una variante guardada, y se edita por bloques:

- Turnos: horas de inicio de mañana, tarde y noche.
- Plantilla: una tabla de 3 turnos × (enfermería de triaje, médicos) y el número de boxes.
- Triaje: el reparto de los 5 niveles, con su suma y el reparto normalizado que usará el motor.
- Duraciones: mediana y p90 de triaje, valoración, reevaluación y respuesta de pruebas, con la media resultante y una curva pequeña de cada lognormal.
- Pruebas e ingreso: probabilidad por nivel y el porcentaje global de ingreso que implica (Σ reparto × probabilidad).

La validación es la de `CenterConfig`: cada error aparece junto a su campo con el mismo mensaje que da la CLI, y el botón de simular se desactiva mientras haya alguno. Una lista muestra qué claves cambian frente a la base. «Guardar como variante» escribe el TOML con sus comentarios en `resultados/variantes/<nombre>.toml`.

**2. La carga prevista.** Antes de simular, una gráfica de una semana muestra la carga ofrecida frente a la capacidad, sin esperas y sin efecto diario Z (como m(t) en el hito 3):

- Médicos: λ(t) × minutos de médico esperados por paciente, frente a la plantilla de cada turno.
- Boxes: λ(t) × minutos de box esperados por paciente, frente al número de boxes.

Debajo, una tabla con la utilización prevista por turno (carga media entre capacidad). Por encima de 1 el turno se satura seguro; entre 0,85 y 1 las esperas crecen deprisa (umbral orientativo, la lección del hito 1).

**3. La ejecución.** Perfil de llegadas (`config/llegadas.toml`), días (de 1 a 60, 14 por defecto), calentamiento (2), semilla (2026) y `run_id`, propuesto como `<variante>-r<semilla>` y editable. Si el `run_id` ya existe, la app lo dice y propone otro. Al pulsar «Simular», un panel de estado muestra los pasos (simular, escribir, comprobar invariantes, analizar) y termina con un resumen y el botón «Ver resultados».

**Detalles de la A.3** (decididos el 3 de noviembre de 2026):

- **Valores en bruto, no el centro normalizado:** el editor y las variantes trabajan con los valores tal como se escriben en el TOML, por ejemplo `triaje.reparto_niveles` en porcentajes. `CenterConfig` normaliza el reparto para que sume 1: escribir el centro normalizado cambiaría los números y contradiría el comentario «% de pacientes». El centro normalizado sirve para validar, comparar con la base y calcular la carga.
- **Todos los errores a la vez:** una función del núcleo valida cada clave por separado, con las mismas comprobaciones y mensajes que `CenterConfig`, y devuelve un error por clave; `load_center` y el editor comparten esa validación. Los mensajes del núcleo siguen en inglés, como en la CLI; la app los muestra junto a su campo, con la etiqueta en español.
- **Variantes:** `write_variant` parte del texto de la base con tomlkit, cambia solo los valores y conserva comentarios y formato; la base sin cambios se escribe byte a byte igual. El nombre sigue la regla del `run_id`. Guardar con un nombre existente pide confirmación: una variante es un borrador, y las ejecuciones que la usaron no cambian porque guardan su propia copia.
- **Diferencias:** `center_diff` compara los centros normalizados clave a clave, así que escribir el reparto en porcentajes o en fracciones no cuenta como cambio.
- **Carga ofrecida:** `offered_work` reutiliza `offered_load_by_pool` del hito 3 con una muestra de pacientes de semilla fija, independiente de la ejecución. m(t) empieza vacía, así que se calculan antes los días previos que hagan falta, max(1, ceil(edad máxima de ocupación de la muestra / 1440)), con una copia del perfil de fecha retrocedida; la gráfica muestra 7 días desde fecha\_inicio (carga en régimen, no la ejecución, que empieza vacía). Comprobación con tasa constante o periódica diaria: la media de m(t) en días completos es λ̄ × tiempo medio de ocupación de la muestra (identidad exacta) y se acerca a λ̄ × E\[tiempo\] calculado a mano con las lognormales (con tolerancia estadística).
- **Tarea crítica:** tomlkit entra como dependencia del núcleo. La A.3 se divide en A.3a (núcleo, con `@codex review`) y A.3b (página).

**Detalles de la A.3b** (decididos el 3 de noviembre de 2026, con lo aprendido en la A.3a):

- **Origen del borrador:** el centro base (`config/centro.toml`) o una variante de `resultados/variantes/`, listadas por una función del núcleo (ficheros `*.toml` con nombre válido, sin ocultos). El borrador vive en el estado de sesión con claves propias, como la selección de la A.2b, y se guarda siempre sobre el fichero del que salió, para conservar sus comentarios.
- **Solo se simula lo que está en disco:** con cambios sin guardar, «Simular» se desactiva y pide guardar la variante. Así `run.json` dice de qué fichero salió cada ejecución y su copia coincide con un fichero que existe.
- **Errores y cambios:** cada campo muestra su error de `validate_center_values` (el mensaje del núcleo, bajo una etiqueta en español); «Guardar» y «Simular» se desactivan mientras haya alguno. La lista de cambios frente a la base usa `center_diff`. Sobrescribir una variante pide confirmación en dos pasos, como el borrado.
- **Números derivados en el núcleo:** el reparto normalizado, la media de cada duración, los puntos de la curva de cada lognormal y los porcentajes globales de pruebas e ingreso salen de una función del núcleo reexportada en `edsim.runs`, con tests de valores calculados a mano. La página no calcula.
- **Carga prevista:** `offered_work` en caché por los valores del centro y la huella del perfil (0,4 s por cálculo). La gráfica muestra un recurso cada vez, carga frente a capacidad, con medias de 15 minutos; la tabla de utilización por turno señala los turnos por encima de 0,85 y de 1. Si hay más de un día previo, la ayuda lo explica.
- **Ejecución:** perfil `config/llegadas.toml`, días de 1 a 60 (14), calentamiento menor que los días (2), semilla (2026) y `run_id` propuesto `<variante>-r<semilla>` (`centro-r2026` para la base); si existe, se propone `-2`, `-3`… El panel de estado tiene un solo paso: `simulate_run` no informa del progreso, y añadirle una llamada de progreso cambiaría su contrato. Al terminar, un resumen y «Ver resultados», que elige la ejecución y abre Resultados con `?run=`.
- **Retoque de la A.2b:** la tabla de Ejecuciones dice «Fecha de creación (UTC+1)».

### Resultados

- **Cabecera:** `run_id`, variante y huella del centro, días, calentamiento, semilla, fecha y versión de EDsim.
- **Invariantes:** verde si no hay violaciones; si las hay, las 10 primeras, como en la CLI.
- **KPIs de la ventana** (sin calentamiento): llegadas por día, censo medio, estancia media y p90, puerta-médico media y p90, desalojos y porcentaje de ingreso.
- **Esperas por nivel:** tabla con n, media y p90 de espera de triaje, de box, de médico, puerta-médico y estancia; al lado, el máximo de Manchester (inmediato, 10, 60, 120 y 240 min) y el porcentaje de pacientes que lo superan. Una gráfica de puntos (media y p90 por nivel) con el máximo como referencia.
- **Ocupación:** mapa de calor de 3 pools × 3 turnos con la ocupación (ocupado entre plantilla).
- **Curvas:** una semana elegida de la curva que se escoja (censo, cola de triaje, cola de box, enfermeras, médicos o boxes ocupados), con la plantilla vigente como escalón.
- **Perfil diario:** censo medio por hora del día.
- **Ley de Little:** L, λ y W del sistema y de las dos colas, con el error relativo.
- **Descargas:** el log JSONL, los dos CSV de ground truth y la configuración usada.

**Detalles de la A.4** (decididos el 3 de noviembre de 2026, con lo aprendido en la A.3b):

- **Abrir la ejecución:** la página muestra la ejecución elegida (la de `?run=` o la selección compartida de la A.2b) y la abre con `RunStore.open`. Sin ejecución elegida, pide elegir una en Ejecuciones; si no se puede abrir, da un mensaje claro con el motivo.
- **Un servicio del núcleo:** una función de `edsim.runs` lee el log y la copia del centro de la carpeta de la ejecución y devuelve todo lo que la página muestra: `RunInfo`, `analyze_run`, los KPIs y el cumplimiento de Manchester. La app no lee los ficheros de la ejecución por su cuenta.
- **Caché:** el análisis se guarda en `st.cache_data` por `run_id` y la huella de `run.json`, porque una ejecución borrada y recreada con el mismo nombre cambia su fecha de creación. Pocas entradas (4, pensando en Comparar). Se miden la lectura y el análisis de 14 y 60 días.
- **KPIs de la ventana** (`window_kpis`, en el núcleo): llegadas por día, censo medio, estancia media y p90, puerta-médico media y p90, episodios desalojados al menos una vez y desalojos totales, y porcentaje de ingreso. Esperas, estancia, desalojos e ingreso usan los episodios que llegan en la ventana y salen (`completed_in_window`), como el resumen de la CLI. Tests con valores calculados a mano.
- **Manchester:** reutiliza `manchester_compliance` de `engine/targets.py` sobre la ventana. Por nivel: n, porcentaje que supera el máximo (exactamente en el máximo cumple; el nivel 1, «inmediato», es 0 minutos) y días fuera de objetivo (menos del 90 % dentro del máximo), porque una media semanal esconde los días malos.
- **Invariantes:** verde si `run.json` dice 0 violaciones. Si hay alguna, se recalculan con `check_invariants` desde el log y se muestran las 10 primeras, como en la CLI. La página explica que dos subcomprobaciones de conservación (llegadas frente al ground truth y procesos vivos en SimPy) solo existen durante la simulación; si el recuento recalculado no coincide con el guardado, lo dice. No cambia el formato en disco.
- **Ocupación:** mapa de calor de 3 pools × 3 turnos con `ShiftOccupancy.ratio`, que puede superar 1 cuando baja la plantilla, porque nadie se interrumpe.
- **Curvas:** una semana elegida (bloques de 7 días desde el día 0; la última puede ser más corta) de la curva que se escoja, con la media y el máximo de cada bloque de 15 minutos. Ambos los calcula el núcleo: la media es exacta con el área acumulada, como `hourly_means_by_day`. La plantilla vigente se dibuja como escalón y el calentamiento, sombreado.
- **Perfil diario:** censo medio por hora del día en la ventana, con `hourly_means_by_day`.
- **Little:** L, λ, W y error relativo del sistema y de las dos colas, de `RunAnalysis.little`.
- **Descargas:** un botón por fichero (log JSONL, los dos CSV de ground truth, `centro.toml` y `llegadas.toml`), con la lectura diferida como el zip de la A.2b. Una función del núcleo devuelve los bytes y solo admite los nombres del formato de ejecución.
- **Fechas en las gráficas:** hora del log (UTC+1) como hora de reloj sin zona, para que el navegador no la desplace (lección de la A.3b).
- **Igual que la CLI:** un test compara los KPIs, las ocupaciones y los errores de Little de la página con `analyze_run` y `format_run_summary` de la misma ejecución.
- **Correcciones de la A.3b:** un commit `fix(app)` aparte, el PR #34 (a076ab9), fusionado antes de empezar la A.4; la A.4 no las repite.
- **No es crítica:** añade funciones al núcleo sin cambiar contratos ni el formato en disco; sin `@codex review`.

### Episodios

- **Filtros:** nivel, destino, desalojado o no, día, tramo (calentamiento, ventana o sin terminar), puerta-médico y estancia por encima de un valor.
- **Tabla** con las columnas de `EpisodeRecord`, en minutos y en hora del reloj, paginada; al elegir una fila se abre su ficha.
- **Ficha del episodio:** llegada (fecha y hora), nivel, destino y estancia; una línea temporal con un tramo por estado (espera de triaje, triaje, espera de box, espera de médico, valoración, espera de pruebas, reevaluación), el box ocupado y los desalojos marcados; y la lista de sus eventos tal como están en el log.
- **«Ver la verdad»:** un interruptor que añade el `EpisodeTruth` del episodio: nivel y duraciones sorteadas al llegar, frente a lo observado en el log. Una valoración interrumpida por un desalojo se ve aquí como la suma de sus tramos.
- **«Ver en el replay»** abre el Replay en el minuto de llegada del paciente.

**Detalles de la A.5** (decididos el 3 de noviembre de 2026, con lo aprendido en la A.4):

- **Abrir la ejecución:** como Resultados: `read_run_header` en cada recarga, `RunReadError` y `RunAnalysisError` como mensaje. La tabla sale de `RunResults.analysis.table`, que ya está en caché: Episodios no relee el log para listar.
- **Índice de eventos por episodio:** una función del núcleo anota en qué posición (bytes) de `eventos.jsonl` está cada evento de cada episodio. A ser posible se construye en la misma lectura que `read_run_results`, para no leer el log dos veces, y vive en la misma caché. La ficha lee y valida solo las líneas de su episodio. Se miden el tiempo del índice, su memoria y el tiempo de una ficha con 14 y 60 días.
- **Tramos (`episode_segments`, en el núcleo):** del episodio, contiguos, sin huecos ni solapes y sin tramos de duración cero, desde la llegada hasta la salida (o hasta el horizonte si sigue dentro). El estado es dónde está el paciente: espera de triaje, triaje, espera de box, en box esperando médico, valoración, en box esperando pruebas y reevaluación. Cada tramo en box lleva su número de box, y un desalojo devuelve a espera de box. Los tramos suman la estancia, u horizonte menos llegada si no terminó.
- **Banda de pruebas y desalojos:** aparte de los tramos, una banda «pruebas en curso» de `test_ordered` a `test_resulted` (o al horizonte), porque el laboratorio sigue aunque el paciente pierda su box. Los desalojos se marcan como instantes, con el box y el episodio que desalojó (`desalojado_por`).
- **Tests de los tramos:** en una ejecución real, todos los episodios tienen tramos contiguos que suman su estancia (criterio de aceptación). Logs escritos a mano para un desalojo durante la valoración, un desalojo esperando pruebas con el resultado llegando en la cola de box, un paciente sin pruebas y uno sin terminar.
- **Filtros:** nivel, destino, desalojado o no, día de llegada, tramo, y puerta-médico y estancia mayores que un valor, en una función pura probada sin Streamlit. El tramo es excluyente: «sin terminar» si no hay salida, «calentamiento» si llegó antes del fin del calentamiento y salió, y «ventana» si llegó después y salió. Los filtros se recuerdan al navegar, con claves propias.
- **Tabla:** las columnas de `EpisodeRecord` en minutos y la llegada en hora de reloj (UTC+1), con el número de episodios que pasan los filtros. `st.dataframe` ya se desplaza sin pintar todas las filas, así que no se pagina a mano.
- **Elegir un episodio:** un selector con los episodios filtrados, recordado al navegar y escrito en la URL junto a la ejecución (`?run=…&episodio=EP-000137`), para que un enlace abra la misma ficha. Si el episodio no existe o deja de pasar los filtros, la página lo dice y no abre la ficha.
- **Ficha:** llegada (fecha y hora), nivel, destino y estancia; línea temporal en Altair con los tramos, la banda de pruebas y los desalojos, en hora de reloj sin zona; y la lista de sus eventos tal como están en el log.
- **«Ver la verdad»:** un interruptor añade el `EpisodeTruth` del episodio, leído de `ground_truth_episodios.csv` por una función nueva del núcleo (una vez por ejecución, en caché). Compara lo sorteado con lo observado: nivel, triaje, valoración (la suma de sus tramos si se interrumpió), reevaluación, respuesta de pruebas y destino. Las duraciones sorteadas que no se usaron (reevaluación y respuesta sin pruebas) se marcan como no usadas. En el hito 3 todo coincide, porque el triaje no tiene error; un test lo comprueba en todos los episodios terminados de una ejecución, con una tolerancia de redondeo fijada antes.
- **«Ver en el replay»:** se deja para la A.7, cuando el Replay sepa abrir un minuto.
- **No es crítica:** añade funciones al núcleo sin cambiar el formato en disco ni los contratos del motor; sin `@codex review`.

### Comparar

- Se eligen A y B (o llegan marcadas desde Ejecuciones).
- **Emparejamiento:** si comparten semilla, huella del perfil, días y calentamiento, la comparación es emparejada: las llegadas son las mismas y, si solo cambian plantilla o boxes, también lo sorteado de cada paciente (decisión candidata 24). Si cambian parámetros clínicos, las llegadas coinciden pero los sorteos no. La app muestra el caso y la lista de claves del centro que difieren.
- **KPIs de A y B,** con la diferencia B − A y el cambio relativo; las esperas por nivel, lado a lado.
- **Paciente a paciente** (solo emparejada): histograma de la diferencia de estancia y de puerta-médico, porcentaje de pacientes que mejoran, empeoran o quedan igual, y los 10 más afectados, con enlace a su ficha.
- Un aviso fijo: es una sola réplica de cada lado; las comparaciones con intervalos de confianza llegan en el hito 9.

**Detalles de la A.6** (decididos el 4 de noviembre de 2026, con lo aprendido en la A.5):

- **Elegir A y B:** dos selectores en la página que leen y escriben las marcas A y B compartidas de la A.2b, así que marcar en Ejecuciones o elegir aquí es lo mismo. Cada lado se abre como Resultados (`read_run_header` y la caché de `RunResults`), con su error si no se puede.
- **Un servicio del núcleo (`compare_runs`):** recibe los resultados de A y B (y su ground truth) y devuelve el tipo de emparejamiento, las diferencias de metadatos y del centro, los KPIs con la diferencia, las esperas por nivel y, si son emparejadas, las diferencias por episodio. La página no calcula.
- **Emparejamiento, por configuración y comprobado con la verdad:**
  - *No emparejada* si cambia la semilla, la huella del perfil, los días o el calentamiento; la página dice cuál. Solo se comparan KPIs y esperas por nivel.
  - *Emparejada con los mismos sorteos* si solo cambian turnos, plantilla o boxes.
  - *Emparejada con sorteos distintos* si cambia algún parámetro clínico. El motor usa cuatro flujos aleatorios separados (nivel, duraciones, pruebas y destino) con consumo fijo por paciente: cambiar una duración solo cambia esa duración, y cambiar el reparto puede cambiar niveles y, con ellos, pruebas y destino.
  - La clasificación sale de `run.json` y `center_diff`, y se comprueba con los dos `ground_truth_episodios.csv`: misma llegada para todos los episodios y, por cada sorteo, cuántos pacientes difieren. Si la comprobación contradice la configuración, la página lo muestra como error.
- **KPIs:** los nueve de la ventana de A y de B, la diferencia B − A y el cambio relativo; «—» si A es 0 o no existe.
- **Esperas por nivel:** n, media y p90 de las cinco medidas y el porcentaje que supera el máximo de Manchester, de A y de B lado a lado.
- **Paciente a paciente (solo emparejadas, también con sorteos distintos):** los episodios que llegan en la ventana y terminan en las dos ejecuciones, como `paired_waits`. Con sorteos distintos, un aviso dice qué sorteos cambian y en cuántos pacientes, porque la diferencia mezcla el efecto de la plantilla y el del parámetro clínico.
- **Excluidos:** los episodios que terminan solo en A, solo en B o en ninguna se cuentan y se muestran siempre. Si hay alguno, la página explica el sesgo: los que siguen dentro en la ejecución más saturada son los peores, y quedan fuera de la diferencia.
- **Diferencias:** histograma de B − A de la estancia y de puerta-médico, y porcentaje de pacientes que mejoran, empeoran o quedan igual. «Igual» es la misma historia: diferencia dentro de la tolerancia de la A.5 (1e-8 minutos).
- **Los 10 más afectados:** por la diferencia absoluta de estancia, con su signo, nivel y estancias en A y B, y un botón para abrir su ficha en A o en B. El botón elige la ejecución y el episodio, quita los filtros de Episodios con un aviso para que la ficha se vea y abre la página con `?run=` y `?episodio=`.
- **Una ejecución frente a sí misma:** emparejada con los mismos sorteos, cero en todas las diferencias y 100 % iguales (criterio de aceptación), con un test.
- **Aviso fijo:** es una sola réplica de cada lado; las comparaciones con intervalos de confianza llegan en el hito 9.
- **Rendimiento:** dos ejecuciones abiertas a la vez. Se miden la primera entrada, la recarga y la memoria con dos de 14 y dos de 60 días. Las tablas grandes no usan `Styler` (lección de la A.5), y los controles que no cambian A o B viven en fragmentos.
- **No es crítica:** añade funciones al núcleo sin cambiar el formato en disco ni los contratos existentes; sin `@codex review`.

### Replay

- **Controles:** ejecución, día, minuto (deslizador de 0:00 a 23:59), botones de paso (±1 y ±10 minutos), reproducir y pausar, y velocidad (1, 5, 15 o 60 minutos simulados por segundo).
- **Barra de estado:** fecha y hora simuladas, turno, censo y si el minuto cae en el calentamiento.
- **Plano del servicio** en ese minuto, de izquierda a derecha:
  - cola de triaje, con una ficha por paciente;
  - triaje, con los puestos de la plantilla vigente;
  - cola de box, ordenada por prioridad (nivel y llegada);
  - rejilla de boxes, una casilla por box con el color del nivel y el estado del paciente (esperando médico, en valoración, esperando pruebas, en reevaluación); un desalojo reciente se marca con un borde;
  - médicos ocupados frente a la plantilla vigente;
  - salidas de la última hora, por destino.
- **Debajo:** el censo del día con una línea vertical en el minuto, los últimos 15 eventos y la lista de pacientes dentro, con enlace a su ficha.
- Los contadores del plano coinciden en cada minuto con las curvas escalonadas del hito 3: el replay no tiene lógica propia de conteo.

**Detalles de la A.7** (decididos el 4 de noviembre de 2026, con lo aprendido en las A.4 a A.6):

- **Antes de nada, acelerar los tests:** un commit `chore` mide las suites rápidas con `--durations` y marca `slow` los AppTest que simulan o miden. Las suites completas y el CI los siguen ejecutando todos. Se anotan los tiempos antes y después.
- **`ReplayIndex` en el núcleo:** al abrir la ejecución, una pasada por el log guarda una foto completa del estado cada 60 minutos simulados (quién está en cada cola y en cada box, con su nivel, estado y llegada; plantilla vigente; salidas y desalojos recientes) y la posición en bytes del primer evento de cada hora, como el índice de la A.5. `state_at(t)` parte de la foto anterior y lee y valida del JSONL como mucho una hora de eventos. Se guarda en `st.cache_resource` con la clave de siempre (raíz, `run_id` y huella de `run.json`).
- **El minuto t:** el estado tras todos los eventos de los instantes ≤ t, la misma convención que `StepCurves.value`.
- **Sin lógica propia de conteo:** los contadores del plano y de la barra de estado (censo, colas, ocupados y plantilla) salen de las curvas escalonadas de `RunResults`. Las fichas y las casillas salen del `ReplayIndex`, y un test comprueba en todos los minutos de una ejecución de prueba que lo que dibuja el `ReplayIndex` coincide con las curvas (criterio de aceptación).
- **Plano (`plan.py`, función pura que devuelve SVG):** cola de triaje en orden de llegada; puestos de triaje con la plantilla vigente; cola de box por prioridad (nivel y llegada); rejilla con una casilla por box, color del nivel y estado del paciente; médicos ocupados frente a la plantilla; salidas de la última hora por destino. Cada cola dibuja hasta 30 fichas y «+N más», con el total siempre visible. Un desalojo de los últimos 60 minutos se marca con un borde, la misma ventana que las salidas.
- **Colores por nivel en toda la app:** la paleta de Manchester (rojo, naranja, amarillo, verde y azul para los niveles 1 a 5), en un solo sitio y usada por el plano y por las gráficas existentes que distinguen niveles.
- **Controles:** ejecución, día, minuto (deslizador de 0:00 a 23:59), pasos de ±1 y ±10 minutos, reproducir y pausar, y velocidad (1, 5, 15 o 60 minutos simulados por segundo). La reproducción es un `st.fragment` con `run_every` que solo vuelve a dibujar el plano y la barra de estado. Al pasar de las 23:59 sigue en el día siguiente, y al llegar al horizonte se pausa. La posición y la velocidad se recuerdan al navegar.
- **Barra de estado:** fecha y hora (UTC+1), turno, censo y si el minuto cae en el calentamiento.
- **Debajo del plano:** el censo del día con una línea vertical en el minuto (fechas sin zona en Altair), los últimos 15 eventos tal como están en el log y los pacientes dentro, con un selector y un botón para abrir su ficha (como en Comparar).
- **«Ver en el replay»:** la ficha de Episodios añade el botón, que abre el Replay de esa ejecución en el día y el minuto de llegada del paciente, con su ficha resaltada en el plano.
- **Rendimiento:** cada fotograma en menos de 200 ms con 14 y con 60 días (objetivo de la especificación), medido como en la A.5. Se miden también la construcción del `ReplayIndex` y su memoria.
- **No es crítica:** añade funciones al núcleo sin cambiar el formato en disco ni los contratos existentes; sin `@codex review`.

### En todas las páginas

- Un desplegable «¿Qué estoy viendo?» con dos o tres frases y el concepto que hay detrás (ventana y calentamiento, ley de Little, números aleatorios comunes, prioridad y desalojo).
- Formatos: minutos con un decimal, horas como hh:mm, fechas en la zona del log (UTC+1), números con coma decimal.
- Colores fijos por nivel de triaje en todas las gráficas y en el plano.

## Arquitectura

&#91;embedded content: arquitectura de la fase 1 · 4 capas\]

Las páginas solo llaman a `edsim.runs`, que usa el motor del hito 3 sin cambiarlo y guarda cada ejecución en su carpeta; la CLI pasa por los mismos servicios, así que las dos producen lo mismo.

## Diseño técnico

### Stack

| Pieza | Elección | Motivo |
| --- | --- | --- |
| Interfaz | Streamlit 1.66 o posterior (la última publicada en octubre de 2026; se comprueba al instalar) | Está en el stack para «exploración y what-if»; páginas con `st.navigation`, caché, fragmentos y `AppTest` para los tests |
| Tablas | pandas, que llega con Streamlit | Solo en `edsim-app`; el núcleo sigue sin pandas |
| Gráficas | Altair, que llega con Streamlit | Gráficas declarativas e interactivas sin otra dependencia |
| Variantes del centro | tomlkit | Escribe TOML conservando los comentarios; `tomllib` sigue leyendo. Es dependencia del núcleo, porque la usa `edsim.runs` |
| Plano del replay | SVG generado en Python | Una función pura y testeable, sin JavaScript |

- **Un repositorio, dos paquetes.** El núcleo `edsim` y la app `edsim-app` viven en el mismo repositorio como un workspace de uv: un solo `.venv` y un solo `uv.lock`, así que la app siempre se prueba contra el núcleo actual. No hace falta un entorno nuevo: sirven el mismo Python 3.13, WSL y Cursor.
- Streamlit, pandas y Altair son dependencias de `edsim-app`; el `pyproject.toml` del núcleo no los lista.
- Arranque: `uv run --package edsim-app edsim-app`, un script del paquete de la app que lanza Streamlit en `localhost` y el puerto 8501. Desde Windows se abre `http://localhost:8501` gracias al reenvío de localhost de WSL2.
- Sincronización: `uv sync --all-packages` es el comando estándar. Un `uv sync` simple deja el entorno exactamente como el paquete raíz: instala solo el núcleo y desinstala la app. Por eso el arranque lleva `--package edsim-app`, que instala lo que falte (comprobado con un workspace de prueba el 3 de noviembre de 2026).

### Estructura del código

```
edsim/                        # repositorio
  AGENTS.md                   # instrucciones para los agentes: fuente única
  CLAUDE.md                   # @AGENTS.md y lo propio de Claude Code
  .codex/                     # config.toml, rules/edsim.rules y hooks.json de Codex
  pyproject.toml              # paquete edsim (núcleo) y [tool.uv.workspace] members = ["app"]
  uv.lock                     # un solo lock para los dos paquetes
  src/edsim/                  # núcleo: lo que ya existe y, nuevo, edsim.runs
    runs/                     # sin Streamlit; también lo usa la CLI
      store.py                # RunStore: listar, abrir, crear y borrar ejecuciones; run.json
      service.py              # simulate_run: simular, escribir, comprobar y resumir
      variants.py             # variantes con tomlkit y diferencias (la validación por campo, en engine/center.py)
      offered.py              # carga ofrecida de médicos y boxes por minuto y por turno
      kpis.py                 # KPIs de la ventana y cumplimiento de los máximos de Manchester
      timeline.py             # tramos de estado de cada episodio
      replay.py               # ReplayIndex: estado del servicio en un minuto
      compare.py              # comparación de dos ejecuciones, emparejada por episodio
  tests/                      # tests del núcleo
  docs/                       # documentación del núcleo: diseño, specs, ADR 0001…, diario
  app/                        # paquete edsim-app
    pyproject.toml            # depende de edsim y streamlit; script edsim-app
    AGENTS.md                 # reglas de la app para los agentes
    src/edsim_app/
      main.py                 # st.navigation, estado compartido y ?run=
      views/                  # las seis páginas; nunca pages/ (activa la navegación antigua)
      frames.py               # dataclasses del núcleo a DataFrames
      charts.py               # gráficas de Altair
      plan.py                 # SVG del plano del servicio (función pura)
      help.py                 # textos de «¿Qué estoy viendo?»
    tests/                    # AppTest y plan.py
    docs/
      specs/fase-1.md         # exportación de esta pestaña
      decisiones/             # ADR APP-0001…
      diario/                 # una entrada por fase
```

### Una ejecución en disco

Cada ejecución es una carpeta `resultados/ejecuciones/<run_id>/` (`resultados/` ya está en `.gitignore`). La app y `edsim motor simular` escriben el mismo formato a través de `simulate_run`.

| Fichero | Contenido |
| --- | --- |
| `eventos.jsonl` | El log de eventos, igual que hoy |
| `ground_truth_episodios.csv`, `ground_truth_dias.csv` | El ground truth, igual que hoy |
| `centro.toml`, `llegadas.toml` | Copia byte a byte de la configuración usada |
| `run.json` | Metadatos: versión del formato, `run_id`, fecha de creación, origen (app o CLI), versión de EDsim, semilla, días, calentamiento, variante y huellas del centro y del perfil, violaciones de invariantes, llegadas en la ventana y duración de la simulación |

- `simulate_run` copia primero los dos TOML en la carpeta y simula desde esas copias, así que lo simulado y lo guardado son los mismos bytes; las huellas se calculan sobre las copias y los CSV conservan la ruta original como procedencia. Volver a simular desde la carpeta da el mismo log.
- La ejecución se escribe en una carpeta temporal junto al destino, con `run.json` en último lugar, y se renombra al terminar: una ejecución a medias nunca aparece en el catálogo. Si algo falla, la carpeta temporal se borra.
- El `run_id` se valida con una regla nueva del núcleo, común a la CLI y a la app: letras, cifras, `.`, `-` y `_`, empezando por letra o cifra, hasta 64 caracteres. Así no puede salirse de `resultados/ejecuciones/`. La regla anterior de `--run-id` aceptaba cualquier texto no vacío, también `../algo` (decidido el 3 de noviembre de 2026).
- `edsim motor simular` guarda por defecto en `resultados/ejecuciones/<run_id>`, así que sus ejecuciones aparecen en el catálogo, y se niega a sobrescribir una ejecución existente: una ejecución es un hecho. `--salida` sigue permitiendo otra carpeta, que no debe existir.
- Las variantes del centro se guardan en `resultados/variantes/<nombre>.toml`; una variante que merezca conservarse se copia a `config/` y se versiona a mano.

### Funciones nuevas del paquete

| Función | Qué hace | Comprobación clave |
| --- | --- | --- |
| `simulate_run(...) -> SimulationResult` | Simula con `simulate_ed`, escribe la carpeta, comprueba las invariantes y guarda `run.json` | La CLI y la app dan el mismo log para los mismos parámetros, y volver a simular desde la carpeta también |
| `RunStore(root)` | `list`, `open`, `exists`, invalid y `delete` de ejecuciones | Ida y vuelta de `run.json`; ignora carpetas temporales |
| `write_variant(base, values, path)` y `center_diff(a, b)` | Escribe los valores en bruto de un centro sobre el TOML base, conservando sus comentarios, y lista las claves que cambian comparando centros normalizados | `Una variante escrita y leída da los mismos valores con centros aleatorios válidos; la base sin cambios se escribe byte a byte igual` |
| `offered_work(center, profile, days)` | Minutos de médico y de box ofrecidos por minuto y utilización prevista por turno, con `offered_load` del hito 3 | Con tasa constante o periódica diaria, la media de la ventana es λ̄ × el tiempo medio de ocupación (exacta con la muestra y cercana al valor calculado a mano); con perfiles generales, la convolución se comprueba a mano en minutos elegidos |
| `window_kpis(analysis)` y `manchester_compliance(table, start, end)` | KPIs de la ventana y porcentaje por encima del máximo de cada nivel (el nivel 1, inmediato, solo muestra el tiempo) | Valores calculados a mano en un log pequeño |
| `episode_segments(events)` | Tramos de estado de cada episodio, con su box | Los tramos de cada episodio son contiguos y suman su estancia |
| `ReplayIndex.from_events(events)` y `.state_at(t)` | Estado del servicio en el minuto t: colas, boxes, plantilla, salidas recientes y últimos eventos | Los contadores coinciden con `step_curves` en todos los minutos de una ejecución |
| `compare_runs(a, b)` | Tipo de emparejamiento, diferencias del centro, KPIs y diferencias por episodio | Una ejecución frente a sí misma da cero en todo |

`ReplayIndex` guarda una foto completa del estado cada 60 minutos simulados y aplica los eventos desde la foto anterior, así que cada consulta recorre como mucho una hora de eventos.

### Estado, caché y rendimiento

- **Estado de sesión:** la ejecución elegida (sincronizada con `?run=`), las marcas A y B y el borrador del centro en edición.
- **Caché:** `st.cache_data` para leer y analizar una ejecución, con la clave `run_id` y la fecha de modificación del log; `st.cache_resource` para el `ReplayIndex`. Como mucho tres ejecuciones en caché.
- **Simulación:** síncrona dentro de la sesión, con un panel de estado. La app limita el horizonte a 60 días; las medidas de la A.2a lo confirman: 60 días se simulan en unos 12 s y el log pesa unos 1,35 MB por día (anexo de la A.2a).
- **Reproducción:** un `st.fragment` con `run_every` avanza el minuto según la velocidad y solo vuelve a dibujar el plano y la barra de estado.
- **Objetivos:** abrir una ejecución de 14 días en menos de 3 s la primera vez y de 0,5 s desde la caché; cada fotograma del replay, en menos de 200 ms.
- **Borrar:** solo dentro de `resultados/ejecuciones/`, con confirmación.

### Documentación y decisiones

- La especificación vive en esta pestaña del documento de diseño y se exporta a `app/docs/specs/fase-1.md` al cerrar la fase, como las de los hitos.
- La app tiene su propia serie de ADR, `APP-0001`, `APP-0002`…, en `app/docs/decisiones/`, y su diario en `app/docs/diario/`.
- **Criterio de reparto:** una decisión va a la serie del componente al que obliga. Si una necesidad de la app cambia el núcleo, como el formato de ejecución que también escribe la CLI, la ADR es del núcleo.
- Una ADR aceptada no se edita: un cambio de idea es una ADR nueva que sustituye a la anterior, y las dos se citan.

### Frontera, versiones y agente

- **Superficie pública:** la app solo importa lo público del núcleo, nada con `_` delante y lo declarado en `__all__` de `edsim.runs`. La API de la fase 2 expondrá esa misma superficie.
- **Dirección de las dependencias:** la app depende del núcleo, nunca al revés. Como los dos paquetes comparten entorno, un test comprueba que `edsim` no importa `streamlit`, `pandas` ni `edsim_app`.
- **Versiones:** etiquetas propias de la app (`app-v0.1.0` al cerrar la fase 1), separadas de las de los hitos (`v0.3-hito3`). Commits con ámbito: `feat(app)`, `fix(app)`.
- **Agente:** `app/AGENTS.md` guarda las reglas de la app. El agente no arranca el servidor de Streamlit, que no termina y bloquearía la sesión: prueba con `AppTest`, y Pedro revisa en el navegador.
- **Datos generados:** ejecuciones y variantes en `resultados/`, nunca dentro de `app/`.
- **Fase 2:** si el frontend se hace en JavaScript, una ADR decidirá si va en una carpeta `web/` de este repositorio o en uno nuevo.

### Implementación con Codex

La fase 1 se implementa con Codex, el agente de OpenAI, en lugar de Claude Code (APP-0003). El chat del proyecto sigue con los conceptos, la especificación, los prompts y la revisión, y Pedro sigue fusionando. La tarea A.0 lo deja preparado y probado.

- **Instrucciones:** `AGENTS.md` en la raíz es la fuente única (modo de trabajo, comandos, convenciones, reglas de git y una sección `## Review guidelines`). `CLAUDE.md` queda en `@AGENTS.md` más lo propio de Claude Code, así que el hito 3 y siguientes no cambian.
- **Arranque:** Codex se lanza siempre en la raíz del repositorio, dentro de WSL, porque las tareas tocan `src/edsim/runs/` y `app/`. El `AGENTS.md` raíz pide leer `app/AGENTS.md` cuando la tarea toque la app, porque Codex solo combina los `AGENTS.md` del camino hasta la carpeta de trabajo.
- **Seguridad:** `.codex/config.toml` fija `sandbox_mode = "workspace-write"` y `approval_policy = "on-request"`: edita y ejecuta dentro del repositorio, sin red, y pide permiso para lo demás. Nunca `--yolo` ni `danger-full-access`.
- **Plan:** cada tarea empieza con `/plan`; el plan se revisa y se aprueba como hasta ahora.
- **Hooks:** `.codex/hooks.json` con un hook `Stop` que ejecuta `ruff format` y `pytest -m "not slow"`, con la ruta del repositorio sacada de `git rev-parse --show-toplevel`. Desde la A.1 ejecuta también los tests rápidos de la app, porque Codex es quien la toca; el hook de Claude Code sigue solo con el núcleo y el CI cubre el resto.
- **Revisión:** la revisión en el chat, en todas las tareas. `@codex review` en el PR, como segunda opinión guiada por las *Review guidelines* de `AGENTS.md`, solo en las tareas críticas: las que cambian un contrato que comparten el núcleo, la CLI y la app (el formato de una ejecución en disco, la CLI o las dependencias del núcleo), es decir, la A.2a y la A.3a, y las que Pedro marque (decidido el 3 de noviembre de 2026).
- **Diario:** al cerrar cada tarea, unas notas sobre el plan, los permisos pedidos, los errores y el consumo, para comparar con Claude Code al final de la fase.

**Convivencia con Claude Code.** Claude Code sigue trabajando en el repositorio (hitos del núcleo). Nunca trabajan dos agentes a la vez en la misma carpeta: se hacen turnos o se usa `git worktree` para tener una segunda copia de trabajo en otra carpeta y otra rama. Cuando una rama se fusiona, la otra se actualiza con `git pull --rebase origin main` antes de su PR. Una sesión de Codex por tarea, igual que con Claude Code.

Las reglas de `.codex/rules/edsim.rules` sustituyen a los permisos de `.claude/settings.json`. Solo se cargan si Codex confía en la carpeta del proyecto.

| Comandos | Decisión | Por qué |
| --- | --- | --- |
| `git switch`, `add`, `commit`, `pull`, `status`, `diff`, `log` | Permitir | `.git` es de solo lectura dentro del sandbox |
| `gh pr create`, `gh pr view`, `gh pr checks`, `gh run view` | Permitir | Necesitan red, cerrada en el sandbox |
| `git push`, `uv sync` | Preguntar | El push siempre con permiso de Pedro; `uv sync` necesita red y `AGENTS.md` pide permiso antes de ejecutarlo |
| `gh pr merge` | Prohibir | La fusión es de Pedro |

Trampas conocidas, que la tarea A.0 comprueba una a una:

1. **Sin red:** `uv sync`, `gh` y `git push` fallan dentro del sandbox; un `uv run` tras cambiar dependencias intenta sincronizar y también necesita red.
2. **`.git` protegido:** sin las reglas, cada commit pide permiso.
3. **`AGENTS.md` anidados:** se resuelve arrancando en la raíz y con la indicación del `AGENTS.md` raíz.
4. **Extensión de Cursor en WSL:** tiene que instalarse en el lado de WSL y da problemas conocidos; la vía principal es la CLI en el terminal integrado.

## Tests y CI

La lógica nueva se prueba como el resto del paquete; la app solo necesita pruebas de humo, porque no tiene lógica propia.

- **Núcleo (`edsim.runs`, en `tests/`):** tests primero y valores calculados a mano, como en los hitos anteriores. Las comprobaciones cruzadas son las de la tabla de funciones: el replay frente a `step_curves`, los tramos frente a la estancia, el TOML de ida y vuelta y una ejecución comparada consigo misma.
- **Formato común:** un test simula el mismo centro con `simulate_run` y con `edsim motor simular` y comprueba que los logs son idénticos.
- **Caracterización antes del refactor:** antes de que la CLI pase a usar `simulate_run`, un test fija el SHA-256 del log y de los dos CSV que produce hoy con parámetros fijos; después del cambio deben salir idénticos.
- **Frontera:** un test lanza un intérprete nuevo, importa todos los módulos de `edsim` y comprueba que `sys.modules` no contiene `streamlit`, `pandas` ni `edsim_app`; un intérprete nuevo evita que otro test haya cargado pandas antes. Lo completa una pasada estática con `ast` sobre `src/edsim`, que también ve los imports dentro de funciones. Se valida con una versión incorrecta temporal (un `import pandas` en el núcleo).
- **Plano (en `app/tests/`):** `plan.py` se prueba sin Streamlit: dado un estado escrito a mano, el SVG tiene una casilla por box y los colores de cada nivel.
- **Páginas (en `app/tests/`):** un test de `AppTest` por página, con una ejecución de 3 días creada en una carpeta temporal: la página se ejecuta sin excepciones y muestra sus elementos clave. Simular desde la app se prueba con 1 día.
- **CI:** dos jobs en el mismo workflow, `tests` para el núcleo y `tests-app` para la app, los dos obligatorios en el ruleset. Se ejecutan siempre, sin filtros por ruta: un check obligatorio que un filtro salta se queda pendiente y bloquea el PR. Los tests de 60 días, si hacen falta, se marcan `slow`.
- **Entornos del CI:** `tests` sincroniza solo el núcleo (`uv sync --locked`), así que en su entorno no están Streamlit ni pandas y un import prohibido falla de verdad; es una segunda barrera de la frontera. `tests-app` sincroniza todo (`uv sync --locked --all-packages`) y ejecuta `app/tests`.
- **Prueba manual al cerrar cada tarea:** Pedro abre la app, recorre la página nueva y revisa el PR, como con el notebook.

## Decisiones candidatas

Seis decisiones candidatas en dos series. Las que obligan al núcleo siguen su numeración (31 a 33, después de las del hito 3); las que solo afectan a la app abren la serie APP. La tarea de cierre A.8 las convierte en ADR, en `docs/decisiones/` y en `app/docs/decisiones/`.

| # | Serie | Decisión | Motivo |
| --- | --- | --- | --- |
| 31 | Núcleo | App incremental: fase 1 en Streamlit al cerrar el hito 3, una tarea de app en los hitos siguientes y la aplicación completa (API y frontend propio) después del hito 6 o de la v0 | Cambia la hoja de ruta; ver el modelo pronto sin rehacer la app cuando cambien el paciente, los eventos y la arquitectura |
| 32 | Núcleo | Una ejecución es una carpeta `resultados/ejecuciones/<run_id>/` con el log, el ground truth, la copia de la configuración y `run.json`, escrita por `simulate_run` tanto desde la CLI como desde la app | Los ficheros son la verdad, sin base de datos; cada ejecución se puede reproducir |
| 33 | Núcleo | Las variantes del centro se escriben con tomlkit conservando los comentarios, en `resultados/variantes/`; `config/` guarda solo lo que se versiona a mano | Los comentarios explican cada clave; las pruebas no ensucian el repositorio |
| APP-0001 | App | En la fase 1, Streamlit llama directamente al núcleo, sin API; la API de FastAPI llega con el modo directo del hito 6 | Menos piezas; la API se diseña cuando exista algo en vivo que controlar |
| APP-0002 | App | La app es un paquete aparte, `edsim-app`, en el mismo repositorio (workspace de uv, un solo entorno), con sus dependencias, su documentación, sus ADR y sus etiquetas | Lo que cambia junto vive junto; frontera declarada en las dependencias; separable si llega un frontend en JavaScript |
| APP-0003 | App | La fase 1 se implementa con Codex en lugar de Claude Code: `AGENTS.md` como fuente única de instrucciones para los dos agentes y configuración versionada en `.codex/` (sandbox, reglas y hooks) | Aprender otra herramienta de agentes y usar los créditos de la suscripción de ChatGPT; un solo fichero de instrucciones evita que dos se contradigan |

## Tareas, ramas y orden de ejecución

Las tareas A.1 a A.8 empiezan cuando exista la etiqueta `v0.3-hito3`; la A.0 puede hacerse antes, porque solo prepara la herramienta. Siguen el ciclo de los hitos: explicación breve del concepto en el chat, plan con `/plan` en una sesión nueva de Codex, implementación completa tras aprobar el plan, PR revisado por Pedro (y por `@codex review` en las tareas críticas) y *squash and merge*. Al cerrar cada tarea se actualiza el anexo de esta pestaña.

| # | Tarea | Rama | Resultado |
| --- | --- | --- | --- |
| A.0 | Preparar Codex: instalación en WSL e inicio de sesión; `AGENTS.md` en la raíz a partir de `CLAUDE.md`, y `CLAUDE.md` con `@AGENTS.md`; `.codex/config.toml`, reglas y hooks; Codex conectado al repositorio para `@codex review`; prueba de extremo a extremo con el propio PR de la tarea | `chore/app-codex` | Codex trabaja en el repositorio con los permisos justos y Claude Code sigue funcionando igual |
| A.1 | Especificación en `app/docs/specs/fase-1.md`; workspace de uv con el paquete `edsim-app` (pyproject, script `edsim-app`, `app/AGENTS.md` y carpetas de documentación); seis páginas vacías con `st.navigation`; test de la frontera; `AppTest` de humo y job `tests-app` en el CI y en el ruleset | `feat/app-esqueleto` | La app arranca con `uv run --package edsim-app edsim-app` y el CI la prueba |
| A.2a | `RunStore`, `simulate_run` y `run.json`; `edsim motor simular` pasa a usarlos y guarda por defecto en el catálogo; regla del run\_id; medida de tiempo y memoria; retoques de la A.1 | `feat/app-ejecuciones-nucleo` | La CLI escribe ejecuciones atómicas y reproducibles en resultados/ejecuciones/ |
| A.2b | Página Ejecuciones: catálogo, acciones, zip, borrado con confirmación y botón del centro base; estado compartido y `?run=` | `feat/app-ejecuciones` | La CLI y la app escriben la misma ejecución y el catálogo la muestra |
| A.3a | Valores en bruto y errores por campo del centro; `write_variant` y `center_diff` con tomlkit; `offered_work` | `feat/app-simular-nucleo` | Una variante se guarda conservando los comentarios y su carga prevista se calcula |
| A.3b | Página Simular: editor por bloques con errores por campo, variantes, carga prevista y ejecución; cabecera UTC+1 en Ejecuciones | `feat/app-simular` | Una variante editada, guardada y simulada desde la app |
| A.4 | `window_kpis` y `manchester_compliance`; página Resultados | `feat/app-resultados` | KPIs, esperas, ocupación, curvas, Little e invariantes de una ejecución |
| A.5 | `episode_segments`; página Episodios con ficha y «ver la verdad» | `feat/app-episodios` | La línea temporal de cualquier episodio, desalojos incluidos |
| A.6 | `compare_runs`; página Comparar | `feat/app-comparar` | Base frente a un médico más de noche, paciente a paciente |
| A.7 | `ReplayIndex`, `plan.py` y reproducción; página Replay | `feat/app-replay` | El servicio minuto a minuto, coherente con las curvas |
| A.8 | Cierre: ADR 0031 a 0033 y APP-0001 a APP-0003, entrada del diario de la app con la comparación entre Codex y Claude Code, anexo, exportación de esta pestaña, README de la app y etiqueta `app-v0.1.0` | `docs/app-cierre` | Fase 1 cerrada |

Orden: A.1, A.2a y A.2b primero, porque todo lo demás lee ejecuciones del catálogo. A.3, A.4 y A.5 pueden ir en cualquier orden. A.6 usa los KPIs de A.4, y A.7 va al final por ser la más grande.

**Detalles de la A.8** (decididos el 4 de noviembre de 2026, con lo aprendido en las A.0 a A.7):

- **Qué es:** una tarea de documentación y cierre, sin código nuevo salvo el título de la app. No es crítica: sin `@codex review`. Si la revisión de la A.7 pide un `fix(app)`, va en su propio PR antes de la A.8.
- **Primer commit, las exportaciones:** esta pestaña en `app/docs/specs/fase-1.md` y la pestaña de diseño en `docs/diseno.md`, que el chat pone antes al día (decisiones 31 a 33 en el registro y estado de la app en la hoja de ruta). La de la app se comprueba contando el encabezado en negrita de estos detalles, que debe aparecer una vez (el texto plano aparece dos veces, porque la pestaña lo cita); la de diseño, buscando el texto de la decisión 33.
- **ADR del núcleo 0031 a 0033** en `docs/decisiones/`, con su índice. Mismo formato que la 0030 (estado, fecha, contexto, decisión, alternativas y consecuencias), con las consecuencias medidas y enlaces al anexo de la tarea que las mide: 60 días y 81,4 MB en la 0032, escritura sin sobrescribir con `os.link` en la 0033.
- **ADR de la app APP-0001 a APP-0003** en `app/docs/decisiones/`, con su índice. Las consecuencias recogen lo que costó cada decisión: cachés, fragmentos y límites de AppTest en la APP-0001; un solo `uv.lock` y el `uv sync --all-packages` en la APP-0002; sandbox, reglas, hooks y la comparación del diario en la APP-0003.
- **Diario de la fase** en `app/docs/diario/fase-1.md`: una entrada por tarea A.0 a A.7 con el formato del README, escrita desde la sección «Notas para el diario» de los PR #28 a #38 y desde este anexo. Después, una sección «Codex frente a Claude Code» que compara con el diario del hito 3: plan y preguntas, permisos y sandbox, errores y correcciones tras la revisión, hallazgos de `@codex review`, tiempo y consumo. Termina con «Reflexiones de Pedro» vacía, que escribe él.
- **README de la app** (`app/README.md`): qué es, cómo arrancarla, las seis páginas, `EDSIM_EJECUCIONES`, tests rápidos y completos, la frontera con el núcleo y enlaces a la especificación, las ADR y el diario. El README raíz añade una línea que remite a él.
- **Retoques pendientes:** la regla de las marcas `slow` en `app/AGENTS.md`, y «EDsim Lab» como título de la pestaña del navegador con `st.set_page_config`.
- **Criterios de aceptación:** el PR trae una tabla con cada criterio y su evidencia: el test que lo cubre, por nombre, o la comprobación manual que hace Pedro en el navegador. El agente no marca como cumplido lo que no ha comprobado.
- **Último commit, la exportación final** de esta pestaña, con el anexo de la A.8 escrito en el chat durante la revisión y los criterios marcados.
- **Etiqueta:** tras la fusión, `app-v0.1.0` anotada sobre el commit de `main`, que crea y sube Pedro (o el agente con su permiso).

## Criterios de aceptación

- [x] `uv run --package edsim-app edsim-app` abre la app en `http://localhost:8501` y las seis páginas funcionan con una ejecución de 14 días.
- [x] Desde la app se edita el centro, se guarda una variante, se ve la carga prevista y se simula sin tocar la terminal.
- [x] Una ejecución de la app y otra de `edsim motor simular` con los mismos parámetros tienen el mismo log.
- [x] Resultados muestra los mismos KPIs, ocupaciones y errores de Little que el resumen de la CLI.
- [x] Cualquier episodio tiene su línea temporal, con tramos contiguos que suman su estancia.
- [x] Comparar detecta el emparejamiento y, con una ejecución consigo misma, da cero en todo.
- [x] Los contadores del replay coinciden con `step_curves` en todos los minutos de una ejecución de prueba.
- [x] Se cumplen los objetivos de rendimiento, o la tarea A.2a deja medido y justificado otro límite.
- [x] El núcleo no importa Streamlit, pandas ni `edsim_app`, y un test lo comprueba.
- [x] CI en verde con los jobs `tests` y `tests-app`.

## Preguntas abiertas

- Resuelta antes de la A.8: la app se llama «EDsim Lab», título de la pestaña del navegador.
- Resuelta en la A.2a: límite de 60 días por ejecución y 14 por defecto, con las medidas del anexo.
- Resuelta en la A.4: todas las gráficas de la app se hacen en Altair, por la interactividad; las de matplotlib siguen solo en la CLI y los notebooks.

## Anexo: guía de referencia de la fase 1

### Tarea A.0: preparar Codex

PR #28 (rama `chore/app-codex`), implementado con Codex (codex-cli 0.166.0, extensión de Cursor en WSL) y fusionado por Pedro con *squash and merge* el 3 de noviembre de 2026. Tres commits: `AGENTS.md` como fuente única, la configuración de `.codex/` y la precisión de la regla de tests tras la revisión de Codex.

**Qué se hizo**

- Codex instalado en WSL con el script oficial, revisado antes de ejecutarlo; sesión iniciada con la cuenta de ChatGPT; extensión de Cursor instalada en el lado de WSL.
- `AGENTS.md` en la raíz con todas las reglas de `CLAUDE.md`, comprobadas una a una con una tabla, más cuatro añadidos (leer `app/AGENTS.md`, explicar en español, no arrancar servidores, permiso para `uv sync`) y las *Review guidelines*. `CLAUDE.md` queda en `@AGENTS.md` y cuatro líneas propias de Claude Code.
- `.codex/config.toml` (sandbox `workspace-write`, aprobación `on-request`), 14 reglas con ejemplos `match` y `not_match`, y un hook `Stop` que formatea y ejecuta los tests rápidos.
- Codex cloud conectado a GitHub con acceso solo a `edsim`; entorno en la nube (Python 3.13, `uv sync` y hooks; sin internet salvo los dominios de gestores de paquetes); revisión de código manual con `@codex review`.

**Cambios respecto al plan**

- `uv sync` quedó en «preguntar» y no en «permitir», para que la regla haga cumplir lo que dice `AGENTS.md`.
- No hizo falta un PR de prueba aparte: el propio PR de la tarea fue la prueba de extremo a extremo (commits, push, PR y revisión).
- La regla «código nuevo sin tests» se precisó para el paquete y la app; los hooks se verifican a mano.
- El hito 3 ya estaba cerrado (`v0.3-hito3`), así que no hubo conflicto con la tarea 3.9.

**Conceptos**

| Concepto | Qué hay que entender |
| --- | --- |
| Sandbox y aprobación | `workspace-write` limita la escritura al repositorio y corta la red; `on-request` pide permiso para salir de esos límites |
| Rutas protegidas | `.git` y `.codex/` son de solo lectura dentro del sandbox: el agente no puede cambiar sus propios límites, y su configuración se aprueba una vez, nunca «siempre» |
| Reglas | `prefix_rule` decide qué comandos salen del sandbox sin preguntar, preguntando o nunca; si coinciden varias, gana la más restrictiva; `match` y `not_match` son tests de la propia configuración |
| Comandos compuestos | Codex trocea `a && b` al ejecutar y evalúa cada parte; `codex execpolicy check` recibe argumentos y no trocea, así que las partes se comprueban por separado |
| Hooks y confianza | Un hook es código que se ejecuta solo: Codex no lo ejecuta hasta aprobarlo con `/hooks`; su stdout queda reservado al protocolo |
| `AGENTS.md` anidados | Codex combina los del camino hasta la carpeta de trabajo; por eso se arranca en la raíz y el raíz remite a `app/AGENTS.md` |
| Codex cloud y entornos | El código vive en GitHub; un entorno es la receta de un contenedor temporal que clona, prepara, trabaja y se destruye. Preparación con red, trabajo sin red |
| Sesiones | Cada mensaje reprocesa toda la sesión: una por tarea; `/status` y `/compact` para las largas; `codex resume` y `~/.codex/sessions/` para consultar las antiguas |

**Comprobaciones y resultados**

| Comprobación | Resultado |
| --- | --- |
| `codex execpolicy check` de siete comandos | Decisiones esperadas según el informe de Codex, revisado por Pedro |
| `AGENTS.md` al empezar la sesión | Cargado automáticamente |
| `git status` y `git log` en vivo | Sin pedir permiso (regla `allow`) |
| `gh pr merge 999` en vivo | Bloqueado por la política antes de ejecutarse, sin buscar otra vía |
| Entorno en la nube desde cero | 1.041 tests y 3 notebooks en verde, lint y formato correctos, simulación de 758 pacientes sin violaciones y ningún fichero versionado cambiado. La primera publicación del entorno falló por un error del servicio; la revisión del PR funcionó después |

**Revisión del PR: dos revisores**

|  | Codex (`@codex review`) | Chat del proyecto |
| --- | --- | --- |
| Hallazgos | P1: el script del hook no tiene tests, aplicando la regla de `AGENTS.md` | El hook formatea en todos los turnos; tras un segundo fallo el turno termina; enlace «Hito en curso» desfasado |
| Estilo | Aplica las reglas escritas de forma literal y sistemática | Razona sobre el comportamiento y el contexto |

Decisión sobre el P1: sin tests para el hook (es una herramienta de desarrollo que se ejecuta en cada turno, como el de Claude Code, que tampoco los tiene); la regla se precisó en `AGENTS.md` y la decisión quedó explicada en el hilo del PR.

**Lecciones aprendidas**

- Una regla de revisión vaga produce falsos positivos. Cuando un revisor automático marca algo que no querías, se precisa la regla; no se ignora al revisor.
- Dos revisores distintos se complementan: ninguno vio lo del otro.
- El agente no debe controlar sus propios límites: la protección de `.codex/` es el equivalente de denegar `gh pr merge`.
- Una prueba solo vale si comprueba lo que crees que comprueba: `execpolicy check` con `&&` habría dado un `allow` engañoso.
- Una sola fuente de instrucciones evita que dos agentes reciban reglas distintas con el tiempo.
- El entorno en la nube demostró que el repositorio se reproduce desde cero fuera del portátil y del CI, solo con `uv.lock` y las instrucciones.
- Antes de ejecutar un script de instalación descargado, se lee.

**Pendiente para la tarea A.1**

- Actualizar el enlace «Hito en curso» de `AGENTS.md` (sigue apuntando al hito 3).
- Crear `app/AGENTS.md` y `app/CLAUDE.md` con `@AGENTS.md`, para que Claude Code también vea las reglas de la app.
- Comprobar que «Automatic reviews» está desactivado en los ajustes de Codex.
- Si no se hizo antes de fusionar: `/memory` en Claude Code debe mostrar `CLAUDE.md` y, importado, `AGENTS.md`.

### Tarea A.1: esqueleto de la app y workspace de uv

PR #29 (rama `feat/app-esqueleto`), implementado con Codex (codex-cli 0.166.0) y revisado en el chat el 3 de noviembre de 2026; se fusiona con *squash and merge* tras la prueba de Pedro en el navegador. Seis commits: especificación, workspace y navegación con tests, frontera, CI y hook, documentación y una aclaración sobre git fuera del sandbox.

**Qué se hizo**

- Workspace de uv: la raíz declara `members = ["app"]` y `app/pyproject.toml` define `edsim-app` 0.1.0 con `edsim` (fuente `workspace`) y `streamlit>=1.66.1`. pandas 3.1.0 y Altair 6.3.0 llegan con Streamlit, sin declararse. Un solo `uv.lock`.
- Seis páginas vacías con `st.navigation` en dos grupos (Ejecutar: Ejecuciones y Simular; Analizar: Resultados, Episodios, Comparar y Replay) y `url_path` en español; Ejecuciones abre en `/`.
- Lanzador `edsim-app`: `python -m streamlit run main.py` en `localhost:8501`, sin navegador ni aviso de email (`headless`) y sin estadísticas de uso; Ctrl+C sale con código 130 sin traza.
- Frontera con dos tests en el núcleo (al importar, en un intérprete nuevo, y estático con `ast`) y el job `tests` en un entorno sin la app.
- CI con un job nuevo, `tests-app` (`--all-packages`); el hook `Stop` de Codex ejecuta también los tests rápidos de la app.
- `app/AGENTS.md`, `app/CLAUDE.md`, los README de decisiones y diario, y los comandos nuevos en el `AGENTS.md` raíz.

**Cambios respecto al plan**

- Orden de los commits: el código antes que la documentación, y la frontera después del workspace, para ejecutar las versiones incorrectas con pandas instalado.
- El lanzador fija `--server.headless true` y `--browser.gatherUsageStats false`, y sale limpio con Ctrl+C.
- `url_path` en español; Streamlit ignora el de la página por defecto, que abre en `/`.
- El diario de la app solo tiene su README: las notas de cada tarea van en el PR y la entrada de la fase se escribe en la A.8.

**Conceptos**

| Concepto | Qué hay que entender |
| --- | --- |
| Workspace de uv | Varios paquetes, cada uno con su `pyproject.toml` y sus dependencias, con un solo `uv.lock` y un solo `.venv`; `{ workspace = true }` hace que `edsim` sea el del repositorio, instalado en modo editable |
| Sincronización exacta | `uv sync` deja el entorno exactamente como el paquete raíz y retira lo demás (24 paquetes, la app incluida); `uv run` no retira nada. Por eso el comando estándar es `uv sync --all-packages` |
| `--package` | Elige el miembro del workspace para `uv run` o `uv sync`; dentro de `app/` se elige solo |
| Frontera declarada y comprobada | Las dependencias del `pyproject.toml` son una promesa: Python no las lee al importar y el entorno es compartido. La comprueban el test y el job `tests`, cuyo entorno no tiene Streamlit ni pandas |
| Comprobación dinámica y estática | Importar y mirar `sys.modules` ve lo que se carga de verdad, también a través de otras bibliotecas; `ast` ve los imports dentro de funciones que no se ejecutan al importar. Se complementan |
| `AppTest` con `st.navigation` | Se arranca desde `main.py`, se llama a `run()` antes de `switch_page` y se comprueba el título de destino: «sin excepciones» pasaría aunque no cambiara de página |
| Aviso de email de Streamlit | La primera ejecución pide un email en la terminal y se bloquea; `--server.headless true` lo evita. El `config.toml` del proyecto se busca en la carpeta desde la que se lanza, así que las opciones van en el lanzador |
| Configuración por paquete | pytest elige `rootdir` y `configfile` a partir de la ruta de los tests: `app/tests` usa `app/pyproject.toml`. Ruff usa el de la raíz; `src = ["src", "app/src"]` clasifica los dos paquetes como propios |

**Comprobaciones y resultados**

| Comprobación | Resultado |
| --- | --- |
| Workspace de prueba en el chat (uv 0.11) | `uv sync` retira la app; `uv run edsim-app` falla desde la raíz sin ella; `--package` y `--all-packages` funcionan. Confirmado por Codex con uv 0.13.6 |
| Ayuda de `streamlit run` | Existen `--server.address`, `--server.port`, `--server.headless` y `--browser.gatherUsageStats` |
| Núcleo sin la app | 1.043 tests en 176 s y 3 notebooks en 29 s, sin Streamlit, pandas ni `edsim_app` instalados |
| Tests rápidos | 1.025 del núcleo (18 `slow` excluidos) y 9 de la app, en un segundo aproximadamente |
| Hook | Ejecución real con `{}` por stdout; con `stop_hook_active=true` no ejecuta nada; un fallo en cualquier comando da código 2 y las últimas 50 líneas por stderr |
| Especificación | Mismo SHA-256 que la exportación del chat, antes y después de pre-commit |

**Versiones incorrectas temporales**

| Mutación | Entorno | Predicción y resultado |
| --- | --- | --- |
| `import pandas` de nivel superior | Con pandas | Fallan las dos comprobaciones. Confirmado |
| `import pandas` dentro de una función | Con pandas | Pasa la dinámica y falla la estática. Confirmado |
| `import pandas` de nivel superior | Solo el núcleo | La dinámica falla con `ModuleNotFoundError` y la estática por el import. Confirmado |

**Revisión del PR**

Revisión en el chat del diff completo, sin `@codex review`: desde esta tarea, la segunda opinión de Codex queda para las tareas críticas. Dos retoques menores se aplazan a la A.2a (ver «Pendiente»). Interrumpir una simulación a medias ya lo cubre la especificación de la A.2a: la ejecución se escribe en una carpeta temporal y se renombra al terminar.

**Lecciones aprendidas**

- Probar un comportamiento en un entorno de juguete antes de especificarlo: el criterio «arranca con `uv run edsim-app`» era falso desde la raíz.
- Una versión incorrecta solo valida si falla por la razón prevista: sin pandas instalado, la comprobación dinámica habría fallado por `ImportError`, no por detectar pandas.
- Las dependencias declaradas son una promesa; un entorno de CI sin la app las convierte en una barrera.
- Cada commit documenta solo lo que ya existe: el orden de los commits también se revisa.
- Los valores por defecto dependen del entorno (`headless` según `DISPLAY`): lo que se ejecuta en WSL se fija de forma explícita.
- Que un comando de git falle dentro del sandbox es el diseño de la A.0, no un error: las reglas actúan cuando se pide salir del sandbox.

**Pendiente para la tarea A.2a**

- `AGENTS.md` raíz: «Hito en curso» sigue apuntando al hito 3, ya cerrado; cambiarlo por «Último hito cerrado: hito 3 (el hito 4 aún no tiene especificación)».
- `tests/test_dependency_boundary.py`: generar el conjunto prohibido del script del subproceso a partir de `FORBIDDEN_PACKAGES`, para que haya una sola fuente.
- Antes de fusionar el PR #29, Pedro añade `tests-app` al ruleset.

### Tarea A.2a: núcleo de ejecuciones

PR #30 (rama `feat/app-ejecuciones-nucleo`), implementado con Codex (codex-cli 0.166.0) y fusionado por Pedro con *squash and merge* el 3 de noviembre de 2026 (`033dc13`). Ocho commits: especificación, retoques de la A.1, caracterización, metadatos y catálogo, servicio, CLI y dos correcciones tras la revisión del chat. Tarea crítica: `@codex review` no encontró problemas importantes.

**Qué se hizo**

- `edsim.runs` con `__all__`: `validate_run_id`, `RunInfo` (exactamente `run.json`, versión de formato 1), `SimulationResult` (`info`, `analysis` y `violations`), `simulate_run` y `RunStore` (`list`, `invalid`, `open`, `exists` y `delete`).
- `simulate_run` copia los TOML en una carpeta oculta junto al destino, carga desde las copias, simula, escribe los CSV con la ruta original como procedencia, comprueba las invariantes con `ground_truth` e `inside`, escribe `run.json` el último y renombra. Un `finally` borra la carpeta temporal ante cualquier fallo, también `KeyboardInterrupt`.
- `edsim motor simular` valida argumentos, configuración y destino, imprime la cabecera y llama a `simulate_run`; guarda por defecto en `resultados/ejecuciones/<run_id>` y rechaza un destino ocupado con código 2. Los fallos internos se propagan.
- Regla del `run_id` en `--run-id`, `simulate_run` y `RunStore`; `default_run_id` no cambia y, si genera un ID que no cumple la regla, se pide uno explícito.
- Retoques de la A.1, dos reglas P1 nuevas en las *Review guidelines* y README.

**Cambios respecto al plan**

- Plan: `SimulationResult` en lugar de campos opcionales en `RunInfo`; `default_run_id` intacto; `exists` indica si el nombre está ocupado e `invalid()` lista las carpetas no válidas; destino de la caracterización inexistente; test explícito que modifica el original tras copiarlo; limpieza con `KeyboardInterrupt`; ámbitos de commit del núcleo.
- Tras la revisión del PR: la CLI capturaba como error de uso cualquier `OSError` o `ValueError` del servicio, también los fallos internos, e imprimía la cabecera después de simular. Ahora valida antes, imprime la cabecera al principio y solo captura la carrera de `FileExistsError`.
- Tras la revisión del PR: `tempfile.mkdtemp` crea la carpeta con permisos 0700, que la ejecución publicada heredaba. Ahora toma los permisos de un `mkdir` normal, observados en una carpeta de referencia para no tocar la `umask` del proceso.

**Conceptos**

| Concepto | Qué hay que entender |
| --- | --- |
| Escritura atómica | Se prepara todo en una carpeta oculta del mismo disco y se publica con un solo renombrado; `run.json` va el último. Quien mira el catálogo ve la ejecución entera o no la ve |
| Copiar primero | Simular desde la copia garantiza que lo simulado y lo archivado son los mismos bytes; leer el original dos veces abre la puerta a que cambie entre lecturas |
| Test de caracterización | Antes de refactorizar se congela lo que el código produce hoy (SHA-256 del log y de los CSV). Después no se toca: si falla, el refactor ha cambiado el comportamiento |
| Validar en la frontera | La regla del `run_id` se aplica donde un texto se convierte en ruta (CLI, servicio y catálogo), no en el motor, que solo lo escribe en el log |
| Tipos que dicen lo que son | `RunInfo` es siempre `run.json` completo; `SimulationResult` añade lo que solo existe recién simulado. Sin campos `None` según la procedencia |
| Ocupado frente a válido | Un nombre puede estar ocupado por una carpeta incompleta: `exists` responde a «¿puedo escribir aquí?» y `invalid()` a «¿qué hay roto?» |
| Error de uso frente a fallo interno | El código 2 dice «has pedido algo mal»; un fallo del programa debe verse con su traza. Capturar excepciones amplias mezcla los dos |
| Permisos y `umask` | `mkdtemp` crea carpetas privadas (0700) por seguridad; al publicarlas hay que devolverles los permisos normales |
| Medir en procesos nuevos | Cada medida en un proceso limpio, con la memoria máxima del proceso (incluye el intérprete y las bibliotecas) y tres muestras |

**Medidas** (centro base, semilla 2026, 2 días de calentamiento; medianas de tres muestras)

| Días | Simular | Log | Eventos | Leer | Analizar | Leer + analizar | Memoria máxima |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 14 | 2,0 s | 18,6 MB | 49.843 | 0,57 s | 0,09 s | 0,61 s | 186 MiB |
| 30 | 4,9 s | 41,6 MB | 111.545 | 1,41 s | 0,28 s | 1,66 s | 256 MiB |
| 60 | 12,4 s | 81,4 MB | 218.501 | 2,63 s | 0,89 s | 3,82 s | 373 MiB |

El log crece de forma casi lineal, entre 1,33 y 1,39 MB por día, y todas las ejecuciones salieron sin violaciones. Abrir una ejecución de 14 días cumple de sobra el objetivo de 3 s; una de 60 días tarda unos 3,8 s. Se mantiene el límite de 60 días y el valor por defecto de 14.

**Versiones incorrectas temporales**

| Mutación | Predicción | Resultado |
| --- | --- | --- |
| Escribir directamente en el destino | Tras un fallo queda una ejecución a medias publicada | Falla la atomicidad con `RuntimeError` y con `KeyboardInterrupt` |
| Quitar la validación del ID en `delete` | `-x` está dentro de la carpeta, pero la regla debe rechazarlo | No se lanza el `ValueError`: borra `-x` |
| Cargar el original después de copiarlo | El log deja de coincidir con la configuración archivada | Falla la igualdad del log (primera diferencia en el byte 6.251) |

La primera ejecución de la mutación de escritura directa falló antes de tiempo: el test buscaba el log solo bajo un nombre oculto. Se corrigió el test, y entonces falló por la razón prevista.

**Comprobaciones**

| Comprobación | Resultado |
| --- | --- |
| Caracterización | Sin cambios desde su commit, anterior al refactor, y en verde después |
| Suite rápida del núcleo | 1.099 tests (18 `slow` excluidos) en 33 s |
| Suite completa del núcleo | 1.117 tests en 199 s |
| App | 9 tests en 1,1 s |
| Especificación | Mismo SHA-256 que la exportación del chat |

**Revisión del PR: dos revisores**

|  | Codex (`@codex review`) | Chat del proyecto |
| --- | --- | --- |
| Hallazgos | Ninguno importante | Errores internos convertidos en errores de uso; cabecera después de simular; permisos 0700 heredados de `mkdtemp`; `delete` no puede borrar nombres fuera de la regla ni enlaces (para la A.2b) |
| Estilo | Comprueba el diff contra las reglas escritas | Razona sobre el comportamiento visible de la herramienta y sobre el futuro (Docker en el hito 8) |

**Lecciones aprendidas**

- Un test de caracterización se diseña para el código de después: con `--salida tmp_path` habría fallado tras el refactor y habría que haberlo tocado.
- Un hash de un CSV incluye la procedencia: rutas relativas o el test depende de la máquina.
- Capturar excepciones amplias para dar mensajes amables esconde los fallos del programa.
- Que un test se ponga rojo no basta: tiene que ponerse rojo por la razón prevista (la mutación de escritura directa lo demostró).
- Las respuestas de un catálogo deben coincidir con lo que rechaza quien escribe: «no existe» y «no puedo escribir» a la vez confunden.
- Un revisor automático sin hallazgos no sustituye a la revisión del comportamiento.

**Pendiente para la tarea A.2b**

- Las páginas vacías de la A.1 siguen diciendo «La tarea A.2 añadirá…» en Ejecuciones: la A.2b la sustituye por la página real.
- `invalid()` incluye nombres fuera de la regla y enlaces simbólicos que `delete` no puede borrar: la página los muestra con su motivo y explica que se borran a mano.
- pandas pasa a ser dependencia directa de `edsim-app` en cuanto la app lo importe.

### Tarea A.2b: página Ejecuciones y estado compartido

PR #31 (rama `feat/app-ejecuciones`), implementado con Codex (codex-cli 0.166.0), revisado en el chat y probado por Pedro en el navegador; fusionado con *squash and merge* el 3 de noviembre de 2026 (`3c48833`). Seis commits: especificación, núcleo, cambio de `pages/` a `views/`, estado compartido, página y botón del centro base. Sin `@codex review`: no es tarea crítica.

**Qué se hizo**

- Núcleo: `RunInfo.arrivals_per_day`, `RunStore.archive(run_id) -> bytes` (los seis ficheros en la raíz del zip, solo ficheros regulares) y `RunConfigurationError(ValueError)`, que envuelve solo la lectura del original y la validación de la copia.
- App: `state.py` (carpeta del catálogo con `EDSIM_EJECUCIONES`, selección y marcas A y B con claves propias, `?run=` reescrito en cada recarga, limpieza de lo que ya no está en disco), `frames.py` (tabla con cabeceras en español y coma decimal con `Styler`), `help.py`, `defaults.py` y `views/runs.py`.
- Barra lateral con la ejecución elegida y las marcas en las seis páginas.
- pandas y Jinja2 pasan a ser dependencias directas de `edsim-app`.

**Cambios respecto al plan**

- Aprobados antes de implementar: `RunConfigurationError`, Jinja2 explícito y la comprobación en cada recarga de que la selección y las marcas siguen en disco.
- Durante la implementación: la carpeta `pages/` activaba la navegación antigua de Streamlit y Replay se ejecutaba sin pasar por `main.py`. Codex paró y preguntó; se renombró a `views/` con un test de guarda.
- `st.dialog` no persistía en `AppTest`: el borrado se confirma en dos pasos, y cambiar la selección cancela el borrado pendiente.

**Conceptos**

| Concepto | Qué hay que entender |
| --- | --- |
| URL y estado de sesión | Streamlit borra los parámetros de la URL al cambiar de página. Durante la sesión manda `st.session_state`; `main.py` vuelve a escribir `?run=` en cada recarga y `st.switch_page` lo pasa con `query_params` |
| Estado de un widget | Cuando una página deja de mostrarse, Streamlit borra el estado de sus widgets. Lo que debe sobrevivir a la navegación va en claves propias, no en la `key` del widget |
| Comportamiento implícito | Una carpeta `pages/` junto al script principal activa la navegación antigua. Un nombre de carpeta puede cambiar lo que hace una biblioteca |
| Límites de `AppTest` | No puede pulsar filas de `st.dataframe` (por eso el selectbox) y su `switch_page` conserva los parámetros que el navegador borra: los tests limpian la URL a mano para reproducir el navegador |
| Descarga diferida | `st.download_button` con una función: el zip se crea al pulsar, en otro hilo, no en cada recarga |
| Los ficheros son la verdad | La sesión puede quedarse vieja si algo cambia fuera de la app; cada recarga comprueba en disco lo que recuerda |
| Clasificar errores | La app muestra como mensaje solo lo que es culpa de la entrada (`RunConfigurationError`, `FileExistsError`) y deja ver el resto. Leer el original y escribir la copia se clasifican por separado |
| Formato sin perder el dato | `Styler.format(decimal=",")` muestra la coma sin convertir los números en texto, así que la tabla sigue ordenándose bien |

**Versiones incorrectas temporales**

| Mutación | Predicción | Resultado |
| --- | --- | --- |
| No reescribir `?run=` en `main.py` | Se pierde el parámetro al navegar por la barra lateral | Falla la restauración en Replay (`KeyError: 'run'`) |
| No limpiar las marcas al borrar | Las marcas apuntan a la ejecución borrada | Falla el borrado confirmado: la barra lateral sigue mostrando A y B |
| Dividir las llegadas entre todos los días | El calentamiento entra en el denominador | Falla el caso calculado a mano (180 en lugar de 300) |
| Quitar la comprobación con `exists` | Un borrado desde la terminal no se limpia ni avisa | Fallan los dos tests de borrado externo |
| Volver a llamar `pages/` a la carpeta | Fallan la guarda y la restauración en Replay | Fallan exactamente esos dos |

**Comprobaciones**

| Comprobación | Resultado |
| --- | --- |
| Suite rápida del núcleo | 1.130 tests (18 `slow` excluidos) en 36 s |
| Suite completa del núcleo | 1.148 tests en 203 s |
| App | 48 tests en 7,9 s |
| Navegador (Pedro) | Centro base desde el catálogo vacío, selección que sobrevive a la navegación, enlace directo a `/replay?run=r2026`, marcas, zip, borrado desde fuera y desde la app |

**Revisión del PR**

Revisión en el chat del diff completo, sin hallazgos que bloquearan. Dos detalles quedan para más adelante (ver «Pendiente»).

**Lecciones aprendidas**

- Compartir una selección entre páginas exige separar la clave de la sesión de la del widget.
- Un test de navegación debe comprobar la página, el contenido compartido y la URL: el test superficial de la A.1 no vio que Replay se saltaba `main.py`.
- Cuando una biblioteca no se comporta como se esperaba, parar y preguntar fue lo correcto: ni se parcheó Streamlit ni se rebajó el test.
- Una herramienta de test puede comportarse distinto que el navegador; el test tiene que reproducir el navegador, no la herramienta.
- La clasificación de un error depende de dónde se captura: separar leer el original de escribir la copia evita llamar «configuración no válida» a un disco lleno.

**Pendiente**

- A.3b: la cabecera de la tabla debe decir «Fecha de creación (UTC+1)»; en verano España está en UTC+2 y la hora mostrada no coincidiría con el reloj.
- A.4: la comprobación de cada recarga usa `exists`, que da verdadero también para una carpeta rota. Resultados abrirá la ejecución con `open` y mostrará un mensaje claro si falla.

### Tarea A.3a: núcleo de Simular

PR #32 (rama `feat/app-simular-nucleo`), implementado con Codex (codex-cli 0.166.0) y fusionado por Pedro con *squash and merge* el 3 de noviembre de 2026 (`5f8abc3`). Seis commits: especificación, validación por campo, tomlkit, variantes y diferencias, carga ofrecida y una corrección que Codex encontró en su propia revisión. Tarea crítica: `@codex review` no encontró problemas y la revisión del chat tampoco encontró nada que bloqueara.

**Qué se hizo**

- `engine/center.py`: una sola tabla une cada clave TOML con su comprobación y la usan `CenterConfig`, `read_center_values`, `validate_center_values` (todos los errores, uno por clave), `center_from_values` y `load_center`, que conserva sus mensajes (`tests/test_center.py` sin tocar). Una clave literal con punto en la raíz del TOML no se confunde con una clave de tabla.
- `runs/variants.py`: `write_variant` cambia con tomlkit solo los elementos que difieren, devuelve los bytes de la base si no hay cambios, publica con `os.link` (o `os.replace` al sobrescribir) desde un temporal oculto `.tmp` con los permisos de un fichero normal; `center_diff` compara centros normalizados; `MAX_VARIANT_NAME_LENGTH = 42`.
- `runs/offered.py`: `offered_work` con días previos adaptativos, ventana desde `fecha_inicio`, carga y capacidad minuto a minuto y utilización por turno para médicos, boxes y enfermería de triaje.
- tomlkit 0.15.2 como dependencia del núcleo; reexportaciones en `edsim.runs`, incluidos `load_center`, `load_profile` y `ArrivalProfile`.

**Cambios respecto al plan y a la especificación**

- Días previos adaptativos, max(1, ceil(edad máxima / 1440)), en lugar de «un día más»: con duraciones largas, un día dejaba fuera trabajo de pacientes llegados antes.
- La identidad de Little se comprueba solo con tasa constante o periódica diaria; con perfiles generales se comprueba la convolución a mano.
- Ventana desde `fecha_inicio` con un perfil de fecha retrocedida, para que la gráfica hable del mismo calendario que la simulación.
- Publicación con `os.link` en lugar de comprobar y sustituir; nombre de variante de hasta 42 caracteres.
- Añadidos tras revisar el plan: permisos normales del temporal, temporal invisible para `*.toml`, reexportaciones para la página y medidas con `days=7`.
- La validación por campo vive en `engine/center.py`, junto a `CenterConfig`, no en `runs/variants.py`.

**Conceptos**

| Concepto | Qué hay que entender |
| --- | --- |
| Valor en bruto, normalizado y texto | `0.70` y `0.7` valen lo mismo pero son bytes distintos; el reparto en porcentajes cambia al normalizarse. El editor trabaja con lo escrito; el centro normalizado sirve para validar y comparar |
| Una sola fuente de reglas | Una tabla clave → comprobación alimenta la construcción, el editor y el cargador: imposible que discrepen |
| Edición con conservación de formato | tomlkit guarda comentarios y espacios; solo se tocan los elementos que cambian, y sin cambios no se reescribe nada |
| Publicar sin sobrescribir | Comprobar y después sustituir deja una carrera; un enlace duro (`os.link`) crea el nombre de forma atómica y falla si ya existe |
| Permisos de los temporales | `mkstemp` crea ficheros privados (0600) y la publicación los hereda: hay que darles los permisos normales sin tocar la `umask` global |
| Carga ofrecida | m(t) = trabajo que la demanda mantendría ocupado sin colas, una convolución de λ(t) con la probabilidad de ocupar el recurso a cada edad, estimada con una muestra |
| Arranque vacío y días previos | m(t) empieza vacía; hacen falta tantos días previos como la ocupación más larga. Una lognormal no tiene techo: el máximo de la muestra, y con él los días previos, depende de la muestra |
| Little en una ventana | La media de m(t) es λ̄ × tiempo medio solo si no entra ni sale trabajo neto por los bordes: tasa constante o periódica con la ventana. Con factores semanales y mensuales es una aproximación |
| Error de Monte Carlo | La carga se estima con una muestra; dos semillas distintas miden cuánto cambia el resultado por azar |

**Medidas** (centro y perfil base, 7 días; medianas de tres procesos)

| Muestra | Tiempo | Días previos (semillas 73001 / 73002) | Mayor diferencia de utilización entre semillas |
| --- | --- | --- | --- |
| 5.000 | 0,04 s | 1 / 1 | 0,030 (boxes) |
| 20.000 | 0,19 s | 2 / 1 | 0,006 (boxes) |
| 50.000 | 0,42 s | 2 / 1 | 0,007 (boxes) |

Se usa 50.000 pacientes con la semilla 73001, elegida antes de explorar. La ocupación más larga observada fue de 2.210 minutos, unas 37 horas.

**Versiones incorrectas temporales**

| Mutación | Resultado |
| --- | --- |
| Devolver solo el primer error | Faltan tres diagnósticos en el test de errores simultáneos |
| Reasignar todas las claves | Se pierde `0.70`: fallan cuatro casos de saltos de línea y el de final sin salto |
| Comparar el reparto sin tolerancia | Diferencia falsa entre porcentajes y fracciones, solo en los últimos bits |
| Comprobar y publicar con `os.replace` | La carrera sustituye el fichero ajeno sin `FileExistsError` |
| Publicar con el modo de `mkstemp` | Seis fallos por 0600 |
| Temporal con extensión `.toml` | Visible como variante antes de publicarse |
| No descartar los días previos | Fallan Little con tasa constante y periódica y la plantilla constante |
| Forzar un día previo con ocupaciones largas | La carga sale por debajo: 5,55 médicos frente a 6,20 |

**Comprobaciones**

| Comprobación | Resultado |
| --- | --- |
| Suite rápida del núcleo | 1.216 tests (18 `slow` excluidos) en 57 s |
| Suite completa del núcleo | 1.234 tests en 230 s |
| App | 48 tests en 12 s |
| Notebooks en modo rápido | 3 en 29 s |

Un test falló por 1,8 × 10⁻¹⁵ porque `ArrivalProfile` renormaliza sus factores; se aísló la causa con factores unidad, sin cambiar la semilla ni ensanchar la tolerancia.

**Lecciones aprendidas**

- Una predicción sin calcular («el centro base usa un día previo») puede estar mal: el test comprueba la regla y su resultado, no la intuición.
- Una identidad matemática tiene condiciones; un test que la exige fuera de ellas falla por una razón correcta.
- Las preguntas de Codex durante el plan mejoraron tres decisiones de la especificación: pararse a preguntar es parte del método.
- El mismo error de permisos apareció dos veces, con carpetas (A.2a) y con ficheros (A.3a): la lección es el patrón, no el caso.

**Pendiente para la tarea A.3b**

- Cabecera «Fecha de creación (UTC+1)» en Ejecuciones (de la A.2b).
- `offered_work` tarda 0,4 s: la página lo guarda en caché para no recalcular en cada cambio.

### Tarea A.3b: página Simular

PR #33 (rama `feat/app-simular`), implementado con Codex (codex-cli 0.166.0) y fusionado por Pedro con *squash and merge* el 3 de noviembre de 2026 (c7046af). Siete commits: especificación, variantes y propuestas de `run_id`, números derivados, cabecera UTC+1, borrador y editor, carga prevista y ejecución. Tarea no crítica: sin `@codex review`; plan y PR revisados en el chat. Se fusionó antes de la ronda de correcciones de la revisión del PR, que entraron después en el PR #34 (a076ab9).

**Qué se hizo**

- Núcleo (`edsim.runs`): `list_variants` (ficheros `.toml` regulares, nombre válido de hasta 42 caracteres, sin enlaces y sin leer el contenido); `RunStore.suggest_run_id` (original, `-2`, `-3`…; `None` si el sufijo no cabe en 64 caracteres; cuentan como ocupados las carpetas no válidas, los ficheros y los enlaces rotos); `summarize_center`, que devuelve `CenterSummary` y `DurationSummary` (suma del reparto, reparto normalizado, media exp(μ + σ²/2), curva de 122 puntos y porcentajes globales), y la reexportación de `config_fingerprint`.
- `draft.py`: el borrador vive en claves propias (valores, copia guardada y origen); los widgets se rellenan desde él en cada recarga y sus callbacks copian solo el campo editado. Los ajustes de ejecución y el modo del `run_id` tienen sus propias claves.
- Página Simular en tres pasos: editor por bloques con errores por campo y tipos fijos (enteros en turnos y recursos); cambios frente a la base; números derivados y curvas; «Guardar como variante» desde el origen, con confirmación de sobrescritura y de cambio de origen; carga prevista con gráfica Altair de medias de 15 minutos y tabla de utilización; ejecución con semilla de texto, `run_id` automático o manual y un solo `st.status`.
- `preview.py` (`st.cache_data`, 3 entradas; clave: valores en bruto, ruta y huella del perfil), `charts.py`, `frames.py` (`offered_frame` y `utilization_frame`) y `help.py`.
- Cabecera «Fecha de creación (UTC+1)» en Ejecuciones. Altair 6.3.0 pasa a dependencia directa de la app con `uv lock --offline`; ninguna versión cambia.

**Cambios respecto al plan**

- Diez ajustes de la revisión del plan: semilla `[0-9]{1,20}`; tipos de widget fijos por clave; origen releído en cada recarga; argumentos exactos de `simulate_run` (rutas sin resolver, `output_dir` y sin `variant`); nombre «centro» reservado al centro base; pruebas añadidas; editar cancela la confirmación de sobrescritura; contrato de `summarize_center` (lanza `ValueError`); commit UTC+1 aparte, y `uv.lock` sin red.
- La fixture de configuración usaba `tmp_path/config` y rompía tres tests de errores de Ejecuciones; pasó a `simulation-config`.
- Casos añadidos: perfil ausente o no válido y errores internos de la carga prevista, que no se ocultan.
- Los tests de la app calculan la carga con una muestra de 32 pacientes, para ir rápido; las medidas usan la muestra real de 50.000.

**Conceptos**

| Concepto | Qué hay que entender |
| --- | --- |
| Estado persistente y estado de widgets | Streamlit borra las claves de los widgets de una página que no se pinta. El borrador vive en claves propias y los widgets se rellenan desde él en cada recarga |
| Caché por contenido | `st.cache_data` guarda por argumentos. La huella del perfil entra en la clave porque la ruta y la fecha de modificación no garantizan el contenido |
| Una confirmación autoriza una operación concreta | Confirmar la sobrescritura vale para unos valores, un nombre y un origen; cambiar cualquiera la cancela |
| Modo automático o manual | El `run_id` propuesto sigue a la semilla y al origen hasta que se edita; el modo es estado del formulario y sobrevive a la navegación |
| Validar texto como número | `int()` acepta espacios, guiones bajos y cifras Unicode. La semilla se valida con `[0-9]{1,20}`, y así el `run_id` cabe en 64 caracteres con nombres de hasta 42 |
| Media y mediana de una lognormal | La mediana es exp(μ) y la media exp(μ + σ²/2), siempre mayor: la cola de casos lentos sube la media. La curva usa puntos equiespaciados en escala logarítmica entre μ − 3σ y μ + 3σ |
| Medias para ver y cifra oficial | Las medias de 15 minutos solo dibujan; la utilización sale del núcleo, y un test comprueba que ambas coinciden por turno |

**Medidas** (centro y perfil base, 7 días, muestra de 50.000 pacientes, dos días previos; medianas de tres medidas con AppTest, sin pintado del navegador)

| Operación | Tiempo |
| --- | --- |
| `offered_work` sin caché | 0,462 s |
| Primera entrada en Simular, caché vacía | 0,975 s |
| Recarga con caché | 0,067 s |
| Cambiar el recurso de la gráfica | 0,063 s |
| Cambiar la semilla de ejecución | 0,067 s |

**Versiones incorrectas temporales**

| Mutación | Resultado |
| --- | --- |
| Borrador ligado a las claves de los widgets | Se pierde al navegar: médicos de mañana vuelve a 12 en lugar de 13 |
| Simular con cambios sin guardar | El test encuentra «Simular» activado |
| Clave constante en lugar de la huella del perfil | Dos cálculos en lugar de tres al cambiar el perfil en la misma ruta |
| Regenerar siempre el identificador | Sale `centro-r7` en lugar de `custom` |
| Guardar siempre desde el centro base | Falta «Comentario propio» en los bytes de la variante |
| No cancelar la sobrescritura al editar | «Confirmar sobrescritura» sigue visible |

**Comprobaciones**

| Comprobación | Resultado |
| --- | --- |
| Ruff y formato | 156 ficheros conformes |
| Suite rápida del núcleo | 1.224 tests (18 slow excluidos) en 46,9 s |
| Suite completa del núcleo | 1.242 tests en 230,9 s |
| App | 96 tests en 24,4 s |
| Notebooks en modo rápido | 3 en 27,6 s |

**Revisión del PR: hallazgos, corregidos en el PR #34**

- Los campos decimales usan el formato `%.17g`, y el navegador muestra 0.29999999999999999 en lugar de 0.3. Con `%.15g` se ve igual que en el TOML.
- Una variante editada a mano con valores que su widget no representa rompe o falsea la página: `boxes = "treinta"` lanza un error, `30.5` se ve como 30 y `true` como 1.
- La lista de cambios muestra la clave sin etiqueta en español y los números con punto decimal.
- La gráfica de carga recibe fechas con zona horaria, y Vega-Lite las pinta en la hora del navegador. Coincide con UTC+1 por casualidad: perfil de enero y navegador en Madrid.
- Menores: el aviso de cambio de origen sigue tras un fallo de lectura; `preview.py` reutiliza `RunConfigurationError` del núcleo; un `centro.toml` creado a mano en `resultados/variantes/` aparecería en el selector.

**Lecciones aprendidas**

- AppTest comprueba valores, no lo que se pinta: un formato que ensucia cada campo pasa los 96 tests. Lo que solo se ve en el navegador lo cubre la prueba en el navegador.
- Un ajuste de revisión puede pasarse de largo: «no redondear lo que se ve» llevó a 17 cifras. La regla buena es la mínima que cumple el objetivo (15).
- El mismo problema vuelve por otro camino: la cabecera UTC+1 se corrigió y la gráfica lo repite en el navegador.
- Las fixtures también tienen contratos: invadir la carpeta que controla otro test convierte un test de error en otra cosa.
- El estado de un formulario incluye su modo (automático o manual), no solo sus valores.

**Pendiente para la tarea A.4**

- Hecho: las correcciones de la revisión del PR #33 entraron en el PR #34 (a076ab9), un commit `fix(app)` propio.
- Resultados abre la ejecución con `RunStore.open` y da un mensaje claro si falla (de la A.2b).

### Tarea A.4: página Resultados

PR #35 (rama `feat/app-resultados`), implementado con Codex (codex-cli 0.166.0) y fusionado por Pedro con *squash and merge* el 3 de noviembre de 2026 (4871075). Siete commits: especificación, KPIs y cumplimiento, lectura de resultados y ficheros, medias y máximos por bloque, cabecera e indicadores, ocupación y curvas, y una corrección tras la revisión del PR. Tarea no crítica: sin `@codex review`. Las correcciones de la A.3b entraron antes, en el PR #34 (a076ab9).

**Qué se hizo**

- `runs/metrics.py`: `window_kpis` devuelve `WindowKPIs` (n, llegadas por día, censo medio, estancia y puerta-médico con media y p90, episodios desalojados, desalojos totales y fracción de ingreso). `window_compliance` devuelve `WindowCompliance`: el `Compliance` diario y un `LevelCompliance` por nivel, con los pacientes que superan el máximo contados como enteros.
- `runs/results.py`: `read_run_header` (metadatos y SHA-256 de `run.json`) y `read_run_results`, que lee las copias guardadas y devuelve `RunResults` (metadatos, centro, fecha de inicio, `RunAnalysis`, KPIs, cumplimiento, perfil horario del censo y violaciones recalculadas si las hay). Errores públicos `RunReadError` (lectura o validación de una entrada) y `RunAnalysisError` (ventana sin episodios completados, comprobada antes de `analyze_run`).
- `runs/curves.py`: `curve_blocks` (media exacta y máximo por bloque, con el valor vigente al empezar) y `curve_steps` (escalones recortados a una ventana).
- `RunStore.read_file` y `archive` comparten la lista de los seis ficheros y rechazan enlaces y entradas que no sean ficheros regulares. Reexportaciones en `edsim.runs`, incluidos `EpisodeRecord`, `RunAnalysis`, `StepCurves`, `Violation`, `TIMEZONE` y `SUMMARY_MEASURES`.
- Página Resultados: cabecera, invariantes, nueve KPIs, tabla y gráfica de esperas por nivel frente a Manchester, mapa de ocupación, curvas por semana con media, máximo, plantilla y calentamiento sombreado, perfil diario, Little con λ·W y cinco descargas diferidas.
- `results.py` con `st.cache_resource` (4 entradas; clave: raíz del catálogo, `run_id` y huella de `run.json`). `state.py` abre la ejecución elegida en cada recarga y limpia la selección con su motivo si falla.

**Cambios respecto al plan y a la especificación**

- `st.cache_resource` en lugar de `st.cache_data`: `RunAnalysis` contiene `mappingproxy`, que pickle no serializa, y `cache_data` deserializaría el análisis en cada recarga. El resultado se comparte y se trata como de solo lectura; un test lo compara con uno recién calculado tras recargas y navegación.
- La comprobación previa construye `episode_table` dos veces; cuesta del 3,2 al 3,9 % del servicio, por debajo del umbral del 10 %, y se queda.
- Decisiones del plan: `RunAnalysis` obligatorio y `RunAnalysisError` específico; recuentos 0 y estadísticas `None` sin población; referencia solo en las curvas de recursos ocupados; columna λ·W; excedidos como enteros.
- `curve_steps` elimina escalones consecutivos con el mismo valor. La ocupación tiene además una tabla desplegable con los nueve valores.
- Corrección tras la revisión: mensaje de carga, explicación del nivel 1, rótulo de semana «\[día 0, día 7)» y texto blanco sobre las celdas oscuras del mapa.
- La exportación de la especificación (e6e14c8e…) es anterior a esas decisiones; el PR explica sus líneas desactualizadas.

**Conceptos**

| Concepto | Qué hay que entender |
| --- | --- |
| Caché de datos y de recursos | `cache_data` guarda una copia serializada y la reconstruye en cada lectura; `cache_resource` comparte el mismo objeto. El segundo es más rápido y no necesita pickle, a cambio de no modificar nunca lo que devuelve |
| Huella como clave | Una ejecución borrada y recreada con el mismo nombre es otra ejecución; la huella de `run.json` lo distingue. La caché supone que nada cambia los ficheros fuera de `simulate_run` |
| Recuento frente a estadística | Un recuento de cero episodios es 0; una media o un porcentaje de cero episodios no existe y se muestra «—». Mostrar n explica la diferencia |
| Dos denominadores | El porcentaje de pacientes que superan el máximo agrupa pacientes; los días fuera de objetivo cuentan días con pacientes. Promediar porcentajes diarios cambiaría la pregunta |
| Máximo de un bloque | Necesita el valor vigente antes del primer evento del bloque: mirar solo los cambios interiores pierde picos aunque la media sea correcta |
| Un caso imposible es un dato dañado | `simulate_run` ya analiza el log antes de publicar, así que una ventana sin episodios completados solo aparece si el log se modificó; se detecta con una comprobación propia, nunca capturando `ValueError` |
| Invariantes guardados y recalculados | Desde el log no se pueden repetir la comparación con el ground truth ni los procesos vivos de SimPy; por eso se muestran los dos recuentos |
| Nivel 1 y Manchester | Puerta-médico incluye la espera y la duración del triaje, así que el nivel 1 («inmediato», 0 minutos) nunca cumple en el modelo actual: es el hallazgo del hito 3, pendiente del hito 4 |

**Medidas** (centro y perfil base, semilla 2026, 2 días de calentamiento; medianas de tres procesos; WSL2, i7-1255U)

| Medida | 14 días | 60 días |
| --- | --- | --- |
| Eventos y tamaño del log | 49.843 y 18,6 MB | 218.501 y 81,4 MB |
| Lectura del log | 0,52 s | 2,88 s |
| Análisis | 0,09 s | 0,82 s |
| Servicio completo | 0,64 s | 3,90 s |
| Primera entrada en la página | 1,01 s (objetivo < 3 s) | 3,93 s |
| Recarga | 0,10 s (objetivo < 0,5 s) | 0,10 s |
| Cambiar semana o curva | 0,10 s | 0,10 s |
| Recalcular invariantes con 0 guardados | 0,07 s | 0,33 s |
| Memoria del proceso (máximo) | 309 MiB | 498 MiB |

Casi todo el coste de la primera entrada es leer el JSONL; el análisis es pequeño.

**Versiones incorrectas temporales**

| Mutación | Resultado |
| --- | --- |
| Caché solo por `run_id` | Una llamada al servicio en lugar de dos al recrear la ejecución |
| Máximo sin el valor vigente al empezar | Máximos \[1, 0\] en lugar de \[7, 99\] |
| Desalojos sobre toda la tabla | 4 episodios y 10 desalojos en lugar de 2 y 3 |
| Fechas con zona en Altair | Falla la comprobación de ausencia de zona y la de `to_dict()` |
| Recalcular invariantes también con 0 | El espía detecta una llamada |
| Capturar `ValueError` alrededor del análisis | `app.exception` con 0 en lugar de 1 |

**Comprobaciones**

| Comprobación | Resultado |
| --- | --- |
| Suite completa del núcleo | 1.301 tests en 232 s |
| App | 135 tests en 57 s |
| Notebooks en modo rápido | 3 en 40 s |
| Ruff, formato y `git diff --check` | Conformes (164 ficheros) |
| Valores a mano | 4 llegadas en 2 días, 3 completados, área de censo 1.500 paciente-minuto, 2 episodios y 3 desalojos, ingreso 1/3; bloque \[15, 30) con media 3 y máximo 7 |

**Lecciones aprendidas**

- Elegir una caché exige mirar qué se guarda: un tipo que pickle no admite, y el coste de copiar en cada recarga, decidieron entre `cache_data` y `cache_resource`.
- Un contrato protegido se respeta comprobando su precondición antes de llamarlo, no capturando su error.
- Un dato correcto puede parecer un fallo: el 100 % del nivel 1 necesita su explicación en la página.
- Una espera de 4 segundos sin aviso parece un cuelgue; la medida de rendimiento lo reveló antes que el navegador.
- La suite de la app ha pasado de 24 a 57 s: cuando el hook de Codex lo note, los AppTest que simulan pueden marcarse `slow`.

**Pendiente para la tarea A.5**

- No existe lectura del ground truth de episodios: «Ver la verdad» necesita una función del núcleo que lea `ground_truth_episodios.csv`.
- `RunResults` no guarda los eventos: la ficha de un episodio necesita leerlos sin releer el log entero.

### Tarea A.5: página Episodios

PR #36 (rama `feat/app-episodios`), implementado con Codex (codex-cli 0.166.0) y fusionado por Pedro con *squash and merge* el 4 de noviembre de 2026 (8b54275). Siete commits: especificación, índice de eventos, tramos, verdad, tabla y filtros, ficha, y el fragmento de la ficha tras la revisión del PR. Tarea no crítica: sin `@codex review`.

**Qué se hizo**

- `runs/events.py`: `build_episode_event_index` recorre el JSONL en binario, saca con `json.loads` el episodio de cada línea y guarda su posición en bytes y su número de línea en arrays de solo lectura (`EpisodeEventIndex`). `read_episode_events` salta a esas líneas y las valida con `from_json`.
- `runs/episodes.py`: `episode_segments` devuelve los tramos de un episodio (dónde está el paciente, con su box), la banda de pruebas (`TestBand`) y los desalojos (`Displacement`). Agrupa los eventos del mismo instante, elimina los tramos de duración cero y se contrasta con `engine/timeline.episode_timeline`.
- `runs/truth.py`: `read_run_episode_truth` lee `ground_truth_episodios.csv` a `EpisodeTruth` con floats exactos y parámetros comprobados contra `run.json`. `compare_episode_truth` clasifica cada dato como coincide, discrepancia, parcial, pendiente o no usada, con tolerancia absoluta de 1e-8 minutos y `math.fsum`.
- `runs/filters.py`: `EpisodeFilters`, `filter_episodes`, `episode_period` (sin terminar, calentamiento, ventana) y `episode_observed_time`.
- Página Episodios: filtros comunes entre ejecuciones, tabla con «Tiempo observado (min)», selector con `?episodio=` por ejecución y una ficha en `st.fragment` con datos básicos, línea temporal de dos carriles (recorrido y pruebas, con rombos de desalojo), eventos del log y «Ver la verdad». Tres cachés de recursos: índice, eventos de cada ficha (128 entradas) y verdad.

**Cambios respecto al plan y a la especificación**

- El índice iba a construirse dentro de `read_run_results`. Con 60 días, la primera entrada de Resultados empeoró un 10,0011 % (4,21 s → 4,63 s), por encima del umbral del 10 % fijado antes de medir. Se paró, no se repitió la medida y el índice pasó a ser independiente; `RunResults` queda como en la A.4.
- Decisiones durante el plan, no recogidas en la exportación: censura por la derecha en los filtros de estancia y puerta-médico; avance parcial en «Ver la verdad»; filtros comunes entre ejecuciones y episodio recordado por ejecución y huella.
- La ejecución de prueba con 30 boxes no producía desalojos; la comprobación de que existan lo detectó, y los tests usan un centro con menos boxes, sin cambiar la semilla.
- Corrección tras la revisión: el selector y la ficha viven en un `st.fragment`, y el callback de la selección actualiza `?episodio=`. Un adaptador de test (`app/tests/fragment_runner.py`) envía reejecuciones parciales reales a través de AppTest.

**Conceptos**

| Concepto | Qué hay que entender |
| --- | --- |
| Índice de posiciones | Como el índice de un libro: anotar dónde empieza cada línea de cada episodio permite leer una ficha sin leer el log entero. Las posiciones son bytes, no caracteres: un acento ocupa dos |
| Validar tarde | El índice solo necesita el episodio de cada línea; la validación completa se hace al abrir la ficha, sobre unas pocas líneas |
| Dónde está frente a qué se espera | El paciente está en un solo sitio cada vez, pero el laboratorio sigue aunque pierda el box: por eso las pruebas son una banda aparte y los tramos suman la estancia |
| Censura por la derecha | De un paciente que sigue dentro se sabe que lleva al menos horizonte − llegada; si esa cota supera un umbral, su estancia también, y si no, no se sabe |
| Comparación parcial | Una etapa en curso al llegar el horizonte no coincide ni discrepa todavía, pero lo observado no puede superar lo sorteado: sigue siendo comprobable |
| Un umbral se aplica | Un criterio fijado antes de medir se respeta aunque el exceso sea mínimo; repetir la medida hasta quedar por debajo sería ajustar la tolerancia al resultado |
| Reejecución parcial | Streamlit vuelve a ejecutar la página entera en cada clic; un `st.fragment` reejecuta solo su parte, y así la ficha no vuelve a pintar la tabla |

**Medidas** (centro y perfil base, semilla 2026, 2 días de calentamiento; medianas de tres procesos)

| Medida | 14 días | 60 días |
| --- | --- | --- |
| Eventos y episodios | 49.843 y 4.439 | 218.501 y 19.499 |
| Construir el índice | 0,21 s | 0,94 s |
| Lectura validada completa, para comparar | 0,54 s | 2,47 s |
| Memoria del índice | 2,2 MiB | 9,7 MiB |
| Leer y reconstruir una ficha en el núcleo | 0,5 ms | 0,4 ms |
| Leer el ground truth | 0,03 s | 0,16 s |
| Primera entrada en Episodios, en frío | 1,9 s | 7,6 s |
| Primera entrada con Resultados en caché | 0,84 s | 3,78 s |
| Recarga con la tabla completa, antes del fragmento | 0,53 s | 2,22 s |
| Elegir un episodio, con el fragmento | 0,04 s | 0,06 s |
| Activar «Ver la verdad», con el fragmento | 0,04 s | 0,08 s |

Con 60 días, el `Styler` se lleva 2,08 s de los 2,39 s de una recarga con la tabla completa; construir el DataFrame cuesta 0,09 s. Con el fragmento, la ficha cumple el objetivo de 0,5 s en todas las muestras. Cambiar un filtro sigue costando unos 2 s con 60 días.

**Versiones incorrectas temporales**

| Mutación | Resultado |
| --- | --- |
| Ignorar los desalojos | La espera de box tras el desalojo aparece como espera de médico en el box anterior |
| Las pruebas mandan | El laboratorio sustituye la espera de box de 30 a 85 |
| Conservar tramos de duración cero | Aparece un triaje de 0 a 0 |
| Contar caracteres en lugar de bytes | Un acento desplaza las posiciones |
| Comparar solo la primera valoración | Cuenta 7 de los 17 minutos |
| Tramos no excluyentes | Seis grupos con cuatro episodios |
| Mostrar la ficha de un episodio excluido | Aparece la ficha |
| Excluir a todos los sin terminar | Falta el episodio con cota de 1.480 minutos sobre un umbral de 1.200 |
| Comparar la etapa en curso como terminada | 14 de 17 minutos como discrepancia falsa |

**Comprobaciones**

| Comprobación | Resultado |
| --- | --- |
| Suite completa del núcleo | 1.371 tests en 292 s |
| App | 164 tests en 106 s (en paralelo con otras suites) |
| Notebooks en modo rápido | 3 en 51 s, fuera del sandbox porque necesitan sockets |
| Ruff, formato y `git diff --check` | Conformes (174 ficheros) |
| Motor, `RunResults` y tests de la A.4 | Sin diferencias frente a 4871075 |

**Lecciones aprendidas**

- Un umbral fijado antes de medir decidió la arquitectura: la medida descartada forma parte del resultado y queda en el PR.
- Lo que cuesta no siempre es lo que parece: el núcleo lee una ficha en menos de un milisegundo, y el tiempo visible lo pone el `Styler` de una tabla grande.
- Un test real no garantiza el caso que se quiere probar: la comprobación de que hubiera desalojos descubrió un centro de prueba sin ellos.
- Las dos censuras (en filtros y en la verdad) son la misma idea: lo no observado da una cota, no un valor.
- El adaptador de fragmentos para AppTest depende de detalles internos de Streamlit 1.66.1: hay que revisarlo si se actualiza Streamlit.

**Pendiente para la tarea A.6 y siguientes**

- Cambiar un filtro en Episodios cuesta unos 2 s con 60 días por el `Styler`. Propuesta de Codex, sin implementar: guardar en caché la tabla presentada por ejecución y filtros.
- `runs/results.py`, `events.py` y `truth.py` usan `RunStore._file`: un método público dejaría la frontera más limpia.
- La suite de la app crece (164 tests): marcar `slow` los AppTest que simulan si el hook de Codex se nota lento.
- El botón «Ver en el replay» se añade en la A.7.

### Tarea A.6: página Comparar

PR #37 (rama `feat/app-comparar`), implementado con Codex (codex-cli 0.166.0), revisado y fusionado por Pedro el 4 de noviembre de 2026 (a7aea24) con *squash and merge*. Seis commits: especificación, emparejamiento comprobado, comparación de indicadores y episodios, selección y resumen, paciente a paciente con enlace a la ficha, y una corrección de formatos e histogramas tras la revisión (1dc0081). Tarea no crítica: sin `@codex review`.

**Qué se hizo**

- `runs/compare.py`: `pairing_blockers` (semilla, huella del perfil, días y calentamiento), `compare_run_summary` (`RunSummaryComparison`: metadatos, `center_diff`, nueve KPIs con B − A y cambio relativo, cinco niveles y sin terminar por lado, sin nada de pacientes) y `compare_runs` (`RunComparison`, sin campos opcionales: emparejamiento comprobado, excluidos, diferencias por episodio, histogramas y los 10 más afectados).
- `DRAW_EFFECTS`: tabla única e inmutable que dice qué sorteos puede cambiar cada clave del centro, con un test que obliga a cubrir todas las claves.
- Comprobación con el ground truth: mismos pacientes en log y verdad, llegadas iguales (exactas entre verdades, con 1e-8 entre verdad y log) y recuento de pacientes con cada sorteo distinto. Un sorteo que cambia fuera de lo permitido, o una llegada distinta, lanza `PairingCheckError`.
- Página Comparar: selectores sobre las marcas A y B, aviso fijo de una réplica, resumen siempre visible, comprobación de sorteos, paciente a paciente en un `st.fragment` y botones para abrir la ficha en A o en B, que quitan los filtros de Episodios con un aviso. Caché de comparaciones de 4 pares ordenados.
- Corrección tras la revisión: formatos compartidos en `frames.py` (diferencias del centro como en Simular, fecha de creación en UTC+1) y histograma con el 0 como borde exacto, coloreado por mejora o empeoramiento.

**Cambios respecto al plan y a la especificación**

- Decisiones durante el plan, no recogidas en la exportación (8815214a…): un parámetro clínico cambiado conserva «sorteos distintos» aunque ningún paciente cambie; los sin terminar por lado se muestran siempre junto a los KPIs; un ground truth ausente, ilegible o contradictorio bloquea solo el emparejamiento validado y la sección paciente a paciente; y dos funciones públicas, para que el tipo del resumen no pueda contener pacientes.
- Ajustes de la revisión del plan: `RunComparison` sin campos opcionales (`compare_runs` lanza `ValueError` con un par no emparejable), `pairing_blockers` en lugar de un booleano, histograma sin los iguales y test de simetría.
- El test de simetría añade un oráculo explícito de B − A, porque A − B también es simétrico.

**Conceptos**

| Concepto | Qué hay que entender |
| --- | --- |
| Números aleatorios comunes | Con la misma semilla, el paciente k llega igual y sortea igual en las dos ejecuciones; cualquier diferencia en él se debe al cambio de configuración |
| Flujos separados con consumo fijo | Nivel, duraciones, pruebas y destino tienen cada uno su flujo, y cada paciente consume siempre lo mismo: cambiar una duración solo cambia esa duración |
| Diseño frente a observación | La categoría sale de lo que cambió en la configuración; los recuentos, de lo que pasó. Un sorteo de umbral puede no cambiar a nadie en una muestra pequeña |
| Comprobar, no suponer | El ground truth verifica lo que la configuración promete; una contradicción significa que la carpeta se modificó fuera de la app |
| Censura en los promedios | La estancia media de cada lado solo cuenta a quienes terminaron; el lado más saturado deja fuera a sus peores pacientes |
| Estados imposibles | Un resumen sin campos de pacientes y una comparación sin campos opcionales impiden por el tipo mostrar como validado lo que no se comprobó |
| Simetría y signo | Intercambiar A y B invierte todo, pero la simetría no fija el signo: hace falta un caso con resultado conocido |

**Medidas** (base frente a un médico más de noche, semilla 2026, 2 días de calentamiento; medianas de tres procesos)

| Medida | 14 días | 60 días |
| --- | --- | --- |
| Primera entrada (dos ejecuciones) | 2,14 s | 9,88 s |
| Recarga | 0,05 s | 0,06 s |
| Reejecución parcial del fragmento | 0,03 s | 0,04 s |
| Leer los dos ground truth | 0,10 s | 0,39 s |
| `compare_run_summary` | 0,001 s | 0,006 s |
| `compare_runs` | 0,02 s | 0,13 s |
| Memoria retenida (resultados, verdades y comparación) | 10,4 MiB | 45,6 MiB |
| Memoria del proceso con los dos lados en caché | 329 MiB | 575 MiB |

La primera entrada con 60 días es casi toda leer dos logs; no se fijó un límite nuevo ni se repitió la medida.

**Versiones incorrectas temporales**

| Mutación | Resultado |
| --- | --- |
| Clasificar solo por configuración | No detecta un nivel alterado en una comparación de plantilla |
| Exigir cambios observados | `PairingCheckError` falso con cero cambios |
| Imputar excluidos como cero | 11 pares en lugar de 7 |
| Tolerancia de 1 minuto | 1 mejora, 1 empeora y 5 iguales en lugar de 2, 2 y 3 |
| Dividir el cambio relativo por B | 0,333… en lugar de 0,5 |
| Mantener los filtros al abrir la ficha | Siete filtros incompatibles se conservan |
| Unir episodios por posición | Cambia la comparación al invertir las filas de B |
| Ocultar los sin terminar en no emparejadas | Falta el recuento de 27 pacientes |
| Ocultar los KPIs ante un error de verdad | No existe la tabla de KPIs |
| Pintar pacientes desde el resumen | `RunSummaryComparison` no tiene `excluded` |
| Diferencia A − B | −10 en lugar de +10; fallan los dos oráculos de signo |
| Histograma con los iguales | 682 en lugar de 116 + 33 |

**Comprobaciones**

| Comprobación | Resultado |
| --- | --- |
| Suite completa del núcleo | 1.401 tests en 311 s |
| App | 199 tests en 150 s (rápida, 130 s) |
| Notebooks en modo rápido | 3 en 50 s, fuera del sandbox por los sockets del kernel |
| Casos reales cortos (3 días) | 1.101 llegadas y 4 pacientes de nivel 1; un médico más de noche no cambia ningún sorteo; la valoración un 20 % más larga solo cambia la valoración; 1e-12 más de probabilidad de pruebas no cambia a nadie y no da error |

**Lecciones aprendidas**

- Compartir semilla no basta: la configuración dice qué debería conservarse y el ground truth comprueba qué pasó.
- El tipo de un resultado puede proteger mejor que la disciplina de quien lo usa: es la ventaja de separar resumen y comparación.
- Un control cruzado (la simetría) no sustituye a un valor conocido: los dos se complementan.
- Una barra enorme de iguales esconde la forma de la distribución; un intervalo que cruza el 0 mezcla mejoras y empeoramientos.
- El formato de las diferencias del centro falló por tercera vez en otra página: los formatos compartidos viven en un solo sitio (`frames.py`).
- La suite rápida ya tarda unos 4 minutos en cada parada del hook de Codex.

**Pendiente para la tarea A.7**

- Marcar `slow` los AppTest que simulan o miden, para aligerar las suites rápidas.
- Paleta fija de colores por nivel, que la especificación pide y aún no existe.
- Botón «Ver en el replay» en la ficha de Episodios.

### Tarea A.7: página Replay

PR #38 (rama `feat/app-replay`), implementado con Codex (codex-cli 0.166.0), revisado y fusionado por Pedro el 4 de noviembre de 2026 (d9e6c6f) con *squash and merge*. Siete commits: especificación (49da0cd), marcas `slow` (b29c2b2), reductor de ubicación compartido (6a64e31), índice del replay (b6e2786), plano y paleta (bc77365), página con reproducción (a984f11) y «Ver en el replay» desde la ficha (d3a93be). Tarea no crítica: sin `@codex review`. El motor y los seis ficheros de una ejecución no cambian.

**Qué se hizo**

- **Antes de nada, tests más rápidos:** `conftest.py` marca `slow` los AppTest que simulan (por fichero y *fixture*) y `test_smoke.py` deja seis humos rápidos. La suite rápida de la app pasó de 116,7 s a 30,2 s.
- **`runs/_location.py`:** un reductor puro, `LocationState.apply(evento)`, que dice dónde está un paciente. Lo comparten la ficha de Episodios y el replay. Va en un commit `refactor` aparte: los 17 tests del núcleo y los 24 AppTest de la A.5 pasan sin tocarlos (SHA-256 comprobados).
- **`runs/replay.py`:** `build_replay_index` hace una pasada binaria validada y guarda una foto del estado antes de cada frontera de 60 minutos (pacientes con nivel, estado, box y pruebas pendientes; plantilla; salidas y desalojos de la última hora; últimos 15 eventos), con la posición en bytes y la línea física. `read_replay_state` parte de la foto y lee y valida como mucho una hora; si el fichero cambió de tamaño, error. `replay_counts` lee las curvas. Todos los tipos son inmutables, y `edsim.runs` reexporta también `shift_at`.
- **`plan.py`:** SVG puro y escapado. Colas con hasta 30 fichas y «+N más» sobre el total de las curvas, puestos de triaje y médicos, rejilla de boxes, salidas de la última hora, «Terminando atención» cuando la plantilla baja y quedan ocupados de más, y el paciente elegido en violeta.
- **`palette.py`:** la paleta de Manchester en un solo sitio, usada por el plano y por la gráfica de esperas de Resultados.
- **Página Replay:** controles fuera del fragmento; plano y barra de estado en un `st.fragment` con `run_every` de 1 s. La posición es el origen más los segundos transcurridos por la velocidad, con un reloj monotónico. Un día extra, «Fin de ejecución», muestra a los que siguen dentro en el horizonte. Debajo, el censo del día, los últimos 15 eventos y los pacientes dentro con botón a su ficha. Posición, velocidad y resaltado se guardan por ejecución; salir de Replay o cambiar de ejecución pausa.
- **Episodios:** «Ver en el replay» abre la llegada exacta, pausada y resaltada, con segundos si la llegada no cae en un minuto entero.

**Cambios respecto al plan y a la especificación**

- El boceto `ReplayIndex.from_events(events).state_at(t)` pasa a dos funciones, `build_replay_index` y `read_replay_state`: el índice solo guarda datos y se comparte en la caché sin riesgo.
- La foto de la hora h contiene los eventos anteriores a h, y leer t aplica los de su hora hasta t inclusive. Así no hay casos ambiguos en las horas exactas, el minuto 0 ni el horizonte.
- Las marcas `slow` viven en `conftest.py`, no en cada test, para no tocar los ficheros de la A.5.
- Un desalojo reciente se marca dos veces: borde discontinuo en el box que perdió y contorno rojo en el paciente desalojado.
- La barra de estado añade triaje y médicos (ocupados / plantilla), y el selector de día el «Fin de ejecución».

**Conceptos**

| Concepto | Qué hay que entender |
| --- | --- |
| Puntos de control | Guardar el estado completo cada cierto tiempo evita reconstruir desde el principio: cualquier minuto cuesta una foto más, como mucho, una hora de eventos. Se paga en memoria |
| Reductor puro | Una función (estado, evento) → estado nuevo, sin efectos. Una sola definición de «dónde está el paciente» para la ficha y el plano |
| Indicadores, no etiquetas | La ubicación visible no basta para continuar: tras un desalojo el laboratorio sigue y las pruebas pendientes son independientes del box |
| Dos fuentes y un control cruzado | Los contadores salen de las curvas y las fichas del índice; un test los compara en todos los minutos, así que el replay también valida el log |
| Reloj anclado | La posición se calcula desde un origen y el tiempo transcurrido, no sumando un paso en cada tic, que acumularía retrasos |
| Fragmento con `run_every` | Solo se vuelve a ejecutar una parte de la página; la gráfica y las tablas se actualizan al pausar |
| Lectura acotada y validada | Leer una hora por fotograma mantiene el tiempo constante con 14 o 60 días; comprobar el tamaño del fichero detecta un log cambiado tras indexarlo |

**Medidas** (medianas de tres procesos, ejecutados en secuencia; 189 fotogramas por caso)

| Medida | 14 días | 60 días |
| --- | --- | --- |
| Leer `RunResults` | 0,91 s | 4,82 s |
| Construir el índice validado | 1,41 s | 6,02 s |
| Primera entrada completa | 2,56 s | 11,16 s |
| Recarga | 0,04 s | 0,04 s |
| Fotograma, mediana | 10,3 ms | 10,8 ms |
| Fotograma, máximo | 28,0 ms | 16,2 ms |
| Memoria del índice | 6,2 MiB | 26,9 MiB |
| Memoria de resultados e índice | 9,7 MiB | 42,2 MiB |
| Memoria del proceso | 303 MiB | 466 MiB |

Ninguna muestra se acercó al límite de 200 ms, fijado antes de medir. La primera entrada con 60 días lee y valida el log dos veces, una para los resultados y otra para el índice. Con cuatro entradas en caché, los índices de 60 días retienen unos 108 MiB.

**Versiones incorrectas temporales** (las 16 las detecta su test)

| Mutación | Resultado |
| --- | --- |
| Tiempo estricto (< t) | El minuto 0 no incluye sus eventos |
| Sin foto de partida | Se pierde el paciente llegado en la hora 0 |
| Hora equivocada | Falta un resultado de pruebas de 85 |
| Contar en el plano | Totales de 40 en lugar de 41 y 42 |
| Cola de box por llegada | El nivel más urgente no queda primero |
| Cola sin límite | 40 fichas en lugar de 30 |
| Borde permanente | La marca de desalojo sigue a los 61 minutos |
| Mismo borde en box y paciente | Falta el borde discontinuo del box antiguo |
| Posiciones en caracteres | Un acento desplaza las posiciones en bytes |
| Alinear y después sumar | +10 desde 10:23:18 da 10:34 en lugar de 10:33 |
| Detalles dentro del fragmento | Tres recálculos de los detalles durante la reproducción |
| Deslizador activo | Se puede mover durante la reproducción |
| Seguir al navegar | La reproducción sigue activa al salir a Episodios |
| Puestos de más | Tres puestos vigentes con plantilla de dos |
| Horizonte como último minuto | 4.319 en lugar de 4.320 |
| Redondear la llegada hacia arriba | Desaparece un episodio que llega y sale en el mismo minuto |

**Comprobaciones**

| Comprobación | Resultado |
| --- | --- |
| Suite completa del núcleo | 1.423 tests en 303 s |
| App completa | 241 tests en 133 s |
| Suites rápidas | Núcleo, 1.405 tests en 105 s (18 excluidos); app, 124 tests en 35 s (117 excluidos) |
| Marcas `slow` | App rápida de 203 tests en 116,7 s a 101 tests en 30,2 s (108 excluidos, con los seis humos nuevos) |
| Notebooks en modo rápido | 3 en 38 s |
| Replay frente a curvas | Coinciden en todos los minutos de la ejecución de prueba (criterio de aceptación) |

**Revisión del PR** (en el chat, sobre el diff completo; sin ejecutar los tests, porque el entorno del chat no tenía acceso a PyPI)

Sin hallazgos que bloqueen la fusión. Cuatro observaciones menores:

- **Gráfica de esperas de Resultados:** el color pasa a ser el nivel, que ya está en el eje X, y las tres series (media, p90 y máximo) solo se distinguen por la forma. El amarillo del nivel 3 se ve poco sobre blanco. Revisar en el navegador.
- **Marcas `slow` implícitas:** dependen del nombre del fichero y de la *fixture* en `conftest.py`, así que un test que simule en un fichero nuevo no se marca solo. La regla se documenta en `app/AGENTS.md`.
- **`ReplayIndex`:** las fotos son un campo con `repr`, así que imprimir el índice volcaría decenas de MiB; bastaría `field(repr=False)`.
- **Importación dentro de `open_episode_replay`:** no hay ciclo que la justifique.

**Lecciones aprendidas**

- Guardar la foto antes de la frontera y aplicar los eventos ≤ t elimina los casos ambiguos de las horas exactas, el minuto 0 y el horizonte.
- Un estado que se reanuda necesita todos sus indicadores, no la etiqueta que se ve: el laboratorio sigue aunque el paciente pierda el box.
- Con dos fuentes independientes (curvas e índice), el replay se convierte en un control cruzado del log, pero no sustituye a los casos escritos a mano.
- Un refactor en su propio commit, con los tests anteriores sin tocar, demuestra que no cambia el comportamiento.
- Acelerar la suite antes de la tarea más grande bajó cada parada del hook de unos 4 minutos a unos 2,5.
- Las marcas fuera del test son cómodas, pero invisibles para quien añade el siguiente.

**Pendiente para la tarea A.8**

- Hecho: prueba en el navegador y fusión del PR #38, sin correcciones.
- Decidir si la gráfica de esperas necesita un `fix(app)` (contraste del amarillo y series solo por forma).
- Documentar en `app/AGENTS.md` la regla de las marcas `slow`.
- Para fases siguientes: la doble lectura del log en la primera entrada del Replay, el `Styler` de Episodios (2 s al filtrar con 60 días) y el adaptador de fragmentos en AppTest, que depende de Streamlit 1.66.1.

### Tarea A.8: cierre de la fase 1

PR #39 (rama `docs/app-cierre`), implementado con Codex (codex-cli 0.166.0), revisado el 4 de noviembre de 2026 y fusionado por Pedro el 5 de noviembre (08db87a) con *squash and merge*. Contenido, por commits: exportaciones, ADR del núcleo, ADR de la app, diario, README, marcas `slow` con el título, las dos correcciones de la revisión y la exportación final de esta pestaña. Etiqueta `app-v0.1.0` sobre 08db87a. Tarea no crítica: sin `@codex review`.

**Qué se hizo**

- **Exportaciones** de esta pestaña y de la de diseño, tal cual (SHA-256 `a60107ed…` de `fase-1.md` y `3bb8b4bb…` de `diseno.md`).
- **ADR del núcleo 0031 a 0033** (app incremental, ejecuciones en carpetas reproducibles, variantes TOML con comentarios) y **de la app APP-0001 a APP-0003** (Streamlit sin API, paquete en el workspace de uv, Codex para la fase 1), con sus índices. Cada alternativa y cada consecuencia enlaza al PR o al anexo que la midió.
- **Diario de la fase** (`app/docs/diario/fase-1.md`): una entrada por tarea, de A.0 a A.7, desde las «Notas para el diario» de los PR #28 a #38. El PR #28 no tenía esa sección y su entrada sale del cuerpo y del anexo. Después, «Codex frente a Claude Code» en cinco dimensiones, con hechos enlazados y las ausencias de datos dichas como tales, y «Reflexiones de Pedro» vacía.
- **README de la app** (`app/README.md`), con una línea en el README raíz.
- **`app/AGENTS.md`:** la regla de las marcas `slow`. Qué ficheros examina `conftest.py`, cuándo hace falta una marca explícita (como el `pytestmark` de `test_replay.py`) y cómo comprobar los dos conjuntos con `--collect-only`.
- **Título «EDsim Lab»** con `st.set_page_config` en `main.py`, sin test: se comprueba en el navegador.

**Cambios respecto al plan y a la especificación**

- La comprobación de la exportación daba 2 en lugar de 1, porque estos detalles citaban literalmente el texto que contaban. Se cuenta el encabezado en negrita, y los detalles ya no citan el texto.

**Conceptos**

| Concepto | Qué hay que entender |
| --- | --- |
| ADR al cierre | Escrita al final, la decisión ya puede registrar lo que costó: alternativas probadas y consecuencias medidas, no solo lo que se planeó |
| Criterio de reparto | Una decisión va a la serie del componente al que obliga: el formato de ejecución es del núcleo aunque lo pidiera la app |
| Hechos frente a impresiones | La comparación entre agentes solo afirma lo que consta con enlace; la falta de un dato se dice y no se rellena |
| Comparar exige medir igual | Sin registros homogéneos de tiempo y consumo no hay conclusión de productividad: había que decidir antes qué anotar en ambos |
| Evidencia de un criterio | Cada criterio de aceptación se apoya en un test con nombre o en una comprobación manual de Pedro, nunca en «se supone» |

**Criterios de aceptación y su evidencia**

| Criterio | Evidencia |
| --- | --- |
| La app arranca y las seis páginas funcionan con 14 días | Humos de `app/tests/test_smoke.py` y prueba de Pedro en el navegador en cada tarea |
| Editar, guardar, prever y simular sin terminal | AppTest de Simular (lentos) y prueba de Pedro en la A.3b |
| Mismo log desde la app y desde la CLI | `test_cli_and_service_share_artifact_format` y la caracterización de la CLI |
| Resultados igual que el resumen de la CLI | `test_selected_header_kpis_waits_and_cli_numbers` y `test_occupancy_and_little_equal_independent_analysis_and_cli` |
| Línea temporal con tramos que suman la estancia | `test_all_real_episodes_cover_their_stay_and_match_engine_timeline` |
| Comparar consigo misma da cero | `test_self_comparison_has_zero_differences_and_all_equal` |
| Replay igual que las curvas en todos los minutos | `test_every_minute_matches_curves_full_fold_and_cards` |
| Rendimiento | Medidas de los anexos A.2a (límite de 60 días justificado) y A.7 (fotogramas por debajo de 200 ms) |
| Frontera del núcleo | `test_core_imports_without_ui_dependencies`, `test_core_has_no_ui_imports_including_inside_functions` y el job `tests` sin la app |
| CI en verde | Jobs `tests` y `tests-app` en cada PR, incluido el #39 |

**Comprobaciones de la revisión**

| Comprobación | Resultado |
| --- | --- |
| Enlaces relativos y anclas en los 12 ficheros nuevos o cambiados | Ninguno roto |
| Encabezado de los detalles de la A.8 en la exportación | 1 |
| Exportaciones frente a lo que trajo Pedro | Entran tal cual; solo cambian esos dos ficheros fuera de los nuevos |
| Cifras de las ADR frente al anexo | Coinciden (por ejemplo 81,4 MB, 12,4 s y 3,82 s con 60 días) |

**Revisión del PR**

Sin errores de fondo. Dos correcciones y dos comprobaciones, todas resueltas antes de fusionar:

- **Diario, entrada de la A.7:** la frase que dice que el anexo aún describe la espera deja de ser cierta con la exportación final; se quita.
- **README de la app:** enlaza a `AGENTS.md#pruebas-y-convenciones`, pero la regla vive en su propio apartado, `#selección-de-tests-slow`.
- **Título:** Pedro comprueba en el navegador que la pestaña dice «EDsim Lab».
- **Permisos de las exportaciones (previo a la A.8):** `diseno.md`, `fase-1.md` y `hito-0.md` a `hito-3.md` están en el repositorio con modo 755 porque se copian desde Windows. Se corrige con `chmod 644` en el commit final, y conviene añadirlo a la rutina de copia.

**Lecciones aprendidas**

- Una comprobación que se cita a sí misma cambia su propio resultado: la especificación debe describir la comprobación, no copiar el texto que cuenta.
- Las ADR del final salen mejores si cada PR deja sus notas: la única entrada sin notas propias es la de la A.0.
- Para comparar dos herramientas hay que decidir al principio qué se anota en las dos; sin eso, el diario solo puede decir lo que falta.
- Copiar ficheros desde Windows arrastra permisos que Git registra.

**Pendiente tras la fase 1**

- «Reflexiones de Pedro» en el diario (la etiqueta `app-v0.1.0` ya está creada).
- Para la fase siguiente: la doble lectura del log en la primera entrada del Replay, el `Styler` de Episodios, el adaptador de fragmentos de AppTest y la revisión visual de la gráfica de esperas.
- Hito 4 con Claude Code, con su tarea de app y los hallazgos del hito 3 sobre el triaje y el centro provisional.
