# EDsim

Simulador de urgencias hospitalarias que genera datos sintéticos para un laboratorio de analítica.

- Diseño: [docs/diseno.md](docs/diseno.md)
- Hito en curso: [docs/specs/hito-3.md](docs/specs/hito-3.md)

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
EDSIM_NB_RAPIDO=1 uv run pytest --nbmake notebooks/  # notebooks en modo rápido (como el CI)
uv run pytest --nbmake --nbmake-timeout=600 notebooks/  # notebooks en modo normal
```

Los notebooks de `notebooks/` se abren en Cursor con el kernel de `.venv`. Se versionan sin resultados: el hook `nbstripout` de pre-commit los borra.

`--nbmake-timeout` (300 s por defecto) es un límite **por celda**, no por notebook: nbmake lo pasa a `nbclient`, que lo aplica a cada celda. El límite que importa es el de la celda más larga; el de 600 s deja margen en máquinas lentas.

## Convenciones

- Código, nombres y docstrings en inglés.
- Documentación, especificaciones y mensajes de commit en español.
- Claves de los ficheros de configuración (TOML) en español, como en el diseño.
- Commits con prefijo `feat`, `fix`, `docs`, `test`, `chore` o `ci`, p. ej. `feat(sim): cola M/M/1 con SimPy`.
- Decisiones importantes como ADR en [docs/decisiones/](docs/decisiones/README.md); aprendizaje en [docs/diario/](docs/diario/README.md).

## Reglas de git

- Nunca trabajes en `main`: cada tarea va en su rama y entra por pull request.
- Nunca subas (`git push`) sin permiso explícito.
- Nunca fusiones pull requests: la fusión es de Pedro.

Flujo de cada tarea (desde el hito 2, Claude Code ejecuta git):

1. Actualiza `main` (`git switch main && git pull`) y crea la rama de la tarea (`git switch -c <rama>`).
2. Haz los commits en la rama.
3. Pide permiso a Pedro y haz `git push -u origin <rama>`.
4. Abre el pull request con `gh pr create`.
5. Pedro revisa y fusiona siempre.

Encadena con `&&` los pasos que dependen del anterior, para que ninguno se ejecute si el previo falla.
