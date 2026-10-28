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
- Tests de fórmulas, reproducibilidad, invariantes, ley de Little y validación estadística.

**Fuera del alcance**

- Llegadas que varían con la hora del día (hito 2).
- Pacientes, triaje, prioridades y log de eventos (hito 3).
- Notebooks (más adelante).

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

## Tareas, ramas y orden de ejecución

Cada tarea empieza con una explicación breve del concepto concreto, sigue con el plan en modo Plan y se ejecuta en modo Manual.

| # | Tarea | Rama | Resultado |
| --- | --- | --- | --- |
| 1.1 | Dependencias y fórmulas teóricas | `feat/h1-teoria` | `theory.py` con tests de valores conocidos |
| 1.2 | Modelo M/M/1 en SimPy con flujos y semilla | `feat/h1-modelo-mm1` | Modelo reproducible e invariantes en verde |
| 1.3 | Métricas por cliente y en el tiempo; ley de Little | `feat/h1-metricas` | Wq, W, Lq, L, ρ y test de Little |
| 1.4 | Réplicas, IC y validación; marca `slow` y ajuste del hook | `feat/h1-replicas` | La teoría cae dentro del IC |
| 1.5 | CLI `mm1 comparar` y `mm1 barrido` con CSV y gráfica | `feat/h1-cli` | Curva de Wq frente a ρ generada por EDsim |
| 1.6 | Cierre: diario, ADRs si proceden, anexo de referencia, etiqueta `v0.1-hito1`; retirar de `CLAUDE.md` la regla de git manual | `docs/h1-cierre` | Hito cerrado |

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

[SimPy en PyPI](https://pypi.org/project/simpy/)
