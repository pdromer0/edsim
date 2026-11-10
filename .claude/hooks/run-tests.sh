#!/usr/bin/env bash
# Stop hook: al terminar cada turno de Claude, los tests rápidos con sello
# (scripts/tests-rapidos.sh), que solo ejecutan las suites afectadas por los cambios.
# Si fallan, sale con código 2 y Claude recibe el final de la salida por stderr.
set -u

# Sin jq no podemos leer la entrada: avisar sin bloquear. El código 1 es un error que no
# bloquea y que Claude Code muestra en la sesión. El 2 bloquearía y, sin poder leer
# stop_hook_active, entraría en bucle; el stderr de un 0 no se ve.
if ! command -v jq >/dev/null 2>&1; then
  echo "run-tests.sh: jq no está instalado; se omiten los tests." >&2
  exit 1
fi

entrada=$(cat)

# Si Claude ya continúa por este hook, no volver a bloquear (evita bucles).
if [ "$(jq -r '.stop_hook_active // false' <<<"$entrada" 2>/dev/null)" = "true" ]; then
  exit 0
fi

# En modo plan el árbol no cambia: no se ejecuta nada.
if [ "$(jq -r '.permission_mode // ""' <<<"$entrada" 2>/dev/null)" = "plan" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}" || exit 0

if ! salida=$(scripts/tests-rapidos.sh 2>&1); then
  printf '%s\n' "$salida" | tail -n 50 >&2
  exit 2
fi
printf '%s\n' "$salida" | tail -n 1
