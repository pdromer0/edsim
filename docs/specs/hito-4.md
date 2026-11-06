# Hito 4 — Perfiles clínicos

## Objetivo y alcance

Al terminar el hito 4, cada paciente de EDsim llega con edad, sexo, medio de llegada y motivo de consulta, tiene una gravedad real que el hospital no ve y recibe un nivel de triaje con error. Sus pruebas y duraciones dependen de esa gravedad y de su motivo. Todo sale de un muestreador clínico que se enchufa en el punto de muestreo inyectable del hito 3, sin cambiar la lógica de colas, recursos ni turnos. El centro base queda calibrado, por primera vez, contra datos españoles observados: pretriaje y tiempo hasta el médico.

Dentro del alcance

- Población de adultos (15 años o más): banda y edad, sexo y medio de llegada, condicionados al contexto (franja, tipo de día y estación).
- Los 17 motivos de consulta del catálogo como perfiles, con una categórica log-lineal sorteada con Gumbel-max.
- Gravedad latente G y triaje ordinal con ruido y sesgo (G + ε cortada por umbrales derivados y escritos); nivel real, calidad del triaje e infra y sobretriaje en el ground truth.
- El nivel 1 asignado se clasifica en la puerta y va directo al box.
- Pruebas de cuatro tipos con probabilidad logística, resultado y tiempo de respuesta; duraciones lognormales por nivel real y motivo.
- Tres relojes hasta el médico con nombre propio; cumplimiento Manchester desde la clasificación; indicador de pretriaje.
- Primera calibración: parámetros directos contra datos y plantilla de médicos contra horquillas observadas, con objetivos de ajuste y de comprobación en `config/objetivos.toml`.
- `config/perfiles.toml`, validación estadística del muestreador, CLI, tests y el notebook `04_perfiles_clinicos.ipynb`.
- El incremento de la app para el hito 4 (tareas 4.8a y 4.8b), documentado en la pestaña «App web — incrementos».

Fuera del alcance

- Destino real (alta, ingreso, UCI, traslado, exitus), abandono, boarding y bucles de saturación (ruido de triaje que crece con la cola): hito 5. El destino provisional del hito 3 no cambia.
- Calibrar el porcentaje de ingreso, la estancia y la cola de los niveles 4 y 5 en días punta: dependen de lo anterior y se calibran en el hito 5.
- Pediatría y centros mixtos: perfiles de centro de la v3.
- Triaje dentro del box y desalojo de médicos: circuito de críticos de la v1.
- Un evento por tipo de prueba: versiones posteriores (ver «Para versiones posteriores»).
- Editar los perfiles desde la app: fase 2 de la app.

Las tareas con código empiezan con la etiqueta `v0.3-hito3`, que ya existe. El núcleo lo implementa Claude Code y las páginas de la app, Codex. Claude Code y Codex ejecutan git (rama, commits, push con permiso y PR) y Pedro siempre fusiona.

## Sesión conceptual

Los conceptos se explicaron en la conversación de arranque del hito (3 y 5 de noviembre de 2026), con gráficas y cálculos reales. Esta tabla es el resumen de referencia.

| Concepto | Qué hay que entender |
| --- | --- |
| Cadena generativa | Cada atributo se sortea condicionado a los anteriores: contexto, edad, motivo, gravedad, nivel, pruebas, duraciones |
| Categórica log-lineal | Peso base × factores de contexto, renormalizado; en logaritmos los factores se suman. Un factor multiplica, no suma puntos |
| Peso base frente a reparto global | El reparto que sale es la media de los contextos ponderada por las llegadas; los pesos base se derivan para dar el reparto del catálogo |
| Gumbel-max | Un sorteo por categoría y gana el mayor log w + g. Misma distribución, y al cambiar un peso solo cambian los pacientes que entran o salen de esa categoría (3,6 % frente a 17,3 % con la CDF inversa en el ejemplo de la gripe) |
| Gravedad latente | G continua, oculta, en desviaciones de la población de referencia; depende del motivo y de la edad |
| Triaje ordinal | Nivel asignado = umbrales(G + ε); nivel real = umbrales(G). Los umbrales se derivan una vez para dar el reparto asignado objetivo y se escriben en el TOML |
| Infra y sobretriaje | Asignado menos o más urgente que el real. Con G normal estándar, ruido 0,32 y sesgo −0,08 salen un 10,2 % y un 6,2 %; el 31 % de los niveles 1 reales se asigna como 2 |
| Asignado frente a real | La prioridad usa el asignado (lo que sabe el hospital); duraciones y pruebas, la gravedad real (el paciente que hay delante) |
| Logística | Convierte una suma sin límites en una probabilidad entre 0 y 1; los coeficientes son odds ratios. El TOML da el porcentaje a gravedad media y el código calcula el intercepto |
| Lognormal por factor | Multiplicar la mediana por k desplaza la lognormal sin cambiar σ: la media también queda multiplicada por k |
| Consumo fijo | Número fijo de sorteos por flujo, salga lo que salga; un flujo por fuente |
| Sortear un puesto | Se sortea una z estándar y los parámetros la transforman: al cambiar un parámetro, el paciente conserva su percentil |
| Tres relojes | Desde la llegada (A), desde el inicio del triaje (B), desde la clasificación (C). El cumplimiento Manchester usa C |
| Norma frente a observación | Se calibra a lo observado; las normas solo puntúan. Un centro calibrado a la norma cumpliría por diseño |
| Directos e indirectos | Los directos se fijan contra su dato; los indirectos se ajustan iterando contra KPIs emergentes |
| Identificabilidad | Si dos mandos producen el mismo efecto en todos los objetivos disponibles, no se pueden calibrar a la vez |
| Ajuste y comprobación | Unos objetivos ajustan y otros, reservados, comprueban que el ajuste no ha sido trampa; semillas distintas para cada uno |
| Días fuera de objetivo | Manchester es una regla por paciente y las colas son no lineales: se miran percentiles y días fuera, no medias |

## Cómo encajan las piezas

Cada llegada del hito 2 pasa por el muestreador clínico, que sortea al paciente en orden fijo y con un flujo aleatorio por fuente; el motor del hito 3 solo usa el resultado.

&#91;embedded content: cadena generativa del muestreador clínico · 8 flujos\]

La gravedad se bifurca: el nivel asignado (G más el error de la enfermera) va al log y decide la prioridad, y el nivel real (G sola) va al ground truth. Pruebas y duraciones dependen de la gravedad real; el destino sigue siendo el provisional.

## Población y contexto

El centro atiende solo a adultos de 15 años o más (decisión candidata 35): los objetivos de triaje son de adultos y el corte coincide con el que usa el SAS para separar a los menores. Las 300 urgencias al día del hito 2 pasan a ser 300 urgencias de adultos; el perfil de llegadas no cambia.

**Contexto de la llegada.** El muestreador traduce el instante de cada llegada en tres rasgos, con el mismo calendario que λ(t) del hito 2 (reloj sin cambio de hora, +01:00):

| Rasgo | Valores | Nota |
| --- | --- | --- |
| Franja | mañana, tarde y noche, con inicios propios del perfil (8, 15 y 22 h por defecto) | Independientes de los turnos de `centro.toml`: mover un cambio de turno no mueve a los pacientes |
| Tipo de día | laborable; fin de semana (sábado y domingo) | El hito 2 no tiene calendario de festivos; un festivo cuenta como laborable |
| Estación | invierno, primavera, verano y otoño | Por meses: diciembre a febrero es invierno, y así sucesivamente |

**Edad, sexo y medio de llegada** (flujo 5, siete sorteos fijos por paciente):

1. Banda de edad con una categórica log-lineal, sorteada con Gumbel-max (cuatro sorteos): 15–44, 45–64, 65–79 y 80–99 años. Cada banda tiene su peso base y factores por franja y tipo de día (más jóvenes de noche y en fin de semana).
2. Edad entera, uniforme dentro de la banda (una uniforme).
3. Sexo, con un porcentaje de mujeres por banda.
4. Medio de llegada (ambulancia o propio), con un porcentaje por banda.

**Objetivo de edad convertido a adultos.** Las fuentes dan entre un 27 y un 35 % de urgencias de mayores de 65 años sobre todas las edades. Si los menores son una de cada cinco urgencias (SAS, 2013), la proporción sobre adultos es un 34–44 % (se divide por 0,79). Un objetivo se convierte siempre a la población que se simula antes de usarlo. Entre los mayores de 65 años, el 27 % llega en ambulancia (cohorte EDEN).

## Motivos de consulta

Los 17 motivos del catálogo del diseño existen desde el principio, cada uno como un perfil de `config/perfiles.toml` (decisiones candidatas 36 y 37).

**Mezcla de casos.** Para una llegada con contexto c y paciente de banda b, el peso del motivo m es `w_m = peso_base_m × f_edad[b] × f_franja × f_dia × f_estacion`, y la probabilidad es `w_m / Σ w`. Un factor que el motivo no escribe vale 1.

**Ejemplo a mano** (valores orientativos de la sesión). Disnea con peso base 8, factor 2,4 en mayores y 1,5 en invierno: 8 × 2,4 × 1,5 = 28,8. Con todos los motivos, la suma es 126,74, y la disnea queda en 22,7 % de los mayores un martes de invierno.

**Sorteo con Gumbel-max** (flujo 6, 17 sorteos fijos por paciente). Cada motivo recibe un g\_m de una Gumbel estándar y gana el mayor `log w_m + g_m`. La distribución es exactamente la categórica y no hace falta renormalizar. Al cambiar el peso de un motivo, solo cambian los pacientes que entran o salen de él: con la disnea ×1,5 cambia el 3,6 % de los pacientes (el mínimo posible es 3,5 %), frente al 17,3 % con la CDF inversa (decisión candidata 43).

**Pesos base derivados.** La columna «peso aprox.» del catálogo es un reparto global, no un peso de referencia: el reparto que sale es la media de los contextos ponderada por las llegadas. `base_weights_for(...)` calcula los pesos base para que el reparto global de un año del perfil de llegadas (contextos ponderados por las llegadas esperadas y por la mezcla de bandas de cada contexto) coincida con el catálogo. Se ejecuta una vez y su resultado se escribe en el TOML con un comentario. Un test comprueba que el reparto global sale dentro de ±0,5 puntos. El peso base es el punto fijo y los factores mandan: así un shock «disnea ×1,5» no se renormaliza de vuelta.

**Estado de cada parámetro.** No hay una fuente española pública con el reparto de diagramas de Manchester, así que cada número lleva su estado en un comentario del TOML y en esta especificación:

| Estado | Qué significa | Ejemplos |
| --- | --- | --- |
| Calibrado | Ajustado a un objetivo público con su horquilla | Reparto de triaje, infra y sobretriaje, edad, pretriaje, plantilla |
| Derivado | Lo calcula el código a partir de otros | Umbrales, interceptos, μ y σ, pesos base |
| Orientativo | Juicio clínico razonado, sin dato | Gravedad, pruebas, duraciones y factores por motivo |

Un factor solo se escribe si hay una razón clínica, que va en un comentario al lado (por ejemplo, intoxicación ×3 en noches de fin de semana por el ocio nocturno). El orden clínico de gravedad del catálogo (de muy alta en parada a baja en ORL) es una comprobación: la gravedad media de los motivos debe respetarlo.

## Gravedad latente y triaje

Cada paciente tiene una gravedad real G que el hospital nunca ve; la enfermera clasifica G + ε, y los cinco niveles son cuatro umbrales sobre esa escala (decisión candidata 38).

**Gravedad** (flujo 7, una normal z por paciente): `G = media_motivo + por_edad[b] + desviacion_motivo × z`. G se mide en desviaciones típicas de la población de referencia, la mezcla de un año del perfil de llegadas: 0 es la gravedad media de un adulto. Más G es más grave. Los valores por motivo son orientativos, respetan el orden de la columna «Gravedad típica» del catálogo (un test lo comprueba) y se desplazan y escalan en común para que la mezcla tenga media 0 y desviación 1: x′ = (x + 0,104) / 1,065 (por\_edad y desviación solo se dividen), con media 0,0014 y desviación 1,0002 al redondear. Un desplazamiento y una escala comunes no cambian ningún nivel, porque los umbrales se mueven con ellos.

| Motivo | Gravedad típica (catálogo) | media | desviación | por\_edad (15–44, 45–64, 65–79, 80–99) | G media del año | Razón clínica (orientativa) |
| --- | --- | --- | --- | --- | --- | --- |
| Parada / crítico | Muy alta | 3,38 | 0,38 | — | 3,38 | Compromiso vital a cualquier edad (3,5 y 0,4 antes de la transformación) |
| Disnea | Media–alta | 0,94 | 0,85 | −0,38 / 0 / 0,19 / 0,38 | 1,07 | Asma leve en jóvenes; EPOC e insuficiencia cardiaca en mayores |
| Dolor torácico | Media–alta | 0,94 | 0,75 | −0,38 / 0 / 0,19 / 0,28 | 0,94 | Mecánico o ansiedad en jóvenes; síndrome coronario desde los 45 |
| Malestar | Media | 0,29 | 0,75 | −0,28 / 0 / 0,09 / 0,28 | 0,36 | En frágiles esconde sepsis o descompensación |
| Dolor abdominal | Media | 0,29 | 0,75 | −0,19 / 0 / 0,19 / 0,47 | 0,32 | Abdomen agudo atenuado en mayores |
| Síncope | Media | 0,29 | 0,75 | −0,38 / 0 / 0,19 / 0,28 | 0,31 | Vasovagal en jóvenes; arritmia o hemorragia en mayores |
| Palpitaciones | Media | 0,29 | 0,66 | −0,28 / 0 / 0,09 / 0,19 | 0,27 | Fibrilación auricular rápida en mayores |
| Psiquiátrico | Media | 0,19 | 0,75 | — | 0,19 | Ansiedad frente a agitación o ideación suicida |
| Urológico | Baja–media | −0,18 | 0,66 | 0 / 0 / 0,09 / 0,19 | −0,13 | Retención y urosepsis en mayores |
| Fiebre | Baja–media | −0,18 | 0,75 | −0,19 / 0 / 0,28 / 0,47 | −0,14 | Viriasis en jóvenes; neumonía y sepsis en mayores |
| Traumatismo | Baja | −0,56 | 0,66 | −0,09 / 0 / 0,09 / 0,38 | −0,55 | Fractura de cadera en ≥80 |
| Otros | Baja | −0,56 | 0,75 | — | −0,56 | Cajón de sastre |
| Cutáneo | Baja | −0,75 | 0,56 | — | −0,75 | Banal; la anafilaxia es la cola |
| ORL | Baja | −0,84 | 0,56 | — | −0,84 | Otitis, faringitis, cuerpo extraño |
| Neurológico | Variable | 0,38 | 1,13 | −0,28 / 0 / 0,28 / 0,38 | 0,47 | Cefalea y vértigo frente a ictus |
| Intoxicación | Variable | 0,10 | 1,13 | — | 0,10 | Embriaguez frente a sobredosis |
| Digestivo | Variable | −0,09 | 1,03 | −0,19 / 0 / 0,19 / 0,38 | −0,08 | Gastroenteritis frente a hemorragia digestiva |

Los «Variable» tienen más desviación que la mediana de los 17 motivos (0,75); un test lo comprueba.

**Límite conocido: no todas las paradas van a la puerta.** El catálogo da un 0,5 % de paradas y el objetivo de nivel 1 asignado es un 0,4 %, así que, aunque el nivel 1 fuera solo de paradas, una de cada cinco no cabría en él. Con los valores de la tabla, el 62,4 % de las paradas tiene nivel real 1 y el 53,1 % recibe nivel 1 asignado y va a la puerta (unas 292 de 550 al año); las demás reciben nivel 2 y hacen cola en el triaje. El 74,1 % de los niveles 1 reales son paradas; el resto, sobre todo disnea (12,2 %) y neurológico (9,5 %). Con la parada en 2,94 y 0,47 (la primera versión de la tarea 4.3), solo el 34,5 % iba a la puerta. Subir más la parada no resuelve el límite: los umbrales se derivan para el 0,4 %, y c₁ sube con ella.

**Triaje** (flujo 1, una normal zₑ por paciente): `ε = sesgo + ruido × zₑ`. El nivel asignado es G + ε cortada por los umbrales c₁ > c₂ > c₃ > c₄ (nivel 1 si supera c₁, nivel 5 si queda por debajo de c₄). El nivel real es G cortada por los mismos umbrales. El nivel k es el intervalo (c\_k, c\_{k−1}\]: un valor justo en un umbral se queda en el nivel menos urgente.

**Umbrales derivados y escritos.** Los umbrales se calculan para que el reparto *asignado*, sobre la mezcla de G + ε de un año del perfil de llegadas, sea el objetivo del TOML (adultos de Emergencias 2013: 0,4 / 12,1 / 33,6 / 52,6 / 1,4 %, que suman 100,1 por el redondeo y se normalizan). El cálculo es exacto: una raíz por umbral sobre una suma de normales, una por motivo y banda de edad. Como los pesos base, `thresholds_for(...)` se ejecuta una vez y su resultado se escribe en el TOML con el comando en un comentario; un test comprueba que los escritos siguen siendo los derivados. **No se recalculan al cargar los perfiles**: un escenario con más gravedad (un brote de gripe, un accidente con múltiples víctimas) debe dar más niveles urgentes, y si los umbrales se recalcularan el reparto volvería al objetivo y el shock desaparecería. Con la disnea ×1,5 y los umbrales del perfil base, el nivel 2 asignado pasa del 12,09 % al 13,10 %. El reparto objetivo se cumple por construcción solo en el perfil base. Como el ruido ensancha la distribución observada, el reparto real es más estrecho que el asignado: el ruido «inventa» niveles 1 y 5.

**Calibración del error.** Con G normal estándar y el reparto de adultos, un ruido de 0,32 y un sesgo de −0,08 dan un 10,2 % de infratriaje y un 6,2 % de sobretriaje, cerca del dato más reciente, de Asturias (10,1 % y 6,3 %). Un ruido simétrico sin sesgo daría más sobretriaje que infratriaje. Con esos valores, el 31 % de los niveles 1 reales se asigna como 2 y el 17 % de los niveles 5 reales sube a 4: los errores se concentran en los niveles raros, de franjas estrechas.

| Nivel real \\ asignado (%), G normal estándar | 1 | 2 | 3 | 4 | 5 |
| --- | --- | --- | --- | --- | --- |
| 1 | 69,1 | 30,9 | 0 | 0 | 0 |
| 2 | 1,3 | 76,5 | 22,2 | 0 | 0 |
| 3 | 0 | 6,5 | 75,4 | 18,2 | 0 |
| 4 | 0 | 0 | 7,1 | 91,5 | 1,4 |
| 5 | 0 | 0 | 0 | 16,8 | 83,2 |

Valores exactos, por integración, con G normal estándar. La versión anterior de esta tabla salió de un millón de pacientes sorteados: la fila del nivel 1 (unos 3400 pacientes) tenía alrededor de 0,8 puntos de error de muestreo.

**Con la mezcla real.** La mezcla de motivos y edades no es normal: tiene una cola grave (las paradas) y motivos de mucha dispersión. `triage_error_for(...)` ajusta ruido y sesgo a los objetivos de Asturias, recalculando los umbrales en cada paso, y da 0,333 y −0,081, que también se escriben en el TOML (calibrados). Con los valores escritos, el infratriaje es del 10,10 % y el sobretriaje del 6,28 %.

| Nivel real \\ asignado (%), mezcla real | 1 | 2 | 3 | 4 | 5 |
| --- | --- | --- | --- | --- | --- |
| 1 | 72,4 | 27,6 | 0 | 0 | 0 |
| 2 | 0,8 | 78,8 | 20,5 | 0 | 0 |
| 3 | 0 | 6,0 | 75,7 | 18,3 | 0 |
| 4 | 0 | 0 | 7,7 | 90,6 | 1,7 |
| 5 | 0 | 0 | 0 | 19,5 | 80,5 |

Umbrales \[3,260; 1,140; −0,044; −2,163\]; reparto real 0,42 / 12,46 / 35,81 / 50,65 / 0,65 % frente al asignado 0,40 / 12,09 / 33,55 / 52,56 / 1,40 %.

**Asignado frente a real.** La prioridad de box y médico usa el nivel asignado, que es lo que sabe el hospital. Las duraciones y las pruebas usan la gravedad real, porque el médico atiende al paciente que tiene delante. Así, un 2 infratriado como 4 espera como un 4 pero necesita lo que necesita un 2: es el mecanismo que hace peligroso el infratriaje.

**Nivel 1 en la puerta** (decisión candidata 39). Si el nivel asignado es 1, el paciente no pide enfermera: emite `triage_started` y `triage_completed` en el mismo instante de la llegada, con `circuito: "puerta"` en el payload de `triage_started`, y pide box con desalojo. El orden de los eventos no cambia. Los demás pacientes siguen en FIFO, con `circuito: "enfermeria"`, y el triaje sigue la lognormal del perfil (mediana 5 y p90 10 minutos). Consecuencias:

- Los críticos infratriados como 2 hacen cola como cualquier otro; el ground truth lo mide (críticos reales no reconocidos y su espera).
- Los médicos no se desalojan (decisión 25): al nivel 1 le queda su espera de médico, de alrededor de 1 minuto en el hito 3. Es la distancia medida entre «inmediato» y el modelo, y se resuelve con el circuito de críticos de la v1.
- La capacidad de enfermería y su escalera no cuentan los triajes de puerta; la teoría de la M/G/1 del triaje usa λ · (1 − p₁), porque los niveles 1 ya no llegan a la enfermera (por *thinning*, la llegada sigue siendo Poisson).

**Ground truth.** G, nivel real, calidad del triaje (correcto, infra o sobre) y salto en niveles. Ninguno va al log.

## Pruebas y duraciones

**Cuatro tipos de prueba, en una sola ronda** (decisión candidata 42): analítica, radiografía, ECG e imagen (eco o TC). Para cada tipo t, el paciente sortea si se le pide con una probabilidad logística sobre la gravedad real, el motivo y la edad:

```latex
P(t) = \frac{1}{1 + e^{-(a_{t,m} + b_t G + c_t \cdot \text{mayor})}}, \qquad a_{t,m} = \operatorname{logit}(p_{t,m}), \quad b_t = \ln OR^{G}_t, \quad c_t = \ln OR^{\text{mayor}}_t
```

El TOML da p\_{t,m}, el porcentaje para un adulto de menos de 65 años con G = 0 de cada motivo (por ejemplo, analítica 40 %: a = logit(0,40) = −0,4055), y dos odds ratios por tipo. Con b = 1,2 y c = 0,8, la probabilidad con G = 0 es 40,00 % en un adulto y 59,74 % en un mayor; con G = 1, 68,88 % y 83,13 %. «Mayor» son las bandas que empiezan en 65 años o más (`older_bands`). Los porcentajes de pedir y de alterado van en el intervalo abierto (0, 100), porque el logit de 0 o de 100 no existe.

**El porcentaje del TOML no es el del paciente típico del motivo.** Es el de un adulto con G = 0, y el motivo tiene su propia gravedad y su mezcla de edades: la parada escribe un 36 % de analítica y pide un 98 % en el año. Por eso cada p se eligió por su **marginal de un año** (el porcentaje de los pacientes del motivo a los que se pide), que es la que se lee clínicamente, y el TOML la lleva en un comentario, calculada con los enteros escritos (`workup_model(...).order_by_reason()`). Su estado es «orientativo, elegido por su marginal». Un test compara las 68 marginales, el porcentaje global de cada tipo y el de alguna prueba con una tabla literal (a 0,05 puntos), y otro comprueba que los comentarios siguen siendo las marginales exactas: si cambian los odds ratios, la gravedad, la mezcla o el perfil de llegadas, hay que actualizarlos.

**Resultado y respuesta.** Cada tipo sortea también su resultado (normal o alterado, otra logística sobre G: `logit(base) + ln(OR)·G`; con base 30 y OR 2,5, 30,00 / 51,72 / 72,82 % con G = 0, 1 y 2) y su tiempo de respuesta (lognormal por mediana y p90, con un factor por franja). El paciente espera a la prueba más lenta de las pedidas; con ninguna pedida no hay ronda, y `round_turnaround` devuelve `None` (en la 4.5a, `needs_tests=False`). El resultado no lo usa nadie todavía: lo usará el destino del hito 5, y se sortea ya para que el flujo de pruebas no cambie de consumo entre hitos. Una prueba se pide si su uniforme es estrictamente menor que la probabilidad, y sale alterada igual, como en el `ProvisionalSampler`.

**La franja se aplica al pedir** (decisión de la tarea 4.4). El muestreador da la respuesta *base* de cada tipo (factor 1) y el motor, desde la 4.5a, la multiplica por el factor de la franja del *pedido*, no de la llegada: `round_turnaround(pedidas, respuestas, turnaround_shift_factors(perfiles, franja_del_pedido))`. Es exacto, porque multiplicar una lognormal por k equivale a multiplicar su mediana por k, y la máxima se calcula entonces porque los factores son distintos por tipo. Ejemplo: analítica (75) y ECG (12) pedidas e imagen (200) no; la ronda dura 75 de mañana y 82,5 de tarde (analítica ×1,1).

**Consumo fijo** (flujo 3): tres sorteos por tipo, en el orden analítica, radiografía, ECG e imagen (uniforme de pedir, uniforme de resultado y normal de respuesta), doce por paciente, se pida o no cada prueba. Las pruebas usan G y no G + ε: con otro ruido de triaje, ninguna prueba ni duración cambia.

**En el log**, un solo pedido y un solo resultado por ronda, con la lista dentro: `test_ordered` lleva `pruebas` (por ejemplo `["analitica", "ecg"]`) y `test_resulted` llega con la más lenta y lleva `resultados` (por ejemplo `{"analitica": "alterado", "ecg": "normal"}`). El orden de los eventos no cambia. El tiempo de respuesta de cada tipo va al ground truth.

**Duraciones** (flujo 2, tres normales por paciente: triaje, valoración y reevaluación). La parametrización es la del hito 3: μ = ln(mediana) y σ = (ln p90 − ln mediana) / z₀,₉, con z₀,₉ = 1,28155. La valoración y la reevaluación tienen una base por nivel real, y cada motivo aplica un factor sobre la mediana:

```latex
\mu = \ln(k_m \cdot \text{mediana}_{n}), \qquad \sigma = \sigma_{n}, \qquad E[S] = k_m \cdot E[S_{n}]
```

Multiplicar la mediana por k desplaza la lognormal sin cambiar σ, y la media también queda multiplicada por k. Con base 20 y 45 minutos (σ = 0,6328), la media es 24,43; con k = 1,2, la mediana es 24, el p90 54 y la media 29,32. El triaje tiene una sola lognormal para los niveles 2 a 5, sin factor por motivo; se sortea siempre y el nivel 1 no lo usa. La reevaluación se sortea siempre y solo se usa si hay ronda. Las duraciones son orientativas y fijas durante la calibración del hito 4 (ver «Calibración»).

**Regla de los k.** Los k reparten la duración entre motivos sin cambiar la carga: con los k, la carga de valoración de un año queda a 1 ± 0,05 de la carga sin ellos (un test lo comprueba sobre `config/perfiles.toml`). Con los valores orientativos, la razón es 1,0052 y la media simple de k por paciente, 0,9905.

**Carga del médico por paciente**: E\[valoración\] + E\[reevaluación · 1{alguna prueba}\], con G dentro de la integral, porque mueve el nivel real y las pruebas a la vez. Las medias por nivel real, sin k, son 48,87 / 37,33 / 27,01 / 18,66 / 12,91 minutos de valoración y 17,36 / 14,14 / 11,58 / 9,02 / 6,95 de reevaluación; con el reparto real exacto, 24,07 y 10,60. Con los k y las pruebas del perfil, 24,20 + 8,18 = 32,38 minutos, frente a los 30,84 del modelo provisional (24,43 + 55,41 % × 11,58): la valoración baja un poco y toda la subida viene de la reevaluación, porque el 72,79 % de los pacientes tiene alguna prueba (55,41 % en el provisional). Es una comprobación clínica, no un objetivo.

## El muestreador clínico en el motor

El `ClinicalSampler` tiene el mismo contrato que el `ProvisionalSampler` del hito 3, `sampler(arrival) → PatientDraws`: el motor sigue leyendo nivel, duraciones, pruebas y destino, y el resto de campos solo los copia a los payloads y al ground truth (tarea 4.5a).

**Dónde vive.** En `src/edsim/engine/clinical_sampler.py`, no en `profiles/`: necesita `PatientDraws` y el destino de `CenterConfig`, y `profiles/` no importa el motor (un test lo comprueba en un subproceso). Une los tres muestreadores de `profiles/sampler.py`, que siguen sin conocer el motor.

```python
class ClinicalSampler:
    """Same contract as ProvisionalSampler: sampler(arrival) -> PatientDraws."""

    def __call__(self, arrival):
        # Context, person and reason: streams 5 (4 Gumbel + 3 uniforms) and 6 (17 Gumbel).
        person_reason = self._person_reason(arrival)
        # G and the triage: streams 7 (z of G) and 1 (error of the nurse), 1 normal each.
        severity_triage = self._severity_triage(person_reason)
        # Tests and durations, with G and the true level: streams 3 (12) and 2 (3 normals).
        workup_durations = self._workup_durations(person_reason, severity_triage)
        # Destination: stream 4, 1 uniform, with the assigned level.
        u = self._destination_rng.random()
        return PatientDraws(..., test_turnaround=None, clinical=ClinicalDraws(truth, shifts))
```

**Flujos y consumo** (decisión candidata 43). `child_streams(seed, 8)` da los mismos cinco primeros hijos que `child_streams(seed, 5)`, porque cada hijo depende solo de su índice: las llegadas (flujo 0) no cambian ni un bit. `simulate_ed` pasa los hijos 1 a 7 al `ClinicalSampler`, que los reparte así: `[5, 6]` a la persona y el motivo, `[7, 1]` a la gravedad y el triaje, `[3, 2]` a las pruebas y las duraciones, y el 4 al destino.

| Flujo | Fuente | Sorteos fijos por paciente |
| --- | --- | --- |
| 0 | Llegadas (hito 2) | Los de `iter_arrivals` |
| 1 | Triaje: error de la enfermera | 1 normal |
| 2 | Duraciones | 3 normales (triaje, valoración, reevaluación) |
| 3 | Pruebas | 12 (pedir, resultado y respuesta de 4 tipos) |
| 4 | Destino provisional | 1 uniforme |
| 5 | Población | 4 Gumbel (banda) y 3 uniformes (edad, sexo, medio) |
| 6 | Motivo | 17 Gumbel |
| 7 | Gravedad | 1 normal |

Tres reglas: orden fijo y número fijo de sorteos por flujo, salga lo que salga; un flujo por fuente; y sortear lo estándar (uniformes, normales, Gumbel) y transformarlo después con los parámetros. Con la tercera, al cambiar un parámetro clínico el paciente conserva su percentil, y los números aleatorios comunes sirven también para escenarios clínicos, no solo de plantilla.

**Contrato de `PatientDraws`.** El motor lee los mismos campos con los dos modelos: `level` (con el clínico, el nivel *asignado*: la prioridad, la puerta y el destino lo usan), `triage_time`, `assessment_time`, `reassessment_time`, `needs_tests` (con el clínico, si se pide alguna prueba: hay ronda) y `admitted`. Un campo nuevo, `clinical`, es `None` con el provisional y un `ClinicalDraws` congelado con el clínico: la verdad del paciente (`ClinicalTruth`) y los factores de la respuesta por franja de la ejecución (`TurnaroundShifts`). Con el clínico, `test_turnaround` es `None`, sin un valor inventado: la respuesta de la ronda no se conoce en la llegada.

**La franja del pedido.** Al pedir las pruebas, en el instante `t` del `test_ordered`, el motor calcula `clinical.round_turnaround(t)`: la máxima, sobre las pruebas pedidas, del factor de la franja de `t` (la de `arrival_context(t, fecha_inicio, franjas del perfil)`, no la de la llegada) por la respuesta base. Ejemplos con los factores de `perfiles_ejemplo.toml`: analítica y ECG pedidas a las 14:59, 75 minutos; a las 15:00, 82,5; a las 22:00, 67,5. Analítica y radiografía a las 22:00, 84, porque de noche la más lenta pasa a ser la radiografía (70 × 1,2). Un paciente que llega a las 14:00 y al que piden a las 15:10 usa el factor de la tarde. `patient.py` tiene una rama explícita: sin `clinical`, exactamente el código del hito 3.

**Catálogo versión 2** (tarea 4.5a). Hay un catálogo por versión (`CATALOGS`) y `SCHEMA_VERSIONS = {1, 2}`; `SCHEMA_VERSION` desaparece, para que un uso antiguo falle al importar en vez de comparar un entero con un conjunto. La versión 1 es el catálogo del hito 3 con el `circuito` de la tarea 4.1, sin cambios: el modelo provisional la sigue escribiendo, con las mismas huellas. La versión 2 es la 1 más estos payloads:

| Evento | Payload nuevo | Valores |
| --- | --- | --- |
| `patient_arrived` | `medio` | `"ambulancia"` o `"propios_medios"` |
| `patient_registered` | `edad`, `sexo` | Entero; `"mujer"` o `"hombre"` |
| `triage_completed` | `motivo` (además de `nivel`, el asignado) | Una de las 17 claves |
| `test_ordered` | `pruebas` | Lista no vacía de tipos, en el orden de `TEST_TYPES` y sin repetir, como `["analitica", "ecg"]` |
| `test_resulted` | `resultados` | Objeto con los mismos tipos que el `test_ordered` del episodio, cada uno `"normal"` o `"alterado"`, como `{"analitica": "alterado", "ecg": "normal"}` |

En memoria, `pruebas` es una tupla y `resultados` un mapping de solo lectura con las claves en el orden de `TEST_TYPES`: el evento sigue inmutable, comparable con `==` y con pickle y deepcopy, y la ida y vuelta por JSONL da el mismo evento. Cada `test_resulted` se lee solo, sin buscar su pedido. Un log lleva una sola versión, la de su `EventLog(..., schema_version=...)`; `read_events` valida cada evento con el catálogo de su versión, y `_upgrade` (el `circuito` de los logs anteriores a la 4.1) solo actúa en la versión 1. Ningún catálogo lleva G, z, nivel real, calidad, salto, banda ni respuestas; un test lo comprueba.

**Cambios en el motor**, pequeños y explícitos; la lógica de colas, recursos y turnos no cambia:

1. Los payloads del catálogo versión 2, con el modelo clínico; `triage_started` lleva `circuito` en las dos versiones.
2. El nivel 1 en la puerta: una rama en `patient.py` sin petición de enfermera.
3. `check_capacity`, la escalera de enfermeras y la identidad de utilización no cuentan los triajes con `circuito: "puerta"`; «nadie se cuela» se amplía al triaje (nadie adelanta en su cola salvo un nivel 1).
4. La respuesta de la ronda con la franja del pedido (ver arriba).

**Invariantes nuevas** (tarea 4.5a), en `CHECKS`:

- `door`, con los dos modelos: un triaje con `circuito: "puerta"` va con un `triage_completed` de nivel 1, y al revés; en la puerta, `triage_started` y `triage_completed` ocurren en el instante de la llegada. Lo contrario no se exige: un triaje de enfermería también puede empezar al llegar, si hay una enfermera libre.
- `schema_version`: una sola versión en el log.

**Logs anteriores a la tarea 4.1.** `_upgrade` los lee con `circuito: "enfermeria"` en todos sus triajes, también en los de sus niveles 1, porque entonces el nivel 1 pasaba por la enfermera. Si se recalculan sus invariantes con las reglas de hoy, `door` marca cada uno de esos niveles 1. Es lo esperado: esas ejecuciones guardaron 0 violaciones en `run.json` con las reglas de su momento, y `runs/results.py` solo recalcula las invariantes de una ejecución que guardó alguna, así que en la app no cambian.
- `clinical`, con logs de la versión 2: los tipos de `resultados` son los `pruebas` del pedido del episodio; con el ground truth, `medio`, `edad`, `sexo`, `nivel` (el asignado), `motivo`, `pruebas` y `resultados` coinciden con la verdad; con el ground truth y los perfiles (`check_invariants(..., profiles=...)`), la respuesta observada de cada ronda (`test_resulted − test_ordered`) es la máxima de factor(franja del pedido) × base, calculada aparte, con una tolerancia absoluta de 1e-8 minutos.

**Ground truth de episodios.** `EpisodeTruth` gana un campo `clinical` (`None` con el provisional, sin otros cambios) con la verdad clínica, `ClinicalTruth`, compuesta de los resultados congelados de los muestreadores de `profiles/`:

| Campo | Contenido |
| --- | --- |
| `context` | Franja, tipo de día y estación de la llegada |
| `person` | Banda, edad, sexo y medio de llegada |
| `reason` | Motivo |
| `triage` (`SeverityAndTriage`) | z de la gravedad, G, nivel asignado y real, calidad del triaje y salto |
| `workup` (`Workup`) | Por tipo, si se pide, si sale alterada y su respuesta base (factor 1), con los 12 sorteos estándar del flujo 3 |

`level` sigue siendo el nivel asignado y `test_turnaround` es `None`: la respuesta de cada ronda depende de la franja del pedido y se reconstruye con la base y el instante del log. De los sorteos estándar, la verdad guarda la z de la gravedad y los 12 de las pruebas, porque vienen en `SeverityAndTriage` y `Workup`; no guarda los 7 + 17 de persona y motivo ni los 3 de duraciones, porque se reconstruyen con la semilla y la asignación de flujos, y el emparejamiento clínico de la tarea 4.8a se detecta por la semilla. La paciencia llega en el hito 5. El CSV del ground truth clínico es de la tarea 4.5b: hasta entonces, `write_episodes_csv` con episodios clínicos lanza un error antes de crear el fichero, y con provisionales escribe el CSV de siempre, byte a byte.

**Modelo opcional durante el hito** (decisión candidata 44). `simulate_ed(..., profiles=...)` y, desde la tarea 4.5b, la CLI aceptan unos perfiles. Con ellos usan `child_streams(seed, 8)`, el `ClinicalSampler` y un log de la versión 2; sin ellos, `child_streams(seed, 5)` y el `ProvisionalSampler`, y la app y `runs/` siguen funcionando sin cambios. Dar `profiles` y `sampler` a la vez es un error de uso. El cambio de modelo por defecto y la separación de `centro.toml` (decisión candidata 36) se hacen en la tarea de cierre, cuando la app ya trabaje con perfiles. El `ProvisionalSampler` se queda para la validación del motor (M/G/1, escenario de tres boxes), que necesita un modelo sencillo con teoría conocida.

**Huellas.** Las huellas SHA-256 del modelo provisional cambian una sola vez, en la tarea 4.1, por el nivel 1 en la puerta y el campo `circuito`; su PR lo justifica. Después no deben cambiar en ninguna tarea del hito, y no cambiaron en la 4.5a. El modelo clínico tiene sus propias huellas desde la tarea 4.5a, con el centro, las llegadas y los perfiles de ejemplo, semilla 2026 y 3 días: la del log y la del ground truth, una línea JSON por episodio (`json.dumps(asdict(e), ensure_ascii=False, allow_nan=False, separators=(",", ":"))`, con el `EpisodeTruth` entero). Se regeneran solo con un cambio a propósito de los muestreadores o de `ClinicalTruth`, explicado en el commit; el formato estable del ground truth será el CSV de la tarea 4.5b.

**Pendiente para la tarea 4.5b.** `simulate_run` debe pasar `profiles` a `check_invariants`: sin ellos, la comprobación de la respuesta de la ronda no se hace. La 4.5b añade un test que lo vigile. La app serializa el payload con `json.dumps(dict(event.payload))`, que no admite el mapping anidado de `resultados`: la 4.8a tendrá que usar `to_json` o un payload plano. Si la 4.8a guarda una ejecución antigua como dato de prueba, debe ser posterior a la tarea 4.1 o tener en cuenta que `door` marca sus niveles 1 (ver «Logs anteriores a la tarea 4.1»).

## Relojes y cumplimiento

Entre la llegada y el primer médico hay tres tramos (pretriaje, triaje y espera de box y médico), y en España se usan tres relojes distintos (decisión candidata 40). `EpisodeRecord` tiene los tres con nombre propio:

| Reloj | Medida | Desde | Para qué |
| --- | --- | --- | --- |
| A | `door_to_doctor` (ya existe) | Llegada | Comparar con el TPAM del SAS |
| B | `triage_start_to_doctor` | Inicio del triaje | Comparar con el TEA del SAS |
| C | `classified_to_doctor` | Fin del triaje (nivel asignado) | Cumplimiento Manchester de EDsim |

**Por qué C para el cumplimiento.** Antes del triaje el nivel no existe, y no se puede incumplir un plazo que aún no se ha asignado. Además, C separa responsabilidades: un fallo de pretriaje es de la enfermería de triaje y un fallo de C, de boxes y médicos. Con el reloj A, el nivel 2 no puede cumplir nunca en el modelo del hito 3: el triaje tiene p90 de 10 minutos, así que solo el 90 % de los triajes acaba en 10 minutos, y cualquier espera deja el cumplimiento por debajo del 90 %.

**Reglas:**

- `manchester_compliance` recibe la medida como parámetro y usa C por defecto. Un día está fuera para un nivel si menos del 90 % de sus pacientes llega dentro del máximo (justo en el máximo cumple), como en la tarea 3.8.
- `runs/metrics.py` pasa la medida de forma explícita: la app sigue mostrando el reloj A hasta la tarea 4.8a, que la cambia a C junto con las etiquetas de la 4.8b.
- **Pretriaje con indicador propio**, por día: porcentaje con pretriaje de 10 minutos o menos (estándar del 85 %) y porcentaje por encima de 5 minutos (el TECLA del SAS). Los niveles 1 no cuentan.
- **Nivel 1 solo con su tiempo** (mediana y p90), sin porcentaje: su máximo es 0 y el porcentaje sería siempre 0 %.
- **Cumplimiento por nivel real**, solo con ground truth: la misma regla con el nivel real. La diferencia con el KPI es el coste del infratriaje medido en tiempo. Nunca entra en el log ni en los KPIs observables.

Las normas (máximos de Manchester, pretriaje en 10 minutos, límites del PAUE) se informan siempre, pero no son objetivos de calibración.

## Calibración

El centro base es realista: se calibra a lo observado en hospitales españoles, con horquillas, y por eso incumplirá a veces, como los reales (decisión candidata 41). Un centro que cumple Manchester el 90 % de los días es una variante (`centro_cumplidor.toml`), no la base.

**Parámetros directos**, fijados contra su dato:

| Parámetro | Objetivo | Fuente |
| --- | --- | --- |
| Umbrales de triaje | Reparto asignado en adultos 0,4 / 12,1 / 33,6 / 52,6 / 1,4 % | Emergencias 2013 (Hospital do Salnés) |
| Ruido y sesgo del triaje | Infratriaje 10,1 %, sobretriaje 6,3 % | Concordancia Manchester en Asturias (2026) |
| Pesos base de motivos | Reparto global del catálogo del diseño | Catálogo (orientativo) |
| Reparto de edad | 34–44 % de mayores de 65 años entre adultos | Gaceta Sanitaria 2018, convertido a adultos |

El reparto de triaje se cumple por construcción, porque los umbrales salen de él: elegirlo es fijar un dato, no validar el modelo.

**Parámetros indirectos: un solo mando, la plantilla de médicos por turno.** Menos médicos y valoraciones más largas alargan igual el tiempo hasta el médico, y en el hito 4 no hay ningún objetivo que los distinga (la estancia, que sí depende de las duraciones, se calibra en el hito 5). Calibrar los dos sería un problema no identificable. Las duraciones quedan fijas por criterio clínico y se ajusta solo la plantilla, que es una «plantilla equivalente» del modelo, no una recomendación de dotación.

**Objetivos indirectos** (horquillas orientativas; se fijan en `config/objetivos.toml` en la tarea 4.6). El CMBD del SAS es de 2013 e incluye niños, así que da el orden de magnitud y las horquillas son anchas.

| Objetivo | Reloj | Referencia observada | Horquilla | Uso |
| --- | --- | --- | --- | --- |
| Pretriaje medio | — | SAS 12,4 min | 6–15 min | Ajuste |
| Tiempo medio hasta el médico, niveles 2 a 5 | A | SAS 35,6 a 68,5 min según el nivel | 35–70 min | Ajuste |
| Tiempo medio hasta el médico, nivel 3 | A | SAS 59,0 min | 45–75 min | Ajuste |
| Porcentaje por encima del tiempo recomendado | A | SAS 18,95 % | 10–30 % | Comprobación |
| Porcentaje con pretriaje de más de 5 minutos | — | SAS 46,3 % | 30–60 % | Comprobación |

Fuera de la calibración del hito 4, a propósito (decisión candidata 34): el porcentaje de ingreso, la estancia y la cola de los niveles 4 y 5 en días punta. Sin destino, boarding ni abandono saldrían mal por construcción, y ajustarlos ahora sobredimensionaría la plantilla.

**Reglas contra el sobreajuste:**

1. Pocos mandos, globales y documentados en un registro de calibración (parámetro, antes, después, KPI y motivo).
2. Objetivos de ajuste y de comprobación separados: si los de comprobación también encajan, el modelo tiene algo de verdad.
3. Semillas distintas para calibrar y para verificar.
4. Horquillas, no puntos: un objetivo pasa si la media entre réplicas cae dentro y su IC no es más ancho que la horquilla.
5. Sensibilidad antes de ajustar: si mover un mando apenas cambia un KPI, ese KPI no puede calibrarlo.

**Por qué días fuera de objetivo y percentiles.** Manchester es una regla por paciente, las colas crecen de forma no lineal cerca de la saturación y el servicio se juzga por sus días malos: en el hito 3, una ocupación media del 64 % convivía con lunes de 572 minutos de espera de box en el nivel 5. Cada objetivo se informa también por día, con su porcentaje de días fuera y su p90.

## Ficheros de configuración

`config/perfiles.toml` describe a los pacientes que llegan y `centro.toml`, el hospital (decisión candidata 36). Los valores de abajo son orientativos; lo que fija la especificación es la forma.

```toml
# config/perfiles.toml — población y perfiles clínicos. Ver docs/specs/hito-4.md.
# Cada valor lleva su estado: calibrado, derivado u orientativo.

[contexto]
franjas = [8, 15, 22]               # inicio de mañana, tarde y noche (independiente de los turnos)

[poblacion]
bandas_edad = [15, 45, 65, 80]      # límite inferior de cada banda; tope 99
reparto_edad = [38, 22, 22, 18]     # % en el contexto de referencia
mujeres = [50, 50, 55, 62]          # % por banda
ambulancia = [6, 10, 21, 34]        # % por banda; 26,9 % en ≥65 frente al 27 % de EDEN ([20, 32] daría un 25,4 %)

[triaje]
reparto_objetivo = [0.4, 12.1, 33.6, 52.6, 1.4]   # % asignado (suma 100,1: se normaliza)
infratriaje = 10.1                  # % objetivo (Asturias)
sobretriaje = 6.3
ruido = 0.333                       # calibrado con triage_error_for; desviación del error, en unidades de G
sesgo = -0.081                      # calibrado; negativo: tiende a infratriar
umbrales = [3.260, 1.140, -0.044, -2.163]   # derivado con thresholds_for; no se recalcula al cargar
duracion = [5, 10]                  # [mediana, p90] en minutos, niveles 2 a 5; el nivel 1 no la usa

[duraciones]
valoracion = [[40, 90], [30, 70], [22, 50], [15, 35], [10, 25]]   # [mediana, p90] por nivel real
reevaluacion = [[15, 30], [12, 25], [10, 20], [8, 15], [6, 12]]

[pruebas.analitica]
respuesta = [60, 150]               # [mediana, p90] en minutos
respuesta_franja = [1.0, 1.1, 0.9]  # factor sobre la mediana según la franja del pedido; opcional, vale 1
or_gravedad = 3.3                   # odds ratio por unidad de G
or_mayor = 2.2                      # opcional, vale 1
alterado = { base = 30, or_gravedad = 2.5 }   # % alterado con G = 0 y su odds ratio

[motivos.dolor_toracico]
nombre = "Dolor torácico"
peso_base = 5                       # derivado con base_weights_for
edad = [0.5, 1.0, 1.6, 1.6]
franja = [1.0, 1.1, 0.8]
dia = [1.0, 0.9]                    # laborable; fin de semana
estacion = [1.1, 1.0, 0.9, 1.0]     # invierno, primavera, verano, otoño
gravedad = { media = 0.6, por_edad = [-0.3, 0.0, 0.3, 0.5], desviacion = 0.9 }
pruebas = { analitica = 65, radiografia = 56, ecg = 96, imagen = 2 }   # % en adulto < 65 con G = 0; marginal del año 84,9 / 69,9 / 98,2 / 5,9
duracion = 1.0                      # k sobre la mediana de su nivel real; opcional, vale 1
```

**Reglas de `perfiles.toml`:**

- `ClinicalProfiles` inmutable, validado y normalizado al construirse, y `load_profiles(path)` con `tomllib`, como `CenterConfig`.
- Unidades clínicas en el fichero (porcentajes, minutos, factores, odds ratios); el código calcula pesos normalizados, interceptos y μ y σ. Ningún número derivado se escribe a mano. Los pesos base (`base_weights_for`) y los umbrales (`thresholds_for`) se derivan una vez y se escriben con un comentario, y ruido y sesgo se calibran con `triage_error_for`; un test comprueba que los escritos son los recalculados.
- Factores opcionales: si faltan valen 1. Claves desconocidas prohibidas, con un error que nombra la clave y el motivo. Longitudes validadas: 4 bandas, 3 franjas, 2 tipos de día, 4 estaciones, 5 niveles y 4 tipos de prueba.
- Pruebas: los cuatro tipos (`TEST_TYPES`: analitica, radiografia, ecg, imagen) son fijos en el código y obligatorios, en `[pruebas.<tipo>]` y en el `pruebas` de cada motivo. En cada tipo, `respuesta`, `or_gravedad` y `alterado = { base, or_gravedad }` son obligatorios; `respuesta_franja` y `or_mayor`, opcionales. Los porcentajes de pedir y de alterado van en (0, 100), con un error que nombra la clave y el valor, y cada `[mediana, p90]` exige mediana > 0 y p90 > mediana.
- Los 17 motivos son obligatorios, con los nombres del catálogo en `snake_case`.
- Hasta el cierre, `centro.toml` conserva sus secciones provisionales (`[triaje]`, `[duraciones]`, `[pruebas]`, `[destino]`) para el modelo provisional; en la tarea 4.9 pierde las tres primeras y conserva `[destino]` hasta el hito 5.

`config/objetivos.toml` guarda cada objetivo de calibración con su fuente al lado, para que el notebook, la CLI y los tests lean lo mismo:

```toml
[objetivos.tiempo_medico_nivel_3]
medida = "door_to_doctor"           # reloj A
niveles = [3]
estadistico = "media"
referencia = 59.0
horquilla = [45, 75]
uso = "ajuste"                      # ajuste o comprobacion
fuente = "SAS, CMBD de urgencias 2013"
enlace = "https://www.sspa.juntadeandalucia.es/..."
nota = "Incluye menores de 15 años"
```

## Salidas: CLI

La CLI sigue siendo fina: lee argumentos, llama al paquete y escribe.

```bash
edsim motor simular --perfiles config/perfiles.toml --dias 14 --calentamiento 2 --semilla 2026 --salida resultados/motor
edsim perfiles validar --perfiles config/perfiles.toml --pacientes 20000 --semilla 2026 --salida resultados/perfiles
edsim calibracion evaluar --perfiles config/perfiles.toml --objetivos config/objetivos.toml --replicas 10 --semilla 2026 --salida resultados/calibracion
```

- `motor simular` acepta `--perfiles`; sin él usa el modelo provisional, como hasta ahora. La ejecución se escribe con `simulate_run`, y `run.json` guarda la huella de los perfiles cuando los hay.
- `perfiles validar` prueba el muestreador sin el motor: imprime una tabla con una fila por comprobación (mezcla de motivos por contexto, reparto asignado y real, infra y sobretriaje, pruebas por tramos de G, cuantiles de duraciones) y guarda sus gráficas.
- `calibracion evaluar` ejecuta las réplicas, compara cada objetivo con su horquilla e imprime una tabla con la media, su IC, la horquilla, el uso, el porcentaje de días fuera y el resultado. Guarda un CSV para el registro de calibración.
- Códigos de salida como en los hitos 2 y 3: 0 si todo va bien, 1 si alguna comprobación falla (escribiendo igualmente los ficheros) y 2 para errores de uso, sin crear ficheros a medias.
- Las opciones `--perfiles` y `--objetivos` usan por defecto los ficheros de `config/` en los subcomandos nuevos.

## Estructura del código

Un subpaquete nuevo para el modelo clínico y otro para la calibración; el motor solo cambia en los puntos de «El muestreador clínico en el motor».

```
config/
  perfiles.toml          población y perfiles clínicos
  objetivos.toml         objetivos de calibración con horquilla y fuente
  centro_cumplidor.toml  variante que cumple Manchester (tarea 4.6)
src/edsim/profiles/
  __init__.py
  config.py              ClinicalProfiles, load_profiles (tomllib), validación
  context.py             franja, tipo de día y estación de una llegada
  mixing.py              categórica log-lineal, Gumbel-max, base_weights_for
  population.py          banda, edad, sexo y medio de llegada
  severity.py            gravedad latente, umbrales derivados, triaje con error
  workup.py              pruebas por tipo, resultado y respuesta; WorkupModel exacto
  durations.py           lognormales por nivel real y motivo; DurationModel y carga del médico
  sampler.py             PersonReasonSampler, SeverityTriageSampler y WorkupDurationSampler
  validation.py          comprobaciones estadísticas del muestreador
src/edsim/calibration/
  __init__.py
  targets.py             objetivos.toml: Target, load_targets
  evaluate.py            réplicas, comparación con horquillas, días fuera
src/edsim/engine/        cambios acotados
  clinical_sampler.py    ClinicalSampler, ClinicalDraws, ClinicalTruth y TurnaroundShifts (tarea 4.5a)
  clinical.py            PatientDraws con clinical y test_turnaround opcional; ProvisionalSampler
  patient.py             nivel 1 en la puerta, payloads clínicos, respuesta con la franja del pedido
  events.py              catálogos 1 y 2 (CATALOGS, SCHEMA_VERSIONS): circuito, medio, edad, sexo, motivo, pruebas, resultados
  engine.py              simulate_ed(..., profiles=None)
  analysis.py            triage_start_to_doctor y classified_to_doctor
  targets.py             cumplimiento con medida, pretriaje, nivel 1 sin porcentaje
  invariants.py          capacidad sin triajes de puerta, nadie se cuela en el triaje; door, schema_version y clinical
  ground_truth.py        EpisodeTruth.clinical (ClinicalTruth)
  validation.py          M/G/1 con λ·(1 − p₁)
src/edsim/lognormal.py   lognormal por mediana y p90 (tarea 4.4; engine/clinical.py la reexporta)
src/edsim/cli.py         --perfiles, perfiles validar, calibracion evaluar
notebooks/04_perfiles_clinicos.ipynb
tests/test_profiles_config.py, test_context.py, test_mixing.py, test_population.py,
      test_severity.py, test_workup.py, test_durations.py, test_sampler.py,
      test_profiles_validation.py, test_calibration.py, test_door_triage.py,
      test_clinical_sampler.py, test_clinical_engine.py, clinical_factory.py
```

`ProvisionalSampler` sigue en `engine/clinical.py` para la validación del motor. Sin dependencias nuevas: `tomllib`, NumPy y SciPy cubren la Gumbel, la logística y la búsqueda de umbrales. Los nombres de módulos los confirma el plan de cada tarea.

## Tests y validación

La filosofía es la del hito 3, por capas: valores a mano, versiones incorrectas con predicción y pruebas estadísticas con su potencia.

| Grupo | Qué comprueba |
| --- | --- |
| Perfiles | Carga del TOML de ejemplo y del real; factores opcionales neutros; errores con claves desconocidas, longitudes, porcentajes y medianas inválidos |
| Contexto | Franja en los bordes (7:59 y 8:00), tipo de día en el paso de domingo a lunes, estación por mes |
| Mezcla | Valor a mano (22,7 % de disnea en mayores en invierno); Gumbel-max con sorteos fijados a mano; reparto global de `base_weights_for` dentro de ±0,5 puntos; «con más disnea solo cambian los que pasan a disnea» |
| Triaje | Umbrales a partir del reparto; reparto asignado y real; infra y sobretriaje; matriz real × asignado casilla a casilla; umbrales escritos = derivados y el shock con los escritos; orden clínico de gravedad por motivo; nivel 1 en la puerta con un escenario a mano |
| Pruebas y duraciones | logit(0,40) = −0,4055 y 40,00 / 59,74 / 68,88 / 83,13 %; bordes u = P; máxima de las pedidas (75; 82,5 de tarde; `None` sin pruebas); media lognormal 24,43 → 29,32 con el factor 1,2; lo exacto contra `quad`; marginales por motivo y regla de los k sobre `config/perfiles.toml`; `check_workup` y `check_durations` |
| Muestreador | Consumo fijo por flujo; el paciente k es el mismo con otra plantilla y conserva sus z con otro parámetro clínico; llegadas idénticas a `iter_arrivals` |
| Motor | Asignación de flujos con sorteos a mano; consumo fijo con generadores instrumentados; el motor como tubería del `ClinicalSampler`; respuesta con la franja del pedido (75 / 82,5 / 67,5; 84 de noche; 260 a las 7:59; pedido a las 15:10 de una llegada a las 14:00); destino con el nivel asignado; payloads del catálogo 2 en un escenario a mano, sin campos ocultos; invariantes `door`, `schema_version` y `clinical`, y cero violaciones en 14 días; huellas del modelo provisional (sin cambios) y del clínico (log y ground truth) |
| Relojes | Las tres medidas en un log a mano; cumplimiento con C; pretriaje; nivel 1 sin porcentaje; cumplimiento por nivel real |
| Calibración (slow) | Objetivos cargados con su fuente; evaluación con réplicas; semillas de ajuste y de comprobación distintas |
| CLI | Subcomandos nuevos, ficheros y código 2 ante errores de uso |

**Potencia.** El muestreador se prueba sin el motor, con 20 000 pacientes en décimas de segundo. Con el χ² por motivo, nivel 0,01 y Bonferroni entre 17, se detecta un 5 % que pasa a 6 % con una potencia del 99,7 %, pero un 5 % que pasa a 5,5 % solo con un 43 %. Cada prueba escribe qué tamaño de error ve. Los motivos raros (crítico, 0,5 %) necesitan comprobar que hay pacientes suficientes, para que el test no pase de forma vacía.

**Validación de pruebas y duraciones** (tarea 4.4). `check_workup` y `check_durations` sortean los pacientes de un año como `check_triage`, ahora también con los flujos 3 y 2, y comparan con lo exacto (`WorkupModel` y `DurationModel`, con el integrador de Gauss-Legendre de `triage_matrix`): χ² de un grado de libertad o binomial exacta por debajo de 5 esperados, con Bonferroni.

| Comprobación | Categorías |
| --- | --- |
| `check_workup` (134, nivel 0,01/134) | Pedir × quintil de G (20); alterado × quintil, sobre todos los pacientes porque el resultado se sortea siempre (20); pedir \| infratriado (4); pedir × motivo (68); pedir × nivel real (20); mediana y p90 de la ronda (2) |
| `check_durations` (64, nivel 0,01/64) | Mediana y p90 del triaje (2), de la respuesta base de cada tipo (8) y de la valoración y la reevaluación por nivel real (20); mediana de las dos por motivo (34), que prueba los k |

Un año (109 542 pacientes, unos 14 s cada una) por defecto; 20 000 (2,5 s) en los tests rápidos. Cada grupo condicionado debe esperar al menos 50 pacientes, con los esperados exactos: el nivel real 1 (0,42 %) necesita 12 000. Con una potencia del 80 %, pedir analítica en el quintil central (45,0 %) se ve si pasa a 48,8 % con 20 000 y a 46,6 % en un año; los infratriados (59,8 %), a 65,0 % y 62,0 %; la mediana de la valoración del nivel 3, a 52,7 % y 51,2 %. Un error que comparten el muestreador y lo exacto (qué bandas son «mayores», cómo actúa k) mueve también la hipótesis: solo lo ven los valores a mano y los literales.

**Versiones incorrectas con predicción** (ejemplos; cada plan añade las suyas):

| Versión incorrecta | Predicción |
| --- | --- |
| Factores sumados en lugar de multiplicados | Falla el valor a mano y el χ² del contexto de mayores en invierno |
| Gumbel-max sin el logaritmo (w + g) | Falla el χ² de la mezcla en todos los contextos |
| CDF inversa en lugar de Gumbel-max | Pasan las frecuencias; falla «con más disnea solo cambian los que pasan a disnea» |
| Olvidar renormalizar con Gumbel-max | No falla nada: el argmax no depende de la escala (decisión de diseño) |
| Umbrales sobre G en lugar de G + ε | Falla el reparto asignado (más niveles 1 y 5); pasa el real |
| Pruebas con G + ε (lo que ve la enfermera) en lugar de G | Con 20 000: pasan las marginales por motivo y falla el pedido de analítica de los infratriados (59,81 → 52,25 %, potencia 99,8 %). Con un año fallan también el nivel real 3 y los tramos de G (tarea 4.4, cumplida) |
| Resultado sorteado solo si se pide la prueba | Fallan los tests de independencia y también los estadísticos, porque alterado y respuesta se prueban sobre todos los pacientes: las 20 categorías de alterado y las 8 de respuesta (tarea 4.4, cumplida) |
| Duraciones con el nivel asignado | Con un año fallan las medianas de valoración de los niveles 2 a 4 y los p90 del 4; pasan las medianas por motivo (tarea 4.4, cumplida) |
| Suma de las respuestas en lugar de la máxima | Fallan la ronda a mano y la mediana y el p90 de la ronda (tarea 4.4, cumplida) |
| Hora en UTC en lugar de +01:00 | Falla la franja en el borde de las 8:00 |
| Triaje de puerta contado como enfermera | Falla la capacidad con las enfermeras ocupadas |
| Prioridad de triaje por nivel completo (1 a 5) | Falla «los niveles 2 a 5 siguen en FIFO entre sí» |
| Respuesta de la ronda con la franja de la llegada en lugar de la del pedido | Fallan el pedido a las 15:10 de una llegada a las 14:00, la respuesta con otra plantilla, la invariante `clinical` en 14 días y la huella del log clínico; pasa la del ground truth (tarea 4.5a, cumplida) |
| Destino con el nivel real en lugar del asignado | Fallan la asignación de flujos a mano y las dos huellas clínicas; pasa el destino a mano, que es una función pura (tarea 4.5a, cumplida) |
| Puerta decidida con el nivel real | Fallan los payloads a mano del infratriado y el sobretriado, la invariante `door` en 14 días y la huella del log; pasa la del ground truth (tarea 4.5a, cumplida) |
| Factor del tipo de mayor base sobre la máxima de las bases, en lugar de la máxima de factor × base | Falla solo el caso a mano de las 22:00 (84) y pasa el de las 15:00 (82,5); fallan la respuesta con otra plantilla, la invariante `clinical` y la huella del log (tarea 4.5a, cumplida) |

Como siempre: semilla fija en los tests, nunca se cambia una semilla para que un test pase, y si una predicción falla se añade el test que faltaba. El hook de Claude Code ejecuta `pytest -m "not slow"` y el CI, todos, con el job `tests-app` incluido.

## Notebook de perfiles clínicos

Un cuarto notebook didáctico, `notebooks/04_perfiles_clinicos.ipynb`, con las reglas de los anteriores: toda la lógica vive en `edsim`, se ejecuta de principio a fin, semillas explícitas, modo rápido `EDSIM_NB_RAPIDO=1` para el CI y sin resultados en git. Cada sección combina una explicación breve, código que solo llama a `edsim`, una gráfica, preguntas «Para experimentar» y un recuadro «Lo que debes recordar».

Contenido

1. Uso: cómo ejecutarlo y el modo rápido.
2. Del paciente sin rasgos al paciente con perfil: la cadena generativa.
3. La mezcla de motivos: los 17 motivos en varios contextos y el reparto global frente al peso base.
4. Gumbel-max y los números aleatorios comunes: la ola de gripe con los dos métodos.
5. Gravedad y triaje: G con sus umbrales, la matriz de nivel real frente a asignado y qué pasa al mover el ruido y el sesgo.
6. El nivel 1 en la puerta y los críticos no reconocidos.
7. Pruebas y duraciones: curvas logísticas y lognormales por nivel y motivo.
8. Los tres relojes: el mismo día medido con A, B y C, y por qué el nivel 2 no podía cumplir con A.
9. La calibración: norma frente a observación, horquillas, sensibilidad de la plantilla y objetivos de comprobación.
10. El coste del infratriaje: cumplimiento por nivel asignado frente a nivel real.
11. Centro realista frente a centro cumplidor, con los mismos pacientes.
12. Para experimentar: un perfil con muchos niveles 5 (el reparto del SAS), otro ruido de triaje, otra plantilla.
13. Resumen: las lecciones del hito en pocas frases.

## Decisiones del hito

Once decisiones candidatas, acordadas en la sesión conceptual del 5 de noviembre de 2026. Si se confirman durante el hito, la tarea de cierre las convierte en los ADR 0034 a 0044 y las añade al registro del diseño. La decisión APP-0003, que solo afecta a la app, está en «App web — incrementos».

| # | Decisión | Motivo |
| --- | --- | --- |
| 34 | El hito 4 cubre población, motivo, gravedad, triaje con error, pruebas, duraciones, relojes y una primera calibración; el destino provisional no cambia, y abandono, destino, boarding y bucles de saturación van al hito 5 | Sin destino, boarding ni abandono, el ingreso, la estancia y la cola en días punta saldrían mal por construcción; los bucles necesitan el estado del servicio en el paciente |
| 35 | Solo adultos de 15 años o más, con cuatro bandas de edad (15–44, 45–64, 65–79, 80–99) y edad uniforme dentro de la banda | Los objetivos de triaje son de adultos; la pediatría pide su propio catálogo (v3) |
| 36 | `config/perfiles.toml` aparte de `centro.toml`, una tabla por motivo, unidades clínicas, factores opcionales neutros, claves desconocidas prohibidas y franjas propias | Hospital y población son preguntas distintas; perfiles intercambiables en la v3; nada derivado a mano |
| 37 | Los 17 motivos desde el principio, cada parámetro con su estado (calibrado, derivado u orientativo) y pesos base derivados del reparto del catálogo con `base_weights_for` | No hay fuente pública por motivo; el estado dice qué respaldo tiene cada número; los shocks no se renormalizan |
| 38 | Gravedad latente normal y triaje ordinal G + ε con ruido y sesgo; umbrales derivados una vez para el reparto asignado y escritos en el TOML, sin recalcularse al cargar; la prioridad usa el nivel asignado, y duraciones y pruebas, la gravedad real | Modelo del diseño; reproduce el infra y sobretriaje publicados; hace medible el daño del infratriaje; un escenario con más gravedad da más niveles urgentes |
| 39 | El nivel 1 asignado se clasifica en la puerta (triaje de duración 0, `circuito: "puerta"`, sin enfermera) y va directo al box; sin desalojo de médicos | El crítico no hace cola de triaje sin cambiar el orden de los eventos; el desalojo de médicos ahorraría un minuto a un paciente al día con una regla clínica sin datos (v1) |
| 40 | Tres relojes con nombre propio; cumplimiento Manchester desde la clasificación (C); pretriaje con indicador propio; nivel 1 sin porcentaje; cumplimiento por nivel real solo con ground truth | Antes del triaje no hay nivel; separa la cola de triaje de la de médicos; con el reloj A el nivel 2 no podía cumplir |
| 41 | Centro base realista, calibrado a horquillas observadas en `config/objetivos.toml`, con objetivos de ajuste y de comprobación; la plantilla de médicos es el único mando indirecto | Un laboratorio que nunca incumple no sirve; plantilla y duraciones no son identificables sin la estancia |
| 42 | Pruebas de cuatro tipos en una ronda, con un solo `test_ordered` (lista de pruebas) y un solo `test_resulted` (resultados) | Mismo comportamiento del paciente sin cambiar el contrato del log; un evento por tipo queda para versiones posteriores |
| 43 | Sorteos sincronizados: Gumbel-max para las categorías y z estándar transformadas para las variables continuas, con consumo fijo y un flujo por fuente (`child_streams(seed, 8)`) | Números aleatorios comunes también para escenarios clínicos: con la gripe cambia el 3,6 % de los pacientes y no el 17,3 % |
| 44 | Modelo clínico opcional durante el hito (`profiles=None` usa el provisional) y por defecto en el cierre, cuando la app ya lo soporta; el `ProvisionalSampler` se queda para la validación del motor | `main` estable y `tests-app` obligatorio en todo el hito; la app no se rompe a mitad de camino |

Al cerrar el hito se actualizan también la pestaña de diseño (catálogo de eventos con los payloads nuevos, objetivos de calibración, hoja de ruta con lo aplazado) y la ADR 0031 con una nota de actualización: los incrementos de la app se documentan en su propia pestaña, no en la del hito.

## Tareas, ramas y orden de ejecución

Las tareas van en orden y con una sola rama abierta a la vez. Cada una empieza con una explicación del concepto en el chat del hito, sigue con el plan en modo Plan en una sesión nueva y, con el plan aprobado, se implementa completa; al cerrarla se actualiza el anexo.

| # | Tarea | Quién | Rama | Resultado |
| --- | --- | --- | --- | --- |
| 4.1 | Especificación en `docs/specs/hito-4.md`; tres relojes y pretriaje (40); nivel 1 en la puerta (39); pendientes menores | Claude Code | `feat/h4-relojes` | Cumplimiento con el reloj C, triajes de puerta y huellas justificadas |
| 4.2 | `perfiles.toml` y `ClinicalProfiles`; contexto; población; motivos con Gumbel-max y `base_weights_for` (35, 36, 37, 43) | Claude Code | `feat/h4-perfiles` | Población y motivo validados sin el motor |
| 4.3 | Gravedad latente, umbrales derivados y triaje con ruido y sesgo; nivel real y calidad (38) | Claude Code | `feat/h4-triaje` | Reparto asignado, infra y sobretriaje en verde |
| 4.4 | Pruebas por tipo con resultado y respuesta (42); duraciones por nivel real y motivo | Claude Code | `feat/h4-pruebas` | Logísticas y lognormales validadas |
| 4.5a | `ClinicalSampler` en el motor como opción (44): `PatientDraws` ampliado, `simulate_ed` con perfiles, catálogo versión 2 y payloads, ground truth clínico en memoria, invariantes y huellas | Claude Code | `feat/h4-muestreador` | Primer log con pacientes con perfil, sin invariantes violadas |
| 4.5b | CSV del ground truth clínico, `simulate_run` con perfiles, `run.json` versión 2 con la huella de los perfiles (adelantado de la 4.8a), `motor simular --perfiles` y `perfiles validar` | Claude Code | `feat/h4-cli-perfiles` | Ejecuciones clínicas en `resultados/` y validación del muestreador desde la CLI |
| 4.6 | `objetivos.toml`, `calibracion evaluar` y primera calibración de la plantilla (41); `centro_cumplidor.toml` | Claude Code | `feat/h4-calibracion` | Objetivos de ajuste dentro de horquilla y registro de calibración |
| 4.7 | Notebook `04_perfiles_clinicos.ipynb` | Claude Code | `feat/h4-notebook` | Notebook ejecutable de principio a fin en el CI |
| 4.8a | Núcleo de la app con perfiles (`runs/`); `run.json` versión 2 se adelanta a la 4.5b | Claude Code | `feat/h4-app-nucleo` | Ver «App web — incrementos» |
| 4.8b | Páginas de la app con perfiles | Codex | `feat/app-h4-paginas` | Ver «App web — incrementos»; etiqueta `app-v0.2.0` |
| 4.9 | Cierre: modelo clínico por defecto y separación de `centro.toml` (36, 44); ADR 0034 a 0044; diario; anexo; exportación de pestañas; ajustes de la pestaña de diseño; etiqueta `v0.4-hito4` | Claude Code | `docs/h4-cierre` | Hito cerrado |

Preparación en la tarea 4.1: exportar esta pestaña a `docs/specs/hito-4.md`, apuntar el hito en curso al hito 4 en `CLAUDE.md` y `AGENTS.md`, añadir el prefijo `refactor` a la lista de commits y quitar el permiso de ejecución a los `.md` de `docs/` (`git update-index --chmod=-x`).

**Autonomía del agente** (desde la tarea 4.1). En el primer commit de la 4.1, `.claude/settings.json` pasa `git push` de `ask` a `allow` solo para las ramas `feat/*` y `docs/*`, permite `git branch -D`, y añade a `deny` el push forzado y el push a `main`; `gh pr merge` sigue prohibido. `CLAUDE.md` añade que, con el plan aprobado, el agente hace push de su rama y abre el PR sin pedir confirmación. El plan se aprueba con el modo auto de Claude Code, que no necesita ningún cambio en el repositorio. La red de seguridad sigue siendo el ruleset de `main` (solo por PR y con el CI en verde) y la fusión reservada a Pedro.

**Prompts.** Cada tarea va en una sesión nueva, así que el prompt pide un plan que empiece con una sección «Contexto»: qué ficheros ha leído (`CLAUDE.md` o `AGENTS.md`, `docs/specs/hito-4.md`, los módulos que reutiliza y los de las tareas anteriores) y qué ha entendido de la tarea, antes de proponer cambios. Para la lógica delicada, el plan incluye versiones incorrectas temporales con la predicción de qué tests fallarán. Los prompts se entregan en el chat del hito, en una caja de código, también los de Codex.

## Flujo de git y reparto entre agentes

El núcleo (`src/edsim/`, `tests/`, `config/`, `notebooks/`, `docs/`) lo implementa Claude Code. Las páginas de la app (`app/`) las implementa Codex, con las reglas de `app/AGENTS.md`. Ninguno toca la zona del otro; si una tarea del núcleo rompe un test de `app/tests`, para y lo explica, en lugar de arreglarlo. El CI, con `tests` y `tests-app` obligatorios, lo hace visible antes de fusionar.

En cada tarea, como en el hito 3:

1. El agente parte de `main` actualizado y crea la rama: `git switch main && git pull && git switch -c <rama>`.
2. Pedro aprueba el plan con «Yes, and use auto mode»: un clasificador revisa cada acción en segundo plano y el agente no pide permiso para ediciones ni comandos. Implementa la tarea completa sin esperar revisión entre pasos: un commit por paso lógico, con prefijo y mensaje en español, añadiendo los ficheros por su nombre y con ruff y los tests rápidos en verde. Solo para y pregunta si algo contradice el plan o la especificación, una biblioteca no se comporta como se esperaba, un test falla sin causa clara o hace falta una decisión de diseño nueva.
3. Hace `git push -u origin <rama>` sin pedir permiso (solo ramas `feat/*` y `docs/*`; el push forzado y el push a `main` están prohibidos) y abre el PR con `gh pr create`. La descripción explica cada decisión, lo que cambió respecto al plan, las comprobaciones, las medidas y las versiones incorrectas.
4. Pedro revisa el PR completo con este chat, espera el CI en verde y fusiona con *squash and merge*. `gh pr merge` sigue denegado para los dos agentes.
5. Sincronización: `git switch main && git pull && git branch -D <rama>`.

Solo una rama abierta a la vez. La revisión automática con `@codex review` se pide solo en las tareas críticas: en este hito, la 4.5a (el muestreador en el motor) y la 4.9 (el cambio de modelo por defecto).

## Criterios de aceptación

El hito 4 está cerrado cuando se cumplen todos:

- `uv run pytest` pasa, incluidos los tests slow, los tests de la app pasan y el CI está en verde con `tests` y `tests-app`.
- `edsim perfiles validar` pasa todas sus comprobaciones con los perfiles reales: mezcla de motivos por contexto, reparto global del catálogo, reparto asignado, infra y sobretriaje, pruebas y duraciones.
- `edsim motor simular` con los perfiles por defecto escribe un log sin invariantes violadas, con los payloads nuevos y sin campos fuera del catálogo; el ground truth tiene G, nivel real y calidad del triaje.
- Con la misma semilla, dos ejecuciones dan el mismo log y el mismo ground truth bit a bit, y las llegadas siguen siendo las de `iter_arrivals`. Con otra plantilla, ningún valor sorteado del paciente cambia; con otro parámetro clínico, cada paciente conserva sus sorteos estándar.
- El nivel 1 no consume enfermería y su tiempo hasta el box es 0 cuando puede desalojar.
- El cumplimiento Manchester usa el reloj C, el pretriaje tiene su indicador y el nivel 1 se informa sin porcentaje.
- `edsim calibracion evaluar` deja los objetivos de ajuste dentro de su horquilla con semillas de calibración e informa los de comprobación con semillas distintas; el registro de calibración explica cada cambio.
- Cada parámetro de `perfiles.toml` tiene su estado (calibrado, derivado u orientativo) y cada objetivo de `objetivos.toml`, su fuente.
- La app trabaja con perfiles (ver «App web — incrementos») y existe la etiqueta `app-v0.2.0`.
- `notebooks/04_perfiles_clinicos.ipynb` se ejecuta de principio a fin en el CI y se versiona sin resultados.
- Pedro sabe explicar cómo se mezcla un motivo con su contexto, por qué el nivel asignado no es el real y qué consecuencias tiene, por qué el cumplimiento se mide desde la clasificación, y por qué se calibra a lo observado con un solo mando.
- `docs/` contiene esta especificación, los ADR 0034 a 0044, la entrada del diario y el anexo de referencia del hito.
- La etiqueta `v0.4-hito4` existe en GitHub.

## Para versiones posteriores

Lo que este hito aplaza a propósito, con su destino. La tarea de cierre lo lleva a la hoja de ruta del diseño.

| Aplazado | Por qué ahora no | Dónde |
| --- | --- | --- |
| Un `test_ordered` y un `test_resulted` por tipo de prueba, cada uno a su hora (opción 1 de la decisión 42) | Cambia el contrato del log que comparten el motor, el replay y la app; el paciente se comporta igual | Versiones posteriores, cuando la analítica de servicios (laboratorio frente a radiología) lo necesite |
| Triaje dentro del box para el nivel 1 | Cambia el orden de los eventos en 11 módulos y en la app | Circuito de críticos de la v1 |
| Desalojo de médicos por un nivel 1 | Ahorra alrededor de 1 minuto a un paciente al día; regla clínica sin datos (¿a quién deja el médico?) | Circuito de críticos de la v1, con equipo propio |
| Reconocimiento en la puerta por la gravedad real, con su propio error | Un segundo juicio que calibrar sin datos | Por decidir |
| Ruido de triaje que crece con la saturación | Necesita el estado del servicio en el paciente, como el abandono | Hito 5 |
| Destino multinomial, abandono, boarding y su calibración (ingreso, estancia, días punta) | Dependen unos de otros | Hito 5 |
| Editar los perfiles desde la app | Tarea grande: 17 motivos con validación en vivo | Fase 2 de la app |
| Pediatría y centros mixtos | Catálogo y gravedad propios | Perfiles de centro de la v3 |

## Fuentes

Consultadas el 3 de noviembre de 2026.

- [Ministerio de Sanidad — Urgencias atendidas en el SNS, frecuentación y porcentaje de ingresos, tabla 27 (2024)](https://www.sanidad.gob.es/estadEstudios/sanidadDatos/tablas/tabla27.htm): 10,1 % de ingresos en el SNS y 7,5 % en Andalucía.
- [SAS — Urgencias hospitalarias en el Servicio Andaluz de Salud, CMBD 2013](https://www.sspa.juntadeandalucia.es/servicioandaluzdesalud/sites/default/files/sincfiles/wsas-media-pdf_publicacion/2020/UrgenciasHospitalariasenelServicioAndaluzdeSalud.CMBD2013_0.pdf): definiciones de TRC, TEA, TPAM y TPU; reparto por prioridad; TPAM por nivel; pretriaje; estancias; salidas voluntarias.
- [Junta de Andalucía — Objetivos PAUE, contrato-programa 2015](https://www.juntadeandalucia.es/sites/default/files/2020-03/PAUE%20OBJETIVOS%20CP%202015.pdf): indicadores TECLA y TEPCOF de la prioridad II; Manchester modificado.
- [Castro González et al. — Validez del Sistema de Triaje Manchester, Emergencias 2013](https://revistaemergencias.org/wp-content/uploads/2023/08/Emergencias-2013_25_3_191-195.pdf): reparto de triaje en adultos y definiciones de tiempos.
- [El triaje como indicador de calidad — Anales del Sistema Sanitario de Navarra](https://recyt.fecyt.es/index.php/ASSN/article/download/9391/7014/20917): llegada–clasificación menor de 10 minutos, clasificación menor de 5 minutos y tiempos por nivel.
- [Indicadores de urgencias, cuadro de mando — ponencia FESEMI](https://www.fesemi.org/sites/default/files/documentos/ponencias/xxxi-congreso-semi/Dra.%20Cristina%20Netto.pdf): admisión–triaje en menos de 10 minutos en al menos el 85 %; fugas antes y después del triaje.
- [Ministerio de Sanidad y Política Social — Unidad de urgencias hospitalaria: estándares y recomendaciones (2010)](https://vsf-iwsold-pro-01.mscbs.gob.es/areas/calidadAsistencial/excelenciaClinica/docs/UUH.pdf): 90 % de los pacientes fuera de urgencias en cuatro horas.
- [Concordancia del triaje Manchester en Asturias — Enfermería Clínica 2026](https://portalinvestigacion.uniovi.es/documentos/6a98ad557986db85ebf3a195): infratriaje del 10,1 % y sobretriaje del 6,3 % en viñetas.
- [Parenti et al. — Revisión sistemática del Manchester Triage System (2014)](https://cris.unibo.it/handle/11585/516047): alta tasa de infratriaje y baja sensibilidad en los niveles más urgentes.
- [Miró et al. — Cohorte EDEN, Emergencias 2022](https://revistaemergencias.org/wp-content/uploads/2023/08/Emergencias-2022_34_6_418-427.pdf): mayores de 65 años en urgencias; 27 % llega en ambulancia.
- [Urgencias procedentes de residencias geriátricas — Gaceta Sanitaria 2018](https://scielosp.org/pdf/gs/2018.v32n1/27-34/es): entre el 27 y el 35 % de las urgencias son de mayores de 65 años.
- [Caracterização dos atendimentos segundo o STM — REME 2019](https://doaj.org/article/926dcf7162664dbdb4ebf4b029b66c35): diagramas de Manchester más usados (orden de magnitud, Brasil).
- Documentación del hito 3 (anexo de las tareas 3.6 a 3.8) para los tiempos del centro provisional.

## Anexo: guía de referencia del hito 4

Este anexo se amplía al cerrar cada tarea del hito con lo que se hizo, los conceptos que aparecieron, las decisiones, los resultados medidos, las versiones incorrectas y las lecciones aprendidas.

### Tarea 4.1: relojes, pretriaje y nivel 1 en la puerta

**Qué se hizo**

PR #40 (rama `feat/h4-relojes`), abierto por Claude Code y fusionado por Pedro con *squash and merge*. Es la primera tarea con el plan aprobado en modo auto. Once commits: autonomía del agente; especificación y hito en curso; relojes; nivel 1 en la puerta; nadie se cuela en el triaje; M/G/1 con λ·(1 − p₁); cumplimiento con la medida como parámetro; pretriaje; resumen de la CLI; notebook 03; y la cifra de la M/G/1 en el test slow de `validate_engine`.

- **Autonomía.** En `.claude/settings.json` desaparece `ask` para `git push` (en Claude Code `ask` gana a `allow`, así que con él el `allow` no tenía efecto); `allow` gana `git push -u origin feat/*` y `docs/*` y `git branch -D`; `deny` gana el push forzado y el push a `main`. `CLAUDE.md` dice que, con el plan aprobado, el agente hace push y abre el PR sin pedir confirmación.
- **Preparación.** `docs/specs/hito-4.md` entra en modo 100644; `AGENTS.md` apunta al hito 4 y añade el prefijo `refactor`. El pendiente del `chmod -x` no tenía nada que cambiar: los 44 `.md` versionados ya eran 100644.
- **Relojes** (`engine/analysis.py`): `triage_start_to_doctor` y `classified_to_doctor` en `EpisodeRecord` y en `MEASURES`, con `None` hasta la primera valoración. `SUMMARY_MEASURES` no cambia, porque la app construye sus columnas con él.
- **Nivel 1 en la puerta.** `clinical.classified_at_the_door` y `triage_duration`; una rama en `patient.py` que emite `triage_started` y `triage_completed` en la llegada sin pedir enfermera. `events.py` define `DOOR` y `NURSE`, y el catálogo exige `circuito` en `triage_started`.
- **Lectura de logs antiguos.** `from_json` completa `circuito: "enfermeria"` en los `triage_started` que no lo tienen; `emit` sigue exigiendo el campo. `schema_version` sigue en 1.
- **Invariantes y curvas.** `check_capacity` y `busy_intervals` no cuentan los triajes de puerta; `step_curves` los trata como «sale de la cola de triaje y entra en la de box», sin enfermera. «Nadie se cuela» añade la cola de triaje (FIFO entre triajes de enfermería).
- **Validación.** Pollaczek–Khinchine con λ·(1 − p₁) y Wq sobre los niveles 2 a 5; `total_stay`, `_held_intervals` y la capacidad infinita exacta, con triaje 0 para el nivel 1.
- **Objetivos.** `manchester_compliance(..., measure="classified_to_doctor")` con `Compliance.measure` y `pooled_within`; `pretriage(...)` con recuentos por día y nivel y una columna «total 2–5»; `clock_quantiles`. `runs/metrics.py` pasa el reloj A de forma explícita (`APP_COMPLIANCE_MEASURE`), y `runs/truth.py` marca el triaje de puerta como no usado.
- **CLI.** El resumen de `motor simular` añade dos tablas: relojes por nivel (mediana y p90) con el cumplimiento con C, y pretriaje. Las filas se llaman «nivel 1» a «niveles 2-5».
- **Escenarios.** P5 llega en el minuto 20 en el escenario de tres boxes, y los escenarios a mano de `test_priority` y `test_timeline` mueven su nivel 1 al instante en que antes acababa el triaje: los demás instantes no cambian.
- **Notebook 03.** Secciones 5 y 8 y la pista del nivel 1, reescritas tras ejecutarlo en modo normal; mide el cumplimiento con `door_to_doctor` explícito.
- 1.459 tests en la suite completa (4 min 55 s); 1.441 rápidos (unos 2 min, antes 1.406); 241 de la app (2 min 30 s); notebooks en modo rápido en 32 s y el 03 en modo normal en 4 min 54 s.

**Conceptos**

- **Tres relojes, una resta.** Los tres salen de los mismos instantes del log; lo que cambia es desde cuándo se cuenta, y con ello qué cola se juzga.
- **Cambiar un valor por defecto sin cambiar el significado.** `manchester_compliance` pasa a usar C, pero quien ya lo usaba con A (la app y el notebook 03) lo pide de forma explícita: nada cambia sin querer.
- **Thinning de las llegadas a la enfermera.** Si cada llegada es nivel 1 con probabilidad p₁, independiente de las demás, las que llegan a la enfermera son un Poisson de tasa λ·(1 − p₁): la lección del hito 2, al revés. p₁ sale de la configuración, nunca de lo que vio la ejecución.
- **Tolerancia solo en la frontera de lectura.** El escritor es estricto y el lector, tolerante con lo antiguo: así la tolerancia no puede tapar un fallo del motor.
- **Comparar con `main` evento a evento** demuestra el alcance de un cambio: todo es idéntico hasta el primer nivel 1 y las diferencias empiezan justo ahí.
- **Cambios del mismo instante.** Las escaleras pliegan los cambios de un mismo instante: un +1 y un −1 simultáneos no dejan rastro, y por eso la V6 no la ve ningún test.

**Decisiones**

- `circuito` obligatorio al escribir y con valor por defecto al leer; `schema_version` en 1. La política de versiones del catálogo la decide la tarea 4.5.
- M/G/1 con λ·(1 − p₁) en lugar de dejar el nivel 1 a cero en `mg1_center`: la validación sigue simulando el centro real y pone a prueba la rama de puerta.
- Exclusión explícita de los triajes de puerta con las constantes `DOOR` y `NURSE`.
- `test_un_nivel_1_no_desaloja_a_otro` ya no puede construir su caso: con la puerta, los niveles 1 piden box en orden de llegada. Ahora comprueba que un nivel 1 espera sin desalojar a otro, y la regla sigue cubierta por el test unitario de `should_displace`.
- `offered_load_by_pool` fallaba en `np.convolve` cuando nadie ocupaba un recurso (por ejemplo, con solo niveles 1); un test nuevo lo descubrió y ahora la carga es 0.

**Resultados**

| Comprobación | Valor |
| --- | --- |
| M/G/1 teórica, centro real | Wq 13,10 → 12,93 min; ρ 0,7717 → 0,7694; Lq 1,747 → 1,719 (λ = 0,13293 por minuto) |
| M/G/1 a mano | p₁ = 0,5: λ = 1/15, ρ = 0,3858, Wq = 2,436; p₁ = 0 recupera 13,10 |
| M/G/1 simulada (20 réplicas) | Wq 12,51 \[11,58; 13,44\] |
| Huellas | Cambia `eventos.jsonl`; los dos CSV del ground truth no cambian (predicción cumplida) |
| Comparación con `main` (semilla 7, 2 días, 707 episodios) | 457 episodios idénticos hasta el primer nivel 1 (EP-000461); 26 distintos, el primero en 1946,48, cuando antes esperaba enfermera hasta 1951,14 |
| Escenario de puerta, relojes A / B / C | F 0 / 0 / 0; D 29 / 20 / 15; E 28 / 20 / 15; A 10 / 10 / 0 |

En el mes del notebook 03 (ejecución larga de `validate_engine`):

| Cifra | Antes | Después |
| --- | --- | --- |
| Nivel 1, días fuera con el reloj A | 17 de 17 | 8 de 17 |
| Nivel 1, puerta-médico medio | 9,6 min | 0,6 min |
| Nivel 2, días fuera | 25 de 26 (reloj A) | 0 de 26 (reloj C) |
| Nivel 4, días fuera (reloj A) | 3 de 26 | 2 de 26 |
| Nivel 5, días fuera (reloj A) | 8 de 26 | 8 de 26 |

Al nivel 1 le queda la espera de médico: 10 de sus 26 pacientes esperan, hasta 5,3 minutos. Es la distancia conocida de la decisión de no desalojar médicos (circuito de críticos de la v1).

**Comprobación con versiones incorrectas** (temporales; resultado del PR)

| Versión incorrecta | Predicción | Observado |
| --- | --- | --- |
| V1. `check_capacity` cuenta el triaje de puerta | Fallan los tests a mano y los de invariantes en ejecuciones del motor | Exacta en lo esencial: 21 fallos. Los escenarios a mano de `test_priority` no fallan; sí `test_estres_con_muchos_niveles_1` |
| V2. Prioridad de triaje por (nivel, llegada) | Fallan el FIFO a mano, el orden de `test_shifts` y «nadie se cuela» en ejecuciones; el escenario de puerta pasa | Exacta: 23 fallos; en la ejecución base, las 198 violaciones son de la cola de triaje |
| V3. Cumplimiento con `door_to_doctor` por defecto | Solo falla el test del reloj C por defecto | Exacta: 1 fallo; la app pasa |
| V4. M/G/1 con λ y no λ·(1 − p₁) | Fallan los tests deterministas; la prueba estadística pasa | Exacta: 3 fallos. Con p₁ = 0,3 %, el IC contiene 13,10 y 12,93: límite de potencia |
| V5. El pretriaje cuenta el nivel 1 en el total | Fallan los tests del total 2–5 | Exacta: 2 fallos |
| V6. `step_curves` cuenta el triaje de puerta como enfermera | No falla nada: +1 y −1 en el mismo instante | Exacta: 0 fallos; la regla queda escrita, pero no se puede observar |
| V7. `from_json` sin valor por defecto | Solo falla la lectura de una línea antigua | Exacta: 1 fallo |

**Lecciones aprendidas**

- **El incumplimiento del nivel 2 era del reloj, no del centro.** Con el reloj A, el nivel 2 no podía cumplir por construcción; con el C queda 0 días fuera. Antes de corregir un modelo hay que comprobar qué mide el indicador.
- **Cambiar una regla puede volver imposible el escenario de un test.** Entonces se mueve la comprobación a donde todavía se puede hacer (el test unitario de `should_displace`), no se borra.
- **Un test nuevo puede encontrar un fallo antiguo.** El caso límite «nadie ocupa el recurso» llevaba sin probarse desde que nació la función, en la tarea 3.8.
- **Una prueba estadística no ve un sesgo pequeño.** Una diferencia de 0,17 minutos cabe en el IC de la M/G/1; solo el test determinista la detecta. Es la lección de potencia de la tarea 3.6.
- **Los ajustes de la revisión del plan tienen que llegar al agente.** Los de esta tarea (reglas para los push posteriores, la V8 y los patrones de `-f` con espacios) no están en el PR; se aplican en la 4.2.

**Pendiente para la tarea 4.2**

- `.claude/settings.json`: permitir `git push` sin `-u` y `git push origin feat/*` y `docs/*`, y escribir los patrones de `-f` con espacios.
- `docs/specs/hito-4.md`: el hito 2 no tiene calendario de festivos, así que el tipo de día es laborable o fin de semana; la especificación en línea ya está corregida y el fichero se corrige en la 4.2.
- Para la 4.5: la política de versiones del catálogo de eventos.

### Tarea 4.2: perfiles, contexto, población y motivo

**Qué se hizo**

PR #41 (rama `feat/h4-perfiles`), fusionado por Pedro con *squash and merge*: once commits del plan y cuatro de la revisión del PR. No toca el motor, la CLI ni la app. El subpaquete `src/edsim/profiles/` se construye y se valida suelto; el motor lo usará en la tarea 4.5.

- **Autonomía.** `.claude/settings.json` permite `git push`, `git push origin feat/*` y `git push origin docs/*`. En `deny`, los patrones de `-f` se escriben con espacios (`git push * -f`, `git push * -f *`, `git push -f` y `git push -f *`) y se añade el refspec con `+` (`git push *+*`). El PR comprueba 20 comandos; `git push -u origin feat/x-f` ya no se deniega por error.
- **Especificación.** La exportación local de la pestaña entró como base, por decisión de Pedro, en modo 100644 y sin la firma. Encima: sin festivos; flujo 5 con Gumbel-max (siete sorteos); «un año del perfil de llegadas» en los pesos base; el comentario del flujo 5 en `ClinicalSampler`; la ambulancia `[6, 10, 21, 34]`.
- **Refactor.** `rate.split_days` y `rate.day_calendar` pasan a ser públicos (antes `_split` y el cuerpo de `_day_scale`). `check_integer` y `check_list` pasan de `engine/center.py` a `checks.py`, para que `profiles/` no importe el motor.
- **`config.py`**: `ClinicalProfiles`, `Population` y `ReasonProfile`, inmutables y validados al construirse; `load_profiles`; el catálogo `REASONS` (clave, nombre y peso aproximado).
- **`context.py`**: `context_indices` (vectorizada), `arrival_context`, `context_weights` (llegadas esperadas exactas de cada contexto, con Λ(t)) y `context_time`.
- **`mixing.py`**: `gumbel_max`, las probabilidades exactas de banda y motivo, `global_reason_shares` y `base_weights_for`.
- **`population.py`**: banda, edad, sexo y medio de llegada; `share_65_plus`.
- **`sampler.py`**: `PersonReasonSampler`, con los flujos 5 y 6, que devuelve `PersonAndReason(context, person, reason)`.
- **`validation.py`**: `check_mixing`, un χ² por categoría con Bonferroni (4 bandas, 17 motivos marginales y 68 motivos dentro de cada banda), más `detectable_share` y `detection_power`.
- **Configuración.** `config/perfiles.toml` y su copia fija `tests/data/perfiles_ejemplo.toml`, con el estado de cada valor en un comentario.
- 1.759 tests en la suite completa (6 min 36 s); 1.740 rápidos (2 min 16 s; 1.444 antes de la tarea); 241 de la app (3 min), sin cambios.

**Conceptos**

- **El contexto es una función pura de t.** Franja, tipo de día y estación salen de la misma aritmética de calendario que λ(t). Las franjas son del perfil, no de los turnos: mover un cambio de turno no mueve a los pacientes.
- **Categórica log-lineal con Gumbel-max.** El peso es la base por los factores, y gana el mayor log w + g. No hace falta renormalizar (V4b): multiplicar todos los pesos no cambia el ganador.
- **El peso base no es el reparto global.** `base_weights_for` resuelve un punto fijo multiplicativo, la idea del *raking* de las encuestas. Sin derivar los pesos, la intoxicación saldría en un 2,99 % en lugar del 2,01 % del catálogo.
- **Números aleatorios comunes.** Con Gumbel-max, reforzar un motivo solo atrae pacientes hacia él. Con la disnea ×1,5 cambia el 3,28 % de los pacientes, todos hacia la disnea; con la CDF inversa cambiaría el 15,6 %, también entre motivos que nadie ha tocado.
- **Consumo fijo.** Siete sorteos del flujo 5 y diecisiete del flujo 6 por paciente, salga lo que salga: el paciente k recibe siempre su bloque k.
- **Marginal frente a condicionado.** Un χ² marginal no ve una relación conjunta rota: si el motivo se sorteara con otra banda, el reparto marginal sería el mismo (V8).
- **La potencia, antes que el test.** Un test de detección sin potencia no demuestra nada. La disnea ×1,2 solo en 80–99 movía la disnea del contexto del 10,8 % al 11,3 %: con el χ² marginal, una potencia del 4 %.

**Decisiones**

- Claves de los motivos: el primer término del catálogo en snake\_case ASCII; el nombre completo va en `nombre`. El catálogo vive en `config.REASONS`; suma 99,5 y se normaliza como objetivo.
- Porcentajes y pesos guardados como se escriben; las probabilidades las calcula `mixing`. Un factor ausente vale 1.
- `profiles/` no carga SimPy ni el motor: `ArrivalRecord` solo se importa bajo `TYPE_CHECKING`, y un test lo comprueba en un subproceso.
- Las probabilidades de banda viven en `mixing.py`, para que `base_weights_for` las use sin un ciclo de imports.
- La validación prueba categoría a categoría (un grado de libertad), para que un fallo nombre la categoría y la potencia se diga como «p₀ que pasa a p₁». Da error si un esperado baja de 5, para no pasar en vacío.
- El ejemplo a mano se construye en un perfil de test: la sesión no dejó escritos todos los factores que daban la suma de 126,74 (disnea en un 22,72 %).
- Ambulancia `[6, 10, 21, 34]`: el 26,9 % de los mayores de 65 años llega en ambulancia, frente al 27 % de EDEN; `[20, 32]` daba un 25,4 %.
- `reparto_edad` es el reparto del contexto de referencia (mañana laborable), calibrado en el total de mayores de 65 años.
- Tolerancia de 1e-3 entre pesos escritos y recalculados: con tres decimales, la mayor diferencia es 0,000486.

**Factores** (todos orientativos; lo que no aparece vale 1)

| Motivo o banda | Factor | Valor | Razón clínica |
| --- | --- | --- | --- |
| Banda 15–44 | franja / día | \[1; 1; 1,3\] / \[1; 1,15\] | Ocio nocturno, consultas fuera del horario laboral y fin de semana |
| traumatismo | edad / franja / día / estación | \[1,3; 1,0; 0,7; 0,8\] / \[1; 1,1; 0,8\] / \[1; 1,2\] / \[0,9; 1; 1,1; 1\] | Deporte, trabajo y tráfico en jóvenes; caídas en ≥80; actividad diurna; fin de semana; verano |
| fiebre | estación | \[1,4; 1; 0,7; 1\] | Gripe y VRS |
| disnea | edad / franja / estación | \[0,4; 0,8; 1,8; 2,4\] / \[1; 1; 1,2\] / \[1,5; 1; 0,7; 1\] | EPOC e insuficiencia cardiaca; disnea paroxística nocturna; invierno |
| malestar | edad | \[0,5; 0,9; 1,8; 2,5\] | Fragilidad y pluripatología |
| dolor\_toracico | edad / estación | \[0,6; 1,3; 1,4; 1,2\] / \[1,1; 1; 0,9; 1\] | Cardiopatía isquémica de 45 a 79, atípica en ≥80; más coronarios en invierno |
| neurologico | edad | \[0,7; 1,0; 1,5; 1,7\] | Ictus |
| sincope | edad / estación | \[0,7; 0,8; 1,5; 2,0\] / \[1; 1; 1,2; 1\] | Ortostatismo, fármacos y arritmias; calor |
| urologico | edad / estación | \[1,0; 1,1; 1,0; 1,1\] / \[1; 1; 1,2; 1\] | Cólico renal en la edad media; retención de orina, sondas e ITU complicada en ≥80; deshidratación en verano |
| cutaneo | franja / día / estación | \[1; 1; 0,7\] / \[1; 1,2\] / \[0,9; 1,2; 1,2; 0,9\] | Consulta demorable; centro de salud cerrado el fin de semana; alergias, picaduras y sol |
| orl | franja / día / estación | \[1; 1; 0,7\] / \[1; 1,2\] / \[1,2; 1; 0,9; 1\] | Consulta demorable; centro de salud cerrado; otitis y faringitis |
| psiquiatrico | edad / franja | \[1,4; 1,0; 0,5; 0,4\] / \[1; 1; 1,3\] | Crisis y debuts en jóvenes; crisis nocturnas |
| palpitaciones | edad | \[0,7; 1,1; 1,5; 1,3\] | Fibrilación auricular |
| intoxicacion | edad / franja / día | \[2,0; 0,8; 0,3; 0,2\] / \[1; 1; 1,8\] / \[1; 1,7\] | Alcohol y drogas; noche × fin de semana = 3,06, el «×3» sin interacciones |
| parada | edad | \[0,2; 0,8; 1,8; 2,5\] | Parada en mayores |
| dolor\_abdominal, digestivo, otros | — | — | Sin patrón claro |

Población: `reparto_edad = [38, 22, 22, 18]` (calibrado en el total de ≥65), `mujeres = [50, 50, 55, 62]` (orientativo), `ambulancia = [6, 10, 21, 34]` (calibrado en ≥65). Pesos base derivados (suman 100): traumatismo 19,670; dolor abdominal 10,673; fiebre 8,340; disnea 7,388; malestar 5,611; dolor torácico 5,327; neurológico 4,975; síncope 3,787; urológico 3,919; cutáneo 4,136; ORL 4,247; digestivo 4,269; psiquiátrico 3,040; palpitaciones 2,060; intoxicación 1,342; parada 0,539; otros 10,673.

**Resultados**

| Comprobación | Valor |
| --- | --- |
| Llegadas esperadas en un año (`config/llegadas.toml`) | 109.542: 40,3 % de mañana, 38,4 % de tarde y 21,3 % de noche; 26,6 % en fin de semana |
| `base_weights_for` | 9 vueltas; con los pesos escritos, a 0,00065 puntos del catálogo como máximo |
| Mayores de 65 años | 38,6 % en el año (horquilla del 34–44 %); 40 % en la mañana laborable |
| Ambulancia en ≥65 | 26,9 % (EDEN: 27 %) |
| Disnea ×1,5 | La disnea pasa del 8,7 % al 12,0 %; cambia el 3,28 % de los pacientes (predicho: 3,36 %), todos hacia la disnea; con la CDF inversa, el 15,6 % |
| Muestreador | Unos 120 µs por paciente |
| Validación de los 24 contextos | 47 s (slow): 20.000 pacientes por contexto, 89 categorías, nivel 0,01/2136. La rápida, 2 contextos en 5 s |
| Potencia marginal (80 %) | 0,5 → 0,78 %; 5 → 5,85 %; 8 → 9,05 %; 20 → 21,54 % |
| Potencia dentro de 80–99 (unos 3.600 pacientes) | 5 → 7,02 %; 20 → 23,65 % |
| Menor esperado dentro de una banda | 7,1 (intoxicación en 80–99, tarde laborable de invierno) |
| Disnea ×1,5 solo en 80–99 | Del 19,9 % al 27,1 % en esa banda; potencia mayor del 99,99999 % |

**Comprobación con versiones incorrectas** (temporales; primera ejecución del PR, más la V8 de la revisión)

| Versión incorrecta | Predicción | Observado |
| --- | --- | --- |
| V1. Factores sumados | Fallan el ejemplo a mano, «escritos = recalculados» y el ±0,5; pasa el χ² | 10 fallos y el χ² pasa; falla además «sin derivar se saldría del catálogo» |
| V2. `argmax(w + g)` | Fallan Gumbel a mano y el χ²; pasa el de números comunes | 12 fallos. El de números comunes falla por su guarda: el traumatismo gana casi siempre y nadie cambia |
| V3. CDF inversa en el motivo | Solo falla el de números comunes | 5 fallos: también los tres «paciente k recibe su bloque», que detectan cualquier cambio de transformación |
| V4a. Probabilidades sin dividir por la suma | Fallan el ejemplo, «suman 1» y el χ²; `base_weights_for` no converge | Exacta: 23 fallos, con `RuntimeError` y `ValueError` |
| V4b. Renormalizar en `gumbel_max` | No falla nada | Exacta: 0 fallos |
| V5a. Hora en UTC | Fallan los bordes; «probablemente» «escritos = recalculados» | 50 fallos: bordes, pesos de contexto, ±0,5, ≥65 y el χ² |
| V5b. Franjas de `centro.toml` | Solo falla el test de franjas \[7, 14, 21\] | 4 fallos: \[7, 14, 21\] y \[0, 12, 23\] |
| V6. `base_weights_for` con un día | Fallan el ±0,5 y «escritos = recalculados» | 4 fallos; el ±0,5 pasa, porque usa los pesos ya escritos |
| V7. Edad sin el tope de la banda | Fallan los bordes, la cobertura y la uniforme de 80–99 | Exacta: 6 fallos |
| V8. Motivo sorteado con otra banda | Pasan el χ² marginal y el de banda; falla el condicionado | Exacta: 30 y 26 categorías condicionadas en los dos contextos rápidos, ninguna marginal |

**Lecciones aprendidas**

- **Una predicción fallida dice qué test cubre qué.** Seis de nueve fallaron en la primera ronda. La guarda «el caso ocurre» atrapó la V2; el test de bloque, cualquier cambio de transformación (V3); y la derivación la protege «escritos = recalculados», no el ±0,5 (V6). Una hora de desfase contamina todo lo que depende del contexto (V5a).
- **Calcular la potencia antes de escribir un test de detección.** Si no, el test puede pasar por suerte o fallar sin demostrar nada.
- **Probar la relación conjunta, no solo los marginales.** El muestreador era correcto, pero ningún test lo habría dicho si dejara de serlo.
- **Los ajustes de la aprobación volvieron a llegar a medias.** Entraron los bordes de febrero, la convención de los meses, el ejemplo con su perfil de llegadas y el comentario de `reparto_edad`, pero no el χ² condicionado, la V8, los factores ni el patrón `+`, y hizo falta una ronda de revisión del PR. Desde la 4.3, la descripción del PR lleva una sección «Ajustes de la aprobación» con cada punto y su estado.
- **Un cambio local ajeno se pregunta, no se pisa.** El agente encontró la exportación sin commitear y preguntó antes de incluirla.

**Pendiente**

- Para la 4.3: el esquema crece con `gravedad` por motivo y con `[triaje]`. Los pesos base no cambian, porque la gravedad no altera el motivo.
- Para la 4.5: `person_from_draws` recalcula los pesos de banda en cada paciente (unos 120 µs por paciente). Sobra con 300 pacientes al día, pero conviene precalcularlos, como los de motivo, si las réplicas crecen.
- Para la 4.5: las categorías dentro de una banda se condicionan a los pacientes que salieron en ella, que son aleatorios. Con 20.000 pacientes el menor esperado es 7,1; con muchos menos, el error de `MIN_EXPECTED` dependería del sorteo.

### Tarea 4.3: gravedad latente y triaje

**Qué se hizo**

PR #42 (rama `feat/h4-triaje`), fusionado por Pedro con *squash and merge*: siete commits del plan y dos de la revisión del PR, por la gravedad de la parada. No toca el motor: el muestreador de gravedad y triaje se une a `PersonReasonSampler` en el `ClinicalSampler` de la tarea 4.5.

- **Esquema.** Cada motivo lleva `gravedad = { media, por_edad, desviacion }` (`por_edad` es opcional). `[triaje]` tiene `reparto_objetivo` (suma 100 ± 0,5 y se normaliza), `infratriaje`, `sobretriaje`, `ruido`, `sesgo` y `umbrales`.
- **`severity.py`, todo exacto.** `SeverityMixture` agrupa 68 componentes (motivo × banda), con los pesos de un año de `reason_band_mass` y los momentos en forma cerrada. Contiene `assigned_shares` y `real_shares` (sumas de Φ); `thresholds_for` (una raíz por umbral); `triage_matrix` (Gauss-Legendre de 96 nodos, comprobada contra `quad` a 1e-11); `triage_error_for` (`scipy.optimize.root`, 1 s); y las funciones puras `severity_from_draw`, `triage_from_draws` y `triage_quality`.
- **Muestreo.** `SeverityTriageSampler`, con los flujos 7 y 1, devuelve `SeverityAndTriage` (z, G, nivel asignado y real, calidad y salto).
- **Validación.** `check_triage` sortea un año (109.542 pacientes, unos 10 s) y prueba 30 categorías: el reparto asignado y las 25 casillas de la matriz. Usa el χ² o, con menos de 5 esperados, la binomial exacta, con Bonferroni a 0,01/30.
- **Configuración.** La tabla de gravedad (en «Gravedad latente y triaje»); el ruido (0,333) y el sesgo (−0,081), calibrados; los umbrales \[3,260; 1,140; −0,044; −2,163\], derivados.
- **Especificación.** Umbrales derivados y escritos, valores exactos con G normal estándar y con la mezcla real, tabla de gravedad y límite de las paradas.
- 1.911 tests en la suite completa (7 min 12 s); 1.891 rápidos; 241 de la app, sin cambios.

**Conceptos**

- **Una mezcla de normales se calcula exacta.** El reparto es una suma de Φ, cada umbral una raíz y la matriz una integral en una dimensión por componente. Lo exacto es la hipótesis de las pruebas estadísticas.
- **Una simulación no es un valor exacto.** La tabla de la especificación salía de un millón de pacientes, y la fila del nivel 1 (unos 3400) tenía 0,8 puntos de error de muestreo.
- **La escala de G.** Un desplazamiento y una escala comunes no cambian ningún nivel, porque los umbrales se mueven con ellos, pero fijan la unidad del ruido y de los odds ratios de la 4.4.
- **Derivar y escribir frente a recalcular.** Lo que se recalcula al cargar absorbe los shocks: con los umbrales escritos, la disnea ×1,5 sube el nivel 2 asignado del 12,09 % al 13,10 %; recalculados, volvería al 12,09 %.
- **Dos parámetros, dos objetivos.** El ruido sube los dos errores y el sesgo los reparte entre infratriaje y sobretriaje: el problema es identificable.
- **El χ² es una aproximación; la binomial, exacta.** Con menos de 5 esperados se usa la binomial, que vale con cualquier número y detecta pacientes donde el modelo casi no permite ninguno.
- **Un borde de medida cero solo lo ve un test a mano** (V8).

**Decisiones**

- Los umbrales se derivan una vez y se escriben; no se recalculan al cargar (cambia el texto de la decisión 38).
- El reparto objetivo guarda el dato publicado (suma 100,1) y el código lo normaliza, con una tolerancia de ±0,5.
- Los tests usan los valores exactos (10,16 % de infratriaje, 6,21 % de sobretriaje, 30,92 % de niveles 1 reales asignados como 2), y la especificación se corrigió. Los objetivos de calibración siguen siendo los de Asturias (10,1 % y 6,3 %).
- Las casillas con menos de 5 esperados usan la binomial exacta; las 30 categorías entran en Bonferroni.
- Convención del corte: el nivel k es (c\_k, c\_{k−1}\]; un valor justo en un umbral se queda en el nivel menos urgente.
- La calidad del triaje va en español, como `circuito`, y el salto es |asignado − real|.
- Parada con media 3,5 y desviación 0,4 (antes de la transformación), tras la revisión del PR: con 2,94 y 0,47, el 65 % de las paradas hacía cola en el triaje.

**Resultados**

| Comprobación | Valor |
| --- | --- |
| Calibración con la mezcla real | Ruido 0,333 y sesgo −0,081; con los escritos, 10,10 % de infratriaje y 6,28 % de sobretriaje |
| Reparto real frente al asignado | 0,42 / 12,46 / 35,81 / 50,65 / 0,65 % frente a 0,40 / 12,09 / 33,55 / 52,56 / 1,40 %: el ruido inventa sobre todo niveles 5 |
| Paradas (2,94 / 0,47 → 3,5 / 0,4) | Nivel real 1: 37,6 → 62,4 %; a la puerta: 34,5 → 53,1 % (unas 292 de 550 al año) |
| Nivel real 1 por motivo | Parada 74,1 %, disnea 12,2 %, neurológico 9,5 % (antes 49,7 / 23,9 / 16,5 %) |
| Mayores de 80 frente a 15–44 | G media 0,43 frente a −0,29; nivel 2 asignado 22,2 % frente a 5,7 %; infratriaje 11,5 % frente a 9,1 % |
| Shock (disnea ×1,5) | Nivel 2 asignado del 12,09 % al 13,10 % |
| Potencia de `check_triage` en un año (80 %) | Asignado 1: 0,40 → 0,49 %; real 1 → asignado 2: 0,113 → 0,164 %; real 3 → asignado 2: 2,14 → 2,35 % |
| Detección | Ruido 0,40 frente a 0,333: la casilla real 3 → asignado 2 sube del 2,14 al 2,80 %, con una potencia del 99,4 % con 20.000 pacientes. Ruido 1,5: falla la casilla binomial real 3 → asignado 1 |
| Tiempos | `triage_error_for` 1 s; matriz en milisegundos; `check_triage` 10 s en un año y 3 s con 20.000 |

**Comprobación con versiones incorrectas** (temporales; primera versión del PR)

| Versión incorrecta | Predicción | Observado |
| --- | --- | --- |
| V1. Umbrales sobre G | Fallan la reproducción, el asignado con los recalculados y «escritos = recalculados»; pasan `check_triage` y el shock | Exacta: 10 fallos |
| V2. Nivel real con G + ε | Fallan el borde a mano, números comunes y `check_triage` | 7 fallos: también «detecta un salto imposible», escrito después del plan |
| V3. Sesgo con el signo invertido | Fallan el borde a mano y `check_triage` | Exacta: 3 fallos |
| V4. Umbrales recalculados al cargar | Fallan el shock y los valores literales; pasa «escritos = recalculados» | 6 fallos: más otro de literales, la potencia escrita y un reparto degenerado que deja de cargar |
| V5. Un solo flujo para G y ε | Fallan el consumo fijo y `check_triage` | Exacta: 3 fallos |
| V6. Mezcla sin la edad | Fallan «escritos = recalculados», el asignado con los escritos y `check_triage` | 12 fallos: más los que comparan con valores exactos medidos |
| V7. Infra y sobre intercambiados | Fallan la calidad a mano, la reproducción y la calibración | 11 fallos: más la definición a mano, la desigualdad sin sesgo y el sesgo, que sale positivo |
| V8. `<` en lugar de `<=` en el corte | Solo los bordes a mano | Exacta: 6 fallos |

Ninguna predicción de fallo quedó sin cumplirse; las sorpresas fueron fallos de más, todos explicados.

**Lecciones aprendidas**

- **Los ajustes de la aprobación se perdían en el diálogo.** En Claude Code, «Yes, and use auto mode» aprueba sin texto; el texto va con «No, keep planning». Por eso se perdieron en la 4.1, la 4.2 y la 4.3. Desde la 4.4: con ajustes, «No, keep planning» y el texto; cuando el plan los recoge, «Yes, and use auto mode».
- **Saber de dónde sale una cifra antes de probarla con una tolerancia estrecha.** La tabla de la especificación era de Monte Carlo y el agente lo detectó al reproducirla.
- **Los tests con valores exactos medidos ven cualquier cambio** en la mezcla o en una definición, no solo los que comparan con lo recalculado (fallos de más en V4, V6 y V7).
- **Un modelo puede pasar todos los tests y ser clínicamente raro.** Las comprobaciones clínicas del PR mostraron que dos de cada tres paradas hacían cola en el triaje.
- **Recalcular al cargar también rompe perfiles degenerados:** con el reparto \[0, 0, 100, 0, 0\], dos umbrales coinciden y el perfil no carga.
- **El hook Stop ejecutó los tests con una versión incorrecta aplicada.** Falló el test esperado y no hubo daño, pero las versiones incorrectas deben aplicarse y deshacerse dentro del mismo turno.

**Pendiente**

- Para la 4.4: `duracion` de `[triaje]` (mediana 5 y p90 10 minutos, niveles 2 a 5) entra en el esquema con `[duraciones]` y las pruebas, que usan la gravedad real y el nivel real.
- Para la 4.5: unir `PersonReasonSampler` y `SeverityTriageSampler` en el `ClinicalSampler`; la prioridad usa el nivel asignado; el ground truth lleva z, G, nivel real, calidad y salto.
- Para la 4.5 y el notebook 04: medir la espera de las paradas que reciben nivel 2 (el 47 %), el coste del límite conocido.

### Tarea 4.4: pruebas por tipo y duraciones por nivel real y motivo

**Qué se hizo**

PR #43 (rama `feat/h4-pruebas`), fusionado por Pedro con *squash and merge*: nueve commits del plan, con los tres ajustes de la aprobación, y uno de corrección que destapó la versión incorrecta V4; sin commits de revisión. No toca el motor: el muestreador de pruebas y duraciones se une a los otros dos en el `ClinicalSampler` de la tarea 4.5.

- **Refactors.** `lognormal_params` y `Z90` pasan a `edsim/lognormal.py`, porque `profiles` no puede importar el motor; `engine/clinical.py` los reexporta. `severity.interval_nodes` es el único integrador de Gauss-Legendre por componente e intervalo de G, y lo usan `triage_matrix`, `workup.py` y `durations.py` (la matriz de la 4.3 cambia como mucho 3,9e-16).
- **Esquema.** `TEST_TYPES` = analitica, radiografia, ecg, imagen. `[triaje] duracion`; `[duraciones]` con `valoracion` y `reevaluacion` (5 pares por nivel real); `[pruebas.<tipo>]` con `respuesta`, `respuesta_franja` (opcional), `or_gravedad`, `or_mayor` (opcional) y `alterado = { base, or_gravedad }`; en cada motivo, `pruebas` (los 4 tipos, % para un adulto de menos de 65 años con G = 0, en (0, 100)) y `duracion` = k (opcional).
- **`workup.py`.** Logísticas de pedir y de alterado, respuesta base (factor 1), `turnaround_shift_factors`, `round_turnaround` (la máxima de las pedidas, o `None`), `Workup` y el modelo exacto `WorkupModel`: % global, por motivo, por nivel real y por quintiles de G; alguna prueba; alterado; pedir si infratriado; y la distribución de la ronda.
- **`durations.py`.** `duration_params` (μ = ln(k·mediana) y la σ de su par), `durations_from_draws` y el modelo exacto `DurationModel`: medias, CDF por nivel real y por motivo, y `physician_load`.
- **Muestreo.** `WorkupDurationSampler`, con los flujos 3 y 2 y 12 + 3 sorteos fijos por paciente, devuelve `WorkupAndDurations`.
- **Validación.** `check_workup` (134 categorías) y `check_durations` (64), con lo exacto como hipótesis, χ² o binomial exacta y Bonferroni. Un año por defecto (unos 14 s cada una) y 20.000 pacientes en los tests rápidos (2,5 s).
- **Guardas de la configuración.** Las 68 marginales, los globales y «alguna prueba» contra una tabla literal; los comentarios del TOML al día; y la regla de los k.
- 2.098 tests en la suite completa (9 min 26 s); 2.076 rápidos; 241 de la app, sin cambios.

**Conceptos**

- **La logística trabaja en odds.** Un odds ratio multiplica las odds, y en la escala del logit se suma: a + b·G + c·mayor. Con p = 40 %, b = 1,2 y c = 0,8: 40,00 % en un adulto con G = 0, 59,74 % en un mayor y 68,88 % en un adulto con G = 1.
- **El médico ve la gravedad real.** La prioridad usa el nivel asignado; las pruebas y las duraciones, G y el nivel real. Un infratriado espera como su nivel asignado y recibe las pruebas de su gravedad.
- **El % del TOML no es el del paciente típico.** Es el de G = 0; el que se lee clínicamente es la marginal del año: la parada escribe un 36 % de analítica y pide un 98 %.
- **La ronda dura lo que la más lenta.** Dado G, los tipos son independientes: P(ronda ≤ x) = Π(1 − P\_t + P\_t·F\_t(x)) − Π(1 − P\_t), dividido por P(ronda). La media de la máxima es mayor que la máxima de las medias.
- **Multiplicar una lognormal por k es multiplicar su mediana.** Por eso el factor de la franja se puede aplicar al pedir sobre la respuesta base, y k mueve la mediana, la p90 y la media sin cambiar σ.
- **Los k reparten, no añaden.** Con la carga de valoración a 1 ± 0,05 de la carga sin k, las bases por nivel siguen significando «el motivo medio de ese nivel», y la carga de los médicos no cambia a escondidas.
- **Un error que comparten el muestreador y lo exacto no lo ve la estadística**, porque mueve también la hipótesis: solo lo ven los valores a mano y los literales (V4, V6). Un error solo del muestreador sí lo ve la estadística (V4b, V6b).

**Decisiones**

- El factor de la franja de la respuesta se aplica al pedir, en la 4.5; el muestreador da la respuesta base.
- Una ronda sin pruebas es `None`; en la 4.5 equivale a `needs_tests=False`.
- Los p de cada motivo son «orientativos, elegidos por su marginal»: el TOML lleva en un comentario la marginal que dan los enteros escritos, y dos tests la vigilan.
- Regla de los k: la carga de valoración de un año con los k, a 1 ± 0,05 de la carga sin ellos (razón 1,0052; media simple 0,9905).
- Se acepta que la carga del médico suba un 5 % respecto al modelo provisional: 32,38 frente a 30,84 min por paciente. La valoración baja (24,20 frente a 24,43) y toda la subida viene de la reevaluación (8,18 frente a 6,42), porque el 72,79 % tiene alguna prueba (55,41 % en el provisional). La 4.6 lo absorberá con la plantilla, a la vista.
- Alterado y respuesta se prueban sobre todos los pacientes, porque se sortean siempre.
- Cada grupo condicionado necesita al menos 50 pacientes esperados (exactos): el nivel real 1 pide 12.000.

**Valores orientativos por tipo de prueba**

| Tipo | Respuesta \[mediana, p90\] (min) | Franja (mañana / tarde / noche) | OR gravedad | OR mayor | Alterado (base %; OR) | Razón |
| --- | --- | --- | --- | --- | --- | --- |
| Analítica | \[60, 150\] | 1,0 / 1,1 / 0,9 | 3,3 | 2,2 | 30; 2,5 | Pico de muestras por la tarde; sigue a la gravedad; pluripatología en mayores |
| Radiografía | \[30, 75\] | 1,0 / 1,0 / 1,2 | 1,5 | 1,8 | 25; 2,0 | Depende más del motivo que de la gravedad; un solo técnico de noche |
| ECG | \[10, 25\] | sin factor | 2,0 | 3,0 | 20; 2,0 | A pie de cama; casi rutina en mayores |
| Imagen (eco o TC) | \[100, 240\] | 1,0 / 1,1 / 1,3 | 2,0 | 1,8 | 35; 2,0 | Radiólogo de guardia y sin eco programada de noche; TC craneal en caídas con anticoagulantes |

**Pruebas y k por motivo** (p en el TOML para un adulto de menos de 65 años con G = 0; marginal exacta de un año de `config/llegadas.toml`)

| Motivo | p (an / rx / ecg / img) | Marginal del año (%) | Alguna (%) | k |
| --- | --- | --- | --- | --- |
| Traumatismo | 9 / 72 / 4 / 7 | 8,1 / 69,7 / 4,6 / 6,4 | 74,1 | 0,85 |
| Dolor abdominal | 67 / 14 / 7 / 25 | 75,0 / 19,5 / 14,9 / 35,1 | 85,3 | 1,1 |
| Fiebre | 72 / 46 / 6 / 4 | 69,8 / 49,6 / 10,2 / 5,4 | 84,1 | 1,0 |
| Disnea | 59 / 73 / 32 / 2 | 84,8 / 85,0 / 65,0 / 7,3 | 98,2 | 1,1 |
| Malestar | 68 / 24 / 38 / 4 | 79,9 / 35,4 / 59,9 / 8,4 | 92,4 | 1,2 |
| Dolor torácico | 65 / 56 / 96 / 2 | 84,9 / 69,9 / 98,2 / 5,9 | 99,8 | 1,0 |
| Neurológico | 40 / 4 / 13 / 40 | 59,7 / 7,3 / 30,5 / 54,6 | 81,0 | 1,15 |
| Síncope | 49 / 9 / 92 / 8 | 64,9 / 14,5 / 94,9 / 14,9 | 97,7 | 1,1 |
| Urológico | 59 / 17 / 3 / 32 | 60,0 / 20,0 / 5,0 / 35,5 | 77,3 | 0,9 |
| Cutáneo | 14 / 3 / 3 / 2 | 9,9 / 2,9 / 3,2 / 1,6 | 16,4 | 0,8 |
| ORL | 8 / 4 / 2 / 4 | 5,2 / 3,7 / 2,0 / 3,1 | 13,1 | 0,8 |
| Digestivo | 72 / 12 / 9 / 11 | 69,6 / 15,2 / 15,6 / 15,2 | 77,1 | 1,0 |
| Psiquiátrico | 12 / 2 / 8 / 2 | 19,8 / 2,5 / 12,2 / 2,9 | 31,9 | 1,3 |
| Palpitaciones | 58 / 18 / 97 / 2 | 70,1 / 25,3 / 98,0 / 3,7 | 99,3 | 0,9 |
| Intoxicación | 78 / 7 / 46 / 6 | 74,7 / 8,3 / 49,7 / 8,4 | 85,2 | 1,1 |
| Parada | 36 / 61 / 83 / 4 | 98,0 / 90,1 / 99,0 / 40,4 | 100 | 1,0 |
| Otros | 22 / 10 / 7 / 4 | 19,7 / 10,4 / 8,5 / 3,9 | 35,1 | 0,9 |

**Resultados**

| Comprobación | Valor |
| --- | --- |
| Pruebas en un año | Analítica 48,08 %, radiografía 37,32 %, ECG 28,09 %, imagen 13,14 %; alguna prueba 72,79 % (55,41 % en el provisional) |
| Alguna prueba por nivel real | 100 / 98,2 / 86,7 / 57,1 / 26,9 % (provisional: 95 / 85 / 70 / 40 / 20) |
| Alterado entre los pedidos | 42,3 / 30,0 / 30,8 / 44,9 %; alguna alterada en la ronda, 46,8 % |
| Pedir si infratriado | 59,8 / 39,3 / 35,1 / 15,9 % (infratriaje del 10,10 %) |
| Ronda (factor 1) | Media 78,19 min, mediana 57,67, p90 161,78 |
| Valoración y reevaluación por nivel real, con k | 50,24 / 40,44 / 27,95 / 17,48 / 12,17 min y 17,85 / 15,32 / 11,98 / 8,45 / 6,54 min |
| Carga del médico por paciente | 24,20 + 8,18 = 32,38 min (provisional 30,84) |
| Regla de los k | Razón 1,0052; media simple 0,9905 |
| Quintiles de G (un año) | −0,8435 / −0,3202 / 0,1796 / 0,8128 |
| Potencia (80 %) | Pedir analítica en el quintil central, 45,0 → 48,8 % con 20.000 y 46,6 % en un año; infratriados, 59,8 → 65,0 y 62,0 %; mediana de valoración del nivel 3, 50 → 52,7 y 51,2 % |
| Detección | Alterado de analítica 30 → 36, otro OR de pedir y el k de traumatismo 0,85 → 1: potencia mayor que 0,999 |
| Tiempos | `check_workup` y `check_durations`, 2,5 s con 20.000 y 14 s en un año; lo exacto, milisegundos |
| Verificación del chat | Globales, alguna prueba, por nivel real, infratriados, carga, razón de los k, quintiles y las 68 marginales, reproducidos con una integración independiente |

**Comprobación con versiones incorrectas** (temporales; aplicadas y deshechas en el mismo turno)

| Versión incorrecta | Predicción | Observado |
| --- | --- | --- |
| V1. Pedir con G + ε | Fallan el muestreador a mano, «otro ruido no cambia las pruebas» e infra/analítica con 20.000; con un año, los infratriados y real 3/analítica | Cumplida, con fallos de más: infra/imagen y real 3/analítica con 20.000, y 12 categorías con un año (quintiles 3 a 5). Un primer intento (V1′) pasó G + ε también al resultado y falló alterado: se limitó al pedido |
| V2. Duraciones con el nivel asignado | Fallan el muestreador a mano, «otro ruido no cambia las duraciones» y siete categorías por nivel real con un año | Cumplida, más los p90 del nivel 2 (potencia 0,91 y 0,71, sin predicción) |
| V3. Resultado y respuesta solo si se pide | Fallan el consumo, «otro p no cambia resultados ni respuestas», las 20 de alterado y las 8 de respuesta | Cumplida casilla a casilla, más dos tests que también comprueban resultados y respuestas |
| V4. k sobre σ en `duration_params`, compartida | Fallan los valores a mano con k y los literales; `check_durations` pasa | No cumplida a la primera: fallaron los p90, porque `DurationModel` tomaba σ sin k. Corregido en un commit aparte, con un test casilla a casilla; después, cumplida |
| V4b. k sobre σ solo al sortear | Fallan el muestreador a mano y `check_durations` en varios motivos | Fallan las categorías firmes (23 con 20.000 y 33 con un año). El muestreador «a mano» pasó, porque usa `durations_from_draws` como referencia; lo vieron los valores a mano de esa función |
| V5. Suma de las respuestas en lugar de la máxima | Fallan la ronda a mano y la mediana y el p90 de la ronda | Exacta |
| V6. «Mayor» desde 45, compartida | Fallan los valores a mano y los literales; `check_workup` pasa | Cumplida: 11 tests, incluida la guarda de la tabla |
| V6b. «Mayor» desde 45 solo en el muestreador | Fallan el muestreador a mano y analítica y ECG por nivel real con un año | Cumplida: 64 categorías con un año y 15 con 20.000 |
| V7. Un solo flujo para pruebas y duraciones | Fallan el consumo y «otra semilla de un flujo no cambia el otro» | Exacta |
| V8. Factor de la franja de la llegada en la respuesta | Fallan el muestreador a mano, imagen con los dos tamaños y radiografía con un año | Cumplida, más radiografía con 20.000 y analítica y la ronda con un año |
| V9. `<=` en lugar de `<` al pedir | Solo el borde a mano | Exacta |

Una predicción fallida (V4) destapó un error real del modelo exacto; las demás se cumplieron, con fallos de más explicados.

**Lecciones aprendidas**

- **Una predicción fallida puede encontrar un error de verdad.** V4 debía pasar la validación y falló, porque lo exacto suponía cómo actúa k en lugar de usar la función del muestreador. Lo exacto y el muestreador comparten las funciones de parámetros, y un test lo comprueba casilla a casilla.
- **Los errores compartidos solo los ven los valores a mano y los literales; los del muestreador, la estadística.** Por eso conviene probar cada versión incorrecta en las dos variantes (V4 y V4b, V6 y V6b).
- **Un test de integración que usa las funciones como referencia comprueba el cableado, no las fórmulas** (V4b). Las fórmulas las cubren los valores a mano de cada función.
- **Lo elegido con un script también necesita guarda.** Los p salieron de su marginal objetivo; sin la tabla literal, los comentarios del TOML mentirían en cuanto cambiase la mezcla.
- **Una sola copia de la cuadratura.** Extraer `interval_nodes` antes de usarla en dos módulos más evitó tres integradores con sus propias colas.
- **Un test por cosa.** El test de la regla de los k comprueba también el literal 1,0052: con V4 falló por el literal aunque la regla se cumplía.
- **Los ajustes llegaron al agente.** Con «No, keep planning» y el texto, los tres ajustes estaban en el plan y en la sección «Ajustes de la aprobación» del PR: la primera tarea del hito sin ajustes perdidos.

**Pendiente**

- **Para la 4.5:** unir los tres muestreadores en el `ClinicalSampler`. El motor aplica `turnaround_shift_factors` con la franja del momento del pedido y llama a `round_turnaround`; `None` equivale a `needs_tests=False`. La reevaluación solo se usa si hay ronda, y el triaje no se usa en el nivel 1. Payloads `pruebas` y `resultados`; ground truth con las pruebas pedidas, su resultado y su respuesta por tipo. `perfiles validar` incluye `check_workup` y `check_durations`.
- **Para la 4.6:** la carga del médico es un 5 % mayor que en el modelo provisional (32,38 frente a 30,84 min por paciente); la plantilla lo absorberá.
- **Mejora menor:** separar en dos el test de la regla de los k (la regla y el literal).
