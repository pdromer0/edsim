# 0015. Idiomas del proyecto

- **Estado:** Aceptada
- **Fecha:** 2026-10-27

## Contexto

El proyecto mezcla código, configuración y documentación pensada para el aprendizaje de Pedro ([diseño](../diseno.md#metodología-de-trabajo-con-claude-code-y-cursor)).

## Decisión

- Código, nombres y docstrings en inglés.
- Documentación, especificaciones y mensajes de commit en español.
- Claves de configuración en español.

Motivo: el inglés es el estándar del código, y la documentación sirve al aprendizaje en el idioma de Pedro.

## Alternativas consideradas

No se documentaron alternativas.

## Consecuencias

- Conviven nombres en inglés, como los eventos (`patient_arrived`), con claves de configuración en español, como `peso_base` o `replicas`.
- La convención está recogida en [CLAUDE.md](../../CLAUDE.md).
