# 0018. Notebooks de Jupyter sin lógica propia

- **Estado:** Aceptada
- **Fecha:** 2026-10-29

## Contexto

El hito 1 incluye un notebook didáctico, abierto en Cursor, para explorar los conceptos de la M/M/1 ([especificación](../specs/hito-1.md#notebook-de-exploración-de-la-mm1)).

Ejecutar las celdas en cualquier orden puede dejar un notebook que solo funciona en una sesión: es el estado oculto. Además, las salidas y las imágenes hacen ilegibles los diffs de git.

## Decisión

- Se usan notebooks de Jupyter sin lógica propia: solo llaman a funciones de `edsim`, visualizan y explican. Lo que necesitan se añade al paquete con tests.
- `nbstripout` en pre-commit borra las salidas.
- En el CI, `nbmake` ejecuta los notebooks de principio a fin en modo rápido.

Motivo: explorar y aprender sin estado oculto ni salidas en git.

## Alternativas consideradas

- marimo: se elige Jupyter por ser el estándar.

## Consecuencias

- El notebook `notebooks/01_mm1_exploracion.ipynb` dio lugar a funciones nuevas, todas con tests:
  - `src/edsim/queueing/analysis.py`;
  - `t_critical`;
  - `coverage_mm1`;
  - `format_records`.
- `ipykernel` y `nbmake` son dependencias de desarrollo. `nbstripout` se instala como hook de pre-commit, en su propio entorno.
- **Modo rápido:** con `EDSIM_NB_RAPIDO=1`, una única celda de parámetros reduce réplicas y duraciones. El CI ejecuta así el notebook en unos 10 s.
- El hook de tests de Claude Code no ejecuta los notebooks: pytest solo recoge `tests/`, y `nbmake` solo actúa con `--nbmake`.
- **Modo normal:** tardó 288 s, cerca del límite de 300 s de `nbmake`. Se ejecuta con `uv run pytest --nbmake --nbmake-timeout=600 notebooks/`.
- **`nbstripout` en los commits:** si el notebook tiene salidas, cancela el primer commit, y hay que repetir `git add` y el commit. Tras cada commit, el notebook queda sin gráficas hasta volver a ejecutarlo.
