@AGENTS.md

## Específico de Claude Code

Las instrucciones comunes a los agentes viven en AGENTS.md; aquí solo está lo propio de Claude Code.

- El modo inicial es `plan`, definido en `.claude/settings.json`.
- El estilo de salida es `Explanatory`, definido en `.claude/settings.json`.
- El hook `PostToolUse` aplica `ruff format` a los ficheros Python editados, definido en `.claude/settings.json`.
- El hook `Stop` ejecuta `scripts/tests-rapidos.sh` (la rápida con sello, también de la app si las rutas la afectan) y no hace nada en modo plan; está configurado en `.claude/settings.json` y definido en `.claude/hooks/run-tests.sh`.
  Para que la espera de 2 a 3 minutos no parezca un cuelgue, lleva un `statusMessage` que avisa de que empieza la N2. En verde termina con un `systemMessage` corto: las suites que ejecutó, o por qué ninguna.
- El hook `SessionStart` mete en el contexto la rama, la última etiqueta, la línea «Hito en curso» de `AGENTS.md` y `git status -sb`, al abrir una sesión, reanudarla, tras `/clear` y al compactar. Solo usa `git` y `grep` locales; está definido en `.claude/hooks/session-start.sh`.
- Las reglas `ask` de `.claude/settings.json` piden confirmación al editar o escribir `config/` y `tests/data/` (la configuración calibrada y los datos de referencia), también en modo auto.
- Sin `jq`, los dos hooks que lo usan (`PostToolUse` y `Stop`) salen con código 1: un error que no bloquea y que se ve en la sesión.
- Lo personal de Pedro vive en `~/.claude`, no en el repositorio: el aviso de Windows (hook `Notification`), la línea de estado, el plugin LSP de Python (pyright) y Remote Control (`claude --rc`). Los pasos están en [docs/proceso/portabilidad.md](docs/proceso/portabilidad.md), sección 5.
- Las especificaciones grandes se leen por secciones (`grep -n '^#'` y después Read con offset y limit), nunca enteras.
- `/tarea-edsim N [notas efímeras]` empieza una tarea desde su issue (cuerpo y comentarios; las notas duraderas van en el comentario «Notas del chat») y la lleva hasta el PR; `/sincronizar [N]`, tras la fusión (después de `/clear`). Están en `.claude/skills/` y solo se lanzan a mano.
- Al terminar una tarea (PR abierto), recuerda a Pedro que haga `/clear` antes de la siguiente, y también antes de revisar o sincronizar.
- Con el plan aprobado, haces `git push -u origin <rama>` de tu rama (`feat/*`, `fix/*`, `docs/*`, `refactor/*`, `test/*`, `chore/*` o `ci/*`) y abres el PR con `gh pr create` sin pedir confirmación. Es una excepción que sustituye el paso 3 de «Reglas de git» de AGENTS.md; Codex sigue pidiendo permiso. El push forzado y el push a `main` están denegados en `.claude/settings.json`, y `gh pr merge` también: la fusión es de Pedro.
