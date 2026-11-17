#!/usr/bin/env bash
# Tests de integración contra un Kafka, un Postgres y un Grafana reales (tests_integracion/), en
# local y en el CI (job tests-integracion).
#
# Compose va con el perfil analitica, el de Grafana. Si Kafka, Postgres y Grafana de compose.yaml
# ya están sanos, los usa y los deja en marcha. Si no, levanta lo que falta con
# docker compose up --wait y, al salir, baja solo eso: con los tres parados, docker compose down;
# con alguno ya en marcha (el Kafka del notebook 06, que no tiene volumen, o el compose sin el
# perfil), docker compose rm -sf de los que faltaban, y lo que estaba sigue igual. Nunca con -v:
# el volumen de Postgres, con los datos de Pedro, se queda; los tests usan una base de datos
# propia y la borran. Sincroniza el entorno de dbt (analitica/), ejecuta pytest con los extras
# kafka y postgres y uv.lock tal cual (--locked), imprime los tiempos y sale con el código de
# pytest. Si algo falla, imprime antes el final del registro de los tres.
set -u

# Límite del arranque, fijado antes de medir (unos 10 s en el portátil con las imágenes ya
# descargadas; la descarga va antes y no cuenta; Postgres con un volumen nuevo, unos 10 s más).
WAIT_TIMEOUT=120

# El perfil analitica en todas las órdenes de compose (up, ps, logs, rm y down), para que vean
# Grafana (tests_integracion/test_grafana.py): un down sin el perfil lo dejaría vivo y no podría
# borrar la red.
export COMPOSE_PROFILES=analitica
# Los servicios que se comprueban; la consola va con Kafka.
SERVICIOS=(kafka postgres grafana)

raiz=$(git rev-parse --show-toplevel) || exit 1
cd "$raiz" || exit 1

resumen=()
duracion() {
  local segundos=$1
  printf '%d:%02d' $((segundos / 60)) $((segundos % 60))
}

registro_servicios() {
  local servicio
  for servicio in "${SERVICIOS[@]}"; do
    echo "tests-integracion.sh: últimas 50 líneas del registro de $servicio:" >&2
    docker compose logs --no-color --tail 50 "$servicio" >&2
  done
}

sano() {
  [ "$(docker compose ps "$1" --format '{{.Health}}' 2>/dev/null)" = healthy ]
}

# Lo que este script levantó: vacío si no levantó nada, «todo» si no había nada en marcha, o
# los servicios que faltaban (la consola va con Kafka).
levantados=()

bajar() {
  local inicio
  inicio=$(date +%s)
  if [ "${levantados[*]}" = todo ]; then
    echo "tests-integracion.sh: docker compose down"
    docker compose down
  else
    # Solo lo que levantó el script: el servicio que ya estaba en marcha sigue igual.
    echo "tests-integracion.sh: docker compose rm -sf ${levantados[*]}"
    docker compose rm -sf "${levantados[@]}"
  fi
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
faltan=()
for servicio in "${SERVICIOS[@]}"; do
  sano "$servicio" || faltan+=("$servicio")
done
if [ "${#faltan[@]}" -eq 0 ]; then
  echo "tests-integracion.sh: Kafka, Postgres y Grafana de compose.yaml ya están sanos; se usan y se dejan en marcha"
else
  # Lo que falta lo levanta este script, y al salir lo baja, pase lo que pase; lo que ya estaba
  # en marcha se usa y se deja.
  if [ "${#faltan[@]}" -eq "${#SERVICIOS[@]}" ]; then
    levantados=(todo)
  else
    for servicio in "${faltan[@]}"; do
      levantados+=("$servicio")
      if [ "$servicio" = kafka ]; then
        levantados+=(console)
      fi
    done
  fi
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

# El entorno de dbt (analitica/, con su propio uv.lock), antes de pytest y con su tiempo en el
# resumen: en frío descarga dbt, y la medida de la 8.1 la separa de la de los tests.
inicio=$(date +%s)
(cd analitica && uv sync --locked)
rc=$?
resumen+=("dbt (sync) $(duracion $(($(date +%s) - inicio)))")
if [ "$rc" -ne 0 ]; then
  echo "tests-integracion.sh: uv sync de analitica/ falló (código $rc)" >&2
  $levantado || imprimir_resumen
  exit "$rc"
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
