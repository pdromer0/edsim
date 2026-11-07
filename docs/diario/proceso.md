# Diario · Proceso

Tareas de proceso (serie P): cómo trabajamos, no qué hace el simulador. No pertenecen a ningún hito.

## 2026-11-07 · Tarea P.1 — Tests por niveles

**Qué se hizo:** los tests pasan a ir por niveles:
- antes de cada commit, los ficheros del área tocada;
- en el Stop, `scripts/tests-rapidos.sh`: la rápida con sello, solo de las suites que afectan los cambios desde su último verde;
- antes del push, `scripts/tests-completos.sh`.

El núcleo se ejecuta en paralelo con pytest-xdist en los scripts y en el CI. El notebook tiene su propio job.

**Qué aprendí:**
- El sello es el manifiesto de huellas de los ficheros en el último verde, no un commit. Lo que cuenta es el contenido del árbol: un commit no obliga a repetir los tests, y volver al árbol del último verde de una suite no la ejecuta.
- Un fichero seguido y borrado se detecta sin código especial. `git ls-files` lo sigue listando, `sha1sum` no lo encuentra y queda fuera del manifiesto: cuenta como cambio.
- `git hash-object -w` escribe objetos en `.git` y además refresca la fecha de los que ya existen. Por eso el sello usa `sha1sum`: el `.git` de Codex es de solo lectura, y `git status --porcelain` no lo habría delatado.
- Cada worker de xdist es un proceso propio: recalcula los fixtures de sesión y de módulo.
  - `loadfile` deja cada fichero en un worker. Gana en la rápida y pierde en la completa, porque ahí el fichero más largo (`test_calibrated_center.py`) marca el tiempo.
  - `worksteal` reparte los tests y roba trabajo al worker que va más cargado. Gana en la completa.
- Este portátil (i7-1255U: 2 núcleos de rendimiento y 8 de eficiencia, 15 W) rinde unas 2,6× con 6 procesos y 3,3× con 12. Con 12 workers se agota la memoria y aparece el swap. Cada test tarda en paralelo unas 2,6 veces lo que tarda solo.

**Medidas (tiempo de pared, main en 462d0d1):**

| Suite | Serie | Paralelo (6 workers) |
|---|---|---|
| Rápida del núcleo | 5 min 35 s – 6 min 05 s | 3 min 05 s (`loadfile`) |
| Completa del núcleo | 15 min 27 s | 9 min 00 s (`worksteal`) |
| App | 2 min 19 s – 2 min 33 s | en serie |
| Antes del push (completa, app y notebooks) | 18 min 46 s | 12 min 32 s (`tests-completos.sh`) |

**Qué costó o falló:**
- La misma configuración tardó entre 200 y 283 s en dos ejecuciones. Se repitieron las medidas intercalando configuraciones, y también la serie.
- Con xdist, 4 `AppTest` superaron el límite de 3 s por página en una de dos ejecuciones. No es estado compartido: es la CPU ocupada. La app queda en serie hasta que ese límite se pueda configurar.
- Al comparar ids, `cut -d' '` partía los ids parametrizados con espacios, y parecía que la recolección y la ejecución no coincidían.
- Un caso del clon dejó un fichero borrado dentro de un `git commit -a`, y el caso siguiente no tenía nada que borrar.

**Preguntas abiertas:**
- Los tiempos orientativos (rápida ≤ 1 min 30 s y N3 ≤ 7 min) no se alcanzan en este portátil. Habrá que ver los del CI y, después, revisar las marcas `slow` de los 40 tests rápidos de más de 2 s.
- `--dist loadgroup` no agrupa con pytest 9.2 (pytest-xdist#1386): revisarlo cuando xdist publique una versión que lo arregle.

**Enlaces:** PR #52 · decisión candidata 47 (ADR en la 4.9) · [pytest-xdist: distribución](https://pytest-xdist.readthedocs.io/en/stable/distribution.html)
