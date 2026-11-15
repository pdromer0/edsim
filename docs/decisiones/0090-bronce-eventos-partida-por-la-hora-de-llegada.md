# 0090. `bronce.eventos`, partida por la hora de llegada, con clave (`event_id`, `ingest_time`)

- **Estado:** Aceptada
- **Fecha:** 2026-11-13

## Contexto

Bronce guarda los datos tal como llegan. Había que decidir la forma de la tabla, por qué hora se parte y qué clave impide guardar dos veces la misma lectura. TimescaleDB exige que toda clave única de una hypertable incluya su columna de partición ([especificación, «Tablas»](../specs/hito-7.md#tablas-migración-001_broncesql)).

## Decisión

- `bronce.eventos` lleva el sobre en columnas, el `payload` en JSON (`jsonb`), las coordenadas de Kafka (topic, partición y offset) y el mensaje original (`valor`).
- Es una **hypertable por `ingest_time`**, con un índice por `event_time`.
- La **clave única es (`event_id`, `ingest_time`)**.
- Los mensajes de `ed.runs` van a `bronce.ejecuciones`, y los ilegibles, a `bronce.rechazados`.

## Alternativas consideradas

- **Partir por `event_time`:** el reloj desajustado del registro clínico decidiría dónde se guarda cada registro. Tendría sentido con horas de sistema fiables, por ejemplo eventos de sensores.
- **Clave por `event_id` solo:** Timescale no la admite en una hypertable partida por otra columna. Tendría sentido en una tabla sin partir.
- **Clave por las coordenadas de Kafka:** Timescale tampoco la admite (V14), y un broker sin volumen reutiliza los offsets tras reiniciarse.

## Consecuencias

- La hora de llegada es fiable y siempre existe: la pone el broker.
- Una relectura del consumidor (el mismo `event_id` con el mismo `ingest_time`) se ignora; una republicación (el mismo `event_id`, llegado en otro momento) se guarda otra vez. Bronce es «tal como llegó».

## Qué cambió al implementarla

- **7.5, la clave confirmada con la versión fijada:** con `UNIQUE` sin `ingest_time`, `create_hypertable` falla («cannot create a unique index without the column "ingest_time"»). Es V14, comprobada a mano.
- **7.5, `bronze.py` no valida con el catálogo**, porque lo registrado tiene campos a `null` y `record_corrected`. Exige solo las claves que llenan columnas, con sus tipos. Manda a `rechazados` todo lo que se sabe que rompe el `INSERT`: un entero fuera de `integer` (V17), NaN e infinito, NUL, sustitutos sueltos, UTF-8 roto y horas sin zona. Un mensaje así bloquearía el consumidor, que releería el mismo lote para siempre.
- **7.5, ajuste de la revisión del PR** (Codex, `690f6ac`): un JSON muy anidado lanzaba `RecursionError`, que no es `ValueError`, y bloqueaba la partición. Ahora va a `rechazados`, con el motivo «JSON demasiado anidado».
- **7.6, en el notebook 07:** la republicación da 110.236 filas con 55.118 `event_id`, el doble de filas y los mismos identificadores.
