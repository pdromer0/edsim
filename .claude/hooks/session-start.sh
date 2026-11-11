#!/usr/bin/env bash
# SessionStart hook: la salida (stdout) entra en el contexto de Claude al abrir una sesión,
# al reanudarla, tras /clear y al compactar. Solo comandos locales de git y grep, sin red,
# y siempre sale con código 0: un fallo aquí no debe impedir abrir la sesión.
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}" 2>/dev/null || exit 0

# Fuera de un repositorio git no hay nada que contar.
git rev-parse --git-dir >/dev/null 2>&1 || exit 0

rama=$(git branch --show-current 2>/dev/null)
echo "rama: ${rama:-(HEAD desacoplado)}"

# La etiqueta más cercana a HEAD; sin etiquetas, git describe falla.
etiqueta=$(git describe --tags --abbrev=0 2>/dev/null) || etiqueta=""
echo "última etiqueta: ${etiqueta:-ninguna}"

hito=$(grep -m1 '^- Hito en curso' AGENTS.md 2>/dev/null) || hito=""
hito=${hito#- }
echo "${hito:-Hito en curso: no encontrado}"

# Como mucho 15 líneas; si hay más, se dice cuántas faltan.
git status -sb 2>/dev/null \
  | awk 'NR <= 15 { print } END { if (NR > 15) printf "… y %d líneas más\n", NR - 15 }'
exit 0
