# 0066. `run_id` del directo con la semilla y la hora de arranque; el replay conserva el suyo

- **Estado:** Aceptada
- **Fecha:** 2026-11-06

## Contexto

Los consumidores descartan repetidos por `event_id`, que es el `run_id` más un número de orden. Dos directos con la misma semilla publicarían los mismos `event_id`, y un consumidor idempotente confundiría uno con otro ([especificación, «Identidad de una ejecución»](../specs/hito-6.md#identidad-de-una-ejecución-h6-19)).

## Decisión

- El `run_id` por defecto de un directo es `r`, la semilla, `_` y la hora de arranque en `+01:00` (`r2026_20261106T172300`), o el que se pase con `--run-id`.
- El replay conserva el `run_id` y los `event_id` de la ejecución guardada: publica los mismos hechos.

## Alternativas consideradas

- El `run_id` del batch (`r` y la semilla): dos directos con la misma semilla compartirían `event_id`.
- Un `run_id` nuevo en el replay: los mismos hechos parecerían otros.

## Consecuencias

- El test «directo = batch» pasa el mismo `run_id` a los dos.
- El batch de un directo se reproduce con `edsim motor simular` y el mismo `--run-id`.

## Qué cambió al implementarla

- 6.5: `live_run_id(semilla, pared)` toma la hora en `+01:00`, no en UTC, y valida el resultado con `validate_run_id`.
- 6.6: los topics mezclan todos los directos, y el consumidor filtra los eventos por el `run_id` de su **valor**, no por la clave (que es el `episode_id`; V6 de la 6.6). El notebook 06 usa un `run_id` propio, `nb06_<fecha y hora>`.
