# 0091. El consumidor de bronce: guarda y después apunta, con inserción idempotente

- **Estado:** Aceptada
- **Fecha:** 2026-11-13

## Contexto

Hay que llevar cada registro de Kafka a Postgres sin perder ninguno y sin guardar ninguno dos veces, aunque el consumidor se caiga a mitad. Guardar y apuntar el offset no se pueden hacer a la vez ([especificación, pieza 4](../specs/hito-7.md#pieza-4--el-consumidor-al-menos-una-vez-e-inserción-idempotente)).

## Decisión

- Un consumidor con **`confluent-kafka`**.
- **Guarda un lote** (hasta 500 mensajes o 1 s) en una transacción con `ON CONFLICT DO NOTHING`, **y después confirma** los offsets, de forma síncrona.
- **`ingest_time` sale de la marca `LogAppendTime`**; otro tipo de marca es un error del topic.
- Grupo fijo `edsim-bronce`, tres topics (`ed.patient.events`, `ed.resource.events` y `ed.runs`) y los ilegibles a `bronce.rechazados`.
- Corre de continuo (hasta Ctrl+C) o hasta el fin de una ejecución (`--run`).

## Alternativas consideradas

- **Apuntar y después guardar** («como mucho una vez»): pierde mensajes si se cae entre medias (V13).
- **Quix Streams:** esconde el orden de guardar y apuntar, que aquí se quería ver a mano. Tiene sentido en el hito 8, con KPIs por ventana.
- **Los offsets en Postgres**, en la misma transacción que el lote («exactamente una vez»): más complejo, y aquí la clave única ya resuelve los repetidos. Tendría sentido si la clave no pudiera distinguir una relectura de un mensaje nuevo.

## Consecuencias

- «Al menos una vez» con inserción idempotente, el patrón estándar: nunca se pierde nada y una relectura no repite filas.
- El orden de guardar y apuntar se ve y se prueba con dobles: la caída entre los dos deja 7 filas y 3 repetidos ignorados, sin pérdidas.

## Qué cambió al implementarla

- **7.5, la red de seguridad:** si el `INSERT` del lote falla por un dato, el lote se repite fila a fila, con un `SAVEPOINT` por fila, y solo la que falla va a `rechazados` (V21). Un error que no es de datos se propaga sin confirmar.
- **7.5, se inyecta un almacén, no la conexión:** las transacciones, los savepoints y la red viven en `consumer.py` y se prueban en rápidos con `tests/fake_store.py`. La integración prueba lo que el falso solo imita: `ON CONFLICT`, su recuento y el error de Postgres.
- **7.5, `--run` cuenta en bronce, desde el último `inicio`:** así termina un consumidor relanzado, y no lo engaña una publicación anterior (V18). Por eso `KafkaSink.start` espera a que el broker confirme el `inicio` antes de mandar el censo (`99e51b9`).
- **7.5, ajuste de la revisión del PR** (Codex, `6345783`): `--run` daba por completa una publicación vieja, porque miraba el recuento antes del primer `consume`. Ahora la da por completa solo si el recuento cuadra y además ese `consume` volvió vacío: el consumidor está al día.
- **7.5:** la integración usa un grupo único por sesión (`edsim-bronce-test-<8 hex>`), para no mover los offsets del consumidor de Pedro.
- **7.6, lo que queda frágil:** en una republicación, la parada depende de que el grupo se forme dentro del primer `consume` de 1 s. Funciona por el `KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS: 0` de `compose.yaml`. Con el retraso por defecto (3 s), pararía con la primera lectura vacía sin leer la publicación nueva. Queda en «Para versiones posteriores», con el remedio posible: no darla por completa hasta tener asignación y estar al día con la marca alta de cada partición.
