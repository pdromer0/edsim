# EDsim — Documento de diseño

Oct 27, 2026 · @Pedro

## Visión y objetivos

EDsim es un simulador de urgencias hospitalarias que genera datos sintéticos realistas, en tiempo real y por lotes, para un laboratorio completo de analítica. Se construye desde cero y paso a paso, con un objetivo doble: obtener el sistema y aprender sus fundamentos (simulación, estadística, ingeniería de datos y desarrollo con IA).

El laboratorio sirve a tres objetivos:

1. **Analítica, docencia y desarrollo de producto:** datos en streaming y en base de datos para practicar ingeniería de datos, analítica y visualización.
2. **Entrenar y validar modelos:** conocer el estado del sistema, generar alertas, predecir esperas y llegadas, y medir la robustez ante cambios.
3. **Análisis de escenarios:** lanzar experimentos que modifican variables y comparar sus resultados con rigor estadístico.

El simulador modela el recorrido del paciente desde la llegada hasta la salida: triaje, esperas, atención, pruebas, decisión de destino y abandono. El tipo y tamaño del centro son parametrizables, empezando por un hospital general de tamaño medio.

## Principios de diseño

Seis principios guían todas las decisiones técnicas del proyecto.

1. **Un solo motor, varios modos de reloj.** El mismo núcleo corre en modo directo (tiempo real o acelerado, publicando eventos) y en modo batch (máxima velocidad, muchas réplicas).
2. **El log de eventos es la fuente de verdad.** Los eventos son inmutables y los estados se derivan de ellos. Esto permite reconstruir qué se sabía en cada instante y evitar el *data leakage*.
3. **Verdad oculta separada de datos observados.** El simulador guarda el ground truth (gravedad real, paciencia, defectos inyectados) aparte de los datos tal como los vería un sistema hospitalario.
4. **Correlaciones causales, no ruido independiente.** Las variables se generan en cadena y el estado del sistema realimenta el comportamiento (saturación, abandono, boarding).
5. **Escenarios como configuración.** Centros, catálogos, escenarios y experimentos son ficheros TOML con semilla y `run_id` trazable. El motor no contiene conocimiento clínico.
6. **Calibración con datos públicos.** Volúmenes y proporciones se ajustan con estadísticas del Ministerio de Sanidad, literatura española y datasets como MIMIC-IV-ED.

## Modelo conceptual

El paciente recorre una máquina de estados en la que las esperas son estados explícitos, porque ahí se miden los KPIs y se producen los abandonos. El centro no está programado en el código: se describe en configuración (áreas, recursos por turno, reglas de enrutado).

&#91;embedded content: máquina de estados del paciente · v0\]

Las flechas discontinuas son abandonos desde las esperas; las pruebas forman un bucle con la atención y pueden repetirse.

### Entidades

| Entidad | Qué representa | Notas |
| --- | --- | --- |
| Paciente | Atributos estables: edad, sexo | `patient_id` estable entre visitas |
| Episodio | Cada visita a urgencias | `episode_id`; permite modelar reconsultas en 72 h |
| Recursos humanos | Médicos, enfermería, técnicos, celadores | Pools anónimos en la v0; individuos en la v3 |
| Recursos físicos | Boxes, sillones, camas de observación, sala de espera | Capacidad por configuración |
| Áreas o circuitos | Triaje, consulta rápida, boxes, críticos, observación | Un único circuito de boxes en la v0 |
| Servicios externos | Laboratorio, radiología, interconsultas, planta | Cajas negras con tiempo de respuesta |

### Tres dimensiones del estado

El estado del paciente no es una sola variable. Se separan tres dimensiones independientes:

- **Estado clínico-administrativo:** esperando triaje, en atención, pendiente de pruebas…
- **Ubicación física:** sala de espera, box 4, observación.
- **Responsable:** pool o profesional que lo atiende.

Un paciente puede estar en la sala de espera mientras tiene una analítica en curso; mezclar las dimensiones haría el modelo inmanejable.

### Reglas de flujo

- Cola ordenada por nivel de triaje y, dentro de cada nivel, por orden de llegada.
- El nivel 1 puede desalojar a otro paciente de un box (*preemption*).
- Re-triaje de quien supera el tiempo máximo de su nivel (v2).
- Sin cama de planta, el ingreso espera en el box (boarding) y lo bloquea.

### Destinos y límites

Destinos finales: alta a domicilio, observación, ingreso, traslado, abandono sin ser visto y exitus. Quedan fuera del sistema lo prehospitalario y lo que ocurre en planta tras el ingreso.

Marco temporal: turnos 8–15, 15–22 y 22–8; reloj en minutos; horizonte de simulación configurable.

## Variables y relaciones

Las variables se dividen en muestreadas, que se generan con distribuciones al llegar el paciente, y emergentes, que salen de la interacción entre pacientes y recursos. Las esperas nunca se muestrean: son consecuencia de colas y recursos.

### Variables por capas

| Capa | Variables | Tipo |
| --- | --- | --- |
| Contexto exógeno | Fecha y hora, día de la semana, festivos, estación, epidemias, olas de calor, eventos | Configurado |
| Atributos al llegar | Edad, sexo, medio de llegada, motivo de consulta, fragilidad | Muestreado |
| Gravedad latente | Gravedad real, nunca observada por el hospital | Muestreado (ground truth) |
| Proceso | Nivel de triaje, circuito, pruebas, reevaluaciones, tiempos de actividad | Muestreado y emergente |
| Estado del sistema | Pacientes por estado, colas, ocupación, personal, boarding, índice de saturación | Emergente |
| Resultados | Destino, estancia total, abandono, reconsulta en 72 h, exitus | Emergente |

### Cadena generativa

Cada atributo se muestrea condicionado a los anteriores:

1. Hora y contexto → tasa de llegadas y mezcla de casos.
2. Edad → medio de llegada y motivo de consulta.
3. Motivo, edad y medio → gravedad latente.
4. Gravedad latente más ruido → nivel de triaje (infra y sobre-triaje).
5. Motivo, gravedad y edad → pruebas solicitadas.
6. Gravedad, edad y resultados → destino.
7. Gravedad y pruebas → duración de cada actividad.

### Bucles de realimentación

- Saturación → abandono, sobre todo en niveles 4 y 5.
- Saturación → triaje más rápido y menos preciso.
- Boarding → boxes bloqueados → menos capacidad → más cola.
- Saturación → menos tiempo de atención o ingresos defensivos.

Cada variable tiene un momento en el que se conoce (el destino solo al final). Los eventos llevan marca de tiempo para construir features "a fecha de" sin *data leakage*.

## Catálogo de motivos de consulta

Se usan unos 17 motivos agrupados, alineados con los diagramas de Manchester; el diagnóstico CIE-10 queda como atributo opcional para versiones posteriores. Cada motivo es un perfil configurable y los pesos de la tabla son orientativos hasta la calibración.

| Motivo | Peso aprox. | Edad típica | Gravedad típica | Pruebas típicas | Ingreso |
| --- | --- | --- | --- | --- | --- |
| Traumatismo / musculoesquelético | 20 % | Joven–adulto | Baja | Radiografía | Bajo |
| Dolor abdominal | 10 % | Todas | Media | Analítica, eco/TC | Medio |
| Fiebre / infección | 8 % | Todas | Baja–media | Analítica, cultivos | Medio |
| Disnea / respiratorio | 8 % | Mayor | Media–alta | Analítica, Rx tórax, gasometría | Alto |
| Malestar general / debilidad | 6 % | Mayor | Media | Analítica, ECG | Medio |
| Dolor torácico | 5 % | Adulto–mayor | Media–alta | ECG, troponinas, Rx | Medio |
| Neurológico | 5 % | Adulto–mayor | Variable | TC craneal | Medio |
| Síncope / mareo | 4 % | Mayor | Media | ECG, analítica | Medio |
| Urológico / renal | 4 % | Adulto | Baja–media | Orina, analítica, eco | Bajo |
| Cutáneo / alergia | 4 % | Todas | Baja | Pocas | Bajo |
| ORL / oftalmológico | 4 % | Todas | Baja | Pocas | Muy bajo |
| Digestivo | 4 % | Todas | Variable | Analítica | Medio |
| Psiquiátrico | 3 % | Joven–adulto | Media | Pocas | Bajo |
| Palpitaciones / arritmia | 2 % | Adulto–mayor | Media | ECG, analítica | Medio |
| Intoxicación | 2 % | Joven | Variable | Analítica, tóxicos | Medio |
| Parada / crítico | <1 % | Mayor | Muy alta | Todas | Muy alto |
| Otros | \~10 % | Todas | Baja | Pocas | Bajo |

Cada perfil contiene: peso base; modificadores por edad, hora, estación y día; distribución de gravedad latente; probabilidad de cada prueba; modificadores de duración; y probabilidades de destino.

```toml
[dolor_toracico]
peso_base = 0.05
modificadores = { edad = "mayor_mas", hora = "neutro", estacion = "neutro" }
gravedad_latente = { media_por_edad = [...], dispersion = ... }
pruebas = { ecg = 0.98, analitica = 0.90, rx_torax = 0.70 }
destino = { depende_de = ["gravedad", "edad", "resultado_pruebas"] }
```

## Modelo estadístico y calibración

Los parámetros se escriben en términos que entiende un clínico (medianas, percentiles, porcentajes) y el motor los convierte internamente a los parámetros de cada distribución.

| Componente | Modelo | Parametrización |
| --- | --- | --- |
| Llegadas | Poisson no homogéneo, generado por *thinning* (Lewis–Shedler) | λ(t) = base × perfil horario × día × estación × evento |
| Sobredispersión | Efecto aleatorio diario gamma (media 1) | Recuentos diarios binomial negativa |
| Incidentes múltiples | Llegadas en grupo | N pacientes casi simultáneos, gravedad alta |
| Atributos | Categóricas log-lineales | Peso base × modificadores, renormalizado |
| Gravedad y triaje | Gravedad latente normal; triaje ordinal = gravedad + ruido cortada por umbrales | Ruido y sesgo constantes en el hito 4; ruido creciente con la saturación en el hito 5 |
| Tiempos de actividad | Lognormal (alternativa: gamma) | Mediana y p90 por nivel y motivo |
| Pruebas | Bernoulli con probabilidad logística | Gravedad, motivo, edad; respuesta lognormal según la hora |
| Abandono | Paciencia individual Weibull o lognormal | Escala por nivel de triaje; abandona si espera > paciencia |
| Destino | Logística multinomial | Interceptos ajustados al % de ingreso objetivo |
| Boarding | Lognormal | Depende de la hora y de la ocupación del hospital |

Conversión de mediana y p90 a parámetros de la lognormal:

```latex
\mu = \ln(\text{mediana}), \qquad \sigma = \frac{\ln(p_{90}) - \ln(\text{mediana})}{1{,}2816}
```

### Objetivos de calibración

| Objetivo | Valor de referencia | Fuente |
| --- | --- | --- |
| Ingresos sobre urgencias atendidas | 10,1 % en el SNS; 7,5 % en Andalucía | [Ministerio de Sanidad](https://www.sanidad.gob.es/gl/estadEstudios/sanidadDatos/tablas/tabla27.htm) |
| Distribución de triaje en adultos | Nivel 2: 12,1 %; nivel 3: 33,6 %; nivel 4: 52,6 %; nivel 5: 1,4 % | [Emergencias 2013](https://revistaemergencias.org/wp-content/uploads/2023/08/Emergencias-2013_25_3_191-195.pdf) |
| Tiempo máximo hasta atención (Manchester) | Inmediato, 10, 60, 120 y 240 min por nivel | Manual del sistema Manchester |

Hay dos tipos de parámetros. Los directos (mezcla de motivos, triaje, ingresos) se fijan contra datos. Los indirectos se consiguen iterando la simulación: plantilla y tiempos de servicio se ajustan hasta que los KPIs emergentes se parezcan a los objetivos.

**Calibración del hito 4.** `config/objetivos.toml` guarda cada objetivo con su horquilla y su fuente (SAS, CMBD de 2013, con menores). De ajuste, uno por mando: el pretriaje medio de los niveles 2 a 5 (6–15 min, referencia 12,4) para la enfermería de triaje y el tiempo puerta-médico medio de los niveles 2 a 5 (reloj A, 35–70 min) para los médicos. De comprobación, que nunca eligen: el reloj A del nivel 3 (45–75 min, discrepancia estructural escrita), el porcentaje por encima del máximo de Manchester con el reloj A (10–30 %) y el porcentaje con más de 5 minutos de pretriaje (30–60 %). Los boxes quedan fijos (30). Con la ventana anual (una réplica de 14 días por mes), el centro base queda con la enfermería de triaje `[3, 2, 1]` y los médicos `[12, 11, 4]` (pretriaje 6,8 min y reloj A 42,1 min con la semilla 2026). `config/centro_cumplidor.toml` (médicos `[14, 14, 6]`) es la variante que cumple Manchester. Detalle en la pestaña del hito 4 y en `docs/calibracion/registro.md`.

## Motor de simulación y reloj

El motor es una simulación de eventos discretos con SimPy que corre siempre en tiempo virtual (minutos); un marcapasos propio lo convierte en tiempo real cuando hace falta.

&#91;embedded content: arquitectura del motor · de la configuración a los destinos de datos\]

El log de eventos es la única salida del motor; el ground truth y la capa de observación se derivan de él.

- **SimPy:** cada paciente es un proceso que recorre la máquina de estados; los pools son recursos con prioridad (nivel de triaje, luego orden de llegada) y desalojo para el nivel 1.
- **Pacer propio:** permite cambiar la velocidad en caliente (×1, ×10, ×60), pausar, y anclar el reloj al calendario real para que el dashboard muestre "ahora".
- **Calentamiento:** 24–48 h simuladas a máxima velocidad sin emitir antes de empezar. En el directo, al terminarlo se publica el censo inicial: los eventos del calentamiento de los episodios que siguen abiertos y los de recursos, en su orden (hito 6). Más adelante, arranque desde una foto guardada.
- **Tres modos de uso:** directo (pacer, publica en vivo, admite shocks), batch (sin pacer, réplicas en paralelo) y replay (re-emite una ejecución guardada, determinista y rebobinable; llega en el hito 6, con el directo).
- **Un flujo aleatorio por fuente de azar:** llegadas, motivos, tiempos y paciencia tienen flujos independientes derivados de la semilla con `SeedSequence` de NumPy. Esto habilita los números aleatorios comunes en los experimentos.
- **Tres tiempos por evento:** `event_time` (cuándo ocurrió), `recorded_time` (cuándo se registró) e `ingest_time` (cuándo llegó al broker).
- **Plano de control:** en el hito 6, el topic `ed.control`, con las órdenes `velocidad`, `pausar`, `reanudar` y `parar` que publica `edsim directo control`. Más adelante, una API FastAPI publicará en el mismo topic las órdenes para pausar, cambiar la velocidad, modificar la plantilla o lanzar shocks. Cada orden queda registrada: el topic es en sí un registro.

## Modelo de datos

Todos los eventos comparten un sobre común y lo específico va en el `payload`; el ground truth se guarda aparte y una capa de observación introduce defectos realistas configurables.

### Sobre común

```json
{
  "event_id": "exp042_rep07-000184213",
  "event_type": "triage_completed",
  "schema_version": 1,
  "run_id": "exp042_rep07",
  "episode_id": "EP-000184",
  "patient_id": "PT-000184",
  "source_system": "triaje",
  "sim_time": 1024.2,
  "event_time": "2026-10-27T17:04:12.000+01:00",
  "recorded_time": "2026-10-27T17:11:40.000+01:00",
  "ingest_time": "2026-10-27T17:11:41.000+01:00",
  "payload": { "nivel": 3, "motivo": "dolor_toracico" }
}
```

### Catálogo de eventos v0

| Evento | Cuándo | Payload principal |
| --- | --- | --- |
| `patient_arrived` | Cruza la puerta | Medio de llegada |
| `patient_registered` | Admisión | Edad, sexo |
| `triage_started` / `triage_completed` | Triaje | Nivel, motivo |
| `box_assigned` | Entra en un box (también al reanudar tras un desalojo) | Box |
| `patient_displaced` | Un nivel 1 le quita el box | Box, episodio que desaloja |
| `assessment_started` / `assessment_ended` | Valoración médica y reevaluación | Tipo (inicial o reevaluación), pool y box; al terminar, si se interrumpió |
| `test_ordered` / `test_resulted` | Pruebas | Tipo, resultado normal o alterado |
| `disposition_decided` | Decisión de destino | Destino |
| `bed_requested` / `bed_assigned` | Boarding | Servicio |
| `patient_departed` | Sale de urgencias | Destino final |
| `patient_left_wbs` | Abandono sin ser visto | Estado en que estaba |
| `staffing_changed` | Cambio de turno o plantilla | Recurso, plantilla anterior y nueva |
| `shock_started` / `shock_ended` | Evento de sistema | Tipo, intensidad |
| `control_command` | Orden desde la API | Comando |
| `system_snapshot` | Cada 5 minutos | Colas, ocupación, saturación |

**Versiones del catálogo (hito 4).** Cada log lleva una sola versión en el `schema_version` del sobre, una por modelo y no por configuración:

- **Versión 1**, modelo provisional: los eventos del hito 3 que el motor escribe, con `circuito` en `triage_started` (`puerta` para el nivel 1 o `enfermeria`).
- **Versión 2**, modelo clínico (tarea 4.5a): `medio` en `patient_arrived`, `edad` y `sexo` en `patient_registered`, `motivo` en `triage_completed`, la lista de pruebas en `test_ordered` y el resultado de cada una en `test_resulted`.
- **Versión 3**, modelo clínico desde la tarea 4.6a: la versión 2 más `box_released` (`box` y `espera`), cuando un paciente de los niveles de `espera_resultados_fuera` deja el box para esperar los resultados.

Lo oculto para el hospital (gravedad real, nivel real, calidad del triaje, banda de edad y tiempos de respuesta de las pruebas) no está en ningún catálogo: va al ground truth.

### Topics

- `ed.patient.events` (3 particiones), con clave `episode_id` para conservar el orden por episodio.
- `ed.resource.events` (clave `recurso`), `ed.runs` (un mensaje `inicio` y otro `fin` por ejecución, con clave `run_id`) y `ed.control` (órdenes al simulador). Los crea y comprueba `edsim directo preparar`; el broker no los autocrea (hito 6).
- `ed.system.events` y `ed.snapshots` no se crean hasta que existan los shocks y `system_snapshot`.
- El valor de cada mensaje es la línea del JSONL tal cual, con `ingest_time` nulo. La hora de llegada es la marca de tiempo del broker (`LogAppendTime`), que el consumidor del hito 7 copiará en `ingest_time`.
- Esquemas en JSON Schema en la v0 (uno por versión del catálogo, generados, en `schemas/`); Avro con un registro de esquemas (Apicurio o Karapace) más adelante.

### Ground truth

Una fila por episodio con gravedad latente, paciencia, calidad del triaje (correcto, infra o sobre), tiempos reales por etapa, causa del abandono y los defectos de observación inyectados.

### Defectos de la capa de observación

Retraso de registro, desorden, duplicados, campos vacíos, valores erróneos, eventos olvidados (pacientes "fantasma"), desfase de reloj entre sistemas y correcciones tardías. Cada defecto tiene tasa configurable y hay tres perfiles: limpio, realista y hostil.

### Capas de almacenamiento

| Capa | Contenido | Tecnología |
| --- | --- | --- |
| Bronce | Eventos tal como llegan | Postgres / Parquet |
| Plata | Deduplicados y tipados: `episodios`, `intervalos_estado`, `ocupacion_recursos` | dbt |
| Oro | KPIs por hora y turno; tablas de features "a fecha de" | dbt |

Postgres con TimescaleDB para lo operacional y en tiempo real; Parquet con DuckDB para lo analítico, particionado por `run_id` y fecha.

## Diseño de experimentos

Un experimento es un conjunto de variantes de un escenario base, cada una con N réplicas emparejadas por semilla, comparadas con intervalos de confianza sobre las diferencias.

```toml
experimento = "plantilla_tarde_invierno"
base = "hospital_medio_v0"
duracion = { calentamiento_dias = 3, dias = 28 }
replicas = 30
semilla = 2026
metricas = ["espera_p90_por_nivel", "estancia_media", "abandono_pct", "cumplimiento_manchester", "ocupacion_boxes"]

[variantes.control]

[variantes.medico_extra_tarde]
"recursos.medicos.turnos.tarde" = "+1"

[variantes.medico_extra_y_gripe]
"recursos.medicos.turnos.tarde" = "+1"
shocks = ["brote_gripe_moderado"]
```

### Tipos de experimento

- **Comparación A/B:** un cambio concreto frente al control.
- **Barrido de parámetros:** rejillas como médicos 3–7 × demanda +0 % a +30 %.
- **Sensibilidad:** uno a uno primero; después hipercubo latino e índices de Sobol.
- **Estrés y robustez:** shocks y combinaciones de shocks.
- **Optimización** (más adelante): plantilla mínima que cumple los tiempos Manchester el 95 % de los días.

### Rigor estadístico

- Sistema en estado estacionario: se descarta el calentamiento y se simulan semanas.
- 20–30 réplicas iniciales; se añaden hasta alcanzar la precisión deseada.
- Comparaciones emparejadas gracias a los números aleatorios comunes.
- Percentiles y porcentaje de días fuera de objetivo, no solo medias.

### Catálogo de shocks

Cada shock se define por inicio, duración, forma (escalón, rampa o pulso), intensidad y parámetros afectados.

| Shock | Qué modifica |
| --- | --- |
| Brote de gripe / VRS | λ ×1,2–1,5 durante semanas; más respiratorios en mayores; más gravedad |
| Accidente con múltiples víctimas | 15–30 llegadas en una hora; gravedad alta |
| Ola de calor | Más mayores, deshidratación y síncopes |
| Baja de personal | −1 médico o enfermera en un turno |
| Caída del laboratorio | Tiempos de respuesta ×3 durante unas horas |
| Bloqueo de camas | Ocupación de planta al 100 %; boarding disparado |
| Puente o festivo | Patrón horario distinto y menos plantilla |
| Evento masivo | Más intoxicaciones y traumatismos en jóvenes, de noche |
| Temporada turística | λ aumentada y más traumatismos en costa |

### Registro y validación

Cada réplica es un *run* de MLflow; las salidas detalladas van a Parquet por experimento y réplica, consultadas con DuckDB. El simulador se valida con pruebas de condiciones extremas, comparación con los objetivos de calibración y revisión cualitativa de trazas por alguien con experiencia clínica.

## Stack tecnológico y despliegue

Todo corre en un portátil con Docker Compose, usando piezas estándar de la industria que se introducen de una en una a lo largo de los hitos.

&#91;embedded content: bloques del proyecto y su tecnología\]

El camino directo alimenta Grafana en tiempo real desde Postgres; el camino batch alimenta experimentos y modelos desde Parquet; dbt une las dos bases y la orquestación lanza los trabajos por lotes.

| Capa | Elección | Alternativa |
| --- | --- | --- |
| Simulación | Python + SimPy + NumPy/SciPy | Salabim |
| Configuración | TOML leído con tomllib y validado con dataclasses al construir | YAML con Pydantic |
| API de control | FastAPI | Topic de control |
| Broker | Apache Kafka 4 en modo KRaft (un nodo) + Redpanda Console como interfaz | Redpanda (ejercicio de compatibilidad) |
| Streaming | Consumidores Python con Quix Streams | Flink o RisingWave |
| BD operacional | PostgreSQL + TimescaleDB | ClickHouse |
| BD analítica | Parquet + DuckDB | Iceberg |
| Transformación | dbt | SQLMesh |
| Tiempo real y alertas | Grafana | — |
| Exploración y what-if | Streamlit | Dash |
| BI educativo | Metabase | Superset |
| ML | scikit-learn, LightGBM, statsmodels + MLflow | Feast |
| Orquestación | CLI propia; Dagster después | Prefect |
| Notebooks | JupyterLab | — |

### Perfiles de Docker Compose

- `core`: simulador, API, Kafka, Redpanda Console y Postgres. En el hito 6, `kafka` y `console` van sin perfil, porque son la base y arrancan siempre; el simulador, la API y Postgres entran en `core` cuando existan.
- `analytics`: dbt, DuckDB, Metabase y Jupyter.
- `realtime`: Grafana y consumidores de streaming.
- `ml`: MLflow y entorno de modelos.

El stack completo necesita unos 8–16 GB de RAM; `core` mucho menos.

### Repositorio y CLI

```
edsim/
├── src/edsim/      # núcleo: queueing, arrivals, engine, profiles, calibration, runs; live (hito 6)
├── app/            # EDsim Lab (Streamlit), paquete edsim-app
├── config/         # centro, llegadas, perfiles y objetivos (TOML)
├── schemas/        # JSON Schema de los eventos y de los mensajes (hito 6)
├── tests/          # tests del núcleo; tests_integracion/ contra Kafka (hito 6)
├── notebooks/      # un notebook por hito
├── docs/           # diseño, specs, ADRs, diario y calibración
├── compose.yaml    # Kafka y Redpanda Console (hito 6)
└── pyproject.toml  # workspace de uv con los dos paquetes
```

Árbol real del repositorio, actualizado al preparar el hito 6. El diseño inicial proponía `sim/`, `configs/`, `api/`, `consumers/`, `dbt/`, `dashboards/`, `ml/` y `docker/`; las carpetas de los hitos 7 a 10 se deciden en su hito.

```bash
edsim directo lanzar --velocidad 60 --anclar
edsim experimento configs/experimentos/plantilla_tarde_invierno.toml
edsim directo reemitir exp042_rep07 --velocidad 10
edsim shock --tipo brote_gripe_moderado --intensidad 1.3
```

### Calidad

Tests de invariantes (llegadas = salidas + dentro; ningún recurso por encima de su capacidad; ningún evento anterior a la llegada), tests de regresión con semilla fija y CI con GitHub Actions. Qué tests hay, cuánto cuestan y cuándo se ejecutan, en «Calidad y tests (QA)».

## Casos de uso

La gran mayoría de los casos de uso ya son posibles con la v0; sirven también como catálogo de ejercicios y como prueba de que el diseño está completo.

| Bloque | Caso de uso | Técnica | Nivel | Versión |
| --- | --- | --- | --- | --- |
| Datos y streaming | Capas bronce → plata → oro | dbt, deduplicación | Básico | v0 |
| Datos y streaming | Censo en vivo a partir de eventos | Event sourcing, agregación con estado | Intermedio | v0 |
| Datos y streaming | KPIs por ventana con eventos tardíos | Ventanas, watermarks | Intermedio | v0 |
| Datos y streaming | Detección de problemas de calidad | Tests de datos validados con ground truth | Intermedio | v0 |
| Datos y streaming | Evolución de esquemas | Avro + Schema Registry | Avanzado | v1 |
| Analítica | Panel de KPIs de urgencias | SQL, Grafana, Metabase | Básico | v0 |
| Analítica | Patrones temporales hora × día | Análisis exploratorio | Básico | v0 |
| Analítica | Descubrir los perfiles de motivo | Análisis exploratorio | Intermedio | v0 |
| Analítica | Minería de procesos | pm4py sobre `intervalos_estado` | Intermedio | v0 |
| Analítica | Calidad del triaje | Comparación con gravedad latente | Avanzado | v0 |
| Modelos | Índice de saturación y alertas por umbral | Reglas sobre el stream | Básico | v0 |
| Modelos | Previsión de llegadas a 24–72 h | Regresión de Poisson, series temporales | Intermedio | v0 |
| Modelos | Predicción de ingreso desde el triaje | LightGBM | Intermedio | v0 |
| Modelos | Predicción de abandono | Clasificación o supervivencia | Intermedio | v0 |
| Modelos | Espera estimada al llegar | Regresión cuantílica "a fecha de" | Avanzado | v0 |
| Modelos | Alerta anticipada de saturación a 2 h | Modelo sobre snapshots | Avanzado | v1 |
| Modelos | Detección de cambios de régimen | CUSUM, puntos de cambio | Avanzado | v0 |
| Modelos | Robustez ante *drift* | Entrenar en normalidad, evaluar con shocks | Avanzado | v0 |
| Escenarios | Dimensionado de plantilla por turno | Barrido, comparación emparejada | Intermedio | v0 |
| Escenarios | Planes de contingencia | Experimentos de estrés | Intermedio | v0 |
| Escenarios | Evaluar intervenciones de circuito | Comparación de configuraciones | Avanzado | v1–v2 |
| Escenarios | Inferencia causal con respuesta conocida | Estimación observacional frente a experimento | Avanzado | v0 |

## Hoja de ruta

La v0 se construye en 11 hitos agrupados en cuatro fases, cada una con un criterio de salida; después, las versiones v1–v3 añaden complejidad al modelo.

&#91;embedded content: hoja de ruta · 11 hitos en 4 fases\]

Cada fase se cierra cuando se cumple su criterio (el rombo); la plataforma de datos se monta sobre el modelo v0 antes de complicarlo.

### Hitos

- **0 · Entorno:** Python con uv, git, Cursor, Claude Code, `CLAUDE.md`, pytest y pre-commit.
- **1 · Colas y SimPy:** eventos discretos, cola M/M/1 y ley de Little; validación contra la teoría.
- **2 · Llegadas:** Poisson no homogéneo, *thinning*, sobredispersión y validación estadística.
- **3 · Motor y eventos:** paciente, triaje, recursos con prioridad y desalojo, turnos, log de eventos en JSONL y validación del motor.
- **4 · Perfiles clínicos:** población adulta, 17 motivos, gravedad latente y triaje con error, pruebas por tipo y duraciones por nivel real y motivo, tres relojes, sala de resultados para los niveles 4 y 5 y primera calibración con la ventana anual.
- **5 · Cierre del flujo:** abandono, destino, boarding simple y ground truth.
- **6 · Tiempo real:** pacer, Docker y Apache Kafka con Redpanda Console.
- **7 · Persistencia:** consumidor hacia Postgres/Timescale y capa de observación con defectos.
- **8 · Analítica:** dbt (medallón) y Grafana.
- **9 · Experimentos:** runner con réplicas, números aleatorios comunes y MLflow.
- **10 · Modelos:** casos de uso de ML, uno a uno.

### Versiones del modelo

- **v0:** un circuito de boxes, recursos en pool con plantilla por turno, llegadas con patrón horario y semanal.
- **v1:** consulta rápida (niveles 4–5), críticos (niveles 1–2).
- **v2:** observación, boarding realista, re-triaje y reconsultas en 72 h.
- **v3:** perfiles de centro intercambiables, profesionales individuales y constantes vitales.

**Aplazado en el hito 4**, con su destino:

- **Hito 5:** destino multinomial, abandono, boarding y su calibración (ingreso, estancia, días punta); ruido de triaje que crece con la saturación.
- **v1 (circuitos):** triaje dentro del box y equipo propio para el nivel 1, con desalojo de médicos; circuitos separados para los niveles 4 y 5 (consultas o vía rápida), lo que permitiría calibrar el reloj A del nivel 3.
- **v3 (perfiles de centro):** pediatría y centros mixtos.
- **Fase 2 de la app:** editar los perfiles desde la app.
- **Versiones posteriores o por decidir:** un `test_ordered` y un `test_resulted` por tipo de prueba; reconocimiento en la puerta por la gravedad real; turnos escalonados por mando (pretriaje de noche); plantilla por temporada (refuerzo de invierno); la regla de la plantilla equivalente con la carga prevista por turno en lugar de la tasa de llegadas.

### App web

La app web crece en paralelo a la hoja de ruta: una app local en Streamlit al cerrar el hito 3, una tarea pequeña en los hitos siguientes y la aplicación completa después del hito 6 o de la v0. Decisión y especificación de la fase 1: App web — fase 1.

Fase 1 cerrada el 5 de noviembre de 2026 con la etiqueta `app-v0.1.0`: EDsim Lab, seis páginas (tareas A.0 a A.8) y las ADR 0031 a 0033 y APP-0001 a APP-0003.

Incremento del hito 4 (tareas 4.8a, 4.8b y 4.8c): la app simula y muestra el modelo clínico, con las etiquetas `app-v0.2.0` y `app-v0.2.1` y las ADR APP-0004 (perfiles de solo lectura) y APP-0005 (Simular solo crea ejecuciones clínicas). Especificación y anexo: App web — incrementos.

## Metodología de trabajo con Claude Code y Cursor

Claude Code escribe el código; Pedro dirige, pregunta y revisa. Cada hito sigue el mismo ciclo, con el aprendizaje como prioridad.

1. **Sesión conceptual:** Claude explica qué se va a implementar y por qué (estadística, simulación, tecnología); Pedro pregunta hasta entenderlo.
2. **Especificación del hito:** alcance, criterios de aceptación y tests, en `docs/specs/`.
3. **Plan:** Claude Code propone el plan en modo plan antes de tocar código.
4. **Implementación:** con el plan aprobado, Claude Code implementa la tarea completa, con un commit por paso lógico; solo para si algo contradice el plan o hace falta una decisión nueva.
5. **Revisión del PR:** la descripción del PR explica cada decisión y lo que cambió respecto al plan; Pedro la revisa con Claude en el chat del hito y pide cambios o aclaraciones (desde la tarea 3.6; antes se revisaba cada diff).
6. **Cierre:** tests en verde, nota en el diario de aprendizaje (`docs/diario/`) y ADR si hubo una decisión importante.

Se usan las librerías directamente, sin reimplementar fundamentos a mano; los conceptos se explican en la sesión y se profundiza bajo demanda.

### Herramientas

- **Cursor:** editor para leer, navegar, revisar diffs, depurar y trabajar con notebooks. Su IA propia no se usa al principio, para no mezclar flujos.
- **Claude Code:** agente en el terminal integrado de Cursor.

### Prácticas de desarrollo con IA que se introducen por el camino

- `CLAUDE.md` como memoria del proyecto: convenciones, comandos y modo de trabajo.
- Modo plan antes de codificar.
- Tests como barandilla, acordados antes del código.
- Tareas pequeñas, commit por paso lógico y revisión del PR completo.
- Comandos personalizados y *skills* para flujos repetidos (empezar hito, revisar, cerrar hito).
- *Hooks* para lanzar linter y tests automáticamente.
- Subagentes, más adelante, para tareas grandes.

Los detalles concretos de configuración de Claude Code se comprueban contra su documentación al montar el entorno.

### Flujo de desarrollo (GitHub Flow)

`main` está siempre estable; cada tarea vive en una rama corta que entra en `main` por pull request, con el CI en verde y tras la revisión de Pedro. Claude Code nunca fusiona en `main`.

| # | Paso | Quién | Cómo |
| --- | --- | --- | --- |
| 1 | Actualizar `main` local | Claude Code | `git pull`, con permiso |
| 2 | Crear rama de la tarea | Claude Code | `git switch -c feat/h1-cola-mm1` |
| 3 | Proponer el plan | Claude Code propone, Pedro aprueba | Modo plan |
| 4 | Implementar código y tests | Claude Code | La tarea completa, con el plan aprobado |
| 5 | Comprobar al final de cada turno | Automático | Hook Stop: tests rápidos con sello (N2), nada en modo plan; ver «Calidad y tests (QA)» |
| 6 | Commit local | Claude Code | Mensaje estándar: `feat(sim): cola M/M/1 con SimPy` |
| 7 | Comprobar al hacer commit | Automático | Hooks de pre-commit; si fallan, no hay commit |
| 8 | Comprobar la tarea completa | Claude Code | scripts/tests-completos.sh (N3) una vez antes de cada push y revisión de sus propias gráficas |
| 9 | Subir la rama | Claude Code, con permiso | `git push` |
| 10 | Abrir el pull request | Claude Code | `gh pr create` con resumen y checklist |
| 11 | Ejecutar el CI | Automático | GitHub Actions |
| 12 | Corregir si el CI falla | Claude Code | `gh run view` y vuelta al paso 4 |
| 13 | Revisar el PR y fusionar | Pedro | "Squash and merge" en GitHub |
| 14 | Limpiar | Automático y Claude Code | GitHub borra la rama; Claude vuelve a `main` y sincroniza |

- **Inicio de hito:** sesión conceptual y especificación en `docs/specs/`, redactada por Claude y aprobada por Pedro.
- **Cierre de hito:** nota en el diario, ADR si procede y etiqueta de versión (`v0.1-hito1`).
- **Configuración única (Pedro, guiado por Claude):** cuenta y repositorio en GitHub, `gh auth login` y protección de `main` (solo por pull request con CI en verde).
- **Permisos de Claude Code:** lectura y tests sin preguntar; subidas con permiso; fusión reservada a Pedro.
- **Aprendizaje de git:** en los hitos 0 y 1, Pedro ejecuta a mano los pasos de git (rama, commit, push, pull request) siguiendo las indicaciones de Claude; desde el hito 2 los ejecuta Claude Code.

## Calidad y tests (QA)

Los tests van por niveles (decisión 47, tarea P.1): cada punto del ciclo ejecuta solo lo que el último cambio puede haber roto, y el árbol que llega a `main` pasa siempre la suite completa en local y en el CI. Cifras de `main` en `f410f00` (7 de noviembre de 2026). El hito 6 añade la suite de integración contra Kafka, su script y su job del CI: ver «Qué añadió el hito 6», al final de esta sección.

### Qué tests hay

Hay 3.000 tests en cinco suites. La marca `slow` separa los caros: en el núcleo, los estadísticos largos y los que reproducen una calibración (decisión 17); en la app, los `AppTest` que simulan, que marca `app/tests/conftest.py` al recolectar.

| Suite | Tests | Qué incluye |
| --- | --- | --- |
| Núcleo rápido | 2.723 | Todo `tests/` salvo `slow` |
| Núcleo `slow` | 32 | Validaciones estadísticas largas y reproducción de las filas del registro de calibración |
| App rápida | 124 | Tests de `app/tests/` sin simulación |
| App `slow` | 117 | `AppTest` que simulan y los del Replay |
| Notebooks | 4 | Los cuatro notebooks de `notebooks/` en modo rápido (`EDSIM_NB_RAPIDO=1`) |

El núcleo, por familias. Los tests usan valores calculados a mano y literales, no la función probada como referencia.

| Familia | Tests | `slow` | Qué comprueba |
| --- | --- | --- | --- |
| Ejecuciones, métricas y análisis | 607 | 2 | `simulate_run`, `run.json`, CSV clínico, ground truth, relojes, cumplimiento, carga ofrecida, comparación y Replay |
| Configuración | 563 | 0 | Lectura y validación de `centro.toml`, `perfiles.toml` y `llegadas.toml`; «escritos = recalculados» |
| Motor, eventos e invariantes | 557 | 8 | Máquina de estados, prioridades, turnos, catálogo de eventos, invariantes del log, huellas y validación del motor |
| Perfiles clínicos | 471 | 4 | Mezcla exacta de la gravedad, triaje, pruebas y duraciones; muestreadores frente a lo exacto |
| Llegadas | 188 | 7 | λ(t), *thinning*, efecto diario Z y las cinco pruebas de validación |
| CLI | 149 | 2 | Comandos de `edsim`, incluidos `motor validar` y `perfiles validar` de verdad |
| Calibración | 139 | 7 | Plantilla equivalente, ventana anual, sensibilidad y reproducción del centro calibrado |
| Colas de referencia | 75 | 2 | M/M/1 frente a la teoría, estadística y réplicas |
| Frontera y humo | 6 | 0 | El núcleo no importa `streamlit`, `pandas` ni `edsim_app` |
| **Total** | **2.755** | **32** |  |

### Cuánto cuestan

En el portátil de Pedro, la rápida del núcleo baja de unos 6 min en serie a 3 min 05 s en paralelo, y la comprobación completa antes del push, de 18 min 46 s a 12 min 32 s. Medidas del PR #52 sobre `main` en `462d0d1`: i7-1255U (2 núcleos de rendimiento y 8 de eficiencia, 12 hilos), 7,6 GB, WSL2, pytest 9.2.0 y pytest-xdist 3.8.0, 6 workers. Entre dos ejecuciones iguales hubo hasta un 40 % de diferencia.

| Suite | En serie | Como se ejecuta ahora |
| --- | --- | --- |
| Núcleo rápido | 5 min 35 s – 6 min 05 s | 3 min 05 s (xdist, `loadfile`) |
| Núcleo completo | 15 min 27 s | 9 min 00 s (xdist, `worksteal`) |
| App rápida | 33 s | En serie |
| App completa | 2 min 19 s – 2 min 33 s | En serie |
| Notebooks | 1 min | En serie |
| `scripts/tests-completos.sh` (todo lo anterior, con lint y formato) | 18 min 46 s | 12 min 32 s |

- **Qué domina.** 40 tests rápidos de más de 2 s suman 204 de los 362 s de la rápida en serie. En la completa pesan los fixtures caros: `engine_validation_real` (unos 2 min, de sesión), `clinical_store` y `clinical_simulation` (de sesión) y los del centro calibrado (de módulo).
- **Por qué xdist no gana más.** Cada worker es un proceso propio y recalcula esos fixtures. Con `loadfile` cada fichero va a un worker y la completa no baja del fichero más largo (`test_calibrated_center.py`); `worksteal` reparte mejor y gana en la completa. Con 12 workers se agota la memoria y aparece el swap.
- **Por qué la app va en serie.** En paralelo no baja del 87 % de la serie, y con la CPU ocupada algunos `AppTest` superan su límite de 3 s por página.
- **El CI.** En el runner (4 CPU) el núcleo completo tardó 463 s en serie, 470 s con `worksteal` y 382 s con `loadfile`. Ninguno llega al 60 % de la serie, así que el CI va en serie. La misma ejecución en serie ha tardado entre 463 y 933 s según la máquina asignada. Los tres jobs van en paralelo: `tests` tarda unos 8 min (hasta unos 16 con una máquina lenta), `tests-app` unos 2,5 y `notebooks` 1.
- **El criterio.** xdist se adopta en una suite solo si en paralelo tarda como mucho el 60 % de la serie y da exactamente los mismos resultados test a test. Se fijó antes de medir.

### Cuándo se ejecutan

Cuatro niveles, de lo más barato a lo más completo: **N0** ruff; **N1** los ficheros de test del área tocada; **N2** la rápida con sello, solo de las suites afectadas; **N3** todo. Cada punto del ciclo usa el nivel más bajo que le basta.

| Punto del ciclo | Nivel | Qué se ejecuta | Qué garantiza |
| --- | --- | --- | --- |
| Al editar un `.py` | N0 | `ruff format` del fichero (hook `PostToolUse` de Claude Code) | Formato |
| Al final de cada turno (hook `Stop` de Claude Code y de Codex) | N2 | `scripts/tests-rapidos.sh`. En modo plan, nada. Sin cambios desde el último verde, o con solo documentación, nada. Si no, la rápida de cada suite afectada, con `-x`: el núcleo con xdist y la app en serie. Codex formatea antes con `ruff format .` | El agente no devuelve el turno con la rápida en rojo |
| Antes de cada commit | N0 + N1 | pre-commit (nbstripout, `ruff check --fix`, `ruff format`, espacios, YAML, ficheros grandes) y los ficheros de test del área tocada | El paso está limpio y su área pasa |
| Al probar una versión incorrecta | N1 | Los ficheros donde se predice el fallo y los que deben seguir pasando | El test detecta el error previsto |
| Antes de cada push | N3 | `scripts/tests-completos.sh`: lint, formato, núcleo completo con xdist, app completa en serie y notebooks. Ejecuta todas las partes aunque una falle y sella las dos suites si todo pasa. En las tareas que tocan Kafka, también `scripts/tests-integracion.sh` (hito 6) | Lo que se sube pasa todo |
| En cada push al PR | CI | `tests` (lint, formato y núcleo completo en serie), `tests-app`, `notebooks` y, desde el hito 6, `tests-kafka` (integración contra el Kafka de `compose.yaml`), en paralelo. Un push nuevo cancela la ejecución anterior del mismo PR | Lo comprueba una máquina limpia; la protección de `main` exige sus checks obligatorios |
| Al fusionar en `main` | CI | Lo mismo sobre `main`, sin cancelar nunca | `main` sigue en verde |

Qué suite afecta cada ruta cambiada (el primer caso que encaja manda):

| Ruta cambiada | Suites que se ejecutan |
| --- | --- |
| `*.md`, `docs/`, `app/docs/`, `notebooks/` | Ninguna; se actualizan los sellos |
| `app/` | App |
| `src/edsim/`, `config/`, `pyproject.toml`, `uv.lock`, `tests/data/` | Núcleo y app (la app usa el núcleo y lee `tests/data/`) |
| `compose.yaml`, `tests_integracion/` (hito 6) | Ninguna; se actualizan los sellos. Los prueba `scripts/tests-integracion.sh` |
| `tests/`, `schemas/`, `scripts/`, `.claude/`, `.codex/`, `.github/`, `.pre-commit-config.yaml`, `.gitignore` | Núcleo |
| Cualquier otra | Núcleo y app (lo conservador) |

`uv run pytest tests/test_x.py` sigue en serie: xdist no va en `addopts`, y solo lo piden los dos scripts.

### Workflow

Una tarea pasa por siete pasos y cada uno tiene su nivel de tests; los dos bucles vuelven a la implementación.

&#91;embedded content: ciclo de una tarea · los tests de cada paso\]

Dentro de la implementación, cada paso lógico es un commit con N1, y al final de cada turno el `Stop` ejecuta N2 sobre lo que haya cambiado. N3 se ejecuta una vez por push, no por commit. Una revisión con ajustes o un CI en rojo vuelven a la implementación con commits nuevos en la misma rama, y el ciclo de tests se repite desde N1.

**Cómo funciona el sello** (`scripts/sello.sh`):

- **Qué es.** El manifiesto del árbol en el último verde de cada suite: una línea `sha1  ruta` por fichero seguido o sin seguir no ignorado (`git ls-files --cached --others --exclude-standard` y `sha1sum`). Hay un sello para el núcleo y otro para la app, en `.cache/edsim/`.
- **Cómo decide.** Compara el manifiesto actual con el sello de cada suite, no con `HEAD`: un commit no obliga a repetir los tests, y un fichero nuevo sin seguir sí cuenta. Las rutas cambiadas se clasifican con la tabla anterior.
- **Cuándo se escribe.** Solo con la suite en verde, y con el manifiesto tomado antes de pytest: lo que cambie durante los tests no queda como verde. Una suite a la que no afecta ningún cambio se vuelve a sellar sin ejecutarse.
- **Ficheros borrados.** Un fichero seguido y borrado sigue en el índice; `sha1sum` no lo encuentra, falta en el manifiesto y cuenta como cambio.
- **Por qué fuera de `.git`.** El `.git` de Codex es de solo lectura en su sandbox, y `git hash-object -w` escribiría objetos. `sha1sum` solo lee.

### Qué cambió con la P.1 y cómo queda

La espera en tests por tarea baja de unas 3 h a menos de 50 min. La ganancia viene sobre todo de no ejecutar nada cuando no hace falta (modo plan, árbol ya verde, commits); el paralelismo aporta menos en este portátil. Cambios del PR #52 (7 de noviembre de 2026):

| Punto | Antes | Ahora | Por qué |
| --- | --- | --- | --- |
| `Stop` en modo plan | Rápida completa del núcleo, unos 6 min por turno | Nada | En plan el código no cambia |
| `Stop` sin cambios que afecten | Rápida completa | Nada (0,26 s para decidirlo) | El árbol ya pasó |
| `Stop` con cambios | Rápida del núcleo, siempre | La rápida de las suites afectadas: núcleo 3 min 05 s, app 33 s | Solo lo que el cambio puede romper |
| Antes de cada commit | Rápida completa | ruff y los tests del área | Con *squash and merge*, los commits intermedios no llegan a `main` |
| Antes del push | Completa, app y notebooks en serie, 18 min 46 s | `scripts/tests-completos.sh`, 12 min 32 s | Un solo comando, con el núcleo en paralelo |
| CI | Job `tests` con lint, completa y notebook (8 min 22 s); `tests-app` aparte | `tests`, `tests-app` y `notebooks` en paralelo; un push nuevo cancela el anterior | El notebook no espera al núcleo y no se acumulan ejecuciones |
| `Stop` de Codex | Rápida del núcleo y de la app, siempre | El mismo script, por rutas | Una sola lógica para los dos agentes |

El coste por tarea es una estimación con las medidas de la tabla «Cuánto cuestan» y un supuesto de tarea típica, no una tarea medida:

| Supuesto | Antes | Ahora |
| --- | --- | --- |
| 10 turnos en modo plan | 58 min | 0 |
| 12 commits | 70 min | 12 min como mucho (N1 sin medir; cota de 1 min por commit) |
| 3 turnos con cambios en el núcleo y la app | 17 min | 11 min |
| 2 rondas de push | 38 min | 25 min |
| **Total** | **unas 3 h** | **menos de 50 min** |

**Por qué no se pierde calidad.** A `main` solo llega el árbol final del PR (*squash and merge*), y ese árbol pasa N3 en local y el CI completo en una máquina limpia, como antes. Lo único que deja de comprobarse uno a uno son los commits intermedios, que desaparecen al fusionar. El sello nunca da por verde un árbol que no pasó: se escribe solo en verde y compara contenidos, no commits.

**Limitaciones conocidas:**

- En este portátil no se alcanzan los tiempos orientativos (rápida en 1 min 30 s y N3 en 7 min): manda la CPU.
- En el runner del CI, xdist no compensa: el CI va en serie y su tiempo varía hasta el doble según la máquina.
- La app va en serie por el límite de 3 s por página de `AppTest`. Un fallo por tiempo con la máquina cargada se repite en serie antes de investigarlo.
- `--dist loadgroup` no agrupa con pytest 9.2 ([pytest-xdist #1386](https://github.com/pytest-dev/pytest-xdist/issues/1386)); no se usa.

**Pendiente (fase 2):**

- Hacer configurable el límite de `AppTest` (3 s por defecto), con su test.
- Revisar la marca `slow` de los 40 tests rápidos de más de 2 s.
- `timeout-minutes` en cada job del CI: hoy no hay límite y GitHub deja un job colgado hasta 6 h.
- Repartir los tests `slow` en jobs del CI aparte, cada uno en su máquina, para bajar el tiempo típico y el peor caso.
- N1 automático con `pytest-testmon`: solo sigue el código Python, así que un cambio en `config/` o `tests/data/` seguiría pidiendo N2. Comprobar antes que admite pytest 9.2.
- Saltar los tests del CI cuando el PR solo cambia documentación, con una comprobación dentro del job y no con `paths-ignore` (un check obligatorio que no se ejecuta bloquea la fusión).
- Volver a mirar `loadgroup` cuando xdist publique una versión que admita pytest 9.2.

### Qué añadió el hito 6

El hito 6 (Tiempo real) añade una suite que necesita un broker de Kafka y, por eso, va aparte de las demás (decisión 50, H6-3). Estado tras la tarea 6.5 (9 de noviembre de 2026).

| Pieza | Qué es |
| --- | --- |
| `tests_integracion/` | Tests contra un Kafka real, fuera de `testpaths`: `uv run pytest` no los recoge. Prueba de humo (6.1); topics, particiones con murmur2, un directo de un día y las órdenes (6.4); la CLI `edsim directo` de extremo a extremo, Ctrl+C, `reemitir` y sin broker (6.5). Eran 11 tras la 6.4 |
| `scripts/tests-integracion.sh` | Levanta `compose.yaml` si hace falta (`docker compose up --wait`), ejecuta `uv run --locked --extra kafka pytest tests_integracion` y baja los contenedores si los levantó él. De 29 a 34 s en el portátil de Pedro. Se ejecuta antes del push en las tareas que tocan Kafka |
| Job `tests-kafka` | Cuarto job del CI: `uv sync --locked --extra kafka` y `scripts/tests-integracion.sh`, con `timeout-minutes: 15`. Obligatorio en la protección de `main` desde la 6.4 |
| Sello | `compose.yaml` y `tests_integracion/` no afectan a la rápida (los prueba el script de integración); `schemas/` es núcleo, porque un test compara los esquemas escritos con los generados |
| Frontera | El núcleo se importa sin `confluent-kafka`: solo `edsim/live/kafka.py` lo importa, dentro de funciones, y un test lo comprueba. La suite rápida usa un `FakeProducer` y, desde la 6.5, un módulo `confluent_kafka` falso |

**Medir sin contenedores.** Con Kafka en marcha la completa tardó unos 6 minutos más (19:53 en la 6.1 frente a 14:00 en la 6.2). `scripts/tests-completos.sh` se mide sin contenedores (`docker compose down`); en el equipo de Pedro el motor de Docker corre dentro de WSL, sin Docker Desktop. La completa varía entre días sin cambios de código (la app, que no cambió, entre 3:06 y 4:25): se compara la parte que cambia, no el total. Tras la 6.4, 18 min 09 s: núcleo 3.167 tests en 13:00, app 287 en 4:16 y notebooks 0:53.

## Registro de decisiones y preguntas abiertas

Decisiones tomadas durante el brainstorming del 27 de octubre de 2026; las 34 a 46 son del hito 4 (sesiones conceptuales del 5 y el 6 de noviembre; el detalle está en su pestaña), la 47, de la tarea de proceso P.1, y las 48 a 66, del hito 6 (H6-1 a H6-19, con sus ADR desde la tarea 6.6); cada una se convertirá en un ADR en `docs/decisiones/`.

| # | Decisión | Motivo |
| --- | --- | --- |
| 1 | El laboratorio sirve a tres objetivos a la vez: analítica, modelos y escenarios | Alcance pedido |
| 2 | Tipo y tamaño de centro parametrizables; se empieza por un hospital general medio | Empezar simple sin cerrar la puerta |
| 3 | Profesionales como pools anónimos en la v0 | Simplicidad del motor; identificadores preparados para la v3 |
| 4 | Motivos de consulta agrupados (\~17); CIE-10 opcional más adelante | Coste de calibración |
| 5 | Simulación de eventos discretos con SimPy y pacer propio | Velocidad ajustable en caliente |
| 6 | Log de eventos como fuente de verdad; ground truth separado | Docencia, ML sin leakage, validación |
| 7 | Un flujo aleatorio por fuente de azar | Números aleatorios comunes en experimentos |
| 8 | Claude Code escribe el código tras una sesión conceptual; revisión conjunta | Modo de trabajo elegido |
| 9 | Librerías directamente, sin reimplementar fundamentos | Modo de aprendizaje elegido |
| 10 | Apache Kafka 4 (KRaft) como broker, con Redpanda Console como interfaz | Aprender el estándar de la industria con licencia abierta; cambiar a Redpanda es trivial |
| 11 | GitHub Flow con pull requests, CI obligatorio y fusión reservada a Pedro | Red de seguridad para código escrito por IA; control humano de main |
| 12 | Desarrollo en Windows con WSL2, Docker Desktop y Cursor conectado a WSL, confirmado en el hito 0; WSL y Claude Code en canal estable | Entorno local parecido al CI en Linux |
| 13 | Centro base de 300 urgencias al día, rango 200–400 | Hospital general de tamaño medio |
| 14 | Repositorio público en GitHub, con ruleset que protege main | Los rulesets solo están disponibles en repositorios públicos del plan gratuito; datos sintéticos, sin secretos |
| 15 | Código, nombres y docstrings en inglés; documentación, especificaciones y commits en español; claves de configuración en español | Estándar del código; la documentación sirve al aprendizaje en el idioma de Pedro |
| 16 | Métricas derivadas de los registros por cliente, sin traza aparte en el modelo | Una única fuente de verdad: hechos registrados y estados derivados, como en el log de eventos |
| 17 | Tests estadísticos marcados como slow: el hook de Claude Code los omite y el CI los ejecuta todos | Ciclo de trabajo rápido sin renunciar a la validación estadística. Matizada por la 47: el Stop ejecuta la rápida con sello y los slow corren antes del push y en el CI |
| 18 | Notebooks de Jupyter sin lógica propia, con nbstripout en pre-commit y nbmake en el CI en modo rápido | Explorar y aprender sin estado oculto ni salidas en git; Jupyter por ser el estándar frente a marimo |
| 19 | Perfiles de llegadas en TOML: repartos horario y semanal en porcentaje y factores mensuales de tasa, normalizados a media 1 en el código | Parámetros en términos que entiende un clínico; tomllib sin dependencias; la base conserva su significado |
| 20 | λ(t) continua: interpolación lineal periódica entre los centros de las horas; día, mes y Z cambian a medianoche; reloj sin cambio de hora | Sin saltos artificiales a las en punto; Λ exacta con trapecios |
| 21 | Llegadas por thinning de Lewis–Shedler, perezoso, con cota por día comprobada en cada candidata | Exacto sin integrar ni invertir Λ; funciona en vivo; la comprobación evita recortes silenciosos |
| 22 | Sobredispersión con un efecto diario Z gamma de media 1, parametrizado por el CV (6 %), con flujo propio y guardado como ground truth | El CV se traslada entre centros, a diferencia del índice de dispersión; Z queda disponible para validar modelos |
| 23 | Validación con cinco pruebas al nivel 0,01, Bonferroni dentro de a y de d, Pearson condicional y pruebas de potencia; la hipótesis sale del perfil | Cada prueba busca un error distinto; las falsas alarmas quedan en el 5 % al combinar pruebas; sin hipótesis independiente no hay potencia |
| 24 | Cada paciente es un proceso SimPy que recorre la máquina de estados; todo lo aleatorio del paciente se sortea al llegar, en orden fijo, con un flujo por fuente, detrás de una función de muestreo inyectable | Los estados son los yield; el paciente k es el mismo con cualquier plantilla (números aleatorios comunes); el hito 4 cambia el muestreo sin tocar el motor |
| 25 | Tres pools: triaje FIFO; boxes con prioridad (nivel, llegada) y desalojo solo del nivel 1 a pacientes de nivel mayor, con reanudación; médicos con prioridad sin desalojo. El box se retiene toda la estancia y el médico solo en las valoraciones | Reglas de flujo del diseño; el orden no depende de cuándo se pide el recurso; el box como cuello de botella realista |
| 26 | Plantilla por turnos (8–15, 15–22, 22–8) desde el hito 3, con reservas de capacidad que esperan a que el profesional termine | staffing\_changed y el dimensionado por turno están en la v0; un Resource no cambia de capacidad; nadie deja a un paciente a medias |
| 27 | Log JSONL con el sobre del diseño más sim\_time, event\_id determinista y hora con desfase fijo +01:00; box\_assigned y patient\_displaced en el catálogo; la reevaluación usa assessment\_started/ended | Reproducibilidad bit a bit; cálculos sin redondeos de reloj; la ocupación de boxes y médicos se deriva del log |
| 28 | Ground truth en ficheros aparte (episodios y días); el log no lleva campos fuera del catálogo, y un test lo comprueba | Verdad oculta separada; evita data leakage; validación con valores conocidos |
| 29 | Calentamiento y horizonte en días completos (2 y 14 por defecto); en batch el log es completo y las métricas usan la ventana | Régimen periódico sin estado estacionario; invariantes válidas en todo el fichero |
| 30 | Validación del motor por niveles: invariantes, leyes operacionales, M/G/1 y Mₜ/G/∞ de referencia, condiciones extremas y huella de regresión, al nivel 0,01 | Sin fórmula cerrada para el sistema completo, cada tipo de comprobación cubre errores que los otros no ven |
| 31 | App incremental: fase 1 en Streamlit al cerrar el hito 3, una tarea de app en los hitos siguientes y la aplicación completa (API y frontend propio) después del hito 6 o de la v0 | Ver el modelo pronto sin rehacer la app cuando cambien el paciente, los eventos y la arquitectura |
| 32 | Una ejecución es una carpeta resultados/ejecuciones/\<run\_id>/ con el log, el ground truth, la copia de la configuración y run.json, escrita por simulate\_run desde la CLI y desde la app | Los ficheros son la verdad, sin base de datos; cada ejecución se puede reproducir |
| 33 | Las variantes del centro se escriben con tomlkit conservando los comentarios, en resultados/variantes/; config/ guarda solo lo que se versiona a mano | Los comentarios explican cada clave; las pruebas no ensucian el repositorio |
| 34 | El hito 4 cubre población, motivo, gravedad, triaje con error, pruebas, duraciones, relojes y una primera calibración; el destino provisional no cambia, y abandono, destino, boarding y bucles de saturación van al hito 5 | Sin destino, boarding ni abandono, el ingreso, la estancia y la cola en días punta saldrían mal por construcción; los bucles necesitan el estado del servicio en el paciente |
| 35 | Solo adultos de 15 años o más, con cuatro bandas de edad (15–44, 45–64, 65–79, 80–99) y edad uniforme dentro de la banda | Los objetivos de triaje son de adultos; la pediatría pide su propio catálogo (v3) |
| 36 | `config/perfiles.toml` aparte de `centro.toml`, una tabla por motivo, unidades clínicas, factores opcionales neutros, claves desconocidas prohibidas y franjas propias | Hospital y población son preguntas distintas; perfiles intercambiables en la v3; nada derivado a mano |
| 37 | Los 17 motivos desde el principio, cada parámetro con su estado (calibrado, derivado u orientativo) y pesos base derivados del reparto del catálogo con `base_weights_for` | No hay fuente pública por motivo; el estado dice qué respaldo tiene cada número; los shocks no se renormalizan |
| 38 | Gravedad latente normal y triaje ordinal G + ε con ruido y sesgo; umbrales derivados una vez para el reparto asignado y escritos en el TOML, sin recalcularse al cargar; la prioridad usa el nivel asignado, y duraciones y pruebas, la gravedad real | Modelo del diseño; reproduce el infra y sobretriaje publicados; hace medible el daño del infratriaje; un escenario con más gravedad da más niveles urgentes |
| 39 | El nivel 1 asignado se clasifica en la puerta (triaje de duración 0, `circuito: "puerta"`, sin enfermera) y va directo al box; sin desalojo de médicos | El crítico no hace cola de triaje sin cambiar el orden de los eventos; el desalojo de médicos ahorraría un minuto a un paciente al día con una regla clínica sin datos (v1) |
| 40 | Tres relojes con nombre propio; cumplimiento Manchester desde la clasificación (C); pretriaje con indicador propio; nivel 1 sin porcentaje; cumplimiento por nivel real solo con ground truth | Antes del triaje no hay nivel; separa la cola de triaje de la de médicos; con el reloj A el nivel 2 no podía cumplir |
| 41 | Centro base realista, calibrado a horquillas observadas en `config/objetivos.toml`, con objetivos de ajuste y de comprobación; dos mandos indirectos con objetivos separados, la enfermería de triaje (pretriaje) y los médicos (tiempo hasta el médico), ajustados en ese orden; los boxes quedan fijos (30), y la sensibilidad de los mandos se mide antes de ajustar. Desde la tarea 4.6c, cada candidato se mide con la ventana anual (una réplica por mes) y la semilla de comprobación puede vetar la elección, no hacerla; después de un veto se confirma con 2028 | Un laboratorio que nunca incumple no sirve; plantilla y duraciones no son identificables sin la estancia, y plantilla y boxes tampoco con objetivos de tiempo hasta el médico; los médicos no mueven el pretriaje (1,4 minutos con la enfermería de antes); los objetivos del SAS son medias anuales, y una plantilla elegida con una semilla que falla con otra está en el borde por azar |
| 42 | Pruebas de cuatro tipos en una ronda, con un solo `test_ordered` (lista de pruebas) y un solo `test_resulted` (resultados) | Mismo comportamiento del paciente sin cambiar el contrato del log; un evento por tipo queda para versiones posteriores |
| 43 | Sorteos sincronizados: Gumbel-max para las categorías y z estándar transformadas para las variables continuas, con consumo fijo y un flujo por fuente (`child_streams(seed, 8)`) | Números aleatorios comunes también para escenarios clínicos: con la gripe cambia el 3,37 % de los pacientes, el mínimo posible, y no el 15,55 % |
| 44 | Modelo clínico opcional durante el hito (`profiles=None` usa el provisional) y por defecto en el cierre, cuando la app ya lo soporta; el `ProvisionalSampler` se queda para la validación del motor | `main` estable y `tests-app` obligatorio en todo el hito; la app no se rompe a mitad de camino |
| 45 | Con el modelo clínico, los pacientes de los niveles asignados de `espera_resultados_fuera` (`centro.toml`, `[4, 5]`) dejan el box al pedir las pruebas, esperan los resultados en una sala sin límite de capacidad y vuelven a pedir box con su misma clave de prioridad para la reevaluación; un evento nuevo en el catálogo versión 3. El provisional no cambia | El 64 % del tiempo de box era espera de resultados y saturaba los 30 boxes; en las urgencias reales los leves esperan fuera; la plantilla de médicos no puede calibrar una cola de boxes |
| 46 | La parada / crítico pasa al 0,3 % del catálogo con una gravedad alta y poco dispersa, para que casi todas sean nivel 1 real y asignado; pesos base, ruido y sesgo, umbrales y marginales de pruebas se rederivan y se escriben | Con el 0,54 % y la gravedad en el umbral, el 44 % de las paradas recibía nivel 2 y esperaba en la cola del triaje: el nivel 1 asignado del 0,4 % no dejaba sitio para todas |
| 47 | Tests por niveles según el punto del ciclo (candidata; ADR en la 4.9): ruff al editar y en pre-commit; los tests del área antes de cada commit; en el hook Stop, la rápida con sello solo de las suites afectadas y nada en modo plan; antes de cada push, scripts/tests-completos.sh; el CI completo en cada push. pytest-xdist solo en el núcleo y en local; la app y el CI en serie. Matiza la 17 | Con squash and merge solo llega a main el árbol final, que pasa N3 y el CI; la espera en tests rondaba las 3 h por tarea y queda por debajo de 50 min. xdist solo donde tarda como mucho el 60 % de la serie con los mismos resultados (tarea P.1, PR #52) |
| 48 | El hito 6 va antes que el 5; después el 5 y solo entonces el 7. Todo vale para cualquier versión del catálogo | Cambio de terreno tras el hito 4 y ver EDsim en vivo antes; el 6 no depende del 5. No construir persistencia ni dbt sobre un modelo sin abandono ni boarding |
| 49 | Código en el subpaquete `edsim.live` del núcleo; cliente `confluent-kafka` como extra opcional `edsim[kafka]`, importado solo en `live/kafka.py`, con test de frontera; `compose.yaml` en la raíz | El pacer y el motor por pasos son piezas del motor; solo el cliente es opcional, y se importa de forma perezosa para que todo el núcleo se importe y se pruebe sin él. librdkafka tiene productor idempotente y es la base de Quix Streams (hito 8) |
| 50 | Tres capas de tests: rápidos sin broker, slow como hoy, integración en `tests_integracion/` fuera de `testpaths` | Tests deterministas y en milisegundos; una marca de exclusión la anularía el `-m` del hook |
| 51 | Motor por pasos con `peek()` y `step()`; `run_engine` = avanzar hasta el horizonte; huellas intactas | `run(until)` es un bucle de `step()`; el directo necesita intercalar esperas sin cambiar el resultado |
| 52 | Pacer síncrono en un hilo; reloj inyectable (monótono para esperar, de pared solo para anclar); objetivos absolutos desde un ancla que se reancla al cambiar de velocidad o reanudar; esperas en tramos de 0,2 s; nunca salta eventos | Sin deriva acumulada (3,8 s al día con esperas relativas frente a 2 ms); sin hilos ni `asyncio`, nada que sincronizar; probado con un reloj falso |
| 53 | Control en vivo por el topic `ed.control` y `edsim directo control`; velocidad inicial por la CLI; sin `control_command` en el catálogo | La API FastAPI llegará después y publicará en el mismo topic; las órdenes del hito solo cambian el ritmo, así que el log sigue siendo igual al batch |
| 54 | Cuatro topics: `ed.patient.events` (3 particiones, clave `episode_id`), `ed.resource.events` (1, `recurso`), `ed.runs` (1, `run_id`) y `ed.control` (1, `run_id`); reparto por `episode_id` nulo o no; creados por `edsim directo preparar` y autocreación desactivada | Orden por episodio visible con varias particiones; regla válida para cualquier catálogo; un nombre mal escrito falla en vez de crear un topic |
| 55 | Productor idempotente con `acks=all` y `partitioner=murmur2_random`; al menos una vez de extremo a extremo con consumidores que descartan por `event_id`; si un mensaje no se entrega, el directo se para; `flush` al terminar; sin transacciones | Sin duplicados ni desorden por reintentos; mismo reparto que Java; el log no puede tener huecos silenciosos; las transacciones no aportan nada con un solo productor |
| 56 | El valor de cada mensaje es la línea del JSONL (mismos bytes); `ingest_time` nulo en el valor; hora de llegada = marca `LogAppendTime`; cabeceras `event_type` y `schema_version` | Solo el broker sabe cuándo llega un mensaje; «directo = batch» compara bytes; con `event_time` como marca, Kafka 4 rechazaría los mensajes a más de 1 h en el futuro y la retención borraría los de fecha pasada |
| 57 | JSON Schema 2020-12 generado del catálogo, un fichero por versión, escrito en `schemas/` con test «escritos = generados»; esquemas a mano para `ed.runs` y `ed.control`; sin registro de esquemas | Contrato legible para otros programas; patrón «derivado y escrito»; Avro y registro en la v1 (diseño) |
| 58 | Censo inicial = eventos del calentamiento de los episodios abiertos en W más los de recursos, en su orden; «abierto» con `TERMINAL_EVENTS` por versión de catálogo, contrastado con los procesos vivos | Sin contrato nuevo; vale para cualquier catálogo; el consumidor deriva el estado con el mismo código para censo y directo (event sourcing) |
| 59 | Dos arranques: con la fecha del perfil (reproducible) o anclado (`--anclar`: calienta hasta «ahora»); se mantiene el desfase fijo `+01:00` | Los tests necesitan el primero; el panel del hito 8, el segundo. La decisión 20 sigue en pie: el instante es correcto |
| 60 | Replay dentro del hito, con el mismo pacer, censo y productor | Cuesta poco con las piezas hechas y da al hito 7 un stream idéntico cada vez |
| 61 | Horizonte finito (`--dias`); al llegar, con `parar` o con Ctrl+C: mensaje `fin` y `flush` | Un directo siempre termina limpio y deja dicho por qué |
| 62 | Versiones fijadas con etiqueta exacta y comprobadas en la 6.1: hoy `apache/kafka:4.4.0`, Redpanda Console v3.13.1, `confluent-kafka` 2.16.x | El Kafka del portátil, el de Claude Code y el del CI son el mismo |
| 63 | Job `tests-kafka` en el CI con el mismo `compose.yaml`, obligatorio desde la 6.4 | La integración no depende de que alguien la ejecute en local; mismo Kafka que en el portátil |
| 64 | Etiqueta de cierre `v0.6-hito6`; la `v0.5-hito5` llegará después | La etiqueta nombra el hito, no el orden |
| 65 | El simulador no va en un contenedor en este hito: corre en WSL2 con `uv` y entra por el listener `EXTERNAL`; Compose levanta solo Kafka y la consola | Ciclo de desarrollo y tests igual que hoy; el contenedor del simulador llega con la API |
| 66 | `run_id` del directo = `r`, semilla, `_` y hora de arranque (o `--run-id`); el replay conserva el `run_id` y los `event_id` originales | Dos directos con la misma semilla no comparten `event_id`; reemitir la misma ejecución publica los mismos hechos |

### Preguntas resueltas

- **Entorno:** Windows. Propuesta para el hito 0: desarrollo dentro de WSL2 (Ubuntu), Docker Desktop con motor WSL2 y Cursor conectado a WSL, para que el entorno local se parezca al del CI (Linux). Se confirma al especificar el hito 0.
- **Nivel de partida:** Python y git aceptables; nociones de estadística sin conceptos avanzados. Las sesiones conceptuales explican la estadística desde la intuición (distribuciones, procesos de Poisson, intervalos de confianza) y dan por sabido lo básico de Python y git.
- **Calibración de llegadas:** se parte de un perfil horario y semanal típico de urgencias españolas (mínimo de madrugada, picos de mañana y tarde, lunes más cargado) y se contrasta con estudios publicados y estadísticas del SNS en el hito 2.
- **Volumen del centro base:** 300 urgencias al día por defecto, parametrizable en el rango 200–400.
