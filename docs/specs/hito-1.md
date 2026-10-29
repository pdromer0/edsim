# Hito 1 — Colas y SimPy

## Objetivo y alcance

Al terminar el hito 1, EDsim contiene un modelo M/M/1 en SimPy, reproducible por semilla, que mide esperas, ocupación y número en cola. Un experimento con réplicas demuestra, con intervalos de confianza, que sus resultados coinciden con la teoría de colas. Es el primer paso del criterio de salida de la fase de fundamentos: "M/M/1 cuadra con la teoría".

**Dentro del alcance**

- Dependencias: SimPy, NumPy, SciPy y Matplotlib.
- Fórmulas teóricas de la M/M/1.
- Modelo M/M/1 en SimPy con flujos aleatorios independientes y semilla.
- Métricas por cliente (Wq, W) y promediadas en el tiempo (Lq, L, ρ), y comprobación de la ley de Little.
- Réplicas con calentamiento e intervalos de confianza al 95 %.
- CLI para comparar con la teoría y para barrer la utilización, con tabla, CSV y gráfica.
- Tests de fórmulas, reproducibilidad, invariantes, ley de Little y validación estadística, y un notebook de exploración en Jupyter.

**Fuera del alcance**

- Llegadas que varían con la hora del día (hito 2).
- Pacientes, triaje, prioridades y log de eventos (hito 3).
- Otros notebooks (en este hito solo el de exploración de la M/M/1).

Es el último hito en el que Pedro ejecuta a mano los comandos de git; desde el hito 2 los ejecuta Claude Code.

## Sesión conceptual

Los conceptos se explicaron en la conversación de arranque del hito. Esta tabla es el resumen de referencia.

| Concepto | Qué hay que entender |
| --- | --- |
| Simulación de eventos discretos | El estado solo cambia en instantes concretos; el reloj salta de un evento al siguiente usando una lista de eventos futuros |
| Anatomía de una cola | Llegadas, servicio, servidores y disciplina; notación de Kendall: M/M/1 = llegadas Poisson, servicio exponencial, un servidor |
| Poisson y exponencial | Llegadas independientes con tasa λ; tiempos entre llegadas exponenciales de media 1/λ; la exponencial no tiene memoria |
| Utilización y estabilidad | ρ = λ/μ debe ser menor que 1; la espera crece como 1/(1 − ρ) y se dispara cerca del 100 % |
| Fórmulas de la M/M/1 | Wq = ρ/(μ − λ), W = 1/(μ − λ), Lq = ρ²/(1 − ρ), L = ρ/(1 − ρ) |
| Ley de Little | L = λ·W en cualquier sistema estable, sea cual sea la distribución |
| SimPy | `Environment`, procesos como funciones generadoras, `timeout`, `Resource` con `request`, `run` |
| Medias por cliente y medias en el tiempo | Wq y W promedian sobre clientes; Lq, L y ρ promedian sobre el tiempo (área bajo la curva entre duración) |
| Calentamiento, réplicas e IC | Descartar el arranque vacío; repetir con semillas distintas; intervalo de confianza con la t de Student |
| Semillas y flujos | La misma semilla reproduce exactamente el resultado; un flujo aleatorio por fuente de azar |

## Cómo encajan las piezas

La semilla genera flujos aleatorios independientes; el modelo los consume y deja registros, de los que salen las métricas; las réplicas producen intervalos de confianza que se comparan con las fórmulas.

&#91;embedded content: flujo del hito 1 · de la semilla a la comparación\]

## Diseño del modelo M/M/1

El modelo es deliberadamente mínimo, pero ya sigue los principios del diseño de EDsim: las esperas no se muestrean, emergen de la cola, y toda la aleatoriedad sale de flujos con semilla.

| Parámetro | Significado | Valor de referencia |
| --- | --- | --- |
| `lam` | Tasa de llegadas (clientes por unidad de tiempo) | 0,8 |
| `mu` | Tasa de servicio (clientes por unidad de tiempo) | 1,0 |
| `duracion` | Tiempo observado tras el calentamiento | 10 000 |
| `warmup` | Tiempo inicial descartado | 1 000 |
| `semilla` | Semilla del experimento | 2026 |

La unidad de tiempo es abstracta en este hito; en el resto de EDsim serán minutos.

**Procesos**

- **Generador de llegadas:** bucle que espera un tiempo exponencial de media 1/λ (flujo de llegadas) y crea un proceso cliente.
- **Cliente:** al llegar recibe su tiempo de servicio, exponencial de media 1/μ (flujo de servicio); pide el servidor, espera su turno, ocupa el servidor ese tiempo y lo libera.
- **Servidor:** un `simpy.Resource` de capacidad 1; la cola FIFO la gestiona SimPy.

El tiempo de servicio se asigna al llegar, y no al empezar la atención, para que cada cliente tenga siempre el mismo tiempo de servicio con la misma semilla aunque cambie el resto del sistema. Es la base de los números aleatorios comunes de los experimentos.

**Registros y métricas**

- Por cliente: identificador, llegada, inicio de servicio y fin.
- Traza del sistema: cada cambio en el número de clientes en cola y en el sistema, con su instante.
- **Wq y W:** media sobre los clientes que llegan después del calentamiento y terminan antes del final.
- **Lq y L:** media ponderada en el tiempo de la traza (área bajo la curva escalonada entre la duración observada).
- **ρ:** tiempo con el servidor ocupado entre la duración observada.
- **Ley de Little:** se comprueba L ≈ λ̂·W, con λ̂ la tasa de llegadas observada.

Con ρ ≥ 1, o con tasas no positivas, el modelo rechaza los parámetros con un error claro, porque la teoría no tiene régimen estable que comparar.

## Aleatoriedad y reproducibilidad

- Se usa `numpy.random.Generator`; nunca el módulo `random` ni `np.random.seed` globales.
- `SeedSequence(semilla)` genera una semilla independiente por réplica, y cada réplica deriva dos flujos: llegadas y servicio.
- Con la misma semilla, el resultado es idéntico bit a bit; con semillas distintas, distinto. Ambas cosas se testean.

## Experimento y estadística

- R réplicas independientes (20 por defecto), cada una con calentamiento y duración observada.
- Para cada métrica: media de las réplicas, desviación típica e intervalo de confianza al 95 % con la t de Student.

```latex
\bar{x} \pm t_{0{,}975;\,R-1}\,\frac{s}{\sqrt{R}}
```

- **Criterio de validación:** el valor teórico cae dentro del intervalo, y se informa también del error relativo.
- **Escenarios:** μ = 1 y ρ ∈ {0,5; 0,8; 0,9}. Con ρ = 0,9 la convergencia es lenta y puede requerir más duración: observarlo es parte del aprendizaje.
- Con intervalos al 95 %, aproximadamente una de cada veinte comparaciones correctas cae fuera por azar. Los tests usan semilla fija y se interpretan en conjunto.

## Salidas: CLI, CSV y gráfica

Las opciones de la CLI van en español, como en el diseño; el código interno, en inglés.

```bash
edsim mm1 comparar --lam 0.8 --mu 1 --duracion 10000 --warmup 1000 --replicas 20 --semilla 2026
edsim mm1 barrido --rhos 0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,0.95 --salida resultados/mm1
```

- `comparar` imprime una tabla: métrica, teoría, media simulada, IC al 95 %, error relativo y si la teoría cae dentro.
- `barrido` guarda un CSV y una gráfica PNG con la curva teórica de Wq frente a ρ y los puntos simulados con sus intervalos.
- La carpeta `resultados/` se añade a `.gitignore`: los resultados se regeneran, no se versionan.

## Estructura del código

```
src/edsim/
├── cli.py                  # subcomando mm1 (comparar, barrido)
├── queueing/
│   ├── __init__.py
│   ├── theory.py           # fórmulas de la M/M/1
│   └── mm1.py              # modelo SimPy, registros y métricas
└── stats.py                # réplicas e intervalos de confianza
tests/
├── test_theory.py
├── test_mm1.py             # reproducibilidad, invariantes, Little
├── test_stats.py
├── test_mm1_validation.py  # teoría dentro del IC (marcado slow)
└── test_cli.py
```

Dependencias nuevas con `uv add`: `simpy`, `numpy`, `scipy` y `matplotlib`.

## Tests

| Grupo | Qué comprueba |
| --- | --- |
| Fórmulas | Valores conocidos (λ = 0,5, μ = 1: Wq = 1, W = 2, Lq = 0,5, L = 1) y error con ρ ≥ 1 |
| Reproducibilidad | Misma semilla, mismos registros; semillas distintas, registros distintos |
| Invariantes | Inicio ≥ llegada, fin ≥ inicio, orden FIFO, nunca dos clientes en servicio, ρ entre 0 y 1 |
| Ley de Little | L ≈ λ̂·W dentro de una tolerancia |
| Validación estadística | La teoría cae dentro del IC para ρ = 0,5 y 0,8 con semilla fija |
| CLI | Los subcomandos responden y generan sus salidas |

Los tests estadísticos tardan más y se marcan como `slow`. El hook `Stop` de Claude Code pasa a ejecutar `pytest -m "not slow"` para seguir siendo rápido; el CI ejecuta todos.

## Notebook de exploración de la M/M/1

Un notebook de Jupyter, abierto en Cursor, para exponer y explorar todos los conceptos del hito ejecutando las funciones del paquete `edsim`. Es didáctico: cada sección combina una explicación breve, código que llama al paquete, una visualización y una pregunta para experimentar.

**Reglas**

- Toda la lógica vive en `edsim`; el notebook solo llama a sus funciones, visualiza y explica. Si algo necesita lógica nueva, se añade al paquete con tests.
- Debe ejecutarse de principio a fin sin errores ("Restart & Run All"), sin depender del orden en que se ejecutaron las celdas.
- Las semillas son explícitas en cada sección, para que los resultados sean reproducibles.
- `nbstripout` en pre-commit borra resultados e imágenes antes de cada commit: se versionan el código y el texto, no las salidas.
- Fichero: `notebooks/01_mm1_exploracion.ipynb`. Dependencias de desarrollo: `ipykernel` y `nbmake`; `nbstripout` se instala como hook de pre-commit, en su propio entorno.

**Contenido**

1. **Introducción:** qué es una cola M/M/1, notación de Kendall y objetivo del notebook.
2. **Llegadas y servicio:** histogramas de tiempos entre llegadas y de servicio frente a la exponencial teórica; la propiedad de no tener memoria; el error de escala (tasa frente a media) visto en una gráfica.
3. **Una réplica paso a paso:** la tabla de registros de una simulación corta y un diagrama de Gantt del servidor, con llegadas, esperas y servicios.
4. **El sistema en el tiempo:** número en cola y en el sistema como función escalonada; el calentamiento visible con el sistema arrancando vacío; varias semillas superpuestas.
5. **Métricas:** media por cliente frente a media en el tiempo (el área bajo la escalera); recorte a la ventana; comprobación de la ley de Little.
6. **Variabilidad entre réplicas:** distribución de Wq en muchas réplicas; efecto de la duración en la dispersión y en el sesgo.
7. **Intervalos de confianza:** error estándar, t de Student y cómo se estrecha el intervalo con más réplicas (√R).
8. **Cobertura:** el experimento de 100 intervalos dibujado como "bosque" de intervalos frente al valor teórico, con duración corta y larga.
9. **Utilización y no linealidad:** barrido de Wq frente a ρ con la curva teórica; ensanchamiento de los intervalos cerca de la saturación.
10. **Para experimentar:** parámetros que cambiar (λ, μ, duración, calentamiento, réplicas) y preguntas guía.
11. **Resumen:** las lecciones del hito en pocas frases.

**Comprobaciones**

- El CI ejecuta el notebook de principio a fin (por ejemplo, con el plugin de pytest `nbmake`), con parámetros reducidos para que sea rápido.
- pre-commit verifica que el notebook se guarda sin resultados.

## Tareas, ramas y orden de ejecución

Cada tarea empieza con una explicación breve del concepto concreto, sigue con el plan en modo Plan y se ejecuta en modo Manual.

| # | Tarea | Rama | Resultado |
| --- | --- | --- | --- |
| 1.1 | Dependencias y fórmulas teóricas | `feat/h1-teoria` | `theory.py` con tests de valores conocidos |
| 1.2 | Modelo M/M/1 en SimPy con flujos y semilla | `feat/h1-modelo-mm1` | Modelo reproducible e invariantes en verde |
| 1.3 | Métricas por cliente y en el tiempo; ley de Little | `feat/h1-metricas` | Wq, W, Lq, L, ρ y test de Little |
| 1.4 | Réplicas, IC y validación; marca `slow` y ajuste del hook | `feat/h1-replicas` | La teoría cae dentro del IC |
| 1.5 | CLI `mm1 comparar` y `mm1 barrido` con CSV y gráfica | `feat/h1-cli` | Curva de Wq frente a ρ generada por EDsim |
| 1.6 | Notebook de exploración de la M/M/1 con Jupyter en Cursor y `nbstripout` en pre-commit | `feat/h1-notebook` | Notebook ejecutable de principio a fin, sin resultados versionados |
| 1.7 | Cierre: diario, ADRs si proceden, anexo de referencia, etiqueta `v0.1-hito1`; retirar de `CLAUDE.md` la regla de git manual | `docs/h1-cierre` | Hito cerrado |

## Criterios de aceptación

El hito 1 está cerrado cuando se cumplen todos:

- [ ] `uv run pytest` pasa, incluidos los tests `slow`, y el CI está en verde.
- [ ] Con la misma semilla, dos ejecuciones dan resultados idénticos.
- [ ] `edsim mm1 comparar` con ρ = 0,8 muestra Wq, W, Lq, L y ρ teóricos dentro de sus intervalos al 95 %.
- [ ] La ley de Little se cumple en la simulación dentro de la tolerancia.
- [ ] `edsim mm1 barrido` genera el CSV y la gráfica de Wq frente a ρ con la curva teórica.
- [ ] Pedro sabe explicar por qué la espera se dispara cerca del 100 % de utilización y por qué hacen falta réplicas.
- [ ] `docs/` contiene esta especificación, la entrada del diario y el anexo de referencia del hito.
- [ ] La etiqueta `v0.1-hito1` existe en GitHub.
- [ ] `notebooks/01_mm1_exploracion.ipynb` se ejecuta de principio a fin en el CI y se versiona sin resultados.

[SimPy en PyPI](https://pypi.org/project/simpy/)

## Anexo: guía de referencia del hito 1

Este anexo se amplía al cerrar cada tarea del hito: qué se hizo, los conceptos que aparecieron, las decisiones y las lecciones aprendidas. Sirve de referencia para repetir el trabajo o retomarlo más adelante.

### Tarea 1.1: dependencias y fórmulas teóricas

**Qué se hizo**

- La especificación del hito se exportó a Markdown y se guardó en `docs/specs/hito-1.md`, para que Claude Code trabaje contra ella.
- Se añadieron `simpy`, `numpy`, `scipy` y `matplotlib` como dependencias del proyecto con `uv add`.
- Se escribió `tests/test_theory.py` antes que el código, con los valores conocidos de la M/M/1, la ley de Little aplicada a las fórmulas y los errores de parámetros inválidos.
- Se creó el subpaquete `src/edsim/queueing/` con `theory.py`: una función que recibe λ y μ y devuelve un resultado inmutable con ρ, Wq, W, Lq y L.

**Conceptos**

- **Dependencias de ejecución y de desarrollo.** `uv add` añade lo que el simulador necesita para funcionar (aparece en `dependencies`); `uv add --dev` añade lo que solo hace falta para desarrollar, como pytest o ruff (aparece en `[dependency-groups]`).
- **Funciones puras.** Sin estado ni aleatoriedad: la misma entrada da siempre la misma salida. Son el caso más fácil de testear y sirven de referencia ("patrón oro") para validar el simulador.
- **Tests primero (TDD ligero).** Se escriben los tests, se comprueba que fallan y luego se implementa hasta que pasan. Con un agente, los tests fijan qué es correcto antes de que escriba el código.
- **Subpaquetes.** El fichero `__init__.py` convierte una carpeta en un subpaquete de Python, lo que permite importar `edsim.queueing.theory`.
- **Comparar decimales.** Los números en coma flotante no son exactos (`0.1 + 0.2` no es exactamente `0.3`), así que los tests comparan con tolerancia mediante `pytest.approx`.

**Decisiones**

- El resultado de las fórmulas es un objeto inmutable (por ejemplo, un `dataclass` con `frozen=True`), para que nadie lo modifique por error tras calcularlo.
- Los parámetros inválidos (λ ≤ 0, μ ≤ 0 o ρ ≥ 1) se rechazan antes de calcular, con un error claro: con ρ ≥ 1 no hay régimen estable y algunas fórmulas darían valores negativos o dividirían por cero.

**Lecciones aprendidas**

- **No todos los rojos son iguales.** El primer fallo fue `ModuleNotFoundError`: el código no existía. Es un rojo válido para un módulo nuevo, pero el más informativo es el que demuestra que el test detecta un error concreto. Para lógica delicada conviene pedir primero una versión mínima incorrecta y ver que los tests la atrapan.
- **La especificación vive en el repositorio.** Exportarla a `docs/specs/` al empezar el hito permite que el prompt de cada tarea sea corto ("lee la especificación y haz la tarea 1.1") y que el agente trabaje contra un documento estable.
- **Rutina tras cada fusión:** `git switch main`, `git pull`, `git branch -D <rama>` y `git log --oneline -5`.

### Tarea 1.2: el modelo M/M/1 en SimPy

**Qué se hizo**

- La validación de λ, μ y ρ se sacó de las fórmulas a una función pública, `validate_mm1_rates(lam, mu)`, que usan la teoría y el modelo.
- `src/edsim/queueing/mm1.py` contiene `simulate_mm1(lam, mu, horizon, seed)`, que simula una réplica y devuelve un registro inmutable por cliente.
- `CustomerRecord` tiene los campos `customer_id`, `arrival`, `service_time`, `service_start` y `departure`. `None` significa "no ocurrió dentro del horizonte".
- Dos flujos aleatorios independientes con `SeedSequence(seed).spawn(2)`: llegadas y servicio. El tiempo de servicio se sortea al llegar el cliente y se guarda aunque no termine.
- `tests/test_mm1.py`, escrito antes que el modelo: reproducibilidad, invariantes con carga alta (ρ = 0,9), comprobación de que alguien llega a esperar, clientes incompletos, error de escala con λ = 2 y μ = 5 y unos 40 000 clientes, y errores con parámetros inválidos u horizonte no positivo.
- Prueba con el servidor roto: se cambió temporalmente la capacidad a 2 para comprobar qué tests lo detectan, y se deshizo el cambio.

**Conceptos**

- **Procesos de SimPy.** Funciones generadoras en las que cada `yield` significa "despiértame cuando ocurra esto". El generador de llegadas es un bucle infinito; cada cliente es un proceso propio.
- **El recurso y su cola.** `simpy.Resource(env, capacity=1)` es el servidor. Con `with servidor.request() as turno: yield turno`, el cliente espera si está ocupado y lo libera al salir del bloque.
- **Tasa frente a escala.** `rng.exponential()` recibe la media (1/λ), no la tasa (λ). Confundirlas no da error: da resultados falsos. Con λ = μ = 1 el error es invisible, porque 1/1 = 1; por eso el test usa λ = 2 y μ = 5.
- **Simular y medir por separado.** El modelo solo registra hechos (llegada, inicio, salida); las métricas se calculan aparte. Cada parte es más fácil de probar.
- **DRY y refactorización segura.** Mover la validación a una función compartida evita dos copias que divergen. Es seguro porque los tests de la tarea 1.1 avisarían si el comportamiento cambiara.
- **Verdad vacía.** Un invariante como "nadie empieza antes de llegar" se cumple trivialmente si nunca hay cola. El test de que alguien llega a esperar garantiza que la situación probada ocurre de verdad.
- **Tolerancia de un test estadístico.** La media de 40 000 tiempos exponenciales de media 0,5 tiene un error estándar de unos 0,0025; una tolerancia del orden del 3 % es holgada para el azar e imposible de cumplir con el error de escala.

**Decisiones**

- El tiempo de servicio se asigna al llegar y se guarda en el registro: la misma semilla da a cada cliente el mismo tiempo de servicio, base de los números aleatorios comunes.
- Los clientes sin terminar no se descartan ni se completan con valores inventados: quedan con `None` en lo que no ocurrió.

**Lecciones aprendidas**

- **Predecir antes de romper.** Antes de cambiar la capacidad a 2 se anticipó qué tests debían fallar ("nunca dos en servicio"), cuáles podían fallar (incompletos) y cuáles no (FIFO, inicio ≥ llegada, fin ≥ inicio, que un sistema con dos servidores también cumple). Así se aprende qué detecta cada test.
- **Pregúntale al código.** Para no suponer nombres: `dataclasses.fields(Clase)` lista los campos, `inspect.signature(funcion)` muestra los argumentos e `inspect.getmembers(modulo)` lo que contiene (incluido lo importado, como `dataclass`).
- **Leer los registros a mano confirma el modelo.** En una simulación de 20 unidades con λ = 0,8 y μ = 1, cada inicio coincidía con la salida del cliente anterior (el servidor no paró), el cliente en servicio al cortar tenía inicio y no salida, y el que esperaba no tenía ninguno de los dos.
- **Una simulación corta engaña.** En esa muestra de 11 clientes, la media de los tiempos de servicio fue 1,82 frente al 1 teórico, por dos servicios largos de 5,01 y 5,58. La espera media salió casi igual a la teórica (4,1 frente a 4) por pura casualidad. Por eso hacen falta simulaciones largas, descartar el arranque y réplicas.

### Tarea 1.3: métricas y ley de Little

**Qué se hizo**

- En `mm1.py`, `mm1_metrics(records, warmup, horizon)` devuelve un `MM1Metrics` inmutable con `wq`, `w`, `lq`, `l`, `rho`, `n_customers` y `lam_obs` (tasa de llegadas observada).
- Las métricas se calculan a partir de los propios registros, sin una traza aparte en el modelo. La función privada `_time_in_window` recorta cada intervalo a la ventana de observación.
- Tests con un ejemplo pequeño construido y calculado a mano (con clientes que cruzan los bordes de la ventana), la ley de Little en una simulación larga y los errores de ventana inválida. Se comprobó que el ejemplo a mano detecta una versión que no recorta las estancias a la ventana.
- `simulate_mm1` devuelve una tupla de registros, que tampoco se puede modificar.

**Conceptos**

- **Calentamiento.** La simulación empieza con la cola vacía, lo que sesga las medias a la baja. Se mide solo en la ventana \[warmup, horizon\].
- **Media por cliente frente a media en el tiempo.** Wq y W promedian sobre clientes ("¿cuánto espera un paciente típico?"). Lq, L y ρ promedian sobre el tiempo: el número en cola es una escalera, y su media es el área bajo la escalera dividida por la duración.
- **Recortar a la ventana.** De cada estancia solo cuenta la parte que cae dentro de la ventana, incluidos los clientes que estaban antes de empezar o siguen al final. Es el error más probable, y por eso se prueba con un ejemplo calculado a mano.
- **Hechos y estados derivados.** El número de clientes en el sistema en cada instante se reconstruye de los registros (llegados menos salidos). Es el principio del diseño de EDsim: guardar hechos y derivar estados.
- **Ley de Little como control cruzado.** L = λ·W relaciona métricas calculadas de formas distintas; si no encajan, alguna está mal.
- **Funciones privadas.** El guion bajo inicial (`_time_in_window`) indica un detalle interno del módulo que no debe usarse desde fuera.
- **Decimales en coma flotante.** La teoría devuelve Wq = 4,000000000000001 porque 0,8 y 0,2 no tienen representación binaria exacta. Por eso se compara con tolerancia.

**Resultado de una réplica** (λ = 0,8, μ = 1, horizonte 11 000, calentamiento 1 000, semilla 2026, 8 158 clientes)

| Métrica | Teoría | Simulación | Diferencia |
| --- | --- | --- | --- |
| ρ | 0,800 | 0,828 | +3,5 % |
| Tasa de llegadas | 0,800 | 0,816 | +2,0 % |
| Wq | 4,00 | 4,75 | +19 % |
| W | 5,00 | 5,76 | +15 % |
| Lq | 3,20 | 3,87 | +21 % |
| L | 4,00 | 4,70 | +18 % |

**Lecciones aprendidas**

- **Little valida el código aunque no coincida la teoría.** λ\_obs·W = 4,702 frente a L = 4,703, y λ\_obs·Wq = 3,874 frente a Lq = 3,875: métricas calculadas por caminos distintos encajan en la cuarta cifra decimal.
- **Una réplica es una sola historia.** Esta tuvo por azar más llegadas de la media, y el servidor estuvo ocupado un 82,8 % en lugar de un 80 %.
- **La no linealidad en directo.** Un 3,5 % más de utilización produjo un 20 % más de espera. Con la utilización que hubo realmente, la fórmula da Wq ≈ 0,828 / 0,172 ≈ 4,8, casi lo simulado: el modelo responde como dice la teoría a la carga que le tocó.
- **Buscar en el código.** `grep -n "^def \|^class " src/edsim/queueing/*.py` lista las funciones y clases de cada fichero con su línea.

### Tarea 1.4: réplicas, intervalos de confianza y validación

**Qué se hizo**

- `src/edsim/stats.py`: `summarize(values, confidence=0.95)` devuelve un `Summary` con media, desviación típica, error estándar e intervalo con la t de Student (`scipy.stats.t`). No depende de nada de colas.
- `src/edsim/queueing/replications.py`: `compare_mm1(...)` ejecuta R réplicas, cada una con un hijo de `SeedSequence(seed).spawn(R)`, y devuelve por métrica el resumen, la teoría, el error relativo y si la teoría cae dentro del intervalo.
- `simulate_mm1` acepta ahora `int | SeedSequence`; con un entero da exactamente lo mismo que antes, y un test lo comprueba.
- Tests: el intervalo de los valores 1 a 5 calculado a mano (al 95 % y al 90 %); réplicas reproducibles y distintas entre sí; ampliar de 3 a 5 réplicas conserva las 3 primeras; y la validación frente a la teoría, marcada `slow`, que muestra una tabla si falla.
- Marca `slow` registrada en `pyproject.toml` con `--strict-markers` (comprobado con una marca mal escrita a propósito). El hook de Claude Code ejecuta `pytest -m "not slow"`; el CI ejecuta todos los tests. `CLAUDE.md` incluye el comando de los tests rápidos.

**Resultado de la validación** (semilla 2026, 20 réplicas): la teoría cae dentro del intervalo al 95 % en las 10 comparaciones (5 métricas con ρ = 0,5 y 0,8), con errores relativos entre el 0,1 % y el 1,2 %. El test lento tarda unos 2,4 s.

| ρ | Métrica | Teoría | Media de 20 réplicas | IC 95 % |
| --- | --- | --- | --- | --- |
| 0,5 | Wq | 1,000 | 1,010 | \[0,972; 1,048\] |
| 0,5 | ρ | 0,500 | 0,501 | \[0,496; 0,505\] |
| 0,8 | Wq | 4,000 | 3,977 | \[3,762; 4,192\] |
| 0,8 | L | 4,000 | 3,977 | \[3,796; 4,158\] |

**Conceptos**

- **Réplicas independientes con semilla maestra.** Un solo número reproduce el experimento completo, y las réplicas son independientes entre sí.
- **Desviación típica y error estándar.** La primera mide cuánto varían las réplicas; el segundo (s/√R), cuánto variaría la media. Reducir el error a la mitad exige cuatro veces más réplicas.
- **Intervalo de confianza al 95 %.** Si se repitiera el experimento muchas veces, el 95 % de los intervalos construidos así contendrían el valor verdadero. No significa que el valor tenga un 95 % de probabilidad de estar en un intervalo concreto.
- **t de Student.** Con pocas réplicas, la desviación típica también es incierta; la t ensancha el intervalo para compensarlo (t ≈ 2,09 con 20 réplicas frente al 1,96 de la normal).
- **Tests lentos.** Se separan con una marca para que el ciclo de trabajo siga siendo rápido sin dejar de ejecutarse en el CI.

**Experimento de cobertura** (fuera del repositorio): 100 experimentos de 20 réplicas con ρ = 0,8 y semillas maestras 0 a 99.

| Duración y calentamiento | Cobertura de Wq | Fallos de Wq | Cobertura de las demás métricas | Tiempo |
| --- | --- | --- | --- | --- |
| 2 000 y 500 | 96/100 | 4, todos con la simulación por debajo | Entre 93 y 95 | 34 s |
| 10 000 y 1 000 | 97/100 | 2 por debajo y 1 por encima | Entre 94 y 97 | 163 s |

**Lecciones aprendidas**

- **Una réplica engaña; veinte no.** Una sola réplica se desviaba un 19 % de la teoría; la media de veinte, menos de un 1 %.
- **El 95 % de confianza es una frecuencia.** El experimento de cobertura lo mostró: el procedimiento acierta en torno al 95 % de las veces, y un resultado entre 90 y 99 de 100 es normal (95 % ± 4,4 %).
- **Con simulaciones cortas, las esperas salen subestimadas.** Con ventanas de 2 000 unidades, todos los fallos quedaban por debajo de la teoría; con 10 000, se repartían. La causa más probable es que los clientes atrapados en una cola larga al final no terminan y quedan fuera de la media, junto con la asimetría de las medias de réplicas cortas. Por eso los experimentos de EDsim simulan semanas con días de calentamiento.
- **Las métricas de cola fallan juntas.** Wq, W, Lq y L están unidas por la ley de Little y por W = Wq + 1/μ; las diez comparaciones de la validación equivalen a unas cuatro independientes, y la probabilidad de algún fallo por azar baja del 40 % a cerca del 19 %.
- **Diagnóstico por métricas.** ρ depende de llegadas y servicio y falla "por libre". Si fallan a la vez ρ y las esperas, revisar llegadas y servicio; si fallan solo las esperas, sospechar de los episodios de saturación.
- **Medir la utilización es fácil; medir las esperas cerca de la saturación, no.** El intervalo de ρ es decenas de veces más estrecho que el de Wq con ρ = 0,8.
- **Honestidad estadística.** Si una validación falla con la semilla fijada, no se prueban semillas hasta que pase (*p-hacking*): se analiza la causa y se decide con criterio, por ejemplo con más duración o más réplicas.
- **Comprobar las barandillas.** `--strict-markers` se verificó con una marca mal escrita: sin esa opción, un error de tecleo convertiría en silencio un test lento en rápido.

### Tarea 1.5: CLI `edsim mm1 comparar` y `edsim mm1 barrido`

**Qué se hizo**

- `src/edsim/queueing/report.py`, sin dependencia de `argparse`: `format_comparison` (la tabla), `write_sweep_csv` (el CSV) y `plot_sweep` (la gráfica, que devuelve la figura para poder inspeccionarla en los tests).
- `src/edsim/cli.py` construye los subcomandos, valida, llama a `compare_mm1` y a `report`, e imprime o escribe. El bucle del barrido cabe en una línea.
- Subcomandos obligatorios: `edsim mm1` sin acción da un error de uso. Opciones en español con los valores por defecto de la especificación.
- `barrido` escribe `barrido.csv` y `barrido_wq.png` en el directorio de `--salida`, que se crea si no existe.
- CSV *tidy*: una fila por ρ y métrica, con columnas en español, decimales escritos con `repr` para recuperarlos exactamente, y los parámetros del experimento (réplicas, duración, calentamiento y semilla) repetidos en cada fila para que el fichero sea trazable.
- El test de validación usa ahora `format_comparison` en lugar de su propia tabla; `resultados/` se añadió a `.gitignore`.
- Tests en `tests/test_cli.py` con parámetros pequeños (menos de 1 s en total): versión, salida de `comparar`, ficheros del barrido y contenido exacto del CSV, la figura, `--rhos` inválido (código 2, sin crear ficheros) y errores de dominio sin traza de Python.

**Conceptos**

- **Subcomandos con `argparse`.** Como `git commit` o `gh pr create`: cada acción tiene sus opciones y su ayuda (`edsim mm1 barrido --help`).
- **CLI fina.** La CLI lee argumentos, llama a funciones y muestra resultados; la lógica y la presentación viven en funciones testeables sin terminal.
- **Formato *tidy*.** Una observación por fila; es el formato que mejor leen pandas, DuckDB o una hoja de cálculo, y permite concatenar experimentos.
- **Gráficas sin pantalla.** El *backend* `Agg` dibuja en un fichero. Se usa creando la figura con `matplotlib.figure.Figure` y `FigureCanvasAgg`, sin cambiar el *backend* global: así importar `report` desde un notebook no impide ver gráficas en pantalla, y no quedan figuras abiertas en memoria.
- **Códigos de salida.** 0 si todo va bien; `argparse` usa el 2 para errores de uso. Los errores internos se convierten con `parser.error` para que todos se vean igual.

**Resultados medidos**: el barrido completo por defecto (10 valores de ρ × 20 réplicas × 11 000 unidades) tarda unos 10 s, y el punto de ρ = 0,95 es el más lento (1,9 s). La teoría cae dentro del intervalo en los 10 puntos. `comparar` con ρ = 0,8 tarda 1,5 s.

**Lecciones aprendidas**

- **Anticipar el uso futuro.** Evitar `matplotlib.use("Agg")` previno un problema que habría aparecido en el notebook de la tarea 1.6.
- **Una sola versión de cada cosa.** Sustituir la tabla duplicada del test por `format_comparison` evita formatos que divergen con el tiempo.
- **Los resultados deben llevar su origen.** Incluir los parámetros en el CSV permite saber cómo se generó cada fichero y comparar barridos distintos.
- **Errores coherentes.** Validar en `argparse` y convertir los errores internos da un único formato de error, el mismo código de salida y ningún fichero a medias.
- **El modo Plan en Cursor.** Cuando Claude presenta un plan formal en modo Plan, la extensión lo abre como documento Markdown en el editor, donde se pueden añadir comentarios en línea; si solo lo explica en la conversación, aparece en el panel lateral.
- **Cerca de la saturación, cuidado con la duración.** El punto de ρ = 0,95 pasa la validación, pero las simulaciones cortas tienden a subestimar las esperas; una mejora futura sería alargar la duración del barrido según ρ se acerca a 1.

### Tarea 1.6: notebook de exploración de la M/M/1

**Qué se hizo**

- `notebooks/01_mm1_exploracion.ipynb`, en español, con una sección 0 de uso y las 11 secciones de la especificación. Cada sección combina explicación, código que solo llama a `edsim`, una gráfica, preguntas "Para experimentar" y un recuadro "Lo que debes recordar".
- Funciones nuevas en el paquete, con tests escritos antes: `src/edsim/queueing/analysis.py` (tiempos entre llegadas y de servicio, tiempos residuales, la serie escalonada de ocupación, su media en el tiempo y su muestreo en una rejilla), `t_critical` en `stats.py`, `coverage_mm1` en `replications.py` y `format_records` en `report.py`.
- Un test une las dos formas de calcular las medias en el tiempo: la escalera de ocupación y `mm1_metrics` coinciden con precisión de 10⁻¹².
- Infraestructura: `ipykernel` y `nbmake` como dependencias de desarrollo; hook `nbstripout` (0.9.1) en pre-commit; un paso del CI que ejecuta el notebook en modo rápido (`EDSIM_NB_RAPIDO=1`); comandos y apertura en Cursor documentados en `CLAUDE.md`.
- El hook de tests de Claude Code no ejecuta el notebook: pytest solo recoge `tests/`, y `nbmake` solo actúa con `--nbmake`.

**Conceptos**

- **Notebook y kernel.** Celdas de código y de texto; el código lo ejecuta un kernel de Python que conserva las variables entre celdas. Debe ser el de `.venv` para encontrar `edsim`.
- **Estado oculto.** Ejecutar celdas en cualquier orden puede dejar un notebook que solo funciona en tu sesión. La defensa es *Restart & Run All*, y `nbmake` lo hace en el CI.
- **`nbstripout`.** Borra resultados e imágenes antes de cada commit: git guarda código y texto, con diffs legibles.
- **Modo rápido.** Una variable de entorno reduce réplicas y duraciones desde una única celda de parámetros, para que el CI ejecute el notebook en segundos.
- **El notebook no contiene lógica.** Lo que necesita se añade al paquete con tests; así surgieron piezas reutilizables, como la serie de ocupación, útil para futuros paneles de urgencias.
- **Ruff también revisa notebooks**, igual que el resto del código.

**Tiempos**: en modo rápido, unos 10 s (el del CI). En modo normal, 288 s, la mayor parte en la cobertura de la sección 8, que reproduce el experimento de 96 y 97 aciertos de 100.

**Lecciones aprendidas**

- **Cuidado con los límites de tiempo.** `nbmake` corta por defecto a los 300 s, y el modo normal tardó 288 s, más de lo estimado. El modo normal se ejecuta con `uv run pytest --nbmake --nbmake-timeout=600 notebooks/`.
- **`nbstripout` cancela el primer commit.** Al quitar las salidas modifica el fichero y el commit no se crea; hay que repetir `git add` y el commit. Tras cada commit, el notebook queda sin gráficas en Cursor hasta volver a ejecutarlo: conviene explorar libremente y hacer el commit al final.
- **Encadenar con `&&`.** Con los comandos en líneas separadas, el `push` y el `gh pr create` se ejecutaron aunque el commit había fallado, y el PR falló con "No commits between main and…". Con `git add . && git commit … && git push && gh pr create …`, cada paso solo se ejecuta si el anterior ha ido bien.
- **Un notebook didáctico empuja a mejorar el paquete.** Las visualizaciones exigieron funciones de análisis que antes no existían y que ahora tienen tests y servirán en hitos posteriores.
