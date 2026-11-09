# 0060. Replay de una ejecución guardada con el mismo pacer, censo y productor

- **Estado:** Aceptada
- **Fecha:** 2026-11-06

## Contexto

El hito 7 necesitará un stream idéntico cada vez para probar sus consumidores, y las demostraciones necesitan cargar Kafka rápido con una ejecución conocida ([especificación, pieza 6](../specs/hito-6.md#pieza-6--el-modo-directo-calentamiento-censo-inicial-control-y-replay)).

## Decisión

`edsim directo reemitir RUN_ID` lee una ejecución de `resultados/ejecuciones/` y la reemite con el mismo pacer, el mismo censo y el mismo productor. El motor no corre: los instantes salen del `sim_time` de cada evento. Conserva el `run_id` y los `event_id`.

## Alternativas consideradas

- Dejar el replay para el hito 7: con las piezas hechas costaba poco.

## Consecuencias

- Para un consumidor idempotente, reemitir la misma ejecución no añade nada: son los mismos hechos. Solo el `inicio` dice `modo: replay`.

## Qué cambió al implementarla

- 6.3: `LogSource` lee el log de forma perezosa, un evento por paso, y avisa si retrocede en el tiempo.
- 6.5: `prepare_replay` toma el horizonte y la semilla de `run.json`, W de `--calentamiento` o del guardado, y la fecha de inicio del primer evento (`event_time` − `sim_time`, redondeada al minuto). Reemitir 47.402 eventos a velocidad máxima tardó de 5,8 a 6,7 s, y la integración comprueba que publica los mismos bytes que el `eventos.jsonl`.
