# Hito 3 — Motor y eventos

> **Estado:** cerrado (`v0.3-hito3`). Original en este repositorio desde el 10 de noviembre de 2026; la pestaña del documento online es un archivo.

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

> Diagrama «flujo del hito 3 · de la configuración y la semilla a la validación»: en la [pestaña archivada](https://claude.ai/artifact/8pd9CbSV9JTCm7MghHtMV9#b696232b-6338).

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

- El nivel 1 pide box con `preempt=True` solo si algún box lo ocupa un paciente de nivel mayor que 1; si todos los boxes los ocupan niveles 1, pide sin desalojo y espera el primero. El resto pide con `preempt=False`. Basta con decidirlo al pedir, porque SimPy solo desaloja en el instante de la petición. Si no hay box libre, SimPy expulsa al usuario con la clave mayor (menor prioridad), siempre que sea menos prioritario que el nivel 1 que llega. Un nivel 1 nunca desaloja a otro nivel 1 (con la tupla sola, uno que llegó antes podría desalojar a uno que llegó después). El box del desalojado se reserva para el nivel 1 que lo desaloja, aunque en el mismo instante se libere otro con número menor.
- El desalojado recibe `simpy.Interrupt` en el `yield` en el que esté. Emite `patient_displaced` (box y `episode_id` de quien lo desaloja), vuelve a pedir box con su misma clave y sin desalojo y, al recuperarlo, emite otro `box_assigned`.
- Si estaba en valoración o reevaluación, se corta: se libera el médico, se emite `assessment_ended` con `interrumpida: true` y, al recuperar box y médico, se reanuda con el tiempo pendiente (*preempt-resume*). Si estaba esperando pruebas, el reloj de las pruebas sigue corriendo: el laboratorio es un proceso propio de cada paciente que emite `test_resulted` y dispara un evento que el paciente espera, así que los resultados pueden llegar mientras espera box en la sala. Si estaba esperando médico dentro del box, cancela esa petición.
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
- El día 0 empieza a las 0:00 en el turno de noche que empezó a las 22 h del día anterior. En el minuto 0, antes que cualquier otro evento, se emite un `staffing_changed` por pool de personal con `anterior` 0 y la plantilla de ese turno, para que el log describa la plantilla vigente desde el principio sin consultar la configuración. Después solo se emite cuando la plantilla cambia de verdad (de 12 a 12 no hay evento).

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
- El motor no perturba las llegadas: el ground truth guarda el instante de cada llegada idéntico, bit a bit, al de `iter_arrivals` con el primer flujo. En el log, `patient_arrived` lleva `env.now`, como todos los eventos, y puede diferir en el último bit (como mucho 1 ulp): `arrival_source` espera `t − now` y la suma `now + (t − now)` se redondea. El error no se acumula, porque cada espera apunta a un instante absoluto. Las dos cosas se testean.
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
- Nadie se cuela: al asignar un box o empezar una valoración, ningún paciente que esperaba ese recurso desde un instante estrictamente anterior tiene una clave `(nivel, llegada)` menor. Los empates de un mismo instante no cuentan: el orden del fichero dentro de un instante no es el orden de las concesiones de SimPy.
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
- Días punta: la espera por día y nivel en un mes, el porcentaje de días fuera de los tiempos máximos de Manchester y por qué una ocupación media del 70 % esconde días saturados (hallazgo de la tarea 3.7).
- Validación: invariantes, Little, M/G/1 y Mₜ/G/∞; la variabilidad del servicio con el factor (1 + CV²)/2.
- Números aleatorios comunes: más médicos con la misma semilla, paciente a paciente.
- Para experimentar: plantilla, boxes, duraciones, reparto de niveles y semillas.
- Resumen: las lecciones del hito en pocas frases.

## Decisiones del hito

Siete decisiones candidatas; si se confirman durante el hito, la tarea de cierre las convierte en los ADR 0024 a 0030 y las añade al registro del diseño.

| # | Decisión | Motivo |
| --- | --- | --- |
| 24 | Cada paciente es un proceso SimPy que recorre la máquina de estados; todo lo aleatorio del paciente se sortea al llegar, en orden fijo, con un flujo por fuente, detrás de una función de muestreo inyectable | Los estados son los `yield`; el paciente k es el mismo con cualquier plantilla (números aleatorios comunes); el hito 4 cambia el muestreo sin tocar el motor |
| 25 | Tres pools: triaje FIFO; boxes con prioridad `(nivel, llegada)` y desalojo solo del nivel 1 a pacientes de nivel mayor (nunca a otro nivel 1), con reanudación del tiempo pendiente y el laboratorio como proceso propio; médicos con prioridad sin desalojo. El box se retiene toda la estancia y el médico solo en las valoraciones | Reglas de flujo del diseño; el orden no depende de cuándo se pide el recurso; el box como cuello de botella realista |
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
- Con el plan aprobado, implementa la tarea completa sin esperar revisión entre pasos (desde la tarea 3.6): un commit por paso lógico, con prefijo y mensaje en español, añadiendo los ficheros por su nombre y con ruff y los tests rápidos en verde. Solo para y pregunta si algo contradice el plan o la especificación, una biblioteca no se comporta como se esperaba, un test falla sin causa clara o hace falta una decisión de diseño nueva. Pedro revisa el PR completo, cuya descripción explica cada decisión y lo que cambió respecto al plan.
- Pide permiso para `git push -u origin <rama>` y abre el PR con `gh pr create`, con un resumen y las comprobaciones hechas.
- Pedro revisa el PR, espera el CI en verde y fusiona con *squash and merge*. `gh pr merge` sigue denegado para Claude Code.
- Sincronización: `git switch main && git pull && git branch -D <rama>`.

## Criterios de aceptación

El hito 3 está cerrado cuando se cumplen todos:

- `uv run pytest` pasa, incluidos los tests slow, y el CI está en verde.
- Con la misma semilla, dos ejecuciones dan un log y un ground truth idénticos bit a bit, y las llegadas del ground truth son las de `iter_arrivals` bit a bit (en el log, como mucho a 1 ulp).
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

### Tarea 3.1: configuración del centro y sorteos del paciente

**Qué se hizo**

- PR #19 (rama `feat/h3-centro`), abierto por Claude Code y fusionado por Pedro con *squash and merge*. Dos commits: configuración del centro y sorteos provisionales.
- La especificación ya había entrado en `main` con la tarea 2.7 (`docs/specs/hito-3.md`, y `CLAUDE.md` apuntando al hito 3), así que el paso 1 se omitió.
- `config/centro.toml` como en la especificación y `tests/data/centro_ejemplo.toml`, una copia fija que no se recalibra.
- `src/edsim/engine/center.py`: `CenterConfig` inmutable, validado y normalizado en `__post_init__`, y `load_center(path)` con `tomllib`. Una tabla `_KEYS` relaciona cada clave TOML con su campo y sirve para cargar, para detectar claves que faltan o sobran (también secciones enteras) y para los mensajes de error.
- `src/edsim/engine/clinical.py`: `lognormal_params(median, p90)`, `cumulative_shares`, `PatientDraws` y `ProvisionalSampler(center, streams)`, que recibe los flujos 1 a 4 de `child_streams(seed, 5)` y se llama con cada llegada: `sampler(arrival)`.
- 180 tests nuevos en `tests/test_center.py` y `tests/test_clinical.py` (unos 2 s; ninguno `slow`).

**Conceptos**

- **La lognormal por mediana y p90.** μ = ln(mediana) y σ = (ln p90 − ln mediana) / z₀,₉, con z₀,₉ = `NormalDist().inv_cdf(0.9)` = 1,28155, sin redondear a 1,2816. `rng.lognormal(mean, sigma)` recibe los parámetros de la normal de dentro, no la media ni la mediana: es la misma trampa que la escala de `rng.gamma` en el hito 2.
- **Consumo fijo por paciente.** Cada paciente consume siempre 1 uniforme de nivel, 3 lognormales de duraciones, 1 uniforme y 1 lognormal de pruebas y 1 uniforme de destino, aunque no use alguno. No basta con separar los flujos: dentro de cada flujo, el número de sorteos no puede depender de lo que salga.
- **Nivel por la suma acumulada.** Con una uniforme u en \[0, 1), el nivel es `searchsorted(cum, u, side="right") + 1`. Un nivel con peso 0 repite el valor acumulado del anterior y nunca se elige. En coma flotante la suma puede quedarse en 0,9999999999999999, así que `cumulative_shares` fuerza 1,0 desde el último nivel con peso.
- **El cuantil empírico con la binomial.** Si la mediana configurada es la verdadera, el número de sorteos por debajo de ella es una Binomial(n; 0,5), y el del p90, una Binomial(n; 0,9). Comprobar que 0,5 y 0,9 caen en el IC de Clopper–Pearson de esas proporciones equivale al IC del cuantil con estadísticos de orden, sin fijar un porcentaje a ojo. Con n = 20 000 y Bonferroni entre 8 comparaciones, la tolerancia es de ±0,011 en la mediana y ±0,0069 en el p90, en proporción (entre un 1,6 y un 2,8 % en minutos).
- **Una interfaz que mira al hito 4.** El muestreador recibe la llegada aunque hoy no la use: la mezcla de casos dependerá de la hora y de la estación, y así el motor no cambiará.

**Decisiones**

- `reparto_niveles` admite ceros (no negativos y suma positiva), porque las condiciones extremas de la tarea 3.6 necesitan "sin nivel 1" y "todos del mismo nivel".
- Horas de turno enteras, de 0 a 23 y estrictamente crecientes; capacidades enteras mayores o iguales que 1. `true`, `3.0`, `"3"`, nan e inf se rechazan con un error que nombra la clave TOML y la posición, como `recursos.medicos[2]`.
- `PatientDraws` guarda tipos de Python (`int`, `float`, `bool`), no escalares de NumPy, para que la igualdad sea limpia y el JSON de la tarea 3.2 no dé sorpresas.
- Los helpers de validación se copiaron en `center.py` en lugar de importar los privados de `arrivals/profile.py`. Factorizarlos en un módulo común queda como mejora posible.
- El muestreador exige exactamente cuatro `SeedSequence` y no los modifica: los mismos objetos en dos muestreadores dan los mismos sorteos.

**Resultados (centro de ejemplo, semilla 2026, 20 000 pacientes)**

| Cantidad | Esperado | Medido |
| --- | --- | --- |
| Pacientes por nivel, 1 a 5 | 60 / 2.420 / 6.720 / 10.520 / 280 | 68 / 2.374 / 6.621 / 10.640 / 297 (χ²: p = 0,215) |
| Proporción con pruebas | 0,5541 | 0,5491 |
| Proporción de ingresos | 0,1284 | 0,1278 |
| Triaje: mediana, p90 y media (min) | 5 / 10 / 5,79 | 5,05 / 10,06 / 5,81 |
| Valoración | 20 / 45 / 24,43 | 19,91 / 44,68 / 24,33 |
| Reevaluación | 10 / 20 / 11,58 | 9,96 / 19,95 / 11,51 |
| Respuesta de pruebas | 60 / 150 / 77,47 | 60,17 / 151,82 / 78,02 |

Los 20 000 pacientes se sortean en unos 0,2 s.

**Comprobación con versiones incorrectas** (temporales; observado reproducido en la revisión del PR sobre el código fusionado)

| Versión incorrecta | Predicción | Observado |
| --- | --- | --- |
| A. `rng.lognormal(mean=mediana, sigma=σ)` | Fallan los 8 cuantiles empíricos; pasan los valores a mano, las frecuencias, la reproducibilidad y la independencia | Acertada: 8 fallos, 35 tests pasan |
| B. Tiempo de respuesta sorteado solo si hay pruebas (0 si no) | Fallan los dos tests de independencia y los cuantiles de la respuesta | Acertada, y falla además `test_valores_en_rango`, que exige duraciones positivas: 5 fallos |

**Lecciones aprendidas**

- **Los tests de reproducibilidad no ven un error de parametrización.** Con la versión A, la mediana del triaje pasa a ser e⁵ ≈ 148 min y todo sigue siendo reproducible e independiente. Solo los tests que comparan con valores conocidos la detectan.
- **Separar los flujos no basta.** La versión B usa sus propios flujos, pero el consumo depende de lo que salga, y cambiar una probabilidad desplaza los tiempos de respuesta de todos los pacientes siguientes. Lo ven los tests de independencia, no los estadísticos.
- **Un test detecta todo aquello de lo que depende** (como en las tareas 2.2 y 2.3): con B también cayó el test de rangos, que no estaba en la predicción, porque el 0,0 de quien no tiene pruebas no es una duración positiva.
- **Revisar el plan antes de ejecutar paga.** La revisión añadió tres cambios antes de escribir código: la firma con la llegada, la suma acumulada forzada desde el último nivel con peso y el control de que el test de independencia no pase de forma vacía.

**Pendiente para la tarea 3.2.** La normalización del reparto no es exactamente idempotente. Con `[0.3, 12.1, 33.6, 52.6, 0]` la suma normalizada da 0,9999999999999999, y un `dataclasses.replace` vuelve a dividir y cambia el último bit, en un 11 % de repartos aleatorios (`math.fsum` no lo evita). `test_normalizacion_idempotente` lo esconde porque compara con `approx`. Arreglo: no dividir si la suma ya es 1 con tolerancia 10⁻¹², y comparar con igualdad exacta. Es la misma lección del hito 2 con `ArrivalProfile`, y conviene cerrarla antes de que las tareas 3.4 y 3.6 comparen ejecuciones bit a bit con `replace`.

### Tarea 3.2: log de eventos (sobre, catálogo y JSONL)

**Qué se hizo**

- PR #20 (rama `feat/h3-eventos`), abierto por Claude Code y fusionado por Pedro con *squash and merge*. Dos commits: el arreglo pendiente de la tarea 3.1 y el módulo de eventos.
- `fix(engine)`: `_check_shares` no vuelve a dividir si la suma ya es 1 con tolerancia 10⁻¹², y `test_normalizacion_idempotente` compara con igualdad exacta, también con `[0.3, 12.1, 33.6, 52.6, 0]`. La predicción (falla solo ese caso con el código anterior) se cumplió.
- `src/edsim/engine/events.py`, sin SimPy:
  - `CATALOG`: los 13 tipos de la especificación, cada uno con su `source_system`, si es de paciente y una comprobación por clave del `payload`.
  - `Event`: el sobre de 12 campos, validado al construirse.
  - `EventLog(run_id, start_date, sink).emit(...)`.
  - `MemorySink` y `JsonlSink`.
  - `to_json`, `from_json`, `read_events`, `event_time`, `episode_id` y `patient_id`.
- 84 tests nuevos en `tests/test_events.py`; con `center` y `clinical`, 265 tests en 2,6 s.

**Conceptos**

- **Event sourcing.** El log es una lista de hechos inmutables, en orden y solo de añadir; el estado se calcula recorriéndolos. Por eso el log tiene que ser exacto, reproducible bit a bit y cerrado.
- **Sobre y `payload`.** Todos los eventos tienen la misma forma exterior; lo específico va en el `payload`. El catálogo es la única definición de los tipos, y quien emite no pasa el `source_system`: lo pone el catálogo, así no puede contradecirlo.
- **Validar al emitir.** Un tipo desconocido, una clave de más o de menos, o un valor de tipo incorrecto (un nivel `"3"`, `True` como entero) falla en el primer evento, no en un log de 100 000 líneas. Un `emit` que falla no consume número ni mueve el reloj del log.
- **JSONL.** Una línea, un objeto: se añade al final, se lee línea a línea con un generador, un corte solo estropea la última línea y cada línea será un mensaje de Kafka.
- **Bytes reproducibles.** Orden de claves fijo (el del sobre y, en el `payload`, el del catálogo), `ensure_ascii=False`, UTF-8 y `newline="\n"` explícitos, `allow_nan=False` (NaN no es JSON) y `event_id` determinista en lugar de `uuid4`.
- **Truncar los milisegundos.** `ms = floor(sim_time · 60 000)` y, desde ahí, todo en enteros. Redondeando, 1.439,9999999 min pasaría al día siguiente.
- **`MappingProxyType` y `pickle`.** Un `payload` de solo lectura no se puede serializar con `pickle` ni copiar con `deepcopy`; `__reduce__` reconstruye el evento con un `dict` y vuelve a validarlo. Lo necesitarán las réplicas en paralelo de los hitos 9 y 10.

**Decisiones**

- Las claves y los valores del `payload` no llevan tilde (`reevaluacion`), como las claves TOML. Para comprobar `ensure_ascii=False`, el test usa un `run_id` con tilde, que es un texto libre del sobre.
- Los tipos de cada clave del `payload` se definieron en la tarea, porque la especificación solo fijaba los nombres: `nivel` 1–5; `box` ≥ 1; `anterior` y `nueva` ≥ 0; `tipo`, `pool`, `destino` y `recurso` de un conjunto cerrado; `interrumpida` booleano; `desalojado_por` con formato de episodio.
- `episode_id` y `patient_id` rechazan un `arrival_id` mayor que 999.999 en lugar de escribir siete cifras: el límite, unos 9 años a 300 urgencias al día, está documentado.
- `sim_time` se valida en una sola función, que usan `emit`, `Event` y `event_time`. Un `sim_time` que decrece da `RuntimeError` (regla interna rota del motor) y no `ValueError`.
- `Event` exige `ingest_time` nulo y `schema_version` 1. Los hitos siguientes cambian esas reglas así: el hito 4 admite las versiones 2 y 3 del catálogo; en el hito 6, `ingest_time` sigue nulo dentro del mensaje de Kafka (la hora de llegada es la marca `LogAppendTime` del broker), y el consumidor del hito 7 lo rellena al guardar en la capa bronce.

**Resultados**

| Medida (100.000 eventos) | Valor |
| --- | --- |
| `emit` con `MemorySink` | 16 µs por evento |
| `emit` con `JsonlSink` | 24 µs por evento |
| Tamaño del JSONL | 35 MB, unos 350 bytes por evento |

Un `simular` de 14 días (unos 55.000 eventos) gasta alrededor de 1,3 s en el log. La validación de la tarea 3.6, con 20 réplicas de 30 días, ronda los 2,3 millones de eventos: casi un minuto solo de log, y demasiada memoria si se guardan todos como `Event`.

**Comprobación con versiones incorrectas** (temporales; observado reproducido en la revisión del PR)

| Versión incorrecta | Predicción | Observado |
| --- | --- | --- |
| A. `round` en lugar de truncar | Fallan los dos casos límite (1.439,9999999 y 59,99999999999999); pasan 739,02, los cambios de mes y año, la ida y vuelta y la huella | Acertada: 2 fallos |
| B. `event_id` con `uuid4` | Fallan el formato, el orden, el `emit` fallido, la igualdad entre memoria y fichero y la huella; pasa la ida y vuelta | Casi: 7 fallos. También cae la ida y vuelta, porque compara con un segundo log emitido aparte, cuyos identificadores ya no coinciden; y los dos tests del sobre que comparan el `event_id` literal |
| C. Sin `allow_nan=False` ni la comprobación de nan e inf | Primera predicción: `emit` con nan e inf ya no falla. Corregida en la revisión del plan: falla por `math.floor`, con otro mensaje | 4 fallos: `emit` con nan e inf (el mensaje ya no nombra `sim_time`) y `read_events` con NaN e infinito en el fichero, que ahora los acepta |

**Lecciones aprendidas**

- **Un test puede pasar por la razón equivocada.** Sin la comprobación de nan, `math.floor(nan)` sigue lanzando un `ValueError`. Un test que solo comprobara el tipo de excepción seguiría en verde; exigir que el mensaje nombre `sim_time` es lo que lo detecta.
- **Los casos límite se eligen a propósito.** El redondeo solo se ve con valores pegados a un cambio de segundo o de día; 739,02 da lo mismo con las dos versiones.
- **Un test detecta todo aquello de lo que depende** (otra vez): la ida y vuelta de la versión B cayó porque compara dos logs emitidos por separado. Predecir obliga a leer cómo está construido cada test, no solo su nombre.
- **Pensar en cómo se usará el código** (la lección de `SeedSequence.spawn`): `MappingProxyType` cumplía la inmutabilidad, pero habría roto las réplicas en paralelo. Lo detectó la revisión del plan, no un test.
- **La revisión encuentra errores del revisor.** El prompt pedía comprobar "reevaluación" con tilde en un catálogo sin tildes; Claude Code lo preguntó antes de escribir el test.

**Pendiente para las tareas 3.3 y 3.6.** Medir cuánto pesa el log frente a SimPy en el motor completo. En la validación con réplicas, calcular las métricas réplica a réplica en lugar de acumular millones de `Event` en memoria.

### Tarea 3.3: el paciente como proceso

**Qué se hizo**

- PR #21 (rama `feat/h3-paciente`), abierto por Claude Code y fusionado por Pedro con *squash and merge*. Tres commits: invariantes, paciente con pools FIFO y `simulate_ed`.
- `engine/patient.py`: el proceso del paciente recorre la tabla de estados y emite cada evento en su transición. Tres `simpy.Resource` FIFO, sin prioridad, desalojo ni turnos. El box se retiene de `box_assigned` a `patient_departed`; el médico, solo en cada valoración, y queda libre durante las pruebas.
- `engine/resources.py`: los pools, con la plantilla máxima de cada turno, y `BoxNumbers`, un montículo (`heapq`) que asigna el box libre de número más bajo.
- `engine/ground_truth.py`: `EpisodeTruth` (llegada y sorteos) y `GroundTruth` (episodios y `DayRecord`).
- `engine/engine.py`: `run_engine`, con las llegadas como iterable y el muestreador inyectable, y `simulate_ed`, que usa `child_streams(seed, 5)`: el flujo 0 para `iter_arrivals` y del 1 al 4 para `ProvisionalSampler`. El `run_id` por defecto es `r` y la semilla; un hijo de `SeedSequence(2026)` da `r2026.1`.
- `engine/invariants.py`: conservación, tiempo, transiciones (un autómata escrito como datos) y capacidad. Son funciones puras que devuelven violaciones, registradas en `CHECKS` para que la tarea 3.4 añada las suyas.
- 70 tests nuevos (`test_invariants.py`, `test_patient.py`, `test_engine.py`); la suite rápida queda en 698 tests.

**Conceptos**

- **El motor en tres piezas.** `arrival_source` entrega cada llegada; `on_arrival` pide los sorteos con `sampler(arrival)`, en orden de llegada, y crea el proceso; el proceso del paciente espera en cada `yield` y emite en cada transición.
- **Recursos retenidos en tramos distintos.** Un `with boxes.request()` envuelve toda la estancia en el box; los médicos se piden y se sueltan en cada valoración. Es la diferencia que hace del box el cuello de botella.
- **El número de box.** SimPy solo cuenta plazas; qué box concreto ocupa cada paciente lo lleva aparte un montículo de números libres, de forma determinista.
- **El orden de lo simultáneo.** Cada evento de fin (`triage_completed`, `assessment_ended`, `patient_departed`) se emite antes de liberar su recurso. Quien lo recibe en ese mismo instante se reanuda después, así que en el log el relevo aparece en orden y las invariantes nunca ven un ocupado de más.
- **El horizonte.** `env.run(until=días × 1440)`: los pacientes que siguen dentro no tienen `patient_departed`, y su recorrido es un prefijo válido de la máquina de estados.
- **Conservación con fuentes independientes.** "Llegadas = salidas + dentro", calculado solo con el log, es cierto por construcción. Lo que comprueba algo es comparar con el ground truth (cada episodio, exactamente un `patient_arrived`) y con los procesos que siguen vivos en SimPy al terminar.
- **El ulp de `arrival_source`.** `now + (t − now)` puede no ser exactamente t: pasa en 1 de cada 92.414 llegadas, medido con 20 semillas de 14 días. El ground truth guarda `arrival.time` bit a bit; el log usa `env.now`, como todos los eventos. La comprobación exacta con capacidad infinita parte del `sim_time` del log.

**Decisiones**

- Se reutiliza `arrival_source` sin cambios; el test de llegadas exige igualdad bit a bit en el ground truth y como mucho 1 ulp en el log. La especificación se corrigió en ese sentido.
- `check_invariants` recibe el ground truth y `inside` como argumentos opcionales, para poder validar también un log leído de un fichero sin ellos.
- Tras la primera transición inválida, el episodio deja de revisarse: un error da una violación, no una cascada.
- Huella SHA-256 del JSONL (centro y perfil de ejemplo, semilla 2026, 3 días). Se regenerará a propósito en las tareas 3.4 y 3.5, que cambian el orden de servicio.

**Resultados (14 días, `config/centro.toml` y `config/llegadas.toml`, semilla 2026)**

4.439 pacientes, 49.778 eventos, un JSONL de 18,3 MB y cero violaciones. Un recorrido tiene 13 eventos con pruebas y 9 sin ellas.

| Variante | Tiempo | µs por evento |
| --- | --- | --- |
| Sin emitir eventos (SimPy y sorteos) | 0,19 s | 3,9 |
| Sink nulo (construir y validar los `Event`) | 0,71 s | 14,3 |
| `MemorySink` | 0,77 s | 15,5 |
| `JsonlSink` | 1,09 s | 21,9 |
| `check_invariants` | 0,03 s | 0,7 |

El log se lleva el 83 % del tiempo: 0,52 s en construir y validar los eventos y 0,38 s en serializarlos. La simulación en sí es barata. Por ahora no hace falta optimizar.

**Comprobación con versiones incorrectas** (temporales; resultado del PR)

| Versión incorrecta | Fallos | Predichos y observados | No predichos |
| --- | --- | --- | --- |
| A. Sortear al asignar el box | 7 | Capacidad infinita, horizonte, otra plantilla, invariantes (×2) y huella. Las llegadas y los días pasan, como se predijo | Dos pacientes y un box |
| B. Liberar el box tras la valoración inicial | 6 | Dos pacientes y un box, médico libre durante las pruebas, invariantes (×2) y huella | Pacientes dentro al final |
| C. `test_resulted` antes del `timeout` de la respuesta | 3 | Paciente con pruebas, capacidad infinita y huella | — |

**Lecciones aprendidas**

- **Las invariantes miran la forma del log, no si los tiempos tienen sentido.** La versión C deja un orden válido y un tiempo que no decrece: solo la detectan los tests que conocen los instantes esperados (el escenario a mano y la capacidad infinita).
- **Un test casi vacío puede parecer completo.** "Llegadas = salidas + dentro" calculado solo con el log no puede fallar nunca. Comparar con una fuente independiente es lo que lo convierte en una comprobación.
- **El orden de los sorteos solo se ve cuando cambia.** Con la versión A, en 3 días con 30 boxes el orden de asignación coincide con el de llegada y varios tests no lo ven. Lo detectan los que fuerzan colas (otra plantilla) o un orden conocido (dos pacientes y un box).
- **Comprobar al final de cada escenario paga.** Los escenarios a mano pasan también las invariantes al terminar; por eso la versión B cayó en un test que no estaba en la predicción.
- **Medir antes de optimizar** (como en la tarea 2.2): la simulación cuesta 4 µs por evento y el log, 18. Si algún día hace falta velocidad, el sitio a mirar es el log, no SimPy.

**Pendiente para las tareas 3.4 y 3.5.** Regenerar la huella con una explicación en el commit. Las invariantes "nadie se cuela" y "desalojo" entran como entradas nuevas de `CHECKS`, y `patient_displaced` y las valoraciones interrumpidas, como aristas nuevas del autómata. La capacidad de médicos y enfermeras pasará a compararse con la plantilla vigente según `staffing_changed`.

### Tarea 3.4: prioridad y desalojo

**Qué se hizo**

- PR #22 (rama `feat/h3-prioridad`), abierto por Claude Code y fusionado por Pedro con *squash and merge*. Cuatro commits: contrato de SimPy, autómata y capacidad con desalojo, prioridad con desalojo y laboratorio, e invariantes nuevas con la prueba de estrés.
- `tests/test_simpy_contract.py` fija lo que hace SimPy 4.1.2, comprobado leyendo su código:
  - la clave `(priority, instante de la petición, not preempt)`, también con tuplas;
  - `PreemptiveResource` desaloja al usuario de clave mayor, también a un nivel 1 que llegó después;
  - la interrupción (`URGENT`) va antes que la concesión (`NORMAL`) en el mismo instante, aunque otros eventos del instante caben entre ambas;
  - salir del `with` cancela o libera la petición, y liberar a un usuario ya desalojado no falla;
  - solo se intenta conceder la petición que está a la cabeza de la cola.
- `resources.py`: `priority_key(nivel, llegada)`, `should_displace` (el nivel 1 pide con desalojo solo si algún box lo ocupa un nivel mayor) y `BoxNumbers`, que sabe quién ocupa cada box y traspasa el box del desalojado al nivel 1. Médicos como `PriorityResource`, boxes como `PreemptiveResource`; el triaje sigue FIFO.
- `patient.py`: la estancia es un estado (`_Stay`: etapa y tiempo pendiente) recorrido en un bucle. Cada `yield` hecho con box atrapa `Interrupt` según su etapa, y `patient_displaced` se emite en un único sitio. Las pruebas corren en un proceso de laboratorio propio.
- `invariants.py`: el autómata admite desalojos en cada estado con box y recuerda la etapa en los estados `waiting_box_*`. Dos invariantes nuevas, `nobody_jumps_the_queue` y `displacement`.
- La huella se regeneró a propósito y se comparó línea a línea con el log anterior: los médicos atienden por prioridad desde el minuto 594, y el ejemplo de 3 días tiene 3 desalojos.
- 763 tests rápidos en verde, y la suite completa con los `slow`.

**Conceptos**

- **La prioridad como tupla.** SimPy ordena por `(priority, instante de la petición, not preempt)`. Con `priority = (nivel, llegada)`, quien vuelve a pedir un recurso (reevaluación, vuelta tras un desalojo) se coloca por su llegada y no por cuándo pide. El instante de la petición solo desempataría si coincidieran nivel y llegada.
- **Cómo desaloja SimPy.** Una petición con `preempt=True` que no encuentra plaza mira al usuario de clave mayor y, si es menos prioritario, lo saca, le lanza `Interrupt` con la causa `Preempted` y le da la plaza al que llega, todo en la misma llamada. Solo se intenta la cabeza de la cola: por eso basta con decidir `preempt` al pedir.
- **Decidir con lo que ve SimPy.** Entre que SimPy concede un box y que el paciente emite `box_assigned` hay una ventana dentro del mismo instante. `should_displace` mira `boxes.users`, que es lo que SimPy usará para elegir a quién desaloja, y no el registro de números del motor.
- **Reanudar donde estaba.** La etapa avanza solo después de emitir su evento, y una interrupción solo puede llegar en un `yield`. Por eso ningún evento se pierde ni se duplica, y una valoración cortada vuelve con su mismo tipo y el tiempo pendiente.
- **Dos procesos por paciente.** El laboratorio corre aparte y dispara un evento al terminar. Un desalojo no lo detiene, y los resultados pueden llegar mientras el paciente espera box en la sala.
- **"Nadie se cuela" entre instantes.** Dentro de un mismo instante, el orden del fichero no es el orden en que SimPy concede los recursos. La invariante compara solo con quien esperaba desde un instante estrictamente anterior.

**Decisiones**

- Un nivel 1 nunca desaloja a otro nivel 1. Con la tupla sola, uno que llegó antes desalojaría a uno que llegó después; `should_displace` lo evita sin tocar el código interno de SimPy.
- El box del desalojado se traspasa al nivel 1 que lo desaloja, aunque en el mismo instante se libere otro con número menor.
- Si a un paciente lo desalojan entre la concesión y su reanudación, no ha emitido nada en el box: vuelve a pedirlo sin `patient_displaced`.
- Cualquier interrupción que no sea un desalojo de box lanza `RuntimeError`.
- Las tres decisiones de diseño (el nivel 1 que no desaloja a otro, el traspaso del box y el laboratorio como proceso propio) se añadieron a la especificación y a la decisión candidata 25.

**Resultados: espera media de box por nivel** (minutos desde `triage_completed` hasta el primer box, episodios que llegan tras 2 días de calentamiento, semilla 2026; "FIFO" es la misma ejecución sin prioridad ni desalojo)

| Configuración | Orden | Desalojos | Nivel 1 | Nivel 2 | Nivel 3 | Nivel 4 | Nivel 5 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `config/centro.toml`, 14 días | Prioridad | 4 | 0,0 | 0,5 | 0,8 | 6,8 | 15,1 |
| `config/centro.toml`, 14 días | FIFO | 0 | 3,1 | 3,2 | 3,2 | 3,6 | 3,8 |
| Estrés (24 boxes, 30 % de nivel 1), 4 días | Prioridad | 350 | 0,0 | 3,9 | 16,7 | 167,1 | 362,2 |
| Estrés (24 boxes, 30 % de nivel 1), 4 días | FIFO | 0 | 77,6 | 71,2 | 75,2 | 69,8 | 76,4 |

Con la configuración real, la prioridad apenas cambia la media (unos 3,5 min con FIFO), pero la reparte: el nivel 1 no espera y el nivel 5 espera cuatro veces más. Con el centro saturado, la diferencia es enorme, y el nivel 5 espera unas 6 horas. En `config/centro.toml` hubo 7 / 453 / 1.249 / 1.929 / 43 episodios por nivel. En estrés, los 350 desalojos se repartieron así: 233 en valoración, 60 en pruebas y 57 esperando médico. 85 pacientes fueron desalojados más de una vez. La versión FIFO da 1.684 y 1.244 violaciones de las invariantes nuevas.

**Comprobación con versiones incorrectas** (temporales; resultado del PR)

| Versión incorrecta | Predicción | Observado |
| --- | --- | --- |
| A. Clave solo por nivel | Fallan "mismo nivel" y "nadie se cuela" en estrés; el escenario de tres boxes pasa | Acertada, y además hay violaciones en "sin nivel 1" y en el ejemplo de 3 días: sin la llegada, el orden ya falla en las colas normales |
| B. Boxes FIFO, sin desalojo | Fallan los escenarios de desalojo y el estrés; pasan "sin nivel 1" y "dos niveles 1" | Acertada, salvo que "sin nivel 1" también falla: sin prioridad en los boxes se cuela cualquier nivel, no solo el 1 |
| C. El desalojado reinicia la valoración | Solo fallan los tests con instantes a mano | Exacta: fallan el escenario de tres boxes y el de dos desalojos; ninguna invariante lo ve |
| D. El nivel 1 pide siempre con desalojo | Falla "un nivel 1 no desaloja a otro"; probablemente el estrés | Falla el test a mano; el estrés pasa, porque con 24 boxes es rarísimo que todos los ocupen niveles 1 |
| E. Pruebas como `timeout` del paciente | Falla "desalojo durante las pruebas"; las invariantes y el estrés pasan | Acertada, y además falla el estrés: no por una invariante, sino por la comprobación de que algún resultado llega con el paciente fuera del box (0 frente a al menos 5) |

**Lecciones aprendidas**

- **Leer el código de la biblioteca y fijarlo con tests.** El contrato de SimPy hizo visibles dos detalles que el diseño no veía: solo se intenta la cabeza de la cola, y otros eventos del instante caben entre la interrupción y la concesión. De ahí salieron `should_displace` con `boxes.users` y el traspaso del box.
- **Las invariantes ven el orden, no las duraciones ni el origen.** Detectan A, B y D, pero no C (una valoración reiniciada) ni E (de dónde viene un evento). Para eso hacen falta los escenarios a mano.
- **Un caso raro se prueba provocándolo.** Con la configuración real hubo 4 desalojos en 14 días, y la versión D ni siquiera aparece en estrés. Solo los escenarios construidos y la prueba de estrés, con mínimos exigidos, ejercitan el desalojo de verdad.
- **Las comprobaciones de "no pasar en vacío" también detectan errores.** La versión E la detectó el control de que la prueba de estrés ejercita lo que dice ejercitar, no una invariante.
- **La prioridad no reduce la espera: la reparte.** La media casi no cambia, pero el nivel 1 deja de esperar a costa del 4 y el 5. Es un ejemplo de por qué los KPI de urgencias se miran por nivel.

**Pendiente para la tarea 3.5.** Regenerar otra vez la huella. Pasar la enfermería de triaje a `PriorityResource` para las reservas, y comparar la capacidad de médicos y enfermeras con la plantilla vigente según `staffing_changed`.

### Tarea 3.5: turnos y calentamiento

**Qué se hizo**

- PR #23 (rama `feat/h3-turnos`), abierto por Claude Code y fusionado por Pedro con *squash and merge*. Seis commits:
  - contrato de SimPy para cancelar y liberar reservas;
  - enfermería con prioridad y prioridad de reserva;
  - `warmup_days`;
  - calendario de turnos y reservas;
  - proceso de turnos con `staffing_changed`;
  - capacidad con la plantilla vigente.
- `tests/test_simpy_contract.py` fija cómo trata SimPy las peticiones creadas fuera de un `with`:
  - `cancel()` solo quita una petición que espera;
  - `release()` solo quita una concedida, y la plaza pasa al siguiente cuando SimPy procesa la liberación;
  - `release()` de una petición que espera no hace nada y la deja en la cola: una **reserva fantasma**.
- `resources.py`: la enfermería de triaje pasa a `PriorityResource`. Todos los pacientes piden con `TRIAGE_PRIORITY = (1, 0.0)`, así que el triaje sigue en orden de llegada; la huella no cambió en ese paso. `RESERVATION_PRIORITY = (0, 0.0)` es un "nivel 0" que va antes que cualquier paciente y nunca desaloja.
- `engine/shifts.py`:
  - `shift_at`: el turno de cada instante; la noche cruza la medianoche y el minuto 0 cae en ella;
  - `shift_changes`: los inicios de turno dentro del horizonte;
  - `Reservations`: al bajar crea reservas que esperan a que alguien termine; al subir cancela primero las que esperan y después libera las concedidas;
  - `start_shifts`: pone la plantilla del minuto 0 y arranca el proceso de turnos.
- `simulate_ed` recibe `warmup_days` (2 por defecto, entero de 0 a días − 1) y lo devuelve en el resultado. El log no se recorta.
- `check_capacity` compara médicos y enfermeras con la plantilla vigente leída de `staffing_changed`, no con la configuración.

**Conceptos**

- **Reservas.** La capacidad de un recurso de SimPy no cambia: el pool se crea con la plantilla máxima y las plazas que sobran en un turno las ocupan peticiones del propio motor. Una reserva no desaloja: espera a que un profesional termine. Es lo que pasa en la realidad: el médico saliente acaba lo que tiene entre manos.
- **La plantilla vigente cuenta las reservas en espera.** A las 22 h la plantilla ya es 7, aunque las 5 reservas aún esperen, porque se quedarán con las 5 primeras plazas que se liberen.
- **Cancelar frente a liberar.** Una reserva que espera se cancela y una concedida se libera. Liberar una que espera no hace nada, y más tarde ocuparía una plaza: la plantilla se quedaría corta sin que ninguna invariante lo viera.
- **El orden por construcción.** Los `staffing_changed` del minuto 0 se emiten antes de `env.run`, y los `timeout` de todos los cambios se crean en el minuto 0. Con los números de programación más bajos, cada cambio de turno es el primer evento de su instante, y la plaza de un médico que termina justo a las 22:00 va a la reserva.
- **Comprobar los inicios, no los ocupados.** Tras una bajada puede haber más ocupados que la plantilla, porque nadie es interrumpido. La invariante comprueba que ninguna atención empieza con el pool ya ocupado al nivel de la plantilla vigente.
- **Un log que se explica solo.** El `staffing_changed` del minuto 0 con `anterior` 0 hace que el log describa la plantilla desde el principio sin consultar la configuración: es el principio del *event sourcing*.

**Decisiones**

- Los turnos van en un módulo propio: dependen del calendario y se prueban sin SimPy.
- El `staffing_changed` del minuto 0 se añadió a la especificación. Después solo se emite si la plantilla cambia: a las 15 h, de 12 a 12, no hay evento.
- El `staffing_changed` se emite antes de aplicar el cambio, para que las atenciones que permite una subida vayan detrás del evento que las permite.
- `check_capacity` comprueba también que el `anterior` de cada cambio es la plantilla vigente, y que ninguna atención empieza antes del primer `staffing_changed` de su pool.
- `Reservations.set_staff` con una plantilla fuera de 1..capacidad lanza `RuntimeError`: sería un fallo del motor, no una entrada inválida.

**Resultados**

- Huella regenerada a propósito y comparada línea a línea (centro de ejemplo, 3 días, semilla 2026):
  - de 12.198 a 12.173 eventos, 14 de ellos `staffing_changed` (2 en el minuto 0 y 2 a las 8 y a las 22 h de cada día);
  - la primera diferencia llega en el minuto 121: con 7 médicos de noche, un paciente empieza su valoración 1 minuto más tarde;
  - cambian 409 episodios, sobre todo entre las 22 y la 1 h;
  - quedan dentro 22 pacientes en lugar de 15, con las mismas llegadas y los mismos 3 desalojos.
- Escenarios a mano con instantes exactos: bajada de 3 a 1 médicos con todos ocupados (terminan en 1330, 1340 y 1350, ninguno interrumpido), subida con cola (3 ocupados tras el minuto 480) y subida con reservas sin conceder (4 ocupados en el minuto 720).

855 tests rápidos y 10 `slow` en verde. Cero violaciones en 14 días con semilla 2026, con `config/centro.toml` (49.843 eventos) y con cambios de plantilla grandes (médicos 12/4/1 y enfermeras 3/1/1; 41.289 eventos).

**Turnos frente a plantilla máxima fija** (`config/centro.toml`, 7 días, semilla 2026; espera media de médico según el turno en que empieza la espera)

| Tramo | Con turnos | Con 12 médicos y 3 enfermeras fijos |
| --- | --- | --- |
| Mañana | 2,66 min | 2,66 min |
| Tarde | 2,36 min | 2,34 min |
| Noche | 7,15 min | 0,36 min |
| Primera hora de la noche (22–23 h) | 18,4 min | 1,2 min |

Lo que anticipó la curva de carga ofrecida: la noche empieza justa. De 22 a 23 h hay de media 6,3 médicos ocupados con plantilla 7, cuando con 12 fijos serían 8,3, y la espera de médico se multiplica por 15. Tras la bajada de las 22 h quedaban esperando 5, 5, 4 y 2 reservas de médico de lunes a jueves, y ninguna el fin de semana. En ninguna de las 14 subidas quedaba una reserva sin conceder: con la configuración real, el error B no se notaría nunca.

**Calentamiento** (20 semillas, 14 días; horas cuyo censo medio queda fuera del IC al 99 % con Bonferroni entre las 24 horas)

| Día | Frente a la media de los días 7–13 | Frente al mismo día de la semana (d + 7) |
| --- | --- | --- |
| 0 (lunes) | 0, 1 y 2 h | 0 y 1 h |
| 1 (martes) | Ninguna | Ninguna |
| 2 (miércoles) | Ninguna | Ninguna |
| 3 (jueves) | Ninguna | Ninguna |

Bastan 2 días, con margen: el arranque vacío solo se nota en las primeras horas del día 0 (a las 0 h, un censo medio de 4,8 frente a 21,6). Comparar con la media de la semana mezcla el efecto del día de la semana: el lunes de referencia (día 7) tiene un censo medio de 27,6, frente a 21,4 de la semana.

**Corrección durante la tarea.** El plan decía que crear los `timeout` de turno al principio hacía que un médico que termina justo a las 22:00 cediera la plaza a la reserva. La versión ingenua también lo cumple, porque la plaza se reparte al procesarse la liberación, que va detrás del cambio. Se añadió un test que sí falla con la versión ingenua: cada cambio de turno es el primer evento de su instante.

**Comprobación con versiones incorrectas** (temporales; resultado del PR)

| Versión incorrecta | Predicción | Observado |
| --- | --- | --- |
| A. `RESERVATION_PRIORITY = (3, 0.0)` | Fallan las bajadas, la capacidad en los cambios grandes y la huella; pasan la subida y el resto | 14 fallos: los predichos y, además, el de la constante y uno de subida de `Reservations`, donde los pacientes piden con `TRIAGE_PRIORITY`, que ahora va por delante de la reserva |
| B. Al subir, solo liberar las concedidas | Solo falla la subida con reservas sin conceder; pasan las invariantes, las ejecuciones reales y la huella | 3 fallos: ese test y dos de `Reservations` (3 ocupados a las 12:00 en lugar de 4). Falló una parte: la invariante del `anterior` detecta un `staffing_changed` falso de 2 a 4 a las 22:00, que emite la contabilidad desincronizada |
| C. El minuto 0 con la plantilla de mañana | Fallan la lista de `staffing_changed`, la huella y la subida con reservas; pasan las invariantes | 4 fallos: los predichos y la subida con cola, que también empieza de noche. Ninguna invariante lo detecta |

**Lecciones aprendidas**

- **Un error por defecto no lo ve ninguna invariante de máximos.** Una plantilla que se queda corta (la reserva fantasma) no viola ninguna regla de capacidad. Solo la detecta un escenario con un resultado conocido: cuántos ocupados debe haber justo después de una subida.
- **La huella también sirve para probar que algo no cambia.** Al pasar la enfermería a `PriorityResource`, que la huella siguiera igual demostró que el triaje seguía siendo FIFO.
- **El orden de lo simultáneo se puede diseñar.** En lugar de depender de cómo ordena SimPy los empates, el motor coloca sus eventos donde quiere: antes de `env.run` y con los `timeout` creados al principio.

* **Un test debe fallar con la versión ingenua, o no prueba la decisión.** El test de "la plaza de las 22:00 va a la reserva" pasaba también sin crear los `timeout` al principio; el que de verdad la protege comprueba que el cambio de turno es el primer evento de su instante.
* **Una comprobación de coherencia puede atrapar errores de otro tipo.** La regla del `anterior`, añadida para detectar un motor que anuncia mal la plantilla, detectó también la contabilidad desincronizada de la versión B.
* **Comparar con lo que se parece de verdad.** El calentamiento se mide frente al mismo día de la semana: frente a la media de la semana, el efecto del lunes se confundía con el del arranque vacío.
* **Medir si un error importa en la práctica.** La versión B es un error real, pero con la configuración actual nunca quedan reservas sin conceder en una subida: solo un escenario construido a mano lo ejercita.

**Pendiente para la tarea 3.6.** Las métricas usarán la ventana \[calentamiento, horizonte\] con `warmup_days` del resultado.

### Tarea 3.6: estado, métricas y validación del motor

**Qué se hizo**

- PR #24 (rama `feat/h3-validacion`), abierto por Claude Code y fusionado por Pedro con *squash and merge*. Seis commits. Es la primera tarea con el nuevo modo de trabajo: Claude Code implementó la tarea completa tras aprobar el plan, y Pedro revisó solo el PR. El primer commit actualizó `CLAUDE.md` con ese modo.
- `engine/analysis.py`, funciones puras que pliegan el log:
  - `episode_table`: una fila por episodio con sus instantes y cinco esperas (triaje, box sumando las vueltas, médico, médico inicial y puerta-médico);
  - `step_curves`: censo, colas, ocupados y plantilla vigente como escaleras;
  - `window_metrics`: métricas por nivel y ocupación por pool y turno, con las reglas de recorte de `mm1_metrics`;
  - `little_laws`, `utilization_identities` y `analyze_run`, que lo junta todo.
- `engine/validation.py`: `check_mg1`, `check_infinite_server` (Mₜ/G/∞ y capacidad infinita), `check_operational_laws` (invariantes, Little y utilización en 28 días), `check_more_doctors` y `validate_engine`. Cada réplica se simula en memoria, se reduce a números y se descarta.
- 57 tests rápidos nuevos (912 en total, unos 23 s) y tests `slow` de esta tarea por 130 s: una sola ejecución de `validate_engine` compartida por cuatro tests y tres pruebas de potencia.

**Conceptos**

- **Coherente frente a correcto.** Las invariantes comprueban que el log no se contradice. La validación comprueba que sus números coinciden con la teoría donde la hay.
- **Dos tipos de medias desde el log.** Por episodio (esperas y estancia de los que llegan en la ventana y terminan) y en el tiempo (área bajo una escalera recortada a la ventana), como en el hito 1.
- **Leyes operacionales.** Little (L = λ·W) vale sin suponer distribuciones; en una ventana finita es aproximada por los recortes. La identidad de utilización (área de ocupados = suma de las duraciones) es exacta: compara dos caminos de cálculo independientes. Para la cola de box, Little necesita la espera total, sumando las vueltas tras un desalojo.
- **M/G/1 dentro del motor.** El triaje no depende de lo que pasa después: con λ constante y una enfermera es exactamente una M/G/1, y Pollaczek–Khinchine da la teoría. La variabilidad del servicio, y no solo su media, produce espera: con servicio exponencial de la misma media, Wq sube un 49 %.
- **Mₜ/G/∞.** Con capacidad infinita, el censo en cada instante es una Poisson de media m(t) = ∫ λ(s) · P(estancia > t − s) ds: la curva de carga ofrecida de la sesión conceptual, convertida en test. m(t) se calcula con la λ(t) del hito 2 y una muestra independiente de estancias.
- **Números aleatorios comunes.** Con la misma semilla, los pacientes son los mismos con más médicos, y la diferencia emparejada ve un efecto de 3,7 min con solo 10 réplicas.

**Decisiones**

- Cinco esperas por episodio. `doctor_wait` suma todas las esperas con box (inicial, reevaluación y reanudaciones) y es la de "más médicos", con las mismas reglas que "nadie se cuela". `puerta_medico` (de la llegada a la primera valoración) es el KPI de los tiempos máximos de Manchester.
- Las esperas que suman toda la estancia valen `None` hasta la salida: no se inventa nada.
- `ValidationResult`, `ALPHA` y `summarize` del hito 2 se reutilizan. La teoría siempre sale de la configuración, y un test lo comprueba cambiando la mediana del triaje.
- La condición extrema de capacidad infinita reutiliza las réplicas de la Mₜ/G/∞, sin simular nada más.
- La muestra de 200.000 estancias está justificada: su error en m(t) es como mucho el 5,4 % de la semianchura del IC de cada hora (con 20.000 sería un 17 %).
- Potencia de la M/G/1 con 10 réplicas y no 5. La de la Mₜ/G/∞, con 5.

**Resultados: validación** (`config/centro.toml`, `config/llegadas.toml`, semilla 2026; 91,7 s)

| Comprobación | Valor | IC o tolerancia | Objetivo | Resultado |
| --- | --- | --- | --- | --- |
| Invariantes (28 días) | 0 violaciones | — | 0 | Pasa |
| Little: sistema / triaje / box | 0,39 % / 0,15 % / 0,23 % | ≤ 2 % | — | Pasa |
| Utilización: enfermería / médicos / boxes | 0 / 0 / 0 | ≤ 10⁻⁹ | — | Pasa |
| M/G/1, Wq | 12,64 min | \[11,71; 13,57\] al 99,67 % | 13,10 | Pasa |
| M/G/1, ρ | 0,7725 | \[0,7639; 0,7811\] | 0,7717 | Pasa |
| M/G/1, Lq | 1,688 | \[1,554; 1,822\] | 1,747 | Pasa |
| Mₜ/G/∞ | 0 horas fuera de 24 | IC al 99,958 % por hora | m(t) | Pasa |
| Capacidad infinita | 0 episodios inexactos (20 réplicas) | — | 0 | Pasa |
| Más médicos (+2 por turno) | −3,70 min | \[−4,56; −2,83\] al 99 % | < 0 y mismos pacientes | Pasa |

El censo medio por hora sigue a m(t) en las 24 horas: de unos 5,4 pacientes a las 6 h a 28 a las 12 h, con la segunda joroba de la tarde.

**Resultados: el centro provisional** (14 días, 2 de calentamiento, semilla 2026; 3.681 llegadas en la ventana, 306,8 al día; censo medio 18,98; media / p90 en minutos)

| Nivel | n | Triaje | Box | Médico | Puerta-médico | Estancia |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 7 | 2,2 / 6,4 | 0,0 / 0,0 | 1,1 / 2,8 | 9,4 / 16,4 | 115,0 / 145,3 |
| 2 | 451 | 1,4 / 5,1 | 0,5 / 1,9 | 1,2 / 3,9 | 8,1 / 15,9 | 108,0 / 185,5 |
| 3 | 1.242 | 1,4 / 4,7 | 0,8 / 2,4 | 1,7 / 5,5 | 9,0 / 17,6 | 97,5 / 182,6 |
| 4 | 1.929 | 1,5 / 5,3 | 6,8 / 23,6 | 4,6 / 15,2 | 17,9 / 48,1 | 78,0 / 161,5 |
| 5 | 42 | 2,0 / 6,5 | 15,3 / 15,0 | 18,0 / 55,4 | 36,9 / 132,8 | 79,5 / 180,2 |
| Total | 3.671 | 1,5 / 5,2 | 4,1 / 6,6 | 3,3 / 8,9 | 13,9 / 28,8 | 88,4 / 173,6 |

| Pool | Mañana | Tarde | Noche |
| --- | --- | --- | --- |
| Enfermería de triaje | 58,4 % | 52,9 % | 30,0 % |
| Médicos | 70,0 % | 73,3 % | 53,2 % |
| Boxes | 69,1 % | 72,8 % | 33,3 % |

La espera de box del nivel 5 tiene una media mayor que su p90 (15,3 frente a 15,0): con 42 episodios, unos pocos esperan mucho y tiran de la media.

**Comprobación con versiones incorrectas** (temporales; resultado del PR)

| Versión incorrecta | Predicción | Observado |
| --- | --- | --- |
| A. Little con W de todos los que terminan, también los que llegaron antes de la ventana | `validate_engine` pasa (las fronteras de medianoche se compensan); lo ve el test a mano | Exacta: solo falla el test a mano con recorte |
| B. Medias en el tiempo con el área de todo el log dividida por la ventana | Fallan las tres Little (+7,7 %) y la M/G/1 en ρ y Lq | En parte: fallan Little del sistema y del triaje y ρ, pero no Little de la cola de box (1,3 %) ni Lq |
| C. Estancia sin el tiempo de las pruebas | La Mₜ/G/∞ falla en las 24 horas; nada más | Exacta: m = 13,45 a las 12 h frente a un censo de 28,39 |

**Lecciones aprendidas**

- **La potencia no depende solo del tamaño del efecto.** Con 5 réplicas, un efecto del 49 % en Wq no se veía: con ρ = 0,77 la cola tiene memoria larga y la espera media varía mucho entre réplicas, y la t de Student con 4 grados de libertad y Bonferroni vale 6,25 (frente a 3,95 con 9). Alargar las réplicas no lo arreglaba. La recomendación de 5 réplicas en la revisión del plan fue un error, y lo detectó la medida.
- **Un sesgo multiplicativo solo lo ve la comprobación con el IC más estrecho para esa magnitud.** La versión B pasó en Lq (IC de ±8 %) y falló en ρ (±1 %). Little, con tolerancia fija, depende de cuánto pese el calentamiento en cada curva: la cola de box casi no acumula en los dos primeros días.
- **Una comprobación puede pasar con un error que se compensa.** Con la versión A, los recortes de entrada y de salida casi se anulan a medianoche. Solo un test a mano con un episodio que cruza la frontera lo detecta.
- **El tamaño de una muestra auxiliar se justifica con la anchura del IC**, no a ojo: el error que introduce debe ser pequeño frente a la tolerancia de la prueba.
- **Revisar solo el PR funciona si su descripción explica cada decisión y lo que cambió respecto al plan.** Las preguntas durante la implementación (la potencia) siguieron llegando cuando hacían falta.

**Hallazgos del modelo para el hito 4**

- **El nivel 1 tarda 9,4 min de media hasta el médico, frente al "inmediato" de Manchester.** El triaje es FIFO para todos y dura unos 6 minutos; en la realidad un crítico entra directo. El hito 4 debe decidir si el nivel 1 se salta la cola de triaje o tiene un triaje más corto.
- **El centro provisional está holgado.** Una estancia media de 88 minutos, ocupaciones del 70 % de día y tiempos puerta-médico muy por debajo de los máximos de Manchester en los niveles 3 a 5 se quedan cortos frente a un servicio español real. Es lo que calibrarán los hitos 4 (duraciones y plantilla) y 5 (boarding).

**Deuda para el cierre (tarea 3.9).** Los ayudantes privados copiados de `arrivals/` (`_check_number`, `_interval_result`, `_check_count`) y los nuevos `_all_of` y `_tolerance_result` deberían ir a un módulo común de validación. `_time_in_window` está duplicada respecto a `queueing/mm1.py`. El docstring de `stay_sample` dice "streams 1 to 4" de `child_streams(seed, 4)`, que son los de índices 0 a 3.

### Tarea 3.7: CLI `edsim motor simular` y `edsim motor validar`

**Qué se hizo**

- PR #25 (rama `feat/h3-cli`), abierto por Claude Code y fusionado por Pedro con *squash and merge*. Cinco commits: límites públicos y ejecución larga; resumen, tabla y CSV; gráficas; CLI; y un ajuste de `esperas_por_nivel.png` hecho tras ver la gráfica con los datos reales.
- `engine/report.py`, sin argparse, para que lo reutilice el notebook:
  - `format_run_summary`: pacientes en todo el log, llegadas en la ventana, esperas y estancia por nivel (media / p90), ocupación por pool y turno, Little e invariantes;
  - `format_engine_validation`: la tabla en español con los niveles de la especificación (1, 2, 3a, 3b, 4), los tres IC de la M/G/1 y, solo si las hay, las horas de la Mₜ/G/∞ fuera de su IC;
  - los dos CSV del ground truth;
  - cuatro gráficas que devuelven la figura.
- `cli.py`: subcomando `motor` con `simular` y `validar`, códigos de salida 0, 1 y 2.
- `engine.check_horizon` y `validation.check_engine_validation_counts`: límites públicos que comprueban la CLI y el paquete antes de crear ficheros. `validate_engine` guarda en `long_run` el análisis de la ejecución larga, sin los eventos y con los mismos resultados.
- Corregido el docstring de `stay_sample`.
- 974 tests rápidos; la suite completa, 992 tests en 5 min 25 s.

**Conceptos**

- **CLI fina.** La CLI lee argumentos, llama al paquete y escribe; la presentación vive en `report.py` y se prueba sin terminal.
- **Errores de uso antes de crear nada.** Los límites de días, calentamiento y réplicas se comprobaban dentro de `simulate_ed` y `validate_engine`, cuando el directorio ya estaría creado o el aviso de 90 s ya impreso. Al hacerlos públicos, la CLI los comprueba en el orden `--salida`, configuraciones, límites, cabecera y `mkdir`.
- **Event sourcing también en la CLI.** `simular` escribe el log, lo cierra y lo vuelve a leer con `read_events`. El resumen y las invariantes describen exactamente el fichero que recibirá el laboratorio, y cada ejecución comprueba la ida y vuelta.
- **Tests rápidos para un comando lento.** Los tests de `validar` sustituyen `validate_engine` por un resultado pequeño construido a mano (un *fixture* de sesión que solo se construye si un test lo pide).

**Decisiones**

- Releer el fichero en lugar de guardar los eventos también en memoria: cuesta 0,58 s de 5,3 s. Ningún test distingue las dos opciones; es una decisión de diseño.
- Columnas de parámetros en cada fila de los CSV: centro, huella del centro, llegadas, huella de las llegadas, días, calentamiento, semilla y `run_id`. Se añadió el calentamiento, que no estaba pedido, porque sin él no se sabe qué ventana usa el resumen. Los floats van con `repr` y se leen bit a bit.
- En el CSV de episodios, `destino` va como `alta` o `ingreso`, igual que en el log.
- Los criterios de la tabla se escriben en español a partir de las constantes, no traduciendo el texto inglés.
- La banda de `mg1.png` es el mismo IC que imprime la tabla, y la M/M/1 de la misma media (19,56 min) va en gris como referencia.
- `--run-id` vacío se rechaza en argparse, porque `EventLog` solo lo detectaría con el fichero ya abierto.

**Resultados**

| Comando | Tiempo | Desglose |
| --- | --- | --- |
| `motor simular` (14 días, 49.843 eventos, 18,3 MB) | 5,28 s (185 MB) | Simular y escribir 1,51 s; releer 0,58 s; `analyze_run` 0,12 s; invariantes 0,07 s; importaciones 1,07 s |
| `motor validar` (20 réplicas) | 103,4 s (327 MB) | Pasan las 11 comprobaciones |

Las cuatro gráficas:

- **`censo.png`**: el ciclo diario (2–5 pacientes de madrugada, picos a mediodía y por la tarde). Los boxes ocupados se aplanan en 30 mientras el censo sigue subiendo, hasta 52 algunos días: son los pacientes que esperan triaje o box.
- **`esperas_por_nivel.png`**: la prioridad reparte la espera, y los niveles 4 y 5 cargan con ella.
- **`mg1.png`**: las 20 Wq entre 10,5 y 14,8 min, la banda del IC y Pollaczek–Khinchine (13,10) dentro, con la M/M/1 (19,56) muy por encima. Es el factor (1 + CV²)/2.
- **`censo_por_hora.png`**: m(t) pasa por las 24 barras de error.

**Comprobación con versiones incorrectas** (temporales; resultado del PR)

| Versión incorrecta | Predicción | Observado |
| --- | --- | --- |
| A. CSV con 4 decimales | Fallan solo los dos tests de CSV | Exacta |
| B. `simular` devuelve 0 con violaciones | Falla solo el test del código 1 | Exacta |
| C. `mkdir` antes de `check_horizon` | Fallan los tres errores de uso de días y calentamiento | Exacta |
| D. La línea de P–K dibuja la M/M/1 | Falla solo el test de `mg1.png` | Exacta |
| E. Resumen desde un `MemorySink` sin releer | No falla nada | Exacta: la decisión es de diseño, no de corrección |

**Lecciones aprendidas**

- **En una capa fina, los tests miran justo la interfaz,** y las predicciones salen exactas. Lo valioso aquí es el orden de las comprobaciones y que ningún error de uso deje ficheros a medias.
- **Mirar las gráficas reales.** El solape de etiquetas y el contorno que caía a 0 al final de la escalera solo se vieron al abrir los PNG generados con los datos de verdad.
- **Una referencia calculada por otro camino.** El test de la M/M/1 en `mg1.png` usa P–K con el segundo momento de una exponencial, sin copiar la fórmula del código: si los dos caminos coinciden, ninguno está mal.

**Hallazgo para el hito 4: el centro "holgado" se satura en los días punta.** En la ejecución larga de 28 días, la espera media de box del nivel 5 es de 92 min con un p90 de 338. Casi todos los días los niveles 4 y 5 esperan 1–2 min, pero tres días suben a 50, 64 y 120 min (el de 120 es el lunes 26 de enero). Es la lección del hito 1 en el motor: cerca de la saturación las esperas crecen de forma no lineal, y las medias de ocupación (70 %) esconden los días malos. Para calibrar hay que mirar el porcentaje de días fuera de objetivo, como pide el diseño.

**Pendiente, que se resuelve al inicio de la tarea 3.8.**

- `test_validar_motor_de_verdad` repite `validate_engine` completo (110 s) y sube el CI de 3,5 a 5,5 min. Lo que comprueba de la CLI ya lo cubren los tests rápidos. La propuesta es un *fixture* de sesión con el `validate_engine` real, compartido por los tests lentos de validación y por el de la CLI.
- El aviso de `validar` dice "unos 90 s" y midió 103 s: mejor "unos 2 minutos".

### Tarea 3.8: notebook de exploración del motor

**Qué se hizo**

PR #26 (rama `feat/h3-notebook`), abierto por Claude Code y fusionado por Pedro con squash and merge. Siete commits: los pendientes de la tarea 3.7; medias por día y hora, esperas emparejadas, carga por pool y calentamiento; escenarios didácticos; recorrido de un episodio y Gantt; días fuera de los máximos de Manchester; un test añadido por la versión C; y el notebook.

- **Pendientes de la 3.7.** Un *fixture* de sesión, `engine_validation_real` en `conftest.py`, ejecuta una vez el `validate_engine` real (`config/centro.toml`, `config/llegadas.toml`, semilla 2026). Lo comparten los tests slow de validación y `test_validar_motor_de_verdad`. Este último lo recibe con `monkeypatch` después de comprobar que la CLI pide la misma validación (centro, perfil, semilla y 20 réplicas). El aviso de `validar` dice "unos 2 minutos".
- `engine/scenarios.py`, con el patrón de `arrivals/faults.py`: `three_boxes(center)` y `exponential_triage`, que salen de los tests, y `run_scenario`.
- `engine/timeline.py`: `episode_timeline` (los estados de un episodio, uniendo tramos iguales consecutivos) y `gantt` (carriles de boxes y de médicos).
- `engine/targets.py`: `MANCHESTER_MAX_WAIT = (0, 10, 60, 120, 240)` con su fuente, `COMPLIANCE_TARGET = 0.90`, `daily_waits` y `manchester_compliance`.
- En `analysis.py`, `hourly_means_by_day`, `daily_means` y `paired_waits`. En `validation.py`, `draws_sample`, `offered_load_by_pool`, `census_by_day_and_hour` y `check_warmup`.
- `notebooks/03_motor_exploracion.ipynb`, con 12 secciones: 2 min 52 s en modo normal y 15 s en modo rápido.
- 1.041 tests (antes 992). La suite completa en local baja de 5 min 28 s a 4 min 49 s, porque `validate_engine` se ejecuta una vez en lugar de dos.

**Conceptos**

- **Reparto de intervalos en carriles.** Asignar cada valoración, en orden de inicio, al carril libre de número más bajo usa el mínimo de carriles posible, que es el máximo de valoraciones simultáneas. Un carril queda libre si su última valoración termina antes o en el mismo minuto en que empieza la nueva. Los carriles no son médicos concretos, porque los pools son anónimos.
- **Lo que se sabía en t.** Plegar solo el prefijo del log hasta t da el estado en ese instante, sin mirar el futuro: el lunes 12 a las 12:00, censo 38, 7 esperando triaje y 12 de 12 médicos ocupados. Es la base de las *features* sin *data leakage* del laboratorio.
- **Carga ofrecida por pool.** m(t) de cada recurso con la misma convolución que la Mₜ/G/∞. Sus máximos (30,4 boxes, 13,0 médicos y 2,5 enfermeras) reproducen la tabla de dimensionado de la sesión conceptual.
- **No linealidad cerca de la saturación.** El mismo médico de menos por la mañana suma 19,3 min de espera el lunes y 3,2 el domingo. Es el ρ/(1 − ρ) de la M/M/1 dentro del motor: la plantilla se dimensiona con el día punta, no con el medio.
- **Calentamiento con d + 7.** Cada hora del día d se compara con la misma hora del mismo día de la semana siguiente, emparejada por semilla, con Bonferroni entre las 24 horas.
- **Porcentaje de días fuera de objetivo.** Un día está fuera para un nivel si menos del 90 % de sus pacientes llega al médico dentro del máximo de Manchester. Los días sin pacientes del nivel no cuentan, y la tabla dice con cuántos días se calcula cada nivel.
- **Números aleatorios comunes paciente a paciente.** Las esperas de un mismo paciente en las dos ejecuciones tienen una correlación de 0,56, y emparejar reduce la varianza de la diferencia de 102,5 a 71,5. Unos pocos pacientes esperan más con más médicos: el sistema no es monótono paciente a paciente.

**Decisiones**

- Todo lo que calcula el notebook va al paquete con tests. Las gráficas nuevas se dibujan en el notebook con los colores de `report.py`, y los niveles con los de Manchester (rojo, naranja, amarillo, verde y azul).
- Cumplimiento: llegar justo en el máximo cumple; el día de un episodio es el de su llegada, con la regla de `completed_in_window`; objetivo del 90 %, decisión de Pedro en la revisión del plan.
- Las refactorizaciones de `analysis.py` y `validation.py` dan los mismos bits que antes, y un test lo comprueba contra la fórmula anterior: la Mₜ/G/∞ usa `hourly_means_by_day`, `stay_sample` usa `draws_sample` y `offered_load_by_pool` comparte la convolución de `offered_load`.
- `paired_waits` empareja por `episode_id` y rechaza dos ejecuciones con pacientes distintos.
- La ejecución principal dura 9 días (2 de calentamiento y una semana) en lugar de 14. El mes de las secciones 6, 8 y 9 es una sola ejecución: la larga de `validate_engine` (hijo 2 de 2026), la del hallazgo de la tarea 3.7.
- Añadido en la revisión del plan: la sección 6 muestra la diferencia emparejada en la mañana de cada día de la semana, no solo el lunes.

**Resultados: ejecución principal** (9 días, 2 de calentamiento, semilla 2026)

- 2.885 pacientes y 32.329 eventos; 2.127 llegadas en la ventana, Little del sistema al 1,22 % y 0 violaciones.
- EP-000759 (nivel 4, con pruebas): triaje 9,6 min, espera de médico 31,6, valoración 11,9, pruebas 60,0 y reevaluación 12,0.
- Gantt del lunes de 8 a 15 h: 23,8 boxes y 9,7 médicos ocupados de media, en 12 carriles de médico, igual a la plantilla.

**Resultados: un médico menos en el turno de mañana** (12 → 11, 28 días, 8.825 pacientes emparejados)

El lunes 12 de 8 a 15 h, el puerta-médico medio pasa de 29,8 a 46,9 min. Diferencia emparejada media del puerta-médico por la mañana:

| Día | lun | mar | mié | jue | vie | sáb | dom |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Minutos | +19,3 | +7,2 | +9,6 | +5,7 | +4,5 | +3,5 | +3,2 |

**Resultados: calentamiento, días punta, validación y números aleatorios comunes**

- Calentamiento (20 semillas de 11 días): solo quedan fuera las horas 0, 1 y 2 del día 0 (censo de 4,5 frente a 16,9), igual que en la tarea 3.5.
- Días punta (ejecución larga de 28 días): ocupación media de boxes del 64 %. Los peores días son el lunes 26 (espera de box del nivel 5 de 572 min, ocupación del 74 %), el miércoles 14 (336 min, 69 %) y el jueves 22 (235 min, 69 %).
- Validación: quitar un solo `box_assigned` produce 2.515 violaciones. La M/G/1 con 20 réplicas da Wq 13,12 \[12,07; 14,18\] y pasa; con triaje exponencial, 19,03 \[15,74; 22,33\] y falla, como debe.
- Números aleatorios comunes (+2 médicos): 2.110 pacientes emparejados, espera de médico de 3,20 a 0,66 min; 743 esperan menos, 1.311 igual y 56 más. `check_more_doctors` con 10 pares: −3,34 \[−4,01; −2,67\].

| Nivel | 1 | 2 | 3 | 4 | 5 |
| --- | --- | --- | --- | --- | --- |
| Días fuera de objetivo | 17 de 17 | 25 de 26 | 0 de 26 | 3 de 26 | 8 de 26 |
| % | 100 | 96 | 0 | 12 | 31 |

**Comprobación con versiones incorrectas** (temporales; resultado del PR)

| Versión incorrecta | Predicción | Observado |
| --- | --- | --- |
| A. Carril libre solo si la última valoración termina antes del inicio ("<" en lugar de "≤") | Fallan los carriles de tres boxes y "carriles = máximo de médicos" | Exacta: 2 fallos |
| B. Cumplimiento con "<" en lugar de "≤" | Falla solo "justo en el máximo" | Exacta |
| C. `paired_waits` empareja por posición | Falla "el que sigue dentro" | No falló: el episodio que seguía dentro era el último y la posición coincidía. Se añadió un test con el primero dentro, y entonces falla |
| D. `hourly_means_by_day` traspuesta | Fallan la escalera por día, la igualdad con la fórmula anterior y la forma | En parte: 2 fallos. La forma no, porque la versión conservaba (días, 24) con `.T`; la escalera tampoco, porque con un solo día no cambia nada |
| E. Carga de médicos sin la reevaluación | Falla solo la carga a mano | Exacta |

**Lecciones aprendidas**

- **Un test puede pasar por casualidad.** Con la versión C, el test pasaba porque el caso elegido coincidía por posición y por episodio. La versión incorrecta no se arregló cambiando la predicción, sino con el test que faltaba.
- **Un caso degenerado no ve el error.** Una trasposición no se nota con un solo día ni comprobando solo la forma. Los tests de forma necesitan datos en los que el error cambie algo.
- **La predicción del escenario a mano también se revisa.** El Gantt de tres boxes tiene 3 carriles y no 4: P3 reanuda en el carril que libera P1 a los 65 min. El test se corrigió razonando los instantes, no ajustándolo al resultado.
- **Mirar las gráficas con datos reales.** De las 16 gráficas, una tenía un título que contradecía los datos (sección 10). Ningún test lo habría visto.
- **Medir en condiciones comparables.** La mejora local parecía menor porque la máquina iba cargada: tests sin cambios tardaban un 40 % más. El ahorro real es una ejecución de `validate_engine`, unos 100 s.

**Hallazgos del modelo para el hito 4**

- **El nivel 2 queda fuera 25 de 26 días.** Su puerta-médico medio es de 8,7 min, con unos 6 de triaje FIFO dentro. Antes de dar el modelo por malo, el hito 4 debe decidir desde cuándo cuenta el reloj de Manchester: muchos indicadores de urgencias en España lo miden desde el triaje, no desde la llegada.
- **El nivel 1 queda fuera todos los días**, como se vio en la tarea 3.6.
- **Los niveles 4 y 5 esperan horas en unos pocos días punta** con una ocupación media del 64 %: lo que hay que calibrar es el porcentaje de días fuera de objetivo, no la media.

**Deuda menor para el cierre (tarea 3.9)**

- Sección 9: contar las violaciones del log roto por comprobación, para ver cuáles saltan.
- Sección 8: el texto cita días y porcentajes de la ejecución normal; debe decirlo, porque en modo rápido no coinciden con la gráfica.

### Tarea 3.9: cierre del hito

**Qué se hizo**

PR #27 (rama `docs/h3-cierre`), abierto por Claude Code y fusionado por Pedro con squash and merge. Cinco commits, uno por parte de la tarea. La etiqueta `v0.3-hito3` apunta al commit de la fusión.

- **Exportaciones:** `docs/diseno.md` y `docs/specs/hito-3.md`, idénticas byte a byte a las de la documentación en línea (anexo hasta la tarea 3.8). Antes se ajustó la pestaña de diseño: TOML en lugar de YAML, sobre común con `sim_time`, catálogo de eventos del hito 3, plantilla por turno en la v0, revisión del PR en la metodología y decisiones 24 a 30 en el registro.
- **ADRs 0024 a 0030**, con el formato de la 0023 y las alternativas y consecuencias sacadas del anexo, y **notas de actualización** en la 0008 (revisión del PR completo desde la tarea 3.6) y en la 0019 (TOML para toda la configuración).
- **Diario** `docs/diario/hito-3.md`, con una entrada por tarea y las preguntas abiertas para el hito 4.
- **Deuda:** `src/edsim/checks.py` con `ValidationResult`, `check_number`, `check_count`, `interval_result`, `all_of` y `tolerance_result`, usado por `arrivals` y `engine`; `time_in_window` pública en `queueing/mm1.py` e importada por `engine/analysis.py`.
- **Notebook 03:** la sección 9 cuenta las violaciones del log roto por comprobación; la sección 8 avisa de que sus números son los de la ejecución normal.
- 1.041 tests en verde (suite completa en 4 min 3 s), huellas SHA-256 y semillas sin tocar.

**Conceptos**

- **Un ADR aceptado no se reescribe.** Si la práctica cambia, una nota de actualización con fecha conserva lo que se decidió y explica qué cambió y por qué.
- **Una refactorización se demuestra sin tests nuevos.** La prueba es la suite completa en verde con las huellas intactas, más versiones incorrectas que comprueban que el código compartido lo usan de verdad todos los sitios.
- **Mover código puede crear importaciones circulares.** `ValidationResult` tuvo que ir al módulo común, y `arrivals.validation` lo sigue exponiendo con el mismo nombre para no cambiar a quien lo importa.
- **Un solo error propaga muchas violaciones.** Quitar un `box_assigned` da 2.515: 1 de transiciones, 1 de capacidad y 2.513 de "nadie se cuela", porque para el log ese paciente sigue esperando box toda la ejecución y todos los que reciben box después parecen colarse.

**Decisiones**

- El módulo común va en `src/edsim/`, junto a `seeds.py` y `stats.py`, porque lo usan dos subpaquetes; sus funciones son públicas porque se importan desde fuera.
- Antes de unificar, un script comprobó que cada pareja de copias era idéntica carácter a carácter. `center._check_integer` se parece a `check_count` pero no es una copia, y no se tocó.
- `time_in_window` se queda donde nació la regla (`queueing/mm1.py`). Si aparece un tercer usuario, pasará a `stats.py`.
- La deuda no estaba exactamente donde decía el prompt: `_check_number` validaba los TOML, y `_all_of` y `_tolerance_result` no estaban duplicados. Se movieron igualmente para tener juntos todos los ayudantes de resultados.

**Comprobación con versiones incorrectas** (temporales; resultado del PR)

| Versión incorrecta | Predicción | Observado |
| --- | --- | --- |
| A. `check_count` con "≤" en lugar de "<" | Fallan los límites de las llegadas y los del motor y la CLI, porque usan la misma copia | Exacta: 11 fallos y 10 errores (los errores, de *fixtures* que usan el mínimo exacto) |
| B. `time_in_window` sin recorte por la izquierda | Fallan las métricas de la M/M/1 y las identidades de utilización del motor | Exacta: 5 fallos |

**Lecciones aprendidas**

- **Comprobar el estado antes de la revisión:** las exportaciones se verificaron por su huella frente a los ficheros entregados, y los tres cambios no previstos (la sección "App web", nombres de evento sin formato de código y una fila vacía en la tabla de tareas) se explicaron. Los dos últimos se corrigieron en la documentación en línea y entrarán en la próxima exportación.
- **Medir antes de explicar:** el texto de la sección 9 se escribió después de contar las violaciones por comprobación, no antes.

**Pendiente menor para más adelante**

- Añadir el prefijo `refactor` a la lista de CLAUDE.md.
- Los `.md` de `docs/` tienen permiso de ejecución (100755) desde que se copiaron desde Windows: `git update-index --chmod=-x`.

**Hito 3 cerrado** con la etiqueta `v0.3-hito3`. Lo siguiente es la app web (fase 1) y el hito 4, Perfiles clínicos, en un chat nuevo.
