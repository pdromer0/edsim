# 0053. Control en vivo por el topic `ed.control` y `edsim directo control`

- **Estado:** Aceptada
- **Fecha:** 2026-11-06

## Contexto

Un directo dura horas: hay que poder cambiar la velocidad, pausar, reanudar y parar desde otra terminal. La API del plano de control (FastAPI) llegará después de la v0 ([especificación, pieza 6](../specs/hito-6.md#pieza-6--el-modo-directo-calentamiento-censo-inicial-control-y-replay)).

## Decisión

- Las órdenes viajan por el topic `ed.control` (clave `run_id`); las publica `edsim directo control` y las lee el simulador.
- La velocidad inicial se da en la CLI (`--velocidad`).
- Sin evento `control_command` en el catálogo: las órdenes solo cambian el ritmo, así que el log sigue siendo igual al batch.

## Alternativas consideradas

- Señales del sistema o la entrada estándar: no valen desde otra máquina ni desde la futura API.
- Un evento `control_command` en el log: rompería «directo = batch» sin necesidad.

## Consecuencias

- La futura API publicará en el mismo topic.
- Una orden de otro `run_id` se ignora sin aviso; una inválida avisa y el directo sigue.

## Qué cambió al implementarla

- 6.4: `KafkaControl` no se une a un grupo: lee el offset alto de `ed.control` al crearse y se asigna la partición ahí (`assign`). Con `subscribe` y `latest`, una orden enviada mientras se forma el grupo podía perderse (la lección de la 6.1). Las órdenes se crean antes del calentamiento.
- 6.4: `parse_control` y el esquema `ed-control-v1` deciden igual una colección de 32 órdenes, salvo la de otro `run_id`. Un entero enorme en `velocidad` pasa por `edsim.finite.to_float` (revisión del PR #59).
- 6.5: la primera consulta al broker espera `CONNECT_TIMEOUT` = 10 s; sin respuesta, `BrokerUnavailableError`, con el mismo mensaje en los cuatro comandos. `publish_order` publica la orden y espera su confirmación (`OrderNotDeliveredError` si el broker la rechaza).
- 6.6: el consumidor de órdenes lleva `client.id` `edsim-control-<run_id>`. Sin broker reintentaba cada 50 ms: la biblioteca de Python exige un `group.id`; con él, librdkafka busca el coordinador del grupo, y esa búsqueda pide conexiones dispersas cada `reconnect.backoff.ms` / 2 = 50 ms, sin retroceso exponencial (`rdkafka_cgrp.c` y `rdkafka_conf.c` de librdkafka 2.16.0). Se deja el valor por defecto: sus líneas ya no van a la terminal ([ADR 0055](0055-productor-idempotente-y-al-menos-una-vez.md)).
