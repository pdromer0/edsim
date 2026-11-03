Si la tarea toca `app/`, lee también `app/AGENTS.md` (se creará en la tarea A.1).

# EDsim

Simulador de urgencias hospitalarias que genera datos sintéticos para un laboratorio de analítica.

- Diseño: [docs/diseno.md](docs/diseno.md)
- Hito en curso: [docs/specs/hito-3.md](docs/specs/hito-3.md)

## Modo de trabajo

Ciclo completo en [docs/diseno.md](docs/diseno.md), sección "Metodología de trabajo con Claude Code y Cursor".

- Explica en español el concepto antes de implementar; Pedro pregunta hasta entenderlo.
- Usa modo plan para cualquier cambio no trivial y espera la aprobación del plan.
- Con el plan aprobado, implementa la tarea completa sin esperar revisión entre pasos: un commit
  por paso lógico, con ruff y `pytest -m "not slow"` en verde antes de cada commit.
- Para y pregunta solo si algo contradice el plan o la especificación, una biblioteca no se
  comporta como se esperaba, un test falla sin causa clara o hace falta una decisión de diseño
  nueva. Nunca cambies una semilla para que un test pase.
- Pedro revisa el PR completo: su descripción explica cada decisión del diff, lo que cambió
  respecto al plan, las comprobaciones, las medidas y las versiones incorrectas.
- No arranques procesos que no terminan, como servidores (`streamlit run`, `uv run edsim-app`): las páginas de la app se prueban con `AppTest` y Pedro las revisa en el navegador.
- Si cambias dependencias en `pyproject.toml`, `uv sync` necesita red: pide permiso antes de ejecutarlo.

## Comandos

```bash
uv sync                  # entorno y dependencias (uv.lock)
uv run pytest            # todos los tests (incluidos los slow, como el CI)
uv run pytest -m "not slow"  # solo los rápidos
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

Flujo de cada tarea (desde el hito 2, el agente ejecuta git):

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
- Código nuevo sin tests.
- Romper la convención de idiomas: código, nombres y docstrings en inglés; documentación, commits y textos de la interfaz en español.
