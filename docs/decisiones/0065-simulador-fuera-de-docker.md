# 0065. El simulador corre fuera de Docker; Compose levanta solo Kafka y la consola

- **Estado:** Aceptada
- **Fecha:** 2026-11-06

## Contexto

El diseño prevé perfiles de Compose con el simulador y los consumidores dentro de contenedores, pero el ciclo de desarrollo y los tests de EDsim corren en WSL2 con `uv` ([especificación, pieza 5](../specs/hito-6.md#pieza-5--docker-compose-y-los-listeners-de-kafka)).

## Decisión

En este hito el simulador no va en un contenedor: corre en WSL2 con `uv` y entra en Kafka por el listener `EXTERNAL` (`localhost:9092`). Compose levanta solo Kafka y Redpanda Console, que entra por el listener `INTERNAL` (`kafka:19092`).

## Alternativas consideradas

- El simulador en un contenedor desde ya: cambiaría el ciclo de desarrollo y de tests sin ganar nada hasta que haya API.

## Consecuencias

- Kafka necesita dos listeners, uno para cada lado de Docker: un cliente vuelve a llamar a la dirección que le anuncia el broker, y `localhost` dentro de un contenedor es el propio contenedor.
- El contenedor del simulador llegará con la API, y usará el listener `INTERNAL`.

## Qué cambió al implementarla

- 6.1: `name: edsim` en Compose; quórum estático; la fixture de integración comprueba que cada dirección anunciada se alcanza (lección de la V1 de la 6.1).
- En el equipo de Pedro, el motor de Docker corre dentro de WSL, sin Docker Desktop.
