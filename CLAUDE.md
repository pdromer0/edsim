@AGENTS.md

## Específico de Claude Code

Las instrucciones comunes a los agentes viven en AGENTS.md; aquí solo está lo propio de Claude Code.

- El modo inicial es `plan`, definido en `.claude/settings.json`.
- El estilo de salida es `Explanatory`, definido en `.claude/settings.json`.
- El hook `PostToolUse` aplica `ruff format` a los ficheros Python editados, definido en `.claude/settings.json`.
- El hook `Stop` ejecuta los tests rápidos; está configurado en `.claude/settings.json` y definido en `.claude/hooks/run-tests.sh`.
