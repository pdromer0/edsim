# 0055. Productor idempotente y «al menos una vez» con consumidores idempotentes

- **Estado:** Aceptada
- **Fecha:** 2026-11-06

## Contexto

Entre el simulador y el broker hay una red, y cualquiera de los dos puede fallar a mitad de un envío. El log es la fuente de verdad: un hueco silencioso haría que un consumidor reconstruyera un censo falso ([especificación, pieza 3](../specs/hito-6.md#pieza-3--garantías-de-entrega)).

## Decisión

- Productor idempotente (`enable.idempotence=true`), `acks=all`, `partitioner=murmur2_random` (el reparto de Java y Kafka Streams) y `client.id` `edsim-<run_id>`; el resto, los valores de librdkafka.
- De extremo a extremo, «al menos una vez»: los consumidores descartan los repetidos por `event_id`.
- Si un mensaje no se entrega, el directo se para; al terminar, `flush`.
- Sin transacciones.

## Alternativas consideradas

- «Como mucho una vez» (`acks=0`): perdería mensajes sin que nadie se enterara.
- Transacciones (exactamente una vez): un `transactional.id`, consumidores `read_committed` y más fallos posibles, para escribir en varios topics a la vez de forma atómica, que EDsim no necesita.
- Seguir publicando tras un fallo de entrega: el log tendría un hueco.

## Consecuencias

- Un corte de Kafka de menos de 5 minutos (`message.timeout.ms`) no pierde nada: los mensajes esperan en la cola del productor y salen al volver.
- El `event_id` determinista ([ADR 0027](0027-log-jsonl-con-sobre-comun.md)) es la clave natural para descartar repetidos.

## Qué cambió al implementarla

- 6.4, decidido con Pedro: tras un fallo, cada `write` lanza `SinkError`, y el `fin` de error **dice solo lo confirmado**: `publicados` = eventos confirmados y `ultimo_event_id` = el confirmado con el número más alto, aunque los avisos lleguen desordenados.
- 6.4, revisión del PR #59 (P1 de Codex): el `fin` espera a las confirmaciones. `end` hace `flush(30)` primero y, si algo falló o quedó pendiente, publica un `fin` con motivo `error` y lanza `SinkError`.
- 6.5: los pendientes de la línea de estado se cuentan tras servir los avisos (`pending_messages`). En vivo, un corte de un minuto subió los pendientes a 205, que volvieron a 0 menos de 7 s después de que Kafka escuchara, con 5.048 publicados y 0 `event_id` repetidos en los topics.
- 6.6: el consumidor idempotente está en el paquete (`LiveTracker`): un `event_id` repetido se cuenta y no cambia nada. El vigilante de la conexión (`BrokerWatch`) desvía las líneas de librdkafka: en un corte de 60 s, la terminal pasó de 1.582 líneas a 2 avisos y un resumen, sin tocar el camino de una entrega fallida.
