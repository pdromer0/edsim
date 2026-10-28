# EDsim

Simulador de urgencias hospitalarias que genera datos sintéticos para un laboratorio de analítica.

- Diseño: [docs/diseno.md](docs/diseno.md)
- Hito en curso: [docs/specs/hito-0.md](docs/specs/hito-0.md)

## Modo de trabajo

Ciclo completo en [docs/diseno.md](docs/diseno.md), sección "Metodología de trabajo con Claude Code y Cursor".

- Explica el concepto antes de implementar; Pedro pregunta hasta entenderlo.
- Usa modo plan para cualquier cambio no trivial y espera la aprobación.
- Trabaja en pasos pequeños.
- En la revisión, explica cada decisión del diff.

## Comandos

```bash
uv sync                  # entorno y dependencias (uv.lock)
uv run pytest            # todos los tests (incluidos los slow, como el CI)
uv run pytest -m "not slow"  # solo los rápidos (lo que ejecuta el hook Stop)
uv run ruff check .      # lint
uv run ruff format .     # formato
uv run edsim             # CLI
```

## Convenciones

- Código, nombres y docstrings en inglés.
- Documentación, especificaciones y mensajes de commit en español.
- Claves de los YAML de configuración en español, como en el diseño.
- Commits con prefijo `feat`, `fix`, `docs`, `test`, `chore` o `ci`, p. ej. `feat(sim): cola M/M/1 con SimPy`.
- Decisiones importantes como ADR en [docs/decisiones/](docs/decisiones/README.md); aprendizaje en [docs/diario/](docs/diario/README.md).

## Reglas de git

- Nunca trabajes en `main`: cada tarea va en su rama y entra por pull request.
- Nunca subas (`git push`) sin permiso explícito.
- Nunca fusiones pull requests: la fusión es de Pedro.
- En los hitos 0 y 1, Pedro ejecuta a mano los comandos de git y GitHub; tú indicas cuáles.
