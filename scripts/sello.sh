# Funciones del sello de los tests: se cargan con `source` desde tests-rapidos.sh y
# tests-completos.sh, en la raíz del repositorio.
#
# El sello de una suite (núcleo o app) es el manifiesto del árbol en su último verde: una
# línea "<sha1>  <ruta>" por fichero seguido o sin seguir no ignorado. Vive en .cache/edsim/,
# fuera de .git: nada de esto escribe en .git, que en el sandbox de Codex es de solo lectura.

SELLO_DIR=.cache/edsim

# Escribe por stdout el manifiesto del árbol actual, ordenado.
manifiesto() {
  local lista hashes errores rc
  lista=$(mktemp "$SELLO_DIR/lista.XXXXXX") || return 1
  hashes="$lista.sha1"
  errores="$lista.err"
  if ! git ls-files -z --cached --others --exclude-standard >"$lista"; then
    echo "sello.sh: git ls-files falló" >&2
    rm -f "$lista"
    return 1
  fi
  # Un fichero seguido y borrado sigue en el índice: sha1sum no lo encuentra y xargs sale
  # con 123. Es lo esperado: falta en el manifiesto y cuenta como cambio. Cualquier otro
  # error (otro código, u otro mensaje de sha1sum) se trata como fallo.
  xargs -0 -r sha1sum <"$lista" >"$hashes" 2>"$errores"
  rc=$?
  if [ "$rc" -ne 0 ] && { [ "$rc" -ne 123 ] || grep -qv 'No such file or directory' "$errores"; }; then
    echo "sello.sh: no se pudieron calcular las huellas (xargs salió con $rc):" >&2
    cat "$errores" >&2
    rm -f "$lista" "$hashes" "$errores"
    return 1
  fi
  LC_ALL=C sort -u "$hashes"
  rm -f "$lista" "$hashes" "$errores"
}

# Rutas que cambian entre dos manifiestos (añadidas, borradas o modificadas), una por línea.
rutas_cambiadas() {
  LC_ALL=C comm -3 "$1" "$2" | sed -e 's/^\t//' -e 's/^\\\{0,1\}[0-9a-f]\{40\}  //' | LC_ALL=C sort -u
}

# A qué afecta una ruta: doc (a nada), app, nucleo o ambas. El orden de los casos importa.
clasifica() {
  case "$1" in
    *.md | docs/* | app/docs/* | notebooks/*) echo doc ;;
    app/*) echo app ;;
    # tests/data/ lo lee también app/tests/conftest.py.
    src/edsim/* | config/* | pyproject.toml | uv.lock | tests/data/*) echo ambas ;;
    tests/* | scripts/* | .claude/* | .codex/* | .github/* | .pre-commit-config.yaml | .gitignore)
      echo nucleo ;;
    # Lo que no sabemos clasificar afecta a las dos: es lo conservador.
    *) echo ambas ;;
  esac
}

# Copia el manifiesto $2 como sello de la suite $1, de forma atómica.
sella() {
  local tmp
  tmp=$(mktemp "$SELLO_DIR/sello-$1.XXXXXX") || return 1
  cp "$2" "$tmp" && mv "$tmp" "$SELLO_DIR/sello-$1"
}
