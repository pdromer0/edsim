#!/usr/bin/env bash
# N2: tests rápidos con sello, para el Stop de Claude Code y el de Codex.
#
# Para cada suite (núcleo y app) compara el árbol con su sello, el manifiesto de su último
# verde. Ejecuta la rápida (-m "not slow", -x; el núcleo en paralelo con xdist) de las suites
# que afectan las rutas cambiadas y solo con verde actualiza su sello. Las demás se re-sellan
# sin ejecutar. Sale con el código de pytest de la primera suite que falla, o con 0.
set -u

# xdist solo en el núcleo, con las medidas de la tarea P.1: auto (6 workers en el portátil de
# referencia; con 12 hay swap) y loadfile, que empata con el mejor y deja cada módulo en un worker.
# La app va en serie: en paralelo no llegaba al 60 % y sus AppTest superan el límite de 3 s.
XDIST_NUCLEO=(-n auto --dist loadfile)

raiz=$(git rev-parse --show-toplevel) || exit 1
cd "$raiz" || exit 1
# shellcheck source=scripts/sello.sh
source scripts/sello.sh
mkdir -p "$SELLO_DIR" || exit 1

# El manifiesto se calcula una vez, antes de pytest: lo que cambie durante los tests no
# queda sellado como verde.
actual=$(mktemp "$SELLO_DIR/manifiesto.XXXXXX") || exit 1
cambios=$(mktemp "$SELLO_DIR/cambios.XXXXXX") || exit 1
trap 'rm -f "$actual" "$cambios"' EXIT
manifiesto >"$actual" || exit 1

declare -A nombre=([nucleo]=núcleo [app]=app)
ejecutar=()
saltadas=()
for suite in nucleo app; do
  sello="$SELLO_DIR/sello-$suite"
  if [ ! -f "$sello" ]; then
    echo "tests-rapidos.sh: ${nombre[$suite]}, sin sello" >&2
    ejecutar+=("$suite")
    continue
  fi
  rutas_cambiadas "$sello" "$actual" >"$cambios"
  if [ ! -s "$cambios" ]; then
    saltadas+=("${nombre[$suite]}, sin cambios desde el último verde")
    continue
  fi
  afectan=()
  solo_doc=true
  while IFS= read -r ruta; do
    clase=$(clasifica "$ruta")
    [ "$clase" = doc ] || solo_doc=false
    if [ "$clase" = ambas ] || [ "$clase" = "$suite" ]; then
      afectan+=("$ruta")
    fi
  done <"$cambios"
  if [ "${#afectan[@]}" -gt 0 ]; then
    muestra=$(printf '%s, ' "${afectan[@]:0:5}")
    [ "${#afectan[@]}" -gt 5 ] && muestra+="…, "
    if [ "${#afectan[@]}" -eq 1 ]; then cuantas="1 ruta cambiada"; else cuantas="${#afectan[@]} rutas cambiadas"; fi
    echo "tests-rapidos.sh: ${nombre[$suite]}, $cuantas (${muestra%, })" >&2
    ejecutar+=("$suite")
  else
    # Nada de lo cambiado afecta a esta suite: su último verde sigue valiendo.
    sella "$suite" "$actual" || exit 1
    if $solo_doc; then
      saltadas+=("${nombre[$suite]}, solo documentación")
    else
      saltadas+=("${nombre[$suite]}, sin cambios que le afecten")
    fi
  fi
done

for suite in "${ejecutar[@]}"; do
  case "$suite" in
    nucleo) uv run pytest -q -x -m "not slow" "${XDIST_NUCLEO[@]}" ;;
    app) uv run --package edsim-app pytest app/tests -q -x -m "not slow" ;;
  esac
  rc=$?
  if [ "$rc" -ne 0 ]; then
    exit "$rc"
  fi
  sella "$suite" "$actual" || exit 1
done

if [ "${#saltadas[@]}" -gt 0 ]; then
  # Una sola línea; si las dos suites se saltan por lo mismo, se dice una vez.
  if [ "${#saltadas[@]}" -eq 2 ] && [ "${saltadas[0]#*, }" = "${saltadas[1]#*, }" ]; then
    echo "tests-rapidos.sh: ${saltadas[0]#*, }"
  else
    linea=$(printf '%s; ' "${saltadas[@]}")
    echo "tests-rapidos.sh: ${linea%; }"
  fi
fi
exit 0
