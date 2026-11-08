#!/usr/bin/env bash
# Tests de integración contra un Kafka real (tests_integracion/), en local y en el CI (job
# tests-kafka).
#
# Si el broker de compose.yaml ya está sano, lo usa y lo deja en marcha. Si no, lo levanta con
# docker compose up --wait y lo baja al salir. Ejecuta pytest con el extra kafka y uv.lock tal
# cual (--locked), imprime los tiempos y sale con el código de pytest. Si algo falla, imprime
# antes el final del registro del broker.
set -u

# Límite del arranque, fijado antes de medir (unos 10 s en el portátil con las imágenes ya
# descargadas; la descarga va antes y no cuenta).
WAIT_TIMEOUT=120

raiz=$(git rev-parse --show-toplevel) || exit 1
cd "$raiz" || exit 1

resumen=()
duracion() {
  local segundos=$1
  printf '%d:%02d' $((segundos / 60)) $((segundos % 60))
}

registro_kafka() {
  echo "tests-integracion.sh: últimas 50 líneas del registro de kafka:" >&2
  docker compose logs --no-color --tail 50 kafka >&2
}

bajar() {
  local inicio
  inicio=$(date +%s)
  echo "tests-integracion.sh: docker compose down"
  docker compose down
  resumen+=("bajada     $(duracion $(($(date +%s) - inicio)))")
  imprimir_resumen
}

imprimir_resumen() {
  printf '\n== tests-integracion.sh: resumen\n'
  printf '%s\n' "${resumen[@]}"
  printf 'total      %s\n' "$(duracion $(($(date +%s) - total_inicio)))"
}

total_inicio=$(date +%s)
levantado=false
if [ "$(docker compose ps kafka --format '{{.Health}}' 2>/dev/null)" = healthy ]; then
  echo "tests-integracion.sh: el broker de compose.yaml ya está sano; se usa y se deja en marcha"
else
  # Lo levanta este script: lo baja al salir, pase lo que pase.
  levantado=true
  trap bajar EXIT
  echo "tests-integracion.sh: docker compose up --wait --wait-timeout $WAIT_TIMEOUT"
  inicio=$(date +%s)
  docker compose up --wait --wait-timeout "$WAIT_TIMEOUT"
  rc=$?
  resumen+=("arranque   $(duracion $(($(date +%s) - inicio)))")
  if [ "$rc" -ne 0 ]; then
    echo "tests-integracion.sh: el arranque falló (código $rc)" >&2
    registro_kafka
    exit "$rc"
  fi
fi

inicio=$(date +%s)
uv run --locked --extra kafka pytest tests_integracion
rc=$?
resumen+=("pytest     $(duracion $(($(date +%s) - inicio)))")
if [ "$rc" -ne 0 ]; then
  registro_kafka
fi
# Con el broker levantado aquí, el resumen lo imprime bajar() al salir.
$levantado || imprimir_resumen
exit "$rc"
