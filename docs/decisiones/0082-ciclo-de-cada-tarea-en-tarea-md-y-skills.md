# 0082. El ciclo de cada tarea se escribe una vez en `tarea.md` y lo ejecutan las skills

- **Estado:** Aceptada
- **Fecha:** 2026-11-11

## Contexto

Cada tarea repetía en su prompt los mismos pasos: leer la especificación, planificar, crear la rama, hacer commits, ejecutar los tests, abrir el PR, mover el tablero. Un cambio de proceso había que copiarlo a todos los prompts ([ADR 0081](0081-github-como-gestor-del-trabajo.md) deja el estado de la tarea en el issue; faltaba el procedimiento).

## Decisión

El ciclo se escribe una vez, para cualquier agente, en [docs/proceso/tarea.md](../proceso/tarea.md): arranque, plan con seis apartados, implementación por niveles de tests ([ADR 0047](0047-tests-por-niveles.md)), antes del push, documentación en el mismo PR, pull request y ajustes de la revisión.

Claude Code lo ejecuta con dos skills de `.claude/skills/`, que solo se lanzan a mano:

- `/tarea-edsim N` lee el issue y sus comentarios, comprueba las dependencias, presenta el plan, mueve la ficha, implementa, lanza la N3 y `/code-review` **en paralelo** antes del push, y abre el PR.
- `/sincronizar [N]`, tras la fusión y después de `/clear`: comprueba que el PR está fusionado, actualiza `main`, borra la rama local solo si su punta está contenida en el PR (`refs/pull/N/head`) y revisa el tablero.

Codex lee el mismo `tarea.md` desde `AGENTS.md`. Los permisos de las skills van en `.claude/settings.json`, porque `allowed-tools` solo vale durante el turno que lanza la skill. El push de Claude Code a su rama con el plan aprobado es una excepción escrita en `CLAUDE.md`; la fusión sigue siendo de Pedro.

## Alternativas consideradas

- Un prompt completo por tarea: se desfasa y obliga a corregir cada copia.
- El ciclo dentro de cada skill: Codex no lo leería y habría dos versiones que mantener.
- Una sola skill para arrancar y sincronizar: arrancan en estados distintos (el arranque pide modo plan; la sincronización, un árbol limpio y la rama fusionada).
- Lanzar la N3 y después `/code-review`: la revisión espera 14 minutos de tests que no necesita.

## Consecuencias

- Un cambio de proceso se toca una vez. Cada tarea llega al PR con la misma plantilla, las mismas métricas y la misma revisión propia.
- La prueba de humo de la A5 destapó seis hallazgos; los que cambian el ciclo entran en `tarea.md` y en la skill en la A6 (la N3 se repite solo si las correcciones tocan algo que la N3 ejecuta; los scripts de los hooks se verifican a mano; la skill pide el modo plan antes de presentar el plan; `docker compose ps` que falla por Docker parado cuenta como «sin Kafka»).
- Un push que solo lleva documentación, plantillas o una skill puede ir sin N3 si Pedro lo autoriza, porque el CI lo comprueba igual.
- Quedan en prueba, en las tareas 5.2 a 5.8, los subagentes para las versiones incorrectas, `@claude` en el PR, Codex desde el issue y la sesión en la nube ([portabilidad.md](../proceso/portabilidad.md#14-estado-de-las-piezas-en-prueba)).
