# Hito 2 — Llegadas

## Objetivo y alcance

Al terminar el hito 2, EDsim genera las llegadas de un centro de 300 urgencias al día como un proceso de Poisson no homogéneo. Su tasa varía con la hora, el día de la semana y el mes, y un efecto aleatorio diario añade sobredispersión. El generador usa el algoritmo de *thinning*, es reproducible por semilla y se valida estadísticamente: volumen, forma horaria, propiedad de Poisson y dispersión diaria.

**Dentro del alcance**

- Perfiles de llegadas en un fichero TOML con claves en español, validados y normalizados a media 1.
- Función de tasa λ(t) continua y su intensidad acumulada Λ(t), calculada de forma exacta.
- Generador perezoso por *thinning* de Lewis–Shedler, con cota por día, flujos aleatorios y semilla, y un proceso SimPy que lo consume.
- Efecto aleatorio diario gamma de media 1, guardado como ground truth por día.
- Validación: volumen por día de la semana, chi-cuadrado horario, Kolmogórov–Smirnov de los huecos reescalados, dispersión diaria con réplicas y uniformidad de los p-valores.
- CLI `edsim llegadas generar` y `edsim llegadas validar`, con CSV y gráficas.
- Tests (rápidos y `slow`) y el notebook `02_llegadas_exploracion.ipynb`.

**Fuera del alcance**

- Festivos, eventos y shocks (brotes, accidentes con múltiples víctimas): la fórmula admite un factor más, pero se añaden en hitos posteriores.
- Llegadas en grupo y atributos del paciente (edad, motivo, medio de llegada): hitos 3 y 4.
- Dependencia entre días consecutivos y cambio de hora: el efecto diario es independiente de un día a otro y el reloj no cambia de hora.
- Acoplamiento de escenarios con números aleatorios comunes: hito 9.

Es el primer hito en el que Claude Code ejecuta los comandos de git: crea la rama, hace los commits, hace push con permiso y abre el pull request. Pedro revisa y siempre fusiona.

## Sesión conceptual

Los conceptos se explicaron en la conversación de arranque del hito, con gráficas y un widget de *thinning*. Esta tabla es el resumen de referencia.

| Concepto | Qué hay que entender |
| --- | --- |
| Poisson no homogéneo | Llegadas independientes con tasa λ(t) que cambia con el tiempo; en un intervalo corto dt llega alguien con probabilidad λ(t)·dt |
| Intensidad acumulada | Λ(t) es el área bajo λ(t); las llegadas entre a y b siguen una Poisson de media Λ(b) − Λ(a) |
| Huecos no exponenciales | Con λ(t) variable, los tiempos entre llegadas mezclan huecos largos de madrugada y cortos a mediodía, y no son exponenciales |
| Modelo multiplicativo | λ(t) = base/24 × h(hora) × d(día) × m(mes) × Z(día); la base fija el volumen y los factores, la forma |
| Normalización | Cada perfil tiene media 1 para que la base conserve su significado; los meses se ponderan por sus días |
| Porcentaje frente a tasa | Un 9,31 % del año en un mes de 31 días equivale a un factor de tasa diaria de 1,10, no de 9,31/8,33 |
| Interpolación | Cada valor horario es el del centro de su hora y se unen con rectas: λ(t) continua con el mismo área diaria |
| *Thinning* (Lewis–Shedler) | Candidatas a tasa constante λ\* ≥ λ(t); cada una se acepta con probabilidad λ(t)/λ\*; el resultado es exacto |
| Cota y eficiencia | Aceptación = media de λ / λ\* (≈ 60 % con cota por día); una cota baja recorta los picos sin dar error |
| Sobredispersión | Los días reales varían más que Poisson; un efecto Z gamma de media 1 por día da recuentos binomial negativa |
| CV frente a índice de dispersión | Varianza diaria = μ + (CV·μ)²; el índice 1 + CV²·μ crece con el volumen, el CV se puede trasladar entre centros |
| Reescalado temporal | Los tiempos Λ(tᵢ) forman un Poisson de tasa 1: sus huecos son exponenciales de media 1 y se contrastan con Kolmogórov–Smirnov |
| Chi-cuadrado | Compara recuentos observados y esperados por hora del reloj, teniendo en cuenta que las horas con más llegadas admiten más desviación |
| Uniformidad de los p-valores | Con un generador correcto, el p-valor es uniforme: un 5 % de las semillas da p < 0,05 por azar |

## Cómo encajan las piezas

El perfil define λ(t) y Λ(t); la semilla da dos flujos independientes; el generador por *thinning* combina ambos y deja dos tipos de registros, que consumen el proceso SimPy, la validación (que usa también Λ) y las salidas.

&#91;embedded content: flujo del hito 2 · del perfil y la semilla a la validación\]

## Modelo de llegadas

La tasa es una base de 300 urgencias al día multiplicada por un factor por cada escala de tiempo, como fija el modelo estadístico del diseño; el reloj va en minutos.

```latex
\lambda(t) = \frac{B}{1440} \cdot h(t) \cdot d(t) \cdot m(t) \cdot Z_{\text{día}(t)}
```

| Clave | Significado | Valor por defecto |
| --- | --- | --- |
| `base_diaria` | B: urgencias al día de media anual | 300 (rango 200–400) |
| `reparto_horario` | Porcentaje de las llegadas del día en cada hora, de 0 h a 23 h (24 valores) | Tabla de calibración |
| `reparto_semanal` | Porcentaje de las llegadas de la semana en cada día, de lunes a domingo (7 valores) | Tabla de calibración |
| `factor_mensual` | Factor de tasa diaria de cada mes, de enero a diciembre (12 valores) | Tabla de calibración |
| `cv_diario` | Coeficiente de variación del efecto diario Z; 0 lo desactiva | 0,06 |
| `fecha_inicio` | Fecha del minuto 0 (a las 00:00) | 2026-01-05 (lunes) |

**Reglas del perfil**

- El código valida el número de valores (24, 7 y 12), que sean positivos y que el CV no sea negativo, con errores claros.
- Los repartos se normalizan a factores de media 1: h = 24 × reparto / suma y d = 7 × reparto / suma. No hace falta que sumen exactamente 100.
- El factor mensual se normaliza para que su media ponderada por los días de cada mes (año de 365 días) sea 1. Así la media anual es la base aunque los valores escritos no cuadren del todo.
- Interpolación: cada valor horario corresponde al centro de su hora (h:30) y entre centros consecutivos se interpola linealmente, de forma periódica (las 23:30 enlazan con las 0:30). La curva es continua y el área de un día completo sigue siendo la suma de los 24 factores.
- El día de la semana, el mes y Z cambian a medianoche. El reloj no tiene cambio de hora: todos los días duran 1.440 minutos.
- Λ(t) se calcula de forma exacta: con λ lineal a trozos, el área de cada tramo es un trapecio.

**Calibración del centro base**

La forma del perfil se contrastó con el estudio del CMBD de urgencias de los 28 hospitales del Servicio Andaluz de Salud en 2012 (3,2 millones de urgencias). Los valores intermedios que no da el estudio son supuestos razonables, marcados como tales.

| Escala | Dato publicado | Valor en EDsim |
| --- | --- | --- |
| Horas | Máxima afluencia de 10 a 13 h y de 16 a 17 h; valle de 2 a 8 h; patrón parecido todos los días | Un único perfil para toda la semana; máximo a las 11 h (7,0 %), mínimo a las 5 h (1,1 %) |
| Días | Lunes 16,27 %, sábado 13,08 %, domingo 13,58 % | Esos tres valores; martes a viernes descendiendo de 14,80 a 13,77 % (supuesto) |
| Meses | Enero 9,31 % del año (máximo); septiembre 7,72 % (mínimo) | Factores 1,10 y 0,94 (pasados a tasa por día); el resto, una estacionalidad suave con invierno alto (supuesto) |
| Sobredispersión | Índice de dispersión diario de 1,2 a 1,5 con unas 134 urgencias al día (Whitt y Zhang) | CV de 6 %; con 300 al día equivale a un índice de 2,1 |

Fichero `config/llegadas.toml`:

```toml
# Perfil de llegadas del centro base. Ver docs/specs/hito-2.md.
base_diaria = 300
cv_diario = 0.06
fecha_inicio = 2026-01-05

# % de las llegadas del día, de 0 h a 23 h (SAS 2012: picos 10-13 h y 16-17 h, valle 2-8 h)
reparto_horario = [
  2.7, 2.1, 1.6, 1.3, 1.2, 1.1, 1.3, 2.1,
  3.7, 5.4, 6.6, 7.0, 6.7, 6.0, 5.1, 5.4,
  6.2, 6.2, 5.7, 5.3, 5.0, 4.7, 4.2, 3.4,
]

# % de las llegadas de la semana, de lunes a domingo (SAS 2012: lunes, sábado y domingo)
reparto_semanal = [16.27, 14.80, 14.30, 14.20, 13.77, 13.08, 13.58]

# Factor de tasa diaria por mes, de enero a diciembre (SAS 2012: enero y septiembre)
factor_mensual = [1.10, 1.05, 1.02, 0.99, 1.00, 0.98, 0.99, 0.97, 0.94, 0.97, 0.98, 1.02]
```

## Generación por *thinning*

Las llegadas se generan día a día con el algoritmo de Lewis–Shedler. Su cota es el máximo de λ en ese día, de modo que se aprovecha alrededor del 60 % de las candidatas.

**Algoritmo, para cada día**

1. Al empezar el día se sortea Z (flujo del efecto diario); con `cv_diario = 0`, Z = 1.
2. Cota del día: λ\* = B/1440 × máx(h) × d × m × Z. Con interpolación lineal, λ nunca supera el mayor valor horario.
3. Candidata siguiente: t ← t + E, con E exponencial de media 1/λ\* (flujo de llegadas). Si t pasa del final del día, se reinicia en la medianoche siguiente; la exponencial no tiene memoria, así que reiniciar es exacto.
4. Aceptación: con U uniforme (flujo de llegadas), la candidata se acepta si U · λ\* ≤ λ(t).
5. Si en algún momento λ(t) > λ\*, el generador lanza un error: una cota insuficiente recortaría los picos sin avisar.

**Generador perezoso**

- `iter_arrivals(profile, horizon, seed)` es un generador de Python que entrega las llegadas en orden, una a una, sin calcularlas todas por adelantado. Así podrá funcionar en vivo cuando haya *pacer* y *shocks*.
- `simulate_arrivals(profile, horizon, seed)` lo consume entero y devuelve los registros, para el análisis por lotes.
- `arrival_source(env, arrivals, on_arrival)` es un proceso SimPy que espera hasta cada llegada (`env.timeout`) y llama a `on_arrival`. Es la pieza que usará el motor del hito 3.

**Registros**

- Por llegada (`ArrivalRecord`): `arrival_id` y `time` (minutos desde `fecha_inicio`). La fecha y la hora se derivan del tiempo y no se guardan.
- Por día (`DayRecord`, ground truth): `day`, `date`, `day_effect` (Z), `expected` (Λ del día), `bound` (λ\*), `candidates` y `accepted`. El hospital nunca observa Z; sirve para validar y, más adelante, para medir si un modelo lo detecta.
- El horizonte se da en días completos. Un horizonte no positivo o un perfil inválido dan un error claro.

## Aleatoriedad y reproducibilidad

- Igual que en el hito 1: `numpy.random.Generator`, `SeedSequence` y nunca el módulo `random` ni `np.random.seed`.
- `SeedSequence(seed).spawn(2)` da dos flujos: **llegadas** (huecos de las candidatas y uniformes de aceptación) y **efecto diario** (Z). Desactivar la sobredispersión no altera la secuencia de candidatas.
- `seed` admite `int | SeedSequence`, como `simulate_mm1`, para que las réplicas usen hijos de una semilla maestra.
- Con la misma semilla, llegadas y registros diarios son idénticos bit a bit; con semillas distintas, distintos. Ambas cosas se testean.

## Validación estadística

Cinco pruebas comprueban que las llegadas generadas son un Poisson no homogéneo con la λ(t) configurada; cada una busca un tipo de error distinto. Todas usan Λ con la Z real de cada día (del ground truth), de modo que valen con y sin sobredispersión.

| Prueba | Qué detecta | Cómo | Criterio |
| --- | --- | --- | --- |
| a. Volumen | Errores de escala y de normalización | Cociente observado/esperado de cada día (esperado sin Z), en total y por día de la semana, con `summarize` | 1 dentro del IC al 95 % |
| b. Forma horaria | Perfil horario o interpolación incorrectos | Llegadas por hora del reloj sumadas en todos los días frente al área de λ, con chi-cuadrado (esperados reescalados al total observado, 23 grados de libertad) | p ≥ 0,01 |
| c. Propiedad de Poisson | Huecos mal generados, cota o aceptación incorrectas, bordes entre días | Huecos de los tiempos reescalados Λ(tᵢ) frente a una exponencial de media 1, con Kolmogórov–Smirnov | p ≥ 0,01 |
| d. Dispersión diaria | Z ausente, mal escalado o aplicado al día equivocado | Índice de Pearson P = media de (c − e)²/e por día, con e esperado sin Z; teoría: 1 sin Z y 1 + CV²·ē con Z. 20 réplicas de 364 días | Teoría dentro del IC al 95 % |
| e. Uniformidad de los p-valores | Sesgos pequeños que una sola semilla no ve | p-valores de la prueba c en 100 semillas de 14 días, contrastados con una uniforme mediante Kolmogórov–Smirnov | p ≥ 0,01 |

**Reglas**

- Semilla fija en los tests. Si uno falla, no se cambia la semilla: se analiza la causa (honestidad estadística del hito 1).
- Las pruebas b, c y e usan un umbral de 0,01 para que, con varias pruebas a la vez, las falsas alarmas sean raras. Con un generador correcto, cada prueba falla un 1 % de las veces por azar.
- **Potencia**: los tests comprueban que cada prueba detecta una versión incorrecta concreta. Llegadas generadas con base 330 y validadas contra 300 deben fallar en a; con el perfil horario desplazado una hora, en b; con CV 0,06 validadas como si fuera 0, en d.
- Estimar una varianza necesita muchos días: con un año, la varianza diaria tiene un error de alrededor del 7 %. Por eso la prueba d usa réplicas.
- Las pruebas estadísticas largas se marcan `slow`.

## Salidas: CLI, CSV y gráficas

Dos subcomandos nuevos bajo `edsim llegadas`, con opciones en español y la misma arquitectura fina del hito 1: la CLI lee argumentos, llama al paquete y escribe.

```bash
edsim llegadas generar --config config/llegadas.toml --dias 28 --semilla 2026 --salida resultados/llegadas
edsim llegadas validar --config config/llegadas.toml --dias 364 --replicas 20 --semilla 2026 --salida resultados/llegadas
```

- `generar` escribe `llegadas.csv` (una fila por llegada: `id`, `minuto`, `fecha_hora`, `dia_semana`, `hora`) y `dias.csv` (una fila por día: `dia`, `fecha`, `efecto_diario`, `esperadas`, `cota`, `candidatas`, `aceptadas`). Ambos son *tidy* e incluyen los parámetros (fichero de configuración, días y semilla) en cada fila, como el CSV del barrido.
- `validar` imprime una tabla con una fila por prueba: estadístico, p-valor o IC, criterio y resultado. Además guarda `perfil_horario.png` (observado frente a esperado por hora), `qq_reescalado.png` y `recuentos_diarios.png` (histograma frente a la binomial negativa teórica).
- Si alguna prueba falla, `validar` termina con código de salida 1. Los errores de uso dan el código 2 sin crear ficheros a medias.
- `--config` es opcional y por defecto usa `config/llegadas.toml`; `resultados/` ya está en `.gitignore`.

## Estructura del código

```
config/
  llegadas.toml          perfil del centro base
src/edsim/arrivals/
  __init__.py
  profile.py             ArrivalProfile, load_profile (tomllib), validación y normalización
  rate.py                rate(t) y cumulative_rate(t): λ y Λ exacta
  thinning.py            iter_arrivals, simulate_arrivals, ArrivalRecord, DayRecord, arrival_source (SimPy)
  validation.py          pruebas a–e y resultado por prueba
  report.py              tabla de validación, CSV y gráficas (Figure + FigureCanvasAgg)
src/edsim/cli.py         subcomandos llegadas generar y llegadas validar
notebooks/02_llegadas_exploracion.ipynb
tests/test_profile.py, test_rate.py, test_thinning.py, test_arrival_validation.py, test_cli.py
```

Sin dependencias nuevas: `tomllib` viene con Python 3.13, y SciPy ya da `chisquare`, `kstest`, `gamma` y `nbinom`. `stats.summarize` del hito 1 se reutiliza tal cual.

## Tests

| Grupo | Qué comprueba |
| --- | --- |
| Perfil | Carga del TOML de ejemplo; factores con media 1; factor mensual ponderado por días; errores con 23 valores, valores negativos o CV negativo |
| Tasa | λ en el centro de cada hora = B/1440 · h · d · m; continuidad en los cambios de hora; Λ de un día = B · d · m; Λ exacta frente a `scipy.integrate.quad` |
| Generador | Reproducibilidad y semillas distintas; tiempos crecientes y dentro del horizonte; λ ≤ cota en una rejilla fina de cada día; error si la cota es insuficiente; `DayRecord` coherente (aceptadas ≤ candidatas y suma de aceptadas = número de llegadas) |
| SimPy | El proceso entrega las llegadas en los mismos instantes que el generador |
| Validación (`slow`) | Las cinco pruebas pasan con semilla fija, con CV 0 y con CV 0,06 |
| Potencia (`slow`) | Base 330 frente a 300, perfil desplazado una hora y CV ignorado: cada prueba detecta su versión incorrecta |
| CLI | Los subcomandos responden, generan sus ficheros con el contenido esperado y dan código 2 ante errores de uso |

Como en el hito 1, el hook `Stop` de Claude Code ejecuta `pytest -m "not slow"` y el CI ejecuta todos.

## Notebook de exploración de las llegadas

Un segundo notebook didáctico, con las mismas reglas y el mismo formato que el del hito 1: cada sección combina una explicación breve, código que solo llama a `edsim`, una gráfica, preguntas "Para experimentar" y un recuadro "Lo que debes recordar".

**Reglas**

- Toda la lógica vive en `edsim`; lo que el notebook necesite se añade al paquete con tests.
- Se ejecuta de principio a fin sin errores, con semillas explícitas en cada sección.
- Una celda de parámetros con el modo rápido `EDSIM_NB_RAPIDO=1` para el CI; `nbstripout` borra las salidas antes de cada commit.
- Fichero: `notebooks/02_llegadas_exploracion.ipynb`.

**Contenido**

0. Uso: cómo ejecutarlo y el modo rápido.
1. Introducción: de una λ constante a λ(t), con el grifo que se abre y se cierra.
2. Perfiles y calibración: los repartos horario, semanal y mensual frente a los datos del SAS; la normalización y la trampa del porcentaje mensual.
3. λ(t) y Λ(t): la curva de una semana; Λ como área; escalones frente a interpolación.
4. *Thinning* paso a paso: candidatas aceptadas y descartadas en un día; la eficiencia; qué pasa con una cota insuficiente.
5. Una semana simulada: recuentos por hora frente a lo esperado; varias semillas superpuestas.
6. Huecos y reescalado: por qué los huecos en minutos no son exponenciales y los reescalados sí (gráfico QQ).
7. Sobredispersión: Z por día, recuentos diarios frente a Poisson y binomial negativa; el índice de dispersión crece con el volumen.
8. Validación: las cinco pruebas sobre un año simulado y su tabla.
9. La meta-prueba: histograma de p-valores en muchas semillas y la proporción por debajo de 0,05.
10. Para experimentar: base, perfiles, CV, días y semillas, con preguntas guía.
11. Resumen: las lecciones del hito en pocas frases.

**Comprobaciones**

- El CI ejecuta los dos notebooks en modo rápido con `nbmake`.
- `pre-commit` verifica que se guardan sin resultados.

## Decisiones del hito

Cinco decisiones nuevas; si se confirman durante el hito, la tarea de cierre las convierte en los ADR 0019 a 0023 y las añade al registro del diseño.

| # | Decisión | Motivo |
| --- | --- | --- |
| 19 | Perfiles de llegadas en TOML: repartos horario y semanal en porcentaje y factores mensuales de tasa, normalizados a media 1 en el código | Parámetros en términos que entiende un clínico; `tomllib` sin dependencias; la base conserva su significado |
| 20 | λ(t) continua: interpolación lineal periódica entre los centros de las horas; día, mes y Z cambian a medianoche; reloj sin cambio de hora | Sin saltos artificiales a las en punto; Λ exacta con trapecios |
| 21 | *Thinning* de Lewis–Shedler perezoso, con cota por día comprobada | Exacto, sin integrar ni invertir Λ; funciona en vivo; la comprobación evita recortes silenciosos |
| 22 | Sobredispersión con un efecto diario gamma de media 1 parametrizado por el CV (6 % por defecto) y guardado como ground truth | El CV se puede trasladar entre centros, a diferencia del índice de dispersión; Z queda disponible para validar modelos |
| 23 | Validación con cinco pruebas (volumen, chi-cuadrado horario, KS de huecos reescalados, dispersión de Pearson con réplicas y uniformidad de p-valores) con umbral 0,01 y pruebas de potencia | Cada prueba busca un error distinto; el umbral limita las falsas alarmas al combinar pruebas |

## Tareas, ramas y orden de ejecución

Cada tarea empieza con una explicación breve del concepto, sigue con el plan en modo Plan y se ejecuta en modo Manual; al cerrarla se actualiza el anexo.

| # | Tarea | Rama | Resultado |
| --- | --- | --- | --- |
| 2.1 | Especificación en `docs/specs/hito-2.md`, perfil en TOML y función de tasa | `feat/h2-perfiles` | `profile.py` y `rate.py` con λ y Λ comprobadas a mano |
| 2.2 | Generador por *thinning* con flujos, semilla y proceso SimPy | `feat/h2-thinning` | Llegadas reproducibles con la cota comprobada |
| 2.3 | Efecto diario gamma y registros diarios (ground truth) | `feat/h2-sobredispersion` | Recuentos diarios con la varianza de la binomial negativa |
| 2.4 | Validación estadística, pruebas de potencia y tests `slow` | `feat/h2-validacion` | Las cinco pruebas en verde con semilla fija |
| 2.5 | CLI `llegadas generar` y `llegadas validar` con CSV y gráficas | `feat/h2-cli` | Tabla de validación y gráficas generadas por EDsim |
| 2.6 | Notebook `02_llegadas_exploracion.ipynb` | `feat/h2-notebook` | Notebook ejecutable de principio a fin en el CI |
| 2.7 | Cierre: ADRs, diario, anexo, exportación de pestañas y etiqueta `v0.2-hito2` | `docs/h2-cierre` | Hito cerrado |

**Flujo de git en cada tarea (nuevo en este hito)**

1. Claude Code parte de `main` actualizado y crea la rama: `git switch main && git pull && git switch -c <rama>`.
2. Hace un commit por paso, con prefijo (`feat`, `test`, `docs`…) y mensaje en español, después de que Pedro revise el diff.
3. Pide permiso para `git push -u origin <rama>` y abre el PR con `gh pr create`, con un resumen y las comprobaciones hechas.
4. Pedro revisa el PR, espera el CI en verde y fusiona con *squash and merge*. `gh pr merge` sigue denegado para Claude Code.
5. Sincronización: `git switch main && git pull && git branch -D <rama>`.

## Criterios de aceptación

El hito 2 está cerrado cuando se cumplen todos:

- [ ] `uv run pytest` pasa, incluidos los tests `slow`, y el CI está en verde.
- [ ] Con la misma semilla, dos ejecuciones dan llegadas y registros diarios idénticos.
- [ ] `edsim llegadas validar` con 364 días pasa las cinco pruebas, con CV 0 y con CV 0,06.
- [ ] Las pruebas de potencia detectan la base errónea, el perfil desplazado y el CV ignorado.
- [ ] `edsim llegadas generar` escribe `llegadas.csv` y `dias.csv`, y `validar` guarda sus tres gráficas.
- [ ] `notebooks/02_llegadas_exploracion.ipynb` se ejecuta de principio a fin en el CI y se versiona sin resultados.
- [ ] Pedro sabe explicar por qué el *thinning* es exacto, por qué los huecos en minutos no son exponenciales y por qué se calibra el CV y no el índice de dispersión.
- [ ] Todos los PRs del hito los abrió Claude Code y los fusionó Pedro.
- [ ] `docs/` contiene esta especificación, los ADR nuevos, la entrada del diario y el anexo de referencia del hito.
- [ ] La etiqueta `v0.2-hito2` existe en GitHub.

**Fuentes**: [Goicoechea et al., urgencias hospitalarias del SAS en 2012 a partir del CMBD](https://www.redalyc.org/pdf/170/17029591004.pdf) · [Whitt y Zhang, A data-driven model of an emergency department](https://par.nsf.gov/servlets/purl/10023792) · [Kim y Whitt (2014), Are call center and hospital arrivals well modeled by nonhomogeneous Poisson processes?](https://pubsonline.informs.org/doi/fpi/10.1287/msom.2014.0490) · [Lewis y Shedler (1979), Simulation of nonhomogeneous Poisson processes by thinning](https://ideas.repec.org/a/wly/navlog/v26y1979i3p403-413.html)

## Anexo: guía de referencia del hito 2

Este anexo se amplía al cerrar cada tarea del hito con lo que se hizo, los conceptos que aparecieron, las decisiones, los resultados medidos y las lecciones aprendidas. Sirve de referencia para repetir el trabajo o retomarlo más adelante. Las tareas aparecerán aquí a medida que se cierren, empezando por la 2.1.
