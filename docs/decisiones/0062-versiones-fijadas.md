# 0062. Versiones fijadas con etiqueta exacta: Kafka, Redpanda Console y confluent-kafka

- **Estado:** Aceptada
- **Fecha:** 2026-11-06

## Contexto

El Kafka del portátil, el de Claude Code y el del CI tienen que ser el mismo, y una etiqueta como `latest` cambia sin avisar ([especificación, «Compose»](../specs/hito-6.md#compose)).

## Decisión

Versiones fijadas con etiqueta exacta y comprobadas en la tarea 6.1: `apache/kafka:4.4.0`, `docker.redpanda.com/redpandadata/console:v3.13.1` y el extra `confluent-kafka>=2.16.1,<2.17` (2.16.1, con librdkafka 2.16.0).

## Alternativas consideradas

- Etiquetas flotantes (`latest`, `4`): el CI y el portátil podrían ejecutar versiones distintas el mismo día.

## Consecuencias

- Subir una versión es un cambio explícito, con su comprobación.

## Qué cambió al implementarla

- 6.1: las versiones se comprobaron el 8 de noviembre de 2026; `docker compose up --wait` tarda unos 10 s con las imágenes descargadas.
- **6.6, Redpanda Console se queda en la v3.13.1** (decidido con Pedro). Según el [CHANGELOG de la consola](https://github.com/redpanda-data/console/blob/master/CHANGELOG.md), la v3.14.0 (4 y 5 de noviembre de 2026, la única posterior) solo cambia Redpanda Connect y Kafka Connect, prepara el modo oscuro tras un flag y resuelve 44 avisos de seguridad de dependencias del frontend; nada de topics, mensajes ni grupos de consumidores, que es lo que EDsim mira. La v3.13.1 es el mismo commit que la v3.13.0.
- **La consola no escucha solo en la máquina.** `compose.yaml` publica el puerto como `"8080:8080"`, y `docker compose ps` lo muestra como `0.0.0.0:8080->8080/tcp`: en todas las interfaces de WSL. En el equipo de Pedro, WSL2 usa red NAT, así que desde la red local no se llega sin reenvío de puertos. Pendiente: publicar el puerto como `"127.0.0.1:8080:8080"` si algún día la consola tiene que quedarse solo en la máquina.
