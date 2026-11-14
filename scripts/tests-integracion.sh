#!/usr/bin/env bash
# Tests de integración contra un Kafka y un Postgres reales (tests_integracion/), en local y en
# el CI (job tests-integracion).
#
# Si Kafka y Postgres de compose.yaml ya están sanos, los usa y los deja en marcha. Si no, los
# levanta con docker compose up --wait y los baja al salir (sin -v: el volumen de Postgres, con
# los datos de Pedro, se queda; los tests usan una base de datos propia y la borran). Ejecuta
# pytest con los extras kafka y postgres y uv.lock tal cual (--locked), imprime los tiempos y
# sale con el código de pytest. Si algo falla, imprime antes el final del registro de los dos.
set -u

# Límite del arranque, fijado antes de medir (unos 10 s en el portátil con las imágenes ya
# descargadas; la descarga va antes y no cuenta; Postgres con un volumen nuevo, unos 10 s más).
WAIT_TIMEOUT=120

raiz=$(git rev-parse --show-toplevel) || exit 1
cd "$raiz" || exit 1

resumen=()
duracion() {
  local segundos=$1
  printf '%d:%02d' $((segundos / 60)) $((segundos % 60))
}

registro_servicios() {
  local servicio
  for servicio in kafka postgres; do
    echo "tests-integracion.sh: últimas 50 líneas del registro de $servicio:" >&2
    docker compose logs --no-color --tail 50 "$servicio" >&2
  done
}

sano() {
  [ "$(docker compose ps "$1" --format '{{.Health}}' 2>/dev/null)" = healthy ]
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
if sano kafka && sano postgres; then
  echo "tests-integracion.sh: Kafka y Postgres de compose.yaml ya están sanos; se usan y se dejan en marcha"
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
    registro_servicios
    exit "$rc"
  fi
fi

inicio=$(date +%s)
uv run --locked --extra kafka --extra postgres pytest tests_integracion
rc=$?
resumen+=("pytest     $(duracion $(($(date +%s) - inicio)))")
if [ "$rc" -ne 0 ]; then
  registro_servicios
fi
# Con los servicios levantados aquí, el resumen lo imprime bajar() al salir.
$levantado || imprimir_resumen
exit "$rc"
