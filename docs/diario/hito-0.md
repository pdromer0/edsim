# Diario · Hito 0 — Entorno de desarrollo

Especificación: [docs/specs/hito-0.md](../specs/hito-0.md)

## 2026-10-28 · Tarea 0.1 — Windows y WSL2

**Qué se hizo:** instalación de WSL2 con Ubuntu, Docker Desktop y Cursor. Por el camino hubo que recuperar WSL de una actualización que lo dejó sin arrancar.

**Qué aprendí:**
- `wsl --update` solo sube de versión; no sirve para volver a una versión anterior.
- Conviene usar canales estables: una versión preliminar puede romper el entorno entero.

**Qué costó o falló:**
- WSL se actualizó por winget a la 3.0.3, una versión preliminar, y dejó de arrancar la máquina virtual (`CreateVm/ERROR_FILE_NOT_FOUND`).
- Diagnóstico: fallaban todas las distribuciones, la plataforma de máquina virtual estaba activa y no había `.wslconfig`.
- Solución: desinstalar con winget y volver a la estable 2.7.13.

**Preguntas abiertas:** ninguna.

**Enlaces:** [ADR 0012](../decisiones/0012-entorno-windows-con-wsl2.md)

## 2026-10-28 · Tarea 0.2 — Herramientas en Ubuntu

**Qué se hizo:** instalación de git, GitHub CLI, uv y Claude Code dentro de Ubuntu.

**Qué aprendí:**
- Si se olvida la contraseña de Linux, se puede entrar como root con `wsl -d Ubuntu -u root` y cambiarla con `passwd`.
- GitHub CLI se instala desde el repositorio oficial de GitHub, no desde el paquete de Ubuntu.
- En WSL, el login de `gh` necesita copiar la URL al navegador; wslu lo resuelve.
- Un programa recién instalado puede no encontrarse hasta recargar el PATH.
- Claude Code puede pasar al canal estable fijando la versión actual como mínima.

**Qué costó o falló:**
- La contraseña de Linux estaba olvidada.
- El paquete de GitHub CLI de Ubuntu está roto.
- uv no se encontraba tras instalarlo, hasta recargar el PATH.

**Preguntas abiertas:** ninguna.

**Enlaces:** [ADR 0012](../decisiones/0012-entorno-windows-con-wsl2.md)

## 2026-10-28 · Tarea 0.4 — Calidad local

**Qué se hizo:** ruff, pytest y pre-commit, con un test de humo. Se probó la barandilla de pre-commit con un fichero mal formateado.

**Qué aprendí:**
- pre-commit bloquea el commit si un hook falla: el fichero mal formateado no llegó a entrar.

**Qué costó o falló:** nada.

**Preguntas abiertas:** ninguna.

**Enlaces:** PR #1

## 2026-10-28 · Tarea 0.5 — CI en GitHub Actions

**Qué se hizo:** workflow de CI con lint, formato y tests. Se puso en rojo a propósito para practicar la lectura de un fallo.

**Qué aprendí:**
- `gh run view --log-failed` muestra solo el log de los pasos que fallaron.
- `git revert` deshace un commit con otro commit nuevo, sin reescribir el historial.
- Hay que verificar con herramientas, no con lo que afirma un modelo.

**Qué costó o falló:**
- El asistente del chat dudó de que existiera setup-uv v10.3.3; el CI demostró que sí.

**Preguntas abiertas:** ninguna.

**Enlaces:** PR #2 · [ADR 0011](../decisiones/0011-github-flow-con-ci-obligatorio.md)

## 2026-10-28 · Tarea 0.6 — Ruleset de main

**Qué se hizo:** ruleset que protege `main` en GitHub.

**Qué aprendí:**
- El ruleset rechaza un push directo a `main` con el error GH013.

**Qué costó o falló:** nada.

**Preguntas abiertas:** ninguna.

**Enlaces:** [ADR 0014](../decisiones/0014-repositorio-publico-con-ruleset.md)

## 2026-10-28 · Tarea 0.7 — Configuración de Claude Code

**Qué se hizo:** `CLAUDE.md`, `.claude/settings.json` con permisos, hooks y estilo `Explanatory`, y estructura de `docs/`.

**Qué aprendí:**
- El `defaultMode: "plan"` de `.claude/settings.json` vale para las sesiones de terminal, pero no para el panel de Cursor.
- Para el panel hace falta `claudeCode.initialPermissionMode` en los ajustes de usuario de Cursor.

**Qué costó o falló:**
- El modo Plan por defecto no se aplicaba en el panel de Cursor.

**Preguntas abiertas:** ninguna.

**Enlaces:** PR #3 · [ADR 0008](../decisiones/0008-claude-code-escribe-el-codigo.md)

## Reflexiones de Pedro
