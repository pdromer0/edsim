#!/usr/bin/env bash
# Stop hook: ejecuta los tests al terminar cada turno de Claude.
# Si fallan, sale con código 2 y Claude recibe el final de la salida por stderr.
set -u

# Sin jq no podemos leer la entrada: avisar y no bloquear.
if ! command -v jq >/dev/null 2>&1; then
  echo "run-tests.sh: jq no está instalado; se omiten los tests." >&2
  exit 0
fi

# Si Claude ya continúa por este hook, no volver a bloquear (evita bucles).
if [ "$(jq -r '.stop_hook_active // false')" = "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}" || exit 0

if ! salida=$(uv run pytest -q -x -m "not slow" 2>&1); then
  printf '%s\n' "$salida" | tail -n 50 >&2
  exit 2
fi
