# 0047. Tests por niveles según el punto del ciclo

- **Estado:** Aceptada
- **Fecha:** 2026-11-07

## Contexto

Con 3.000 tests en cinco suites, la espera en tests rondaba las 3 horas por tarea. El hook `Stop` ejecutaba la rápida completa del núcleo (unos 6 minutos) al final de cada turno, también en modo plan y aunque nada hubiera cambiado, y cada commit repetía la rápida. Pero con *squash and merge* solo llega a `main` el árbol final del PR, que ya pasa la suite completa en local y el CI ([diseño, «Calidad y tests (QA)»](../diseno.md#calidad-y-tests-qa) y [diario de proceso, tarea P.1](../diario/proceso.md)).

## Decisión

Cada punto del ciclo ejecuta el nivel más bajo que le basta, de **N0** a **N3**:

- **N0**, ruff: al editar un `.py` (hook `PostToolUse`) y en pre-commit.
- **N1**, los ficheros de test del área tocada: antes de cada commit y al probar una versión incorrecta.
- **N2**, la rápida con sello: en el hook `Stop` (`scripts/tests-rapidos.sh`), solo de las suites que afectan los cambios desde su último verde, y nada en modo plan. El sello es el manifiesto de huellas del árbol en el último verde de cada suite, en `.cache/edsim/`, fuera de `.git`.
- **N3**, todo: antes de cada push, `scripts/tests-completos.sh` (lint, formato, núcleo completo, app completa y notebooks), y el CI en cada push.

pytest-xdist solo en el núcleo y en local (`loadfile` en la rápida, `worksteal` en la completa); la app y el CI van en serie. xdist se adopta en una suite solo si en paralelo tarda como mucho el 60 % de la serie y da los mismos resultados test a test, un criterio fijado antes de medir.

Matiza la [ADR 0017](0017-tests-estadisticos-marcados-slow.md): los tests `slow` siguen marcados, pero ya no es el hook el que los omite cada turno. El `Stop` ejecuta la rápida solo cuando hace falta, y los `slow` corren antes de cada push y en el CI.

Motivo: con *squash and merge* solo llega a `main` el árbol final, que pasa N3 y el CI; la espera en tests rondaba las 3 h por tarea y queda por debajo de 50 min.

## Alternativas consideradas

- La rápida completa antes de cada commit y en cada `Stop`: unos 70 minutos por tarea solo en commits, para comprobar árboles intermedios que desaparecen al fusionar.
- xdist en el CI: en el runner (4 CPU), el núcleo completo tardó 463 s en serie, 470 s con `worksteal` y 382 s con `loadfile`; ninguno llega al 60 % de la serie.
- xdist en la app: en paralelo no baja del 87 % de la serie, y con la CPU ocupada algunos `AppTest` superan su límite de 3 s por página.
- `--dist loadgroup`: no agrupa con pytest 9.2 ([pytest-xdist #1386](https://github.com/pytest-dev/pytest-xdist/issues/1386)).
- Un sello con `git hash-object -w`: escribe objetos en `.git`, que es de solo lectura en el sandbox de Codex. El sello usa `sha1sum`, que solo lee.

## Consecuencias

- En el portátil de Pedro (PR #52, `main` en `462d0d1`), la rápida del núcleo baja de unos 6 min en serie a 3 min 05 s, la completa de 15 min 27 s a 9 min 00 s y la comprobación antes del push, de 18 min 46 s a 12 min 32 s. La espera estimada por tarea baja de unas 3 h a menos de 50 min, sobre todo por no ejecutar nada cuando no hace falta.
- No se pierde calidad: el árbol que llega a `main` pasa N3 en local y el CI completo en una máquina limpia; el sello solo se escribe en verde y compara contenidos, no commits.
- Lo único que deja de comprobarse uno a uno son los commits intermedios del PR, que desaparecen al fusionar.
- Pendiente (fase 2): límite configurable de `AppTest`, revisar la marca `slow` de los 40 tests rápidos de más de 2 s, `timeout-minutes` en el CI, repartir los `slow` en jobs aparte y N1 automático con `pytest-testmon`.
