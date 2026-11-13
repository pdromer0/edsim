# Hito 7 — Persistencia

> **Estado:** especificación aprobada el 13 de noviembre de 2026; sin empezar. El original está en este repositorio.

Al terminar el hito 7, EDsim produce datos **imperfectos, como los de un hospital real**, los **guarda en una base de datos** y puede **decir exactamente en qué se equivocan**. El motor sigue dando la verdad. Una pieza nueva, el **simulador del registro clínico**, la convierte en **lo registrado**: lo que el personal anota, con retrasos, duplicados, olvidos y errores. Lo registrado viaja por Kafka hasta Postgres con TimescaleDB, y una comparación dice qué le pasó a cada hecho y cuánto se desvían los indicadores.

Es una especificación didáctica, con el formato de las de los hitos 5 y 6: cada pieza explica para qué sirve, cómo funciona, cómo se usa en EDsim y cómo aprender más. Las decisiones son candidatas (H7-n) y su número definitivo es 83 + n (H7-1 = 84, H7-16 = 99); la tarea de cierre escribe sus ADR 0084 a 0099. La sesión conceptual fue el 13 de noviembre de 2026, y la implementación empieza con la etiqueta `v0.5-hito5`.

## Objetivo y alcance

Al cerrar el hito 7:

```bash
uv run edsim motor simular --run-id r2026                         # la verdad, como hoy
uv run edsim registro generar r2026 --perfil realista             # lo registrado, en la carpeta de la ejecución
uv run edsim registro comparar r2026 --perfil realista            # qué pasó con cada hecho y cuánto se desvían los indicadores
docker compose up --wait && uv run edsim almacen preparar         # Kafka, Postgres y las tablas
uv run edsim directo reemitir r2026 --registro realista --velocidad max
uv run edsim almacen consumir --run r2026_realista_s2026          # lo registrado, en la tabla bronce
uv run edsim registro comparar r2026 --perfil realista --postgres # la misma comparación, leyendo de Postgres
```

**Por qué ahora.** El modelo v0 está cerrado (hitos 3 a 5) y el hito 6 ya publica la verdad por Kafka, pero nadie la guarda. Un laboratorio de analítica necesita tres cosas que aún no tiene: datos con los fallos de un hospital, un sitio donde consultarlos con SQL y las soluciones del examen para saber cuánto se equivocan. La persistencia y la analítica (hito 8) se construyen sobre el modelo v0 completo, como pedía la decisión 48.

**Dentro del alcance**

- **Simulador del registro clínico** (H7-1 a H7-5): una función pura de la verdad que mete ocho despistes (retraso, desorden, duplicado, campo vacío, valor erróneo, olvido, reloj desajustado y corrección tardía), con tres perfiles (limpio, realista y hostil), una semilla propia, registros renumerados y una libreta de soluciones (`defectos.csv`).
- **Lo registrado en el directo y en la reemisión** (H7-2): con `--registro PERFIL`, solo viaja lo registrado; lo registrado en directo es igual, byte a byte, a lo registrado por lotes.
- **Postgres con TimescaleDB** (H7-6, H7-7, H7-9): en `compose.yaml`, con la tabla `bronce.eventos` partida por la hora de llegada y migraciones SQL propias.
- **El consumidor** (H7-8): de Kafka a la tabla bronce, al menos una vez con inserción idempotente, con `ingest_time` desde la marca `LogAppendTime`.
- **La comparación** (H7-13): conciliación exacta e indicadores ingenuos, en Python, igual con ficheros que con Postgres.
- **Tests** (H7-10) en tres capas, con el job `tests-integracion` (antes `tests-kafka`) en el CI.
- **Proceso** (H7-15): la tarea 7.0, con siete mejoras del flujo.
- **Notebook** `07_persistencia.ipynb`, ADR 0084 a 0099 y etiqueta `v0.7-hito7`.

**Fuera del alcance**

| Qué | Adónde va |
| --- | --- |
| Limpiar lo registrado (deduplicar, aplicar correcciones), capas plata y oro con dbt | Hito 8 |
| Plata con la forma de las tablas de un HIS (H7-11) | Hito 8 |
| La verdad en Postgres (esquema `verdad`) y los permisos por capa (H7-12) | Hito 8 |
| Consumidores con Quix Streams, KPIs por ventana, Grafana | Hito 8 |
| Parquet y DuckDB para el camino por lotes | Hito 8 o 9 |
| Cambios en la app: página del registro clínico, lectura de bronce, directo en vivo, fantasmas en el Replay (H7-14) | Fase 2 de la app (#122) |
| Un HIS simulado con su base de datos transaccional y CDC (H7-11) | Backlog (#123) |

Las tareas con código empiezan con `v0.5-hito5`. Las implementa Claude Code: las de Kafka y Postgres necesitan Docker, y el resto va en la nube (H7-15). Claude Code ejecuta git (rama, commits, push y PR) y Pedro siempre fusiona.

## Cómo encajan las piezas

El motor no cambia: sigue escribiendo la verdad. Lo nuevo está a su salida (el registro clínico), al otro lado de Kafka (el consumidor y Postgres) y al final (la comparación).

```mermaid
---
title: "El hito 7: la verdad se registra con despistes, viaja por Kafka y se guarda en Postgres"
---
flowchart LR
    motor["motor<br/>(sin cambios)"] --> verdad[("la verdad<br/>eventos.jsonl y ground truth")]
    verdad --> registro["simulador del<br/>registro clínico<br/>perfil + semilla"]
    registro --> libreta[("libreta<br/>defectos.csv")]
    registro --> registrado[("lo registrado<br/>registrado.jsonl")]
    registro -->|"directo o reemisión<br/>con --registro"| kafka["Kafka"]
    kafka --> consumidor["consumidor<br/>guarda y después apunta"]
    consumidor --> bronce[("Postgres + TimescaleDB<br/>bronce.eventos")]
    verdad --> comparar["comparación<br/>conciliación e<br/>indicadores ingenuos"]
    libreta --> comparar
    registrado --> comparar
    bronce --> comparar
    classDef destacado fill:#1f6feb26,stroke:#1f6feb,stroke-width:2px
    class registro,libreta,registrado,consumidor,bronce,comparar destacado
```

En azul, lo nuevo del hito 7.

La verdad nunca pasa por Kafka cuando hay registro clínico: por Kafka solo viaja lo registrado (H7-2). Sin la opción `--registro`, el directo publica la verdad como en el hito 6, y todo lo del hito 6 sigue igual.

## Sesión conceptual resumida

La sesión conceptual está escrita en las piezas 1 a 6; esta tabla es el resumen de referencia.

| Concepto | Qué hay que entender | Pieza |
| --- | --- | --- |
| La verdad y lo registrado | El motor sabe lo que pasó; el hospital solo sabe lo que alguien anotó | 1 |
| Los ocho despistes | Retraso, desorden, duplicado, campo vacío, valor erróneo, olvido, reloj desajustado y corrección tardía | 1 |
| Tres horas por registro | Del hecho (`event_time`), de anotación (`recorded_time`) y de llegada a Kafka (`ingest_time`) | 1 |
| Fuga de información | Numerar lo registrado como la verdad delataría los olvidos y los duplicados | 1 |
| El truco del dado | Un sorteo por registro y despiste; el perfil solo pone el umbral, y lo que falla en el realista también falla en el hostil | 2 |
| Base de datos relacional y de series temporales | Postgres guarda tablas que se consultan con SQL; TimescaleDB las parte por tiempo | 3 |
| Arquitectura medallón | Bronce (tal como llega), plata (limpio) y oro (para analizar) | 3 |
| Tablas de estado frente a registro de eventos | Un HIS sobrescribe; un registro de eventos añade y guarda la historia | 3 |
| Al menos una vez | Guardar y después apuntar: nunca se pierde nada, pero se puede leer dos veces | 4 |
| Inserción idempotente | Una clave única hace que guardar dos veces lo mismo sea como guardarlo una | 4 |
| Dos clases de duplicados | El doble clic del hospital (dos registros) frente a la relectura del consumidor (el mismo registro) | 4 |
| Migración | Un fichero SQL numerado que lleva la base de datos de una versión a la siguiente | 5 |
| Conciliación | Cada hecho y cada registro, clasificados, con una cuenta que cuadra exacta | 6 |
| Sesgo de los datos sucios | Un indicador calculado sobre lo registrado se desvía del de la verdad | 6 |

## Pieza 1 — El simulador del registro clínico

### Para qué sirve

Para practicar analítica de verdad hacen falta datos con los fallos que tiene un hospital. La enfermera teclea el triaje diez minutos tarde, el médico documenta la valoración cuando acaba la guardia, alguien hace doble clic, un alta no se registra nunca. Un analista se pasa media vida peleándose con eso, y hasta este hito EDsim le daba datos limpios. El simulador del registro clínico mete esos fallos a propósito y apunta cada uno, así que el laboratorio tiene algo que ningún hospital tiene: las soluciones del examen.

### Cómo funciona

**La imagen.** El motor es una cámara que lo graba todo al segundo y sin errores: **la verdad**. El registro clínico es el personal del hospital tecleando en el ordenador lo que ve: **lo registrado**.

**Lucía, un martes por la tarde.** Así pasa de verdad, y así lo registra un hospital «realista»:

| Hecho verdadero | Hora real | Qué queda registrado | Despiste |
| --- | --- | --- | --- |
| Lucía llega | 17:00:00 | Llegada a las 17:00:00 | Ninguno |
| La registran en admisión | 17:02:30 | Registro a las 17:02:30 | Ninguno |
| Termina el triaje: nivel 3 | 17:04:12 | La enfermera lo teclea a las 17:11:12; el PC de triaje va 2 min adelantado, así que dice «hecho a las 17:06:12, anotado a las 17:13:12». Además, nivel 4 | Retraso, reloj desajustado y valor erróneo |
| — | — | A las 19:26:12 alguien corrige el nivel: era 3 | Corrección tardía |
| La ve el médico | 17:40:00 | La valoración aparece dos veces (doble clic) | Duplicado |
| Sale con el alta | 18:55:00 | Nada: nadie registró el alta. Lucía parece seguir en urgencias, como un «fantasma» | Olvido |

**Los ocho despistes.**

| Despiste | Qué pasa | En los datos se ve… |
| --- | --- | --- |
| Retraso | Se anota después de que ocurra | `recorded_time` posterior a `event_time` |
| Desorden | Por el retraso, un registro llega después que otro de un hecho posterior | Registros fuera de orden. No tiene parámetro: sale solo del retraso |
| Duplicado | Doble clic | Dos registros iguales, cada uno con su número |
| Campo vacío | No se rellena un campo | Un campo del `payload` a `null` |
| Valor erróneo | Se teclea mal | Nivel, edad, motivo o destino cambiados |
| Olvido | Nadie lo registra | Falta el registro (un alta olvidada deja un «fantasma») |
| Reloj desajustado | El ordenador de un sistema va adelantado o atrasado | Todas las horas de ese sistema desplazadas lo mismo |
| Corrección tardía | Alguien arregla un valor erróneo más tarde | Un registro `record_corrected` que dice cuál era el valor |

**Tres horas por registro.** Hasta este hito, `event_time` y `recorded_time` eran iguales e `ingest_time` era nulo. Con el registro clínico:

| Hora | Qué es | Lucía (triaje) |
| --- | --- | --- |
| Del hecho (`event_time`) | Cuándo dice el sistema que pasó, con su reloj | 17:06:12 (17:04:12 + 2 min de reloj) |
| De anotación (`recorded_time`) | Cuándo se tecleó, con el reloj del sistema | 17:13:12 (17:11:12 + 2) |
| De llegada (`ingest_time`) | Cuándo llegó a Kafka; la pone Kafka, no el simulador | Pieza 4 |

`sim_time` pasa a significar **el minuto de simulación en que el sistema escribe el registro**. En la verdad coincide con el de siempre, porque allí se escribe en el instante del hecho; en lo registrado es el instante real de la anotación (1.031,2 min en el triaje de Lucía, sin el desfase del reloj). Por eso el pacer del hito 6 no cambia: sigue esperando por `sim_time`, y el desorden sale solo.

**Las soluciones no van dentro del examen.** Los `event_id` de la verdad van numerados (`r2026-000000001`, `r2026-000000002`…). Si lo registrado conservara esa numeración, un hueco delataría un olvido y una marca delataría un duplicado. Es la misma fuga que evitó la decisión 28 con el ground truth. Por eso lo registrado es una **ejecución derivada**, con su propio `run_id`, y sus registros se **renumeran** en el orden en que se anotan.

**El corte.** Lo que se anotaría después del final de la simulación no se escribe: queda «pendiente al corte», como en una extracción real de datos hecha a una hora concreta.

### En EDsim

- Paquete nuevo `edsim.clinical_record`: una función pura `record(verdad, perfil, semilla, horizonte)` que devuelve lo registrado, la libreta y los datos de la ejecución derivada. No usa SimPy ni el motor.
- Lo registrado no son `Event`: un `Event` valida su `payload` contra el catálogo, y un campo vacío no lo cumple. Es un tipo propio, `Record`, con el mismo sobre y un `payload` sin validar, que se escribe con el mismo orden de claves que `to_json`.
- Funciona con cualquier versión del catálogo (1 a 4), como todo desde la decisión 48.
- Los despistes solo tocan los eventos de pacientes. Los de recursos (`staffing_changed`) pasan tal cual, renumerados: la plantilla no se teclea a mano.
- La verdad de la carpeta no cambia nunca. Lo registrado va en una subcarpeta propia de la ejecución.

### Para aprender más

- Ward, Self y Froehle, «Effects of Common Data Errors in Electronic Health Records on Emergency Department Operational Performance Metrics: A Monte Carlo Simulation», *Academic Emergency Medicine*, 2015: lo mismo que hace este hito, con datos reales. Mete errores de cuatro tipos en las horas de un servicio de urgencias y mide cuánto cambian los indicadores.
- Gordon, Flottemesch y Asplin, «Accuracy of Staff-Initiated Emergency Department Tracking System Timestamps in Identifying Actual Event Times», *Annals of Emergency Medicine*, 2008: un observador apunta la hora real de cada hecho y la compara con la del sistema.
- Martin Kleppmann, *Designing Data-Intensive Applications*, capítulo 11 (tiempo del evento frente a tiempo de proceso).

## Pieza 2 — Perfiles y azar: el truco del dado

### Para qué sirve

Para elegir cuánto se equivoca el hospital y comparar escenarios: el mismo día, registrado por un hospital cuidadoso y por uno desastroso. Y para que esa comparación mida el efecto del perfil, no el de la suerte.

### Cómo funciona

**Tres perfiles, como un dial.**

- **Limpio:** sin despistes. Lo registrado coincide con la verdad salvo los identificadores; sirve para comprobar que todo el circuito funciona (el test de punta a punta del hito).
- **Realista:** las tasas de un hospital normal. Cada valor lleva su estado (calibrado, derivado u orientativo), como los perfiles clínicos (decisión 37).
- **Hostil:** exagerado a propósito, para poner a prueba la limpieza del hito 8.

**El truco del dado.** Cada evento verdadero tira un dado (un número uniforme entre 0 y 1) por cada tipo de despiste, siempre los mismos y en el mismo orden, sea cual sea el perfil. El perfil solo pone el umbral: hay despiste si el dado sale por debajo de la tasa.

Ejemplo: el triaje de Lucía saca 0,03 en el dado del valor erróneo. Con el perfil realista (tasa 0,01) no hay error; con el hostil (0,07), sí. Y como el dado es el mismo, **todo lo que falla en el realista también falla en el hostil**. Al comparar perfiles, la diferencia viene del perfil. Es la idea de los números comunes del hito 4 (decisión 43).

**Semilla propia.** Por defecto, la de la ejecución; se puede cambiar para registrar la misma verdad de varias maneras. Con la misma semilla salen siempre los mismos despistes.

### En EDsim

- `config/registro_clinico.toml`, con una tabla por perfil y claves desconocidas prohibidas, como `perfiles.toml`. Formato y valores, en «Especificación: perfiles».
- Un flujo aleatorio propio, el hijo 10 de `child_streams(semilla del registro, 11)`, con consumo fijo por evento verdadero. El motor usa los hijos 0 a 9 (hito 5): con la semilla por defecto, el registro nunca comparte un flujo con el motor.

### Para aprender más

- Law, *Simulation Modeling and Analysis*, capítulo de técnicas de reducción de varianza: números aleatorios comunes.
- [hito-4.md](hito-4.md#motivos-de-consulta), «Motivos de consulta»: Gumbel-max y por qué con la disnea × 1,5 solo cambia el 3,37 % de los pacientes.

## Pieza 3 — Postgres, TimescaleDB y la capa bronce

### Para qué sirve

Kafka es como el correo: transporta mensajes, pero no es un archivo donde buscar con SQL. Hace falta una base de datos donde lo registrado se guarde y se consulte, y que el hito 8 (dbt y Grafana) pueda leer.

### Cómo funciona

**Postgres** es una base de datos relacional: tablas que se consultan con SQL. Es la de código abierto más usada y la más estándar, así que lo aprendido sirve en cualquier sitio. **TimescaleDB** es una extensión de Postgres para datos con hora: parte una tabla en trozos por tiempo (una *hypertable*) sin que se note al consultarla, y añade funciones como `time_bucket` para agrupar por intervalos. Lo aprovechará sobre todo el hito 8.

**Alternativas consideradas** (sesión conceptual):

| Opción | A favor | En contra |
| --- | --- | --- |
| Postgres + TimescaleDB (elegida) | SQL estándar; funciones de tiempo; Grafana y dbt lo leen de serie | Para analítica muy grande, más lento que una base de datos de columnas; la regla de las claves únicas |
| Postgres solo | Menos piezas | Las funciones de tiempo, a mano; Timescale se podría añadir después |
| ClickHouse | Columnas, muy rápido para analítica; lee de Kafka | Peor para corregir registros; dialecto propio |
| DuckDB con Parquet | Analítica en un fichero, sin servidor | No es un servidor al que muchos escriban a la vez (queda para el camino por lotes) |
| InfluxDB y similares | Métricas numéricas | No relacionales: los eventos con su `payload` encajan mal |
| MongoDB | Guarda el JSON tal cual | Sin SQL estándar; dbt y Grafana encajan peor |

**La arquitectura medallón.** Los datos pasan por tres capas:

- **Bronce:** tal como llegan, como una fotocopia. Es este hito.
- **Plata:** limpios y con forma: duplicados quitados, correcciones aplicadas, tipos comprobados. Hito 8.
- **Oro:** para analizar: KPIs por hora y turno, tablas de hechos y dimensiones. Hito 8.

**Tablas de estado frente a registro de eventos.** Un HIS guarda tablas de estado (`paciente`, `episodio`, `triaje`, `prueba`…) que se van rellenando y sobrescribiendo: al corregir un nivel, el anterior se pierde. EDsim guarda un registro de eventos: cada hecho es una fila y una corrección es otra fila, así que queda la historia. El diseño tiene las dos formas en capas: los eventos en bronce y las tablas tipo HIS en plata, derivadas de los eventos (decisión 6). En un hospital real, analítica casi nunca recibe eventos, sino una extracción de las tablas del HIS: por eso plata imitará la estructura de un HIS (H7-11), y el escenario «extraer de un HIS simulado con CDC» queda en el Backlog.

### En EDsim

- `compose.yaml` añade el servicio `postgres` con la imagen `timescale/timescaledb` en una etiqueta exacta (`X.Y.Z-pg17`), fijada y comprobada en la 7.5, como Kafka en la 6.1 (decisión 62). La imagen no tiene etiqueta `latest` a propósito.
- La tabla `bronce.eventos` es una hypertable partida por `ingest_time`, la hora de llegada: la pone Kafka, siempre existe y su reloj es fiable. Partirla por `event_time` dejaría que el reloj desajustado de la pieza 1 decidiera dónde se guarda cada registro.
- **La regla de Timescale:** toda clave única de una hypertable tiene que incluir la columna por la que se parte. Por eso la clave es (`event_id`, `ingest_time`) y no `event_id` solo (pieza 4).

### Para aprender más

- [TimescaleDB: claves primarias, tiempo y unicidad](https://www.tigerdata.com/docs/learn/data-model/primary-keys-time-and-uniqueness) y [la imagen de Docker](https://hub.docker.com/r/timescale/timescaledb).
- [Databricks: arquitectura medallón](https://docs.databricks.com/aws/en/lakehouse/medallion).
- Kleppmann, *Designing Data-Intensive Applications*, capítulos 3 (almacenamiento) y 11 (flujos y bases de datos).

## Pieza 4 — El consumidor: al menos una vez e inserción idempotente

### Para qué sirve

Para llevar cada registro de Kafka a Postgres sin perder ninguno y sin guardar ninguno dos veces, aunque el consumidor se caiga a mitad.

### Cómo funciona

**El cartero.** El consumidor es como un cartero que mete las cartas en el archivo y apunta en su libreta hasta qué carta ha llegado. A ese número de la libreta Kafka lo llama *offset*. Hace dos cosas, **guardar** y **apuntar**, y no puede hacerlas a la vez:

| Orden | Si se cae entre medias… | Resultado |
| --- | --- | --- |
| Apuntar y después guardar | Al volver, cree que ya la guardó | **Pierde** la carta: «como mucho una vez» |
| Guardar y después apuntar | Al volver, la lee otra vez | La guardaría **dos veces**: «al menos una vez» |

La solución habitual es la segunda, más **un archivo que rechaza lo que ya tiene**: cada registro tiene una clave única, y si llega otra vez, Postgres lo ignora (`INSERT … ON CONFLICT DO NOTHING`). Así nunca se pierde nada y nunca se repite nada. Es «al menos una vez más inserción idempotente», el patrón estándar para escribir de Kafka a una base de datos.

**Dos clases de duplicados.** El doble clic del médico son **dos registros distintos**, con números distintos: bronce guarda los dos y plata los deduplicará. Una relectura del consumidor es **el mismo registro**, con el mismo número y la misma hora de llegada: bronce la ignora. Y si se reemite dos veces la misma ejecución, bronce guarda las dos publicaciones, porque llegaron en momentos distintos: bronce es «tal como llegó».

**Por lotes.** El consumidor no hace un viaje al archivo por cada carta: guarda hasta 500 en una transacción y después apunta. El razonamiento es el mismo.

**La hora de llegada.** Los topics de EDsim usan la marca `LogAppendTime` (decisión 56): Kafka sella cada mensaje con la hora a la que llega. El consumidor la copia en la columna `ingest_time` sin tocar el mensaje, que sigue llevando `ingest_time` nulo. Comparar `ingest_time` con `recorded_time` solo tiene sentido en un directo anclado a ×1: en una reemisión rápida, el triaje es de enero y la llegada, de esta mañana.

**Alternativa para el futuro.** Apuntar los offsets en Postgres, en la misma transacción que el lote, daría «exactamente una vez» sin depender de la clave. Es más complejo y aquí no hace falta: la clave ya resuelve los repetidos.

### En EDsim

- Biblioteca `confluent-kafka`, como en el hito 6: el orden «guardar y después apuntar» se ve y se controla a mano. Quix Streams, que lo esconde, llega en el hito 8.
- `psycopg` 3 para hablar con Postgres, como extra opcional `edsim[postgres]`, importado solo en un módulo (el patrón de la decisión 49).
- Grupo fijo `edsim-bronce`: si se para y se vuelve a lanzar, sigue donde lo dejó.

### Para aprender más

- [Confluent: el consumidor de Kafka y la gestión de offsets](https://docs.confluent.io/platform/current/clients/consumer.html).
- [Conduktor: semánticas de entrega del consumidor](https://docs.conduktor.io/learn/advanced/consumers/delivery-semantics).
- [Postgres: `INSERT … ON CONFLICT`](https://www.postgresql.org/docs/current/sql-insert.html) y [psycopg 3](https://www.psycopg.org/psycopg3/docs/basic/).
- La pieza 3 de [hito-6.md](hito-6.md#pieza-3--garantías-de-entrega): el productor idempotente, el otro lado de la misma garantía.

## Pieza 5 — Migraciones

### Para qué sirve

Para que tu Postgres, el del CI y el de los tests tengan siempre las mismas tablas, y para cambiarlas más adelante sin borrar datos.

### Cómo funciona

Una **migración** es un fichero SQL numerado que lleva la base de datos de una versión a la siguiente: `001` crea la tabla bronce, `002` le añadiría una columna. La base de datos guarda en una tabla qué migraciones ya aplicó, y al preparar solo aplica las que faltan, cada una en su transacción.

**Alternativas** (para el futuro, si crecen las migraciones): Alembic, el estándar en Python, ligado a SQLAlchemy; Flyway o Sqitch, herramientas externas. Aquí bastan unos pocos ficheros, y se ve el SQL tal cual.

### En EDsim

- Ficheros en `src/edsim/store/sql/` (`001_bronce.sql`, …), dentro del paquete.
- `edsim almacen preparar` los aplica, como `edsim directo preparar` crea los topics.
- Las tablas de plata y oro del hito 8 no son migraciones: las crea dbt.

### Para aprender más

- [Documentación de Alembic](https://alembic.sqlalchemy.org/) y [de Flyway](https://documentation.red-gate.com/flyway), para ver cómo lo resuelven las herramientas.

## Pieza 6 — Comparar con la verdad

### Para qué sirve

Para responder a dos preguntas que ningún hospital puede responder: qué le pasó a cada hecho y cuánto se equivocan los indicadores por culpa de los despistes.

### Cómo funciona

**1. La conciliación, exacta.** Cada hecho verdadero se registró bien, con despistes, se perdió o quedó pendiente al corte; cada registro es un hecho, un duplicado o una corrección. Con Lucía y otra paciente que llega a las 17:08 (el escenario L de «Tests y validación»):

| Hecho | Qué le pasó |
| --- | --- |
| Llegada de Lucía | Registrada bien |
| Admisión de Lucía | Registrada bien |
| Triaje de Lucía | Con despistes: tarde, reloj desajustado, nivel mal; corregido después |
| Llegada de la otra paciente | Registrada bien |
| Médico de Lucía | Registrado bien, y además duplicado |
| Alta de Lucía | Perdida |

Son 6 hechos (4 bien, 1 con despistes, 1 perdido) y 7 registros (4 bien, 1 con despistes, 1 duplicado y 1 corrección). La cuenta cuadra siempre, y es un test.

**2. El sesgo de los indicadores.** Unos pocos indicadores se calculan sobre lo registrado **a lo ingenuo**, como lo haría un analista con prisa (toma el primer registro, ignora los vacíos, no aplica las correcciones), y se ponen al lado de los mismos calculados sobre la verdad:

| Indicador | Verdad | Registrado | Lo estropea… |
| --- | --- | --- | --- |
| Tiempo hasta el triaje de Lucía | 4,2 min | 6,2 min | El reloj desajustado |
| Pacientes en urgencias a las 20:00 | 1 | 2 | El olvido: Lucía es un fantasma |
| Reparto por nivel del triaje | nivel 3 | nivel 4 | El valor erróneo, sin aplicar la corrección |

Con miles de pacientes, esto dice, por ejemplo, cuánto sale de alto el censo de la noche con un hospital realista.

### En EDsim

- Una sola implementación, en Python, en el paquete (`edsim.clinical_record.compare`). Recibe la verdad y lo registrado como listas, sin importarle si vienen de ficheros o de la tabla bronce. La usan la CLI, el notebook y los tests; la app, en su fase 2.
- La verdad no se carga en Postgres en este hito (H7-12): la comparación lee la verdad de los ficheros y lo registrado de donde se le diga.
- Los indicadores ingenuos no reutilizan las métricas de `edsim.runs`, que esperan datos limpios y fallarían con los sucios. Miden otra cosa: se aplican igual a la verdad y a lo registrado, y la diferencia es el sesgo.

### Para aprender más

- Ward, Self y Froehle (2015), citado en la pieza 1: los indicadores de intervalos cortos son los más sensibles a los errores de las horas.
- Las dimensiones de la calidad de datos (exactitud, completitud, unicidad, puntualidad, consistencia), en cualquier manual de gobierno del dato, por ejemplo el *DAMA-DMBOK*.

## Especificación: el registro clínico

### La función

`record(events, profile, seed, *, horizon, run_id) -> Recording`, en `edsim.clinical_record`:

- `events`: el log verdadero completo de una ejecución (los `Event` de `eventos.jsonl`, en su orden).
- `profile`: un perfil cargado de `config/registro_clinico.toml`.
- `seed`: la semilla del registro (por defecto, la de la ejecución).
- `horizon`: el horizonte en minutos (`días × 1.440`).
- `run_id`: el de la ejecución verdadera.
- Devuelve `Recording(run_id, records, notebook, info)`: el `run_id` derivado, los `Record` en orden de emisión, las filas de la libreta y los datos para `registro.json`.

Es pura: el mismo log, el mismo perfil y la misma semilla dan los mismos bytes. No importa SimPy ni el motor.

### Los despistes, uno a uno

Se aplican en este orden a cada evento verdadero de un paciente. El consumo del flujo es fijo: cada evento tira siempre los mismos números, en el mismo orden, aunque el perfil sea limpio o el despiste no se aplique.

| # | Despiste | Regla |
| --- | --- | --- |
| 1 | Olvido | Si `u_olvido < olvido`, el evento no se registra: no hay retraso, duplicado ni corrección para él |
| 2 | Retraso | Si `u_retraso < tasa` de su sistema, `retraso = cuantil lognormal [mediana, p90] de su sistema en z_retraso`; si no, 0. `sim_time` registrado = `sim_time` verdadero + retraso |
| 3 | Reloj desajustado | El desfase fijo de su sistema (minutos, puede ser negativo) se suma a `event_time` y a `recorded_time`, nunca a `sim_time` |
| 4 | Valor erróneo | Solo en `nivel`, `edad`, `motivo` y `destino`. Si el evento tiene alguno y `u_erroneo < erroneo`, se elige el campo con `u_campo_erroneo` y el valor con `u_valor_erroneo`: nivel ±1 dentro de 1 a 5 (en los bordes, hacia dentro); edad con las cifras invertidas (67 → 76; si son iguales o es de una cifra, +1); motivo, otro de los del catálogo; destino, otro de los de su versión |
| 5 | Campo vacío | Si el evento tiene algún campo en el `payload` no alterado por el 4 y `u_vacio < vacio`, se elige uno con `u_campo_vacio` y pasa a `null` |
| 6 | Corrección tardía | Solo si hubo valor erróneo. Si `u_correccion < tasa`, un registro `record_corrected` con `sim_time` = el del registro erróneo + cuantil lognormal [mediana, p90] en `z_correccion` |
| 7 | Duplicado | Si `u_duplicado < tasa`, una copia del registro ya alterado, con su propio `event_id` y `sim_time` = el del original + cuantil lognormal [mediana, p90] en `z_duplicado`. La corrección, si la hay, apunta solo al original |

El desorden no tiene regla: sale del retraso. El consumo por evento verdadero es de 13 números en este orden: `u_olvido`, `u_retraso`, `z_retraso`, `u_erroneo`, `u_campo_erroneo`, `u_valor_erroneo`, `u_vacio`, `u_campo_vacio`, `u_correccion`, `z_correccion`, `u_duplicado`, `z_duplicado` y uno de reserva. El plan de la 7.1 confirma el orden y el número; después no cambia, porque cambiarlo cambia todos los despistes de todas las ejecuciones.

Las tasas de los despistes 4 y 5 se aplican a los eventos que tienen campos elegibles; las demás, a todos los eventos de pacientes. Los eventos de recursos no tiran el dado: pasan tal cual, renumerados.

### Identidad, tiempos y orden

- **`run_id` derivado:** `<run_id>_<perfil>_s<semilla>`, por ejemplo `r2026_realista_s2026`. Cumple `validate_run_id` (hasta 64 caracteres); si no cabe, es un error antes de hacer nada.
- **Orden de emisión:** por `sim_time` registrado; en el empate, por el número del evento verdadero y después original antes que duplicado y que corrección. Es determinista.
- **`event_id`:** `<run_id derivado>-<número de emisión con nueve cifras>`, desde 1, sin huecos.
- **`event_time`:** el verdadero más el desfase de su sistema. **`recorded_time`:** la hora del `sim_time` registrado más el desfase. **`ingest_time`:** nulo, como siempre en el mensaje.
- **Corte:** un registro con `sim_time` ≥ horizonte no se escribe. Su hecho queda «pendiente al corte» (o, si es una corrección, «corrección pendiente»).
- **`record_corrected`:** `source_system` el del registro corregido; `episode_id` y `patient_id` los suyos; `schema_version` la del log; `payload` = `{"corrige": <event_id registrado del erróneo>, "campos": {<campo>: <valor verdadero>}}`. Su `event_time` es la hora de la corrección, con el desfase de su sistema.

### Escenario L (para los tests de la 7.1)

El log verdadero, con el minuto 0 a las 0:00 y horizonte 1.440:

| Evento verdadero | Episodio | `sim_time` | Hora | Payload |
| --- | --- | --- | --- | --- |
| L1 `patient_arrived` | EP-000001 | 1.020,0 | 17:00:00 | Medio del catálogo |
| L2 `patient_registered` | EP-000001 | 1.022,5 | 17:02:30 | Edad 54 |
| L3 `triage_completed` | EP-000001 | 1.024,2 | 17:04:12 | Nivel 3, motivo dolor torácico |
| L4 `patient_arrived` | EP-000002 | 1.028,0 | 17:08:00 | — |
| L5 `assessment_started` | EP-000001 | 1.060,0 | 17:40:00 | Inicial |
| L6 `patient_departed` | EP-000001 | 1.135,0 | 18:55:00 | Alta |

Con los dados forzados: L3 con retraso 7,0, nivel 3 → 4 y corrección a los 135 min; triaje con reloj +2; L5 duplicado a los 0,5 min; L6 olvidado. Lo registrado:

| # | Registro | `sim_time` | `event_time` | `recorded_time` |
| --- | --- | --- | --- | --- |
| 1 | L1 | 1.020,0 | 17:00:00 | 17:00:00 |
| 2 | L2 | 1.022,5 | 17:02:30 | 17:02:30 |
| 3 | L4 | 1.028,0 | 17:08:00 | 17:08:00 |
| 4 | L3, nivel 4 | 1.031,2 | 17:06:12 | 17:13:12 |
| 5 | L5 | 1.060,0 | 17:40:00 | 17:40:00 |
| 6 | L5, duplicado | 1.060,5 | 17:40:00 | 17:40:30 |
| 7 | `record_corrected`, corrige el 4: nivel 3 | 1.166,2 | 19:28:12 | 19:28:12 |

La cuenta: 6 hechos = 4 bien + 1 con despistes + 1 perdido + 0 pendientes; 7 registros = 4 bien + 1 con despistes + 1 duplicado + 1 corrección. **Variante del corte:** con la corrección a los 500 min, su `sim_time` sería 1.531,2 ≥ 1.440: no se escribe, la libreta dice «corrección pendiente» y hay 6 registros. **Variante del dado:** con `u_erroneo` = 0,03 en L3, el perfil realista (0,01) no altera el nivel y el hostil (0,07) sí.

El plan de la 7.1 recalcula cada hora con código independiente de la función probada, como siempre.

### La libreta (`defectos.csv`)

Una fila por registro escrito y una por cada hecho o corrección que no se escribió. Columnas:

| Columna | Qué es |
| --- | --- |
| `registro` | `event_id` registrado; vacío si no se escribió |
| `hecho` | `event_id` verdadero del que sale (en una corrección, el del hecho corregido) |
| `clase` | `bien`, `con_despistes`, `duplicado`, `correccion`, `perdido`, `pendiente` o `correccion_pendiente` |
| `retraso_min`, `desfase_min` | Minutos de retraso y de reloj |
| `campo_vacio` | El campo que quedó a `null`, o vacío |
| `campo_erroneo`, `valor_verdadero`, `valor_registrado` | El valor cambiado |
| `duplicado_de`, `corrige` | El `event_id` registrado del original |

**La cuenta que cuadra** (invariante, con test):

- hechos de pacientes en la verdad = `bien` + `con_despistes` + `perdido` + `pendiente`, contando solo filas de hechos (sin duplicados ni correcciones);
- registros escritos = `bien` + `con_despistes` + `duplicado` + `correccion`;
- correcciones escritas + `correccion_pendiente` = valores erróneos con corrección.

### Esquemas

`schemas/registro-v{1..4}.schema.json`, uno por versión del catálogo, generados del catálogo y escritos (patrón «derivado y escrito», decisión 57): el mismo sobre, cada campo del `payload` admite `null`, y `record_corrected` añadido. Test «escritos = generados». Los esquemas `eventos-v*` no cambian.

### En disco

Lo registrado de una ejecución va en `resultados/ejecuciones/<run_id>/registros/<perfil>-s<semilla>/`:

| Fichero | Qué es |
| --- | --- |
| `registrado.jsonl` | Los registros, una línea por registro, en orden de emisión |
| `defectos.csv` | La libreta |
| `registro_clinico.toml` | La copia del fichero de perfiles usado |
| `registro.json` | `run_id` derivado, `run_id` de origen, perfil, semilla, horizonte, huella de la copia y recuentos de la cuenta |

Lo escribe una función del paquete, `record_run(store, run_id, perfil, semilla)` en `edsim.runs` (aditiva en `__all__`), de forma atómica (carpeta temporal y renombrado), sin tocar los ficheros de la ejecución. No es una ejecución nueva: la regla de que solo `simulate_run` escribe ejecuciones sigue igual.

## Especificación: perfiles (`config/registro_clinico.toml`)

```toml
# Simulador del registro clínico (hito 7): cuánto se equivoca el hospital al anotar.
# Un perfil por tabla, con las mismas claves. Tasas en tanto por uno; tiempos en minutos,
# [mediana, p90] de una lognormal. Estado de cada valor: ver docs/specs/hito-7.md.

[limpio]
olvido = 0.0
vacio = 0.0
erroneo = 0.0
duplicado = { tasa = 0.0, minutos = [0.5, 2] }
correccion = { tasa = 0.0, minutos = [120, 720] }

[limpio.retraso]
admision = { tasa = 0.0, minutos = [1, 5] }
triaje = { tasa = 0.0, minutos = [5, 15] }
his = { tasa = 0.0, minutos = [10, 45] }
lab = { tasa = 0.0, minutos = [1, 3] }

[limpio.reloj]   # desfase fijo de cada sistema, en minutos
admision = 0
triaje = 0
his = 0
lab = 0

[realista]
# … mismas claves, con los valores de «Valores orientativos de partida» …

[hostil]
# … mismas claves …
```

**Reglas de carga:**

- Los tres perfiles existen y tienen exactamente las mismas claves; una clave desconocida o que falte es un error con su perfil y su clave.
- Los sistemas de `retraso` y `reloj` son exactamente los del catálogo: `admision`, `triaje`, `his` y `lab`.
- Tasas entre 0 y 1; `[mediana, p90]` con 0 < mediana < p90 (la lognormal de `edsim.lognormal`); desfases enteros o decimales, positivos o negativos.
- El perfil `limpio` tiene todas las tasas y todos los desfases a 0. Si no, es un error: «limpio» tiene que significar limpio.
- `edsim registro validar` comprueba el fichero, como `edsim perfiles validar`.

## Especificación: directo y reemisión con el registro clínico

- `edsim directo lanzar` y `edsim directo reemitir RUN_ID` aceptan `--registro PERFIL` y `--semilla-registro N` (por defecto, la de la ejecución) y `--registros FICHERO` (por defecto, `config/registro_clinico.toml`).
- **Con `--registro`, solo viaja lo registrado.** Los registros van a los mismos topics, con la misma clave (`episode_id`) y las mismas cabeceras; el valor es la línea de `registrado.jsonl`, byte a byte. El `run_id` publicado es el derivado.
- **El mensaje `inicio`** de `ed.runs` lleva un bloque nuevo, `registro`, con `origen` (el `run_id` verdadero), `perfil` y `semilla`; sin `--registro`, no lo lleva. El esquema escrito a mano de `ed.runs` se amplía.
- **La reemisión** lee la verdad de la carpeta, calcula lo registrado con `record` y lo emite con el mismo pacer: es el camino natural del hito. Si la carpeta ya tiene lo registrado con ese perfil y esa semilla, lo usa y comprueba que coincide.
- **El directo con el motor** necesita una sala de espera: el registro de un hecho del minuto 1.024,2 con 7 min de retraso no sale hasta el 1.031,2. Se suelta cuando el motor ya ha pasado su `sim_time` (todo hecho futuro tiene `sim_time` mayor o igual que el del motor, y sus registros también). La sala de espera es un montículo ordenado por la clave de emisión.
- **Censo:** son los registros con `sim_time` < W de los episodios que la verdad tiene abiertos en W, en orden de emisión. Así directo y lotes comparan los mismos registros.
- **«Directo = lotes» de lo registrado:** con la misma verdad, el mismo perfil y la misma semilla, lo publicado (censo y directo) es igual, byte a byte, a `registrado.jsonl` filtrado igual. Test lento, por versión de catálogo.
- `LiveTracker` y `read_run` siguen siendo para la verdad: lo registrado, con olvidos y desorden, no cumple sus comprobaciones de orden. El consumidor de lo registrado es el de bronce.

## Especificación: Postgres y el consumidor

### Compose

```yaml
  postgres:
    image: timescale/timescaledb:X.Y.Z-pg17   # versión exacta fijada en la 7.5
    environment:
      POSTGRES_USER: edsim
      POSTGRES_PASSWORD: edsim      # solo local; el repositorio no guarda secretos reales
      POSTGRES_DB: edsim
    ports:
      - "127.0.0.1:5432:5432"
    volumes:
      - edsim-postgres:/var/lib/postgresql/data
    healthcheck: …                  # pg_isready
volumes:
  edsim-postgres:
```

- Sin perfil: arranca siempre con `docker compose up`, como Kafka y la consola.
- Volumen con nombre: los datos sobreviven a `docker compose down`; para borrarlos, `docker compose down -v`. Kafka sigue sin volumen.
- La consola de Redpanda pasa también a `127.0.0.1:8080` (cierra el #91).

### Tablas (migración `001_bronce.sql`)

```sql
CREATE SCHEMA IF NOT EXISTS bronce;

CREATE TABLE bronce.eventos (
    event_id        text        NOT NULL,
    event_type      text        NOT NULL,
    schema_version  integer     NOT NULL,
    run_id          text        NOT NULL,
    episode_id      text,
    patient_id      text,
    source_system   text        NOT NULL,
    sim_time        double precision NOT NULL,
    event_time      timestamptz NOT NULL,
    recorded_time   timestamptz NOT NULL,
    ingest_time     timestamptz NOT NULL,   -- marca LogAppendTime del mensaje
    payload         jsonb       NOT NULL,
    kafka_topic     text        NOT NULL,
    kafka_particion integer     NOT NULL,
    kafka_offset    bigint      NOT NULL,
    valor           text        NOT NULL,   -- el mensaje tal cual
    recibido        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (event_id, ingest_time)
);
SELECT create_hypertable('bronce.eventos', by_range('ingest_time'));
CREATE INDEX ON bronce.eventos (event_time);
CREATE INDEX ON bronce.eventos (run_id, episode_id);

CREATE TABLE bronce.ejecuciones (   -- mensajes de ed.runs
    run_id text NOT NULL, tipo text NOT NULL, mensaje jsonb NOT NULL,
    ingest_time timestamptz NOT NULL, kafka_offset bigint NOT NULL,
    UNIQUE (run_id, tipo, ingest_time)
);

CREATE TABLE bronce.rechazados (    -- mensajes que no se pueden leer
    valor text NOT NULL, motivo text NOT NULL, kafka_topic text NOT NULL,
    kafka_particion integer NOT NULL, kafka_offset bigint NOT NULL,
    ingest_time timestamptz NOT NULL,
    UNIQUE (kafka_topic, kafka_particion, kafka_offset, ingest_time)
);
```

Los nombres de las columnas del sobre son los del mensaje (el contrato); los de bronce, en español. El plan de la 7.5 confirma el DDL con la versión fijada de TimescaleDB (la sintaxis de `create_hypertable` cambió entre versiones).

La tabla de migraciones aplicadas es `public.migraciones (version integer PRIMARY KEY, nombre text NOT NULL, aplicada timestamptz NOT NULL)`.

### El consumidor

| Propiedad | Valor | Por qué |
| --- | --- | --- |
| `group.id` | `edsim-bronce` | Grupo fijo: sigue donde lo dejó |
| `client.id` | `edsim-bronce` | Se reconoce en la consola |
| `enable.auto.commit` | `false` | Se confirma a mano, después de guardar |
| `auto.offset.reset` | `earliest` | La primera vez, desde el principio |
| Topics | `ed.patient.events`, `ed.resource.events` y `ed.runs` | Los que escribe el directo |
| Lote | Hasta 500 mensajes o 1 s, lo que llegue antes | `consume(500, 1.0)` |

**El bucle:**

1. Lee un lote.
2. Para cada mensaje: lee la marca (`msg.timestamp()`); si no es `TIMESTAMP_LOG_APPEND_TIME`, para con un error que dice que el topic está mal configurado. Interpreta el valor: un evento o registro va a `bronce.eventos`, un mensaje de `ed.runs` a `bronce.ejecuciones`, y lo que no se puede leer (JSON roto, sobre incompleto, hora que no se interpreta) a `bronce.rechazados`, con el motivo.
3. Guarda el lote en una transacción, con `ON CONFLICT DO NOTHING`.
4. Solo después confirma los offsets del lote, de forma síncrona.

**Formas de pararlo:** continuo, hasta Ctrl+C (termina el lote en curso, lo confirma y cierra); o con `--run RUN_ID`, hasta haber visto el `fin` de esa ejecución y tantos eventos distintos de ella como dice `publicados`, o hasta un `--timeout` (120 s por defecto), y entonces dice cuántos faltan. Imprime cada 10 s los mensajes guardados, repetidos ignorados y rechazados.

**Lógica en el paquete:** `edsim.store` (`postgres.py` importa `psycopg`, solo dentro de las funciones que conectan; `bronze.py` convierte un mensaje en una fila sin conectar a nada; `migrations.py` aplica los ficheros; `consumer.py` es el bucle, con el consumidor y la conexión inyectados, para probarlo con un Kafka y un Postgres falsos). La CLI solo construye los clientes reales e imprime.

**Leer lo registrado de bronce:** `read_bronze_records(dsn, run_id) -> list[Record]` reconstruye los registros desde `valor`, uno por `event_id` (si se publicó dos veces, el mismo registro), en orden de `sim_time` y `event_id`. Es lo que usa la comparación con `--postgres`.

## Especificación: la comparación

`compare(truth, records, notebook) -> Comparison`, en `edsim.clinical_record.compare`:

- **Conciliación:** los recuentos de cada `clase` de la libreta, comprobando la cuenta; la distribución del retraso (`recorded_time` − `event_time` sin el desfase) por sistema, con mediana y p90; los recuentos por tipo de despiste.
- **Indicadores ingenuos**, la misma función sobre la verdad y sobre lo registrado:

  | Indicador | Cómo se calcula a lo ingenuo |
  | --- | --- |
  | Tiempo hasta el triaje | Mediana, por episodio, de `event_time` del primer `triage_completed` menos el del primer `patient_arrived`; sin uno de los dos, el episodio no cuenta |
  | Tiempo hasta el médico | Igual, con el primer `assessment_started` de tipo inicial; con el tipo vacío, no cuenta |
  | Pacientes en urgencias | A cada hora en punto, los episodios con llegada y sin salida (`patient_departed` o `patient_left_wbs`) a esa hora, por `event_time`; y su media sobre el horizonte sin el calentamiento |
  | Número de llegadas | Registros `patient_arrived` |
  | Reparto por nivel | Porcentaje de cada nivel en los `triage_completed`, sin aplicar correcciones |

- **Salida:** la tabla «indicador, verdad, registrado, diferencia» y la conciliación, en datos (para el notebook y la fase 2 de la app) y en texto (`edsim registro comparar`, con los textos en español en un módulo de informe, como `engine/report.py`).

## CLI

| Comando | Opciones | Qué hace |
| --- | --- | --- |
| `edsim registro validar` | `--registros FICHERO` | Comprueba `config/registro_clinico.toml` |
| `edsim registro generar RUN_ID` | `--perfil P` (obligatorio), `--semilla N`, `--registros FICHERO`, `--ejecuciones DIR` | Escribe lo registrado en la carpeta de la ejecución e imprime la cuenta |
| `edsim registro comparar RUN_ID` | `--perfil P`, `--semilla N`, `--ejecuciones DIR`, `--postgres [URL]` | La conciliación y los indicadores; con `--postgres`, lo registrado sale de bronce |
| `edsim directo lanzar` y `reemitir` | Las de hoy, más `--registro P`, `--semilla-registro N` y `--registros FICHERO` | Con `--registro`, publican solo lo registrado |
| `edsim almacen preparar` | `--postgres URL` | Aplica las migraciones que falten e imprime cuáles |
| `edsim almacen consumir` | `--kafka`, `--postgres`, `--run RUN_ID`, `--timeout S` | El consumidor de bronce |

URL de Postgres por defecto: `postgresql://edsim:edsim@localhost:5432/edsim`. Sin el extra `postgres`, los comandos que conectan terminan con el mensaje que dice cómo instalarlo (`uv sync --all-packages --extra postgres`), como los de Kafka. Códigos de salida como en el hito 6: 0 bien, 1 fallo de infraestructura o de datos, 2 error de uso antes de conectar.

## Valores orientativos de partida

Todos son **orientativos**: no hay una fuente que dé las tasas de despiste de un servicio de urgencias español. Lo que sí hay son órdenes de magnitud y formas:

- Gordon, Flottemesch y Asplin (2008) compararon las horas tecleadas por el personal con las de un observador: la mediana sale 1,8 minutos antes de lo observado, con un rango intercuartílico de 30,7 minutos antes a 2,9 minutos después. Es decir, errores pequeños en la mayoría y unos pocos muy grandes.
- Ward y colaboradores (2013) encontraron que la hora de la decisión de destino difería más de 10 minutos de la observada en el 16 al 29 % de los casos, según el sistema.
- Ward, Self y Froehle (2015) simularon errores con frecuencias del 2, el 4 y el 7 %.

| Valor | Realista | Hostil | Criterio |
| --- | --- | --- | --- |
| Olvido | 0,005 | 0,05 | Raro en un hospital normal; el hostil, cerca del 7 % de Ward (2015) |
| Campo vacío | 0,01 | 0,07 | Íd. |
| Valor erróneo | 0,01 | 0,07 | Íd. |
| Duplicado | 0,005, [0,5, 2] min | 0,04, [0,5, 5] min | Doble clic: segundos o pocos minutos |
| Corrección (sobre los erróneos) | 0,5, [120, 720] min | 0,3, [240, 1.440] min | Se corrige en el mismo turno o al día siguiente |
| Retraso de admisión | 0,10, [1, 5] min | 0,30, [2, 15] min | Admisión registra al momento |
| Retraso de triaje | 0,60, [5, 15] min | 0,90, [10, 40] min | Diferencias de más de 10 min frecuentes (Ward, 2013) |
| Retraso del HIS | 0,70, [10, 45] min | 0,90, [20, 120] min | La valoración médica se documenta al acabar |
| Retraso de laboratorio | 0,05, [1, 3] min | 0,20, [2, 10] min | Resultados automáticos |
| Reloj (admisión / triaje / HIS / laboratorio) | 0 / +2 / 0 / −1 min | +3 / +7 / −5 / −3 min | Unos minutos, como un PC sin sincronizar |

La 7.2 busca fuentes mejores y cambia lo que haga falta en su plan, con el estado de cada valor. El perfil hostil no busca parecerse a nada: busca que la limpieza del hito 8 tenga trabajo.

## Estructura del código

```
edsim/
├── compose.yaml                 # cambia: postgres y su volumen; consola en 127.0.0.1 (7.5)
├── pyproject.toml               # extra postgres = ["psycopg[binary]…"] (7.5)
├── config/registro_clinico.toml # nuevo: los tres perfiles (7.2)
├── schemas/registro-v*.schema.json   # nuevos, generados (7.1)
├── scripts/tests-integracion.sh # cambia: Kafka y Postgres (7.5)
├── src/edsim/
│   ├── clinical_record/         # nuevo
│   │   ├── records.py           # Record, to_json del registro (7.1)
│   │   ├── record.py            # record(): los ocho despistes, la emisión y el corte (7.1)
│   │   ├── notebook.py          # la libreta y la cuenta (7.1)
│   │   ├── schemas.py           # esquemas del registro (7.1)
│   │   ├── profiles.py          # carga y validación de registro_clinico.toml (7.2)
│   │   ├── compare.py           # conciliación e indicadores ingenuos (7.3)
│   │   └── report.py            # textos en español (7.2, 7.3)
│   ├── runs/                    # record_run y su lectura (7.2)
│   ├── live/                    # --registro en lanzar y reemitir; la sala de espera; inicio con registro (7.4)
│   ├── store/                   # nuevo (7.5)
│   │   ├── sql/001_bronce.sql
│   │   ├── migrations.py
│   │   ├── bronze.py            # mensaje → fila, sin conectar
│   │   ├── consumer.py          # el bucle, con clientes inyectados
│   │   └── postgres.py          # importa psycopg solo al conectar
│   └── cli.py                   # grupos registro y almacen; opciones del directo (7.2 a 7.5)
├── tests/                       # rápidos y lentos, sin Docker
├── tests_integracion/           # contra Kafka y Postgres reales (7.4, 7.5)
├── .github/workflows/ci.yml     # tests-kafka pasa a tests-integracion (7.5)
└── notebooks/07_persistencia.ipynb   # nuevo (7.6)
```

**Reglas que se mantienen:** paquete en inglés; tests del núcleo en español; claves TOML, del payload y opciones de la CLI en español; lógica en el paquete y CLI fina; `edsim.clinical_record` no importa SimPy, el motor, `confluent_kafka` ni `psycopg`; el núcleo se importa sin los extras (test de frontera para `psycopg`, como el de `confluent_kafka`); el núcleo no importa `streamlit`, `pandas` ni `edsim_app`.

## Tests y validación

**La regla del hito (H7-10):** cada test dice qué error pilla que no pille ningún otro. Si no tiene respuesta, sobra. Nada lento ni de integración que ya cubra un test rápido. Las referencias no usan la función probada.

### Rápidos, sin Docker

- **7.1:** el escenario L y sus dos variantes, con cada hora calculada a mano; cada despiste por separado con el dado forzado; la renumeración sin huecos; el `run_id` derivado (y el error si no cabe); el orden de emisión en el empate; la cuenta que cuadra; los esquemas «escritos = generados»; que la función no importa SimPy ni el motor.
- **7.2:** la carga y cada error del fichero de perfiles (también un `limpio` con una tasa distinta de 0); el consumo fijo, contando sorteos; la inclusión «lo del realista ⊂ lo del hostil» con la misma semilla; que cambiar la semilla del registro no cambia la verdad; `record_run` atómico y sin tocar los ficheros de la ejecución (huellas antes y después).
- **7.3:** la conciliación y los indicadores del escenario L (4,2 frente a 6,2 min; 1 frente a 2 pacientes a las 20:00; nivel 3 frente a nivel 4); con el perfil limpio, todos los indicadores iguales.
- **7.4:** la sala de espera con un motor falso: suelta cada registro cuando debe; con `--registro` no se publica ningún evento de la verdad (sumidero en memoria); el `inicio` con el bloque `registro`.
- **7.5:** `bronze.py` con mensajes a mano (evento, registro con campo vacío, `record_corrected`, mensaje de `ed.runs`, JSON roto); el bucle con un Kafka y un Postgres falsos: el orden guardar y después apuntar, la caída entre las dos cosas sin pérdida ni repetición, la marca que no es `LogAppendTime`; el aplicador de migraciones con una conexión falsa; el test de frontera de `psycopg`.

### Lentos

- **«Directo = lotes» de lo registrado** (7.4), por versión de catálogo, con el perfil realista: es el único que pilla los errores de la sala de espera.

No hay test lento de «las tasas salen como dice el fichero»: con el dado, el test rápido ya comprueba el umbral, y la uniformidad del dado es cosa de numpy.

### Integración, contra Kafka y Postgres reales

- **El test de punta a punta del hito:** reemitir con el perfil **limpio** y consumir: lo que hay en bronce coincide con la verdad (salvo los identificadores, con la libreta). Si la 7.5 se fusiona antes que la 7.4, la 7.5 lo hace con la verdad publicada sin registro y la 7.4 añade el caso limpio.
- Con el perfil **realista**, la cuenta cuadra con lo leído de bronce (`read_bronze_records` y la comparación).
- **Un solo test** de parar y relanzar el consumidor: no duplica ni pierde nada. El rápido prueba nuestra lógica; este, que Kafka recuerda de verdad dónde nos quedamos.
- Cada sesión de tests crea su propia base de datos (`edsim_test_<8 hex>`) y la borra al acabar: los datos de Pedro no se tocan.
- En el CI, el job `tests-kafka` pasa a llamarse `tests-integracion` y levanta Kafka y Postgres desde el mismo `compose.yaml`; sigue siendo obligatorio. **Al fusionar la 7.5, Pedro cambia el nombre del check obligatorio en la protección de `main`**; si no, ningún PR podrá fusionarse.

### Versiones incorrectas (temporales, con predicción firme)

Como en los hitos anteriores: el plan escribe la predicción firme de cada una con los tests que diseñe, se aplica y se deshace en el mismo turno (con el subagente `mutante` donde convenga), y si falla se entiende por qué y se añade el test que faltaba. Predicciones de partida:

| # | Tarea | Versión incorrecta | Predicción de partida |
| --- | --- | --- | --- |
| V1 | 7.1 | Lo registrado conserva los `event_id` de la verdad | Falla «sin huecos» del escenario L (falta el de L6) |
| V2 | 7.1 | Se emite por `event_time` en vez de por `sim_time` registrado | Falla el orden del escenario L: el triaje (17:06:12) sale antes que la llegada de EP-000002 |
| V3 | 7.1 | El reloj desajustado también mueve `sim_time` | Falla el `sim_time` de L3 registrado (1.033,2 en vez de 1.031,2) |
| V4 | 7.1 | El duplicado conserva el `event_id` del original | Fallan la unicidad de los `event_id` y la cuenta |
| V5 | 7.1 | La corrección apunta al `event_id` de la verdad | Falla `corrige` del registro 7 (debe ser el 4 registrado) |
| V6 | 7.1 | Lo que cae después del horizonte se escribe | Falla la variante del corte (7 registros en vez de 6) |
| V7 | 7.2 | Un dado distinto por perfil | Falla la inclusión realista ⊂ hostil |
| V8 | 7.2 | `record_run` reescribe `eventos.jsonl` | Falla el test de huellas antes y después |
| V9 | 7.3 | La conciliación cuenta los duplicados como hechos | Falla la cuenta del escenario L (7 hechos en vez de 6) |
| V10 | 7.3 | Los indicadores ingenuos aplican las correcciones | Falla el reparto por nivel del escenario L (nivel 3 en vez de 4) |
| V11 | 7.4 | La sala de espera suelta un registro antes de que el motor pase su `sim_time` | Falla «directo = lotes» de lo registrado |
| V12 | 7.4 | Con `--registro` se publica también la verdad | Falla «solo viaja lo registrado» |
| V13 | 7.5 | Confirmar los offsets antes de guardar | Falla la caída entre guardar y apuntar: se pierde el lote |
| V14 | 7.5 | Clave única por las coordenadas de Kafka | Falla el caso de offsets que vuelven a empezar (Kafka sin volumen): se pierden registros nuevos |
| V15 | 7.5 | `ingest_time` = hora de recepción del consumidor | Falla el test con la marca del mensaje fijada |
| V16 | 7.5 | Se aceptan marcas `CreateTime` | Falla el test del tipo de marca |

### Comprobaciones en el PR (sin test)

- **7.2:** con `config/` y 14 días, la cuenta y las tasas observadas por sistema frente a las del perfil, en los tres perfiles.
- **7.3:** la tabla «verdad frente a registrado» con el perfil realista y con el hostil.
- **7.4:** un directo a ×60 con `--registro realista` unos minutos, visto en Redpanda Console (Pedro).
- **7.5:** filas en bronce = registros publicados; el tiempo del job de integración antes y después.

## Decisiones del hito

Dieciséis decisiones candidatas, tomadas con Pedro una a una en la sesión conceptual del 13 de noviembre de 2026, cada una con la recomendación de Claude salvo donde se dice. Su número definitivo es 83 + n; la tarea 7.7 escribe sus ADR 0084 a 0099, con lo que cambió al implementarlas y las alternativas descartadas, y las añade al [registro de decisiones](../diseno.md#registro-de-decisiones-y-preguntas-abiertas) de `docs/diseno.md`.

| # | Decisión | Motivo |
| --- | --- | --- |
| 84 (H7-1) | La pieza que mete los despistes se llama **simulador del registro clínico** («el registro clínico»; `edsim.clinical_record`), y sus datos, **lo registrado** frente a **la verdad**. Sustituye a «capa de observación» en el diseño. Nombre elegido por Pedro | Dice quién se equivoca y que se equivoca a propósito; «clínico» lo distingue de la admisión y de los registros de calibración y de decisiones |
| 85 (H7-2) | El registro clínico es una función pura de la verdad, dentro del simulador, entre el motor y la salida; sirve para lotes, directo y reemisión. Con `--registro`, la verdad nunca viaja por Kafka; lo registrado en directo es igual, byte a byte, a lo registrado por lotes | Nadie puede leer la verdad desde el broker; un retraso no obliga a dormir mensajes; un solo código, con la comprobación del hito 6. Alternativa descartada: un procesador aparte que lea la verdad de Kafka |
| 86 (H7-3) | Los ocho despistes del diseño, con retraso y reloj propios de cada sistema; la corrección tardía como evento `record_corrected` en esquemas propios del registro; solo se corrigen valores erróneos; los valores erróneos, solo en nivel, edad, motivo y destino; un duplicado es otro registro; solo en eventos de pacientes; con cualquier versión del catálogo | Un error sin su corrección cuenta media historia; los dos límites abaratan sin perder la lección. Alternativa descartada: dejar la corrección para el hito 8 |
| 87 (H7-4) | Tres perfiles (limpio, realista y hostil) en `config/registro_clinico.toml`, con el estado de cada valor; un dado por evento y despiste con consumo fijo, y el perfil como umbral, así que lo del realista está dentro de lo del hostil; semilla propia (por defecto, la de la ejecución) y un flujo que no comparte con el motor | Comparar perfiles mide el perfil, no el azar (números comunes, decisión 43). Alternativa descartada: sortear cada perfil por separado |
| 88 (H7-5) | La libreta `defectos.csv`, con una fila por registro y por hecho no escrito; lo registrado es una ejecución derivada con su `run_id`, sus registros se renumeran en orden de anotación y su `inicio` dice origen, perfil y semilla; lo anotado después del horizonte no se escribe («pendiente al corte»); la cuenta que cuadra es una invariante | Sin huecos ni marcas que regalen las soluciones (la fuga que evitó la decisión 28); dos registros de la misma verdad no se mezclan en el archivo |
| 89 (H7-6) | Postgres con TimescaleDB en `compose.yaml`: imagen con versión exacta fijada en la 7.5, sin perfil, con volumen con nombre y solo en `127.0.0.1`; `psycopg` 3 como extra `edsim[postgres]`, importado en un solo módulo; el consumidor corre fuera de Docker | SQL estándar con funciones de tiempo; la tabla nace partida por tiempo y no hay que migrarla en el hito 8; el patrón de las decisiones 49, 62 y 65. Alternativas descartadas: Postgres solo, ClickHouse, DuckDB, InfluxDB, MongoDB |
| 90 (H7-7) | `bronce.eventos` con el sobre en columnas, el `payload` en JSON, las coordenadas de Kafka y el mensaje original; hypertable por `ingest_time`, con índice por `event_time`; clave única (`event_id`, `ingest_time`); los mensajes de `ed.runs` en `bronce.ejecuciones` | La hora de llegada es fiable y siempre existe; Timescale exige la columna de partición en la clave; con las coordenadas de Kafka, un broker sin volumen reutiliza offsets |
| 91 (H7-8) | Consumidor con `confluent-kafka`: guarda un lote (hasta 500 mensajes o 1 s) en una transacción con `ON CONFLICT DO NOTHING` y después confirma los offsets; `ingest_time` desde `LogAppendTime` (otro tipo de marca es un error); grupo fijo `edsim-bronce`; tres topics; los ilegibles a `bronce.rechazados`; continuo o hasta el fin de una ejecución | Al menos una vez con inserción idempotente, el patrón estándar; el orden se ve a mano. Alternativas para el futuro: Quix Streams (hito 8) y los offsets en Postgres |
| 92 (H7-9) | Migraciones SQL numeradas en el paquete, con un aplicador propio (`edsim almacen preparar`), una tabla de versiones y una transacción por migración; en este hito, solo el esquema `bronce` | Pocas tablas, el SQL a la vista, sin ORM en el núcleo. Alternativas para el futuro: Alembic, Flyway o Sqitch |
| 93 (H7-10) | Tres capas de tests (rápidos sin Docker, lentos e integración); cada test dice qué error pilla que no pille ningún otro; una base de datos de prueba por sesión; el job `tests-kafka` pasa a `tests-integracion`, con Kafka y Postgres, obligatorio | La decisión 50 con la regla de Pedro de no repetir tests caros sin valor; el consumidor necesita los dos servicios |
| 94 (H7-11) | En el hito 8, la capa plata imita las tablas de un HIS (`paciente`, `episodio`, `triaje`, `prueba`, `valoracion`, `destino`), con las correcciones aplicadas; un HIS simulado con su base de datos transaccional y CDC va al Backlog. A pregunta de Pedro | En un hospital, analítica recibe tablas de un HIS, no eventos; el hito 7 se queda en bronce |
| 95 (H7-12) | La verdad no se carga en Postgres en este hito: el esquema `verdad`, cargado desde los ficheros y con permisos separados, llega en el hito 8 con dbt | Una sola comparación, en Python, sin duplicarla en SQL; el esquema llega cuando tiene quien lo use |
| 96 (H7-13) | Una sola comparación, en Python, en el paquete: conciliación exacta, distribución del retraso e indicadores ingenuos (tiempo hasta el triaje y hasta el médico, pacientes en urgencias, llegadas y reparto por nivel), igual con ficheros que con bronce | La usan la CLI, el notebook, los tests y la fase 2 de la app; las métricas de `edsim.runs` esperan datos limpios. Alternativas descartadas: vistas SQL, más indicadores |
| 97 (H7-14) | La app no cambia en el hito 7; la página del registro clínico, la lectura de bronce, el directo en vivo y los fantasmas en el Replay van a la fase 2 de la app. Elegida por Pedro (la recomendación era la página desde ficheros) | Sin tarea de app en el hito; la comparación queda lista en el paquete para la fase 2 |
| 98 (H7-15) | Una tarea 7.0 de proceso con siete mejoras: el formato del plan, el subagente «revisor del plan» (#110), las skills con `gh api` REST, la nube por defecto salvo Docker o navegador, la revisión del chat a la medida, la Release lanzable sola y el piloto `@claude` en el PR | Las propuestas del balance del hito 5 y el piloto pospuesto, como mejora y como aprendizaje |
| 99 (H7-16) | Ocho tareas (7.0 a 7.7) en dos pistas tras la 7.0 (A: 7.1 → 7.2 → 7.3 → 7.4; B: 7.5), con dos ramas abiertas como mucho; `@codex review` en la 7.1, la 7.4 y la 7.5; etiqueta `v0.7-hito7`; Parquet y DuckDB fuera | El registro clínico y la persistencia apenas comparten código; una pista va en la nube y la otra en local |

## Tareas, ramas y orden de ejecución

| Tarea | Contenido | Pista | Dónde | Modelo y esfuerzo | Rama | Crítica |
| --- | --- | --- | --- | --- | --- | --- |
| 7.0 (#114) | Proceso: las siete mejoras de H7-15 (cierra #110). Pedro instala la app de GitHub para `@claude` | — | Local | Opus, alto | `chore/h7-proceso` | No |
| 7.1 (#115) | Registro clínico: `Record`, los ocho despistes con el dado inyectable, la emisión, la renumeración, el corte, la libreta, la cuenta y los esquemas `registro-v*`. Sin perfiles. Primera prueba del revisor del plan | A | Nube | Opus, alto | `feat/h7-registro` | **Sí** |
| 7.2 (#116) | Perfiles en `config/registro_clinico.toml` con su estado y fuentes, carga y validación, el flujo propio, `record_run` y `edsim registro validar` y `generar` | A | Nube | Sonnet, alto | `feat/h7-perfiles-registro` | No |
| 7.3 (#117) | Comparación: conciliación, retraso e indicadores ingenuos; `edsim registro comparar` (sin `--postgres`, que llega con la 7.5) | A | Nube | Sonnet, alto | `feat/h7-comparacion` | No |
| 7.4 (#118) | Directo y reemisión con `--registro`: la sala de espera, el censo, el `inicio` con registro y «directo = lotes» de lo registrado | A | Local (Kafka) | Opus, alto | `feat/h7-directo-registro` | **Sí** |
| 7.5 (#119) | Postgres y consumidor: compose (cierra #91), extra `postgres`, migraciones, `bronce`, el consumidor, `edsim almacen preparar` y `consumir`, `read_bronze_records`, `registro comparar --postgres` y el job `tests-integracion` | B | Local (Docker) | Opus, alto | `feat/h7-almacen` | **Sí** |
| 7.6 (#120) | Notebook `07_persistencia.ipynb`: el escenario de Lucía, los tres perfiles, la tabla «verdad frente a registrado», consultas SQL a bronce y las dos clases de duplicados; modo rápido sin Docker | — | Nube (Pedro lo ejecuta entero en local) | Sonnet, medio | `feat/h7-notebook` | No |
| 7.7 (#121) | Cierre con `/cerrar-hito`: ADR 0084 a 0099, diario, `docs/diseno.md` (el nombre nuevo, las capas, el registro de decisiones y la hoja de ruta), balance, Release y `v0.7-hito7` | — | Local | Opus, alto | `docs/h7-cierre` | No |

**Dependencias:**

| Tarea | Depende de | Por qué |
| --- | --- | --- |
| 7.0 | — | |
| 7.1 | 7.0 | El revisor del plan se estrena aquí |
| 7.2 | 7.1 | Los perfiles alimentan el mecanismo |
| 7.3 | 7.2 | La función solo necesita la 7.1, pero el comando lee lo que escribe `generar` |
| 7.4 | 7.2 | `--registro PERFIL` necesita los perfiles; no necesita la 7.3 |
| 7.5 | 7.0 | Se prueba con la verdad que ya publica el directo; `registro comparar --postgres`, cuando esté la 7.3 (si no, va en la 7.3 o la 7.4, la que se fusione después) |
| 7.6 | 7.3, 7.4, 7.5 | Junta todo |
| 7.7 | Todas | |

```mermaid
---
title: "Dos pistas tras la 7.0: el registro clínico en la nube y la persistencia en local"
---
flowchart LR
    t0["7.0<br/>proceso"] --> t1["7.1<br/>registro clínico"]
    t1 --> t2["7.2<br/>perfiles"] --> t3["7.3<br/>comparación"]
    t2 --> t4["7.4<br/>directo con registro<br/>(local)"]
    t0 --> t5["7.5<br/>Postgres y consumidor<br/>(local)"]
    t3 --> t6["7.6<br/>notebook"]
    t4 --> t6
    t5 --> t6
    t6 --> t7["7.7<br/>cierre"]
```

**Precisiones:**

- **Dos ramas abiertas como mucho**, una por pista: la 7.5 empieza justo después de la 7.0, en paralelo con la 7.1. No se paraleliza la 7.2 con la 7.3 (poco ahorro y tres sesiones que revisar) ni la 7.4 con la 7.5 (las dos en local, con Docker).
- **Las dos pistas tocan zonas distintas** (`clinical_record/` y `live/` frente a `store/`, `compose.yaml` y el CI) y solo coinciden en `cli.py` y `tests_integracion/`. Si al fusionar una la otra tiene conflictos o tocó ficheros compartidos, su agente trae `main` a la rama con un merge (no con rebase: el push forzado está prohibido) y espera al CI; si no, se fusiona directamente y el CI de `main` es la red. El chat lo dice en su revisión.
- **Sesiones en la nube:** al abrirlas, Pedro elige la rama del issue (la nube propone `claude/*`, anexo de la 5.7), y mueve la ficha del tablero (GraphQL no está disponible en la nube).
- La 7.4 y la 7.5 ejecutan `scripts/tests-integracion.sh` antes del push, además de la N3.

## Flujo de git y reparto entre agentes

Todo lo implementa Claude Code. Cada tarea sale de su issue de GitHub y sigue el ciclo de [docs/proceso/tarea.md](../proceso/tarea.md) (con el formato del plan que deje la 7.0), con la entrada del anexo de esta especificación en el mismo PR y la fusión, siempre de Pedro. El manual del flujo para personas está en [docs/proceso/flujo.md](../proceso/flujo.md).

Lo propio de este hito:

- `@codex review` en la 7.1, la 7.4 y la 7.5 (H7-16), las tareas con la etiqueta `critica`; en ellas, también el revisor del plan desde la 7.1.
- Dos ramas abiertas como mucho, con el procedimiento de «Precisiones».
- Al fusionar la 7.5, Pedro cambia el check obligatorio `tests-kafka` por `tests-integracion` en la protección de `main`.
- Esta especificación se cambia en el repositorio, en el mismo PR que el código que la cambia.

## Criterios de aceptación

El hito 7 está cerrado cuando se cumplen todos:

- `uv run pytest` pasa, incluidos los `slow`; los tests de la app y de integración pasan; el CI está en verde con sus jobs, y `tests-integracion` es obligatorio en `main`.
- Las huellas de los logs y del ground truth de los hitos 3 a 6 no cambian: el motor no se toca.
- `edsim registro generar` con el perfil limpio da lo registrado igual a la verdad salvo los identificadores; con la misma verdad, perfil y semilla, los mismos bytes; la cuenta cuadra con los tres perfiles.
- Lo registrado en directo y en la reemisión es igual, byte a byte, a lo registrado por lotes, con las versiones 1 a 4.
- `edsim almacen consumir` deja en `bronce.eventos` exactamente lo publicado, también tras pararlo y relanzarlo, con `ingest_time` desde la marca del broker.
- `edsim registro comparar` da la misma conciliación con ficheros que con `--postgres`.
- `notebooks/07_persistencia.ipynb` se ejecuta en el CI en modo rápido.
- Pedro sabe explicar por qué lo registrado se renumera, qué hace el truco del dado, por qué el consumidor guarda y después apunta, por qué la clave única lleva la hora de llegada, qué diferencia hay entre los dos duplicados y por qué un indicador ingenuo se desvía.
- `docs/` contiene esta especificación con su anexo y su balance, los ADR 0084 a 0099 y la entrada del diario; la etiqueta `v0.7-hito7` y su Release existen en GitHub.

## Para versiones posteriores

Lo que este hito aplaza a propósito, con su destino, y las alternativas que se descartaron y cuándo tendrían sentido. La tarea de cierre lo lleva a la [hoja de ruta](../diseno.md#hoja-de-ruta) de `docs/diseno.md`.

| Qué | Adónde | Nota |
| --- | --- | --- |
| Limpiar lo registrado: deduplicar, aplicar correcciones, tipar; capas plata y oro con dbt | Hito 8 | Y volver a comparar con la verdad: cuánto se acerca lo limpiado |
| Plata con la forma de un HIS (H7-11) | Hito 8 | `paciente`, `episodio`, `triaje`, `prueba`, `valoracion`, `destino` |
| Esquema `verdad` en Postgres y permisos por capa (H7-12) | Hito 8 | Para los tests de datos validados con el ground truth |
| El registro clínico por defecto en el directo | Hito 8 | Cuando Grafana lea de Postgres |
| Quix Streams, KPIs por ventana con eventos tardíos | Hito 8 | El desorden de este hito les da trabajo |
| Retención y compresión de Timescale | Hito 8 | Con datos de semanas |
| Parquet y DuckDB para el camino por lotes | Hito 8 o 9 | Diseño, «Capas de almacenamiento» |
| Página del registro clínico, lectura de bronce, directo en vivo y fantasmas en el Replay (H7-14) | Fase 2 de la app (#122) | La comparación ya está en el paquete |
| Un HIS simulado con base de datos transaccional y CDC (Debezium) | Backlog (#123) | El escenario más realista de extracción |
| Error aleatorio en la hora declarada y anotación anticipada | Versiones posteriores | Gordon (2008): el personal teclea a veces antes de que ocurra |
| Despistes en los eventos de recursos | Versiones posteriores | Hoy pasan tal cual |
| Pacientes duplicados (dos historias para la misma persona) | Versiones posteriores | Un problema de identidad, no de anotación |
| Offsets en Postgres en la misma transacción («exactamente una vez») | Si hace falta | Hoy la clave única lo resuelve |
| Alembic, Flyway o Sqitch | Si crecen las migraciones | |
| ClickHouse o DuckDB para la analítica pesada | Si Postgres se queda corto | |
| Avro y registro de esquemas | v1 | Caso de uso «evolución de esquemas» |

## Fuentes y para aprender más

Consultadas el 13 de noviembre de 2026. Las de «para aprender más» están en cada pieza.

| Tema | Fuente | Qué se tomó |
| --- | --- | --- |
| Exactitud de las horas tecleadas | [Gordon, Flottemesch y Asplin, *Annals of Emergency Medicine* 2008](https://pmc.ncbi.nlm.nih.gov/articles/PMC4361868) | Mediana 1,8 min antes de lo observado; rango intercuartílico de 30,7 min antes a 2,9 min después |
| Calidad de las horas tras implantar un HIS | [Ward et al., *American Journal of Emergency Medicine* 2013](https://pubmed.ncbi.nlm.nih.gov/23707000) | Discrepancias de más de 10 min en la decisión de destino: del 29,3 % al 16,1 % |
| Efecto de los errores en los indicadores | [Ward, Self y Froehle, *Academic Emergency Medicine* 2015](https://pmc.ncbi.nlm.nih.gov/articles/PMC4560638) | Cuatro tipos de error al 2, 4 y 7 %; los indicadores de intervalos cortos, los más sensibles |
| Historias duplicadas | [McCoy et al., *BMJ Quality & Safety* 2013](https://qualitysafety.bmj.com/content/22/3/219) | Orden de magnitud de las coincidencias de identidad; solo para «Para versiones posteriores» |
| Claves únicas en TimescaleDB | [Documentación de TimescaleDB (Tiger Data)](https://www.tigerdata.com/docs/learn/data-model/primary-keys-time-and-uniqueness) | Toda clave única incluye la columna de partición |
| Imagen de TimescaleDB | [Docker Hub](https://hub.docker.com/r/timescale/timescaledb) | Etiquetas `X.Y.Z-pgNN`; sin `latest` |
| Garantías del consumidor | [Confluent](https://docs.confluent.io/platform/current/clients/consumer.html) y [Conduktor](https://docs.conduktor.io/learn/advanced/consumers/delivery-semantics) | Confirmar después de procesar da «al menos una vez»; con procesado idempotente, sin repetidos |
| Arquitectura medallón | [Databricks](https://docs.databricks.com/aws/en/lakehouse/medallion) | Bronce, plata y oro |
| `psycopg` 3 | [Documentación](https://www.psycopg.org/psycopg3/docs/basic/) | Transacciones, `executemany` y `COPY` |

**Cálculos propios de esta especificación.** Las horas del escenario L, calculadas en Python en el chat. Los valores orientativos son de criterio, con las fuentes de la tabla como órdenes de magnitud.

## Anexo: guía de referencia del hito 7

Una entrada por tarea, escrita al cerrarla: qué se hizo, conceptos, decisiones del diff, medidas, versiones incorrectas (predicción frente a observado), revisión, lecciones y pendientes.

### Tarea 7.0: Proceso del hito 7

**Qué se hizo**

Issue #114 (cierra también el #110), rama `chore/h7-proceso`, Claude Code (Opus, en local), sin `@codex review` (tarea no crítica). Aplica las siete mejoras de la decisión 98 (H7-15), un commit por mejora, más uno para `portabilidad.md` y los de las correcciones:

- **El formato del plan** (`tarea.md` §2): ocho apartados, con «Lo que el plan interpreta» y «Diferencias con las notas del chat»; los valores a mano, con su cálculo ejecutado y su salida; el detalle, en el PR. La plantilla del PR gana «Lo que el plan interpretaba».
- **El subagente `revisor-plan`** (`.claude/agents/revisor-plan.md`): Opus, solo lectura, recalcula con `python3` independiente del paquete; `/tarea-edsim` lo lanza en las tareas con la etiqueta `critica` y pone su informe al principio del plan.
- **Las skills por REST:** `/tarea-edsim`, `/sincronizar` y `/cerrar-hito` leen el issue, los comentarios, las dependencias, el PR, sus checks y la Release con `gh api`, y el PR se abre y se edita con `gh api -X POST/PATCH`: un solo camino en local y en la nube. Solo el tablero sigue con `gh project`; si falla, la skill dice a Pedro qué ficha mover. `tarea.md`, `AGENTS.md` y `CLAUDE.md`, al día.
- **La nube por defecto** (`flujo.md`, «Dónde corre cada tarea»; `tarea.md` §1; `portabilidad.md` §9): en local solo lo que necesita Docker, la app en el navegador, ficheros del portátil o crear una Release. La plantilla del issue gana «Dónde y modelo».
- **La revisión del chat a la medida** (`flujo.md`, el diagrama y «Papeles»): el plan, en las críticas o con conceptos nuevos, más lo que marque el revisor; el PR, ligera.
- **La Release lanzable sola** (`/cerrar-hito`): con el issue de cierre ya cerrado, va directamente a la Release; la crean Claude Code en local o Pedro, nunca el chat ni la nube (HTTP 403).
- **El piloto `@claude`:** el `if` de `claude.yml` exige `sender` `pdromer0` y que el texto empiece por `@claude`, sin tocar los `permissions`.

**Decisiones del diff**

- **Las reglas de `gh api` en tres niveles** (ajuste del chat al plan, con un matiz): en una regla `Bash(…)`, `*` casa también con espacios y opciones, así que un `allow` de `gh api repos/pdromer0/edsim/*` dejaba pasar también las escrituras con la opción detrás de la ruta. La convención: lecturas con la ruta justo detrás de `gh api` (`allow`), escrituras con `-X` delante (solo abrir y editar el PR tienen `allow`), las escrituras escritas al revés en `ask`, y la fusión y `DELETE` en `deny`.
- **El `deny` de la fusión es `*pulls/*/merge*`, no `*merge*`:** la comprobación a mano encontró que `*merge*` denegaba también las lecturas que piden `merged` o `merge_commit_sha` en el `--jq`, que es el paso 2 de `/sincronizar` (commit `d3973eb`).
- **«Fusionado» es `merged == true`:** por REST, `merge_commit_sha` también lo trae un PR abierto (el merge de prueba), así que no sirve para decidirlo.
- **Los issues que cierra un PR salen de su cuerpo**, con la regex de las notas más `:?`, porque REST no tiene `closingIssuesReferences`.
- **La etiqueta de la Release se construye** (`v0.H-hitoH`) en lugar de buscarse con un grep, que da varias por especificación (ajuste del chat).
- **El piloto, con un comentario normal** (ajuste del chat): la acción solo se ejecuta con el `claude.yml` de `main`, así que una revisión, que usa el de la rama, se saltaría. La condición nueva se prueba tras la fusión.
- **«Cierra #110» no cierra el issue**: GitHub solo reconoce las palabras clave en inglés; el PR lleva `Closes #114` y `Closes #110`.
- **El tablero por REST existe**: en local, `gh api users/pdromer0/projectsV2/1/fields` responde. Lo que da 403 en la nube es el proxy, no la falta de REST; las skills siguen con `gh project`.

**Valores a mano**

- **Los comandos REST de las skills**, ejecutados tal como están escritos (salida completa en el PR): el issue (#114 abierto; #111 da `es_pr` verdadero), los comentarios, `blocked_by` (#115 bloqueado por #114), el PR #111 y sus cuatro checks en `success`, el PR de una rama por su punta (`commits/<punta>/pulls`), los issues que cierra (#111 da [74]; #106 da [72, 105]) y la etiqueta y la Release de `v0.5-hito5`.
- **La regex frente a GraphQL:** 40 de 40 PR fusionados iguales a `closingIssuesReferences`.
- **Las etiquetas:** `v0.H-hitoH` cuadra con las siete existentes (`v0.0-hito0` a `v0.6-hito6`); un grep de `v0.…-hito…` da dos en `hito-5.md` y `hito-7.md` y tres en `hito-6.md`.

**Medidas**

- **Sin N3:** rama solo de documentación, skills, un agente, un workflow y los permisos de `settings.json`, con el permiso de Pedro (`tarea.md` §4). El CI se ejecuta igual.
- **El grep final:** no queda `gh issue view`, `gh pr view` ni `gh pr create` en `.claude/skills/`, `tarea.md`, `flujo.md`, `AGENTS.md` ni `CLAUDE.md`; `gh project` sigue en `/tarea-edsim` (8 líneas) y `/sincronizar` (9).
- **Los permisos:** una lectura con `gh api` pasa sin aviso, y `gh api …/pulls/111/merge` queda denegado.

**Versiones incorrectas**

| # | Versión incorrecta | Predicción | Observado |
| --- | --- | --- | --- |
| 1 | La regex sin `(?i)` | Los 12 PR que cierran issues dan distinto; los 28 restantes, igual | 12 distintos y 28 iguales |
| 2 | «Fusionado» por `merge_commit_sha` no nulo | Con el PR de la 7.0 abierto, daría «fusionado» | Abierto, con `merged` falso y `merge_commit_sha` relleno (el merge de prueba): habría dado «fusionado». Justo al crearlo era nulo, porque GitHub lo calcula en segundo plano |
| 3 | `claude.yml` con `contains` (lo de `main`) | Tras la fusión, un comentario que solo menciona `@claude` en medio sale *skipped* con `startsWith`; con `contains` se habría ejecutado | Pendiente, tras la fusión |
| 4 | Prueba de humo del revisor: un plan falso de la 7.1 con tres errores sembrados y cuatro apartados de control | Marca los tres y ninguno de control | En una sesión nueva, lanzada por Pedro |

**Revisión**

`/code-review medium main...chore/h7-proceso`, diez hallazgos:

- **Corregidos en `567529c`** (permisos):
  - las reglas `ask` no cubrían las opciones pegadas (`-XDELETE`, `-fbody=`, `--method=`): ahora acaban en `-X*`;
  - `PATCH …/pulls/*` cerraba un PR o cambiaba su base sin preguntar: `state=` y `base=` piden permiso;
  - la API `…/merges` no estaba denegada;
  - `*pulls/*/merge*` denegaba lecturas con `/merge` en el `--jq`: queda `…/merge` al final o seguido de un espacio;
  - el ejemplo de `portabilidad.md` ya no coincidía con el fichero real.
- **Corregidos en `1c91278`** (skills):
  - los valores ejecutados en modo plan, que no deja escribir ficheros: van por la entrada estándar;
  - `check-runs`, con `--paginate`;
  - `/sincronizar` pregunta el número si la búsqueda del PR por la punta no da uno (GitHub documenta que, si el commit no está en `main`, solo devuelve los abiertos; con #111, fusionado con squash, dio el cerrado).
- **Explicados:**
  - la regex lee todo el cuerpo, comentarios HTML incluidos, y no ve los enlaces hechos a mano en la web; coincide con GitHub en 40 de 40, y `/sincronizar` solo avisa, nunca cierra;
  - los *statuses* de commit no se miran porque todo el CI es de Actions y sale como *check runs*.
- **Pendiente:** separar lecturas de escrituras con comodines es frágil. Un hook `PreToolUse` que analice los argumentos de `gh api` (método, campos, rutas de fusión) sería robusto; propuesta para el Backlog.

**Pendiente**

- **La condición nueva de `claude.yml`**, tras la fusión: un comentario de Pedro que empieza por `@claude` se ejecuta; uno que solo lo menciona sale *skipped* (versión incorrecta 3). Hasta entonces, el chat escribe «arroba claude» y Pedro no asigna issues cuyo cuerpo contenga @claude.
- **El primer uso real del revisor del plan**, en la 7.1, comparado con la revisión del chat del mismo plan.
- **Un hook `PreToolUse` para `gh api`** (hallazgo de la revisión), en lugar de las reglas con comodines: propuesta para el Backlog.
- **Las reglas de Codex** (`.codex/rules/edsim.rules`) siguen con `gh pr create` y `gh pr view`: Codex trabaja en local y pide permiso para todo lo que usa la red; se cambia si una tarea de Codex va a la nube.
