# App web de EDsim

Especificación: [docs/specs/fase-1.md](docs/specs/fase-1.md).
Se aplican también las instrucciones del [AGENTS.md raíz](../AGENTS.md).

## Arquitectura y frontera

- La app es una capa fina: muestra y recoge datos. La simulación, los cálculos y
  la persistencia viven en `edsim`, con tests; si una página necesita lógica nueva,
  añade primero una función pública al núcleo.
- Usa solo la superficie pública del núcleo: nada con `_` delante y, para los
  servicios de ejecuciones, lo declarado en `__all__` de `edsim.runs`.
- `edsim-app` depende de `edsim`, nunca al revés. El núcleo no importa `streamlit`,
  `pandas` ni `edsim_app`. pandas y Altair solo pertenecen a la app; se declaran
  como dependencias directas cuando la app los importe.
- Las ejecuciones y las variantes se guardan en `resultados/`, nunca en `app/`.

## Pruebas y convenciones

- Prueba las páginas con `AppTest` desde `main.py`; tras el primer `run()`, usa
  `switch_page` y otro `run()`. Comprueba los elementos de la página de destino,
  además de la ausencia de excepciones, para evitar tests que pasen en vacío.
- No arranques servidores de Streamlit: no terminan y bloquean la sesión.
  Pedro revisa la app en el navegador. El lanzador se prueba con un doble.
- Código, nombres y docstrings en inglés; interfaz y documentación en español.
- Commits de funcionalidad y correcciones con ámbito: `feat(app)` y `fix(app)`.
- Las decisiones van en `docs/decisiones/` con serie `APP-0001`… si obligan solo
  a la app; si obligan al núcleo, van en la serie del núcleo. Las ADR de la fase 1
  y la entrada de su diario se escriben en A.8; las notas de cada tarea van en el PR.

## Comandos desde la raíz del repositorio

Los comandos de git que escriben en `.git` se piden directamente fuera del sandbox.

```bash
uv sync --all-packages
uv run --package edsim-app pytest app/tests
uv run --package edsim-app pytest app/tests -m "not slow"
uv run ruff check .
uv run ruff format .
```

Sincronizar dependencias requiere permiso previo, como establece el AGENTS.md raíz.
Un `uv sync` simple desinstala la app; el comando estándar incluye `--all-packages`.
Para la revisión manual, Pedro ejecuta `uv run --package edsim-app edsim-app`
y abre `http://localhost:8501`. El agente nunca ejecuta ese arranque.
