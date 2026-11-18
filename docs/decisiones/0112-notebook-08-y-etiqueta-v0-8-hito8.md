# 0112. Notebook `08_analitica`, la app sin cambios y nueve tareas en dos pistas

- **Estado:** Aceptada
- **Fecha:** 2026-11-16

## Contexto

Cada hito deja un notebook que cuenta sus piezas paso a paso y que el CI ejecuta en modo rápido. El hito 8 tiene dos zonas que apenas se tocan: `analitica/` y `live/`, `store/`, `compose.yaml` y `grafana/` ([tareas, ramas y orden de ejecución](../specs/hito-8.md#tareas-ramas-y-orden-de-ejecución)).

## Decisión

- El notebook `08_analitica.ipynb`, con modo rápido sin Docker.
- La app no cambia.
- Las ADR 0100 a 0112 se escriben en el cierre.
- La etiqueta `v0.8-hito8`.
- Nueve tareas en dos pistas, con dos ramas abiertas como mucho.

## Alternativas consideradas

- **Una página de la app para el laboratorio:** ataría la app a Postgres; va a la fase 2 (#122).
- **Una sola pista:** el hito 7 ya mostró que dos pistas sin ficheros compartidos acortan el calendario.

## Consecuencias

- El material paso a paso, ejecutado por el CI.
- Dos sesiones locales a la vez comparten compose (`name: edsim`): Pedro lo levanta a mano antes de abrirlas.

## Qué cambió al implementarla

- **8.6 y 8.7** (#154 y #155): en el tramo 4 corrieron a la vez en local, en dos carpetas: `~/proyectos/edsim` y un clon, `~/proyectos/edsim-b`. El `tests-integracion.sh` de una sesión podía levantar y bajar los contenedores de la otra, porque comparten compose.
- **8.8** (#157): la D4 de las notas del chat la pasó de la nube a local, porque añade código al paquete (`bronze_messages` y `write_bronze`, bronce sin Kafka) y el modo normal solo se comprueba con Docker. La tabla de tareas guarda el modelo del plan (Sonnet, alto); la 8.6, la 8.7 y la 8.8 las hizo Opus.
- **8.8, la revisión** (`9d26816`): `write_bronze` escribe toda la publicación en una transacción.
- **8.8, el ajuste tras la revisión** (`6a663a2`): cada pasada del notebook borra las anteriores al empezar la carga.
