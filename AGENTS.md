Si la tarea toca `app/`, lee también `app/AGENTS.md`.

# EDsim

Simulador de urgencias hospitalarias que genera datos sintéticos para un laboratorio de analítica.

- Diseño: [docs/diseno.md](docs/diseno.md)
- Hito en curso: hito 5 (abandono, boarding y destinos) — [docs/specs/hito-5.md](docs/specs/hito-5.md)
- Último hito cerrado: [docs/specs/hito-6.md](docs/specs/hito-6.md) (tiempo real, `v0.6-hito6`); antes, [docs/specs/hito-4.md](docs/specs/hito-4.md) (perfiles clínicos, `v0.4-hito4`)
- App: vigente, [app/docs/specs/incrementos.md](app/docs/specs/incrementos.md); la fase 1 ([app/docs/specs/fase-1.md](app/docs/specs/fase-1.md)) está cerrada (`app-v0.1.0`)

## Modo de trabajo

Ciclo completo en [docs/diseno.md](docs/diseno.md), sección "Metodología de trabajo con Claude Code y Cursor".

- Explica en español el concepto antes de implementar; Pedro pregunta hasta entenderlo.
- Usa modo plan para cualquier cambio no trivial y espera la aprobación del plan.
- Con el plan aprobado, implementa la tarea completa sin esperar revisión entre pasos: un commit
  por paso lógico. Los tests van por niveles:
  - antes de cada commit, ruff y los ficheros de test del área tocada
    (`uv run pytest tests/test_x.py …`). No se ejecutan la rápida completa ni la completa en
    cada commit;
  - al final de cada turno, el hook Stop ejecuta la rápida con sello (`scripts/tests-rapidos.sh`),
    solo de las suites que afectan los cambios desde su último verde;
  - antes de cada push, `scripts/tests-completos.sh` una vez.

  Una versión incorrecta se comprueba con los ficheros donde se predice el fallo y con los que
  deben seguir pasando.
- Para y pregunta solo si algo contradice el plan o la especificación, una biblioteca no se
  comporta como se esperaba, un test falla sin causa clara o hace falta una decisión de diseño
  nueva. Nunca cambies una semilla para que un test pase.
- Pedro revisa el PR completo: su descripción explica cada decisión del diff, lo que cambió
  respecto al plan, las comprobaciones, las medidas y las versiones incorrectas.
- No arranques procesos que no terminan, como servidores (`streamlit run`, `uv run edsim-app`): las páginas de la app se prueban con `AppTest` y Pedro las revisa en el navegador.
- Si cambias dependencias en `pyproject.toml`, `uv sync` necesita red: pide permiso antes de ejecutarlo.
- El repositorio es la fuente de verdad: diseño, especificaciones, anexos y diario se cambian en el
  repositorio, en el mismo PR que el código. Las pestañas del documento online son un archivo y no
  se editan.

## Comandos

```bash
uv sync --all-packages    # entorno completo del workspace (uv.lock)
uv sync --all-packages --extra kafka  # el anterior más el cliente de Kafka
uv run pytest            # tests del núcleo, incluidos los slow (como el CI)
uv run pytest -m "not slow"  # tests rápidos del núcleo
uv run --package edsim-app pytest app/tests  # tests de la app
uv run --package edsim-app pytest app/tests -m "not slow"  # tests rápidos de la app
uv run ruff check .      # lint
uv run ruff format .     # formato
uv run edsim             # CLI
scripts/tests-rapidos.sh    # rápida con sello: solo las suites con cambios desde su último verde
scripts/tests-completos.sh  # antes del push: lint, formato, completa, app y notebooks rápidos
scripts/tests-integracion.sh  # contra Kafka real: levanta compose.yaml si hace falta
uv run python -m edsim.live.schemas  # regenera schemas/eventos-v*.schema.json (tras cambiar el catálogo)
uv run edsim directo preparar    # crea los topics de Kafka (Kafka levantado)
uv run edsim directo lanzar --memoria --velocidad max --dias 3  # un directo sin Kafka, de golpe
uv run edsim directo lanzar --registro-kafka FICHERO  # guarda lo que escribe librdkafka (sin la opción, solo su recuento al final)
EDSIM_NB_RAPIDO=1 uv run pytest --nbmake notebooks/06_tiempo_real.ipynb  # el notebook 06 sin Kafka
uv run --package edsim-app edsim-app  # app local: Pedro la arranca para revisión manual
EDSIM_NB_RAPIDO=1 uv run pytest --nbmake notebooks/  # notebooks en modo rápido (como el CI)
uv run pytest --nbmake --nbmake-timeout=600 notebooks/  # notebooks en modo normal
```

Un `uv sync` simple sincroniza solo el núcleo y desinstala la app y sus dependencias
exclusivas. Usa `uv sync --all-packages` para el trabajo habitual. El arranque con
`--package edsim-app` instala lo que falte. El CI del núcleo usa `uv sync --locked`
para comprobarlo sin Streamlit ni pandas; el de la app añade `--all-packages`.

Los hooks Stop de Claude Code y de Codex llaman a `scripts/tests-rapidos.sh`, que ejecuta la
rápida del núcleo, de la app o de las dos según las rutas cambiadas desde el último verde de cada
una; el sello vive en `.cache/edsim/`, fuera de `.git`. El de Codex formatea antes con
`ruff format .`; el de Claude Code no ejecuta nada en modo plan. pytest-xdist no va en `addopts`:
`uv run pytest tests/test_x.py` sigue en serie, y solo los scripts piden `-n`. El CI va en serie:
en el runner, xdist no llega al 60 % de la serie.

Los notebooks de `notebooks/` se abren en Cursor con el kernel de `.venv`. El 06 con Kafka necesita el broker (`docker compose up --wait` y `edsim directo preparar`) y el extra en `.venv` (`uv sync --all-packages --extra kafka`); en modo rápido, nada de eso. Se versionan sin resultados: el hook `nbstripout` de pre-commit los borra.

`--nbmake-timeout` (300 s por defecto) es un límite **por celda**, no por notebook: nbmake lo pasa a `nbclient`, que lo aplica a cada celda. El límite que importa es el de la celda más larga; el de 600 s deja margen en máquinas lentas.

## Convenciones

- Código, nombres y docstrings del paquete en inglés: `src/` y `app/src/`.
- Tests, cada zona con su práctica ([ADR 0015](docs/decisiones/0015-idiomas-del-proyecto.md)): los del núcleo (`tests/`) llevan nombres de los tests (`test_…`), docstrings y comentarios en español, como material de aprendizaje; las funciones auxiliares y las fixtures pueden ir en inglés, como los identificadores del paquete que usan. Los de la app (`app/tests/`), en inglés, como el código de la app. Los identificadores que un test importa del paquete siguen en inglés.
- Documentación, especificaciones y mensajes de commit en español.
- Claves de los ficheros de configuración (TOML) en español, como en el diseño.
- Commits con prefijo `feat`, `fix`, `refactor`, `docs`, `test`, `chore` o `ci`, p. ej. `feat(sim): cola M/M/1 con SimPy`.
- Decisiones importantes como ADR en [docs/decisiones/](docs/decisiones/README.md); aprendizaje en [docs/diario/](docs/diario/README.md).

## Reglas de git

- Nunca trabajes en `main`: cada tarea va en su rama y entra por pull request.
- Nunca subas (`git push`) sin permiso explícito.
- Nunca fusiones pull requests: la fusión es de Pedro.

Flujo de cada tarea (el agente ejecuta git):

1. Actualiza `main` (`git switch main && git pull`) y crea la rama de la tarea (`git switch -c <rama>`).
2. Haz los commits en la rama, uno por paso lógico, sin esperar revisión entre ellos.
3. Pide permiso a Pedro y haz `git push -u origin <rama>`.
4. Abre el pull request con `gh pr create`.
5. Pedro revisa y fusiona siempre.

Encadena con `&&` los pasos que dependen del anterior, para que ninguno se ejecute si el previo falla.

## Review guidelines

En las revisiones de pull requests, trata como P1:

- Cambiar una semilla o una tolerancia para que un test pase sin analizar la causa.
- Que el paquete `edsim` importe `streamlit`, `pandas` o `edsim_app`.
- Lógica en la CLI, en los notebooks o en la app que debería vivir en el paquete, con tests.
- Tests que pasan de forma vacía, sin comprobar que la situación que prueban ocurre de verdad.
- Código nuevo sin tests en el paquete `edsim` o en la app. Los scripts de herramientas de desarrollo (hooks de `.claude/` y `.codex/`) se verifican a mano y se documenta la comprobación en el PR.
- Romper la convención de idiomas, es decir, usar en una zona el idioma de la otra: código, nombres y docstrings del paquete (`src/`, `app/src/`) y tests de la app (`app/tests/`) en inglés; tests del núcleo (`tests/`: nombres de los tests (`test_…`), docstrings y comentarios; las funciones auxiliares y las fixtures pueden ir en inglés, como los identificadores del paquete que usan), documentación, commits y textos de la interfaz en español. Un test del núcleo en español cumple la convención.
- Que la app importe algo privado del núcleo o fuera de `__all__` de `edsim.runs`.
- Que una ejecución se escriba en `resultados/ejecuciones/` sin pasar por `simulate_run`.
