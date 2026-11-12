# 0079. Ocho tareas en orden y la etiqueta `v0.5-hito5`

- **Estado:** Aceptada
- **Fecha:** 2026-11-10

## Contexto

El hito 5 toca el motor, los perfiles, los formatos, la app, la calibración y un notebook. El hito 4 enseñó que juntar el modelo y su calibración en un PR lo hace difícil de revisar. Además, el modelo nuevo no puede pasar a ser el de por defecto antes de que la app lo soporte (decisión 44) ([especificación, «Tareas»](../specs/hito-5.md#tareas-ramas-y-orden-de-ejecución)).

## Decisión

Ocho tareas en orden estricto, con una sola rama abierta a la vez:

1. motor con pacientes a mano (5.1);
2. perfiles (5.2);
3. el modelo en el motor (5.3);
4. núcleo de la app (5.4);
5. páginas (5.5);
6. calibración, que pone los bloques en `config/` (5.6);
7. notebook (5.7);
8. cierre (5.8).

Lleva `@codex review` en la 5.1, la 5.3 y la 5.6, y se cierra con la etiqueta `v0.5-hito5`.

## Alternativas consideradas

- **El modelo y la calibración en un PR:** la lección del hito 4 es que no se revisa bien.
- **La calibración antes que la app:** durante la 5.5, los tests de la app correrían contra un modelo que la app aún no sabe mostrar.

## Consecuencias

- Lo exacto y aislado va antes que lo que lo junta, como en el hito 4 (4.2 a 4.4 antes de la 4.5a).
- `config/` es el modelo del hito 4 hasta la 5.6.
- La etiqueta nombra el hito, no el orden: `v0.5-hito5` llega después de `v0.6-hito6` (decisión 64).

## Qué cambió al implementarla

- **La 5.5 la hizo Claude Code**, no Codex (decisión de Pedro del 12 de noviembre).
- **Los pilotos de proceso del hito** ([portabilidad.md](../proceso/portabilidad.md#14-estado-de-las-piezas-en-prueba), §14):
  - **subagente `mutante`** (5.2): funciona. El worktree parte del `HEAD` local y deja intacto el árbol principal. Un subagente creado a mitad de sesión no existe hasta la siguiente.
  - **el chat lee el PR y el CI** (5.4): funciona, con `add_repo` y `gh api` REST. Desde la 5.4 el chat también escribe en GitHub: notas en los issues, revisiones y métricas en los PR, issues del Backlog.
  - **Codex desde el issue:** sin hacer, porque la 5.5 pasó a Claude Code.
  - **sesión en la nube** (5.7): funciona sin GraphQL. `gh issue view` y `gh project` dan 403 en el proxy, así que el tablero lo mueve Pedro.
  - **`@claude` en el PR:** pospuesto a después de la 5.8.
  - **la skill `cerrar-hito`** (5.8): escrita con lo que hace esta tarea. La Release, después de la etiqueta de Pedro. La web de la documentación sale del hito: #112.
- **El ciclo de cada tarea** cambió durante el hito: una sola N3, después de la revisión propia ([ADR 0083](0083-una-sola-n3-tras-la-revision-propia.md), tras la 5.2).
