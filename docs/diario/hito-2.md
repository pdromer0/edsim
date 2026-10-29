# Diario · Hito 2 — Llegadas

Especificación: [docs/specs/hito-2.md](../specs/hito-2.md). El anexo de la especificación tiene el detalle de cada tarea.

## 2026-10-29 · Tarea 2.1 — Perfil de llegadas y función de tasa

**Qué se hizo:** `config/llegadas.toml` con el perfil del centro base. `ArrivalProfile` lo valida y normaliza al construirse. `rate.py` calcula λ(t), continua con interpolación lineal, y Λ(t), exacta con trapecios. Fue la primera tarea en la que Claude Code ejecutó git.

**Qué aprendí:**
- `tomllib` solo lee, exige abrir en binario y entrega `fecha_inicio` como `datetime.date`.
- **Validar al construir:** si la validación vive en `__post_init__`, no puede existir un perfil inválido, se construya como se construya.
- El factor mensual se normaliza ponderando por los días de cada mes: los valores escritos daban una media de 1,0007.
- `np.interp(..., period=24)` une las 23:30 con las 0:30 del día siguiente sin código adicional.
- **La autoconsistencia no basta:** con escalones, λ y Λ seguían siendo coherentes entre sí y `quad` pasaba. Solo los valores calculados a mano detectaron el error.
- Los errores pequeños necesitan tolerancias estrechas: la media simple de los meses cambia λ en un 0,01 %.
- Un perfil fijo para los tests y un test aparte para el fichero real distinguen "el código es correcto" de "la configuración es válida".

**Qué costó o falló:**
- Con escalones, falló el test del cambio de día a medianoche, y no se había predicho. Ese test supone que la forma horaria es continua y, con escalones, también salta de h₂₃ a h₀. Predecir antes de romper obliga a entender qué supone cada test.
- En modo Plan, Claude Code no puede ejecutar comandos que cambian el repositorio: hay que pasar a Manual.

**Preguntas abiertas:** ninguna.

**Enlaces:** PR #12 · [ADR 0019](../decisiones/0019-perfiles-de-llegadas-en-toml.md) · [ADR 0020](../decisiones/0020-tasa-continua-interpolada.md)

## 2026-10-29 · Tarea 2.2 — Generador por *thinning*

**Qué se hizo:** `iter_arrivals` genera las llegadas de forma perezosa con Lewis–Shedler y una cota por día comprobada en cada candidata. `simulate_arrivals` devuelve los registros y `arrival_source` es el proceso SimPy que las entrega.

**Qué aprendí:**
- Un generador con `yield` no sortea la siguiente candidata hasta que se pide la siguiente llegada: podrá funcionar en vivo.
- Una función normal que valida y devuelve el generador falla en la llamada; un generador puro no hace nada hasta el primer `next()`.
- Reiniciar a medianoche es exacto porque la exponencial no tiene memoria.
- La aceptación es 1/máx(h) = 59,5 % cualquier día, porque d y m afectan igual a λ y a la cota.
- **Un error puede no serlo:** la versión C (evaluar con la cota del día anterior) parecía un fallo y era correcta. Antes de buscar un test, hay que razonar si de verdad cambia el resultado.
- **Espiar mejor que cronometrar:** `test_perezoso` registra qué funciones se llaman, más fiable que medir tiempos en un CI lento.
- **Medir antes de optimizar:** el 70 % del tiempo estaba en `np.interp` con `period`. De 4,76 s a 0,67 s, con las llegadas idénticas bit a bit.

**Qué costó o falló:**
- Con la cota a la media (versión B), también cayeron los tests de semillas: dependían del *fixture* que lanzaba el error. Predecir obliga a mirar de qué dependen los tests, no solo qué comprueban.
- La versión C′ (el día siguiente arranca en la candidata descartada) pasa los 26 tests: pierde 0,43 llegadas al día, invisibles en el total anual.

**Preguntas abiertas:**
- ¿Qué prueba detecta un error localizado como C′? Quedó para la tarea 2.4.

**Enlaces:** PR #13 · [ADR 0021](../decisiones/0021-thinning-perezoso-con-cota-por-dia.md)

## 2026-10-29 · Tarea 2.3 — Efecto diario Z y sobredispersión

**Qué se hizo:** cada día sortea una Z gamma de media 1, con su propio flujo, que multiplica la tasa y la cota y queda guardada en `DayRecord`. `seeds.py` añade `child_streams`, para derivar flujos sin modificar el `SeedSequence`.

**Qué aprendí:**
- Gamma de media 1 con el CV: k = 1/CV² y θ = CV². `rng.gamma` recibe la escala, no la tasa.
- **Mezcla de Poisson y gamma:** conocida Z, cada día es Poisson; sin conocerla, binomial negativa. El lunes 5 de enero da una varianza de 883 frente a 376.
- El índice de Pearson tiene un error típico de P·√(2/n): medir una varianza necesita muchos días.
- Un flujo propio garantiza que Z no depende del perfil ni de las candidatas, pero activar Z sí cambia las candidatas, porque la cota se multiplica por Z. La especificación decía lo contrario y se corrigió.
- **Tests de instantánea:** la huella SHA-256 de `main` asegura que, con CV 0, todo sigue igual bit a bit. El comentario dice cuándo es legítimo regenerarla.
- La comprobación de la cota de la 2.2 atrapó, sin ningún test específico, el error de poner Z en λ pero no en la cota.

**Qué costó o falló:**
- **`SeedSequence.spawn` modifica el objeto:** con el mismo `SeedSequence` dos veces, `simulate_arrivals` y `simulate_mm1` daban resultados distintos. Los tests no lo veían porque siempre usaban enteros u objetos nuevos. Se resolvió con `child_streams`, y `mm1.py` se migró en el cierre. Lección: probar también la forma en que se usará el código.
- `dataclasses.replace` vuelve a normalizar el perfil y cambia el último bit de los factores; los tests cargan una copia del TOML.

**Preguntas abiertas:** ninguna.

**Enlaces:** PR #14 · [ADR 0022](../decisiones/0022-efecto-diario-gamma-por-cv.md) · [ADR 0007](../decisiones/0007-un-flujo-aleatorio-por-fuente.md)

## 2026-10-29 · Tarea 2.4 — Validación estadística

**Qué se hizo:** `validation.py` tiene las cinco pruebas (volumen, chi-cuadrado horario, KS de huecos reescalados, Pearson y uniformidad de p-valores) y `validate_arrivals`, que las orquesta. Hay tests de aprobado y de potencia marcados `slow`.

**Qué aprendí:**
- **Comparaciones múltiples:** con cinco pruebas al 5 %, un generador correcto falla alguna en el 23 % de las validaciones; al 1 %, en el 5 %. Dentro de una prueba se reparte con Bonferroni.
- **La hipótesis sale del perfil:** si lo esperado se toma de `DayRecord.expected`, el generador se compara consigo mismo y ninguna prueba de potencia puede fallar.
- **Pearson condicional:** si falla el Pearson sin Z, el error está en Z; si fallan los dos, en el Poisson de cada día.
- **Potencia:** una prueba que nunca falla no prueba nada. La tabla de potencia muestra que cada prueba está ciega a algo y que solo el conjunto cubre los errores importantes.
- Con base 330, el Pearson sin Z salió 5,3 y no 4: el sesgo de un 10 % aporta 3. Por eso el volumen tiene su propia prueba.
- Dos tipos de test: los estadísticos ven errores grandes en cualquier parte; los de regresión, cualquier cambio en un sitio concreto.

**Qué costó o falló:**
- **C′ y una potencia del 13 %:** con CV 0,06, la semilla 2026 detectó el error de la medianoche; con CV 0, no. Una potencia baja detecta a veces, y para errores pequeños hacen falta tests de regresión.
- Una clase llamada `TestResult` la intenta recoger pytest: se llamó `ValidationResult`.

**Preguntas abiertas:**
- Incluir Z en los esperados del chi-cuadrado no cambia nada hoy. ¿Importará cuando la forma horaria dependa del día, por ejemplo en fin de semana?

**Enlaces:** PR #15 · [ADR 0023](../decisiones/0023-validacion-con-cinco-pruebas.md)

## 2026-10-29 · Tarea 2.5 — CLI `edsim llegadas generar` y `edsim llegadas validar`

**Qué se hizo:** dos subcomandos con CSV *tidy* y tres gráficas. La presentación vive en `report.py`, y `validar` termina con el código 1 si alguna prueba falla.

**Qué aprendí:**
- **Tres códigos de salida:** 0 si todo va bien, 1 si una prueba falla (las gráficas se escriben igualmente para diagnosticar) y 2 para errores de uso, sin ficheros a medias.
- Cada fila de los CSV lleva una huella del TOML: si la configuración cambia, se nota.
- Un año mezcla lunes con sábados y enero con septiembre, así que el histograma de recuentos crudos no se compara con una sola binomial negativa: se estandariza cada día con su propia media.
- **Dos cifras que parecen contradecirse:** Pearson 2,1 y residuo 1,0 son el mismo dato visto con dos varianzas de referencia.
- **Una función, dos consumidores:** `hourly_counts` y `hour_of_day` garantizan que la gráfica, el CSV y la prueba nunca discrepen.
- `fecha_hora` se trunca a segundos, para que fecha y hora coincidan siempre con las de la validación.

**Qué costó o falló:**
- `docs/specs/hito-2.md` tenía cambios locales que no eran de la tarea: los commits añaden los ficheros por su nombre.
- Quedaron dos fallos de uso para el cierre: `--salida` que apunta a un fichero daba un error de Python, y `validar` imprimía la cabecera antes de comprobar sus límites.
- Como `validar` genera y valida con el mismo perfil, que la gráfica detecte un CV erróneo solo se puede probar desde el paquete.

**Preguntas abiertas:** ninguna.

**Enlaces:** PR #16

## 2026-10-29 · Tarea 2.6 — Notebook de exploración de las llegadas

**Qué se hizo:** `notebooks/02_llegadas_exploracion.ipynb` con las secciones 0 a 11. Lo que necesitaba entró al paquete con tests: el gancho `on_candidate`, `faults.py` para reproducir C′, `validate_arrivals(..., hypothesis=...)` y las distribuciones teóricas de Z y de los recuentos.

**Qué aprendí:**
- **Observar sin intervenir:** un gancho opcional enseña las candidatas descartadas del generador real sin cambiar ningún sorteo.
- **Reproducir un error como perturbación:** borrar las llegadas del primer hueco tras medianoche equivale a C′ en distribución, sin tocar el generador.
- **La teoría se confirma con datos:** la potencia del 13 % calculada en la 2.4 salió un 12 % con 50 semillas. Juntando los p-valores de las 50, la uniformidad da p = 5,7·10⁻⁹.
- Con el generador correcto, c falló en 1 de 50 semillas: al nivel 0,01, eso pasa en el 40 % de los casos. Una falsa alarma aislada es lo esperado.
- Como en el hito 1, el notebook pidió funciones que servirán en hitos posteriores.

**Qué costó o falló:**
- **La lección de nbmake del hito 1 era inexacta:** `--nbmake-timeout` es un límite por celda, no por notebook. Se verificó en el código de nbmake y nbclient y con una prueba manual, y se corrigió el anexo del hito 1.

**Preguntas abiertas:** ninguna.

**Enlaces:** PR #17 · [ADR 0018](../decisiones/0018-notebooks-jupyter-sin-logica.md)

## 2026-10-29 · Tarea 2.7 — Cierre del hito 2

**Qué se hizo:** ADRs 0019 a 0023, una nota en la 0018, este diario y la exportación del diseño y de las especificaciones de los hitos 1 a 3. Se arreglaron dos pendientes: `simulate_mm1` usa `child_streams` y la CLI da el código 2 ante un `--salida` que no es un directorio o un límite de `validar`, antes de calcular nada.

**Qué aprendí:**
- Un ADR aceptado no se reescribe: una nota de actualización conserva lo que se creía y lo que se verificó.
- **Una huella antes de migrar:** la de `simulate_mm1`, calculada en `main`, demuestra que `child_streams` da los mismos resultados que `spawn` con semilla entera; un segundo test demuestra que se arregló la reutilización.
- **Los límites en un único sitio:** `check_validation_counts` la usan `validate_arrivals` y la CLI, así que no se pueden desincronizar.

**Qué costó o falló:**
- Las exportaciones de `docs/diseno.md` y `docs/specs/hito-1.md` no se habían guardado; se detectó con `git status` antes de empezar.
- `mkdir` también falla si un padre de `--salida` es un fichero: la comprobación recorre los padres.

**Preguntas abiertas:** ninguna.

**Enlaces:** PR #18 · ADRs 0019 a 0023

## Reflexiones de Pedro
