# Diario · Proceso

Tareas de proceso (serie P): cómo trabajamos, no qué hace el simulador. No pertenecen a ningún hito.

## 2026-11-07 · Tarea P.1 — Tests por niveles

**Qué se hizo:** los tests pasan a ir por niveles:
- antes de cada commit, los ficheros del área tocada;
- en el Stop, `scripts/tests-rapidos.sh`: la rápida con sello, solo de las suites que afectan los cambios desde su último verde;
- antes del push, `scripts/tests-completos.sh`.

El núcleo se ejecuta en paralelo con pytest-xdist en los scripts locales; en el CI sigue en serie. El notebook tiene su propio job.

**Qué aprendí:**
- El sello es el manifiesto de huellas de los ficheros en el último verde, no un commit. Lo que cuenta es el contenido del árbol: un commit no obliga a repetir los tests, y volver al árbol del último verde de una suite no la ejecuta.
- Un fichero seguido y borrado se detecta sin código especial. `git ls-files` lo sigue listando, `sha1sum` no lo encuentra y queda fuera del manifiesto: cuenta como cambio.
- `git hash-object -w` escribe objetos en `.git` y además refresca la fecha de los que ya existen. Por eso el sello usa `sha1sum`: el `.git` de Codex es de solo lectura, y `git status --porcelain` no lo habría delatado.
- Cada worker de xdist es un proceso propio: recalcula los fixtures de sesión y de módulo.
  - `loadfile` deja cada fichero en un worker. Gana en la rápida y pierde en la completa, porque ahí el fichero más largo (`test_calibrated_center.py`) marca el tiempo.
  - `worksteal` reparte los tests y roba trabajo al worker que va más cargado. Gana en la completa.
- Este portátil (i7-1255U: 2 núcleos de rendimiento y 8 de eficiencia, 15 W) rinde unas 2,6× con 6 procesos y 3,3× con 12. Con 12 workers se agota la memoria y aparece el swap. Cada test tarda en paralelo unas 2,6 veces lo que tarda solo.
- En el runner del CI (4 workers), el núcleo completo tardó 463 s en serie, 470 s con `worksteal` y 382 s con `loadfile`. Ninguno llega al 60 % de la serie, así que el CI sigue en serie: con pocos workers, recalcular los fixtures caros en cada uno se come la ganancia.
- Las máquinas del runner no son iguales: la misma completa en serie tardó entre 463 y 933 s, y el notebook del mismo job varió en la misma proporción. Comparar dos ejecuciones distintas del CI tiene un margen de hasta un factor 2; una comparación limpia mide las dos variantes en el mismo job.

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

## 2026-11-11 · Tarea P.2 — Flujo profesional

**Qué se hizo:** el trabajo pasa a un flujo con papeles, issues y skills ([anexo](../proceso/p2.md), [ADR 0080 a 0082](../decisiones/README.md)):
- la documentación vive en el repositorio y el documento online queda como archivo (A1);
- las instrucciones de los agentes dejan de contradecirse y los hooks sin `jq` salen con código 1 (A2);
- GitHub gestiona el trabajo: un issue por tarea, etiquetas, milestones, tablero «EDsim» y dependencias nativas (A3);
- el ciclo de cada tarea se escribe una vez en `docs/proceso/tarea.md` y lo ejecutan `/tarea-edsim` y `/sincronizar` (A4);
- el método se puede llevar a otro proyecto: `docs/proceso/portabilidad.md` (T1);
- reglas `ask` sobre `config/` y `tests/data/`, hook `SessionStart` y aviso del `Stop`, con la prueba de humo del flujo (A5);
- lecciones, ADR, diario y la P.3 en QA (A6).

**Qué aprendí:**
- Antes de mover documentación, se compara. El diff normalizado (sin firma, cabecera, diagramas ni escapes) convierte «creo que está todo» en «está todo»: faltaban en el repositorio el anexo del hito 0, el de la 6.6 y el cierre del hito 6, y el hito 5 solo existía online.
- Los ficheros grandes los escribe un script, no la salida del modelo. La API se cortó a los 16 minutos, probablemente porque el modelo reescribía los 92 KB del hito 5.
- Una regla nueva que relaja otra antigua nombra la excepción en los dos sitios. `/doctor prompt-audit` encontró seis hallazgos que se habían acumulado sin que nadie los viera.
- Las automatizaciones de GitHub compiten con los scripts: el añadido automático de fichas llegó antes que `gh project item-add` («Content already exists»). Lo robusto es comprobar el estado y actuar solo si falta.
- Un dato del plan puede perderse al ejecutarlo: el #66 perdió su dependencia del #64 al crear el issue. La prueba en seco antes del primer uso real lo destapó.
- Números con el mismo formato se confunden: los issues #63 a #94 se solapan con las decisiones 67 a 79. Las decisiones se citan «decisión 69 (H5-3)», sin almohadilla.
- Lo que vale más allá de una sesión no se pasa como argumento de la skill: va al issue, en el cuerpo o como comentario «Notas del chat».
- El valor esperado de un test se calcula aparte de la función probada, y el cálculo se escribe en el plan.

**Medidas:**

| Pieza | Valor |
|---|---|
| Etiquetas / milestones | 16 (tres grupos con prefijo y `critica`) / 4 |
| Issues creados | 32 (#63 a #94) |
| Dependencias nativas | 15, en 9 issues |
| `session-start.sh` | 35 ms, sin llamadas de red |
| Entradas del anexo de la P.2 | 7 (A1 a A6 y T1) |

**Qué costó o falló:**
- Dos cortes de la API en la A1: el primero al reescribir el hito 5, el segundo por la conexión de la terminal.
- El comprobador de dependencias de la prueba en seco marcó el #66, que había perdido una.
- `docker compose ps` falla en este WSL porque no hay integración con Docker Desktop.
- La skill no decía cómo presentar el plan si la sesión no está en modo plan: hizo falta una segunda ronda.

**Preguntas abiertas:**
- Las comprobaciones en vivo de Pedro: las cuatro pruebas de `ask`, `SessionStart` en una sesión nueva y el texto del `Stop` mientras se ejecuta.
- El plugin LSP de Python (pyright) y Remote Control quedan pendientes en `portabilidad.md`.
- Qué subagentes, `@claude`, Codex desde el issue y la sesión en la nube dan de verdad: se prueban en las tareas 5.2 a 5.8, una por tarea.

**Enlaces:** PR #62, #95 y #96 · ADR 0080 a 0082 · [lecciones transversales](../proceso/lecciones.md)
