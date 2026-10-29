# Diario · Hito 1 — Colas y SimPy

Especificación: [docs/specs/hito-1.md](../specs/hito-1.md). El anexo de la especificación tiene el detalle de cada tarea.

## 2026-10-28 · Tarea 1.1 — Dependencias y fórmulas teóricas

**Qué se hizo:** se añadieron simpy, numpy, scipy y matplotlib con `uv add`. Las fórmulas de la M/M/1 están en `src/edsim/queueing/theory.py`, con tests escritos antes, que dan un resultado inmutable y rechazan los parámetros inválidos.

**Qué aprendí:**
- `uv add` añade dependencias de ejecución; `uv add --dev`, las que solo hacen falta para desarrollar.
- Una función pura es el caso más fácil de testear, y sirve de "patrón oro" para validar el simulador.
- Con un agente, escribir los tests primero fija qué es correcto antes de que escriba el código.
- `__init__.py` convierte una carpeta en un subpaquete.
- Los decimales se comparan con tolerancia (`pytest.approx`).
- Si la especificación está en `docs/specs/`, el prompt de cada tarea puede ser corto.
- Rutina tras cada fusión: `git switch main`, `git pull`, `git branch -D <rama>` y `git log --oneline -5`.

**Qué costó o falló:**
- El primer rojo fue `ModuleNotFoundError`: válido para un módulo nuevo, pero poco informativo. Para lógica delicada conviene ver que los tests atrapan una versión mínima incorrecta.

**Preguntas abiertas:** ninguna.

**Enlaces:** PR #5

## 2026-10-28 · Tarea 1.2 — El modelo M/M/1 en SimPy

**Qué se hizo:** `simulate_mm1(lam, mu, horizon, seed)` simula una réplica con dos flujos aleatorios independientes (llegadas y servicio) y devuelve un registro inmutable por cliente. La validación de parámetros es ahora una función compartida, `validate_mm1_rates`.

**Qué aprendí:**
- En SimPy, cada `yield` de un proceso significa "despiértame cuando ocurra esto".
- `simpy.Resource` es el servidor, con su cola.
- `rng.exponential()` recibe la media (1/λ), no la tasa. Confundirlas no da error, da resultados falsos, y con λ = μ = 1 es invisible.
- El modelo solo registra hechos; las métricas se calculan aparte.
- Un invariante como "nadie empieza antes de llegar" se cumple sin más si nunca hay cola; hay que comprobar que la situación ocurre de verdad.
- Antes de romper el código a propósito, hay que predecir qué tests fallarán. Así se aprende qué detecta cada uno.
- `dataclasses.fields`, `inspect.signature` e `inspect.getmembers` responden preguntas sobre el código sin suponer.
- Una simulación corta engaña: en 11 clientes, la media de los servicios salió 1,82 frente a 1.

**Qué costó o falló:** nada.

**Preguntas abiertas:** ninguna.

**Enlaces:** PR #6 · [ADR 0007](../decisiones/0007-un-flujo-aleatorio-por-fuente.md)

## 2026-10-28 · Tarea 1.3 — Métricas y ley de Little

**Qué se hizo:** `mm1_metrics(records, warmup, horizon)` calcula Wq, W, Lq, L, ρ y la tasa observada a partir de los registros, recortando cada intervalo a la ventana de observación. Se probó con un ejemplo calculado a mano y con la ley de Little.

**Qué aprendí:**
- El calentamiento descarta el arranque vacío, que sesga las medias a la baja.
- Wq y W son medias por cliente; Lq, L y ρ son medias en el tiempo (el área bajo una escalera).
- El error más probable es no recortar las estancias a la ventana, y el ejemplo a mano lo detecta.
- Los estados se derivan de los hechos: el número en el sistema es llegados menos salidos.
- Little valida el código aunque no coincida la teoría: λ_obs·W = 4,702 frente a L = 4,703.
- Una réplica es una sola historia. Con un 3,5 % más de utilización, la espera salió un 20 % más alta.

**Qué costó o falló:** nada.

**Preguntas abiertas:** ninguna.

**Enlaces:** PR #7 · [ADR 0016](../decisiones/0016-metricas-derivadas-de-los-registros.md)

## 2026-10-28 · Tarea 1.4 — Réplicas, intervalos de confianza y validación

**Qué se hizo:**
- `summarize` da la media con un intervalo de la t de Student.
- `compare_mm1` ejecuta R réplicas con semillas hijas de una maestra.
- Un test marcado `slow` valida que la teoría cae dentro del intervalo; el hook los omite y el CI los ejecuta.

**Qué aprendí:**
- **Desviación típica y error estándar:** la desviación típica mide cuánto varían las réplicas; el error estándar, cuánto variaría la media. Para dividir el error entre 2 hacen falta cuatro veces más réplicas.
- **El 95 % es una frecuencia:** en 100 experimentos, 96 y 97 intervalos contenían la teoría, y un resultado entre 90 y 99 es normal.
- **La t de Student** ensancha el intervalo cuando hay pocas réplicas.
- **Las métricas de cola fallan juntas,** porque están unidas por Little. Las diez comparaciones equivalen a unas cuatro independientes.
- **Medir la utilización es fácil; medir las esperas cerca de la saturación, no.**
- **Honestidad estadística:** si la validación falla con la semilla fijada, no se cambia la semilla hasta que pase.
- **Hay que comprobar las barandillas:** `--strict-markers` se verificó con una marca mal escrita.

**Qué costó o falló:**
- Con simulaciones cortas (2 000 de duración), todos los fallos de cobertura de Wq quedaron por debajo de la teoría; con 10 000, se repartieron.

**Preguntas abiertas:**
- La causa del sesgo con duración corta no está demostrada. La más probable: los clientes atrapados en una cola larga al final no terminan y quedan fuera de la media, junto con la asimetría de las medias de réplicas cortas.

**Enlaces:** PR #8 · [ADR 0017](../decisiones/0017-tests-estadisticos-marcados-slow.md)

## 2026-10-29 · Tarea 1.5 — CLI `edsim mm1 comparar` y `edsim mm1 barrido`

**Qué se hizo:**
- Dos subcomandos de `argparse`:
  - `comparar` imprime la tabla frente a la teoría;
  - `barrido` escribe un CSV *tidy* y la gráfica de Wq frente a ρ.
- La presentación vive en `report.py`, testeable sin terminal.

**Qué aprendí:**
- Una CLI fina solo lee argumentos, llama a funciones y muestra resultados.
- **El formato *tidy*** tiene una observación por fila y se puede concatenar.
- **Los resultados deben llevar su origen:** el CSV repite los parámetros en cada fila.
- **Gráficas sin pantalla:** crear la figura con `Figure` y `FigureCanvasAgg`, sin `matplotlib.use("Agg")`, evitó un problema en el notebook de la 1.6.
- **Una sola versión de cada cosa:** el test de validación usa `format_comparison` en lugar de su propia tabla.
- **Errores coherentes:** se validan en `argparse` y los internos se convierten con `parser.error`. Así todos dan el código 2 y ninguno deja ficheros a medias.

**Qué costó o falló:**
- El plan no se veía como antes. Cuando Claude presenta un plan formal en modo Plan, la extensión lo abre como documento Markdown en el editor; si solo lo explica en la conversación, aparece en el panel lateral.

**Preguntas abiertas:**
- Cerca de la saturación, las simulaciones cortas tienden a subestimar las esperas. ¿Conviene alargar la duración del barrido a medida que ρ se acerca a 1?

**Enlaces:** PR #9

## 2026-10-29 · Tarea 1.6 — Notebook de exploración de la M/M/1

**Qué se hizo:**
- `notebooks/01_mm1_exploracion.ipynb` tiene una sección de uso y las 11 secciones de la especificación, cada una con explicación, gráfica, preguntas y "Lo que debes recordar".
- Las funciones que necesitaba se añadieron al paquete con tests.
- El CI lo ejecuta en modo rápido, y `nbstripout` lo versiona sin salidas.

**Qué aprendí:**
- El kernel conserva las variables entre celdas, y debe ser el de `.venv`.
- **Estado oculto:** un notebook ejecutado en cualquier orden puede funcionar solo en tu sesión. La defensa es *Restart & Run All*, y `nbmake` lo hace en el CI.
- `nbstripout` deja en git solo el código y el texto, con diffs legibles.
- Una variable de entorno y una única celda de parámetros bastan para un modo rápido.
- **Un notebook didáctico empuja a mejorar el paquete:** la escalera de ocupación y el análisis de tiempos servirán en hitos posteriores.
- Ruff también revisa los notebooks.

**Qué costó o falló:**
- **El modo normal tardó 288 s,** más de lo estimado y cerca del límite de 300 s de `nbmake`. Solución: ejecutarlo con `--nbmake-timeout=600`.
- **`nbstripout` canceló el primer commit** al quitar las salidas. Hay que repetir `git add` y el commit.
- **Los comandos estaban en líneas separadas,** así que el `push` y el `gh pr create` se ejecutaron aunque el commit había fallado ("No commits between main and…"). Solución: encadenarlos con `&&`.

**Preguntas abiertas:** ninguna.

**Enlaces:** PR #10 · [ADR 0018](../decisiones/0018-notebooks-jupyter-sin-logica.md)

## Reflexiones de Pedro
