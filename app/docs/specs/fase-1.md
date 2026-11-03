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
- También aparecen las ejecuciones de la CLI guardadas con `--salida resultados/ejecuciones/<run_id>`.

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
  Centro y carga: center_to_toml, offered_work
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
      variants.py             # CenterConfig a TOML con tomlkit; diferencias entre dos centros
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
      pages/                  # ejecuciones, simular, resultados, episodios, comparar, replay
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

- La ejecución se escribe en una carpeta temporal y se renombra al terminar: una ejecución a medias nunca aparece en el catálogo.
- El `run_id` se valida con la misma regla que `--run-id` de la CLI, así que no puede salirse de `resultados/ejecuciones/`.
- Las variantes del centro se guardan en `resultados/variantes/<nombre>.toml`; una variante que merezca conservarse se copia a `config/` y se versiona a mano.

### Funciones nuevas del paquete

| Función | Qué hace | Comprobación clave |
| --- | --- | --- |
| `simulate_run(...) -> RunInfo` | Simula con `simulate_ed`, escribe la carpeta, comprueba las invariantes y guarda `run.json` | La CLI y la app dan el mismo log para los mismos parámetros |
| `RunStore(root)` | `list`, `open`, `exists` y `delete` de ejecuciones | Ida y vuelta de `run.json`; ignora carpetas temporales |
| `center_to_toml(center, base)` y `center_diff(a, b)` | Escribe un centro como TOML y lista las claves que cambian | `load_center(center_to_toml(c)) == c` con centros aleatorios válidos |
| `offered_work(center, profile, days)` | Minutos de médico y de box ofrecidos por minuto y utilización prevista por turno, con `offered_load` del hito 3 | Con plantilla constante, la media coincide con λ × E\[tiempo\] calculado a mano |
| `window_kpis(analysis)` y `manchester_compliance(table, start, end)` | KPIs de la ventana y porcentaje por encima del máximo de cada nivel (el nivel 1, inmediato, solo muestra el tiempo) | Valores calculados a mano en un log pequeño |
| `episode_segments(events)` | Tramos de estado de cada episodio, con su box | Los tramos de cada episodio son contiguos y suman su estancia |
| `ReplayIndex.from_events(events)` y `.state_at(t)` | Estado del servicio en el minuto t: colas, boxes, plantilla, salidas recientes y últimos eventos | Los contadores coinciden con `step_curves` en todos los minutos de una ejecución |
| `compare_runs(a, b)` | Tipo de emparejamiento, diferencias del centro, KPIs y diferencias por episodio | Una ejecución frente a sí misma da cero en todo |

`ReplayIndex` guarda una foto completa del estado cada 60 minutos simulados y aplica los eventos desde la foto anterior, así que cada consulta recorre como mucho una hora de eventos.

### Estado, caché y rendimiento

- **Estado de sesión:** la ejecución elegida (sincronizada con `?run=`), las marcas A y B y el borrador del centro en edición.
- **Caché:** `st.cache_data` para leer y analizar una ejecución, con la clave `run_id` y la fecha de modificación del log; `st.cache_resource` para el `ReplayIndex`. Como mucho tres ejecuciones en caché.
- **Simulación:** síncrona dentro de la sesión, con un panel de estado. La app limita el horizonte a 60 días; la tarea A.2 mide tiempo y memoria y ajusta el límite (el hito 3 dejó pendiente medir el peso del log).
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
- **Revisión:** además de la revisión en el chat, `@codex review` en el PR como segunda opinión, guiada por las *Review guidelines* de `AGENTS.md`.
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

Las tareas A.1 a A.8 empiezan cuando exista la etiqueta `v0.3-hito3`; la A.0 puede hacerse antes, porque solo prepara la herramienta. Siguen el ciclo de los hitos: explicación breve del concepto en el chat, plan con `/plan` en una sesión nueva de Codex, implementación completa tras aprobar el plan, PR revisado por Pedro (y por `@codex review`) y *squash and merge*. Al cerrar cada tarea se actualiza el anexo de esta pestaña.

| # | Tarea | Rama | Resultado |
| --- | --- | --- | --- |
| A.0 | Preparar Codex: instalación en WSL e inicio de sesión; `AGENTS.md` en la raíz a partir de `CLAUDE.md`, y `CLAUDE.md` con `@AGENTS.md`; `.codex/config.toml`, reglas y hooks; Codex conectado al repositorio para `@codex review`; prueba de extremo a extremo con el propio PR de la tarea | `chore/app-codex` | Codex trabaja en el repositorio con los permisos justos y Claude Code sigue funcionando igual |
| A.1 | Especificación en `app/docs/specs/fase-1.md`; workspace de uv con el paquete `edsim-app` (pyproject, script `edsim-app`, `app/AGENTS.md` y carpetas de documentación); seis páginas vacías con `st.navigation`; test de la frontera; `AppTest` de humo y job `tests-app` en el CI y en el ruleset | `feat/app-esqueleto` | La app arranca con `uv run --package edsim-app edsim-app` y el CI la prueba |
| A.2 | `RunStore`, `simulate_run` y `run.json`; `edsim motor simular` pasa a usarlos; página Ejecuciones; medida de tiempo y memoria | `feat/app-ejecuciones` | La CLI y la app escriben la misma ejecución y el catálogo la muestra |
| A.3 | `center_to_toml`, `center_diff` y `offered_work`; página Simular | `feat/app-simular` | Una variante editada, guardada y simulada desde la app |
| A.4 | `window_kpis` y `manchester_compliance`; página Resultados | `feat/app-resultados` | KPIs, esperas, ocupación, curvas, Little e invariantes de una ejecución |
| A.5 | `episode_segments`; página Episodios con ficha y «ver la verdad» | `feat/app-episodios` | La línea temporal de cualquier episodio, desalojos incluidos |
| A.6 | `compare_runs`; página Comparar | `feat/app-comparar` | Base frente a un médico más de noche, paciente a paciente |
| A.7 | `ReplayIndex`, `plan.py` y reproducción; página Replay | `feat/app-replay` | El servicio minuto a minuto, coherente con las curvas |
| A.8 | Cierre: ADR 0031 a 0033 y APP-0001 a APP-0003, entrada del diario de la app con la comparación entre Codex y Claude Code, anexo, exportación de esta pestaña, README de la app y etiqueta `app-v0.1.0` | `docs/app-cierre` | Fase 1 cerrada |

Orden: A.1 y A.2 primero, porque todo lo demás lee ejecuciones del catálogo. A.3, A.4 y A.5 pueden ir en cualquier orden. A.6 usa los KPIs de A.4, y A.7 va al final por ser la más grande.

## Criterios de aceptación

- [ ] `uv run --package edsim-app edsim-app` abre la app en `http://localhost:8501` y las seis páginas funcionan con una ejecución de 14 días.
- [ ] Desde la app se edita el centro, se guarda una variante, se ve la carga prevista y se simula sin tocar la terminal.
- [ ] Una ejecución de la app y otra de `edsim motor simular` con los mismos parámetros tienen el mismo log.
- [ ] Resultados muestra los mismos KPIs, ocupaciones y errores de Little que el resumen de la CLI.
- [ ] Cualquier episodio tiene su línea temporal, con tramos contiguos que suman su estancia.
- [ ] Comparar detecta el emparejamiento y, con una ejecución consigo misma, da cero en todo.
- [ ] Los contadores del replay coinciden con `step_curves` en todos los minutos de una ejecución de prueba.
- [ ] Se cumplen los objetivos de rendimiento, o la tarea A.2 deja medido y justificado otro límite.
- [ ] El núcleo no importa Streamlit, pandas ni `edsim_app`, y un test lo comprueba.
- [ ] CI en verde con los jobs `tests` y `tests-app`.

## Preguntas abiertas

- ¿Nombre de la app en la interfaz: «EDsim» a secas o algo como «EDsim Lab»?
- ¿Límite de 60 días por ejecución, o lo fija la medida de la tarea A.2?
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
