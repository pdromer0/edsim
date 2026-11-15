# Hito 7 — Persistencia

> **Estado:** cerrado con la tarea 7.7 y la etiqueta `v0.7-hito7`. Especificación aprobada el 13 de noviembre de 2026; el original está en este repositorio.

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

- `compose.yaml` añade el servicio `postgres` con la imagen `timescale/timescaledb` en una etiqueta exacta, fijada y comprobada en la 7.5 como Kafka en la 6.1 (decisión 62): `2.31.0-pg17`, con Postgres 17.11. La imagen no tiene etiqueta `latest` a propósito.
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

`record(events, profile, seed, *, horizon, run_id, dice) -> Recording`, en `edsim.clinical_record`. En la 7.1, `dice` es obligatorio; la 7.2 lo hace opcional, con el flujo de la semilla por defecto:

- `events`: el log verdadero completo de una ejecución (los `Event` de `eventos.jsonl`, en su orden).
- `profile`: un perfil cargado de `config/registro_clinico.toml`.
- `seed`: la semilla del registro (por defecto, la de la ejecución).
- `horizon`: el horizonte en minutos (`días × 1.440`).
- `run_id`: el de la ejecución verdadera.
- `dice`: de dónde salen los 13 números (`Roll`) de cada evento verdadero de paciente: un objeto con `roll()`. Los tests los fijan a mano.
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

**Precisiones de la 7.4** (su plan, aprobado el 14 de noviembre de 2026):

- **La sala suelta un registro cuando `s ≤ peek()`.** Todo hecho que aún no se ha visto tiene `sim_time ≥ peek()` y una posición mayor que cualquiera visto, así que en el empate decide la posición. Dentro de la sala, el orden es la clave de emisión completa `(s, posición, orden)`, no el de llegada. Vive en `clinical_record/record.py` (`RecordStream`), junto a los borradores de `record`; `live/` solo la conecta con `run_live`.
- **El censo y el directo:** censo = registros con `s < W` sin episodio o de un episodio abierto en `W` según la verdad; directo = todos los de `s ≥ W`, también los de episodios que la verdad cerró antes (una corrección o un duplicado tardíos). La numeración es la de la grabación entera: lo publicado tiene huecos, como la verdad del hito 6.
- **`censo.episodios`** cuenta los episodios con algún registro en el censo, no los abiertos de la verdad: ningún número de la verdad llega al broker.
- **El bloque `registro`** va detrás de `censo`, con `origen`, `perfil` y `semilla`; el formato sigue en `"version": 1`, y `run_id` tiene que ser el derivado.
- **La reemisión** calcula con `record` y el `--registros` dado. Si la carpeta existe, su `registrado.jsonl` tiene que ser lo mismo, byte a byte; si no, error de datos (código 1) con las dos huellas.
- **Todo lleva el `run_id` derivado:** el `inicio`, los registros, el `fin`, la clave de `ed.runs`, el productor y las órdenes (`edsim directo control --run <derivado>`). El directo no escribe `registros/`.

## Especificación: Postgres y el consumidor

### Compose

```yaml
  postgres:
    image: timescale/timescaledb:2.31.0-pg17   # versión exacta fijada en la 7.5
    environment:
      POSTGRES_USER: edsim
      POSTGRES_PASSWORD: edsim      # solo local; el repositorio no guarda secretos reales
      POSTGRES_DB: edsim
    ports:
      - "127.0.0.1:5432:5432"
    volumes:
      - edsim-postgres:/var/lib/postgresql/data
    healthcheck:                    # por TCP: sin -h, daría por sano el servidor temporal del init
      test: ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U edsim -d edsim"]
volumes:
  edsim-postgres:
```

- Sin perfil: arranca siempre con `docker compose up`, como Kafka y la consola.
- Volumen con nombre: los datos sobreviven a `docker compose down`; para borrarlos, `docker compose down -v`. Kafka sigue sin volumen.
- La consola de Redpanda pasa también a `127.0.0.1:8080` (cierra el #91).

### Tablas (migración `001_bronce.sql`)

```sql
CREATE EXTENSION IF NOT EXISTS timescaledb;   -- añadida en la 7.5
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

Los nombres de las columnas del sobre son los del mensaje (el contrato); los de bronce, en español. La 7.5 confirmó el DDL con la versión fijada (TimescaleDB 2.31.0): `by_range` funciona, y una clave única sin `ingest_time` hace fallar `create_hypertable` («cannot create a unique index without the column "ingest_time"»). La migración empieza con `CREATE EXTENSION IF NOT EXISTS timescaledb`, que no hace nada en las bases de datos de la imagen (la trae `template1`) y la crea en cualquier otra.

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

**Leer lo registrado de bronce:** `read_bronze_records(dsn, run_id) -> list[Record]` reconstruye los registros desde `valor`, uno por `event_id` (si se publicó dos veces, el mismo registro), en orden de `sim_time` y `event_id`. Es lo que usa la comparación con `--postgres`. La 7.5 deja `read_bronze_lines(url, run_id) -> list[str]` en `edsim.store.postgres`, con los `valor` tal cual y en ese orden, porque `Record` llega con la 7.1. `read_bronze_records` es su envoltorio y llega con la 7.3, junto con `registro comparar --postgres`.

## Especificación: la comparación

`compare(truth, records, notebook, *, horizon, warmup=0.0) -> Comparison`, en `edsim.clinical_record.compare` (el horizonte y el calentamiento, en minutos, los necesita el censo medio; el origen del reloj sale de la verdad):

- **Conciliación:** los recuentos de cada `clase` de la libreta, comprobando la cuenta (si no cuadra, `ReconciliationError` con todos los problemas: es un error, no un número); la distribución del retraso (`recorded_time` − `event_time`, que ya no lleva el desfase) por sistema, con mediana y p90, de los registros escritos para su propio hecho (`bien` y `con_despistes`); y la clase `con_despistes` desglosada por tipo de despiste (reloj, retraso, valor erróneo y campo vacío, que se solapan, y cuántas son solo reloj).
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
| `edsim registro comparar RUN_ID` | `--perfil P` (obligatorio), `--semilla N`, `--ejecuciones DIR`, `--postgres [URL]` | La conciliación y los indicadores; con `--postgres`, lo registrado sale de la última publicación de la ejecución derivada en bronce (la verdad y la libreta, siempre de ficheros) |
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

**Resultado de la búsqueda de la 7.2 (14 de noviembre de 2026).** No hay fuente mejor para ninguna tasa: **todos los valores de `config/registro_clinico.toml` quedan «orientativo»** y el fichero lo dice, valor a valor. Lo que la búsqueda añadió:

- **Apoyan órdenes de magnitud de los tiempos:** Gordon 2008 (también con sensores pasivos: 1,1 min antes), Ward 2013 (la mediana de la evaluación clínica, 3 min antes tras implantar un HIS) y un estudio de 1994 en urgencias de Indianápolis, donde el 55 % de los relojes difería 1 min o más del UTC.
- **No apoyan ninguna tasa de olvido, campo vacío, valor erróneo, duplicado ni corrección.** Los duplicados de la literatura (del 5 al 10 % de historias duplicadas) son de identidad del paciente, no de un registro anotado dos veces; y la mala clasificación del triaje (infratriaje y sobretriaje) es criterio clínico, no tecleo.
- **Límite:** NCBI y PubMed no se podían abrir desde la nube; las cifras vienen de los resúmenes de la búsqueda, no de los artículos.
- **La clase `con_despistes` de la libreta es grande** (medido en la 7.6, con 14 días de `config/` y semilla 2026: el 66,7 % de los hechos escritos con el realista y el 99,8 % con el hostil; la 7.2 anotó el 66,8 %, de otra ejecución), y **no es «sobre todo el reloj»**: dentro de la clase, en el realista manda el **retraso** (en el 81,7 % de las filas, por las tasas de 0,60 en el triaje y 0,70 en el HIS; el reloj, en el 32,6 %), y en el hostil, el **reloj** (en el 100 %, porque los cuatro sistemas lo tienen desajustado).

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
│   │   ├── record.py            # record(): los ocho despistes, la emisión y el corte (7.1); la sala de espera, RecordStream (7.4)
│   │   ├── notebook.py          # la libreta y la cuenta (7.1)
│   │   ├── schemas.py           # esquemas del registro (7.1)
│   │   ├── profiles.py          # carga y validación de registro_clinico.toml (7.2)
│   │   ├── compare.py           # conciliación e indicadores ingenuos (7.3)
│   │   └── report.py            # textos en español (7.2, 7.3)
│   ├── runs/                    # record_run y su lectura (7.2)
│   ├── live/                    # --registro en lanzar y reemitir; el censo de lo registrado; inicio con registro (7.4)
│   ├── store/                   # nuevo (7.5)
│   │   ├── sql/001_bronce.sql
│   │   ├── migrations.py
│   │   ├── bronze.py            # mensaje → fila, sin conectar
│   │   ├── consumer.py          # el bucle, con clientes inyectados
│   │   ├── postgres.py          # importa psycopg solo al conectar
│   │   └── report.py            # textos de edsim almacen
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
- Con el perfil **realista**, la cuenta cuadra con lo leído de bronce (`read_bronze_records` y la comparación). Lo añade la 7.4 (reparto del chat del 14-11-2026).
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
| 7.3 (#117) | Comparación: conciliación, retraso e indicadores ingenuos; `edsim registro comparar`, también con `--postgres` y `read_bronze_records` sobre el `read_bronze_lines` de la 7.5 (reparto del chat, 14-11-2026) | A | Nube | Sonnet, alto | `feat/h7-comparacion` | No |
| 7.4 (#118) | Directo y reemisión con `--registro`: la sala de espera, el censo, el `inicio` con registro y «directo = lotes» de lo registrado | A | Local (Kafka) | Opus, alto | `feat/h7-directo-registro` | **Sí** |
| 7.5 (#119) | Postgres y consumidor: compose (cierra #91), extra `postgres`, migraciones, `bronce`, el consumidor, `edsim almacen preparar` y `consumir`, `read_bronze_lines` y el job `tests-integracion` | B | Local (Docker) | Opus, alto | `feat/h7-almacen` | **Sí** |
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
| 7.5 | 7.0 | Se prueba con la verdad que ya publica el directo; `registro comparar --postgres` va en la 7.3, sobre lo que deja la 7.5 |
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
| Un test inestable: `test_consumidor_en_vivo_igual_a_batch[hito4]` falló una vez con −25 ms de latencia (7.4) | Backlog, sin issue | Compara el reloj del broker, en Docker, con el de WSL, que son dos máquinas |
| La parada de `almacen consumir --run` en una republicación (7.6) | Backlog, sin issue | Depende de que el grupo se forme dentro del primer `consume` de 1 s, lo que hoy asegura el `KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS: 0` de `compose.yaml`; con el retraso por defecto (3 s), pararía sin leer la publicación nueva. Remedio posible: no darla por completa hasta tener asignación y estar al día con la marca alta de cada partición. Relacionado: con otro productor publicando sin parar en los mismos topics, `--run` llega al `timeout` (7.5) |
| `compare`: la comprobación opcional de las filas de corrección; que `registro comparar` lea la cuenta de `registro.json` (7.3) | Si hace falta | Hoy la tercera igualdad de la cuenta la comprueba `generar` |
| `fecha_inicio` en `run.json` (7.3) | Si hace falta | Quitaría la deducción del origen del reloj en `compare` |
| Un mensaje claro de `read_run` con lo registrado, en cualquier orden (7.4) | Si hace falta | Mirar el `run_id` derivado antes de `from_json` |
| `--forzar` en `registro generar` (7.2) | Si hace falta | Hoy se borra la carpeta a mano |
| Un hook `PreToolUse` que analice los argumentos de `gh api` (7.0) | Backlog, sin issue | Más robusto que las reglas con comodines de `.claude/settings.json` |
| Las reglas de Codex por REST (7.0) | Si una tarea de Codex va a la nube | `.codex/rules/edsim.rules` sigue con `gh pr create` y `gh pr view` |
| Los rápidos cerca del límite de 60 s con xdist (7.4) | Vigilar | De 24 a 41 s, los de `test_cli_calibracion.py`. En la 7.7, `test_la_comprobacion_con_la_ventana_anual_usa_sus_fechas` pasó de 60 s en la N2 con la máquina cargada; solo y en serie, 22,6 s |

Las nueve últimas filas las añadió el cierre (7.7): son los pendientes del anexo que el hito no arregló.

## Fuentes y para aprender más

Consultadas el 13 de noviembre de 2026, y las de la 7.2 el 14. Las de «para aprender más» están en cada pieza.

| Tema | Fuente | Qué se tomó |
| --- | --- | --- |
| Exactitud de las horas tecleadas | [Gordon, Flottemesch y Asplin, *Annals of Emergency Medicine* 2008](https://pmc.ncbi.nlm.nih.gov/articles/PMC4361868) | Mediana 1,8 min antes de lo observado; rango intercuartílico de 30,7 min antes a 2,9 min después |
| Calidad de las horas tras implantar un HIS | [Ward et al., *American Journal of Emergency Medicine* 2013](https://pubmed.ncbi.nlm.nih.gov/23707000) | Discrepancias de más de 10 min en la decisión de destino: del 29,3 % al 16,1 % |
| Efecto de los errores en los indicadores | [Ward, Self y Froehle, *Academic Emergency Medicine* 2015](https://pmc.ncbi.nlm.nih.gov/articles/PMC4560638) | Cuatro tipos de error al 2, 4 y 7 %; los indicadores de intervalos cortos, los más sensibles |
| Desfase de los relojes clínicos | Estudio de 1994 en cinco urgencias y tres servicios de emergencias de Indianápolis, «Does anybody really know what time it is? Does anybody really care?» (solo su resumen; 7.2) | El 55 % de los relojes difería 1 min o más del UTC |
| Horas con sensores pasivos | Gordon et al. 2008, como arriba (7.2) | Con sensores pasivos, la mediana sale 1,1 min antes de lo observado |
| Historias duplicadas | [McCoy et al., *BMJ Quality & Safety* 2013](https://qualitysafety.bmj.com/content/22/3/219) | Orden de magnitud de las coincidencias de identidad; solo para «Para versiones posteriores» |
| Claves únicas en TimescaleDB | [Documentación de TimescaleDB (Tiger Data)](https://www.tigerdata.com/docs/learn/data-model/primary-keys-time-and-uniqueness) | Toda clave única incluye la columna de partición |
| Imagen de TimescaleDB | [Docker Hub](https://hub.docker.com/r/timescale/timescaledb) | Etiquetas `X.Y.Z-pgNN`; sin `latest` |
| Garantías del consumidor | [Confluent](https://docs.confluent.io/platform/current/clients/consumer.html) y [Conduktor](https://docs.conduktor.io/learn/advanced/consumers/delivery-semantics) | Confirmar después de procesar da «al menos una vez»; con procesado idempotente, sin repetidos |
| Arquitectura medallón | [Databricks](https://docs.databricks.com/aws/en/lakehouse/medallion) | Bronce, plata y oro |
| `psycopg` 3 | [Documentación](https://www.psycopg.org/psycopg3/docs/basic/) | Transacciones, `executemany` y `COPY` |

**Cálculos propios de esta especificación.** Las horas del escenario L, calculadas en Python en el chat. Los valores orientativos son de criterio, con las fuentes de la tabla como órdenes de magnitud.

## Balance del hito

Escrito en la tarea 7.7. El hito deja a EDsim con datos imperfectos, como los de un hospital: los guarda en Postgres y dice exactamente en qué se equivocan. El motor no cambió.

### Qué se entregó y dónde

| Pieza | Dónde |
| --- | --- |
| Simulador del registro clínico: los ocho despistes, el dado, la libreta y la cuenta | `src/edsim/clinical_record/`, [ADR 0084](../decisiones/0084-simulador-del-registro-clinico.md) a [0088](../decisiones/0088-libreta-y-ejecucion-derivada.md) |
| Perfiles limpio, realista y hostil, y `edsim registro validar` y `generar` | `config/registro_clinico.toml`, [ADR 0087](../decisiones/0087-tres-perfiles-y-el-truco-del-dado.md) |
| Lo registrado en el directo y en la reemisión | `edsim directo … --registro`, [ADR 0085](../decisiones/0085-registro-clinico-funcion-pura-de-la-verdad.md) |
| Postgres con TimescaleDB, `bronce` y el consumidor | `compose.yaml`, `src/edsim/store/`, [ADR 0089](../decisiones/0089-postgres-con-timescaledb-en-compose.md) a [0092](../decisiones/0092-migraciones-sql-propias.md) |
| La comparación con la verdad | `edsim.clinical_record.compare`, `edsim registro comparar`, [ADR 0096](../decisiones/0096-una-sola-comparacion-en-python.md) |
| Tests en tres capas y el job `tests-integracion` | `tests_integracion/`, [ADR 0093](../decisiones/0093-tres-capas-de-tests-y-tests-integracion.md) |
| Notebook 07 | `notebooks/07_persistencia.ipynb` |
| Lo que se aplaza: plata y la verdad en el hito 8, la app en su fase 2 | [Para versiones posteriores](#para-versiones-posteriores), [ADR 0094](../decisiones/0094-plata-con-la-forma-de-un-his.md), [0095](../decisiones/0095-la-verdad-no-se-carga-en-postgres.md) y [0097](../decisiones/0097-la-app-no-cambia-en-el-hito-7.md) |
| Lo aprendido | [diario](../diario/hito-7.md), [lecciones](../proceso/lecciones.md) |
| Proceso: la 7.0 y las dos pistas | [ADR 0098](../decisiones/0098-tarea-7-0-de-proceso.md), [ADR 0099](../decisiones/0099-ocho-tareas-en-dos-pistas-y-etiqueta-v0-7-hito7.md), [portabilidad.md](../proceso/portabilidad.md#14-estado-de-las-piezas-en-prueba) §14 |

### Cifras

- **Tiempo:** del primer PR, el de la 7.0, abierto el 13 de noviembre a las 22:05 UTC, al de la 7.6, fusionado el 15 a las 11:14 UTC: 37 h. Son ocho issues (#114 a #121) y un PR por tarea.
- **Los PR de la 7.0 a la 7.6**, con sus commits y los minutos de la apertura a la fusión, sacados de `gh api repos/pdromer0/edsim/pulls/N` y un script, en el orden en que se fusionaron:

  | Tarea | PR | Commits | Apertura → fusión |
  | --- | --- | --- | --- |
  | 7.0 | #126 | 16 | 791 min (abierto de noche, fusionado por la mañana) |
  | 7.1 | #129 | 10 | 43 min |
  | 7.5 | #130 | 22 | 68 min |
  | 7.2 | #133 | 10 | 123 min |
  | 7.3 | #134 | 12 | 18 min |
  | 7.4 | #135 | 14 | 19 min |
  | 7.6 | #136 | 7 | 76 min |

  Entre medias entraron dos PR de la P.3: el #127 (#81, saltar los tests cuando un PR solo cambia documentación) y el #132 (#131, el límite de tiempo por test).
- **Issues que salieron del hito:**
  - **#131**, el límite de tiempo por test y el tope de los dobles, por el cuelgue de la 7.5: cerrado por el #132;
  - **abiertos**, de la sesión conceptual: #122 (la fase 2 de la app con el registro clínico) y #123 (un HIS simulado con CDC);
  - **cerrados de paso:** #110 (el revisor del plan, en la 7.0) y #91 (la consola en `127.0.0.1`, en la 7.5).
- **N3:**
  - en la nube, seis: 17:18 (7.1), 15:12 (7.2), 12:52 (7.3), 16:18 y 13:36 (7.5, antes y después de los ajustes de Codex) y 14:54 (7.6). La mediana es 15:03;
  - en local, una: 13:50 (7.4);
  - la 7.0 no tuvo N3: era una rama de documentación, skills y permisos, y Pedro la autorizó sin ella.
- **Paradas para decidir con Pedro durante la implementación:** dos. Una en la 7.4: el límite de 180 s de `test_every_minute_matches_curves_full_fold_and_cards`. Otra en la 7.5: la integración sin ejecutar en local, porque la hizo el CI. Las demás decisiones nuevas llegaron como ajustes al plan: `retraso_min` y la edad literal en la 7.1, y la última publicación de `--postgres` en la 7.3.
- **Interrupciones:** la sesión local de la 7.5 se cortó tres veces, porque WSL se quedaba sin memoria (ver «Lecciones del hito»).

### Los pilotos de la 7.0, medidos

- **El revisor del plan:**
  - en la 7.1, encontró los seis puntos que cambiaron el plan, incluido el único error de hecho, y el chat no añadió nada que lo cambiara (tabla en la entrada de la 7.1);
  - en la 7.4, dos dudas, las dos aplicadas; una, su propuesta de ordenar la sala por `(s, llegada)`, se aplicó como la versión incorrecta V36, que la descartó;
  - en la 7.5, sus ajustes y los del chat dieron la segunda versión del plan, con diez cambios.

  La prueba de humo de la 7.0 tardó 117 s y gastó unos 43.000 tokens.
- **La revisión del chat**, dos casos del hito:
  - **Una nota del chat sobre `con_despistes` estaba mal.** Decía, como la 7.2, que la clase era «sobre todo el reloj»; el 66,8 % que anotó la 7.2 era la parte de la clase, no lo que pesa el reloj dentro de ella: en el realista manda el retraso. Claude Code lo midió en la 7.6 y lo corrigió.
  - **En el #136, el chat predijo un fallo que no ocurrió:** que la republicación pararía sin leer. No falló porque `compose.yaml` pone `KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS: 0` (queda en «Para versiones posteriores»).
  - **La lección:** las cifras de las notas también se miden, y una predicción se contrasta con la configuración real antes de darla por probable.
- **`@claude` en el PR:** 43 s del comentario al commit en el piloto de la 7.0, y la condición nueva de `claude.yml` comprobada el 14 de noviembre (versión incorrecta 3 de la 7.0).
- **La nube por defecto:** la 7.1, la 7.2, la 7.3 y la 7.6, y la segunda mitad de la 7.5. Funcionó sin GraphQL, con las skills por REST y el tablero movido por Pedro. No fue más rápida: la mediana de la N3 en la nube, 15:03, frente a 13:50 en local en la 7.4, con un núcleo de entre 4.071 tests (la 7.1, según su PR, el #129) y 4.651 (la 7.4). En la 5.7, con menos tests, fue al revés: 10:41 frente a 13:52.
- **Dos pistas:** la 7.5 se hizo en paralelo con la 7.1, y las dos se fusionaron el 14 de noviembre, primero la 7.1. La 7.5 trajo `main` con un merge (`5b8fef4`), como pedían las «Precisiones» de las dos pistas.

### Lecciones del hito

- **El cuelgue de WSL durante la 7.5.** La versión incorrecta V16 dejó un bucle sin fin contra un doble que guardaba cada llamada, y la memoria se agotó. De ahí salió el #131: `pytest-timeout`, y `RunawayLoop` con `check_calls` en los dobles que se llaman en bucle. Ya está en `AGENTS.md`.
- **`.wslconfig` con `memory=7GB` y `swap=8GB`** en un portátil de 16 GB, y como mucho dos mutantes a la vez en local ([portabilidad.md](../proceso/portabilidad.md#3-entorno-desde-cero-windows-con-wsl2-probado) §3).
- **Después de fusionar cualquier PR, también si la rama era de la nube, `/sincronizar`**, que hace el `uv sync`. Tras fusionar el #132 (el #131) se hizo solo `git pull`, y el `.venv` local no tuvo `pytest-timeout` hasta la 7.4.

### Propuestas de velocidad

Salen de lo que costó tiempo en el hito. Ninguna se implanta aquí: cada una, si se aprueba, va en su tarea.

1. **Un hook `PreToolUse` para `gh api`**, que lea el método, los campos y la ruta, en lugar de las reglas con comodines de `.claude/settings.json`. En la revisión de la 7.0 hubo que corregir cuatro reglas.
2. **Avisar al abrir la sesión si el `.venv` no está al día con `uv.lock`**, en el hook `SessionStart` y sin red. Tras el #132, el límite de 60 s no se aplicó en local hasta la 7.4, y nadie lo vio: cuando por fin se aplicó, un test que lo superaba tumbó la N2 tres veces seguidas.
3. **Medir la nube antes de mantenerla por defecto para la N3.** En este hito no fue más rápida que el portátil; su ventaja es dejar el portátil libre. `flujo.md` justifica la regla con las cifras de la 5.7.
4. **Dos pistas también en el hito 8**, si sus tareas se reparten en zonas que no se tocan, como las de este hito.
5. **El chat contrasta sus predicciones con la configuración real** (`compose.yaml`, `config/`) antes de darlas por probables, y mide las cifras de sus notas.

**Pendiente de comprobar:** el salto de los tests del #81 (PR #127) queda para el primer PR que solo toque ficheros `.md`. Este no lo es, porque cambia `config/` y `.gitignore`.

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
- **La prueba de humo del revisor** (versión incorrecta 4), lanzada por Pedro en una sesión nueva y en modo plan: 117 s, 7 llamadas a herramientas y unos 43.000 tokens. Ejecutó `python3` sin bloqueo.
  - Las 16 dudas salen sobre todo de «Diferencias con las notas del chat»: el plan falso omitía a propósito muchas notas del #115, y el revisor las marcó una a una, lo que prueba que lee las notas por REST.
  - La variante del corte, un control, sale «sospechosa» porque usa otro origen del reloj que el registro 7, no por su valor.
  - La celda «1.166,2 es 19:26:12» de su informe no es una errata: es la hora de `sim_time`, sin el reloj de +2.
- **El piloto `@claude`**, con un comentario normal en el PR (usa el `claude.yml` de `main`, sin el aviso de validación del workflow):
  - el comentario de Pedro, a las 09:19:17; la primera respuesta de `claude[bot]`, a las 09:19:37; su commit `a6acb27`, a las 09:20:00: 43 s del comentario al commit (el job declara 22 s);
  - hizo lo pedido en un commit y un fichero, con el prefijo de commit del proyecto, y puntuó el elemento anterior con «;» para que la lista cuadrara. Usó Sonnet 5.5, el modelo de serie de la acción;
  - su push lanzó el CI solo, y los cuatro *check runs* de `a6acb27` (`tests`, `tests-app`, `tests-kafka` y `notebooks`) acabaron en `success`.

**Versiones incorrectas**

| # | Versión incorrecta | Predicción | Observado |
| --- | --- | --- | --- |
| 1 | La regex sin `(?i)` | Los 12 PR que cierran issues dan distinto; los 28 restantes, igual | 12 distintos y 28 iguales |
| 2 | «Fusionado» por `merge_commit_sha` no nulo | Con el PR de la 7.0 abierto, daría «fusionado» | Abierto, con `merged` falso y `merge_commit_sha` relleno (el merge de prueba): habría dado «fusionado». Justo al crearlo era nulo, porque GitHub lo calcula en segundo plano |
| 3 | `claude.yml` con `contains` (lo de `main`) | Tras la fusión, un comentario que solo menciona `@claude` en medio sale *skipped* con `startsWith`; con `contains` se habría ejecutado | Comprobado tras la fusión, el 14 de noviembre, con dos comentarios en el #114: el A, que empieza por la mención, se ejecutó; la respuesta del bot y el B, que solo la nombra en medio, salieron *skipped* (anotado en la 7.7) |
| 4 | Prueba de humo del revisor: un plan falso de la 7.1 con tres errores sembrados y cuatro apartados de control | Marca los tres y ninguno de control | Se cumple. Veredicto «dudas (16)»; S1 (el reloj en `sim_time`), error, y ve que choca con el 1.031,2 del propio plan; S2 (100 pasa a 1), sospechosa; S3, error, con 1.166,2 y 19:28:12 recalculados; ningún control como error |

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

- **La condición nueva de `claude.yml`**, tras la fusión (el piloto ya funcionó con la de `main`): un comentario de Pedro que empieza por `@claude` se ejecuta; uno que solo lo menciona sale *skipped* (versión incorrecta 3). Hasta entonces, el chat escribe «arroba claude» y Pedro no asigna issues cuyo cuerpo contenga @claude. [Hecho el 14 de noviembre: ver la versión incorrecta 3.]
- **El primer uso real del revisor del plan**, en la 7.1, comparado con la revisión del chat del mismo plan.
- **Un hook `PreToolUse` para `gh api`** (hallazgo de la revisión), en lugar de las reglas con comodines: propuesta para el Backlog.
- **Las reglas de Codex** (`.codex/rules/edsim.rules`) siguen con `gh pr create` y `gh pr view`: Codex trabaja en local y pide permiso para todo lo que usa la red; se cambia si una tarea de Codex va a la nube.

### Tarea 7.1: Simulador del registro clínico

**Qué se hizo**

Issue #115, rama `feat/h7-registro`, Claude Code (Opus, en la nube), con `@codex review` (tarea crítica). Primer uso real del revisor del plan. Un commit por paso, más los de las correcciones de la revisión:

- **`validate_run_id` en un módulo neutro**, `edsim.identifiers`. Importar `edsim.runs.identifiers` ejecuta `edsim/runs/__init__.py`, que carga el motor y SimPy. `edsim.runs.identifiers` lo reexporta, como `edsim.lognormal`.
- **`edsim.clinical_record`**:
  - `records.py`: `Record`, el sobre de `Event` con el payload sin validar, y `record_json`, con el orden de claves de `to_json`;
  - `record.py`: `Roll` y `Dice`, `Timed` y `RecordProfile` en código, y `record`, con los despistes 1 a 7, la emisión, el corte y la renumeración;
  - `notebook.py`: la libreta y la cuenta;
  - `schemas.py`: los esquemas `registro-v1` a `v4`.
- **La firma de `record`** gana `dice`, obligatorio en la 7.1; la 7.2 lo hace opcional con el flujo de la semilla.

**Decisiones del diff**

- **El dado:** `Roll` tiene los 13 números con nombre en inglés, en el orden de la especificación (`u_forget` es `u_olvido`, …, `spare` es la reserva), y la tabla de equivalencias está en el docstring de `record.py`. Hay una tirada por evento verdadero de paciente, aunque se olvide o el perfil sea limpio. Los recursos no tiran.
- **El cuantil es `mediana · exp(sigma · z)`:** con z = 0 da la mediana exacta. `exp(log 7)` da 6,999999999999999, y con eso el 1.031,2 del escenario L no saldría exacto.
- **La hora del minuto 0 sale del log:** el primer evento la da exacta, y se comprueba en todos. Un log que no salió de `EventLog`, o que no es del `run_id` dado, es un error antes de tirar.
- **Los desfases**, en milisegundos enteros (`round`). **Las horas registradas** se calculan al numerar, solo de lo escrito: una z enorme lleva un duplicado más allá de cualquier fecha, y no se escribe.
- **La clase sale de lo escrito:** `con_despistes` si cambia `sim_time`, el desfase en ms, un valor o un campo. Tener un duplicado o una corrección no cambia la clase del original.
- **`retraso_min`** (decisión de Pedro): `sim_time` del registro − `sim_time` verdadero de su hecho, en todas las filas escritas. En el escenario L da 7,0, 0,5 y 142,0; en las no escritas, vacío.
- **La edad se invierte literalmente** (decisión de Pedro): 20 … 90 pasan a 2 … 9, y 99 a 100. Son errores inverosímiles a propósito, material para la limpieza del hito 8.
- **La cuenta tiene cinco igualdades:** las tres de la especificación; una de recursos (pasan como `bien`); y «registros, por `event_id` distintos, = filas con registro», que es la que pilla un `event_id` repetido (V4). `record` la comprueba al final.
- **Los esquemas** salen de las ramas de `event_schema`: el payload es anulable, y `record_corrected` es la rama de un evento de paciente con otro tipo, sistema y payload. Llevan título, `description` y `$comment` propios.
- **`edsim.clinical_record.record` es la función, no el módulo:** el paquete exporta `record` con el nombre de su módulo, como pide «Estructura del código». Quien necesite el módulo usa `importlib.import_module`.

**Valores a mano**

El escenario L y sus dos variantes, recalculados con `python3` sin importar `edsim` (el código completo, en el PR):

- **L:** 7 registros, con las horas de la tabla de la especificación. La cuenta: 6 = 4 + 1 + 1 + 0 y 7 = 4 + 1 + 1 + 1.
- **El corte:** 6 registros y una `correccion_pendiente`.
- **El dado:** con el realista, 6 registros y el nivel 3; con el hostil, igual que L.

**Medidas**

- Un log de 14 días de `config/` (55.054 eventos, versión 4):
  - `record` tarda unos 3,5 s; la comprobación del inicio del log, 0,31 s;
  - la cuenta cuadra con el realista y con el hostil (iguales salvo `erroneo`): 78 frente a 620 valores erróneos corregidos;
  - los 55.621 registros del hostil validan contra `registro-v4`;
  - dos llamadas dan los mismos bytes.
- Con las tasas realistas, el 66 % de los hechos es `con_despistes`: el reloj del triaje va +2 y el retraso del HIS tiene una tasa de 0,70. Lo había señalado el revisor del plan.

**Versiones incorrectas**

| # | Versión incorrecta | Predicción | Observado |
| --- | --- | --- | --- |
| V1 | Lo registrado conserva los `event_id` de la verdad | Fallan 10: 9 con el `RuntimeError` de la cuenta (el duplicado y la corrección repiten el id) y el de los recursos | 10 fallan, 57 pasan: los mismos |
| V2 | Se emite por `event_time` | Fallan 6 (L, libreta, las dos variantes, el retraso y la libreta en CSV) | 6 fallan, 61 pasan: los mismos |
| V3 | El reloj mueve también `sim_time` | Fallan 7 (L3 en 1.033,2) | 7 fallan, 60 pasan: los mismos (el duplicado en 14,0 y no 12,0; `retraso_min` 9,0 y no 7,0) |
| V4 | El duplicado conserva el `event_id` del original | Fallan 9, con el `RuntimeError` de la cuenta | 9 fallan, 58 pasan: los mismos (6 ≠ 7, 5 ≠ 6, 1 ≠ 2) |
| V5 | La corrección apunta al `event_id` de la verdad | Fallan 3 (L, la libreta, el dado) | 3 fallan, 64 pasan: los mismos |
| V6 | Lo que cae tras el horizonte se escribe | Fallan 3 (la variante del corte, el hecho pendiente, el horizonte exclusivo) | 3 fallan, 64 pasan: los mismos |

Las seis, con el subagente `mutante` en paralelo, sobre `ca5fbe9`.

**Revisión**

`/code-review high main...feat/h7-registro`, diez hallazgos:

- **Corregidos:**
  - el log de otra ejecución (`dc4b814`);
  - el `OverflowError` con una z enorme y la clase por lo sorteado (`7b0c502`);
  - la cuenta y los `campos` mutables (`2782555`);
  - la cuenta que ningún test descuadraba y el JSON con listas y objetos (`023b325`);
  - el sobre de `record_corrected` repetido a mano y la frontera abierta a todo `edsim.live` (`e19f958`).
- **Explicados:**
  - el ruido de los floats en `retraso_min`: es la definición elegida;
  - `record_json` repite la regla de `to_json`, y un test lo ata;
  - validar el log cuesta el 8 % de `record`;
  - depender de `edsim.live.schemas`, que solo importa el catálogo; la frontera lo vigila.

**El revisor del plan frente al chat**

La comparación que pedía el criterio de aceptación del #115, de la revisión del chat del #129 (añadida en la 7.2, para no pagar otra vuelta del CI en la 7.1):

| Hallazgo sobre el plan | Revisor | Chat |
| --- | --- | --- |
| El test de frontera «como el de `profiles/`» sí existía (`tests/test_sampler.py:218`): error de hecho del plan | Sí | Lo confirmó |
| La edad literal convierte 20…90 en 2…9 | Sí | Lo amplió (21/31/41 → 12/13/14; 99 → 100) y Pedro decidió |
| `retraso_min` con dos significados según la fila | Sí | Pedro decidió una sola definición |
| Dados y perfil del escenario L incompletos | Sí | De acuerdo |
| Traslado de `validate_run_id` sin declarar | Sí | De acuerdo |
| `description` heredada de los esquemas | Sí | De acuerdo |
| Horas del escenario L y de sus variantes | Recalculadas: cuadran | Cuadran |
| La hora del minuto 0, ¿falla en horario de verano? | No | Comprobado: no, porque `TIMEZONE` es +01:00 fijo |

**Conclusión:** el revisor encontró los seis puntos que cambiaron el plan, incluido el único error de hecho. El chat no añadió nada que lo cambiara. En las críticas siguientes (la 7.4 y la 7.5), la revisión del chat del plan puede ser ligera, salvo en lo que el revisor marque como dudoso.

**Pendiente**

- **El flujo real del dado** (hijo 10 de `child_streams(semilla, 11)`), la carga de los perfiles y `record_run`: tarea 7.2 (hecho allí).

### Tarea 7.2: Perfiles del registro clínico y `registro generar`

**Qué se hizo**

Issue #116, rama `feat/h7-perfiles-registro`, Claude Code (Sonnet, en la nube). Tarea no crítica: sin revisor del plan, `/code-review medium`. Un commit por paso, más los de la tabla de la 7.1 y la revisión:

- **El dado real** (`c96c247`): `StreamDice(seed)` en `edsim.clinical_record.record`, y `record(..., dice=None)` lo usa por defecto.
- **La carga** (`5b6e98d`): `clinical_record/profiles.py` con `load_record_profiles`, `RecordProfiles` y `PROFILE_NAMES`.
- **El fichero** (`0c1c583`): `config/registro_clinico.toml`, los tres perfiles, con el estado y la fuente de cada valor.
- **`record_run`** (`9be4508`): `runs/recorded.py`, aditivo en `__all__` de `edsim.runs` (`record_run`, `RecordRunResult`).
- **La CLI** (`44cbc80`): `edsim registro validar` y `generar`, con los textos en `clinical_record/report.py`.
- **Documentación** (`f9a5ae4`, `a9db3ae`): la tabla «el revisor del plan frente al chat» en la entrada de la 7.1 (nota 1 del chat del 14), el resultado de la búsqueda de fuentes, las filas de «Fuentes» y los comandos de `AGENTS.md`.

**Decisiones del diff**

- **El flujo:** hijo 10 de `child_streams(semilla, 11)`, una llamada `random(13)` por tirada. Los `z_*` son la inversa de la normal de su uniforme, con `max(u, 2⁻⁵³)` para que u = 0 dé −8,21 y no un error. Se eligió así, y no `standard_normal`, porque el *ziggurat* gasta un número variable de bits y su flujo puede cambiar entre versiones de numpy: con uniformes el consumo es fijo de verdad. `StreamDice` vive en `record.py`, junto a `Roll` y `Dice`, y no en un `dice.py`: `Roll` está en `record.py` y el módulo nuevo habría sido un import circular.
- **La carga** recorre cada perfil contra una plantilla de claves y junta todos los errores, cada uno con su perfil y su clave. El `limpio` exige 0 en las tasas y los desfases; sus `minutos` solo han de ser válidos. Un entero de 400 cifras, que `float()` no traga, es un error con su clave.
- **`record_run`:** comprobaciones previas sin tocar el disco (perfil, semilla, `run_id` derivado, destino, lectura del log); carpeta temporal oculta dentro de la ejecución (`.registros-<perfil>-s<semilla>-…`), la copia de los perfiles dentro de ella y el perfil cargado de la copia; renombrado final. `registro.json` no lleva fecha: la misma verdad, perfil y semilla dan los mismos bytes. Añade `huella` (la de la copia) a lo que devuelve `record`. Un registro que ya existe es un `FileExistsError`: no hay `--forzar`.
- **`RunLogError`**, un `ValueError` de los datos (una línea que no es un evento, o un log de otra ejecución), para que la CLI distinga el código 1 (datos) del 2 (uso).
- **La inclusión «realista ⊂ hostil»** se cumple con dos salvedades que salen de las tasas: la corrección va al revés (el hostil corrige menos, 0,3 frente a 0,5), y el vacío se une al erróneo, porque `destino` es el único campo de `disposition_decided` y `patient_departed`. El test de inclusión exige que cada despiste ocurra de verdad.
- **Valores:** ninguno cambia. Ninguna fuente da tasas de olvido, vacío, erróneo, duplicado o corrección: todos quedan «orientativo» y el fichero lo dice, con las fuentes de los órdenes de magnitud de los tiempos (Gordon 2008, Ward 2013 y un estudio de 1994 sobre relojes, los tres vistos solo por sus resúmenes).

**Valores a mano** (código independiente de `edsim`; completo en el PR)

- La tirada 1 de la semilla 2026: `[0,640905; 0,145248; −0,514496; 0,091152; 0,751757; 0,309891; 0,793521; 0,72415; 0,872385; −0,632064; 0,588579; −0,298706; 0,556176]`. `spawn(11)[10]` es `SeedSequence(2026, spawn_key=(10,))` y distinto de los hijos 0 a 9.
- La proporción de `con_despistes` con los relojes de la especificación (pregunta del chat): 66,8 % de lo escrito con el realista y 100 % con el hostil, calculada antes (36.539 frente a 18.154 `bien`) y observada después (36.538 frente a 18.152).

**Medidas** (`config/`, 14 días, semilla 2026: 54.968 hechos de pacientes y 86 de recursos)

- La ejecución, 4,4 s; cada `registro generar`, de 5,6 a 6,1 s; cada carpeta, 25 a 26 MB.
- La cuenta cuadra con los tres perfiles:

| Perfil | `bien` | `con_despistes` | Perdidos | Pendientes | Registros | Duplicados | Correcciones |
| --- | --- | --- | --- | --- | --- | --- | --- |
| limpio | 54.968 | 0 | 0 | 0 | 55.054 | 0 | 0 |
| realista | 18.152 | 36.538 | 262 | 16 | 55.118 | 263 | 79 |
| hostil | 0 | 52.137 | 2.738 | 93 | 54.639 | 2.086 | 330 |

- Las tasas observadas, por sistema, frente a las del perfil (script independiente, que lee solo el log, la libreta y el TOML): en las 28 comparaciones, |z| ≤ 1,97 (la mayor, el retraso de laboratorio del hostil, −1,97), y los cuatro relojes coinciden.
- N3 (`scripts/tests-completos.sh`, en la nube): 15:12 en verde: lint 0:00, formato 0:00, núcleo 9:17 (con xdist), app 316 tests en 4:33 y notebooks 6 en 1:21.

**Versiones incorrectas**

Con el subagente `mutante` en paralelo, sobre `6737d01`:

| # | Versión incorrecta | Predicción | Observado |
| --- | --- | --- | --- |
| V7 | Un dado distinto por perfil | Fallan 15: 14 de la inclusión (7 por semilla) y «`record` sin `dice` = con `StreamDice(seed)`» | 15 fallan, 67 pasan: los mismos |
| V8 | `record_run` reescribe `eventos.jsonl` | Fallan 3: las huellas antes y después (una por ejecución) | 4 fallan, 25 pasan: los 3 y `…la_ejecucion_sigue_siendo_valida_para_el_catalogo`, que no estaba previsto: el zip de `archive` guarda el `mtime` de cada fichero. No es un fallo del test, pero no sirve solo (el zip redondea a 2 s); la huella con `mtime_ns` sí |
| V22 | Un `limpio` con algo distinto de 0 se carga | Fallan 18 (17 casos y el de los errores juntos) | 18 fallan, 137 pasan: los mismos |
| V23 | `StreamDice` toma 12 números | Fallan 4 (las dos tiradas, el consumo y 2 de los 3 bordes) | 4 fallan, 109 pasan: los mismos |
| V24 | `record_run` escribe sin carpeta temporal | Fallan 7 (5 de `record_run` y 2 de la CLI) | 7 fallan, 37 pasan: los mismos |
| V25 | La semilla por defecto es 0 | Fallan 2 (uno de `record_run` y uno de la CLI) | 2 fallan, 42 pasan: los mismos |

**Revisión**

`/code-review medium main...feat/h7-perfiles-registro`, siete hallazgos:

- **Corregidos** (`d266051`):
  - `_check_finite` dejaba escapar un `OverflowError` con un entero sin `float` (un perfil en código);
  - un `generar` concurrente recibía un `OSError` crudo en lugar de `FileExistsError`;
  - `MINUTES_PER_DAY` repetida.
- **Explicados:**
  - todo `ValueError` de `record()` pasa a `RunLogError`: hoy todas las comprobaciones previas están antes, así que solo puede ser el log;
  - el truco de los permisos se repite de `simulate_run` (cuatro líneas);
  - `_read_events` carga el log tres veces en memoria (21 MB hoy);
  - el test de los bordes del dado sustituye el atributo privado `_rng`.

**Pendiente**

- **La 7.3** (#117): la conciliación verá la clase `con_despistes` dominada por el reloj [corregido en la 7.6: en el realista manda el retraso; el reloj, en el hostil]; el desglose «por tipo de despiste» lo separa. `registro comparar` lee `registros/<perfil>-s<semilla>/`.
- **La 7.4** (#118): `--registro` en `directo lanzar` y `reemitir` usa `StreamDice` y `load_record_profiles`.
- **Si algún día hace falta sobrescribir un registro:** hoy no hay `--forzar`; se borra la carpeta a mano.

### Tarea 7.3: Comparación con la verdad: conciliación e indicadores ingenuos

**Qué se hizo**

Issue #117, rama `feat/h7-comparacion`, Claude Code (Sonnet, en la nube). Tarea no crítica: sin revisor del plan, `/code-review medium`. Un commit por paso, más el de la revisión:

- **Ayudas de los tests** (`30e7121`): el escenario L y su dado forzado pasan de `test_clinical_record.py` a `tests/registro_factory.py`, y `CountingDice` usa `check_calls` de `tests/runaway.py` en lugar de su `RunawayLoop` propio. 94 tests antes y 94 después.
- **Lectores** (`ac21be6`): `record_from_json` (inverso de `record_json`) y `read_notebook_csv` (inverso de `notebook_csv`).
- **`compare`** (`1a24eea`): `edsim.clinical_record.compare`, con la conciliación y los indicadores ingenuos.
- **Textos** (`09c6d30`): `format_comparison` y `format_indicators` en `clinical_record/report.py`.
- **Leer una ejecución** (`6121ef1`): `read_recorded_run`, `read_recorded_records` y `RecordedRun` en `runs/recorded.py` (aditivo en `__all__` de `edsim.runs`).
- **Bronce** (`d46bc14`): `read_bronze_records` sobre `read_bronze_lines`, y `READ_LINES` pasa a leer la última publicación.
- **CLI** (`810303b`): `edsim registro comparar RUN_ID --perfil P [--semilla N] [--ejecuciones DIR] [--postgres [URL]]`.
- **Integración** (`1e8826b`): `tests_integracion/test_comparar.py`, tres tests contra Postgres.

**Decisiones del diff**

- **`--postgres` lee la última publicación** (propuesta del chat del 14-11): las filas de la ejecución desde su último `inicio` de `bronce.ejecuciones`, una por `event_id`, la más reciente; sin `inicio`, todas. Es la definición con la que `edsim almacen consumir --run` cuenta. Cambia lo que daba `read_bronze_lines` (la primera) y su docstring. Una republicación a medias da una cuenta que no cuadra (error con la pista de `almacen consumir --run`), no el hueco rellenado con la publicación anterior.
- **La cuenta, un error**: `ReconciliationError` (un `ValueError`) con todos los problemas: ids repetidos, registros y filas de la libreta que no se corresponden, hechos sin fila o con dos, y las dos sumas de la especificación. La tercera igualdad (correcciones escritas + pendientes = erróneos con corrección) necesita lo sorteado, que solo está en `registro.json`: la comprueba `generar`, no `comparar`.
- **`compare` recibe `horizon` y `warmup`** (minutos), que la especificación no listaba: el censo medio los necesita. El origen del reloj se deduce del primer evento de la verdad con la misma fórmula que `event_time()`. `--perfil` es obligatorio en `comparar`.
- **Indicadores ingenuos**: el primer registro de cada tipo de cada episodio, en el orden dado (el de emisión); `assessment_started` solo con `tipo == "inicial"`; el censo cuenta `llegada <= H < salida` en cada hora en punto de `[calentamiento, horizonte)`; el reparto por nivel, sobre los `triage_completed` con un nivel entero de 1 a 5, duplicados incluidos; las llegadas, todos los `patient_arrived`. Los `record_corrected` no se leen.
- **El retraso por sistema** es `recorded_time - event_time` de los registros `bien` y `con_despistes` (el desfase se cancela: se suma a las dos horas); los duplicados y las correcciones no entran.
- **`con_despistes` desglosado** (nota del chat de la tarde): con reloj, con retraso, con valor erróneo, con campo vacío (se solapan) y solo reloj. Con la ejecución de `config/`, el reloj domina [corregido en la 7.6: en el realista manda el retraso; el reloj, en el hostil]: 17,5 % de la clase es solo reloj en el realista y 22,2 % en el hostil, pero el reloj aparece en el 100 % del hostil.
- **Traducción de errores de Postgres** compartida (`_postgres_errors`) entre `bronze_store` y `read_bronze_lines`: sin las tablas o con la conexión perdida, el mismo error que el consumidor, no una traza.

**Valores a mano** (código independiente de `edsim`; completo en el PR)

- Escenario L: tiempo hasta el triaje 4,2 frente a 6,2 min; a las 20:00, 1 frente a 2 pacientes; serie de las 17 a las 23 `[1, 2, 1, 1, 1, 1, 1]` frente a `[1, 2, 2, 2, 2, 2, 2]` (medias 8/24 y 13/24); nivel 3 frente a 4; retraso de triaje 7 min y HIS 0 (con el duplicado, 0,25).
- A escala, un script de solo biblioteca estándar recalcula los cinco indicadores de los perfiles realista y hostil desde los ficheros: las cifras coinciden con las de la CLI.

**Medidas** (`config/`, 14 días, semilla 2026: 55.054 hechos, 4.439 llegadas)

- La ejecución, 7,6 s; cada `registro comparar` (55.000 registros), 4,2 s, la mayor parte de import y lectura.
- Verdad frente a registrado (la tabla completa, con el limpio, en el PR):

| Indicador | Verdad | Realista | Hostil |
| --- | --- | --- | --- |
| Tiempo hasta el triaje (mediana, min) | 8,87 | 10,89 (+2,02) | 12,93 (+4,06) |
| Tiempo hasta el médico (mediana, min) | 14,89 | 14,90 (+0,01) | 7,06 (−7,83) |
| Pacientes en urgencias (media por hora) | 39,37 | 50,74 (+11,37) | 155,83 (+116,46) |
| Llegadas (registros de llegada) | 4.439 | 4.442 (+3) | 4.435 (−4) |
| Nivel 4 en el triaje (%) | 50,73 | 50,58 (−0,16) | 49,27 (−1,46) |

  Con el limpio, todo igual. El censo es el indicador que más se estropea, por los fantasmas (las salidas olvidadas); el tiempo hasta el médico del hostil sale menor porque el reloj del HIS (−5 min) y el de admisión (+3) restan 8 minutos.
- Integración: los tres tests pasan en local contra un Postgres 16 sin TimescaleDB (con una extensión de mentira que solo admite las dos llamadas de la migración); en el CI, `tests-integracion`: ver «Revisión del PR» del PR.
- N3 (`scripts/tests-completos.sh`, en la nube): 12:52 en verde: lint 0:00, formato 0:01, núcleo 7:23 (con xdist), app 4:08 y notebooks 6 en 1:20.

**Versiones incorrectas**

Con el subagente `mutante` en paralelo, sobre `b33ee53`; V31 a mano, contra Postgres:

| # | Versión incorrecta | Predicción | Observado |
| --- | --- | --- | --- |
| V9 | La conciliación cuenta los duplicados como hechos | Fallan 4 (el L, su informe y la cuenta real de realista y hostil) | 4 fallan, 164 pasan: los mismos. Con realista, 12.911 hechos en vez de 12.858 |
| V10 | Los indicadores aplican las correcciones | Fallan 4 (nivel del L, su tabla, su informe y el reparto con correcciones) | 4 fallan, 164 pasan: los mismos |
| V26 | Último registro de cada tipo | Fallan 2 (el primero con la llegada duplicada tarde, y el censo con la salida duplicada) | 2 fallan, 166 pasan: los mismos |
| V27 | La conciliación no lanza si la cuenta no cuadra | Fallan 11 (los 8 casos, «todos los problemas» y 2 de la CLI) | 11 fallan, 157 pasan: los mismos |
| V28 | El retraso incluye duplicados y correcciones | Fallan 2 (el retraso del L y su informe) | 2 fallan, 166 pasan: los mismos |
| V29 | Empates en la hora en punto al revés | Fallan 5 | 5 fallan, 163 pasan: los mismos |
| V30 | La media del censo incluye el calentamiento | Fallan 5 (4 casos de las horas y la media) | 5 fallan, 163 pasan: los mismos |
| V31 | `READ_LINES` lee la primera publicación | Falla la integración con dos publicaciones | Fallan 2 de 3 (la última publicación y la cortada). Una variante, «la más reciente por `event_id` sin el `inicio`», falla solo la de la publicación cortada |

Dos ajustes de los tests durante la tarea: la primera versión de la integración no distinguía V31 (la publicación vieja tenía una hora ilegible, que bronce rechaza, y quedaba como un prefijo idéntico de la nueva); y el test del reparto con correcciones corregía un nivel al mismo valor que ya tenía, así que V10 no lo habría visto. Los dos se arreglaron antes de lanzar las versiones.

**Revisión**

`/code-review medium main...feat/h7-comparacion`, seis hallazgos:

- **Corregido** (`58c6c48`): un horizonte enorme y finito (`1e300`) daba `OverflowError` en lugar de `ValueError`.
- **Explicados:**
  - `_origin` repite la fórmula de `event_time()`; `run.json` no guarda la fecha de inicio;
  - `record_from_json` repite la comprobación del sobre de `from_json`, que además arregla logs antiguos (`_upgrade`);
  - la tercera igualdad de la cuenta se queda en `generar` (necesita `registro.json`);
  - con `--postgres` antes del identificador de la ejecución, este se lee como la URL: el orden está en la ayuda.

**Pendiente**

- **La 7.4** (#118): `--registro` publica lo registrado; con él, el test de integración puede usar el camino real (publicar y consumir).
- **La 7.6** (#120): el notebook usa `compare` y la tabla verdad frente a registrado.
- **Si hace falta la tercera igualdad en `comparar`:** leer `cuenta` de `registro.json` y compararla con la libreta.
- **Que `run.json` guarde `fecha_inicio`:** quitaría la deducción del origen del reloj.

### Tarea 7.5: Postgres con TimescaleDB y consumidor de bronce

**Qué se hizo**

Issue #119, rama `feat/h7-almacen`, Claude Code; cierra también el #91 (la consola en `127.0.0.1:8080`). Primera tarea de la pista B, en paralelo con la 7.1, que se fusionó antes: la rama trae `main` con un merge. Los pasos 1 a 9, en local; el merge, las versiones incorrectas, la revisión y la N3, en la nube (ver «Proceso»). Un commit por paso, más los de las correcciones de la revisión:

- **`compose.yaml`**: `postgres` con `timescale/timescaledb:2.31.0-pg17` (Postgres 17.11), el volumen `edsim-postgres`, solo en `127.0.0.1:5432` y el healthcheck por TCP (`pg_isready -h 127.0.0.1`); la consola, en `127.0.0.1:8080`.
- **El extra `postgres`** (`psycopg[binary]>=3.3.9,<3.4`). El test de frontera pasa a una tabla de clientes opcionales con su único módulo: `confluent_kafka` en `live/kafka.py` y `psycopg` en `store/postgres.py`, los dos dentro de funciones.
- **`edsim.store`**:
  - `migrations.py` y `sql/001_bronce.sql`: el aplicador y la migración de las tres tablas;
  - `bronze.py`: de un mensaje de Kafka a una fila de `eventos`, `ejecuciones` o `rechazados`, sin conectar a nada;
  - `consumer.py`: el bucle, guardar y después apuntar, con la red de seguridad;
  - `postgres.py`: la conexión, `PostgresBronze`, `prepare` y `read_bronze_lines`;
  - `report.py`: los textos de la CLI.
- **`KafkaSink.start`** espera (`flush`) a que el broker confirme el `inicio` antes de mandar el censo, y falla si no llega.
- **La CLI**: `edsim almacen preparar` y `edsim almacen consumir [--run RUN_ID] [--timeout S]`.
- **Integración**: la base de datos de cada sesión (`edsim_test_<8 hex>`), cuatro tests en `tests_integracion/test_almacen.py`, `scripts/tests-integracion.sh` con los dos servicios y el job `tests-kafka` renombrado a `tests-integracion` (conserva `needs: cambios` y su `if`).

**Decisiones del diff**

- **La imagen es `2.31.0-pg17`**, no la `2.32.0-pg17` de dos días antes, como la consola v3.14.0 en la 6.1. **`001_bronce.sql` empieza con `CREATE EXTENSION IF NOT EXISTS timescaledb`**: la base de datos de los tests se crea con `CREATE DATABASE` y no la trae.
- **`bronze.py` no valida con el catálogo:** lo registrado tiene campos a `null` y `record_corrected`. Exige solo las claves que llenan columnas, con sus tipos, y deja las demás en `valor`. Manda a `rechazados` todo lo que se sabe que rompe el `INSERT` (un entero fuera de `integer`, NaN e infinito, NUL, sustitutos sueltos, UTF-8 roto, horas sin zona), porque un mensaje así bloquearía el consumidor: releería el mismo lote para siempre.
- **La red de seguridad**, para lo que nadie previó: si el `INSERT` del lote falla por un dato, el lote se repite fila a fila con un `SAVEPOINT` por fila, y solo la que falla va a `rechazados`, con el mensaje de Postgres. Un error que no es de datos se propaga sin confirmar.
- **Se inyecta un almacén, no la conexión:** las transacciones, los savepoints y la red viven en `consumer.py`, sobre las primitivas de `PostgresBronze`, y se prueban en rápidos con `tests/fake_store.py`. La integración prueba lo que el falso solo imita: `ON CONFLICT`, su recuento y el error de Postgres.
- **`--run` cuenta en bronce, desde el último `inicio`:** así termina un consumidor relanzado, que no vuelve a ver lo ya confirmado, y no lo engaña una publicación anterior de la misma ejecución. Por eso el `inicio` tiene que llegar antes que el censo (el `flush`). Y la da por completa solo con el consumidor al día, cuando el último `consume` volvió vacío: una publicación nueva puede estar aún en Kafka (ajuste de la revisión del PR).
- **`read_bronze_lines`** en lugar de `read_bronze_records`: `Record` era de la 7.1, sin fusionar cuando se planeó la 7.5.
- **El grupo de la integración es único** (`edsim-bronce-test-<8 hex>`): con `edsim-bronce`, un test movería los offsets del consumidor de Pedro. Por eso la integración llama a las funciones y no a `edsim almacen consumir`, que se prueba en rápidos con dobles y Pedro comprueba a mano.
- **El extremo a extremo y el de parar y relanzar son un solo test**, publicado con `edsim directo lanzar --velocidad max`: la primera pasada para cuando bronce tiene algo de la ejecución, y el test exige 0 < guardados < publicados antes de relanzar, para no pasar vacío.

**Valores a mano**

Recalculados con `python3` sin importar `edsim` (el código, en el plan y en el PR):

- La marca 1.767.225.600.123 ms es `2026-01-01T00:00:00.123+00:00`.
- `"2026-01-05T12:19:01.200+01:00"` es 11:19:01.200 en UTC; sin zona, se rechaza.
- La caída entre guardar y apuntar (7 mensajes, lotes de 3, caída al confirmar el lote 2): 7 filas, 3 repetidos ignorados y ninguno perdido. Apuntando antes (V13), 4 filas, y se pierden los mensajes 3, 4 y 5.

**Medidas**

- El job de integración antes: `tests-kafka`, 1:30 (CI de `main`, `cdde0a4`). Después, `tests-integracion`: 1:46 (`7268d1b`), con 28 tests en 60 s; el script, arranque 0:32, pytest 1:04 y total 1:37.
- En local, `scripts/tests-integracion.sh` antes del cambio: 1:16. Después no se midió en local (ver «Proceso»).
- N3 (`scripts/tests-completos.sh`, en la nube): 16:18 en verde: lint 0:01, formato 0:00, núcleo 4.184 tests en 11:19 (con xdist), app 316 en 3:45 y notebooks 6 en 1:13.

**Versiones incorrectas**

| # | Versión incorrecta | Predicción | Observado |
| --- | --- | --- | --- |
| V13 | Confirmar antes de guardar | Fallan 2: el orden de las llamadas y la caída (3 filas en vez de 6) | 3 fallan, 97 pasan: los 2 y `…un_error_que_no_es_de_datos_se_propaga_sin_confirmar`, que también ve un commit que no debía existir |
| V14 | Clave única por las coordenadas de Kafka | A mano: `create_hypertable` falla, porque Timescale exige la columna de partición en toda clave única | Falla así (paso 1, a mano) |
| V15 | `ingest_time` = hora de recepción | Fallan el de la marca de `bronze.py` y el de la fila guardada del bucle | 43 fallan: los 2, todos los que comparan `ingest_time` (33 de `bronze.py`, entre ellos los 30 casos de `rechazados`) y los de `--run`, que vencen el `timeout` porque los eventos quedan antes del `inicio`. La predicción solo contaba los tests escritos para pillarla |
| V16 | Aceptar `CreateTime` | Fallan el del tipo de marca de `bronze.py` y el del bucle | 4 fallan, 78 pasan: los 2, `…la_marca_se_comprueba_tambien_en_lo_que_se_rechazaria` y el de la CLI con una marca que no es del broker, que con el tope falla con `RunawayLoop` en 11 s (sin él, giraba sin fin: ver «Proceso») |
| V17 | Sin el límite de `integer` en `schema_version` | Falla solo el caso de 2³¹ | 1 falla (`[value10-schema_version]`), 63 pasan |
| V18 | `--run` cuenta en memoria | Falla solo «relanzar con `--run` termina» | 2 fallan, 32 pasan: el predicho y `…cuenta_desde_la_ultima_publicacion`, porque los `event_id` de las dos publicaciones se solapan y el recuento en memoria da 3 = 3 |
| V19 | El aplicador no registra la migración | Fallan 3 | 3 fallan, 27 pasan: los mismos |
| V20 | `tests-integracion` sin `needs`/`if` | No es un test | El diff de `ci.yml` los conserva, y en el CI del PR el job corrió después de `cambios` y pasó |
| V21 | Sin la red de seguridad | Falla el de la fila que Postgres no acepta | 1 falla, 33 pasan: el mismo |

Las rápidas, con el subagente `mutante` en paralelo, sobre `5b8fef4`, el merge de `main`; V16, repetida sobre `bd6457f`, el commit del tope.

**Revisión**

`/code-review high` contra `origin/main`, diez hallazgos:

- **Corregidos:**
  - `start` ignoraba lo que devolvía el `flush`: con el `inicio` aún pendiente, el censo seguía (`99e51b9`);
  - `tests-integracion.sh` bajaba con `down` un Kafka que ya estaba en marcha si Postgres no lo estaba (`ace600e`);
  - los errores de Postgres a mitad de camino salían como una traza de Python (`f914b5f`);
  - `safe_url` no tapaba un `password=` en la consulta (`4cb0a5b`);
  - la primera pasada del test de integración podía guardar la ejecución entera antes de parar, y `dataclasses.replace` en lugar de un ayudante (`9f9f732`).
- **Encontrado al probar V16, fuera de la revisión:** con V16, un test de la CLI no terminaba nunca (`bd6457f`, ver «Proceso»). El consumidor falso corta ahora un bucle que no para (`RunawayLoop` tras 10.000 llamadas a `consume`) y, sin reloj, espera 1 ms con un lote vacío, como el de verdad espera su `timeout`.
- **Explicados:**
  - `progress` en cada vuelta del bucle: cuesta un recuento por lote, pero es lo que hace terminar un `--run` cuando parte de la ejecución la guarda otro consumidor del mismo grupo;
  - `insert_rejected` fuera de un savepoint en la red: no hay nada que lo haga fallar, porque `valor` y `motivo` ya llegan sin NUL ni sustitutos;
  - `read_bronze_lines` devuelve la primera publicación y `--run` cuenta la última: es la decisión del plan; la 7.3 decide qué lee `registro comparar --postgres`;
  - Ctrl+C mientras se conecta espera a los timeouts de conexión, pero no tapa el error;
  - el error de `commit` de Kafka sigue saliendo con su traza (código 1), como decidió el plan: traducirlo pediría importar `confluent_kafka` fuera de `live/kafka.py`.

**Ajustes de la revisión del PR**

Codex encontró dos fallos, los dos ciertos (análisis del chat en el PR). Un commit por arreglo, con el test escrito antes y ejecutado contra el código sin arreglar:

| Hallazgo | Predicción del test sin el arreglo | Observado | Arreglo |
| --- | --- | --- | --- |
| `--run` daba por completa una publicación vieja: miraba `progress` antes del primer `consume`, así que con la publicación 1 completa en bronce y la 2 en Kafka terminaba sin leerla | Termina sin llamar a `consume` | `assert 0 == 2` en `consumer.consumes`: termina con 0 llamadas. Con el arreglo, guarda la 2 (5 filas: el `inicio`, 3 eventos y el `fin`) en dos llamadas, la segunda vacía | `progress` tras cada `consume`; completa solo si además ese `consume` volvió vacío (`6345783`) |
| Un JSON muy anidado lanzaba `RecursionError`, que no es `ValueError`, se escapaba de `to_row` y bloqueaba la partición | Con 1.100 niveles falla `_check_strings`; con 100.000, ya `json.loads` (comprobado antes con `python3`) | Los dos con `RecursionError`, en `bronze.py:233` y en el decodificador de `json`. Con el arreglo, los dos van a `rechazados`; de 900 a 1.100 niveles no se escapa nada (hasta 995, fila de `eventos`; desde 1.000, rechazo) | Los dos sitios convierten `RecursionError` en `_Unreadable`, con el motivo «JSON demasiado anidado» (`690f6ac`) |

Una sola N3 tras los dos: 13:36 en verde (lint 0:00, formato 0:00, núcleo 4.187 tests en 8:17 con xdist, app 316 en 4:01 y notebooks 6 en 1:18).

**Proceso**

- **La sesión local se interrumpió tres veces**, porque WSL se quedaba sin memoria durante las versiones incorrectas. La primera vez había siete mutantes en paralelo con Docker levantado; la segunda, dos mutantes a la vez con Docker levantado: el portátil, con 16 GB, al 96 % y VmmemWSL en 6,4 GB. Se resolvió así: reinicio, WSL limitado a 7 GB con 8 GB de swap, Docker Desktop cerrado salvo para la integración y los mutantes de uno en uno. La tercera, también durante las versiones incorrectas, llevó lo que quedaba a la nube: el merge, las siete versiones incorrectas en paralelo (repitiendo V13, V17 y V19, cuyos resultados locales no se guardaron en el repositorio), la revisión y la N3.
- **La causa probable no era el paralelismo, sino V16.** En la nube, el pytest de V16 sobre `test_cli_almacen.py` llegó a 7,5 GB en un minuto, con la CPU al 100 %, y hubo que matarlo. Aceptando `CreateTime`, el test de la marca que no es del broker ya no para: `edsim almacen consumir` sin `--run` gira sin fin contra el broker falso, que no tiene reloj, y el registro del falso crece en cada vuelta. V16 estaba en la tanda de siete y era la primera de la lista de una en una. Con el tope del consumidor falso (`bd6457f`), ese test falla con `RunawayLoop` en lugar de llenar la memoria, y V16 se repitió sobre ese commit.
- **Sin `scripts/tests-integracion.sh` en local**, por decisión de Pedro (se aparta de «La 7.4 y la 7.5 ejecutan `scripts/tests-integracion.sh` antes del push»): la integración contra Kafka y Postgres la hace el job `tests-integracion` del CI de este PR, y Pedro comprueba a mano `edsim almacen preparar` y `consumir` contra los servicios locales.

**Pendiente**

- `read_bronze_records` (con `Record`) y `registro comparar --postgres`: tarea 7.3.
- «Con el perfil realista, la cuenta cuadra con lo leído de bronce»: tarea 7.4.
- Lo de la memoria de WSL, para `docs/proceso/portabilidad.md`, si Pedro lo pide.
- `--run` con otro productor publicando sin parar en los mismos topics: `consume` no vuelve nunca vacío, así que `--run` espera hasta el `timeout` (código 1) aunque bronce ya tenga la ejecución. No pasa en los tests ni con un solo directo; si hace falta, «al día» podría ser un lote con menos mensajes que `batch_size`.

### Tarea 7.4: Directo y reemisión con el registro clínico

**Qué se hizo**

Issue #118, rama `feat/h7-directo-registro`, Claude Code (Opus, en local). Tarea crítica: revisor del plan, `/code-review high` y `@codex review`. Un commit por paso, más los de la revisión:

- **Las ayudas de `record`** (`d41f849`): `_event_drafts` (los despistes de un hecho) y `_finish` (el registro de un borrador numerado) salen de `record()` sin cambiar un byte.
- **La sala de espera** (`1c1609e`): `RecordStream` en `clinical_record/record.py`.
- **El `inicio` con registro** (`89b2b51`): `RecordInfo` en `RunInfo.record`, el bloque `registro` en `run_start_json` y `parse_run_message`, el esquema de `ed.runs` ampliado y `LiveTracker` que lo rechaza.
- **`run_live` con lo registrado** (`d5252fe`): la sala en el directo, `recorded_census`, `RecordedLog` y los sumideros con `Record`.
- **La reemisión** (`1693505`): `replay_records` (aditivo en `__all__` de `edsim.runs`), `with_recording` y `prepare_replay(record_profile=…)`.
- **La CLI** (`092c0c5`): `--registro`, `--semilla-registro` y `--registros` en `lanzar` y `reemitir`.
- **El lento** (`a5c115b`) y **la integración** (`2a7b1ac`); **la especificación y `AGENTS.md`** (`f0776cd`).

**Decisiones del diff**

- **La sala suelta con `s ≤ peek()`**, con el montículo por la clave de emisión completa (ver «Precisiones de la 7.4» en la especificación). Comprueba también que no llega un hecho anterior a una cota ya soltada: si llegara, la cota no era `peek()`.
- **Lotes y directo comparten los despistes, no la ordenación:** `record` ordena todo de una vez; la sala, con el montículo. Así «directo = lotes» compara dos ordenaciones distintas.
- **La reemisión usa `record`** (la especificación), no la sala: `RecordedLog` suelta los registros ya ordenados con la misma regla, `s ≤ peek()`.
- **Los registros viajan como los eventos:** `route` y las cabeceras no cambian; el valor es `record_json`.
- **`censo.episodios`** cuenta los episodios entre los registros del censo; el texto de la CLI dice «episodios con registros».
- **Un perfil de cualquier nombre** se puede publicar desde el código (`RecordInfo` no exige los tres del fichero); la CLI los limita con `choices`.

**Medidas**

- `record` con `config/`, 14 días y semilla 2026, de 2,2 a 2,5 s por perfil; las huellas de `registrado.jsonl` y `defectos.csv` de los tres perfiles, iguales antes y después del refactor.
- El lento «directo = lotes» de lo registrado: de 1,1 s (v2) a 2,3 s (v3) por caso.
- N3 (`scripts/tests-completos.sh`, en local): 13:50 en verde (lint 0:00, formato 0:00, núcleo 4.651 tests en 10:08 con xdist, app 316 en 2:46 y notebooks 6 en 0:56).
- `scripts/tests-integracion.sh`, en local: 33 tests en 1:47, 1:58 en total (arranque 0:09). La primera vez fallaron los dos nuevos (sobraba un `fetchall`, `0aa1fb8`) y `test_consumidor_en_vivo_igual_a_batch[hito4]`, con una latencia de −25 ms frente al mínimo de −5 ms (el reloj del broker, por delante del de WSL); en la segunda, todo en verde.

**Versiones incorrectas**

Con el subagente `mutante`, dos a la vez, sobre `2a7b1ac` (V11 y V12) y `f0776cd` (las demás):

| # | Versión incorrecta | Predicción | Observado |
| --- | --- | --- | --- |
| V11 | La sala ordena y suelta por la hora verdadera del hecho | Fallan 13: la tabla de L, los mismos bytes que `record` (4), el directo de L, su censo, la reemisión = sala (2) y los 4 lentos | 13 fallan, 172 pasan: los mismos |
| V12 | Con la sala, el directo publica también la verdad | Fallan 9 (7 del directo y 2 de la CLI) | 10 fallan: los 9 y `la_reemision_publica_lo_mismo_que_la_sala[1000.0]`. `RecordedLog` ya tiene todos los registros y suelta el 1 en el censo, antes del paso de L1, y la sala después: con la verdad colada, los dos lados se intercalan distinto |
| V32 | Los abiertos del censo, según lo registrado | Fallan 6: el censo con `W` = 1.140, la reemisión = lotes y los 4 lentos | 6 fallan, 179 pasan: los mismos |
| V33 | Se numera solo lo publicado | Fallan 6: el censo con `W` = 1.140, la reemisión = lotes y los 4 lentos | 6 fallan, 179 pasan: los mismos |
| V35 | La reemisión no compara la carpeta | Fallan 3: los dos casos del lanzador y el de la CLI | 3 fallan, 159 pasan: los mismos |
| V36 | La sala ordena por `(s, llegada)` (propuesta del revisor del plan) | Falla 1: duplicado y corrección a la misma hora | 1 falla, 141 pasan: el mismo |

La predicción de V12 se corrigió antes de lanzarla, al escribir los tests: el plan contaba también el censo con `W` = 1.140, que no puede fallar, porque con ese `W` no queda verdad en el directo.

**Revisión**

`/code-review high main...feat/h7-directo-registro`, diez hallazgos:

- **Corregidos** (`15ee6ce`, `5fe44a8`): una carpeta que no es un registro daba código 2 en vez de 1; una sola serialización de `registrado.jsonl` para escribir y comparar; el log de la reemisión se abría antes de que pudiera fallar `replay_records`; `RecordedLog.ready(NaN)`; `Record` solo para anotar en `census.py` y `status.py`; el valor por defecto de `--registros` en un solo sitio.
- **Explicados:**
  - `read_run` sobre un derivado puede fallar en `from_json` antes del aviso de `LiveTracker`: `read_run` es para la verdad, y leer lo registrado con él sigue siendo un error;
  - la reemisión carga el log y los registros enteros, como `record_run`: lo pide la especificación (`record`);
  - `_replay` carga los perfiles dos veces, la primera para el error de uso con el nombre de la opción;
  - un `perfil` cualquiera en el bloque `registro`: ver «Decisiones del diff».

**Proceso**

- **`pytest-timeout` no estaba en el `.venv` de Pedro** (ni en la caché de uv): el límite de 60 s de #131 no se había aplicado nunca en local. Con el `uv sync` del paso 0, la N2 cayó tres veces en `test_every_minute_matches_curves_full_fold_and_cards` (28 s solo, 73 s con xdist). Por decisión de Pedro, ese test lleva `@pytest.mark.timeout(180)` (`521caa3`).

**Pendiente**

- **La 7.6** (#120): el notebook puede publicar con `--registro` y leer bronce.
- **`read_run` con lo registrado:** si hace falta un mensaje claro en cualquier orden, mirar el `run_id` derivado antes de `from_json`.
- **Los otros tests rápidos cerca del límite con xdist** (de 24 a 41 s, los de `test_cli_calibracion.py`): vigilarlos.

### Tarea 7.6: Notebook `07_persistencia`

**Qué se hizo**

Issue #120, rama `feat/h7-notebook`, Claude Code (Sonnet, en la nube; el modo normal, con Docker, lo ejecuta Pedro en local). Tarea no crítica: sin revisor del plan, `/code-review medium`. Un commit por paso:

- **El notebook** (`5c9c731`): `notebooks/07_persistencia.ipynb`, 44 celdas, sin resultados. Lo escribió un script del *scratchpad* (no se versiona) y quedó formateado con `ruff format`.
- **Un fallo del modo normal** (`fix(notebooks)`): `record_run` lee por defecto `config/registro_clinico.toml` relativo al directorio de trabajo, y el notebook corre desde `notebooks/`; se le pasa el fichero con ruta absoluta.
- **Los ajustes de la revisión propia** (`fix(notebooks): 07 tras la revisión propia`): ver «Revisión».
- **La documentación:** esta entrada, `README.md` y `AGENTS.md` (los comandos y requisitos del 07) y la corrección de la frase del reloj en «Valores orientativos de partida».

**Decisiones del diff**

- **Sin lógica propia.** El notebook llama a `EventLog`, `record`, `compare`, `format_comparison`, `simulate_ed`, `simulate_run`, `record_run`, `read_recorded_run`, `read_bronze_lines`, `read_bronze_records`, `to_row` y `save_batch`; la CLI (`edsim directo reemitir`, `almacen preparar`, `almacen consumir` y `registro comparar`) va por `subprocess`, como el 06. Lo único que escribe él es lo que un lector necesita para ver el fenómeno: el dado a mano de Lucía (una clase con `roll()`, que es el protocolo `Dice`), el perfil de Lucía (`dataclasses.replace` sobre el realista), las agrupaciones del doble clic y los recuentos de despistes.
- **Las secciones 2 a 6 corren en memoria en los dos modos** y son idénticas; la 7 es la única que usa disco y servicios. Una sola ejecución (14 días, 2 de calentamiento, semilla 2026) alimenta todo, porque con ella salen las cifras que citan las notas (censo +29 % y ×4); con 7 días, +12 % y ×2,7.
- **Los `assert` comprueban estructura, no cifras:** la tabla de L (horas y `sim_time` de los siete registros), la cuenta de L, el subconjunto de olvidos y de erróneos entre perfiles, doble clic = filas `duplicado`, el reloj del hostil en todas las filas, y en la sección 7, que bronce tiene tantas filas como registros, que la relectura guarda 0 y repite todas, que la republicación da el doble de filas y los mismos `event_id`, y que `compare` da lo mismo con ficheros, con bronce y en memoria. La única tolerancia es la de 1 min en el tiempo hasta el médico del hostil frente a la resta de los relojes (−8 min; sale −7,83 por los hechos olvidados o vacíos).
- **Reemisión con `--calentamiento 0`** (W = 0, sin censo), como `tests_integracion/test_directo_registro.py`: bronce recibe los 55.118 registros y la cuenta se puede reconciliar.
- **La relectura de Kafka** se enseña volviendo a guardar con `save_batch` cinco mensajes que bronce ya tiene (reconstruidos con `KafkaMessage` desde sus coordenadas y su `ingest_time`), el mismo camino del consumidor; no relanzando `almacen consumir`, que usa un grupo fijo.
- **La clase `con_despistes` no la domina el reloj en el realista** (ver «Pendiente» y la corrección de «Valores orientativos de partida»). El notebook lo dice con el desglose de `compare`.
- **La ejecución guardada de la sección 7 va a una carpeta temporal**, nunca a `resultados/ejecuciones/`, y se borra al final de la celda.

**Medidas**

- N3 (`scripts/tests-completos.sh`, en la nube): 14:54 en verde (lint 0:00, formato 0:00, núcleo 9:47, app 3:44, notebooks 1:23).
- Modo rápido: el notebook, 14 s (11 s dentro del kernel); los siete notebooks, 83 s en total (el 04 tarda 21 s, el 03 18 s, el 07 14 s). Muy por debajo de los 1.800 s de #131.
- Cifras de la ejecución (14 días, 2 de calentamiento, semilla 2026, 55.054 hechos):

  | Perfil | Registros | bien / con_despistes / duplicado / corrección / perdido / pendiente | Censo medio (verdad → registrado) | Hasta el médico | Hasta el triaje |
  | --- | --- | --- | --- | --- | --- |
  | limpio | 55.054 | 55.054 / 0 / 0 / 0 / 0 / 0 | 39,37 → 39,37 | 14,89 → 14,89 | 8,87 → 8,87 |
  | realista | 55.118 | 18.238 / 36.538 / 263 / 79 / 262 / 16 | 39,37 → 50,74 (+28,9 %) | 14,89 → 14,90 | 8,87 → 10,89 |
  | hostil | 54.639 | 86 / 52.137 / 2.086 / 330 / 2.738 / 93 | 39,37 → 155,83 (×3,96) | 14,89 → 7,06 (−7,83) | 8,87 → 12,93 |

- Fantasmas (salidas olvidadas): 25 de los 262 olvidos del realista y 220 de los 2.738 del hostil. Olvidos del realista ⊆ olvidos del hostil: sí. Dobles clics: 263 grupos = 263 filas `duplicado`.
- **Desglose de `con_despistes`:** realista, 36.538 filas: retraso 81,7 %, reloj 32,6 %, solo reloj 17,5 %, 160 erróneos, 528 vacíos; hostil, 52.137 filas: reloj 100 %, retraso 75,6 %, solo reloj 22,2 %.
- **Lo que no se pudo ejecutar en la nube** (no hay Docker): la sección 7 con Kafka y Postgres. Sí se comprobó, sin servicios, lo que la rodea: `simulate_run`, `record_run` (55.118 registros, la misma cuenta que en memoria), `edsim directo reemitir … --calentamiento 0 --registro realista --memoria` (publica 55.118, 0 de censo y 55.118 en directo), `edsim registro comparar` con ficheros, y que la comparación desde ficheros es igual a la de memoria (`Comparison` entera).
- **Lo que debe salir en modo normal** (Pedro): tras publicar y consumir, `bronce.eventos` con **55.118** filas y 55.118 `event_id` distintos para el run derivado; `bronce.ejecuciones` con un `inicio` y un `fin`; **263** dobles clics; la relectura, `saved=0, repeated=5`; tras republicar, **110.236** filas y 55.118 `event_id`; `read_bronze_lines` con 55.118 líneas; y `registro comparar --postgres` igual que con ficheros salvo la línea del origen.

**Versiones incorrectas**

Cinco, aplicadas en el árbol de trabajo sobre el notebook ya confirmado y deshechas con `git checkout` (sin el subagente `mutante`: el cambio es de un solo fichero y no hay worktree que aislar). Cada una, ejecutada con `EDSIM_NB_RAPIDO=1 pytest --nbmake notebooks/07_persistencia.ipynb`:

| # | Versión incorrecta | Predicción | Observado |
| --- | --- | --- | --- |
| V1 | El dado de L6 sin forzar el olvido | Falla el 07 en un `assert` de L | 1 falla (`AssertionError`, en la lista de horas de L, antes que en la cuenta); 2,5 s |
| V2 | La celda de Kafka y Postgres sin el guardia del modo rápido | Falla el 07 en modo rápido | 1 falla. **La predicción no pillaba el motivo:** la primera vez falló con `FileNotFoundError: config/registro_clinico.toml` (un fallo real del modo normal, ver «Qué se hizo»); tras corregirlo, falla en `edsim almacen preparar` con «Falta el extra postgres» |
| V3 | La mediana del triaje del perfil de Lucía en 5 min (la de `config/`) | Falla el 07 en las horas de L3 | 1 falla (`AssertionError`); 2,4 s |
| V4 | El subconjunto de olvidos al revés (hostil ⊆ realista) | Falla el 07 | 1 falla (`AssertionError`); 14 s |
| V5 | El reloj de admisión sumado en vez de restado en lo esperado del tiempo hasta el médico (−2 en vez de −8 min) | Falla el 07 en la comprobación del hostil | 1 falla (`AssertionError`); 14 s |

No cambia ningún fichero del paquete: los tests del núcleo y de la app no pueden verse afectados, y los otros seis notebooks siguen pasando (83 s los siete, con el 07 sin mutar).

**Revisión**

`/code-review medium main...feat/h7-notebook`, siete hallazgos:

- **Corregidos** (un commit): las referencias a secciones del propio notebook (la de Kafka y Postgres es la 7, no la 6, y las que corren en memoria son de la 2 a la 6); el `assert` del tiempo hasta el médico comparaba con −8 escrito a mano, y ahora con lo esperado de los relojes del perfil (HIS menos admisión), también para el realista; la numeración de la libreta de L por la posición (`L1`…, registro 1…) y no por el sufijo del identificador; la gráfica del censo, sin el ternario; las celdas de la sección 7 se pueden volver a ejecutar (la republicación acepta más de dos publicaciones, y la carpeta temporal se borra en la última celda, no al final de la comparación).
- **Explicados:**
  - La sección 7 no se ejecuta en el CI ni la ejecuté yo: no hay Docker en la nube. Es lo que pide el issue (Pedro la ejecuta en local); las cifras que da el texto («55.118», «263», «110.236») llevan «con los valores por defecto» y los `assert` comprueban estructura, no esas cifras. El `assert` de que la conciliación de bronce es la de la memoria depende de que `record` sea determinista, y se comprobó sin servicios (ver «Medidas»).
  - `RAIZ = Path("..")` y `EDSIM = Path(sys.executable).with_name("edsim")` son la convención del 06 (el notebook se ejecuta desde `notebooks/` y con el kernel de `.venv`); `record_run` era el único sitio que dependía del directorio de trabajo, y se corrigió.

**Pendiente**

- **El comentario de `config/registro_clinico.toml`** (líneas «Con estos relojes, la clase “con_despistes” …») repite la frase que esta tarea corrige en la especificación: el reloj domina en el hostil, no en el realista. `config/` pide confirmación de Pedro al editarse; va a la 7.7 (cierre) o a un `docs(config)` aparte. [Hecho en la 7.7.]
- **La sección 7 del notebook, sin ejecutar por mí:** Pedro la ejecuta con los comandos del PR; si algún valor no sale como arriba, se corrige en una ronda de ajustes. [Hecho: Pedro la ejecutó en local con Docker y pasa entera (nota del #121, 15 de noviembre).]

### Tarea 7.7: Cierre del hito 7

**Qué se hizo**

Issue #121, rama `docs/h7-cierre`, Claude Code (Opus, en local), con `/cerrar-hito` (su primer uso). Sin la etiqueta `critica`, pero con `/code-review high` por petición de Pedro; `@codex review` lo pide Pedro en el PR. Un commit por bloque, más los de la revisión:

- **Los ADR 0084 a 0099** (`355b66d`), uno por decisión, con las alternativas descartadas y cuándo tendrían sentido (petición de Pedro), «Qué cambió al implementarla» con la tarea y el commit, y el índice al día. Una nota de actualización en la ADR 0006, que nombraba la «capa de observación» (`4cb4804`).
- **Esta especificación:**
  - el estado;
  - la versión incorrecta 3 de la 7.0, comprobada el 14 de noviembre;
  - las notas entre corchetes de la 7.2, la 7.3 y la 7.6;
  - nueve filas de «Para versiones posteriores» con los pendientes del anexo (`8a8d4c5`);
  - el «Balance del hito» (`e032569`, `f991413`).
- **El diseño** (`e0cc333`, `a1daea7`), con el visto bueno de Pedro al plan:
  - «capa de observación» pasa a «simulador del registro clínico»;
  - los tres tiempos del sobre, lo registrado en el catálogo, bronce en las capas, Postgres sin perfil y el árbol del repositorio;
  - la hoja de ruta con el hito 7 cerrado y lo aplazado;
  - las decisiones 84 a 99.
- **El diario** `docs/diario/hito-7.md` (`3231f8c`), con «Pedro sabe explicar» y «Reflexiones de Pedro» vacía.
- **La app** (`f04a395`): `incrementos.md` gana la sección del hito 7, sin incremento, con lo que va a la fase 2 (#122).
- **El proceso** (`1c439bb`):
  - ocho lecciones;
  - la §14 de `portabilidad.md` con los pilotos del hito;
  - `flujo.md`: `/sincronizar` tras cualquier fusión.
- **Fuera de la documentación:** el comentario de `config/registro_clinico.toml` (`3166f4e`, `00cbf97`) y `.vscode/` en `.gitignore` (`2391479`).
- **La portada:** `AGENTS.md` y `README.md` (`67ea47f`), y la tabla de tamaños de `docs/README.md`.

**Decisiones del diff**

- **La fase 2 de la app, como sección del hito 7 en `incrementos.md`:** no existía sección de fase 2. Lleva una nota: la comparación tendrá que exponerse en `__all__` de `edsim.runs`, porque la app solo importa de ahí.
- **Los pendientes del anexo, en «Para versiones posteriores», sin abrir issues:** la búsqueda en GitHub no encontró ninguno.
- **El anexo no se reescribe:** lo que el hito corrigió va entre corchetes, con la tarea que lo corrigió.
- **«Un registro» es cada fila** (ajuste de Pedro al plan): lo registrado con un perfil y una semilla es la ejecución derivada. Se aplica en el diseño, también donde el plan decía «de cada registro».
- **El cuelgue de WSL fue en la 7.5**, con V16, como dice su anexo (ajuste de Pedro al plan: la nota del chat decía la 7.1).
- **`portabilidad.md` §3 no cambia:** ya tenía el `.wslconfig` con su porqué.
- **El diario fecha cada entrada con la fusión de su PR** en hora `+01:00`: la 7.4 queda en el 15 de noviembre.

**Valores a mano**

- **Los PR del balance:** los commits, la apertura y la fusión, por REST (`pulls/N`), y los minutos con `python3`. El hito, 37 h; la mediana de las N3 en la nube, 15:03.
- **El comentario del TOML:** 36.538 / (18.238 + 36.538) = 66,70 % y 52.137 / (86 + 52.137) = 99,84 %, de los hechos escritos. Sobre todos los registros escritos serían el 66,3 % y el 95,4 % (hallazgo de la revisión).
- **Un descuadre resuelto:** el cuerpo del #136 dice que se abrió a las 00:35, y la API, a las 09:58 UTC. El balance usa la API.

**Medidas**

- **Sin N3**, con el permiso de Pedro (`tarea.md` §4): la rama es documentación, un comentario de `config/` y `.gitignore`. El CI corre entero, porque `config/` cuenta como código.
- **Antes del push:**
  - `ruff check` y `ruff format --check`;
  - `edsim registro validar`, que sigue en verde (en el `diff` del TOML solo cambian líneas de comentario);
  - los 222 tests de `test_registro_perfiles.py`, `test_record_run.py` y `test_cli_registro.py`;
  - un script de enlaces, sin problemas en los enlaces relativos de los markdown cambiados;
  - un comando que comprueba que cada ADR del 0084 al 0099 tiene fichero, está en el índice y está en el registro del diseño: 0 fallos.

  La salida completa de cada uno, en el PR.
- **La huella del TOML** cambia con el comentario (de `9082cf8f5e54` a `20885c3352a2`); ningún test ni documento la fija.
- **La N2 del hook Stop falló una vez:** `test_la_comprobacion_con_la_ventana_anual_usa_sus_fechas` pasó de 60 s con xdist mientras corría `/code-review high` en segundo plano. Solo y en serie, 22,6 s. Es el pendiente de la 7.4, y su fila de «Para versiones posteriores» lo anota. Se repitió con la máquina libre (resultado en el PR).

**Versiones incorrectas**

A mano en el árbol de trabajo, deshechas con `git checkout`:

| # | Versión incorrecta | Predicción | Observado |
| --- | --- | --- | --- |
| V1 | Una línea del comentario del TOML sin el `#` | `registro validar` falla con un error de TOML. Fallan `test_el_fichero_real_tiene_los_valores_de_la_especificacion` (los tres perfiles) y `test_el_limpio_real_no_tiene_nada_distinto_de_cero` | `registro validar` sale con código 2 («Expected '=' after a key», línea 35). Fallan 3 y pasan 152: la predicción contaba un perfil de más, porque el test del fichero real solo lleva `realista` y `hostil` |
| V2 | Un ancla del balance que no existe | El script de enlaces la marca, con fichero y línea | La marca: `hito-7.md:918`, código 1 |
| V3 | El 0091 fuera del índice | El comando de los ADR la marca | «0091: no está en el índice», código 1 |

**Revisión**

`/code-review high main...docs/h7-cierre`, diez hallazgos, todos de documentación. Comprobó con su propio script los enlaces y, por REST, las cifras de los PR del balance.

- **Corregidos:**
  - `docs/README.md` seguía con el hito 7 en curso y los tamaños viejos;
  - «tras el #131» era el #132 (`f991413`);
  - el 66,7 % y el 99,8 % son de los hechos escritos, no de todo lo escrito (`00cbf97`, también en la ADR 0087);
  - V36 descartó la propuesta del revisor de la 7.4, no la aplicó (`f991413`, también en la ADR 0098 y en `portabilidad.md`);
  - la frase de `con_despistes` la escribió la 7.2 (`f991413`);
  - en el diseño, lo opcional de `compare` iba con otro destino que en la especificación (`a1daea7`);
  - los dos pendientes de la 7.6 seguían abiertos (`f991413`);
  - el 4.071 no tenía fuente: es del PR #129 (`f991413`);
  - la ADR 0006 seguía con «capa de observación» (`4cb4804`).
- **Explicado:** faltaba esta entrada, que es el último paso antes del push.

**Pendiente**

- **Pedro, tras la fusión:** la etiqueta `v0.7-hito7` sobre la fusión de este PR y, después, `/cerrar-hito 121`, que con el issue cerrado va directa a la Release. Los pasos, en el PR.
- **Las propuestas de velocidad del balance**, por decidir.
- **La comprobación del salto del #81**, en el primer PR que solo toque `.md`.
