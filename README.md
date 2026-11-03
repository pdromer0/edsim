# EDsim

Simulador de urgencias hospitalarias que genera datos sintéticos realistas, en tiempo real y por lotes, para un laboratorio de analítica: ingeniería de datos, modelos predictivos y análisis de escenarios.

El proyecto se construye paso a paso, por hitos, con un doble objetivo: obtener el sistema y aprender sus fundamentos.

## Requisitos

- [uv](https://docs.astral.sh/uv/getting-started/installation/). Instala Python 3.13 automáticamente según `.python-version`.
- git

## Preparar el entorno

```bash
uv sync                      # crea .venv con el paquete y las herramientas de desarrollo
uv run pre-commit install    # activa los hooks de pre-commit (una vez)
```

## Comandos principales

```bash
uv run edsim --version       # CLI
uv run edsim mm1 comparar    # M/M/1: tabla de teoría frente a simulación
uv run edsim mm1 barrido     # M/M/1: CSV y gráfica de Wq frente a ρ en resultados/mm1/
uv run edsim llegadas generar  # llegadas: dos CSV en resultados/llegadas/
uv run edsim llegadas validar  # llegadas: cinco pruebas y tres gráficas
uv run edsim motor simular   # motor: log JSONL, ground truth y resumen en resultados/ejecuciones/<run_id>/
uv run edsim motor validar   # motor: tabla de validación y cuatro gráficas (unos 90 s)
uv run pytest                # tests
uv run ruff check .          # lint
uv run ruff format .         # formato
uv run pre-commit run --all-files
```

## Flujo de trabajo

GitHub Flow: cada tarea en una rama corta que entra en `main` por pull request, con el CI (lint, formato y tests) en verde.

## Documentación

- [Documento de diseño](docs/diseno.md)
- [Especificaciones por hito](docs/specs/)
- [Registro de decisiones (ADR)](docs/decisiones/README.md)
- [Diario de aprendizaje](docs/diario/README.md)
- [CLAUDE.md](CLAUDE.md): instrucciones para Claude Code

### Ejecuciones del motor

`edsim motor simular` guarda por defecto en `resultados/ejecuciones/<run_id>/`
(por ejemplo, `r2026` con la semilla predeterminada). La carpeta contiene el log,
los dos CSV de ground truth, copias exactas de `centro.toml` y `llegadas.toml`,
y los metadatos versionados de `run.json`. La CLI y la app comparten el servicio
público `edsim.runs.simulate_run` para escribir este formato de forma atómica.

Una ejecución guardada no se sobrescribe: elige otro `--run-id` o una carpeta
inexistente con `--salida`. El identificador admite de 1 a 64 letras ASCII,
cifras, puntos, guiones y guiones bajos, empezando por letra o cifra.
Las violaciones de invariantes se guardan para diagnóstico y dan código de salida 1.
Los errores de uso, incluido un destino ocupado, dan código 2.

Para reproducir el log de una ejecución, usa sus copias con `--centro` y
`--llegadas`, los mismos días, calentamiento, semilla y `--run-id` registrados en
`run.json`, y un destino nuevo. Las rutas de procedencia de los CSV cambiarán
si cambian las cadenas de ruta de entrada; el log seguirá siendo idéntico.
