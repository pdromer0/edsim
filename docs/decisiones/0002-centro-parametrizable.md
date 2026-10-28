# 0002. Tipo y tamaño de centro parametrizables

- **Estado:** Aceptada
- **Fecha:** 2026-10-27

## Contexto

El centro no está programado en el código: se describe en configuración (áreas, recursos por turno, reglas de enrutado). El principio "escenarios como configuración" establece que el motor no contiene conocimiento clínico ([diseño](../diseno.md#principios-de-diseño)).

## Decisión

El tipo y el tamaño del centro son parametrizables. Se empieza por un hospital general de tamaño medio.

Motivo: empezar simple sin cerrar la puerta.

## Alternativas consideradas

No se documentaron alternativas.

## Consecuencias

- Centros, catálogos, escenarios y experimentos son ficheros YAML, validados con Pydantic, con semilla y `run_id` trazable.
- El volumen del centro base se fija en [0013](0013-centro-base-300-urgencias.md).
- La v3 añade perfiles de centro intercambiables.
