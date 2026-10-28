# 0008. Claude Code escribe el código tras una sesión conceptual

- **Estado:** Aceptada
- **Fecha:** 2026-10-27

## Contexto

El proyecto tiene un objetivo doble: construir el sistema y aprender sus fundamentos. Pedro dirige, pregunta y revisa ([diseño](../diseno.md#metodología-de-trabajo-con-claude-code-y-cursor)).

## Decisión

Claude Code escribe el código después de una sesión conceptual en la que explica qué se implementa y por qué. Después, el diff se revisa en conjunto, explicando cada decisión.

Motivo: es el modo de trabajo elegido.

## Alternativas consideradas

- Estilo de respuesta `Learning`, que deja trozos de código para que los escriba Pedro: no encaja con el modo de trabajo ([spec del hito 0](../specs/hito-0.md#claudemd-y-configuración-de-claude-code)).

## Consecuencias

- Cada hito sigue el ciclo: sesión conceptual → especificación → plan en modo plan → implementación en pasos pequeños → revisión conjunta → cierre.
- Claude Code se configura con el estilo `Explanatory` y con `CLAUDE.md` como memoria del proyecto.
- La IA propia de Cursor no se usa al principio, para no mezclar flujos.
- La fusión en `main` queda reservada a Pedro ([0011](0011-github-flow-con-ci-obligatorio.md)).
