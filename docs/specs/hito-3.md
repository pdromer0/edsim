# Hito 3 — Motor y eventos

## Objetivo y alcance

Al terminar el hito 3, EDsim tiene un motor de eventos discretos en SimPy en el que cada paciente es un proceso que recorre la máquina de estados del diseño. Los pacientes llegan con el generador del hito 2, pasan por triaje, esperan box y médico con prioridad por nivel, y el nivel 1 puede desalojar a otro paciente de un box. La única salida del motor es un log de eventos en JSONL, con el sobre común del diseño; el ground truth va aparte, y estado y métricas se derivan del log. El motor se valida sin fórmula cerrada: invariantes, leyes operacionales, un caso de referencia M/G/1 y condiciones extremas.

**Dentro del alcance**

- Configuración del centro en `config/centro.toml`: recursos por turno, triaje, duraciones, pruebas y destino provisionales.
- Proceso paciente en SimPy, con todos sus sorteos al llegar y un flujo aleatorio por fuente.
- Tres pools: enfermería de triaje (FIFO), boxes (prioridad y desalojo del nivel 1 con reanudación) y médicos (prioridad sin desalojo).
- Plantilla por turnos (8–15, 15–22 y 22–8) con reservas de capacidad.
- Calentamiento y horizonte en días completos.
- Log de eventos JSONL con sobre común, `payload` y los tres tiempos; ground truth en ficheros aparte.
- Estado y métricas derivados del log: censo, ocupación, esperas, estancias y ley de Little.
- Validación: invariantes en cada ejecución, leyes operacionales, M/G/1 frente a Pollaczek–Khinchine, condiciones extremas y huella de regresión.
- CLI `edsim motor simular` y `edsim motor validar`, tests (rápidos y slow) y el notebook `03_motor_exploracion.ipynb`.

**Fuera del alcance**

- Motivos de consulta, edad, sexo, medio de llegada, gravedad latente y triaje con error: hito 4. El triaje del hito 3 es provisional y se sustituye sin tocar el motor.
- Abandono, boarding, observación y destinos distintos de alta e ingreso: hito 5.
- Pacer, modo directo, Kafka y emisión en vivo: hito 6. Capa de observación con defectos (`recorded_time` distinto de `event_time`): hito 7.
- Shocks, plano de control, `system_snapshot` y llegadas en grupo: hitos posteriores.
- Calibración de plantilla y duraciones: los valores son provisionales y se ajustan en el hito 4.

Las tareas con código empiezan cuando el hito 2 tenga su etiqueta `v0.2-hito2`. Como en el hito 2, Claude Code ejecuta git (rama, commits, push con permiso y PR) y Pedro siempre fusiona.

## Sesión conceptual

Los conceptos se explicaron en la conversación de arranque del hito, con diagramas y la curva de carga ofrecida de una semana. Esta tabla es el resumen de referencia.

| Concepto | Qué hay que entender |
| --- | --- |
| Paciente como proceso | Una función generadora de SimPy; cada `yield` es una espera (un recurso o un `timeout`) y cada estado es lo que pasa mientras el proceso está parado en un `yield` |
| Eventos en las transiciones | El código entre dos `yield` se ejecuta en un instante; ahí se emite el evento, con `event_time = env.now` |
| Sorteos al llegar | Todo lo aleatorio del paciente se sortea al llegar, en orden fijo, aunque no se use; el paciente k es el mismo con cualquier plantilla (base de los números aleatorios comunes) |
| Recursos retenidos en tramos distintos | El box se retiene toda la estancia; el médico, solo en las valoraciones. Por eso el box suele ser el cuello de botella |
| Cola de triaje FIFO | Antes del triaje no se conoce la prioridad |
| Prioridad como tupla | `(nivel, llegada)` ordena por nivel y, dentro del nivel, por llegada, pida el recurso cuando lo pida (reevaluación, vuelta tras un desalojo) |
| Desalojo | `PreemptiveResource`: el nivel 1 echa al usuario de menor prioridad; el desalojado recibe `simpy.Interrupt`, vuelve a la cola y reanuda el tiempo que le faltaba |
| Carga ofrecida | a = λ · E\[S\] servidores ocupados; con λ(t), m(t) = ∫ λ(s) · P(S > t − s) ds. Si se acerca a la capacidad, las esperas se disparan |
| Turnos con reservas | La capacidad de un `Resource` no cambia: se reservan plazas con peticiones de prioridad máxima que esperan a que el profesional termine |
| Régimen periódico | Con λ(t) no hay estado estacionario; el calentamiento quita el arranque vacío y se mide en días completos |
| Log de eventos | Sobre común + `payload`, una línea JSON por evento; es la única salida del motor |
| Tres tiempos | `event_time` (ocurrió), `recorded_time` (se anotó), `ingest_time` (llegó al broker); en el hito 3 los dos primeros coinciden y el tercero es nulo |
| Event sourcing | El estado en t se obtiene plegando los eventos hasta t: censo, ocupación, esperas, "qué se sabía" en cada instante |
| Ground truth separado | Lo que el hospital no ve va en ficheros aparte y solo entra en la validación |
| Validar sin fórmula cerrada | Invariantes, leyes operacionales (Little, U = X·S), un caso con teoría (M/G/1), condiciones extremas y regresión |
| Pollaczek–Khinchine | Wq = λ·E\[S²\] / (2(1 − ρ)): la variabilidad del servicio, no solo su media, produce esperas |

## Cómo encajan las piezas

Las llegadas del hito 2 y los sorteos de cada paciente alimentan el motor, que solo escribe el log de eventos y, aparte, el ground truth; estado, métricas y validación se derivan de esas dos salidas.

&#91;embedded content: flujo del hito 3 · de la configuración y la semilla a la validación\]

El motor no calcula métricas: todo lo que hay debajo del log se puede recalcular a partir del fichero, con la misma semilla o con otra ejecución.

## El paciente como proceso

Cada llegada del hito 2 crea un episodio y un proceso SimPy que recorre la máquina de estados del diseño; las esperas son estados propios y cada transición emite un evento.

| Estado | Cómo espera el proceso | Eventos al entrar o salir |
| --- | --- | --- |
| Llegada y registro | Sin espera (instantáneo en el hito 3) | `patient_arrived`, `patient_registered` |
| Espera de triaje | `yield` a la cola FIFO de enfermería | `triage_started` |
| Triaje | `yield env.timeout(duración de triaje)` | `triage_completed` (nivel) |
| Espera de box | `yield` a la petición de box con prioridad | `box_assigned` (box) |
| Espera de médico, en el box | `yield` a la petición de médico con prioridad | `assessment_started` (tipo inicial) |
| Valoración | `yield env.timeout(duración pendiente)`; se libera el médico al terminar | `assessment_ended`; si hay pruebas, `test_ordered` |
| Pruebas | `yield env.timeout(respuesta)`; el box sigue ocupado y el médico libre | `test_resulted` |
| Reevaluación | Espera de médico y `timeout` | `assessment_started` y `assessment_ended` (tipo reevaluación) |
| Decisión y salida | Sin espera; se libera el box | `disposition_decided` (destino), `patient_departed` |

Si el paciente es desalojado mientras ocupa un box, emite `patient_displaced` y vuelve a "espera de box" (ver la sección de recursos).

**Sorteos al llegar.** Al crear el proceso, el paciente sortea todo lo aleatorio que necesitará, en este orden fijo y desde el flujo de cada fuente: nivel de triaje; duraciones de triaje, valoración y reevaluación; si tendrá pruebas y su tiempo de respuesta; y destino. Se sortea todo aunque no se use (el tiempo de respuesta de quien no tiene pruebas, por ejemplo). Así el paciente k recibe siempre los mismos valores, cambie lo que cambie la plantilla o la cola: solo cambian sus esperas. Es la regla del hito 1, "el tiempo de servicio se asigna al llegar", aplicada a todo el paciente.

**Identificadores.** `episode_id` = `EP-` y el `arrival_id` con seis cifras; `patient_id` = `PT-` y el mismo número (sin reconsultas en el hito 3, un paciente es un episodio). Los formatos se fijan en el código y se testean.

## Recursos, prioridad y desalojo

Tres pools anónimos (decisión 3), retenidos durante tramos distintos de la estancia.

| Pool | Clave TOML | Tipo en SimPy | Orden de la cola | Desalojo | Se retiene |
| --- | --- | --- | --- | --- | --- |
| Enfermería de triaje | `enfermeria_triaje` | `PriorityResource` (por las reservas de turno) | FIFO: prioridad igual para todos los pacientes | No | Durante el triaje |
| Boxes | `boxes` | `PreemptiveResource` | `(nivel, llegada)` | Solo el nivel 1 | Desde `box_assigned` hasta la salida o el desalojo |
| Médicos | `medicos` | `PriorityResource` | `(nivel, llegada)` | No | Durante cada valoración |

**Reglas de prioridad**

- La prioridad es la tupla `(nivel, instante de llegada)`: menor es más prioritario. SimPy desempata por el instante de la petición, y con la tupla el orden es el del diseño aunque se pida tarde (reevaluación o vuelta tras un desalojo).
- Las reservas de turno usan una prioridad menor que cualquier paciente, para ir siempre las primeras de la cola.
- Claude Code comprueba en el código de SimPy 4.1.2 instalado cómo se ordenan las peticiones, que las tuplas se comparan sin error y a quién se desaloja, y deja un test que fija ese comportamiento (como `test_spawn_de_numpy_muta_el_objeto` en el hito 2).

**Desalojo de un box**

- El nivel 1 pide box con `preempt=True`; el resto, con `preempt=False`. Si no hay box libre, SimPy expulsa al usuario con la clave mayor (menor prioridad), siempre que sea menos prioritario que el nivel 1 que llega. Un nivel 1 nunca desaloja a otro nivel 1 que llegó antes.
- El desalojado recibe `simpy.Interrupt` en el `yield` en el que esté. Emite `patient_displaced` (box y `episode_id` de quien lo desaloja), vuelve a pedir box con su misma clave y sin desalojo y, al recuperarlo, emite otro `box_assigned`.
- Si estaba en valoración o reevaluación, se corta: se libera el médico, se emite `assessment_ended` con `interrumpida: true` y, al recuperar box y médico, se reanuda con el tiempo pendiente (*preempt-resume*). Si estaba esperando pruebas, el reloj de las pruebas sigue corriendo. Si estaba esperando médico dentro del box, cancela esa petición.
- El desalojo no se aplica a médicos ni enfermería: el nivel 1 se pone el primero de la cola, pero no interrumpe una atención en curso.

**Número de box.** Los pools son anónimos, pero el `payload` lleva el box para poder reconstruir la ocupación. El motor mantiene la lista de boxes libres y asigna el de número más bajo, de forma determinista.

## Triaje y actividades provisionales

El hito 3 usa un modelo clínico mínimo, en configuración y detrás de funciones con una interfaz estable; el hito 4 sustituirá lo de dentro (gravedad latente, motivos, duraciones por nivel y motivo) sin tocar el motor.

| Componente | Modelo provisional | Valor por defecto |
| --- | --- | --- |
| Nivel de triaje | Categórica con el reparto por nivel, normalizado en el código | 0,3 / 12,1 / 33,6 / 52,6 / 1,4 % (Emergencias 2013; nivel 1 supuesto) |
| Duraciones | Lognormal por mediana y p90, iguales para todos los niveles | Triaje 5 y 10 min; valoración 20 y 45; reevaluación 10 y 20 |
| Pruebas | Bernoulli por nivel, una sola ronda; respuesta lognormal | 95 / 85 / 70 / 40 / 20 %; respuesta 60 y 150 min |
| Destino | Ingreso con probabilidad por nivel; si no, alta | 80 / 45 / 15 / 4 / 1 % de ingreso |

La lognormal se parametriza como en el diseño: μ = ln(mediana) y σ = (ln p90 − ln mediana) / 1,2816. Con estos valores, un 55 % de los pacientes tiene pruebas, el box se ocupa 74 min de media y el médico 31 min. El ingreso global sale en torno al 13 %, por encima del 10,1 % del SNS: se calibra en el hito 5.

Fichero `config/centro.toml`:

```toml
# Centro base para el motor. Ver docs/specs/hito-3.md.
# Valores provisionales hasta la calibración del hito 4.

[turnos]
# Hora de inicio de los turnos de mañana, tarde y noche
inicio = [8, 15, 22]

[recursos]
# Plantilla por turno: mañana, tarde, noche
enfermeria_triaje = [3, 3, 2]
medicos = [12, 12, 7]
# Capacidad física, igual en todos los turnos
boxes = 30

[triaje]
# % de pacientes por nivel, del 1 al 5 (Emergencias 2013; nivel 1 supuesto)
reparto_niveles = [0.3, 12.1, 33.6, 52.6, 1.4]

[duraciones]
# Minutos: [mediana, p90] de una lognormal
triaje = [5, 10]
valoracion = [20, 45]
reevaluacion = [10, 20]
respuesta_pruebas = [60, 150]

[pruebas]
# Probabilidad de pedir pruebas por nivel, del 1 al 5
probabilidad = [0.95, 0.85, 0.70, 0.40, 0.20]

[destino]
# Probabilidad de ingreso por nivel, del 1 al 5; el resto, alta
probabilidad_ingreso = [0.80, 0.45, 0.15, 0.04, 0.01]
```

**Reglas de la configuración**

- `CenterConfig` inmutable, validado y normalizado en `__post_init__`, y `load_center(path)` con `tomllib`, como `ArrivalProfile`. Rechaza claves que faltan o sobran, longitudes incorrectas (3 turnos, 5 niveles), horas de turno no crecientes o fuera de 0–23, capacidades no enteras o menores que 1, medianas no positivas, p90 ≤ mediana y probabilidades fuera de \[0, 1\]. Los errores nombran la clave TOML y la posición.
- El perfil de llegadas sigue en `config/llegadas.toml`; horizonte, calentamiento y semilla son argumentos de la ejecución, no del centro.
- Los tests usan su propia configuración de ejemplo; un test aparte comprueba que la real se carga.

**Dimensionado provisional.** La plantilla sale de la carga ofrecida m(t) = ∫ λ(s) · P(S > t − s) ds, calculada con el perfil del hito 2 y las duraciones de la tabla, sin colas. Es un límite inferior: con colas la ocupación de los boxes sube.

| Lunes 5 de enero (sin colas) | Mañana (8–15) | Tarde (15–22) | Noche (22–8) | Capacidad |
| --- | --- | --- | --- | --- |
| Boxes ocupados, máximo | 30,2 | 27,6 | 21,7 | 30 |
| Médicos ocupados, media (máximo) | 10,5 (12,9) | 10,7 (11,8) | 4,3 (8,7) | 12 / 12 / 7 |
| Enfermeras de triaje, media (máximo) | 1,9 (2,3) | 1,8 (2,0) | 0,7 | 3 / 3 / 2 |

El lunes de enero es la semana más cargada del año: a mediodía la demanda roza la capacidad y habrá colas; el resto de días hay margen. La noche empieza justa (unos 8 médicos a las 22 h) y termina sobrada (2 a las 5 h): los turnos fijos no siguen a la demanda.

## Turnos, calentamiento y horizonte

**Turnos**

- Tres turnos al día que empiezan a las 8, 15 y 22 h (configurables). Cada pool de personal tiene una plantilla por turno; los boxes no cambian.
- Cada pool se crea con su capacidad máxima en el día. Un proceso de turnos, al empezar cada turno, ajusta las **reservas**: peticiones con prioridad mejor que cualquier paciente y sin desalojo, que ocupan las plazas que sobran. Una reserva espera a que un profesional termine su atención y entonces ocupa su plaza; al subir la plantilla, se liberan reservas.
- Capacidad efectiva en t = capacidad máxima − reservas activas. Cada cambio de plantilla emite `staffing_changed` (recurso, plantilla anterior y nueva).
- El día 0 empieza a las 0:00 en el turno de noche que empezó a las 22 h del día anterior.

**Calentamiento**

- Con λ(t) variable no hay estado estacionario: se alcanza un régimen periódico. El calentamiento quita el sesgo de empezar vacío el día 0 a las 0:00.
- Se mide en días completos, para no mezclar horas del ciclo diario: 2 días por defecto (el rango del diseño es 24–48 h).
- En el modo batch de este hito el log es completo, incluido el calentamiento, y las métricas usan la ventana \[calentamiento, horizonte\], como en el hito 1. Así las invariantes valen en el fichero entero, sin pacientes que aparecen "ya dentro". El modo directo del hito 6 empezará a publicar al acabar el calentamiento, con un evento de censo inicial.

**Horizonte**

- En días completos e incluye el calentamiento: 14 días por defecto (2 de calentamiento y 12 observados). Las llegadas se generan para esos días y la simulación se detiene en el minuto horizonte × 1.440.
- Los pacientes que siguen dentro al final no tienen `patient_departed`: no se inventa nada para ellos y cuentan como "dentro". Los eventos programados en el instante del horizonte o después no ocurren, como en `simulate_mm1`.

## Log de eventos, ground truth y derivados

El motor no calcula métricas: escribe hechos. Cada evento es una línea JSON (JSONL) con el sobre común del diseño y un `payload` con lo específico de su tipo. JSONL se escribe y se lee en *streaming*, línea a línea, y cada línea será un mensaje de Kafka en el hito 6.

**Sobre común**

```json
{"event_id": "r2026-000000412", "event_type": "triage_completed", "schema_version": 1, "run_id": "r2026", "episode_id": "EP-000137", "patient_id": "PT-000137", "source_system": "triaje", "sim_time": 739.02, "event_time": "2026-01-05T12:19:01.200+01:00", "recorded_time": "2026-01-05T12:19:01.200+01:00", "ingest_time": null, "payload": {"nivel": 3}}
```

| Campo | En el hito 3 |
| --- | --- |
| `event_id` | Determinista: `run_id`, un guion y el número de orden del evento con nueve cifras. Un `uuid4` rompería la reproducibilidad |
| `event_type`, `schema_version` | Tipo del catálogo; versión 1 |
| `run_id` | Identificador de la ejecución; por defecto `r` y la semilla |
| `episode_id`, `patient_id` | `EP-000137`, `PT-000137`; nulos en los eventos de recursos |
| `source_system` | `admision`, `triaje`, `his`, `lab` o `rrhh` |
| `sim_time` | Minutos de simulación (nuevo respecto al diseño). Las invariantes y métricas se calculan con él, sin redondeos |
| `event_time` | ISO 8601 con milisegundos y desfase fijo `+01:00`, derivado de `fecha_inicio` + `sim_time` y truncado (reloj sin cambio de hora, decisión 20) |
| `recorded_time` | Igual que `event_time`: no hay capa de observación hasta el hito 7 |
| `ingest_time` | `null`: no hay broker hasta el hito 6 |

**Catálogo del hito 3**

| Evento | Cuándo | `source_system` | `payload` |
| --- | --- | --- | --- |
| `patient_arrived` | Cruza la puerta | `admision` | Vacío (medio de llegada en el hito 4) |
| `patient_registered` | Admisión, en el mismo instante | `admision` | Vacío (edad y sexo en el hito 4) |
| `triage_started` | Empieza el triaje | `triaje` | Vacío |
| `triage_completed` | Termina el triaje | `triaje` | `nivel` |
| `box_assigned` (nuevo) | Ocupa un box | `his` | `box` |
| `patient_displaced` (nuevo) | Desalojado por un nivel 1 | `his` | `box`, `desalojado_por` (episodio) |
| `assessment_started` | Empieza una valoración | `his` | `tipo` (`inicial` o `reevaluacion`), `pool`, `box` |
| `assessment_ended` | Termina o se corta | `his` | `tipo`, `interrumpida` |
| `test_ordered` | Se piden pruebas | `his` | Vacío (tipo de prueba en el hito 4) |
| `test_resulted` | Llegan los resultados | `lab` | Vacío (resultado en el hito 4) |
| `disposition_decided` | Decisión de destino | `his` | `destino` (`alta` o `ingreso`) |
| `patient_departed` | Sale y libera el box | `his` | `destino` |
| `staffing_changed` | Empieza un turno | `rrhh` | `recurso`, `anterior`, `nueva` |

`reassessment_done` del catálogo v0 se sustituye por `assessment_started` y `assessment_ended` con `tipo: reevaluacion`, para poder derivar la ocupación de los médicos. El resto del catálogo v0 (abandono, boarding, shocks, control, snapshots) llega en sus hitos.

**Reglas del log**

- El orden del fichero es el de emisión: `sim_time` no decrece y, a igualdad de tiempo, manda el orden en que SimPy ejecutó las transiciones.
- Los nombres de campo del sobre van en inglés, como en el diseño; las claves y valores del `payload`, en español, como las claves de configuración.
- Un test compara las claves de cada `payload` con las del catálogo: ningún campo oculto puede colarse en el log.
- El log se puede escribir en un fichero o guardar en memoria (para tests y notebooks) con la misma interfaz.

**Ground truth**

Lo que el hospital no ve va en dos CSV tidy, aparte del log y con la huella de la configuración y la semilla en cada fila, como los CSV del hito 2:

- `ground_truth_dias.csv`: una fila por día con los campos de `DayRecord` (Z, esperadas, cota, candidatas, aceptadas).
- `ground_truth_episodios.csv`: una fila por episodio con lo sorteado al llegar: nivel, duraciones de triaje, valoración y reevaluación, si tenía pruebas, tiempo de respuesta y destino.

En el hito 3 el nivel y el destino coinciden con los del log, porque el triaje no tiene error; en el hito 4 aparecerán la gravedad latente y la calidad del triaje, y en el hito 5, la paciencia. El ground truth solo se usa para validar; el formato Parquet llega con la persistencia del hito 7.

**Estado y métricas derivados del log**

- Tabla de episodios: una fila por episodio con los instantes de cada hito (llegada, inicio y fin de triaje, primer box, inicio de la valoración, decisión, salida), nivel, destino y número de desalojos.
- Curvas escalonadas: censo, boxes ocupados, médicos y enfermeras ocupados y capacidad efectiva de cada pool, cambiando solo en los instantes de los eventos.
- Métricas en la ventana \[calentamiento, horizonte\]: esperas de triaje, de box y de médico por nivel (media y p90), estancia total, ocupación por pool y turno, rendimiento y ley de Little (L ≈ λ̂·W) con el mismo recorte a la ventana que `mm1_metrics`.
- Todo se calcula con funciones puras que reciben eventos; la CLI y el notebook solo las llaman (decisión 16).

## Aleatoriedad y reproducibilidad

- `child_streams(seed, 5)` da cinco flujos: llegadas (que se pasa tal cual a `iter_arrivals`, que a su vez separa candidatas y Z), nivel de triaje, duraciones, pruebas (Bernoulli y respuesta) y destino. Añadir un flujo en el hito 4 no cambia los anteriores, porque cada hijo depende solo de su índice.
- Las llegadas del motor son idénticas, bit a bit, a las de `iter_arrivals` con el primer flujo: el motor no perturba las llegadas. Se testea.
- Los sorteos del paciente se hacen al llegar y en orden fijo (ver "El paciente como proceso"). Cambiar la plantilla no cambia ningún valor del ground truth de los episodios. Se testea.
- `seed` admite `int | SeedSequence`; con la misma semilla, el log y el ground truth son idénticos bit a bit, también al pasar dos veces el mismo `SeedSequence`; con semillas distintas, distintos.
- El motor recibe las llegadas como iterable y el muestreo del paciente como una función inyectable, con la misma interfaz que usará el hito 4. Así los tests pueden construir escenarios exactos a mano.

## Validación del motor

Un servicio con λ(t), tres pools, prioridades y desalojo no tiene fórmula cerrada. Se valida con varios tipos de comprobación, cada uno ciego a algo, como las cinco pruebas del hito 2.

| Nivel | Qué detecta | Comprobaciones | Criterio |
| --- | --- | --- | --- |
| 1. Invariantes | Errores de lógica en cualquier ejecución | Ver la lista de abajo | Cero violaciones |
| 2. Leyes operacionales | Incoherencias entre caminos de cálculo | Ley de Little global y por etapa; área de ocupación de cada pool = suma de los tiempos de atención en la ventana | Little dentro del 2 %; el área, con tolerancia relativa 10⁻⁹ |
| 3a. M/G/1 | Esperas mal calculadas en una cola FIFO | Triaje con 1 enfermera y λ constante (perfil plano, CV 0, 8 llegadas/h): Pollaczek–Khinchine da Wq = 13,10 min, ρ = 0,772 y Lq = 1,747 | Teoría dentro del IC al 99 % con 20 réplicas de 30 días |
| 3b. Mₜ/G/∞ | Errores en el flujo con λ(t) | Con capacidad infinita y CV 0, el censo en t es Poisson de media m(t) = ∫ λ(s) · P(estancia > t − s) ds | Media del censo por hora del día dentro de su IC al 99 % (Bonferroni entre las 24 horas) |
| 4. Condiciones extremas | Comportamientos conocidos sin calcular | Ver la lista de abajo | Exactos o emparejados |
| 5. Regresión | Cualquier cambio en un sitio concreto | Huella SHA-256 del log y del ground truth con semilla fija y 3 días | Igual a la guardada |
| 6. Trazas | Sentido clínico | Lectura de episodios concretos en el notebook | Revisión de Pedro |

Fórmula de Pollaczek–Khinchine para la M/G/1, con E\[S²\] de una lognormal; con servicio exponencial se recupera la M/M/1 del hito 1, y la diferencia entre ambas es el factor (1 + CV²)/2:

```latex
W_q = \frac{\lambda\,E[S^2]}{2\,(1-\rho)}, \qquad E[S^2] = e^{2\mu + 2\sigma^2}, \qquad \rho = \lambda\,E[S]
```

**Invariantes (en cada validación y en tests rápidos con ejecuciones cortas)**

- Conservación: en cada instante, llegadas = salidas + dentro, con el censo nunca negativo.
- Capacidad: ningún box ocupado por dos pacientes ni número de box fuera de rango; ninguna atención de médico o enfermería empieza con el pool ya a la plantilla vigente.
- Tiempo: `sim_time` no decrece en el fichero; ningún evento de un episodio es anterior a su `patient_arrived`.
- Transiciones: la secuencia de eventos de cada episodio es válida para la máquina de estados (un autómata en el código).
- Nadie se cuela: al asignar un box o empezar una valoración, ningún paciente que ya esperaba ese recurso tiene una clave `(nivel, llegada)` menor.
- Desalojo: solo desaloja un nivel 1 a alguien de nivel mayor; si un nivel 1 espera box, todos los boxes los ocupan niveles 1.

**Condiciones extremas**

- Capacidad infinita: todas las esperas son exactamente 0 y la estancia de cada episodio en el log es exactamente la suma de sus duraciones del ground truth: triaje y valoración y, si tiene pruebas, respuesta y reevaluación.
- Sin nivel 1 en el reparto: ningún `patient_displaced`.
- Todos del mismo nivel: los boxes se asignan en orden de llegada.
- Escenario a mano (el ejemplo de tres boxes de la sesión conceptual): llegadas y duraciones fijas, instantes de cada evento calculados a mano, incluidos el desalojo y la reanudación.
- Más médicos con la misma semilla: el ground truth de los episodios es idéntico y la espera media de médico baja (comparación emparejada).

**Reglas**

- Semilla fija en los tests; si uno falla, no se cambia la semilla: se analiza la causa.
- Nivel 0,01 en las pruebas estadísticas, como en el hito 2. Las pruebas largas (3a, 3b) se marcan `slow`.
- Validar al validador: cada tarea comprueba con versiones incorrectas temporales, con predicción previa, qué tests las detectan. Ejemplos: prioridad solo por nivel (sin la llegada), boxes FIFO, desalojo que reinicia la valoración, reservas de turno con desalojo, flujos compartidos entre fuentes.

## Salidas: CLI, JSONL y CSV

Dos subcomandos nuevos bajo `edsim motor`, con opciones en español y la arquitectura fina de los hitos anteriores: la CLI lee argumentos, llama al paquete y escribe.

```bash
edsim motor simular --centro config/centro.toml --llegadas config/llegadas.toml --dias 14 --calentamiento 2 --semilla 2026 --salida resultados/motor
edsim motor validar --centro config/centro.toml --llegadas config/llegadas.toml --replicas 20 --semilla 2026 --salida resultados/motor
```

- `simular` escribe `eventos.jsonl`, `ground_truth_episodios.csv` y `ground_truth_dias.csv`, comprueba las invariantes e imprime un resumen: pacientes llegados, salidos y dentro; esperas y estancia por nivel (media y p90); ocupación por pool y turno; y la ley de Little. `--run-id` es opcional (por defecto, `r` y la semilla).
- `validar` ejecuta los niveles 1 a 4 de la validación e imprime una tabla con una fila por comprobación: valor, IC o tolerancia, criterio y resultado. Guarda `censo.png` (censo y boxes ocupados frente a la capacidad), `esperas_por_nivel.png`, `mg1.png` (Wq simulada con su IC frente a Pollaczek–Khinchine) y `censo_por_hora.png` (censo medio por hora frente a m(t)).
- Códigos de salida como en el hito 2: 0 si todo va bien; 1 si alguna invariante o prueba falla, escribiendo igualmente los ficheros para diagnosticar; 2 para errores de uso, sin crear ficheros a medias (incluido `--salida` apuntando a un fichero existente, la lección de la tarea 2.5).
- `--centro` y `--llegadas` son opcionales y usan los ficheros de `config/`; `resultados/` ya está en `.gitignore`.

## Estructura del código

```
config/
  centro.toml            centro base del motor
src/edsim/engine/
  __init__.py
  center.py              CenterConfig, load_center (tomllib), validación
  clinical.py            sorteos provisionales del paciente al llegar (interfaz del hito 4)
  events.py              sobre, catálogo, EventLog (memoria o JSONL), read_events
  resources.py           pools, claves de prioridad, reservas de turno, boxes libres
  patient.py             proceso paciente: máquina de estados, desalojo y reanudación
  engine.py              simulate_ed: entorno, arrival_source, turnos, horizonte
  ground_truth.py        registros del ground truth
  analysis.py            tabla de episodios, curvas escalonadas, métricas, Little
  invariants.py          comprobaciones sobre el log
  validation.py          M/G/1, Mₜ/G/∞, condiciones extremas, validate_engine
  report.py              resumen, tabla de validación, CSV y gráficas
src/edsim/cli.py         subcomandos motor simular y motor validar
notebooks/03_motor_exploracion.ipynb
tests/test_center.py, test_clinical.py, test_events.py, test_patient.py, test_priority.py,
      test_shifts.py, test_engine.py, test_analysis.py, test_invariants.py,
      test_engine_validation.py, test_cli.py
```

Sin dependencias nuevas: `json` y `tomllib` vienen con Python 3.13. Se reutilizan `iter_arrivals`, `arrival_source`, `DayRecord`, `child_streams`, `stats.summarize` y el estilo de `report.py` del hito 2.

## Tests

| Grupo | Qué comprueba |
| --- | --- |
| Centro | Carga del TOML de ejemplo y del real; normalización del reparto de niveles; errores con longitudes, horas, capacidades, medianas, p90 y probabilidades inválidos |
| Sorteos | Parámetros de la lognormal a mano; frecuencias de nivel, pruebas e ingreso; el paciente k recibe los mismos valores con otra plantilla |
| Eventos | Sobre completo y con tipos correctos; `event_id` determinista; `event_time` truncado y con `+01:00`; ida y vuelta por JSONL; claves de `payload` del catálogo |
| Paciente | Secuencia de eventos de un paciente solo; pruebas y reevaluación; box retenido y médico liberado durante las pruebas |
| Prioridad y desalojo | Comportamiento de SimPy fijado con un test; nadie se cuela; el escenario a mano de tres boxes; reanudación con el tiempo pendiente |
| Turnos | Plantilla efectiva en cada turno; la reserva espera a que el profesional termine; `staffing_changed` en cada cambio |
| Motor | Reproducibilidad y semillas distintas; llegadas idénticas a `iter_arrivals`; horizonte y pacientes dentro al final; huella SHA-256 |
| Análisis e invariantes | Curvas y métricas con logs construidos a mano; cada invariante detecta un log roto a propósito |
| Validación (slow) | M/G/1 y Mₜ/G/∞ con semilla fija; condiciones extremas |
| CLI | Los subcomandos responden, generan sus ficheros y dan código 2 ante errores de uso |

Como en los hitos anteriores, el hook Stop de Claude Code ejecuta `pytest -m "not slow"` y el CI ejecuta todos.

## Notebook de exploración del motor

Un tercer notebook didáctico, con las reglas de los anteriores: toda la lógica vive en `edsim`, se ejecuta de principio a fin, semillas explícitas, modo rápido `EDSIM_NB_RAPIDO=1` para el CI y sin resultados en git. Cada sección combina una explicación breve, código que solo llama a `edsim`, una gráfica, preguntas "Para experimentar" y un recuadro "Lo que debes recordar".

Contenido

- Uso: cómo ejecutarlo y el modo rápido.
- Introducción: del M/M/1 al servicio de urgencias.
- Un paciente paso a paso: sus eventos del log y su línea de tiempo.
- El log como fuente de verdad: de los eventos al censo, la ocupación y las esperas.
- Recursos retenidos en tramos distintos: diagrama de Gantt de boxes y médicos de una mañana.
- Prioridad y desalojo: el escenario de tres boxes y las esperas por nivel en una semana.
- Carga ofrecida y turnos: m(t) frente a la plantilla; qué pasa al quitar un médico el lunes por la mañana.
- Calentamiento: varias semillas desde vacío y el régimen periódico.
- Validación: invariantes, Little, M/G/1 y Mₜ/G/∞; la variabilidad del servicio con el factor (1 + CV²)/2.
- Números aleatorios comunes: más médicos con la misma semilla, paciente a paciente.
- Para experimentar: plantilla, boxes, duraciones, reparto de niveles y semillas.
- Resumen: las lecciones del hito en pocas frases.

## Decisiones del hito

Siete decisiones candidatas; si se confirman durante el hito, la tarea de cierre las convierte en los ADR 0024 a 0030 y las añade al registro del diseño.

| # | Decisión | Motivo |
| --- | --- | --- |
| 24 | Cada paciente es un proceso SimPy que recorre la máquina de estados; todo lo aleatorio del paciente se sortea al llegar, en orden fijo, con un flujo por fuente, detrás de una función de muestreo inyectable | Los estados son los `yield`; el paciente k es el mismo con cualquier plantilla (números aleatorios comunes); el hito 4 cambia el muestreo sin tocar el motor |
| 25 | Tres pools: triaje FIFO; boxes con prioridad `(nivel, llegada)` y desalojo solo del nivel 1, con reanudación del tiempo pendiente; médicos con prioridad sin desalojo. El box se retiene toda la estancia y el médico solo en las valoraciones | Reglas de flujo del diseño; el orden no depende de cuándo se pide el recurso; el box como cuello de botella realista |
| 26 | Plantilla por turnos (8–15, 15–22, 22–8) desde el hito 3, con reservas de capacidad que esperan a que el profesional termine | `staffing_changed` y el dimensionado por turno están en la v0; un `Resource` no cambia de capacidad; nadie deja a un paciente a medias |
| 27 | Log JSONL con el sobre del diseño más `sim_time`, `event_id` determinista y hora con desfase fijo `+01:00`; `box_assigned` y `patient_displaced` se añaden al catálogo y la reevaluación usa `assessment_started/ended` | Reproducibilidad bit a bit; cálculos sin redondeos de reloj; la ocupación de boxes y médicos se puede derivar del log |
| 28 | Ground truth en ficheros aparte (episodios y días); el log no lleva campos fuera del catálogo, y un test lo comprueba | Principio de verdad oculta separada; evita *data leakage*; validación con valores conocidos |
| 29 | Calentamiento y horizonte en días completos (2 y 14 por defecto); en batch el log es completo y las métricas usan la ventana | Régimen periódico sin estado estacionario; invariantes válidas en todo el fichero; el modo directo del hito 6 añadirá el censo inicial |
| 30 | Validación del motor por niveles: invariantes sobre el log, leyes operacionales, M/G/1 (Pollaczek–Khinchine) y Mₜ/G/∞ de referencia, condiciones extremas y huella de regresión, al nivel 0,01 | Sin fórmula cerrada para el sistema completo, cada tipo de comprobación cubre errores que los otros no ven |

Al cerrar el hito se actualizan también la pestaña de diseño (la v1 deja de incluir la plantilla por turno y el catálogo de eventos recoge los cambios de la decisión 27) y el formato de configuración: TOML, como en la decisión 19, en lugar de YAML con Pydantic.

## Tareas, ramas y orden de ejecución

Las tareas con código empiezan cuando exista la etiqueta `v0.2-hito2`. Cada tarea empieza con una explicación breve del concepto en el chat del hito, sigue con el plan en modo Plan en una sesión nueva de Claude Code y se ejecuta en modo Manual; al cerrarla se actualiza el anexo.

| # | Tarea | Rama | Resultado |
| --- | --- | --- | --- |
| 3.1 | Especificación en `docs/specs/hito-3.md`, configuración del centro y sorteos del paciente | `feat/h3-centro` | `center.py` y `clinical.py` con valores comprobados a mano |
| 3.2 | Log de eventos: sobre, catálogo y JSONL | `feat/h3-eventos` | `events.py` con ida y vuelta por JSONL y claves del catálogo |
| 3.3 | Paciente como proceso con pools sin prioridad, llegadas del hito 2, horizonte, ground truth e invariantes básicas | `feat/h3-paciente` | Primer log completo y reproducible; conservación, tiempo y transiciones en verde |
| 3.4 | Prioridad `(nivel, llegada)` y desalojo con reanudación | `feat/h3-prioridad` | "Nadie se cuela" y el escenario a mano de tres boxes en verde |
| 3.5 | Turnos con reservas y calentamiento | `feat/h3-turnos` | Plantilla efectiva por turno y `staffing_changed` |
| 3.6 | Estado y métricas derivados del log y validación (Little, M/G/1, Mₜ/G/∞, condiciones extremas) | `feat/h3-validacion` | Todas las comprobaciones en verde con semilla fija |
| 3.7 | CLI `motor simular` y `motor validar` con resumen, tabla y gráficas | `feat/h3-cli` | Log, ground truth, tabla de validación y gráficas generados por EDsim |
| 3.8 | Notebook `03_motor_exploracion.ipynb` | `feat/h3-notebook` | Notebook ejecutable de principio a fin en el CI |
| 3.9 | Cierre: ADR 0024 a 0030, diario, anexo, exportación de pestañas, ajustes de la pestaña de diseño y etiqueta `v0.3-hito3` | `docs/h3-cierre` | Hito cerrado |

**Preparación en la tarea 3.1:** exportar esta pestaña a `docs/specs/hito-3.md` y apuntar en `CLAUDE.md` el hito en curso al hito 3.

**Prompts para Claude Code.** Cada tarea va en una sesión nueva, así que el prompt pide un plan que empiece con una sección "Contexto": qué ficheros ha leído (`CLAUDE.md`, `docs/specs/hito-3.md`, los módulos que reutiliza y los de las tareas anteriores) y qué ha entendido de la tarea, antes de proponer cambios. Para la lógica delicada, el plan incluye versiones incorrectas temporales con la predicción de qué tests fallarán.

**Flujo de git en cada tarea (como en el hito 2)**

- Claude Code parte de `main` actualizado y crea la rama: `git switch main && git pull && git switch -c <rama>`.
- Hace un commit por paso, con prefijo y mensaje en español, añadiendo los ficheros por su nombre, después de que Pedro revise el diff.
- Pide permiso para `git push -u origin <rama>` y abre el PR con `gh pr create`, con un resumen y las comprobaciones hechas.
- Pedro revisa el PR, espera el CI en verde y fusiona con *squash and merge*. `gh pr merge` sigue denegado para Claude Code.
- Sincronización: `git switch main && git pull && git branch -D <rama>`.

## Criterios de aceptación

El hito 3 está cerrado cuando se cumplen todos:

- `uv run pytest` pasa, incluidos los tests slow, y el CI está en verde.
- Con la misma semilla, dos ejecuciones dan un log y un ground truth idénticos bit a bit, y las llegadas del log son las de `iter_arrivals`.
- `edsim motor simular` con los valores por defecto escribe `eventos.jsonl` y los dos CSV del ground truth, sin ninguna invariante violada.
- `edsim motor validar` pasa todas sus comprobaciones: invariantes, Little, M/G/1 frente a Pollaczek–Khinchine, Mₜ/G/∞ y condiciones extremas, y guarda sus cuatro gráficas.
- El escenario a mano de tres boxes reproduce exactamente los instantes calculados, incluidos el desalojo y la reanudación.
- Ningún `payload` del log contiene campos fuera del catálogo.
- `notebooks/03_motor_exploracion.ipynb` se ejecuta de principio a fin en el CI y se versiona sin resultados.
- Pedro sabe explicar por qué el box es el cuello de botella aunque haya médicos libres, por qué la prioridad es una tupla, cómo se derivan el censo y la ocupación del log y cómo se valida un sistema sin fórmula cerrada.
- Todos los PRs del hito los abrió Claude Code y los fusionó Pedro.
- `docs/` contiene esta especificación, los ADR nuevos, la entrada del diario y el anexo de referencia del hito.
- La etiqueta `v0.3-hito3` existe en GitHub.

Fuentes: Ministerio de Sanidad y Emergencias 2013 (objetivos de calibración del diseño) · documentación de recursos de SimPy ([simpy.readthedocs.io](https://simpy.readthedocs.io/en/latest/topical_guides/resources.html)) · Eick, Massey y Whitt (1993), The physics of the Mₜ/G/∞ queue · fórmula de Pollaczek–Khinchine para la M/G/1

## Anexo: guía de referencia del hito 3

Este anexo se amplía al cerrar cada tarea del hito con lo que se hizo, los conceptos que aparecieron, las decisiones, los resultados medidos y las lecciones aprendidas. Sirve de referencia para repetir el trabajo o retomarlo más adelante.
