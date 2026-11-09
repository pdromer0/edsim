# 0063. Job `tests-kafka` en el CI con el mismo `compose.yaml`

- **Estado:** Aceptada
- **Fecha:** 2026-11-06

## Contexto

La integración contra Kafka no puede depender de que alguien la ejecute en local, y el Kafka del CI tiene que ser el del portátil ([especificación, pieza 7](../specs/hito-6.md#pieza-7--cómo-se-prueba-un-sistema-en-tiempo-real)).

## Decisión

Un cuarto job, `tests-kafka`, en un ejecutor Linux de GitHub Actions: `uv sync --locked --extra kafka` y `scripts/tests-integracion.sh`, que levanta el mismo `compose.yaml` con `docker compose up --wait`, ejecuta `tests_integracion/` y lo baja. `timeout-minutes: 15`. Obligatorio en la protección de `main` desde la tarea 6.4.

## Alternativas consideradas

- Los contenedores de servicio de Actions: también exigen Linux, y el Kafka del CI se configuraría aparte del de `compose.yaml`.

## Consecuencias

- Lo que llega a `main` pasa la integración en una máquina limpia.

## Qué cambió al implementarla

- 6.1: el job entró sin ser obligatorio; pasó a serlo al fusionar la 6.4.
- Antes de cada push de las tareas con Kafka, `scripts/tests-integracion.sh` en local: 4 tests en 29 s en la 6.1, 11 en 29 a 34 s en la 6.4, 20 en 0:53 a 1:14 en la 6.5; 23 en 1:21 en la 6.6, con los del consumidor.
