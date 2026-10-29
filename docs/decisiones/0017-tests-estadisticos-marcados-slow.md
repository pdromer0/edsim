# 0017. Tests estadísticos marcados como `slow`

- **Estado:** Aceptada
- **Fecha:** 2026-10-28

## Contexto

La validación frente a la teoría tarda más que el resto de los tests: ejecuta réplicas largas y comprueba que la teoría cae dentro de los intervalos de confianza. Medido en la tarea 1.4, el test lento tarda unos 2,4 s.

El hook `Stop` de Claude Code ejecuta los tests al terminar cada turno ([especificación](../specs/hito-1.md#tests)).

## Decisión

Los tests estadísticos llevan la marca `slow`. El hook de Claude Code los omite con `pytest -m "not slow"`, y el CI los ejecuta todos.

Motivo: un ciclo de trabajo rápido sin renunciar a la validación estadística.

## Alternativas consideradas

No se documentaron alternativas.

## Consecuencias

- La marca está registrada en `pyproject.toml` con `--strict-markers`. Se comprobó con una marca mal escrita a propósito: sin esa opción, un error de tecleo convertiría en silencio un test lento en rápido.
- [CLAUDE.md](../../CLAUDE.md) recoge los dos comandos: `uv run pytest`, con todos los tests, y `uv run pytest -m "not slow"`, con los rápidos.
