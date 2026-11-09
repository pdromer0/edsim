# 0054. Cuatro topics, reparto por `episode_id` y topics creados por EDsim

- **Estado:** Aceptada
- **Fecha:** 2026-11-06

## Contexto

Los eventos tienen que llegar a los consumidores en orden por paciente, con una regla que valga para cualquier catálogo; además hay mensajes de la ejecución y órdenes ([especificación, «Topics»](../specs/hito-6.md#topics)).

## Decisión

- `ed.patient.events` (3 particiones, clave `episode_id`), `ed.resource.events` (1, clave `recurso`), `ed.runs` (1, clave `run_id`: el `inicio` y el `fin`) y `ed.control` (1, clave `run_id`).
- Reparto por `episode_id`: con episodio, a pacientes; sin él, a recursos. No se mira el tipo de evento.
- Los crea `edsim directo preparar`; el broker tiene la autocreación desactivada.

## Alternativas consideradas

- Una sola partición: el orden sería global y nunca se vería el fenómeno central de Kafka, orden por clave y no global.
- Reparto por tipo de evento: se rompería con un catálogo nuevo (V6 de la 6.4: con los catálogos 1 a 3 coincide y solo lo ve un catálogo de prueba).
- Topics creados por Compose o por autocreación: un nombre mal escrito crearía un topic nuevo en silencio.

## Consecuencias

- Los eventos de un paciente se leen en orden; entre pacientes y entre topics no hay orden, y el consumidor ordena por `sim_time` lo que necesite.
- `edsim.live.topics` guarda la tabla literal, y un test la compara con la especificación.

## Qué cambió al implementarla

- 6.4: `ensure_topics` comprueba todo antes de crear nada (`TopicMismatchError` si un topic tiene otras particiones u otra marca) y espera a que los topics nuevos se vean en los metadatos: justo después de crearlos, 7 de 60 no aparecían.
- 6.5: `lanzar` y `reemitir` comprueban sin crear (`MissingTopicsError`, «créalos con edsim directo preparar»), para que un `--kafka` mal escrito no deje topics en otro broker.
- 6.6: el consumidor midió el reparto de un día de `config/`: 1.585, 1.529 y 1.914 eventos en las tres particiones, 0 errores de orden dentro de un episodio y unas 650 a 710 inversiones entre particiones.
