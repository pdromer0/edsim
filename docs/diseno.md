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
5. **Escenarios como configuración.** Centros, catálogos, escenarios y experimentos son ficheros YAML con semilla y `run_id` trazable. El motor no contiene conocimiento clínico.
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

```yaml
dolor_toracico:
  peso_base: 0.05
  modificadores: { edad: mayor_mas, hora: neutro, estacion: neutro }
  gravedad_latente: { media_por_edad: [...], dispersion: ... }
  pruebas: { ecg: 0.98, analitica: 0.90, rx_torax: 0.70 }
  destino: { depende_de: [gravedad, edad, resultado_pruebas] }
```

## Modelo estadístico y calibración

Los parámetros se escriben en términos que entiende un clínico (medianas, percentiles, porcentajes) y el motor los convierte internamente a los parámetros de cada distribución.

| Componente | Modelo | Parametrización |
| --- | --- | --- |
| Llegadas | Poisson no homogéneo, generado por *thinning* (Lewis–Shedler) | λ(t) = base × perfil horario × día × estación × evento |
| Sobredispersión | Efecto aleatorio diario gamma (media 1) | Recuentos diarios binomial negativa |
| Incidentes múltiples | Llegadas en grupo | N pacientes casi simultáneos, gravedad alta |
| Atributos | Categóricas log-lineales | Peso base × modificadores, renormalizado |
| Gravedad y triaje | Gravedad latente normal; triaje ordinal = gravedad + ruido cortada por umbrales | Ruido creciente con la saturación |
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

## Motor de simulación y reloj

El motor es una simulación de eventos discretos con SimPy que corre siempre en tiempo virtual (minutos); un marcapasos propio lo convierte en tiempo real cuando hace falta.

&#91;embedded content: arquitectura del motor · de la configuración a los destinos de datos\]

El log de eventos es la única salida del motor; el ground truth y la capa de observación se derivan de él.

- **SimPy:** cada paciente es un proceso que recorre la máquina de estados; los pools son recursos con prioridad (nivel de triaje, luego orden de llegada) y desalojo para el nivel 1.
- **Pacer propio:** permite cambiar la velocidad en caliente (×1, ×10, ×60), pausar, y anclar el reloj al calendario real para que el dashboard muestre "ahora".
- **Calentamiento:** 24–48 h simuladas a máxima velocidad sin emitir antes de empezar; más adelante, arranque desde una foto guardada.
- **Tres modos de uso:** directo (pacer, publica en vivo, admite shocks), batch (sin pacer, réplicas en paralelo) y replay (re-emite una ejecución guardada, determinista y rebobinable).
- **Un flujo aleatorio por fuente de azar:** llegadas, motivos, tiempos y paciencia tienen flujos independientes derivados de la semilla con `SeedSequence` de NumPy. Esto habilita los números aleatorios comunes en los experimentos.
- **Tres tiempos por evento:** `event_time` (cuándo ocurrió), `recorded_time` (cuándo se registró) e `ingest_time` (cuándo llegó al broker).
- **Plano de control:** API FastAPI para pausar, cambiar la velocidad, modificar la plantilla o lanzar shocks; cada orden queda registrada como evento.

## Modelo de datos

Todos los eventos comparten un sobre común y lo específico va en el `payload`; el ground truth se guarda aparte y una capa de observación introduce defectos realistas configurables.

### Sobre común

```json
{
  "event_id": "7f3c...",
  "event_type": "triage_completed",
  "schema_version": 1,
  "run_id": "exp042_rep07",
  "episode_id": "EP-2026-000184",
  "patient_id": "PT-0091223",
  "source_system": "triaje",
  "event_time": "2026-10-27T17:04:12+01:00",
  "recorded_time": "2026-10-27T17:11:40+01:00",
  "ingest_time": "2026-10-27T17:11:41+01:00",
  "payload": { "nivel": 3, "motivo": "dolor_toracico" }
}
```

### Catálogo de eventos v0

| Evento | Cuándo | Payload principal |
| --- | --- | --- |
| `patient_arrived` | Cruza la puerta | Medio de llegada |
| `patient_registered` | Admisión | Edad, sexo |
| `triage_started` / `triage_completed` | Triaje | Nivel, motivo |
| `assessment_started` / `assessment_ended` | Valoración médica | Pool, box |
| `test_ordered` / `test_resulted` | Pruebas | Tipo, resultado normal o alterado |
| `reassessment_done` | Reevaluación | — |
| `disposition_decided` | Decisión de destino | Destino |
| `bed_requested` / `bed_assigned` | Boarding | Servicio |
| `patient_departed` | Sale de urgencias | Destino final |
| `patient_left_wbs` | Abandono sin ser visto | Estado en que estaba |
| `staffing_changed` | Cambio de turno o plantilla | Recurso, cantidad |
| `shock_started` / `shock_ended` | Evento de sistema | Tipo, intensidad |
| `control_command` | Orden desde la API | Comando |
| `system_snapshot` | Cada 5 minutos | Colas, ocupación, saturación |

### Topics

- `ed.patient.events`, con clave `episode_id` para conservar el orden por episodio.
- `ed.resource.events`, `ed.system.events`, `ed.snapshots` y `ed.control`.
- Esquemas en JSON Schema en la v0; Avro con un registro de esquemas (Apicurio o Karapace) más adelante.

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

```yaml
experimento: plantilla_tarde_invierno
base: hospital_medio_v0
duracion: { warmup_dias: 3, dias: 28 }
replicas: 30
semilla: 2026
variantes:
  control: {}
  medico_extra_tarde:
    recursos.medicos.turnos.tarde: +1
  medico_extra_y_gripe:
    recursos.medicos.turnos.tarde: +1
    shocks: [brote_gripe_moderado]
metricas: [espera_p90_por_nivel, estancia_media, abandono_pct, cumplimiento_manchester, ocupacion_boxes]
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
| Configuración | YAML validado con Pydantic | JSON Schema |
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

- `core`: simulador, API, Kafka, Redpanda Console y Postgres.
- `analytics`: dbt, DuckDB, Metabase y Jupyter.
- `realtime`: Grafana y consumidores de streaming.
- `ml`: MLflow y entorno de modelos.

El stack completo necesita unos 8–16 GB de RAM; `core` mucho menos.

### Repositorio y CLI

```
edsim/
├── sim/            # paquete del motor
├── configs/        # centros, catálogos, escenarios, experimentos
├── api/            # FastAPI de control
├── consumers/      # ingesta y streaming
├── dbt/            # bronce → plata → oro
├── dashboards/     # Grafana como código, Streamlit
├── ml/             # modelos
├── notebooks/      # ejercicios
├── docs/           # diseño, specs, ADRs, diario
└── docker/
```

```bash
edsim run --escenario hospital_medio_v0 --modo directo --velocidad 60
edsim experimento configs/experimentos/plantilla_tarde_invierno.yaml
edsim replay --run exp042_rep07 --velocidad 10
edsim shock --tipo brote_gripe_moderado --intensidad 1.3
```

### Calidad

Tests de invariantes (llegadas = salidas + dentro; ningún recurso por encima de su capacidad; ningún evento anterior a la llegada), tests de regresión con semilla fija y CI con GitHub Actions.

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

0. **Entorno:** Python con uv, git, Cursor, Claude Code, `CLAUDE.md`, pytest y pre-commit.
1. **Colas y SimPy:** eventos discretos, cola M/M/1 y ley de Little; validación contra la teoría.
2. **Llegadas:** Poisson no homogéneo, *thinning*, sobredispersión y validación estadística.
3. **Motor y eventos:** paciente, triaje, recursos con prioridad y log de eventos en JSONL.
4. **Perfiles clínicos:** catálogo de motivos, gravedad latente y primera calibración.
5. **Cierre del flujo:** abandono, destino, boarding simple y ground truth.
6. **Tiempo real:** pacer, Docker y Apache Kafka con Redpanda Console.
7. **Persistencia:** consumidor hacia Postgres/Timescale y capa de observación con defectos.
8. **Analítica:** dbt (medallón) y Grafana.
9. **Experimentos:** runner con réplicas, números aleatorios comunes y MLflow.
10. **Modelos:** casos de uso de ML, uno a uno.

### Versiones del modelo

- **v0:** un circuito de boxes, recursos en pool, llegadas con patrón horario y semanal.
- **v1:** consulta rápida (niveles 4–5), críticos (niveles 1–2), plantilla variable por turno.
- **v2:** observación, boarding realista, re-triaje y reconsultas en 72 h.
- **v3:** perfiles de centro intercambiables, profesionales individuales y constantes vitales.

## Metodología de trabajo con Claude Code y Cursor

Claude Code escribe el código; Pedro dirige, pregunta y revisa. Cada hito sigue el mismo ciclo, con el aprendizaje como prioridad.

1. **Sesión conceptual:** Claude explica qué se va a implementar y por qué (estadística, simulación, tecnología); Pedro pregunta hasta entenderlo.
2. **Especificación del hito:** alcance, criterios de aceptación y tests, en `docs/specs/`.
3. **Plan:** Claude Code propone el plan en modo plan antes de tocar código.
4. **Implementación:** Claude Code escribe en pasos pequeños, con un commit por paso.
5. **Revisión conjunta:** se recorre el diff explicando cada decisión; Pedro pide cambios o aclaraciones.
6. **Cierre:** tests en verde, nota en el diario de aprendizaje (`docs/diario/`) y ADR si hubo una decisión importante.

Se usan las librerías directamente, sin reimplementar fundamentos a mano; los conceptos se explican en la sesión y se profundiza bajo demanda.

### Herramientas

- **Cursor:** editor para leer, navegar, revisar diffs, depurar y trabajar con notebooks. Su IA propia no se usa al principio, para no mezclar flujos.
- **Claude Code:** agente en el terminal integrado de Cursor.

### Prácticas de desarrollo con IA que se introducen por el camino

- `CLAUDE.md` como memoria del proyecto: convenciones, comandos y modo de trabajo.
- Modo plan antes de codificar.
- Tests como barandilla, acordados antes del código.
- Tareas pequeñas, commit por paso y revisión de cada diff.
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
| 4 | Implementar código y tests | Claude Code | Pasos pequeños |
| 5 | Comprobar tras cada cambio | Automático | Hooks de Claude Code: linter y tests rápidos |
| 6 | Commit local | Claude Code | Mensaje estándar: `feat(sim): cola M/M/1 con SimPy` |
| 7 | Comprobar al hacer commit | Automático | Hooks de pre-commit; si fallan, no hay commit |
| 8 | Revisar el diff | Pedro, con Claude explicando | Control de código de Cursor |
| 9 | Subir la rama | Claude Code, con permiso | `git push` |
| 10 | Abrir el pull request | Claude Code | `gh pr create` con resumen y checklist |
| 11 | Ejecutar el CI | Automático | GitHub Actions |
| 12 | Corregir si el CI falla | Claude Code | `gh run view` y vuelta al paso 4 |
| 13 | Aprobar y fusionar | Pedro | "Squash and merge" en GitHub |
| 14 | Limpiar | Automático y Claude Code | GitHub borra la rama; Claude vuelve a `main` y sincroniza |

- **Inicio de hito:** sesión conceptual y especificación en `docs/specs/`, redactada por Claude y aprobada por Pedro.
- **Cierre de hito:** nota en el diario, ADR si procede y etiqueta de versión (`v0.1-hito1`).
- **Configuración única (Pedro, guiado por Claude):** cuenta y repositorio en GitHub, `gh auth login` y protección de `main` (solo por pull request con CI en verde).
- **Permisos de Claude Code:** lectura y tests sin preguntar; subidas con permiso; fusión reservada a Pedro.
- **Aprendizaje de git:** en los hitos 0 y 1, Pedro ejecuta a mano los pasos de git (rama, commit, push, pull request) siguiendo las indicaciones de Claude; desde el hito 2 los ejecuta Claude Code.

## Registro de decisiones y preguntas abiertas

Decisiones tomadas durante el brainstorming del 27 de octubre de 2026; cada una se convertirá en un ADR en `docs/decisiones/`.

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
| 12 | Desarrollo en Windows con WSL2, Docker Desktop y Cursor conectado a WSL (a confirmar en el hito 0) | Entorno local parecido al CI en Linux |
| 13 | Centro base de 300 urgencias al día, rango 200–400 | Hospital general de tamaño medio |

### Preguntas resueltas

- **Entorno:** Windows. Propuesta para el hito 0: desarrollo dentro de WSL2 (Ubuntu), Docker Desktop con motor WSL2 y Cursor conectado a WSL, para que el entorno local se parezca al del CI (Linux). Se confirma al especificar el hito 0.
- **Nivel de partida:** Python y git aceptables; nociones de estadística sin conceptos avanzados. Las sesiones conceptuales explican la estadística desde la intuición (distribuciones, procesos de Poisson, intervalos de confianza) y dan por sabido lo básico de Python y git.
- **Calibración de llegadas:** se parte de un perfil horario y semanal típico de urgencias españolas (mínimo de madrugada, picos de mañana y tarde, lunes más cargado) y se contrasta con estudios publicados y estadísticas del SNS en el hito 2.
- **Volumen del centro base:** 300 urgencias al día por defecto, parametrizable en el rango 200–400.
