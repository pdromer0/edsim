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
- Las páginas viven en `src/edsim_app/views/`. No crees una carpeta `pages/`
  junto a `main.py`: activa la navegación antigua de Streamlit y puede saltarse
  el estado compartido del punto de entrada, por ejemplo al abrir Replay.
- Código, nombres y docstrings en inglés; interfaz y documentación en español.
- Commits de funcionalidad y correcciones con ámbito: `feat(app)` y `fix(app)`.
- Las decisiones van en `docs/decisiones/` con serie `APP-0001`… si obligan solo
  a la app; si obligan al núcleo, van en la serie del núcleo. Las ADR de la fase 1
  y la entrada de su diario se escriben en A.8; las notas de cada tarea van en el PR.

### Selección de tests `slow`

El hook Stop excluye `slow`; el CI y la suite completa ejecutan todas las marcas.
La selección de los AppTest que simulan se hace durante la colección en
`tests/conftest.py`, sin editar los tests de caracterización de la A.5:

- `pytest_collection_modifyitems` solo examina `test_compare.py`,
  `test_episodes.py`, `test_navigation.py`, `test_results.py`, `test_runs.py` y
  `test_simulate.py`. Dentro de esos ficheros, marca `slow` si `run_templates`
  está en `item.fixturenames` (también por dependencias transitivas, como
  `catalog`) o si `item.originalname` pertenece a `_SIMULATION_TESTS`, que recoge
  los casos de simulación o carga prevista que no usan esa fixture.
- `test_smoke.py` se excluye expresamente de esa selección, aunque use el
  catálogo: conserva un humo con datos reales por cada una de las seis páginas
  en la suite rápida. `test_replay.py` y `test_replay_links.py` usan una marca
  explícita de módulo, `pytestmark = pytest.mark.slow`.
- Un fichero nuevo que simule no queda marcado automáticamente por usar
  `run_templates`. Añádelo a la selección de `conftest.py` si corresponde al
  mismo criterio, o marca sus tests explícitamente con `@pytest.mark.slow`
  (o `pytestmark` si todo el fichero es lento). Si simula sin esa fixture,
  necesita una marca explícita o incorporarse también a `_SIMULATION_TESTS`
  dentro de un fichero examinado. No basta con añadirlo solo a la lista de
  ficheros.
- Comprueba ambos conjuntos con `pytest --collect-only -m "not slow"` y
  `pytest --collect-only -m slow`, usando el comando de la app desde la raíz.
  Los seis humos deben seguir en el conjunto rápido y las integraciones largas,
  en el lento.

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
