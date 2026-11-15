# 0097. La app no cambia en el hito 7; el registro clínico va a su fase 2

- **Estado:** Aceptada
- **Fecha:** 2026-11-13

## Contexto

EDsim Lab crece con cada hito (decisión 31). El hito 7 trae lo registrado, bronce y la comparación, pero las piezas que leen de Kafka y de Postgres atan la app a Docker ([especificación, «Objetivo y alcance»](../specs/hito-7.md#objetivo-y-alcance)).

## Decisión

- La app no cambia en el hito 7.
- La página del registro clínico, la lectura de bronce, el directo en vivo y los fantasmas en el Replay van a la fase 2 de la app (#122).
- La eligió Pedro; la recomendación era la página del registro clínico desde ficheros.

## Alternativas consideradas

- **La página del registro clínico desde ficheros, en este hito** (la recomendación): no necesita Docker, y la comparación ya está en el paquete. Tendría sentido como incremento pequeño antes de la fase 2, si Pedro lo pide.
- **Bronce y el directo en vivo en la app:** atan la app a Docker; encajan cuando haya una API entre medias.

## Consecuencias

- El hito no tiene tarea de app ni etiqueta `app-v…`.
- La comparación queda lista en el paquete para la fase 2.

## Qué cambió al implementarla

Nada. Lo que va a la fase 2 está en el #122 y en [incrementos.md](../../app/docs/specs/incrementos.md#hito-7--persistencia).
