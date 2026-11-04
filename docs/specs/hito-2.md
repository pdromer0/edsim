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
- `SeedSequence(seed).spawn(2)` da dos flujos: **llegadas** (huecos de las candidatas y uniformes de aceptación) y **efecto diario** (Z). Los valores de Z de cada día no dependen del perfil horario ni de cuántas candidatas se sorteen, y los sorteos de Z no desplazan los de las candidatas. Activar Z sí cambia los instantes de las candidatas, porque la cota del día se multiplica por Z.
- `seed` admite `int | SeedSequence`, como `simulate_mm1`, para que las réplicas usen hijos de una semilla maestra.
- Con la misma semilla, llegadas y registros diarios son idénticos bit a bit; con semillas distintas, distintos. Ambas cosas se testean.

## Validación estadística

Cinco pruebas comprueban que las llegadas generadas son un Poisson no homogéneo con la λ(t) configurada; cada una busca un tipo de error distinto. Todas usan Λ con la Z real de cada día (del ground truth), de modo que valen con y sin sobredispersión.

| Prueba | Qué detecta | Cómo | Criterio |
| --- | --- | --- | --- |
| a. Volumen | Errores de escala y de normalización | Cociente observado/esperado de cada día (esperado sin Z), en total y por día de la semana, con `summarize` | 1 dentro del IC al 99 %, en total y en cada día de la semana (Bonferroni: cada uno de los 8 intervalos al 1 − 0,01/8) |
| b. Forma horaria | Perfil horario o interpolación incorrectos | Llegadas por hora del reloj sumadas en todos los días frente al área de λ, con chi-cuadrado (esperados reescalados al total observado, 23 grados de libertad) | p ≥ 0,01 |
| c. Propiedad de Poisson | Huecos mal generados, cota o aceptación incorrectas, bordes entre días | Huecos de los tiempos reescalados Λ(tᵢ) frente a una exponencial de media 1, con Kolmogórov–Smirnov | p ≥ 0,01 |
| d. Dispersión diaria | Z ausente, mal escalado o aplicado al día equivocado | Índice de Pearson P = media de (c − e)²/e por día, con e esperado sin Z; teoría: 1 sin Z y 1 + CV²·ē con Z. Además, Pearson condicional con e incluyendo la Z de cada día, cuya teoría es 1: si falla el primero, el error está en Z; si falla el condicional, en el Poisson de cada día. 20 réplicas de 364 días | Las dos teorías dentro de sus intervalos, cada uno al 1 − 0,01/2 = 99,5 % (Bonferroni) |
| e. Uniformidad de los p-valores | Sesgos pequeños que una sola semilla no ve | p-valores de la prueba c en 100 semillas de 14 días, contrastados con una uniforme mediante Kolmogórov–Smirnov | p ≥ 0,01 |

**Reglas**

- Semilla fija en los tests. Si uno falla, no se cambia la semilla: se analiza la causa (honestidad estadística del hito 1).
- Todas las pruebas usan un nivel de 0,01 (p ≥ 0,01 o intervalos al 99 %). Con cinco pruebas al 5 %, un generador correcto daría alguna falsa alarma en el 23 % de las validaciones; al 1 %, en el 5 %. Dentro de la prueba a, los ocho intervalos se corrigen con Bonferroni.
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
- `validar` imprime una tabla con una fila por prueba: estadístico, p-valor o IC, criterio y resultado, con los detalles debajo: los 8 intervalos de a y los dos Pearson de d. Además guarda `perfil_horario.png` (observado frente a esperado por hora), `qq_reescalado.png` y `recuentos_diarios.png` (histograma de los residuos diarios estandarizados, (c − e·Z)/√(e·Z) y (c − e)/√(e + CV²·e²), frente a una normal estándar; los recuentos crudos no se comparan con una sola binomial negativa porque mezclan días con medias distintas).
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
7. Sobredispersión: Z por día, recuentos diarios frente a Poisson y binomial negativa; el índice de dispersión crece con el volumen; por qué los recuentos crudos no se comparan con una sola binomial negativa, y la diferencia entre el Pearson sin Z (≈ 2,08) y el residuo estandarizado (≈ 1).
8. Validación: las cinco pruebas sobre un año simulado y su tabla, y la tabla de potencia (base 330, perfil desplazado, CV ignorado), que muestra qué detecta cada prueba y a qué está ciega.
9. La meta-prueba: histograma de p-valores en muchas semillas y la proporción por debajo de 0,05; el error de la medianoche (C′) con varias semillas, para ver qué significa una potencia del 13 %.
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
| 23 | Validación con cinco pruebas (volumen, chi-cuadrado horario, KS de huecos reescalados, dispersión de Pearson con réplicas y uniformidad de p-valores) al nivel 0,01, con Bonferroni dentro de a (8 intervalos) y de d (Pearson sin Z y condicional), y pruebas de potencia | Cada prueba busca un error distinto; el umbral limita las falsas alarmas al combinar pruebas |

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

Este anexo se amplía al cerrar cada tarea del hito con lo que se hizo, los conceptos que aparecieron, las decisiones, los resultados medidos y las lecciones aprendidas. Sirve de referencia para repetir el trabajo o retomarlo más adelante.

### Tarea 2.1: perfil de llegadas y función de tasa

**Qué se hizo**

- La especificación se exportó a `docs/specs/hito-2.md`. En `CLAUDE.md`, el hito en curso apunta ahora al hito 2 y las claves de configuración son de ficheros TOML.
- Primera tarea en la que Claude Code ejecutó git: creó la rama `feat/h2-perfiles`, hizo cuatro commits, el push con permiso y abrió el PR #12. Pedro lo fusionó con *squash and merge*.
- `config/llegadas.toml` contiene el perfil del centro base, igual que en la especificación.
- `src/edsim/arrivals/profile.py`: `ArrivalProfile` inmutable, que se valida y normaliza en `__post_init__`, y `load_profile(path)` con `tomllib`. Rechaza claves que faltan o sobran, `nan` e `inf`, valores no numéricos (booleanos incluidos), ceros, negativos y fechas con hora. Los errores nombran la clave y la posición: `reparto_horario[3] must be positive, got -1.0`.
- `src/edsim/arrivals/rate.py`: `rate(t, profile)` y `cumulative_rate(t, profile)`, vectorizadas (un escalar devuelve `float`; un array, un array). λ es la escala del día (B/1440 · d · m) multiplicada por la forma horaria. El día de la semana y el mes se calculan con `datetime64`. Λ usa una tabla de 26 nodos con las áreas acumuladas y suma los días completos con una suma acumulada.
- Tests: 20 funciones en `tests/test_profile.py` y 12 en `tests/test_rate.py`, varias parametrizadas, con un perfil propio en `tests/data/llegadas_ejemplo.toml` y un test que comprueba que el fichero de configuración real se carga y es válido. La suite completa (181 tests, incluidos los `slow`) y ruff quedaron en verde.

**Conceptos**

- **TOML y `tomllib`.** TOML admite comentarios y tipos reales; `fecha_inicio = 2026-01-05` llega como `datetime.date`. `tomllib` solo lee y exige abrir en binario (`"rb"`).
- **Validar al construir.** Si la validación vive en `__post_init__`, no puede existir un perfil inválido, se construya como se construya. El resto del código no repite comprobaciones.
- **Normalizar ponderando por días.** El factor mensual cumple Σ m·días/365 = 1. Con los valores escritos esa media era 1,0007; tras normalizar, enero queda en 1,0992 y septiembre en 0,9393.
- **Del minuto al calendario.** Día = t // 1440, día de la semana y mes de la fecha correspondiente. `datetime64` resuelve la duración de los meses y el cambio de año.
- **Interpolación periódica.** `np.interp(..., period=24)` une las 23:30 con las 0:30 del día siguiente sin código adicional.
- **Λ exacta con trapecios.** Con λ lineal a trozos, el área de cada tramo es un trapecio. `scipy.integrate.quad` sirve como comprobación independiente en los tests, integrando día a día porque d y m saltan a medianoche.
- **Autoconsistencia frente a referencia externa.** Comprobar λ contra Λ (`quad`, derivada) verifica que el código es coherente consigo mismo, pero no que sea correcto. Para eso hacen falta valores calculados a mano.

**Decisiones**

- Los factores se guardan como tuplas: inmutables y comparables con `==`. Los campos aceptan pesos positivos cualesquiera y guardan los factores normalizados; normalizar dos veces no cambia nada.
- Mensajes de error en inglés, como en el hito 1, pero con la clave TOML en español, que es la que conoce quien edita el fichero.
- λ = escala del día × forma horaria: el efecto diario Z de la tarea 2.3 entrará como un factor más de la escala del día, sin reescribir `rate.py`.
- Los tests usan su propio perfil de ejemplo: recalibrar `config/llegadas.toml` no rompe los valores a mano.
- Las decisiones 19 y 20 del hito (TOML normalizado y λ continua) quedan confirmadas en la práctica.

**Resultados: valores a mano frente al código** (perfil de ejemplo, lunes 2026-01-05)

| Cantidad | A mano | Código |
| --- | --- | --- |
| λ(11:30) | 0,43815 por minuto | 0,438152 |
| λ(11:00) | 0,42563 por minuto | 0,425634 |
| Λ del día completo | 375,559 | 375,5592 |
| Λ de 0:00 a 1:00 | 10,187 | 10,18704 |

Λ coincide además con `quad` día a día durante 35 días (cruzando a febrero) y en tramos parciales, con tolerancia relativa de 10⁻⁹.

**Comprobación con versiones incorrectas** (temporales, deshechas con `git restore`)

| Versión incorrecta | Tests que fallan | Tests que pasan | Predicción |
| --- | --- | --- | --- |
| A. λ con escalones y Λ con rectángulos | λ(11:00) a mano; continuidad en las horas en punto (22 de 23); enlace 23:30–0:30; Λ(0–1 h) = 10,140; cambio de día a medianoche | Centros de hora, λ(11:30), Λ del día, `quad` y derivada | Acertada, salvo el cambio de día a medianoche, que no se predijo |
| B. Factor mensual con media simple | Los dos tests del factor mensual ponderado; λ(11:30) = 0,438111; Λ del día = 375,524 | Los que se calculan con el propio perfil | Acertada |

**Lecciones aprendidas**

- **La autoconsistencia no basta.** Con escalones, λ y Λ seguían siendo coherentes entre sí, y `quad` y la derivada pasaban. Solo los valores a mano y la continuidad detectaron el error.
- **Los errores pequeños necesitan tolerancias estrechas.** La media simple cambia el factor mensual en un 0,01 %; solo lo detectan los tests con referencia externa y tolerancia ajustada.
- **Por qué 22 de 23.** A las 17:00 los repartos de las 16 h y las 17 h son iguales (6,2 %), así que el escalón no salta. Un test de continuidad solo ve saltos donde hay diferencia: comprobar todas las horas evita depender de una sola.
- **La sorpresa de la medianoche.** El test del cambio de día compara λ justo antes y justo después de las 0:00 con el cociente d\_mar/d\_lun, lo que supone que la forma horaria es continua. Con escalones la forma también salta (de h₂₃ a h₀) y el test falla. Predecir antes de romper obliga a entender qué supone cada test.
- **Código y configuración, por separado.** Un perfil fijo para los tests y un test aparte para el fichero real distinguen "el código es correcto" de "la configuración es válida".
- **Git a cargo de Claude Code.** En modo Plan no puede ejecutar comandos que cambian el repositorio; hay que pasar a Manual. `git push`, `git branch -D` y `git fetch` piden permiso; la sincronización de `main` se hace con una cadena `&&` después de que Pedro fusione.

### Tarea 2.2: generador por *thinning*

**Qué se hizo**

- `src/edsim/arrivals/thinning.py`: `ArrivalRecord` y `DayRecord` (dataclasses congeladas con slots), `iter_arrivals`, `simulate_arrivals` y `arrival_source`. PR #13, fusionado por Pedro.
- `iter_arrivals(profile, days, seed, *, on_day=None, bound_factor=1.0)` aplica Lewis–Shedler con cota por día (escala del día × máx(h)), comprobada en cada candidata con un margen relativo de 10⁻¹². Si λ la supera, lanza `RuntimeError`. Valida los argumentos en la llamada y devuelve un generador interno, así que un `days=0` falla al llamar y no al pedir la primera llegada.
- Los `DayRecord` se emiten con el callback `on_day` al cerrar cada día. En esta tarea `day_effect = 1` y `cv_diario` se ignora, hasta la tarea 2.3.
- `arrival_source` es un proceso SimPy que espera `max(0, time − env.now)` y entrega el registro original. Acepta una tupla o el propio generador perezoso.
- `rate.py` expone `day_scale(day, profile)` y `shape(minutes, profile)`: λ = escala × forma, idéntica bit a bit a `rate()`. La forma interpola sobre los nodos de `_shape_knots`, cacheados por perfil y de solo lectura.
- 26 tests en `tests/test_thinning.py` y tres en `tests/test_rate.py`; la suite queda en 213 tests.

**Conceptos**

- **Generadores de Python.** Una función con `yield` entrega valores bajo demanda y se queda en pausa. La siguiente candidata no se sortea hasta que se pide la siguiente llegada, lo que permitirá funcionar en vivo con *shocks*.
- **Validar fuera del generador.** Una función normal que valida y devuelve el generador falla en la llamada; un generador puro no ejecuta nada hasta el primer `next()`.
- **Reinicio exacto a medianoche.** La candidata que pasa de las 0:00 se descarta y el día siguiente empieza a las 0:00 con su cota. Es exacto porque la exponencial no tiene memoria.
- **Cota y eficiencia.** Con máx(h) = 1,68, la proporción de aceptación es 1/1,68 = 59,5 % cualquier día, porque d y m afectan igual a λ y a la cota. La cota del lunes 5 de enero es 0,43815 por minuto, exactamente λ(11:30): la cota es el pico del día.
- **Dos flujos desde el principio.** `SeedSequence(seed).spawn(2)`: el primero para las candidatas (hueco y, solo si cae dentro del día, uniforme), el segundo reservado para Z. Activar Z no cambiará la secuencia de candidatas.
- **Coma flotante.** La comprobación de la cota necesita un margen ínfimo, y en SimPy `env.now` acumula retrasos y puede diferir del instante generado en la última cifra.
- **El *thinning* es exacto con cualquier cota que domine a λ**, aunque cambie en el instante de una candidata, porque se fija antes de saber si llega la siguiente.

**Decisiones**

- `on_day` como callback, en lugar de mezclar llegadas y días en el mismo generador, para que ningún consumidor tenga que filtrar por tipo.
- `bound_factor` como punto de inyección para tests y para el notebook, validado como finito y positivo.
- `RuntimeError` para la cota insuficiente: no es una entrada inválida, sino una regla interna del algoritmo que se rompe.
- La candidata que pasa de medianoche no cuenta como candidata ni gasta uniforme, para que `accepted/candidates` estime 1/1,68 sin sesgo.
- Orden de los sorteos fijado: primero el hueco y después la uniforme. Una optimización que sortee por bloques cambiaría la secuencia y tendría que ser una decisión consciente.

**Resultados**

Rendimiento de `simulate_arrivals` con 364 días (183.515 candidatas, 109.384 llegadas; mediana de 3 ejecuciones):

| Versión | Tiempo |
| --- | --- |
| `rate()` escalar en cada candidata | 4,76 s |
| Escala calculada una vez por día y forma pública | 2,41 s |
| Forma con `np.interp` sin `period` sobre los nodos cacheados | 0,67 s |

Las llegadas son idénticas bit a bit en las tres versiones (misma huella SHA-256 de los registros).

**Comprobación con versiones incorrectas**

| Versión incorrecta | Predicción | Observado |
| --- | --- | --- |
| A. `rng.exponential(cota)` en lugar de `rng.exponential(1/cota)` | Solo falla el volumen | Acertada: solo falla `test_volumen_56_dias`, con 110.353 llegadas de más sobre unas 16.800 |
| B. Cota con la media del perfil en lugar del máximo | Fallan los tests que simulan un día completo; pasan los de semillas | El `RuntimeError` salta el lunes a las 9:05 (λ = 0,294 > 0,261). Los tests de semillas también fallan: dependen del *fixture* que lanza el error |
| C′. Tras medianoche, el día siguiente arranca en el instante de la candidata descartada | Ningún test rápido lo detecta | Acertada: pasan los 26 tests |

La versión C propuesta inicialmente (evaluar con la cota del día anterior la candidata que pasa de medianoche) se descartó porque no es un error: a las 0:00, λ vale unas 0,73 veces la escala, por debajo de la cota del día anterior (1,68 veces su escala).

**Déficit medido de C′** (364 días; observadas menos esperadas)

|  | Primera media hora, semilla 2026 | z en la primera media hora | z del total anual | Media de 10 semillas |
| --- | --- | --- | --- | --- |
| C′ | −116,3 (sobre 1.569,3 esperadas) | −2,94 | −0,38 | −156,0 ± 11,3 (−0,43 al día) |
| Versión correcta | +4,7 | +0,12 | +0,66 | −7,1 ± 11,6 |

La predicción era −0,44 llegadas al día (λ a las 0:00 por el hueco medio de 1/cota ≈ 2,3 minutos).

**Lecciones aprendidas**

- **Un error puede no serlo.** La versión C parecía un fallo y era estadísticamente correcta. Antes de buscar un test que la detecte, hay que razonar si de verdad cambia el resultado.
- **Los errores localizados se diluyen en las pruebas globales.** C′ es invisible en el total anual y solo aparece al mirar la primera media hora. Es la pregunta de potencia para la tarea 2.4.
- **Un *fixture* compartido propaga los fallos.** Con B, los tests de semillas cayeron con el *fixture* que lanzaba el error: predecir obliga a mirar de qué dependen los tests, no solo qué comprueban.
- **Espiar mejor que cronometrar.** `test_perezoso` sustituye funciones por versiones que registran sus llamadas y comprueba que solo se calcula el día 0. Es más fiable que medir el tiempo en un CI lento.
- **Medir antes de optimizar.** El 70 % del tiempo estaba en `np.interp` con `period`, que ordena los nodos en cada llamada. La mejora vino de quitar trabajo repetido, sin duplicar la implementación de la forma horaria.
- **Pendiente para la tarea 2.3.** `expected` se calcula con dos llamadas a `cumulative_rate`, que cuesta O(día) por día. Al añadir Z conviene calcularlo como Z · escala · área del día.

### Tarea 2.3: efecto diario Z y sobredispersión

**Qué se hizo**

- El *thinning* sortea una Z por día, gamma de media 1 con forma k = 1/CV² y escala θ = CV², desde su propio flujo y de forma perezosa al empezar cada día. Con `cv_diario = 0`, Z = 1 sin sortear. La cota pasa a ser Z · escala · máx(h) y λ = (Z · escala) · forma. PR #14, fusionado por Pedro.
- `DayRecord.day_effect` guarda Z y `DayRecord.expected` es Z · escala · área del día, en O(1), sin llamar a `cumulative_rate`. Resuelve la observación pendiente de la tarea 2.2.
- `rate` y `cumulative_rate` aceptan `day_effects` (solo por nombre), con errores claros. Λ al final de n días solo necesita las n Z recorridas. λ con Z coincide bit a bit con la del *thinning*.
- Funciones públicas nuevas: `day_shape_area(profile)` en `rate.py` y `draw_day_effects(daily_cv, days, seed)` en `thinning.py`, que devuelve las Z que usaría un run con esa semilla. El caché de `_shape_knots` queda acotado con `lru_cache(maxsize=8)`.
- `src/edsim/seeds.py` con `child_streams(seed, n)`: los hijos de una semilla sin modificar el `SeedSequence` (ver lecciones). `mm1.py` se migrará en la tarea de cierre.
- La suite queda en 258 tests, incluido el nuevo test `slow` del índice de Pearson.

**Conceptos**

- **Gamma de media 1 con el CV como parámetro.** Media kθ = 1 y varianza kθ² = CV² dan k = 1/CV² y θ = CV²; con CV 0,06, k = 277,78 y θ = 0,0036. `rng.gamma` de NumPy recibe la escala, no la tasa.
- **Mezcla de Poisson y gamma.** Conocida Z, el día es un Poisson de media Z·e. Sin conocerla, el recuento es una binomial negativa de media e y varianza e + (CV·e)². Para el lunes 5 de enero (e = 375,56): 883,3 frente a 375,6 de Poisson.
- **Índice de Pearson.** P = media de (c − e)²/e, con e esperado sin Z. Vale 1 sin sobredispersión y 1 + CV²·ē con ella. Su error típico es P·√(2/n), así que medir una varianza necesita muchos días.
- **Qué garantiza un flujo propio.** La Z de cada día depende solo de la semilla y del CV, no del perfil ni de las candidatas, y sus sorteos no desplazan los de las candidatas. Activar Z sí cambia las candidatas, porque la cota se multiplica por Z. La especificación decía lo contrario y se corrigió.
- **Tests de instantánea.** Una huella SHA-256 de las llegadas de `main` asegura que, con CV 0, todo sigue igual bit a bit. Su comentario explica el origen y cuándo es legítimo regenerarla: solo si cambia a propósito el orden de los sorteos, nunca para que un test pase.

**Decisiones**

- `child_streams` en un módulo compartido, para que el arreglo de la semilla viva en un único sitio.
- `day_effects` solo por nombre, para no confundirlo con t, y con el mismo orden de multiplicaciones en `rate` y en el *thinning* para que coincidan bit a bit.
- `draw_day_effects` usa el mismo iterador privado que el *thinning*: el notebook podrá enseñar las Z sin una segunda implementación.
- El perfil con CV 0 de los tests se carga de una copia del TOML: `dataclasses.replace` vuelve a normalizar y cambia el último bit de los factores.

**Resultados**

| CV | Índice de Pearson medido (1.092 días) | Teoría 1 + CV²·ē | Tolerancia |
| --- | --- | --- | --- |
| 0 | 0,942 | 1,000 | ±0,171 |
| 0,06 | 2,091 | 2,080 | ±0,356 |

Con CV 0,06, las 1.092 Z tienen media 0,998 y CV 0,0615. El sorteo de Z no cambia el tiempo de forma medible: es un sorteo por día frente a unas 500 candidatas (entre 0,6 y 0,9 s para 364 días, según el ruido de la máquina).

**Comprobación con versiones incorrectas**

| Versión incorrecta | Predicción | Observado |
| --- | --- | --- |
| A. `rng.gamma(1/CV, CV)`: confunde CV con CV² | Fallan el CV de Z, k y θ a mano y P con CV 0,06 (≈ 19) | Acertada: CV de Z 0,245, k = 16,7 y P = 19,7 |
| B. Z en λ pero no en la cota | `RuntimeError` en los runs con CV 0,06; con CV 0 todo pasa | Acertada: 6 fallos y 14 errores, todos `RuntimeError` |
| C. Z sorteada con el flujo de las llegadas | Fallan la independencia respecto a la base y la igualdad con `draw_day_effects` | Acertada, y falla además `test_mismo_seedsequence_dos_veces`, que también compara con `draw_day_effects` |
| D. `expected` sin multiplicar por Z | Fallan expected, la aceptación teórica y los valores a mano con Z | Acertada: aceptación teórica 0,577 en lugar de 0,595 |

**Lecciones aprendidas**

- **El error de `SeedSequence.spawn`.** `spawn` no es una operación neutra: el objeto lleva la cuenta de los hijos creados, y la segunda llamada entrega hijos distintos. En `main`, pasar dos veces el mismo `SeedSequence` a `simulate_arrivals` daba llegadas distintas, y lo mismo ocurre en `simulate_mm1`. Los tests no lo veían porque siempre usaban enteros o un objeto nuevo; el error solo aparece al reutilizar el objeto, que es lo que harán las réplicas y los notebooks. Lección: probar también la forma en que el código se usará, no solo la forma en que se escribió el test.
- **Fijar el comportamiento de una librería con un test.** `test_spawn_de_numpy_muta_el_objeto` documenta lo que hace NumPy hoy; si cambia en una versión futura, el test avisará de que el arreglo puede sobrar.
- **La comprobación de la cota vuelve a pagar.** La versión B la detecta sin ningún test específico: la regla interna de la tarea 2.2 atrapa errores de tareas posteriores.
- **Errores que no cambian la estadística.** La versión C da Z correctas en distribución y solo la detectan los tests de independencia de flujos. Rompería los números aleatorios comunes del hito 9, así que esos tests son necesarios aunque ninguna prueba estadística falle.
- **Un test detecta todo aquello de lo que depende.** C hizo fallar un test que no estaba en la predicción porque también usaba `draw_day_effects`; es la misma lección del *fixture* de la tarea 2.2.
- **La especificación también se revisa.** Preparar la tarea destapó una frase inexacta sobre los flujos; se corrigió en el documento antes de escribir el código.
- **Pendiente para la tarea 2.4.** `pearson_index` vive en `test_thinning.py`; debe pasar a `validation.py` como prueba d y el test debe usarla. Y lo esperado sin Z de cada día es `expected / day_effect`.

### Tarea 2.4: validación estadística

**Qué se hizo**

- `src/edsim/arrivals/validation.py` con cinco pruebas puras, que reciben registros y perfil y no simulan: `check_volume` (a), `check_hourly_shape` (b), `check_rescaled_gaps` (c), `check_dispersion` (d) y `check_p_uniformity` (e). Todas devuelven un `ValidationResult` congelado, con `details` para las pruebas con varios intervalos. PR #15, fusionado por Pedro.
- `validate_arrivals(profile, days=364, replicas=20, seed=2026, *, short_runs=100, short_days=14)` orquesta la validación completa con `child_streams(seed, 3)`: una ejecución larga para a–c, R réplicas para d y ejecuciones cortas para e. Añadir réplicas no cambia la ejecución larga. Devuelve también los registros, para las gráficas de la tarea 2.5.
- `pearson_index` se movió desde los tests al paquete, y se añadió `conditional_pearson_index`.
- 30 tests rápidos con datos construidos a mano y tests `slow` de aprobado (CV 0 y 0,06) y de potencia. 284 tests rápidos (≈ 5 s) y 42 s de tests `slow` en total.

**Conceptos**

- **Comparaciones múltiples.** Con cinco pruebas al 5 %, un generador correcto da alguna falsa alarma en el 23 % de las validaciones (1 − 0,95⁵); al 1 %, en el 5 %. Una prueba con varios intervalos reparte el 1 % entre ellos (Bonferroni): 8 intervalos al 99,875 % en a y 2 al 99,5 % en d.
- **La hipótesis sale del perfil.** Lo esperado se calcula con el perfil contra el que se valida. De los registros solo se toman los hechos (llegadas, recuentos) y Z, que es *ground truth*. `DayRecord.expected` no se usa: lo escribió el generador con su propio perfil, y una prueba basada en él compararía el generador consigo mismo.
- **Pearson condicional.** Con lo esperado incluyendo Z, la teoría es 1. Si falla el Pearson sin Z, el error está en Z; si fallan los dos, en el Poisson de cada día.
- **Potencia: validar al validador.** Cada prueba tiene que pasar con el generador correcto y fallar con uno incorrecto. Una prueba que nunca falla no prueba nada.
- **Potencia de un chi-cuadrado frente a un error localizado.** Un déficit que aporta unos 8,6 puntos a un chi-cuadrado de 23 grados de libertad tiene una potencia del 13 % al 1 % (chi-cuadrado no central): la prueba lo detecta a veces, y no se puede confiar en ella para eso.

**Decisiones**

- Todo al nivel 0,01, con Bonferroni dentro de a y de d (decisión 23 actualizada en la especificación).
- El Pearson condicional cuenta para decidir d, no es solo informativo.
- `ValidationResult` y no `TestResult`: pytest intentaría recoger como test cualquier clase llamada `Test*`.
- Claves de las pruebas en inglés (`volume`, `hourly_shape`…) y criterios en notación matemática; las etiquetas en español son cosa de la CLI.

**Resultados: validación con semilla fija** (364 días, 20 réplicas, 100 ejecuciones de 14 días, semilla 2026)

| Prueba | CV 0 | CV 0,06 |
| --- | --- | --- |
| a. Volumen (total) | 1,0012, IC \[0,9911; 1,0112\] | 1,0029, IC \[0,9895; 1,0162\] |
| b. Forma horaria | χ² = 11,58, p = 0,977 | χ² = 22,52, p = 0,489 |
| c. Huecos reescalados | D = 0,0023, p = 0,621 | D = 0,0032, p = 0,203 |
| d. Pearson sin Z | 1,010 frente a 1 | 2,106 frente a 2,080 |
| d. Pearson condicional | 1,010 frente a 1 | 1,012 frente a 1 |
| e. Uniformidad de los p-valores | D = 0,052, p = 0,934 | D = 0,056, p = 0,893 |

Las cinco pruebas pasan en los dos casos, y los siete días de la semana tienen cocientes entre 0,984 y 1,015.

**Resultados: potencia** (qué detecta cada prueba)

| Caso | a. Volumen | b. Forma | c. Huecos | d. Dispersión |
| --- | --- | --- | --- | --- |
| Base 330 validada contra 300 | Falla (1,103) | Pasa | Falla | Fallan las dos |
| Perfil horario desplazado 1 h | Pasa | Falla (χ² = 3049) | Falla | Pasan las dos |
| CV 0,06 validado como 0 | Pasa | Pasa | Pasa | Falla sin Z (2,11 frente a 1); pasa la condicional |

Cada prueba ve un tipo de error distinto y ninguna los ve todos. b no ve el volumen porque reescala al total; c ve volumen y forma, pero no la sobredispersión; el Pearson condicional pasa con el CV mal especificado porque el Poisson de cada día está bien.

**Comprobación con versiones incorrectas del validador**

| Versión incorrecta | Predicción | Observado |
| --- | --- | --- |
| A. KS con los huecos en minutos, sin reescalar | Fallan c y e con el generador correcto | Acertada: c con D = 0,47 y e con D = 1,00, p ≈ 0 |
| B. Pearson de d con lo esperado con Z | Con CV 0,06, P ≈ 1 frente a 2,08: d falla | Acertada: 1,0115 frente a 2,080 |
| C. Chi-cuadrado sin Z en los esperados (CV 0,06) | No cambia: Z escala días enteros y el reescalado al total la cancela | Acertada: iguales en 13 cifras |

**El caso C′** (error de la medianoche de la tarea 2.2, aplicado de forma temporal; 364 días, semilla 2026)

|  | b. Forma horaria | c. Huecos | a. Volumen |
| --- | --- | --- | --- |
| CV 0 | χ² = 30,45, p = 0,137: pasa | p = 0,028: pasa | Pasa |
| CV 0,06 | χ² = 55,17, p = 0,0002: falla | p = 0,396: pasa | Pasa |

La predicción era una potencia de b de alrededor del 13 %. Con CV 0,06, la semilla 2026 perdió 292 llegadas en la hora 0, frente a una media de unas 150, y b lo detectó; con CV 0, no. En 20 semillas el déficit medio fue de 141 ± 11 (CV 0) y 150 ± 12 (CV 0,06), unas 0,40 llegadas al día, cerca de las 0,44 predichas.

**Lecciones aprendidas**

- **Si la hipótesis sale de los datos, la validación no valida nada.** Usar `DayRecord.expected` habría hecho imposible cualquier prueba de potencia. Un test lo protege.
- **Varias pruebas, varios puntos de vista.** La tabla de potencia muestra que cada prueba está ciega a algo; solo el conjunto cubre los errores importantes.
- **Una potencia baja detecta a veces.** C′ se detectó con una semilla y no con otra. Para errores pequeños y localizados hacen falta pruebas dirigidas o tests de regresión: la huella de la tarea 2.2 lo detecta siempre.
- **Dos tipos de test.** Los estadísticos ven errores grandes en cualquier parte; los de regresión ven cualquier cambio en un sitio concreto. Se necesitan los dos.
- **El Pearson sin Z mezcla variabilidad y sesgo.** Con base 330 salió 5,3 y no 4: el sesgo de un 10 % aporta (0,1·e)²/e = 3. Por eso el volumen tiene su propia prueba.
- **Incluir Z en los esperados de b no cambia nada hoy.** Importará cuando la forma horaria dependa del día, por ejemplo en fines de semana.

### Tarea 2.5: CLI `edsim llegadas generar` y `edsim llegadas validar`

**Qué se hizo**

- `src/edsim/arrivals/report.py`, sin argparse: `format_validation` (tabla en español con los detalles indentados), `config_fingerprint`, `write_arrivals_csv`, `write_days_csv` y tres gráficas que devuelven la figura (`plot_hourly_profile`, `plot_rescaled_qq`, `plot_daily_residuals`). PR #16, fusionado por Pedro.
- En `validation.py`, funciones públicas nuevas: `hourly_counts` (la usan la prueba b y la gráfica), `hour_of_day` (la usan la prueba b y la columna `hora` del CSV) y `daily_residuals`. `ValidationResult` gana el campo `confidence`.
- `cli.py`: `edsim llegadas generar` y `edsim llegadas validar`, con `--config`, `--dias`, `--semilla`, `--salida`, `--replicas` y `--ejecuciones-cortas`. `main` devuelve el código de salida.
- 32 tests nuevos; la suite queda en 325 tests, con 45 s de tests `slow`.

**Conceptos**

- **CLI fina.** La CLI lee argumentos, llama al paquete y escribe; la tabla, los CSV y las gráficas viven en `report.py` y se prueban sin terminal.
- **Tres códigos de salida.** 0 si todo va bien; 1 si la validación se ejecuta y alguna prueba falla, escribiendo igualmente las gráficas para diagnosticar; 2 para errores de uso, sin crear ningún fichero. Con el 1, `edsim llegadas validar && siguiente_paso` se detiene si el perfil no pasa.
- **Trazabilidad con huella.** Cada fila de los CSV lleva la ruta de la configuración, los 12 primeros caracteres de su SHA-256, los días y la semilla. Si el TOML cambia, la huella cambia.
- **Por qué no un histograma de recuentos crudos.** Un año mezcla lunes con sábados y enero con septiembre: el histograma sería una mezcla de distribuciones, más ancha que cualquier binomial negativa. Se estandariza cada día con su propia media y varianza: (c − e·Z)/√(e·Z) y (c − e)/√(e + CV²·e²), frente a una normal estándar.
- **Pearson frente a residuo estandarizado.** El Pearson sin Z divide por la varianza de Poisson y mide la variabilidad *por encima* de Poisson (≈ 2,08 con CV 6 %). El residuo sin Z divide por la varianza de la binomial negativa y comprueba que *el modelo la explica* (desviación típica ≈ 1 si el CV es el correcto). Las dos cifras son coherentes: 2,106/2,080 = 1,013, cuya raíz es 1,006.

**Decisiones**

- `hourly_counts` devuelve lo esperado ya reescalado al total, exactamente lo que recibe el chi-cuadrado: la gráfica enseña lo mismo que la prueba compara.
- Los residuos de `recuentos_diarios.png` salen de las 20 réplicas de la prueba d (7.280 días), no solo de la ejecución larga.
- `fecha_hora` se trunca a segundos en vez de redondear: así fecha, día de la semana y hora coinciden siempre con los que usa la validación (1439,9999999 minutos son las 23:59:59 del día 0, no las 0:00 del día 1).
- `confidence` como campo de `ValidationResult`, para escribir el criterio en español sin analizar el texto en inglés.
- Los commits añaden los ficheros por su nombre, porque `docs/specs/hito-2.md` tenía cambios locales que no pertenecían a la tarea.

**Resultados**

- `edsim llegadas validar` con los valores por defecto: 16,9 s, 205 MB de memoria, código de salida 0, y la misma tabla que la tarea 2.4 con CV 0,06 (misma semilla, mismo resultado).
- `edsim llegadas generar` con los valores por defecto: 9.268 llegadas en 28 días.
- Residuos de la gráfica con el perfil correcto: desviación típica 1,005 (condicional) y 1,006 (sin Z).
- Test `slow` con la hipótesis CV 0 sobre datos de CV 0,06: residuo sin Z con desviación típica 1,451 (teoría √2,08 = 1,442) y condicional 1,005. La gráfica detecta un CV mal especificado, aunque desde la CLI ese caso no se vea.

**Lecciones aprendidas**

- **Una función, dos consumidores.** Extraer `hourly_counts` y `hour_of_day` garantiza que la gráfica, el CSV y la prueba nunca discrepen.
- **Probar lo que la interfaz no enseña.** Como `validar` genera y valida con el mismo perfil, la capacidad de la gráfica de residuos para detectar un CV erróneo solo se puede probar en el paquete.
- **Dos cifras que parecen contradecirse pueden medir cosas distintas.** Pearson 2,1 y residuo 1,0 son el mismo dato visto con dos varianzas de referencia.
- **Pendiente para el cierre.** Si `--salida` apunta a un fichero existente, `mkdir` lanza un error de Python en lugar del código 2; y `validar` imprime la cabecera antes de comprobar los límites de `--dias` y `--replicas`.

### Tarea 2.6: notebook de exploración de las llegadas

**Qué se hizo**

- `notebooks/02_llegadas_exploracion.ipynb`, con las secciones 0 a 11: explicación, código que solo llama a `edsim`, gráfica, "Para experimentar" y "Lo que debes recordar". Modo rápido desde una única celda de parámetros. PR #17, fusionado por Pedro.
- Lo que el notebook necesitaba entró al paquete con tests:
  - `on_candidate` en `iter_arrivals` y `simulate_arrivals`, con `CandidateRecord(time, height, accepted)`: el notebook dibuja el *thinning* del generador real, con las llegadas idénticas bit a bit;
  - `src/edsim/arrivals/faults.py`, con `midnight_lags` y `midnight_restart_fault`, que reproducen C′ sin tocar el generador;
  - `interval_counts` (sobre la que ahora se apoya `hourly_counts`) y `validate_arrivals(..., hypothesis=...)`, que genera con un perfil y valida contra otro;
  - `day_effect_distribution` y `daily_count_distribution`, las distribuciones teóricas de Z y del recuento diario.
- `CLAUDE.md` documenta el comando del modo normal y que el límite de `nbmake` es por celda.
- La suite queda en 365 tests, con 69 s de tests `slow`.

**Conceptos**

- **Observar sin intervenir.** Un gancho opcional deja ver el interior de un algoritmo (las candidatas descartadas) sin una segunda implementación y sin cambiar ningún sorteo.
- **Reproducir un error como perturbación.** Por la falta de memoria de la exponencial, borrar las llegadas de \[0:00, 0:00 + E) de cada día, con E exponencial de media 1/cota del día anterior, equivale en distribución a C′. El código correcto se queda correcto y el error se estudia con muchas semillas.
- **Mezcla de distribuciones.** Los recuentos de un año son una mezcla de binomiales negativas con medias distintas, más ancha que cualquiera de ellas.
- **Juntar ejecuciones multiplica la potencia.** Una prueba que detecta un error en el 12 % de las semillas lo detecta con claridad si se juntan los p-valores de muchas.
- **El *timeout* de `nbmake` es por celda.** Se verificó en el código de `nbmake` y `nbclient` y con una prueba manual. La lección de la tarea 1.6 se corrigió en el anexo del hito 1.

**Decisiones**

- `on_candidate` recibe un `CandidateRecord`, como `on_day` recibe un `DayRecord`.
- Las perturbaciones viven en `faults.py`, separadas del modelo y de la validación: son versiones incorrectas para enseñar y medir potencia. Tienen su propio flujo aleatorio.
- C′ corrige `accepted`, que usan las pruebas a y d, y deja `candidates`, que no se puede reconstruir desde los registros.
- La aritmética didáctica de una o dos líneas (el porcentaje mensual, los escalones) y el formato de la tabla de potencia se quedan en el notebook, como el IC a mano del notebook 01.

**Resultados**

| Medida | Valor |
| --- | --- |
| Tiempo en modo normal | 178–195 s; celda más larga 62 s (tabla de potencia) |
| Tiempo en modo rápido (los dos notebooks, como el CI) | 12,6 s |
| Eficiencia del *thinning* en un año | 0,5957 (teoría 1/1,68 = 0,5952) |
| Coeficiente de variación de los huecos | 1,36 en minutos; 0,996 reescalados |
| Varianza de los recuentos crudos de un año | 1.084, frente a 624 de una sola binomial negativa y 1.169 de la mezcla de los 364 días |
| Pearson sin Z (10 años) | 2,00 (teoría 2,08); varianza del residuo sin Z 0,96 |
| Meta-prueba con el generador correcto (300 ejecuciones) | p < 0,05 en el 3,3 %; uniformidad p = 0,58 |

**C′ con 50 semillas de 364 días** (semillas en las que cada prueba detecta el error)

| Generador | a. Volumen | b. Forma horaria | c. Huecos |
| --- | --- | --- | --- |
| Correcto | 0/50 | 0/50 | 1/50 |
| C′ | 1/50 | 6/50 (12 %) | 2/50 |

La prueba b detecta C′ en el 12 % de las semillas, frente al 13 % de potencia teórica de la tarea 2.4. Con los p-valores de b de las 50 semillas juntos, la uniformidad da p = 5,7·10⁻⁹ con C′, frente a p = 0,77 con el generador correcto. El déficit medio fue de 0,432 llegadas al día (teoría 0,44).

**Lecciones aprendidas**

- **La teoría se confirma con datos.** La potencia del 13 % calculada con un chi-cuadrado no central en la tarea 2.4 salió un 12 % con 50 semillas.
- **Una falsa alarma aislada es lo esperado.** Con el generador correcto, c falló en 1 de 50 semillas: al nivel 0,01 ocurre en el 40 % de los casos (1 − 0,99⁵⁰). Es la honestidad estadística del hito 1 aplicada al revés.
- **Un notebook didáctico mejora el paquete.** Como en el hito 1, las visualizaciones pidieron funciones nuevas (el gancho, `hypothesis=`, `interval_counts`) que servirán en hitos posteriores.
- **Verificar los datos, incluso los propios.** Una lección del hito 1 sobre `nbmake` era inexacta y solo se detectó al comprobarla con la fuente.
