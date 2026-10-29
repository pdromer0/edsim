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
