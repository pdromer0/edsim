# 0012. Desarrollo en Windows con WSL2, Docker Desktop y Cursor

- **Estado:** Aceptada (confirmada en el hito 0)
- **Fecha:** 2026-10-27

## Contexto

Pedro trabaja en Windows, y el CI corre en Linux ([diseño](../diseno.md#preguntas-resueltas)).

## Decisión

Se desarrolla dentro de WSL2 (Ubuntu), con Docker Desktop sobre el motor WSL2 y con Cursor conectado a WSL. El código vive en el sistema de ficheros de Linux (`~/proyectos`). WSL y Claude Code se mantienen en el canal estable.

Motivo: que el entorno local se parezca al CI en Linux.

## Alternativas consideradas

Ambas constan en la [spec del hito 0](../specs/hito-0.md#cómo-encajan-las-piezas):

- Claude Code en Windows nativo: no tiene el sandbox de comandos y necesita Git for Windows.
- El código en `C:` (`/mnt/c`): se descarta por rendimiento y permisos.

## Consecuencias

- Cursor es la única aplicación de trabajo en Windows. Se conecta a WSL con la extensión Remote WSL de Anysphere, porque la de Microsoft no es compatible con Cursor.
- El cliente `docker` funciona desde WSL gracias a la integración de Docker Desktop.
- Los problemas de instalación del hito 0 están en el [diario](../diario/hito-0.md).
