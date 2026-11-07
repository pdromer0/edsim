#!/usr/bin/env bash
# N3: comprobación completa antes de cada push.
#
# Ejecuta todas las partes, una tras otra, aunque alguna falle: lint, formato, núcleo completo
# en paralelo con xdist, app en serie y notebooks en modo rápido. Imprime el tiempo de pared de
# cada una y sale con 1 si alguna falló. Con todo en verde, escribe los sellos de las dos
# suites, como haría tests-rapidos.sh.
set -u

# xdist solo en el núcleo, con las medidas de la tarea P.1: auto y worksteal, el más rápido en
# la completa. La app va en serie y sola, después del núcleo: con la CPU ocupada, sus AppTest
# superan el límite de 3 s por página.
XDIST_NUCLEO=(-n auto --dist worksteal)

raiz=$(git rev-parse --show-toplevel) || exit 1
cd "$raiz" || exit 1
# shellcheck source=scripts/sello.sh
source scripts/sello.sh
mkdir -p "$SELLO_DIR" || exit 1

# El manifiesto del principio es el que se sella: lo que cambie durante la ejecución no
# queda como verde.
inicial=$(mktemp "$SELLO_DIR/manifiesto.XXXXXX") || exit 1
trap 'rm -f "$inicial"' EXIT
manifiesto >"$inicial" || exit 1

resumen=()
fallos=0

parte() {
  local etiqueta=$1 inicio fin rc segundos
  shift
  printf '\n== tests-completos.sh: %s\n' "$etiqueta"
  inicio=$(date +%s)
  "$@"
  rc=$?
  fin=$(date +%s)
  segundos=$((fin - inicio))
  if [ "$rc" -eq 0 ]; then
    estado=verde
  else
    estado="fallo (código $rc)"
    fallos=$((fallos + 1))
  fi
  # Relleno a mano: printf cuenta bytes y «núcleo» lleva una tilde.
  resumen+=("$etiqueta$(printf '%*s' $((11 - ${#etiqueta})) '')$estado$(printf '%*s' $((19 - ${#estado})) '')$(printf '%d:%02d' $((segundos / 60)) $((segundos % 60)))")
}

total_inicio=$(date +%s)
parte lint uv run ruff check .
parte formato uv run ruff format --check .
parte núcleo uv run pytest "${XDIST_NUCLEO[@]}"
parte app uv run --package edsim-app pytest app/tests
parte notebooks env EDSIM_NB_RAPIDO=1 uv run pytest --nbmake notebooks/
total=$(($(date +%s) - total_inicio))

printf '\n== tests-completos.sh: resumen\n'
printf '%s\n' "${resumen[@]}"
printf 'total%*s%d:%02d\n' 25 '' $((total / 60)) $((total % 60))

if [ "$fallos" -gt 0 ]; then
  if [ "$fallos" -eq 1 ]; then cuantas="1 parte falló"; else cuantas="$fallos partes fallaron"; fi
  echo "tests-completos.sh: $cuantas; los sellos no cambian."
  exit 1
fi
sella nucleo "$inicial" && sella app "$inicial" || exit 1
echo "tests-completos.sh: todo en verde; sellos del núcleo y de la app actualizados."
