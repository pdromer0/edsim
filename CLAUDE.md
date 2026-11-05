@AGENTS.md

## Específico de Claude Code

Las instrucciones comunes a los agentes viven en AGENTS.md; aquí solo está lo propio de Claude Code.

- El modo inicial es `plan`, definido en `.claude/settings.json`.
- El estilo de salida es `Explanatory`, definido en `.claude/settings.json`.
- El hook `PostToolUse` aplica `ruff format` a los ficheros Python editados, definido en `.claude/settings.json`.
- El hook `Stop` ejecuta los tests rápidos; está configurado en `.claude/settings.json` y definido en `.claude/hooks/run-tests.sh`.
- Con el plan aprobado, haces `git push -u origin <rama>` de tu rama (`feat/*` o `docs/*`) y abres el PR con `gh pr create` sin pedir confirmación. El push forzado y el push a `main` están denegados en `.claude/settings.json`, y `gh pr merge` también: la fusión es de Pedro.
