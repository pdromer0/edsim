# 0010. Apache Kafka 4 (KRaft) como broker, con Redpanda Console

- **Estado:** Aceptada
- **Fecha:** 2026-10-27

## Contexto

El modo directo publica los eventos en vivo para el streaming y la analítica en tiempo real ([diseño](../diseno.md#stack-tecnológico-y-despliegue)).

## Decisión

El broker es Apache Kafka 4 en modo KRaft, con un solo nodo. La interfaz es Redpanda Console.

Motivo: aprender el estándar de la industria con licencia abierta. Cambiar a Redpanda es trivial.

## Alternativas consideradas

- Redpanda como broker: queda como ejercicio de compatibilidad.

## Consecuencias

- Topics: `ed.patient.events` (con clave `episode_id`, para conservar el orden por episodio), `ed.resource.events`, `ed.system.events`, `ed.snapshots` y `ed.control`.
- Esquemas en JSON Schema en la v0; Avro con un registro de esquemas más adelante.
- Kafka y Redpanda Console van en el perfil `core` de Docker Compose y se introducen en el hito 6.
