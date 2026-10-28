# 0011. GitHub Flow con pull requests, CI obligatorio y fusión reservada a Pedro

- **Estado:** Aceptada
- **Fecha:** 2026-10-27

## Contexto

El código lo escribe Claude Code ([0008](0008-claude-code-escribe-el-codigo.md)), y `main` debe estar siempre estable ([diseño](../diseno.md#flujo-de-desarrollo-github-flow)).

## Decisión

Cada tarea vive en una rama corta que entra en `main` por pull request, con el CI en verde y tras la revisión de Pedro. Claude Code nunca fusiona: Pedro aprueba con "Squash and merge".

Motivo: es una red de seguridad para el código escrito por IA y mantiene el control humano de `main`.

## Alternativas consideradas

No se documentaron alternativas.

## Consecuencias

- Los permisos de Claude Code dejan pasar lectura y tests, piden permiso para `git push` y `gh pr create`, y deniegan `gh pr merge`.
- Un ruleset en GitHub protege `main` ([0014](0014-repositorio-publico-con-ruleset.md)).
- En los hitos 0 y 1, Pedro ejecuta a mano los pasos de git; desde el hito 2 los ejecuta Claude Code.
