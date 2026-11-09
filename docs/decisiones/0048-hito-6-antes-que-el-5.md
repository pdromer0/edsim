# 0048. El hito 6 (tiempo real) va antes que el 5

- **Estado:** Aceptada
- **Fecha:** 2026-11-06

## Contexto

El plan del diseño era 5 (abandono, boarding y destinos), 6 (tiempo real) y 7 (persistencia). El hito 4 fue largo y estadístico, y ver EDsim en vivo era un cambio de terreno útil. El hito 6 no depende del 5: transporta lo que el motor produzca, con la versión de catálogo que sea ([especificación, «Objetivo y alcance»](../specs/hito-6.md#objetivo-y-alcance)).

## Decisión

El hito 6 va antes que el 5; después, el 5, y solo entonces el 7. Todo lo del hito 6 vale para cualquier versión del catálogo (hoy la 1, la 2 y la 3; el hito 5 traerá la 4).

## Alternativas consideradas

- El orden del diseño (5 antes que 6): retrasaba ver EDsim en vivo sin ganar nada, porque el directo no usa nada del hito 5.
- El 7 justo después del 6: se construirían la persistencia y dbt sobre un modelo sin abandono ni boarding, y habría que rehacerlos.

## Consecuencias

- El catálogo 4 entrará en el directo añadiendo su esquema generado, sus eventos terminales y un caso a «directo = batch»; nada del hito 6 cambia de forma.
- La etiqueta del cierre nombra el hito, no el orden: `v0.6-hito6` llega antes que `v0.5-hito5` ([ADR 0064](0064-etiqueta-v0-6-hito6.md)).

## Qué cambió al implementarla

Nada en la decisión. Las piezas que dependen del catálogo se escribieron por versión: `TERMINAL_EVENTS` junto a `CATALOGS` (6.2), un esquema por versión (6.4) y «directo = batch» parametrizado con las versiones 1, 2 y 3 (6.3). El consumidor de la 6.6 usa `TERMINAL_EVENTS` de la versión de cada evento.
