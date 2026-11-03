#!/usr/bin/env bash
# Stop de Codex: formatea el código y ejecuta los tests rápidos antes de terminar.
# Un fallo devuelve código 2 y las últimas 50 líneas por stderr para que el agente continúe.
set -u

# Sin jq no podemos interpretar la entrada: avisar y no bloquear.
if ! command -v jq >/dev/null 2>&1; then
  echo "run-tests.sh: jq no está instalado; se omiten el formato y los tests." >&2
  printf '{}\n'
  exit 0
fi

# Codex entrega un objeto JSON por stdin, incluido el indicador de continuación.
if ! stop_hook_active=$(jq -r '
  if type != "object" then error("Se esperaba un objeto JSON")
  elif has("stop_hook_active") and (.stop_hook_active | type) != "boolean"
  then error("stop_hook_active debe ser booleano")
  else .stop_hook_active // false end
'); then
  echo "run-tests.sh: entrada JSON inválida." >&2
  exit 2
fi

# No volver a bloquear un turno que ya continuó por este hook: evita bucles.
if [ "$stop_hook_active" = "true" ]; then
  printf '{}\n'
  exit 0
fi

# Resolver la raíz con git permite ejecutar el hook desde cualquier subdirectorio.
if ! repo_root=$(git rev-parse --show-toplevel); then
  echo "run-tests.sh: no se pudo localizar la raíz del repositorio." >&2
  exit 2
fi
if ! cd "$repo_root"; then
  echo "run-tests.sh: no se pudo acceder a la raíz del repositorio." >&2
  exit 2
fi

# Capturar la salida: stdout queda reservado al JSON del protocolo de Codex.
if ! output=$(uv run ruff format . 2>&1); then
  printf '%s\n' "$output" | tail -n 50 >&2
  exit 2
fi
printf '%s\n' "$output" >&2

if ! output=$(uv run pytest -q -x -m "not slow" 2>&1); then
  printf '%s\n' "$output" | tail -n 50 >&2
  exit 2
fi
printf '%s\n' "$output" | tail -n 50 >&2

if ! output=$(uv run --package edsim-app pytest app/tests -q -x -m "not slow" 2>&1); then
  printf '%s\n' "$output" | tail -n 50 >&2
  exit 2
fi
printf '%s\n' "$output" | tail -n 50 >&2

printf '{}\n'
