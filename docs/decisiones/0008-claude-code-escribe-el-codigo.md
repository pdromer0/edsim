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

## Nota de actualización (2026-11-03)

Desde la tarea 3.6 cambia la revisión, no quién escribe el código. Con el plan aprobado, Claude Code implementa la tarea completa, con un commit por paso lógico y sin esperar revisión entre pasos; solo para si algo contradice el plan o hace falta una decisión nueva. Pedro revisa el PR completo, cuya descripción explica cada decisión y lo que cambió respecto al plan. Hasta la tarea 3.5 se revisaba cada diff en conjunto ([especificación del hito 3](../specs/hito-3.md#tareas-ramas-y-orden-de-ejecución) y [diseño](../diseno.md#metodología-de-trabajo-con-claude-code-y-cursor)). La decisión no cambia.
