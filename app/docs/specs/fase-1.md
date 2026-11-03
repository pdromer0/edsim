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

### Episodios

- **Filtros:** nivel, destino, desalojado o no, día, tramo (calentamiento, ventana o sin terminar), puerta-médico y estancia por encima de un valor.
- **Tabla** con las columnas de `EpisodeRecord`, en minutos y en hora del reloj, paginada; al elegir una fila se abre su ficha.
- **Ficha del episodio:** llegada (fecha y hora), nivel, destino y estancia; una línea temporal con un tramo por estado (espera de triaje, triaje, espera de box, espera de médico, valoración, espera de pruebas, reevaluación), el box ocupado y los desalojos marcados; y la lista de sus eventos tal como están en el log.
- **«Ver la verdad»:** un interruptor que añade el `EpisodeTruth` del episodio: nivel y duraciones sorteadas al llegar, frente a lo observado en el log. Una valoración interrumpida por un desalojo se ve aquí como la suma de sus tramos.
- **«Ver en el replay»** abre el Replay en el minuto de llegada del paciente.

### Comparar

- Se eligen A y B (o llegan marcadas desde Ejecuciones).
- **Emparejamiento:** si comparten semilla, huella del perfil, días y calentamiento, la comparación es emparejada: las llegadas son las mismas y, si solo cambian plantilla o boxes, también lo sorteado de cada paciente (decisión candidata 24). Si cambian parámetros clínicos, las llegadas coinciden pero los sorteos no. La app muestra el caso y la lista de claves del centro que difieren.
- **KPIs de A y B,** con la diferencia B − A y el cambio relativo; las esperas por nivel, lado a lado.
- **Paciente a paciente** (solo emparejada): histograma de la diferencia de estancia y de puerta-médico, porcentaje de pacientes que mejoran, empeoran o quedan igual, y los 10 más afectados, con enlace a su ficha.
- Un aviso fijo: es una sola réplica de cada lado; las comparaciones con intervalos de confianza llegan en el hito 9.

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

### En todas las páginas

- Un desplegable «¿Qué estoy viendo?» con dos o tres frases y el concepto que hay detrás (ventana y calentamiento, ley de Little, números aleatorios comunes, prioridad y desalojo).
- Formatos: minutos con un decimal, horas como hh:mm, fechas en la zona del log (UTC+1), números con coma decimal.
- Colores fijos por nivel de triaje en todas las gráficas y en el plano.

## Arquitectura

```text
edsim-app (paquete aparte, Streamlit)        CLI
  Ejecuciones · Simular · Resultados          edsim motor simular
  Episodios · Comparar · Replay
  frames, charts, plan (SVG) y help
        │ usa                                   │ usa
        ▼                                       ▼
edsim.runs (núcleo, servicios nuevos sin Streamlit)
  Ejecuciones: RunStore, simulate_run
  Centro y carga: write_variant, offered_work
  Métricas: window_kpis, episode_segments
  Replay y comparar: ReplayIndex, compare_runs
        │ usa
        ▼
Motor y análisis del hito 3, sin cambios
  simulate_ed · analyze_run · step_curves · check_invariants
        │ escribe el log; los servicios lo leen
        ▼
resultados/ejecuciones/<run_id>/  (los ficheros son la verdad)
  eventos.jsonl · ground_truth_episodios.csv · ground_truth_dias.csv
  centro.toml y llegadas.toml (copias exactas) · run.json (metadatos)
```

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

## Criterios de aceptación

- [ ] `uv run --package edsim-app edsim-app` abre la app en `http://localhost:8501` y las seis páginas funcionan con una ejecución de 14 días.
- [ ] Desde la app se edita el centro, se guarda una variante, se ve la carga prevista y se simula sin tocar la terminal.
- [ ] Una ejecución de la app y otra de `edsim motor simular` con los mismos parámetros tienen el mismo log.
- [ ] Resultados muestra los mismos KPIs, ocupaciones y errores de Little que el resumen de la CLI.
- [ ] Cualquier episodio tiene su línea temporal, con tramos contiguos que suman su estancia.
- [ ] Comparar detecta el emparejamiento y, con una ejecución consigo misma, da cero en todo.
- [ ] Los contadores del replay coinciden con `step_curves` en todos los minutos de una ejecución de prueba.
- [ ] Se cumplen los objetivos de rendimiento, o la tarea A.2a deja medido y justificado otro límite.
- [ ] El núcleo no importa Streamlit, pandas ni `edsim_app`, y un test lo comprueba.
- [ ] CI en verde con los jobs `tests` y `tests-app`.

## Preguntas abiertas

- ¿Nombre de la app en la interfaz: «EDsim» a secas o algo como «EDsim Lab»?
- Resuelta en la A.2a: límite de 60 días por ejecución y 14 por defecto, con las medidas del anexo.
- ¿La página Resultados reutiliza las gráficas de matplotlib de la CLI o se rehacen todas en Altair? La propuesta es Altair, por la interactividad.

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
