# 0056. El valor es la línea del JSONL y la hora de llegada es la marca `LogAppendTime`

- **Estado:** Aceptada
- **Fecha:** 2026-11-06

## Contexto

El sobre del log tiene tres horas: `event_time` (cuándo ocurrió en la simulación), `recorded_time` (cuándo lo anotó el hospital) e `ingest_time` (cuándo llegó al sistema de datos). En el directo, «llegar» es llegar al broker, y solo el broker sabe cuándo ocurre ([especificación, pieza 6](../specs/hito-6.md#pieza-6--el-modo-directo-calentamiento-censo-inicial-control-y-replay)).

## Decisión

- El valor de cada mensaje es la línea del JSONL, sin el salto final: exactamente `to_json(event)`, con `ingest_time` nulo.
- La hora de llegada es la marca del mensaje, de tipo `LogAppendTime` (configuración de los topics); el productor nunca pone una marca.
- Cabeceras `event_type` y `schema_version`, para filtrar y elegir esquema sin leer el valor.

## Alternativas consideradas

- Rellenar `ingest_time` con la hora del productor: sería una hora inventada (la de envío, no la de llegada) y el valor dejaría de ser la línea del batch.
- Usar `event_time` como marca (`CreateTime`): Kafka 4 rechaza los mensajes con más de 1 h en el futuro (`message.timestamp.after.max.ms`), y la retención borraría enseguida los de fecha pasada.

## Consecuencias

- «Directo = batch» compara bytes: lo publicado es la línea del log.
- El consumidor del hito 7 copiará la marca a `ingest_time` en la capa bronce.

## Qué cambió al implementarla

- 6.4, V10 forzada: un directo anclado en topics `CreateTime` con la marca = `event_time` se paró con `SinkError` a los 62,9 s (`INVALID_TIMESTAMP`), con 406 eventos entregados.
- 6.4: de `produce` a la marca del broker, a ×3.600, mediana de 5,9 y 6,0 ms (casi todo es `linger.ms` = 5 ms).
- 6.6: el consumidor mide la latencia del broker a él contra esa marca: en dos ejecuciones del notebook 06, mediana de 1,6 y 1,7 ms, p95 de 4,9 y 3,6 ms y máximo de 10,8 y 35,1 ms. Una marca que no es `LogAppendTime` no da latencia.
