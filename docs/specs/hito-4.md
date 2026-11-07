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
- Primera calibración: parámetros directos contra datos y plantilla (enfermería de triaje y médicos) contra horquillas observadas, con objetivos de ajuste y de comprobación en `config/objetivos.toml`.
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
| Gumbel-max | Un sorteo por categoría y gana el mayor log w + g. Misma distribución, y al cambiar un peso solo cambian los pacientes que entran o salen de esa categoría (3,37 %, el mínimo posible, frente al 15,55 % con la CDF inversa en el ejemplo de la gripe; tarea 4.7) |
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

**Ejemplo a mano** (valores orientativos de la sesión). Disnea con peso base 8, factor 2,4 en mayores y 1,5 en invierno: 8 × 2,4 × 1,5 = 28,8. Con todos los motivos, la suma es 126,54, y la disnea queda en 22,8 % de los mayores un martes de invierno (126,74 y 22,7 % con la parada al 0,5 % del catálogo, antes de la tarea 4.6a).

**Sorteo con Gumbel-max** (flujo 6, 17 sorteos fijos por paciente). Cada motivo recibe un g\_m de una Gumbel estándar y gana el mayor `log w_m + g_m`. La distribución es exactamente la categórica y no hace falta renormalizar. Al cambiar el peso de un motivo, solo cambian los pacientes que entran o salen de él: con la disnea ×1,5 cambia el 3,37 % de los pacientes de un año, exactamente el mínimo posible (la distancia de variación total en cada banda y contexto), frente al 15,55 % con la CDF inversa en el orden de `REASON_KEYS` (decisión candidata 43). Cuando solo crece un peso, Gumbel-max alcanza siempre el mínimo: solo cambian los que pasan a ese motivo. Las cifras son exactas y salen de `reason_shock_changes` (`profiles/coupling.py`, tarea 4.7); las de la sesión conceptual (3,6 %, un mínimo de 3,5 % y 17,3 %) eran de los pesos de entonces.

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

**Gravedad** (flujo 7, una normal z por paciente): `G = media_motivo + por_edad[b] + desviacion_motivo × z`. G se mide en desviaciones típicas de la población de referencia, la mezcla de un año del perfil de llegadas: 0 es la gravedad media de un adulto. Más G es más grave. Los valores por motivo son orientativos, respetan el orden de la columna «Gravedad típica» del catálogo (un test lo comprueba) y se desplazan y escalan en común para que la mezcla tenga media 0 y desviación 1: x′ = (x + 0,104) / 1,065 (por\_edad y desviación solo se dividen), con media 0,0014 y desviación 1,0002 al redondear (con la parada de la tarea 4.6a, −0,0026 y 0,9990: dentro de 0 ± 0,01 y 1 ± 0,01, así que la transformación no se rehízo). Un desplazamiento y una escala comunes no cambian ningún nivel, porque los umbrales se mueven con ellos.

| Motivo | Gravedad típica (catálogo) | media | desviación | por\_edad (15–44, 45–64, 65–79, 80–99) | G media del año | Razón clínica (orientativa) |
| --- | --- | --- | --- | --- | --- | --- |
| Parada / crítico | Muy alta | 4,21 | 0,25 | — | 4,21 | Compromiso vital a cualquier edad; elegida por criterio en la tarea 4.6a (4,38 y 0,27 antes de la transformación; antes, 3,38 y 0,38) |
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

**Paradas a la puerta** (decisión candidata 46, tarea 4.6a). Hasta la 4.6a era un límite conocido: con el 0,5 % de paradas del catálogo, una media de 3,38 y una desviación de 0,38, justo por encima de c₁ (3,26), solo el 62,4 % de las paradas tenía nivel real 1 y el 53,1 % iba a la puerta; las demás hacían cola en el triaje. Desde la 4.6a la parada pesa un 0,3 % del catálogo y su gravedad es «orientativa, elegida por criterio»: la desviación se fija en 0,25 (poco dispersa: el compromiso vital no depende de la edad) y la media es la menor de una rejilla de 0,01 con la que, tras rederivar en cascada los pesos base, el ruido y el sesgo y los umbrales, al menos el 99 % de las paradas de un año es nivel real 1 y al menos el 97 % recibe nivel 1 asignado (`severity_mean_for`, en `profiles/derivation.py`). Sale 4,21: el 99,975 % es nivel real 1 y el 97,05 % va a la puerta; con 4,20, el 96,91 %. Manda el asignado, porque el ruido del triaje (0,334) dispersa más que la propia parada. Las dos condiciones caben en el 0,4 % de nivel 1 asignado: las paradas son el 0,302 % de los pacientes y aportan 0,293 puntos (el 73,4 % del nivel 1 asignado); el resto es sobre todo disnea (0,050), neurológico (0,036) y dolor torácico (0,009). Del nivel real 1 (0,388 %), el 77,8 % son paradas.

**Triaje** (flujo 1, una normal zₑ por paciente): `ε = sesgo + ruido × zₑ`. El nivel asignado es G + ε cortada por los umbrales c₁ > c₂ > c₃ > c₄ (nivel 1 si supera c₁, nivel 5 si queda por debajo de c₄). El nivel real es G cortada por los mismos umbrales. El nivel k es el intervalo (c\_k, c\_{k−1}\]: un valor justo en un umbral se queda en el nivel menos urgente.

**Umbrales derivados y escritos.** Los umbrales se calculan para que el reparto *asignado*, sobre la mezcla de G + ε de un año del perfil de llegadas, sea el objetivo del TOML (adultos de Emergencias 2013: 0,4 / 12,1 / 33,6 / 52,6 / 1,4 %, que suman 100,1 por el redondeo y se normalizan). El cálculo es exacto: una raíz por umbral sobre una suma de normales, una por motivo y banda de edad. Como los pesos base, `thresholds_for(...)` se ejecuta una vez y su resultado se escribe en el TOML con el comando en un comentario; un test comprueba que los escritos siguen siendo los derivados. **No se recalculan al cargar los perfiles**: un escenario con más gravedad (un brote de gripe, un accidente con múltiples víctimas) debe dar más niveles urgentes, y si los umbrales se recalcularan el reparto volvería al objetivo y el shock desaparecería. Con la disnea ×1,5 y los umbrales del perfil base, el nivel 2 asignado pasa del 12,10 % al 13,13 % (del 12,09 % al 13,10 % antes de la tarea 4.6a). El reparto objetivo se cumple por construcción solo en el perfil base. Como el ruido ensancha la distribución observada, el reparto real es más estrecho que el asignado: el ruido «inventa» niveles 1 y 5.

**Calibración del error.** Con G normal estándar y el reparto de adultos, un ruido de 0,32 y un sesgo de −0,08 dan un 10,2 % de infratriaje y un 6,2 % de sobretriaje, cerca del dato más reciente, de Asturias (10,1 % y 6,3 %). Un ruido simétrico sin sesgo daría más sobretriaje que infratriaje. Con esos valores, el 31 % de los niveles 1 reales se asigna como 2 y el 17 % de los niveles 5 reales sube a 4: los errores se concentran en los niveles raros, de franjas estrechas.

| Nivel real \\ asignado (%), G normal estándar | 1 | 2 | 3 | 4 | 5 |
| --- | --- | --- | --- | --- | --- |
| 1 | 69,1 | 30,9 | 0 | 0 | 0 |
| 2 | 1,3 | 76,5 | 22,2 | 0 | 0 |
| 3 | 0 | 6,5 | 75,4 | 18,2 | 0 |
| 4 | 0 | 0 | 7,1 | 91,5 | 1,4 |
| 5 | 0 | 0 | 0 | 16,8 | 83,2 |

Valores exactos, por integración, con G normal estándar. La versión anterior de esta tabla salió de un millón de pacientes sorteados: la fila del nivel 1 (unos 3400 pacientes) tenía alrededor de 0,8 puntos de error de muestreo.

**Con la mezcla real.** La mezcla de motivos y edades no es normal: tiene una cola grave (las paradas) y motivos de mucha dispersión. `triage_error_for(...)` ajusta ruido y sesgo a los objetivos de Asturias, recalculando los umbrales en cada paso, y da 0,334 y −0,081 (0,333 y −0,081 antes de la tarea 4.6a), que también se escriben en el TOML (calibrados). Con los valores escritos, el infratriaje es del 10,10 % y el sobretriaje del 6,29 %.

| Nivel real \\ asignado (%), mezcla real | 1 | 2 | 3 | 4 | 5 |
| --- | --- | --- | --- | --- | --- |
| 1 | 90,8 | 9,2 | 0 | 0 | 0 |
| 2 | 0,4 | 78,9 | 20,7 | 0 | 0 |
| 3 | 0 | 6,1 | 75,5 | 18,4 | 0 |
| 4 | 0 | 0 | 7,8 | 90,5 | 1,7 |
| 5 | 0 | 0 | 0 | 19,5 | 80,5 |

Umbrales \[3,341; 1,130; −0,047; −2,164\]; reparto real 0,39 / 12,51 / 35,82 / 50,62 / 0,65 % frente al asignado 0,40 / 12,10 / 33,56 / 52,54 / 1,40 % (tarea 4.6a). Antes de la 4.6a, con la parada al 0,5 % y la gravedad de 3,38: umbrales \[3,260; 1,140; −0,044; −2,163\], el 72,4 % de los niveles 1 reales asignado como 1 y el 27,6 %, como 2; ahora, el 90,8 % y el 9,2 %.

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

**El porcentaje del TOML no es el del paciente típico del motivo.** Es el de un adulto con G = 0, y el motivo tiene su propia gravedad y su mezcla de edades: la parada escribe un 36 % de analítica y pide un 99 % en el año (98 % antes de la tarea 4.6a, con su gravedad anterior). Por eso cada p se eligió por su **marginal de un año** (el porcentaje de los pacientes del motivo a los que se pide), que es la que se lee clínicamente, y el TOML la lleva en un comentario, calculada con los enteros escritos (`workup_model(...).order_by_reason()`). Su estado es «orientativo, elegido por su marginal». Un test compara las 68 marginales, el porcentaje global de cada tipo y el de alguna prueba con una tabla literal (a 0,05 puntos), y otro comprueba que los comentarios siguen siendo las marginales exactas: si cambian los odds ratios, la gravedad, la mezcla o el perfil de llegadas, hay que actualizarlos.

**Resultado y respuesta.** Cada tipo sortea también su resultado (normal o alterado, otra logística sobre G: `logit(base) + ln(OR)·G`; con base 30 y OR 2,5, 30,00 / 51,72 / 72,82 % con G = 0, 1 y 2) y su tiempo de respuesta (lognormal por mediana y p90, con un factor por franja). El paciente espera a la prueba más lenta de las pedidas; con ninguna pedida no hay ronda, y `round_turnaround` devuelve `None` (en la 4.5a, `needs_tests=False`). El resultado no lo usa nadie todavía: lo usará el destino del hito 5, y se sortea ya para que el flujo de pruebas no cambie de consumo entre hitos. Una prueba se pide si su uniforme es estrictamente menor que la probabilidad, y sale alterada igual, como en el `ProvisionalSampler`.

**La franja se aplica al pedir** (decisión de la tarea 4.4). El muestreador da la respuesta *base* de cada tipo (factor 1) y el motor, desde la 4.5a, la multiplica por el factor de la franja del *pedido*, no de la llegada: `round_turnaround(pedidas, respuestas, turnaround_shift_factors(perfiles, franja_del_pedido))`. Es exacto, porque multiplicar una lognormal por k equivale a multiplicar su mediana por k, y la máxima se calcula entonces porque los factores son distintos por tipo. Ejemplo: analítica (75) y ECG (12) pedidas e imagen (200) no; la ronda dura 75 de mañana y 82,5 de tarde (analítica ×1,1).

**Consumo fijo** (flujo 3): tres sorteos por tipo, en el orden analítica, radiografía, ECG e imagen (uniforme de pedir, uniforme de resultado y normal de respuesta), doce por paciente, se pida o no cada prueba. Las pruebas usan G y no G + ε: con otro ruido de triaje, ninguna prueba ni duración cambia.

**En el log**, un solo pedido y un solo resultado por ronda, con la lista dentro: `test_ordered` lleva `pruebas` (por ejemplo `["analitica", "ecg"]`) y `test_resulted` llega con la más lenta y lleva `resultados` (por ejemplo `{"analitica": "alterado", "ecg": "normal"}`). El orden de los eventos no cambia. El tiempo de respuesta de cada tipo va al ground truth.

**Duraciones** (flujo 2, tres normales por paciente: triaje, valoración y reevaluación). La parametrización es la del hito 3: μ = ln(mediana) y σ = (ln p90 − ln mediana) / z₀,₉, con z₀,₉ = 1,28155. La valoración y la reevaluación tienen una base por nivel real, y cada motivo aplica un factor sobre la mediana:

```latex
\mu = \ln(k_m \cdot \text{mediana}_{n}), \qquad \sigma = \sigma_{n}, \qquad E[S] = k_m \cdot E[S_{n}]
```

Multiplicar la mediana por k desplaza la lognormal sin cambiar σ, y la media también queda multiplicada por k. Con base 20 y 45 minutos (σ = 0,6328), la media es 24,43; con k = 1,2, la mediana es 24, el p90 54 y la media 29,32. El triaje tiene una sola lognormal para los niveles 2 a 5, sin factor por motivo; se sortea siempre y el nivel 1 no lo usa. La reevaluación se sortea siempre y solo se usa si hay ronda. Las duraciones son orientativas y fijas durante la calibración del hito 4 (ver «Calibración»).

**Regla de los k.** Los k reparten la duración entre motivos sin cambiar la carga: con los k, la carga de valoración de un año queda a 1 ± 0,05 de la carga sin ellos (un test lo comprueba sobre `config/perfiles.toml`). Con los valores orientativos, la razón es 1,0053 y la media simple de k por paciente, 0,9904 (1,0052 y 0,9905 antes de la tarea 4.6a).

**Carga del médico por paciente**: E\[valoración\] + E\[reevaluación · 1{alguna prueba}\], con G dentro de la integral, porque mueve el nivel real y las pruebas a la vez. Las medias por nivel real, sin k, son 48,87 / 37,33 / 27,01 / 18,66 / 12,91 minutos de valoración y 17,36 / 14,14 / 11,58 / 9,02 / 6,95 de reevaluación; con el reparto real exacto, 24,07 y 10,60. Con los k y las pruebas del perfil, 24,20 + 8,18 = 32,37 minutos, frente a los 30,84 del modelo provisional (24,43 + 55,41 % × 11,58): la valoración baja un poco y toda la subida viene de la reevaluación, porque el 72,75 % de los pacientes tiene alguna prueba (55,41 % en el provisional). Antes de la tarea 4.6a, 32,38 minutos y el 72,79 %. Es una comprobación clínica, no un objetivo.

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

En memoria, `pruebas` es una tupla y `resultados` un mapping de solo lectura con las claves en el orden de `TEST_TYPES`: el evento sigue inmutable, comparable con `==` y con pickle y deepcopy, y la ida y vuelta por JSONL da el mismo evento. Cada `test_resulted` se lee solo, sin buscar su pedido. Un log lleva una sola versión, la de su `EventLog(..., schema_version=...)`; `read_events` valida cada evento con el catálogo de su versión, y `_upgrade` (el `circuito` de los logs anteriores a la 4.1) solo actúa en la versión 1. Ningún catálogo lleva G, z, nivel real, calidad, salto, banda ni respuestas; un test lo comprueba. Los valores aceptados (los 17 motivos, los medios, los sexos, los tipos de prueba y los resultados) están fijados en un test literal: cambiar cualquiera exige una versión 3 del catálogo.

**Catálogo versión 3** (tarea 4.6a). La versión 3 es la 2 más `box_released` (sistema `his`), al final del catálogo; los demás tipos son los mismos objetos de la 2. Su payload es `box` (el box que deja) y `espera` (por qué lo deja; hoy solo `"resultados"`): el paciente sigue dentro, porque no hay `patient_departed`, y espera sus resultados fuera del box (ver «Espera de resultados fuera del box»). El modelo clínico escribe siempre la 3, también con `espera_resultados_fuera = []`: una versión por modelo, no por configuración. Por eso, volver a simular una ejecución clínica de la tarea 4.5b desde sus copias da los mismos eventos con `schema_version` 3 (un test comprueba que, sin sala, el log de la 3 con el número de la 2 es byte a byte el de antes). Las versiones 1 y 2 se siguen leyendo. `CLINICAL_SCHEMA_VERSION` desaparece, como `SCHEMA_VERSION` en la 4.5a, para que un uso antiguo falle al importar en vez de perder los logs nuevos; entran `CURRENT_CLINICAL_SCHEMA_VERSION` (3) y `CLINICAL_SCHEMA_VERSIONS` ({2, 3}, las versiones con payloads clínicos). El literal de valores de la 3 es el de la 2 más `espera`.

**Espera de resultados fuera del box** (decisión candidata 45, tarea 4.6a). Con el modelo clínico, un paciente cuyo nivel *asignado* está en `espera_resultados_fuera` (`centro.toml`) deja el box al pedir las pruebas: emite `test_ordered` y, en el mismo instante, `box_released`, y devuelve el box como en una salida, así que quien lo recibe va detrás en el log. Espera los resultados en una sala sin límite de capacidad y sin recurso, así que nadie puede desalojarlo. Con el `test_resulted` vuelve a pedir box con su clave de siempre, `priority_key(nivel, llegada)`, como un desalojado (otro `box_assigned`, quizá con otro número), y en ese box hace la reevaluación, la decisión y la salida. Decide el nivel asignado, lo que ve el hospital: un infratriado de nivel real 3 asignado como 4 sale del box, y un sobretriado de nivel real 4 asignado como 3 no. El provisional nunca deja el box. Escenario a mano (un box, noche): A (nivel 4) recibe el box en 10, pide un ECG en 30 y lo deja; B, que esperaba desde 11, lo recibe en 30; los resultados de A llegan en 42; en 70, A recupera el box por delante de C, que espera desde 25 pero llegó después (clave (4, 5) frente a (4, 20)); A ocupa el box 20 + 10 minutos, no los 60 de la ronda.

**Cambios en el motor**, pequeños y explícitos; la lógica de colas, recursos y turnos no cambia:

1. Los payloads del catálogo versión 2, con el modelo clínico; `triage_started` lleva `circuito` en las dos versiones.
2. El nivel 1 en la puerta: una rama en `patient.py` sin petición de enfermera.
3. `check_capacity`, la escalera de enfermeras y la identidad de utilización no cuentan los triajes con `circuito: "puerta"`; «nadie se cuela» se amplía al triaje (nadie adelanta en su cola salvo un nivel 1).
4. La respuesta de la ronda con la franja del pedido (ver arriba).
5. La sala de resultados (tarea 4.6a): `leaves_for_results` (modelo clínico y nivel asignado en `espera_resultados_fuera`), `box_released` después de `test_ordered` y la vuelta con la misma clave.

**Invariantes nuevas** (tarea 4.5a), en `CHECKS`:

- `door`, con los dos modelos: un triaje con `circuito: "puerta"` va con un `triage_completed` de nivel 1, y al revés; en la puerta, `triage_started` y `triage_completed` ocurren en el instante de la llegada. Lo contrario no se exige: un triaje de enfermería también puede empezar al llegar, si hay una enfermera libre.
- `schema_version`: una sola versión en el log.
- `clinical`, con logs clínicos (versiones 2 y 3): los tipos de `resultados` son los `pruebas` del pedido del episodio; con el ground truth, `medio`, `edad`, `sexo`, `nivel` (el asignado), `motivo`, `pruebas` y `resultados` coinciden con la verdad; con el ground truth y los perfiles (`check_invariants(..., profiles=...)`), la respuesta observada de cada ronda (`test_resulted − test_ordered`) es la máxima de factor(franja del pedido) × base, calculada aparte, con una tolerancia absoluta de 1e-8 minutos.

**Invariantes de la sala** (tarea 4.6a). `TRANSITIONS` gana el estado `results_room`: `box_released` lleva a él desde `awaiting_tests` y solo `test_resulted` sale de él, a `waiting_box_reassessment`, así que la vuelta llega solo con los resultados y la reevaluación es siempre en un box. `capacity` y `displacement` liberan el box en `box_released`: los pacientes de la sala no cuentan en la capacidad. «Nadie se cuela» abre la espera de box de la vuelta en el `test_resulted`, con la clave de la llegada. Y `results_wait`, nueva en `CHECKS` y solo en logs de la versión 3, exige que dejen el box exactamente los niveles asignados de `espera_resultados_fuera` del centro: el `test_ordered` de uno de esos niveles va seguido de su `box_released` en el mismo instante, y un `box_released` solo puede seguir al de uno de ellos. `door` y `clinical` funcionan con la versión 3.

**Logs anteriores a la tarea 4.1.** `_upgrade` los lee con `circuito: "enfermeria"` en todos sus triajes, también en los de sus niveles 1, porque entonces el nivel 1 pasaba por la enfermera. Si se recalculan sus invariantes con las reglas de hoy, `door` marca cada uno de esos niveles 1. Es lo esperado: esas ejecuciones guardaron 0 violaciones en `run.json` con las reglas de su momento, y `runs/results.py` solo recalcula las invariantes de una ejecución que guardó alguna, así que en la app no cambian.

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

**Huellas.** Las huellas SHA-256 del modelo provisional cambian una sola vez, en la tarea 4.1, por el nivel 1 en la puerta y el campo `circuito`; su PR lo justifica. Después no deben cambiar en ninguna tarea del hito, y no cambiaron en la 4.5a. El modelo clínico tiene sus propias huellas desde la tarea 4.5a, con el centro, las llegadas y los perfiles de ejemplo, semilla 2026 y 3 días: la del log y la del ground truth, una línea JSON por episodio (`json.dumps(asdict(e), ensure_ascii=False, allow_nan=False, separators=(",", ":"))`, con el `EpisodeTruth` entero). Se regeneran solo con un cambio a propósito de los muestreadores o de `ClinicalTruth`, explicado en el commit. En la tarea 4.6a se regeneraron una vez por fase: en la A, el log y el ground truth (la parada y la cascada); en la B, solo el log, por el `schema_version` 3, porque `centro_ejemplo.toml` no tiene sala y el ground truth no cambia. La sala se caracteriza aparte, con `centro_sala_ejemplo.toml` (el centro de ejemplo más `espera_resultados_fuera = [4, 5]`) en `motor simular --perfiles`: sus CSV son los de la caracterización sin sala salvo las columnas `centro` y `huella_centro`. El formato estable del ground truth es el CSV clínico de la tarea 4.5b (ver «Ejecuciones clínicas en disco»), con su propia caracterización.

## Ejecuciones clínicas en disco

Desde la tarea 4.5b, una ejecución del modelo clínico se guarda en `resultados/` con el contrato de la fase 1 de la app (decisión 32): se copia primero, se escribe en una carpeta oculta, `run.json` va el último y la carpeta se publica con un solo renombrado. El modelo provisional no cambia ni un byte, salvo `run.json`.

**CSV del ground truth clínico** (`engine/report.py`). Lleva todo lo que tiene un `EpisodeTruth`, incluidos la z de la gravedad y los 12 sorteos de las pruebas, así que leerlo da el mismo `EpisodeTruth` con `==`, floats bit a bit (escritos con `repr`). Tiene 57 columnas: las 10 de datos del provisional (`respuesta_pruebas` vacía, que se lee como `None`), las 37 clínicas, los 8 parámetros de la ejecución y `perfiles` y `huella_perfiles`.

| Grupo | Columnas |
| --- | --- |
| Contexto | `franja` (`manana`, `tarde`, `noche`), `tipo_dia` (`laborable`, `fin_de_semana`) y `estacion` (`invierno`, `primavera`, `verano`, `otono`), por nombre |
| Persona | `banda` (índice 0 a 3: los límites son de los perfiles), `edad`, `sexo` y `medio`, con las palabras del log |
| Motivo | `motivo` |
| Triaje | `z_gravedad`, `gravedad`, `nivel_real`, `calidad_triaje` y `salto`; el nivel asignado es la columna `nivel`, sin duplicarla |
| Pruebas | `pedida_<tipo>`, `alterada_<tipo>` y `respuesta_base_<tipo>` (factor 1), cuatro de cada, en el orden de `TEST_TYPES` |
| Sorteos del flujo 3 | `sorteo_pedida_<tipo>`, `sorteo_alterada_<tipo>` y `sorteo_respuesta_<tipo>` de cada tipo, en el orden de `Workup.draws` |

`write_episodes_csv(..., profiles=ProfilesParameters(...))` escribe el clínico. Son errores de uso, comprobados antes de crear el fichero: un episodio clínico sin perfiles, uno provisional con ellos, y un episodio clínico que no se puede leer de vuelta (con `test_turnaround`, o con el nivel o `needs_tests` en contradicción con su verdad). `episode_from_row` lee una fila de cualquiera de los dos modelos con tokens exactos y comprobaciones de coherencia (`calidad_triaje` y `salto` con los dos niveles, `pruebas` con las pedidas). `read_episodes_csv` lee el fichero entero y exige la cabecera exacta y los mismos parámetros en todas las filas. El CSV de días es el mismo con los dos modelos, porque las llegadas no dependen de los perfiles.

**`run.json` versión 2** (`runs/store.py`). Es la versión 1 más `model` (`"provisional"` o `"clinico"`) y, solo con el clínico, `clinical_profiles_path` (la ruta original) y `clinical_profiles_fingerprint` (la huella de la copia). Los nombres no se confunden con `profile_path` y `profile_fingerprint`, que son del perfil de llegadas. En `RunInfo` los dos campos son opcionales: el modelo los explica y `__post_init__` exige que existan con el clínico y que sean `None` con el provisional. `read` exige las claves exactas de su versión, sin que los valores por defecto rellenen ninguna; la versión 1 (16 claves) se lee como provisional, y una versión desconocida es un error. `write` solo escribe la 2, sin claves nulas. `RunStore.archive` comprime 7 ficheros en una ejecución clínica, con `perfiles.toml`, y 6 en una provisional. `tests/data/run_v1.json` es un `run.json` real de la versión 1, escrito antes de la 4.5b.

**`simulate_run(..., profiles=None)`**. Con perfiles, copia `perfiles.toml` a la carpeta, como `centro.toml` y `llegadas.toml`, carga desde la copia y calcula su huella sobre ella. Después simula con `simulate_ed(..., profiles=...)`, escribe el CSV clínico y pasa los perfiles a `check_invariants`, que comprueba la respuesta de cada ronda con la franja de su pedido. Volver a simular desde las copias de la carpeta da el mismo log, también con perfiles.

**Emparejamiento mínimo** (`runs/compare.py`). `pairing_blockers` añade, detrás de los bloqueos de antes, `model` y `clinical_profiles_fingerprint`: dos ejecuciones de modelos distintos, o clínicas con perfiles de huella distinta, no son los mismos pacientes. El formato de `run.json` no bloquea: una versión 1 y una 2 provisionales se emparejan.

**Pendiente para la tarea 4.8a.** `runs/truth.py` lee hoy solo el CSV provisional: para el clínico usará `episode_from_row`, con su comprobación contra `run.json`. Queda también el emparejamiento clínico con el ground truth (sorteos estándar por paciente). `read_run_results` recalcula las invariantes sin los perfiles cuando `run.json` guarda alguna violación, así que en una ejecución clínica con violaciones el recuento puede no coincidir. Si la 4.8a guarda una ejecución antigua como dato de prueba, debe ser posterior a la tarea 4.1 o tener en cuenta que `door` marca sus niveles 1 (ver «Logs anteriores a la tarea 4.1»).

**Pendiente de la sala de resultados (tareas 4.8a y 4.8b).** Episodios y Replay con los dos tramos de box. Desde la 4.6a, `runs/_location` deja sin box al paciente de la sala y lo muestra en el estado existente `waiting_tests` mientras espera los resultados, y en `waiting_box` cuando ya los tiene: nunca hay dos pacientes en un box, y la app no necesita nada nuevo. Pero su etiqueta, «En box esperando pruebas», es inexacta para la sala: un estado propio de la sala y su etiqueta, si se quiere distinguir, son de la 4.8a (núcleo) y la 4.8b (páginas). Las dos esperas nuevas de `EpisodeRecord` (`initial_box_wait` y `results_box_wait`) tampoco están en las tablas de la app.

**Pendiente para la tarea 4.8b** (Codex, `app/src`). La app serializa el payload con `json.dumps(dict(event.payload))`, que no admite el mapping anidado de `resultados`: tendrá que usar `to_json` o un payload plano. Comparar muestra los campos nuevos de `run.json` con su nombre en inglés, porque sus etiquetas viven en `comparison_frames.py`.

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

**API del cumplimiento por nivel real** (tarea 4.7, `engine/targets.py`). Una función aparte que recibe el ground truth, para que no se pueda calcular desde el log:

- `true_level_compliance(tabla, ground_truth, primer_día, día_final, *, measure, max_wait, target)` devuelve un `Compliance`, como `manchester_compliance`, con el nivel real para agrupar a cada paciente y para elegir su máximo: un nivel 2 real asignado como 3 que ve al médico en 30 minutos cumple con su nivel asignado (60) y no con el real (10).
- `true_levels(ground_truth)` da el nivel real de cada `episode_id` y es un error con un episodio sin verdad clínica (el modelo provisional); también lo es un episodio de la tabla que falta en el ground truth.
- `true_level_waits(tabla, ground_truth, medida, primer_día, día_final)` da una medida con los dos niveles de cada episodio, emparejados por `episode_id`.
- `manchester_compliance` no cambia ni de firma ni de cuerpo. El auxiliar compartido gana un argumento opcional con el nivel de cada episodio que, sin él, hace lo de siempre. `runs/` y la calibración no usan las funciones nuevas.

En el notebook 04 (89 días, centro calibrado, reloj C), el nivel 2 cumple en el 94,6 % de sus pacientes por nivel asignado y en el 93,3 % por nivel real, con 14 y 21 días fuera; el nivel 3 pasa de 2 días fuera a 15; el nivel 5, de 40 a 24, porque muchos niveles 5 reales están asignados como 4.

**Clasificados tarde** (tarea 4.7). `classified_late(tabla, primer_día, día_final)` da la proporción de cada nivel que ya pasa estrictamente de su máximo, contado desde la llegada, al clasificarse: ningún médico puede hacerlos cumplir con el reloj A. En el notebook 04 es el 45,5 % de los niveles 2: por eso el nivel 2 queda fuera de Manchester con el reloj A los 89 días, y con el C, 14.

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

**Parámetros indirectos: dos mandos con objetivos separados, la enfermería de triaje y los médicos por turno** (decisión candidata 41, revisada el 6 de noviembre para la tarea 4.6b). La enfermería de triaje mueve el pretriaje y casi nada más; los médicos mueven la espera desde la clasificación y no tocan el pretriaje. Como cada mando tiene su objetivo, los dos son identificables y se ajustan en orden: primero la enfermería contra el pretriaje y, con ella fija, los médicos contra el tiempo hasta el médico (reloj A, que incluye el pretriaje). Con la enfermería de antes (`[3, 3, 2]`), ocupada en torno al 40 % del tiempo, el pretriaje medio era de 1,4 minutos y ningún cambio de médicos podía acercarlo a su horquilla. Menos médicos y valoraciones más largas alargan igual el tiempo hasta el médico, y en el hito 4 no hay ningún objetivo que los distinga (la estancia, que sí depende de las duraciones, se calibra en el hito 5). Calibrar los dos sería un problema no identificable. Las duraciones quedan fijas por criterio clínico y se ajusta solo la plantilla, que es una «plantilla equivalente» del modelo, no una recomendación de dotación.

**Boxes fijos y espera de resultados fuera del box** (decisión candidata 45, tarea 4.6a). Con el modelo clínico, el 64 % del tiempo de box (91,2 minutos por paciente en 14 días) era esperar resultados, y los 30 boxes llegaban al pico mientras los médicos estaban a unos 7 de 12 de media: la plantilla no habría podido mover las esperas de los niveles 4 y 5. Desde la 4.6a, los pacientes de los niveles asignados de `espera_resultados_fuera` (en `centro.toml`, `[4, 5]` en el centro base) dejan el box al pedir las pruebas, esperan los resultados en una sala sin límite de capacidad y, con los resultados, vuelven a pedir box con su misma clave de prioridad, como un paciente desalojado, para la reevaluación. Los boxes quedan fijos (30) y no se calibran: con objetivos de tiempo hasta el médico, plantilla y boxes no serían identificables. Antes de ajustar se mide la sensibilidad de los dos mandos (regla 5). El modelo provisional no cambia (sus huellas y la validación del motor siguen iguales). Con la sala (14 días, `config/`, semilla 2026, plantilla \[12, 12, 7\]), el tiempo de box por paciente sin esperas de médico baja de 91,0 a 69,8 minutos; los boxes ocupados, de 21,0 a 16,5 de media (el pico sigue en 30); la espera de box de los niveles 4 y 5, de 35,3 y 85,4 a 12,8 y 20,4 minutos (11,6 y 13,9 la inicial; 1,1 y 0,2 la de la vuelta); y el reloj C del nivel 4, del 82,7 % con 5 días fuera de 12 al 95,4 % con 2. Los médicos siguen en 7,0 de media. Lo que anticipa para la 4.6b, sin calibrar nada: con esa plantilla el tiempo medio hasta el médico (reloj A) es de 18,8 minutos en los niveles 2 a 5 y de 9,3 en el nivel 3, por debajo de sus horquillas (35–70 y 45–75), y el pretriaje medio, de 1,4 minutos, por debajo de 6–15. El pretriaje depende de la enfermería de triaje, no de los médicos: el único mando de la decisión 41 no puede moverlo. Por eso la decisión 41 se revisa: la enfermería de triaje entra como segundo mando, ajustado solo al pretriaje (6 de noviembre).

**Paradas** (decisión candidata 46, tarea 4.6a). La parada / crítico pesaba un 0,54 % con una gravedad media de 3,38 y desviación 0,38, justo por encima del umbral del nivel 1 (3,26): solo el 62 % eran nivel real 1, y el 44 % recibía nivel 2 y esperaba el triaje hasta 32 minutos. Con el nivel 1 asignado del 0,4 % no había sitio para todas. Desde la 4.6a, la parada pesa un 0,3 % en el catálogo (sigue siendo «< 1 %») y su gravedad es alta y poco dispersa, de modo que casi todas son nivel 1 real y asignado, a la puerta. Se rederivan con sus funciones y se escriben los pesos base, el ruido y el sesgo, los umbrales y las marginales de pruebas. Valores finales: media 4,21 y desviación 0,25 (la menor media que cumple ≥ 99 % de nivel real 1 y ≥ 97 % de nivel 1 asignado; ver «Paradas a la puerta»), peso base 0,324, ruido 0,334 y sesgo −0,081, umbrales \[3,341; 1,130; −0,047; −2,164\]. En un año, el 99,975 % de las paradas es nivel real 1 y el 97,05 % va a la puerta.

**Objetivos indirectos** (fijados en `config/objetivos.toml` en la tarea 4.6b). El CMBD del SAS es de 2013 e incluye niños, así que da el orden de magnitud y las horquillas son anchas.

| Objetivo | Reloj | Referencia observada | Horquilla | Uso |
| --- | --- | --- | --- | --- |
| Pretriaje medio | — | SAS 12,4 min | 6–15 min | Ajuste |
| Tiempo medio hasta el médico, niveles 2 a 5 | A | SAS 35,6 a 68,5 min según el nivel | 35–70 min | Ajuste |
| Tiempo medio hasta el médico, nivel 3 | A | SAS 59,0 min | 45–75 min | Comprobación (de ajuste hasta la tarea 4.6b; ver «El nivel 3, de ajuste a comprobación») |
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

**Regla de la plantilla equivalente** (tarea 4.6b). La plantilla de cada mando sale de un solo número u, una ocupación objetivo del turno: personal del turno = ⌈carga del turno / u⌉, al menos 1. La carga es el personal que la demanda del turno tendría ocupado sin colas: para la enfermería, llegadas por hora × (1 − p₁) × media del triaje / 60, con p₁ la proporción de nivel 1 asignado (va a la puerta); para los médicos, llegadas por hora × carga del médico por paciente / 60. Las llegadas por hora del turno son las del día medio del perfil: `base_diaria` × (reparto de las horas del turno) / horas. Con `config/` (turnos de 8, 15 y 22 h; p₁ = 0,40 %; media del triaje 5,79 min; carga del médico 32,37 min): 17,36 / 16,5 / 6,3 llegadas por hora, cargas de enfermería 1,668 / 1,585 / 0,605 y de médicos 9,365 / 8,903 / 3,399. Así la búsqueda es de una dimensión y se puede explicar: con u de 0,55 a 0,99 en pasos de 0,0025 salen 5 plantillas de enfermería, de `[4, 3, 2]` a `[2, 2, 1]`, y 20 de médicos, de `[18, 17, 7]` a `[10, 9, 4]`. No se buscan combinaciones fuera de la regla.

**Evaluación de un candidato** (ventana anual desde la tarea 4.6c). 12 réplicas, **una por mes**: la m (m = 0…11) empieza a las 00:00 del primer lunes del mes m+1 del año de `fecha_inicio` y usa el hijo m de la semilla, con números aleatorios comunes (el hijo m y su fecha son la réplica m para todos los candidatos). Cada réplica tiene el factor mensual, los días de la semana y el contexto clínico de su mes, y empezar en lunes da a todas los mismos días de la semana. Así la media entre réplicas es la del año, como los objetivos del SAS; la 4.6b medía 10 réplicas desde `fecha_inicio`, la primera quincena de enero (ver «El reloj A según el horizonte»), y esa ventana sigue disponible como `--ventana inicio`. Cada réplica simula 14 días con 2 de calentamiento y **un día de vaciado**: cada réplica simula un día más, con llegadas, y solo se mide a los llegados en la ventana `[2, 14)`. Sin él, los que llegan en las últimas horas y siguen dentro, que son los que más esperan, quedarían fuera de las medias, y el sesgo sería mayor justo en las plantillas apretadas. Los llegados en la ventana sin salida al final del horizonte (censurados) se cuentan por réplica, y la CLI avisa por encima del 0,1 %. Las medias son por paciente en la ventana, por réplica; el % de días fuera es la media entre réplicas del % de días de cada una con su valor diario fuera de la horquilla. Un objetivo pasa con la regla 4 (t₁₁ = 2,201). Con la ventana anual, el IC entre réplicas incluye la variación entre meses: es conservador, y pide que los meses no se separen más que la anchura de la horquilla. La media por paciente de las 12 réplicas (pondera cada mes por sus pacientes) se informa, pero no decide. La evaluación es una función pura de los episodios de cada réplica, aparte de la simulación.

**Criterios de elección.** Primero la enfermería y, con ella fija, los médicos (decisión 41). Entre las plantillas de la regla que pasan todos los objetivos de ajuste del mando, la de media más cercana a la referencia del objetivo que decide o, si no la tiene, al centro de su horquilla: la enfermería, con el pretriaje (12,4 min); los médicos, con el reloj A de los niveles 2 a 5, sin referencia única en el SAS (52,5 min, el centro de 35–70). Si ninguna pasa, no se fuerza. Un objetivo de comprobación nunca decide. **La semilla de comprobación puede vetar, no elegir** (decisión 41, revisada en la tarea 4.6c): si la plantilla elegida con la semilla de ajuste (2026) falla un objetivo de ajuste con la de comprobación (2027), se descarta y se toma la siguiente candidata de la regla de elección (la siguiente más cercana a la referencia o al centro de la horquilla) que pase los objetivos de ajuste con las dos semillas; si ninguna pasa con las dos, no se elige. Como 2027 ha intervenido en la elección, la comprobación independiente pasa a la semilla 2028. El centro cumplidor tiene la misma enfermería y los médicos de la regla con el u más alto (menos médicos) con el que cada nivel 2 a 5 tiene como mucho un 10 % de días fuera del cumplimiento Manchester (reloj C), **con días enteros** (tarea 4.6c): los días fuera sumados en las réplicas, frente a los días con pacientes del nivel sumados, fuera × 10 ≤ medidos. No es la media de los porcentajes por réplica cuando las réplicas tienen distinto número de días con pacientes de un nivel (el nivel 5 tiene días sin ninguno): así pesa cada día, y la regla es exacta. Con `--ventana inicio`, la regla con enteros sigue eligiendo el cumplidor de la 4.6b (\[15, 15, 6\], 12 de 120 días fuera en los niveles 4 y 5). Semillas: 2026 de ajuste, 2027 de comprobación (con veto) y 2028 de confirmación después de un veto.

**El nivel 3, de ajuste a comprobación** (6 de noviembre, tarea 4.6b). Con prioridad estricta en un solo grupo de médicos, el nivel 3 casi no espera box ni médico (reloj C de 4,4 min) y las esperas recaen en los niveles 4 y 5, así que ninguna plantilla de la regla lleva su reloj A por encima de 22,9 min (horquilla 45–75) y los dos objetivos del reloj A no se pueden cumplir a la vez. En los hospitales reales los niveles 4 y 5 suelen tener circuito propio y el nivel 3 compite con el 2: es una discrepancia estructural, y el objetivo pasó a comprobación después de medir la sensibilidad (regla 5), no antes.

**Resultados de la calibración** (tarea 4.6c, con la ventana anual; tablas, comandos y tiempos en el [registro de calibración](https://github.com/pdromer0/edsim/blob/main/docs/calibracion/registro.md), que guarda también la de la 4.6b). La sensibilidad confirma la separación de los mandos: el pretriaje es el mismo con cualquier plantilla de médicos salvo por los censurados, que no se miden, y la enfermería no mueve la espera desde la clasificación.

| Mando | 4.6b | 4.6c (u) | KPI con la semilla 2026 | Con 2027 | Con 2028 |
| --- | --- | --- | --- | --- | --- |
| Enfermería de triaje | \[3, 2, 1\] | **\[3, 2, 1\]** (0,795–0,8325) | Pretriaje 6,78 min \[5,49; 8,06\] | 7,86 \[6,31; 9,41\] | 7,76 \[6,48; 9,03\] |
| Médicos | \[12, 11, 5\] | **\[12, 11, 4\]** (0,85) | Reloj A, niveles 2 a 5: 27,75 → 42,10 min \[28,02; 56,18\] | 43,29 \[33,11; 53,47\] | 41,20 \[33,57; 48,84\] |

Con la ventana anual, el centro de la 4.6b da 27,75 min de reloj A, por debajo de 35–70. En la enfermería pasan \[3, 2, 1\] (6,78) y \[2, 2, 1\] (13,21), y la regla elige \[2, 2, 1\], la más cercana a 12,4; con 2027 su pretriaje sale de la horquilla (15,16 \[10,61; 19,71\]: la media pasa de 15 y el IC mide 9,10), así que el veto la descarta y queda \[3, 2, 1\], que pasa con las dos semillas. Con esa enfermería, solo \[12, 11, 4\] pasa el reloj A de los niveles 2 a 5, con un único punto de la rejilla (u = 0,85): con \[12, 11, 5\], 27,75; con \[11, 11, 4\], 50,23 de media pero un IC de 44,87 de ancho. Las comprobaciones con 2027: porcentaje sobre Manchester, 16,79 % (10–30); pretriaje de más de 5 minutos, 32,91 % (30–60); el nivel 3, 20,13 min, fuera, por la discrepancia. Con 2028, los dos objetivos de ajuste pasan y no hay censurados. Con 2026 hay 8 censurados, todos en enero (0,20 %).

El centro cumplidor (`config/centro_cumplidor.toml`) tiene los médicos `[14, 14, 6]` (u de 0,67 a 0,6775): días fuera de Manchester con el reloj C de 1/144, 0/144, 2/144 y 6/142 en los niveles 2 a 5, y reloj A de los niveles 2 a 5 de 15,65 min, por debajo de la horquilla, como se espera de un centro que cumple.

**Enero con una plantilla anual** (tarea 4.6c; tablas en el registro). La plantilla es la misma todo el año y la regla 4 pide que la media del año caiga en la horquilla, así que enero, el mes de más carga (factor 1,10), queda cerca de la saturación. Con \[3, 2, 1\] + \[12, 11, 4\], el reloj A de los niveles 2 a 5 por mes va de 105,2 min en enero a 24,6 en agosto con 2026, y de 78,6 en enero a 22,6 en junio con 2027 (noviembre, 62,3). El paso que lleva el año dentro de la horquilla es el de 5 a 4 médicos de noche: la carga de la noche es de 3,399 médicos, u nominal 0,68 con 5 y 0,85 con 4, y 0,93 con el factor de enero. Con 2026 quedan 8 pacientes de enero censurados (0,20 %); ninguno en otro mes ni con 2027 o 2028. El pretriaje de noche, con el método del 18,6 de la 4.6b y la ventana anual, es de 15,6 min con \[3, 2, 1\] (enero 23,8) y de 18,4 con \[2, 2, 1\]: con dos enfermeras de mañana la cola de la mañana pasa a la tarde y a la noche. Un refuerzo de invierno queda para versiones posteriores.

**El reloj A según el horizonte** (tarea 4.7, revisión del PR #49; tablas en el registro). El reloj A de los niveles 2 a 5 no crece por el arranque vacío: con el factor mensual neutro, los bloques de 14 días de 5 semillas × 56 días dan de 26,8 a 33,9 min y el primero (28,3) no queda por debajo, así que 2 días de calentamiento bastan. Lo mueven el mes (enero, con el factor 1,10, da 57–62 min; febrero, 34–43) y la acumulación en días malos: en la semilla 2026, cuatro días seguidos con más llegadas (19 a 22 de enero) dejan la cola de box de un día para otro y llevan el reloj A de esa semana a 132 min. La calibración mide la primera quincena de enero, el mes de más carga, y con la carga media del año el centro da unos 28 min, por debajo de la horquilla, mientras que los objetivos del SAS son medias anuales. Resuelto en la tarea 4.6c con la ventana anual (una réplica por mes; el calentamiento no era el problema): ver «Evaluación de un candidato» y «Resultados de la calibración».

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
ruido = 0.334                       # calibrado con triage_error_for; desviación del error, en unidades de G
sesgo = -0.081                      # calibrado; negativo: tiende a infratriar
umbrales = [3.341, 1.130, -0.047, -2.164]   # derivado con thresholds_for; no se recalcula al cargar
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
- Unidades clínicas en el fichero (porcentajes, minutos, factores, odds ratios); el código calcula pesos normalizados, interceptos y μ y σ. Ningún número derivado se escribe a mano. Los pesos base (`base_weights_for`) y los umbrales (`thresholds_for`) se derivan una vez y se escriben con un comentario, y ruido y sesgo se calibran con `triage_error_for`; un test comprueba que los escritos son los recalculados. Desde la tarea 4.6a, `derive_written_values` (`profiles/derivation.py`) ejecuta los tres en cascada, redondeados a 3 decimales como se escriben, y otro test comprueba que la cascada entera reproduce el fichero.
- La parada (tarea 4.6a) es el 0,3 % del catálogo y su gravedad, «orientativa, elegida por criterio» con `severity_mean_for` (media 4,21 y desviación 0,25), con el comando en un comentario del TOML y una guarda con Φ a mano: ≥ 99 % de nivel real 1 y ≥ 97 % de nivel 1 asignado en el año.
- Factores opcionales: si faltan valen 1. Claves desconocidas prohibidas, con un error que nombra la clave y el motivo. Longitudes validadas: 4 bandas, 3 franjas, 2 tipos de día, 4 estaciones, 5 niveles y 4 tipos de prueba.
- Pruebas: los cuatro tipos (`TEST_TYPES`: analitica, radiografia, ecg, imagen) son fijos en el código y obligatorios, en `[pruebas.<tipo>]` y en el `pruebas` de cada motivo. En cada tipo, `respuesta`, `or_gravedad` y `alterado = { base, or_gravedad }` son obligatorios; `respuesta_franja` y `or_mayor`, opcionales. Los porcentajes de pedir y de alterado van en (0, 100), con un error que nombra la clave y el valor, y cada `[mediana, p90]` exige mediana > 0 y p90 > mediana.
- Los 17 motivos son obligatorios, con los nombres del catálogo en `snake_case`.
- `centro.toml` gana en la tarea 4.6a `recursos.espera_resultados_fuera`: los niveles asignados (2 a 5, en orden creciente y sin repetir; el 1 tiene su propio error, porque se clasifica en la puerta y nunca sale del box) que esperan los resultados fuera del box. `[4, 5]` en `config/centro.toml`. Es la única clave opcional del centro y, si falta, vale `[]` y no `[4, 5]`: así la copia de `centro.toml` de una ejecución anterior a la 4.6a sigue significando lo mismo (nadie espera fuera) y las ejecuciones guardadas se siguen abriendo. Solo la usa el modelo clínico: el provisional la ignora y no cambia ni un bit. `tests/data/centro_ejemplo.toml` no la lleva, porque los CSV del provisional guardan la huella de los bytes del centro; `tests/data/centro_sala_ejemplo.toml` es una copia con ella, y un test compara sus valores. La app no la edita: su editor no la muestra y las variantes la conservan tal cual. En `runs/compare.py` no cambia ningún sorteo, como los boxes.
- Hasta el cierre, `centro.toml` conserva sus secciones provisionales (`[triaje]`, `[duraciones]`, `[pruebas]`, `[destino]`) para el modelo provisional; en la tarea 4.9 pierde las tres primeras y conserva `[destino]` hasta el hito 5.

`config/objetivos.toml` guarda cada objetivo de calibración con su fuente al lado, para que el notebook, la CLI y los tests lean lo mismo:

```toml
[objetivos.tiempo_medico_nivel_3]
medida = "door_to_doctor"           # reloj A
niveles = [3]
estadistico = "media"
referencia = 59.0
horquilla = [45, 75]
uso = "comprobacion"                # ajuste o comprobacion (de ajuste hasta la tarea 4.6b)
fuente = "SAS, CMBD de urgencias 2013"
enlace = "https://www.sspa.juntadeandalucia.es/..."
nota = "Incluye menores de 15 años"
```

Reglas de `objetivos.toml` (tarea 4.6b): claves desconocidas prohibidas y errores con la clave completa (`objetivos.<nombre>.<clave>`); `medida`, `niveles`, `estadistico`, `horquilla`, `uso`, `fuente` y `enlace` obligatorias. `estadistico` es `"media"` o `"porcentaje_sobre_umbral"`; con el porcentaje, `umbral` es obligatorio (minutos o `"manchester"`, el máximo del nivel asignado de cada paciente; cuenta quien queda estrictamente por encima) y la horquilla va en \[0, 100\]; con la media, `umbral` no se admite. La horquilla exige mínimo < máximo. `referencia` es opcional (el SAS no da una cifra única para los niveles 2 a 5) y, si está, cae dentro de la horquilla; `nota` es opcional. `uso` es `"ajuste"` o `"comprobacion"`. Lo que busca la elección es la referencia o, sin ella, el centro de la horquilla (`Target.aim`).

## Salidas: CLI

La CLI sigue siendo fina: lee argumentos, llama al paquete y escribe.

```bash
edsim motor simular --perfiles config/perfiles.toml --dias 14 --calentamiento 2 --semilla 2026 --salida resultados/motor
edsim perfiles validar --perfiles config/perfiles.toml --pacientes 20000 --semilla 2026 --salida resultados/perfiles
edsim calibracion evaluar --perfiles config/perfiles.toml --objetivos config/objetivos.toml --ventana anual --semilla 2026 --salida resultados/calibracion
edsim calibracion sensibilidad --mando enfermeria_triaje --ventana anual --semilla 2026 --comprobacion 2027 --salida resultados/calibracion
```

- `motor simular` acepta `--perfiles`, sin valor por defecto; sin él usa el modelo provisional, como hasta ahora (decisión 44). La ejecución se escribe con `simulate_run`, y `run.json` guarda el modelo y la huella de los perfiles cuando los hay. La cabecera dice el modelo («Modelo clínico · perfiles … (huella …)» o «Modelo provisional»). Si el fichero de perfiles no existe o no es válido, código 2 antes de imprimir nada o de crear ningún fichero.
- `perfiles validar` prueba el muestreador sin el motor (tarea 4.5b): `--perfiles` y `--llegadas` (por defecto los de `config/`), `--pacientes`, `--semilla` y `--salida` (por defecto `resultados/perfiles`). `validate_profiles` ejecuta `check_mixing` con el hijo 0 de la semilla y sortea **una sola vez** la muestra del año, con el hijo 1, para el triaje, las pruebas y las duraciones. Cada fila es `==` a su `check_*` con esa semilla: con la misma semilla, las tres sortean los mismos pacientes.
  - `--pacientes N` es N por contexto en la mezcla (24 × N) y N en la muestra del año. Sin la opción, 25 000 por contexto (`DEFAULT_MIXING_PATIENTS`; 20 000 hasta la tarea 4.6a) y un año del perfil de llegadas (109 542 con `config/`).
  - Los mínimos se comprueban antes de sortear (código 2). La mezcla calcula lo esperado de cada motivo dentro de una banda con el recuento *observado* de la banda, que es aleatorio: en el mínimo exacto (20 491 por contexto con `config/`, por la parada en 15–44 años, tarde laborable de invierno: P(banda) = 0,38 y P(parada | banda) = 0,0642 %) pararía el 50,0 % de las veces. `check_profiles_validation_counts` exige el N con el que la probabilidad de parar, acotada con la binomial de cada banda y la unión de bandas y contextos, es menor que 1e-6: 21 379 por contexto (+4,3 %). El año exige 16 545 (la parada, el 0,302 % de los pacientes, con 50 esperados en las medianas por motivo). Con la parada al 0,5 % (hasta la 4.6a), mandaban la intoxicación en 80–99 años (13 993 y 15 234) y el nivel real 1 (11 826); con 20 000 por contexto, la mezcla ya no bastaría, y un test vigila que `DEFAULT_MIXING_PATIENTS` ≥ `mixing_minimum`.
  - La tabla tiene una fila por comprobación: pacientes, categorías, fallos, el p mínimo frente al α de cada categoría (Bonferroni), el error detectable de una categoría de referencia con una potencia del 80 % (un motivo del 5 %; el nivel 1 asignado; pedir analítica en el quintil central de G; la mediana de la valoración del nivel real 3) y el tiempo (la mezcla con su sorteo y las otras tres solo su evaluación; el sorteo del año va en una línea aparte).
  - **Falsa alarma conjunta.** Cada comprobación usa α = 0,01 con Bonferroni dentro de ella. Con las cuatro, un muestreador correcto da código 1 hasta un 4 % de las veces (desigualdad de Boole); la tabla y la ayuda lo dicen.
  - Cuatro gráficas (`profiles/report.py`), cada una con lo exacto y el IC al 95 % de lo observado (Wilson para las proporciones; estadísticos de orden para los cuantiles): `motivos.png` (los 17 motivos del año), `triaje.png` (P(asignado | real), un panel por nivel real), `pruebas_por_gravedad.png` (pedir cada tipo por quintil de G) y `duraciones_por_nivel.png` (mediana y p90 de la valoración y la reevaluación por nivel real). Se escriben siempre, también si algo falla.
  - Tiempos con los valores por defecto y `config/` (tarea 4.5b): 29 s en total; la mezcla, 11,1 s con su sorteo; la muestra del año, 14,3 s; la evaluación del triaje, las pruebas y las duraciones, 0,0, 0,2 y 0,2 s. Sortear el año para cada comprobación por separado costaría unos 14 s más.
- `calibracion evaluar` (tarea 4.6b) ejecuta las réplicas, compara cada objetivo con su horquilla e imprime una tabla con la media, su IC, la horquilla, el uso, el porcentaje de días fuera y el resultado, los censurados (aviso por encima del 0,1 %) y el desglose por nivel de los porcentajes (porcentaje del nivel y contribución a la cifra global). Opciones: `--centro`, `--llegadas`, `--perfiles` y `--objetivos` (los de `config/` por defecto), `--ventana` (tarea 4.6c: `anual`, por defecto, una réplica por mes desde el primer lunes; `inicio`, todas desde `fecha_inicio`, como en la 4.6b), `--replicas` (12 con la ventana anual, la única que admite: otro valor es código 2 antes de simular; 10 por defecto con `inicio`), `--dias` (14, con el calentamiento y sin el día de vaciado), `--calentamiento` (2), `--semilla` (2026, la de ajuste; 2027 para la comprobación, que puede vetar; 2028 para la confirmación después de un veto) y `--salida` (`resultados/calibracion`). Imprime además el valor de cada objetivo y los censurados por réplica (con la ventana anual, el perfil por mes) y la media por paciente de todas las réplicas, que no decide. Escribe `evaluacion.csv` (con `media_por_paciente`), `evaluacion_replicas.csv` (con la `fecha_inicio` de cada réplica) y `evaluacion_niveles.csv`, con los parámetros (y la `ventana`) y las huellas de los cuatro ficheros en cada fila. Código 1 si falla un objetivo de ajuste; los de comprobación se informan.
- `calibracion sensibilidad --mando {enfermeria_triaje,medicos}` (tarea 4.6b), con las mismas opciones y `--u-min` (0,55), `--u-max` (0,99) y `--paso` (0,0025): evalúa cada plantilla distinta de la regla con el otro mando como en el centro, imprime cada fila al acabarla (todos los objetivos, los censurados y, para los médicos, los días fuera de Manchester con el reloj C de los niveles 2 a 5 frente a los días medidos, sumados en las réplicas), la elección y, para los médicos, el cumplidor, y escribe `sensibilidad_<mando>.csv` (con `dias_fuera_c_nivel_k` y `dias_medidos_c_nivel_k`). Con `--comprobacion SEMILLA` (opcional, distinta de `--semilla`; revisión del PR #50), la elección se hace con `choose_staffing(…, check=…)`: evalúa con esa semilla, la misma ventana y el resto de opciones solo las candidatas que hagan falta, en el orden de la elección, e imprime cada una con su valor y su IC con la semilla de comprobación, vetada o elegida; el CSV no cambia de formato. Sin la opción, la línea de la elección añade «con la semilla de ajuste; la de comprobación puede vetarla (--comprobacion, decisión 41)». Código 1 si ninguna plantilla pasa los objetivos de ajuste del mando (con `--comprobacion`, con las dos semillas).
- Códigos de salida como en los hitos 2 y 3: 0 si todo va bien, 1 si alguna comprobación falla (escribiendo igualmente los ficheros) y 2 para errores de uso, sin crear ficheros a medias.
- Las opciones `--perfiles` y `--objetivos` usan por defecto los ficheros de `config/` en los subcomandos nuevos.

## Estructura del código

Un subpaquete nuevo para el modelo clínico y otro para la calibración; el motor solo cambia en los puntos de «El muestreador clínico en el motor».

```
config/
  perfiles.toml          población y perfiles clínicos
  objetivos.toml         objetivos de calibración con horquilla y fuente
  centro_cumplidor.toml  variante que cumple Manchester (tarea 4.6b)
docs/calibracion/
  registro.md            registro de calibración: parámetro, antes, después, KPI, motivo y tablas (tarea 4.6b)
src/edsim/profiles/
  __init__.py
  config.py              ClinicalProfiles, load_profiles (tomllib), validación
  context.py             franja, tipo de día y estación de una llegada
  mixing.py              categórica log-lineal, Gumbel-max, base_weights_for
  population.py          banda, edad, sexo y medio de llegada
  severity.py            gravedad latente, umbrales derivados, triaje con error
  derivation.py          cascada de derivados redondeados como se escriben; criterio de la gravedad de un motivo (tarea 4.6a)
  workup.py              pruebas por tipo, resultado y respuesta; WorkupModel exacto
  durations.py           lognormales por nivel real y motivo; DurationModel y carga del médico
  sampler.py             PersonReasonSampler, SeverityTriageSampler y WorkupDurationSampler
  validation.py          comprobaciones estadísticas del muestreador y validate_profiles
  report.py              tabla y gráficas de perfiles validar (tarea 4.5b)
  coupling.py            Gumbel-max frente a la CDF inversa: cambios exactos y simulados con números comunes (tarea 4.7)
src/edsim/calibration/
  __init__.py
  targets.py             objetivos.toml: Target, load_targets
  staffing.py            regla de la plantilla equivalente: cargas por turno, ⌈carga / u⌉, plantillas de la regla (tarea 4.6b)
  window.py              ventana de la calibración: anual (una réplica por mes, desde el primer lunes) o inicio (tarea 4.6c)
  evaluate.py            réplicas con día de vaciado y fecha de inicio, comparación con horquillas, días fuera, media por paciente, sensibilidad, elección con veto y cumplidor con días enteros
  report.py              tablas y CSV de calibracion evaluar y sensibilidad (tarea 4.6b)
  sas.py                 cifras del SAS que no son objetivos: reparto por nivel en adultos y TPAM por nivel (tarea 4.7)
src/edsim/engine/        cambios acotados
  clinical_sampler.py    ClinicalSampler, ClinicalDraws, ClinicalTruth y TurnaroundShifts (tarea 4.5a)
  clinical.py            PatientDraws con clinical y test_turnaround opcional; ProvisionalSampler
  patient.py             nivel 1 en la puerta, payloads clínicos, respuesta con la franja del pedido; sala de resultados (tarea 4.6a)
  events.py              catálogos 1, 2 y 3 (CATALOGS, SCHEMA_VERSIONS): circuito, medio, edad, sexo, motivo, pruebas, resultados; box_released (3)
  engine.py              simulate_ed(..., profiles=None)
  analysis.py            triage_start_to_doctor y classified_to_doctor; initial_box_wait y results_box_wait (tarea 4.6a)
  center.py              espera_resultados_fuera, opcional (tarea 4.6a)
  targets.py             cumplimiento con medida, pretriaje, nivel 1 sin porcentaje; cumplimiento por nivel real y clasificados tarde (tarea 4.7)
  invariants.py          capacidad sin triajes de puerta, nadie se cuela en el triaje; door, schema_version y clinical; la sala y results_wait (tarea 4.6a)
  ground_truth.py        EpisodeTruth.clinical (ClinicalTruth)
  validation.py          M/G/1 con λ·(1 − p₁)
src/edsim/lognormal.py   lognormal por mediana y p90 (tarea 4.4; engine/clinical.py la reexporta)
src/edsim/cli.py         --perfiles, perfiles validar, calibracion evaluar y sensibilidad (--ventana)
notebooks/04_perfiles_clinicos.ipynb
tests/test_profiles_config.py, test_context.py, test_mixing.py, test_population.py,
      test_severity.py, test_workup.py, test_durations.py, test_sampler.py,
      test_profiles_validation.py, test_calibration.py, test_calibration_targets.py,
      test_calibration_sensitivity.py, test_calibration_window.py, test_staffing.py, test_calibrated_center.py,
      test_cli_calibracion.py, test_door_triage.py,
      test_clinical_sampler.py, test_clinical_engine.py, clinical_factory.py,
      test_true_level_compliance.py, test_coupling.py, test_sas.py,
      test_target_mix_variant.py (tarea 4.7)
```

`ProvisionalSampler` sigue en `engine/clinical.py` para la validación del motor. Sin dependencias nuevas: `tomllib`, NumPy y SciPy cubren la Gumbel, la logística y la búsqueda de umbrales. Los nombres de módulos los confirma el plan de cada tarea.

## Tests y validación

La filosofía es la del hito 3, por capas: valores a mano, versiones incorrectas con predicción y pruebas estadísticas con su potencia.

| Grupo | Qué comprueba |
| --- | --- |
| Perfiles | Carga del TOML de ejemplo y del real; factores opcionales neutros; errores con claves desconocidas, longitudes, porcentajes y medianas inválidos |
| Contexto | Franja en los bordes (7:59 y 8:00), tipo de día en el paso de domingo a lunes, estación por mes |
| Mezcla | Valor a mano (22,8 % de disnea en mayores en invierno; 22,7 % hasta la tarea 4.6a); Gumbel-max con sorteos fijados a mano; reparto global de `base_weights_for` dentro de ±0,5 puntos; «con más disnea solo cambian los que pasan a disnea». Tarea 4.7: [2, 1, 1] → [3, 1, 1] a mano (mínimo 0,10, Gumbel-max 0,10 y CDF inversa 0,15 en el orden [A, B, C]); Gumbel = mínimo con un solo peso que crece y ≥ mínimo con cualquier cambio (pesos aleatorios); la simulación con números comunes dentro de su binomial; la gripe con `config/` (3,37 % y 15,55 %, a 1e-6) y simulada en el año; otra población es un error |
| Triaje | Umbrales a partir del reparto; reparto asignado y real; infra y sobretriaje; matriz real × asignado casilla a casilla; umbrales escritos = derivados y el shock con los escritos; la cascada entera (pesos, ruido y sesgo, umbrales) igual a lo escrito; la guarda de la parada (≥ 99 % de nivel real 1 y ≥ 97 % de asignado 1, con Φ a mano) y la media del criterio (4,21; con 4,20 no cumple); orden clínico de gravedad por motivo; nivel 1 en la puerta con un escenario a mano |
| Pruebas y duraciones | logit(0,40) = −0,4055 y 40,00 / 59,74 / 68,88 / 83,13 %; bordes u = P; máxima de las pedidas (75; 82,5 de tarde; `None` sin pruebas); media lognormal 24,43 → 29,32 con el factor 1,2; lo exacto contra `quad`; marginales por motivo y regla de los k sobre `config/perfiles.toml`; `check_workup` y `check_durations` |
| Muestreador | Consumo fijo por flujo; el paciente k es el mismo con otra plantilla y conserva sus z con otro parámetro clínico; llegadas idénticas a `iter_arrivals` |
| Motor | Asignación de flujos con sorteos a mano; consumo fijo con generadores instrumentados; el motor como tubería del `ClinicalSampler`; respuesta con la franja del pedido (75 / 82,5 / 67,5; 84 de noche; 260 a las 7:59; pedido a las 15:10 de una llegada a las 14:00); destino con el nivel asignado; payloads del catálogo 2 en un escenario a mano, sin campos ocultos; invariantes `door`, `schema_version` y `clinical`, y cero violaciones en 14 días; huellas del modelo provisional (sin cambios) y del clínico (log y ground truth) |
| Relojes | Las tres medidas en un log a mano; cumplimiento con C; pretriaje; nivel 1 sin porcentaje; cumplimiento por nivel real (tarea 4.7): un infratriado que cumple con su nivel asignado y no con el real y un sobretriado al revés, a mano; bien clasificados = `manchester_compliance` campo a campo; errores sin verdad clínica o con un episodio que falta; esperas emparejadas por id con la tabla desordenada; en 3 días, el `n` por nivel es el de los niveles reales. Clasificados tarde en el borde (10 min no, 10,5 sí; el nivel 1 en la puerta, 0) |
| Calibración (tarea 4.6b) | `objetivos.toml` real y sus errores con la clave completa; cargas con `config/` (a 1e-3), regla a mano (`u` = 0,60 → `[3, 3, 2]`; 0,80 → `[12, 12, 5]` en médicos…) y las listas de plantillas distintas; IC a mano (10, 12, 14: media dentro de \[6, 15\] e IC de 9,94, no pasa; t₉ = 2,262); días fuera (5, 8, 16, 10 → 50 %); media diaria por paciente; ventana sin calentamiento; umbral de Manchester en el borde; desglose por nivel; pureza de la evaluación; vaciado a mano (una llegada en el minuto 1430 que sale después de la ventana) y su espía; el pretriaje igual con otros médicos (igualdad exacta) y distinto con otra enfermería; semillas de ajuste y de comprobación distintas; sensibilidad corta con un espía de la plantilla de cada candidato; elección y cumplidor a mano (el centro de la horquilla sin referencia); CLI con códigos 0, 1 y 2 sin ficheros; centros calibrado y cumplidor desde la regla con sus u. Slow: la fila corta del registro |
| Calibración con la ventana anual (tarea 4.6c) | Primeros lunes de 2026 y 2027 a mano; `window_replicas` y `window_start_dates` (la anual solo con 12; `inicio`, 10 y sin fechas); espía de `simulate_ed`: la réplica m con el hijo m (`spawn_key == (m,)`) y la fecha m, y sin fechas el perfil tal cual; la réplica de enero = la réplica 0 sin fechas, y las de julio y diciembre = una simulación directa con un `llegadas.toml` con su `fecha_inicio` (igualdad exacta, `nan` incluidos); otra fecha conserva los factores bit a bit; fechas con otra longitud o con hora, error; media por paciente a mano (17,5 frente a 15 de media de réplicas; 40 %) y, con una sola réplica, igual a su valor en los cinco objetivos; cumplidor con días enteros: borde de 120 días (12 fuera pasa, 13 no), días sumados frente a media de proporciones (12 de 120 pasa con una media de 1/6) y días medidos obligatorios, y los días enteros = `manchester_compliance`; veto a mano (\[2, 2, 1\] vetada y \[3, 2, 1\] elegida; sin veto la comprobación no cambia nada y se pide solo hasta que una pasa; ninguna con las dos, `None`; los médicos miran solo sus objetivos de ajuste; la comprobación de otra plantilla, error); tres semillas distintas; CLI con `--ventana` (anual con otro `--replicas`, código 2 sin ficheros; CSV con 12 fechas y `ventana`; `inicio` como antes). Slow: enero = réplica 0 de la 4.6b con `tests/data/centro_4_6b.toml`; la fila del centro de `config/` con 2026 (8 censurados de enero); el veto de 2027; la confirmación con 2028; el cumplidor y su siguiente con días enteros; la fila corta anual |
| CLI | Subcomandos nuevos, ficheros y código 2 ante errores de uso. `motor simular --perfiles`: caracterización con los argumentos de la del provisional (log igual al de `simulate_ed` y CSV de días con la huella del provisional), la CLI y `simulate_run` dan el mismo log, y código 2 con perfiles que no existen o no son válidos. `perfiles validar`: tabla y gráficas con un contexto (rápido), código 1 con el sesgo del triaje desplazado en el muestreador (`sampled_profiles`), código 2 sin ficheros y los valores por defecto con `config/` (slow) |
| Sala de resultados (tarea 4.6a) | Escenario a mano (un box, tres niveles 4): el motor lo escribe evento a evento, A ocupa el box 20 + 10 minutos, vuelve por delante de C con su clave, y esperas, curvas, Little y utilización exactas; quién deja el box (nivel 3, infratriado, sobretriado, nivel 4 sin pruebas); el provisional con `[4, 5]`, igual y con su huella; números comunes con y sin sala y con otra plantilla; una copia de `centro.toml` sin la clave da el log de antes; la clave y sus errores; catálogo 3 literal y lectura de las versiones 1, 2 y 3; violaciones a mano de las invariantes nuevas; Replay y Episodios sin dos pacientes en un box; 14 días con `config/`: cero violaciones, utilización exacta y la cola de box contada por dos caminos |
| Variante y SAS (tarea 4.7) | El SAS en adultos a mano (1,15 / 7,32 / 34,44 / 38,86 / 18,22 % y 2.574.941 adultos) y con niños; la variante con umbrales = `thresholds_for`, reparto asignado exacto = objetivo (a 1e-10), ruido y sesgo sin cambios, los ficheros de `config/` iguales byte a byte y en su hora; la densidad de G a mano, su integral y su media; `lognormal_pdf` frente a SciPy; `evaluate_staffings` con un espía de la plantilla de cada candidato |
| Ejecuciones (tarea 4.5b) | Ida y vuelta del CSV clínico con `==` y tipos exactos; cabecera literal y fila a mano; `run.json` v1 de `tests/data` y v2 con los dos modelos; `simulate_run` pasa los perfiles a `check_invariants` (espía y comportamiento); `pairing_blockers` con los dos modelos |

**Potencia.** El muestreador se prueba sin el motor, con 25 000 pacientes por contexto en la mezcla (20 000 hasta la tarea 4.6a) en décimas de segundo. Con el χ² por motivo, nivel 0,01 y Bonferroni entre 17, se detecta un 5 % que pasa a 6 % con una potencia del 99,98 % (99,7 % con 20 000), pero un 5 % que pasa a 5,5 % solo con un 57 % (43 %). En la tabla de `perfiles validar`, con Bonferroni entre las 2.136 categorías de los 24 contextos, un motivo del 5 % se ve si pasa a 5,76 % (5,85 % con 20 000). Cada prueba escribe qué tamaño de error ve. Los motivos raros (crítico, 0,3 % desde la tarea 4.6a) necesitan comprobar que hay pacientes suficientes, para que el test no pase de forma vacía.

**Validación de pruebas y duraciones** (tarea 4.4). `check_workup` y `check_durations` sortean los pacientes de un año como `check_triage`, ahora también con los flujos 3 y 2, y comparan con lo exacto (`WorkupModel` y `DurationModel`, con el integrador de Gauss-Legendre de `triage_matrix`): χ² de un grado de libertad o binomial exacta por debajo de 5 esperados, con Bonferroni.

| Comprobación | Categorías |
| --- | --- |
| `check_workup` (134, nivel 0,01/134) | Pedir × quintil de G (20); alterado × quintil, sobre todos los pacientes porque el resultado se sortea siempre (20); pedir \| infratriado (4); pedir × motivo (68); pedir × nivel real (20); mediana y p90 de la ronda (2) |
| `check_durations` (64, nivel 0,01/64) | Mediana y p90 del triaje (2), de la respuesta base de cada tipo (8) y de la valoración y la reevaluación por nivel real (20); mediana de las dos por motivo (34), que prueba los k |

Un año (109 542 pacientes, unos 14 s cada una) por defecto; 20 000 (2,5 s) en los tests rápidos. Cada grupo condicionado debe esperar al menos 50 pacientes, con los esperados exactos: desde la tarea 4.6a manda la parada (0,302 %), que necesita 16 545; antes, el nivel real 1 (0,42 %), con 12 000. Con una potencia del 80 %, pedir analítica en el quintil central (44,9 %) se ve si pasa a 48,7 % con 20 000 y a 46,5 % en un año; los infratriados (59,5 %), a 64,7 % y 61,7 %; la mediana de la valoración del nivel 3, a 52,7 % y 51,2 % (antes de la 4.6a: 45,0 → 48,8 y 46,6 %; 59,8 → 65,0 y 62,0 %). Un error que comparten el muestreador y lo exacto (qué bandas son «mayores», cómo actúa k) mueve también la hipótesis: solo lo ven los valores a mano y los literales.

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
| `simulate_run` sin `profiles` en `check_invariants` | Fallan el espía y el test de comportamiento (con la ronda alargada 1 minuto, `run.json` guarda 0 violaciones); fallan también los dos espías que fijan los argumentos exactos (tarea 4.5b, cumplida) |
| CSV clínico con la respuesta base multiplicada por el factor de la franja de la llegada | Fallan la ida y vuelta de 3 días, la fila a mano (de tarde), la huella del CSV clínico de la CLI y la lectura frente a `simulate_ed`; pasan la cabecera literal, los tipos exactos, el log y las huellas del provisional (tarea 4.5b, cumplida) |
| `run.json` de una ejecución clínica con `format_version` 1 | `RunInfo` la rechaza: no se publica ninguna ejecución clínica y fallan todos los tests que crean una; pasan los provisionales y la lectura de la versión 1 (tarea 4.5b, cumplida) |
| Perfiles cargados del original y no de la copia | Falla solo «el original modificado tras copiarlo no cambia el log» (tarea 4.5b, cumplida) |
| CSV provisional con las columnas de los perfiles | Fallan la huella de la caracterización provisional, las cabeceras y todos los lectores de cabecera exacta (`runs/truth.py`, `read_episodes_csv` y la comparación de ejecuciones); pasa todo lo clínico (tarea 4.5b, cumplida) |
| `pairing_blockers` sin mirar el modelo | Falla solo la tupla exacta del provisional frente al clínico: el bloqueo sigue por la huella de los perfiles (tarea 4.5b, cumplida) |
| `validate_profiles` sortea el año en cada comprobación | Falla solo el espía del sorteo: con la misma semilla salen los mismos pacientes y la igualdad con los `check_*` no lo ve (tarea 4.5b, cumplida) |
| Mínimo de la mezcla sin margen (lo esperado exacto) | Fallan las cifras de los mínimos y el código 2 entre los dos mínimos; contra la predicción, fallan también los tests rápidos, que toman N de `mixing_minimum`: en el mínimo exacto, la mezcla para por falta de pacientes (4,91 esperados < 5), que es lo que el margen evita (tarea 4.5b) |
| Umbrales rederivados con el ruido y el sesgo de antes de la tarea 4.6a (0,333 y −0,081) | Fallan «ruido y sesgo escritos = calibrados» (0,00136 > 1e-3) y el literal del ejemplo; pasan los umbrales (redondeados, iguales), infra y sobre, la guarda de la parada y las huellas clínicas. Fallaron además la guarda (fija el ruido escrito antes de su cálculo a mano), el shock, la cascada y las tres huellas clínicas: en 3 días se esperaban 0,53 cambios de nivel (no 0,3) y el CSV clínico de la CLI lleva la huella de `perfiles.toml`, que cambia con cualquier edición (tarea 4.6a) |
| La parada al 0,3 % sin rederivar los pesos base | Fallan pesos, umbrales y ruido escritos = derivados, el reparto asignado con los umbrales escritos, los mínimos y las huellas clínicas; pasan el reparto global a ±0,5 puntos (0,20), la mezcla de G a ±0,05 y la guarda de la parada. Cumplida, con fallos de más explicados (marginales, k, shock, errores detectables) (tarea 4.6a) |
| La parada con media 4,20 y su cascada coherente | Fallan la guarda (96,91 % < 97 %) y el literal del criterio; pasan los «escritos = derivados». Cumplida, más los literales que dependen de c₁ (3,340) y las marginales de la parada (tarea 4.6a) |
| La sala decidida con el nivel real | Fallan el infratriado y el sobretriado a mano, `results_wait` en 14 días y la huella del log con sala; pasan el escenario principal y las huellas de la 4.5a. Exacta (tarea 4.6a) |
| La vuelta al box con una clave nueva (la hora de vuelta) | Fallan el escenario a mano y «nadie se cuela», en su log y en 14 días (1.735 violaciones): la invariante reconstruye la clave del log (nivel, llegada), no la del motor. El chat predijo que pasaban las invariantes; se cumplió la predicción del plan (tarea 4.6a) |
| La sala también con el provisional | `box_released` no está en el catálogo 1: `ValueError` en las guardas del provisional con `[4, 5]` y en todo test provisional con `config/centro.toml`; pasan las cuatro huellas del provisional y la M/G/1. Cumplida (tarea 4.6a) |
| Soltar el box antes de emitir el `test_ordered` | Fallan `transitions` (`box_released` en `assessed`) en el escenario y en 14 días y la huella del log con sala; pasan las huellas de la 4.5a. Exacta (tarea 4.6a) |
| La capacidad cuenta a los de la sala | Falla `capacity` en el escenario y en 14 días; pasan las huellas. Cumplida, más los tests de violaciones a mano que fijan la lista entera sobre el mismo escenario (tarea 4.6a) |
| `step_curves` sin `box_released` en los boxes ocupados | Fallan las curvas a mano y la identidad de utilización de los boxes (escenario y 14 días); pasan las invariantes y las huellas. Exacta (tarea 4.6a) |
| La cola de box sin la vuelta de la sala | Fallan la curva a mano, Little en el escenario y la cola de box por dos caminos en 14 días; pasan las invariantes. Exacta (tarea 4.6a) |
| Replay sin `box_released` (el de la sala conserva su box) | Fallan «nunca dos pacientes en el mismo box» y los estados de A; pasan motor, invariantes y análisis. Exacta (tarea 4.6a, añadida) |
| `round` en lugar de `ceil` en la regla | Fallan los 7 casos a mano y las dos listas de plantillas; pasan cargas, evaluación y `objetivos.toml`. El caso u = 0,85 de enfermería pasó (`round` también da `[2, 2, 1]`) y falló el test de redondear hacia arriba; los tres casos de los centros calibrado y cumplidor desde la regla, exacta (tarea 4.6b) |
| Un objetivo pasa solo con la media, sin el IC | Falla solo el IC a mano de tres réplicas. Exacta (tarea 4.6b) |
| IC con z = 1,96 en lugar de la t de Student | Fallan el IC a mano y el de t₉. Exacta (tarea 4.6b) |
| La misma semilla para ajuste y comprobación | Fallan los literales de las semillas y «otras llegadas». Exacta (tarea 4.6b) |
| El candidato se evalúa con la plantilla del centro | Fallan el espía de la sensibilidad y «otro pretriaje con cada plantilla». Exacta (tarea 4.6b) |
| Media diaria como media de las medias por nivel | Falla la media diaria con recuentos desiguales. Exacta (tarea 4.6b) |
| La ventana incluye el calentamiento | Falla la ventana a mano. Exacta (tarea 4.6b) |
| `>=` en el umbral de un porcentaje | Falla el borde de Manchester; falló también el borde en minutos (tarea 4.6b) |
| Carga de enfermería sin (1 − p₁) | Fallan las cargas de enfermería y la lista de enfermería, por los cuatro bordes de u que se mueven; pasan los casos a mano. Exacta (tarea 4.6b) |
| La elección entre todas las plantillas, no solo las que pasan | Falla la elección a mano; fallaron también «ninguna pasa» y el código 1 de la CLI. Tras pasar el nivel 3 a comprobación, la elección de médicos a mano no la veía y se reforzó con una plantilla que no pasa más cerca del centro de la horquilla (tarea 4.6b) |
| El cumplidor con el reloj A | Falla el cumplimiento a mano con A ≠ C. Exacta (tarea 4.6b) |
| La CLI crea `--salida` antes de validar | Fallan los tests de código 2 sin ficheros (15). Exacta (tarea 4.6b) |
| Sin día de vaciado | Fallan el vaciado a mano, el espía del horizonte y la fila corta del registro (slow). Exacta (tarea 4.6b) |
| El cumplimiento por nivel real con el nivel asignado | Fallan los casos a mano del infratriado y del sobretriado y la ejecución de 3 días; pasan «bien clasificados = asignado» y los tests de `manchester_compliance`. Cumplida, con un fallo de más: sin buscar el nivel real, nadie detecta el episodio que falta en el ground truth (tarea 4.7) |
| Gumbel-max con sorteos distintos antes y después del cambio de pesos | Fallan las simulaciones del contexto (cambia el 60 % frente al 10 %) y del año; pasan las fórmulas exactas y la CDF inversa simulada. Cumplida, más los dos «sin cambio de pesos nadie cambia» simulados: con sorteos independientes cambian pacientes aunque los pesos no cambien (tarea 4.7) |
| La variante con los umbrales de antes | Fallan «umbrales = `thresholds_for`» y «reparto asignado exacto = objetivo»; pasan «no toca los ficheros» y «ruido y sesgo sin cambios». En la primera pasada falló también este último, que comprobaba además que los umbrales cambian; esa aserción pasó a su test y la segunda pasada fue exacta (tarea 4.7) |
| La fórmula de Gumbel-max con `min` en lugar de `max` | Fallan el 0,10 a mano, «Gumbel = mínimo con un peso que crece», el literal de la gripe y la simulación del año; pasan la CDF inversa y la simulación del contexto, que se compara con los valores a mano. Cumplida, más los cuatro tests que usan la fórmula con un cambio de pesos (escala, peso cero, «ningún método por debajo del mínimo» y por ejes) (tarea 4.7) |
| Clasificados tarde con `>=` | Fallan el borde de 10 minutos y el nivel 1 en la puerta (todos «tarde»); pasa el de 10,5. Exacta (tarea 4.7) |
| El SAS en adultos restando los puntos de los menores al reparto con niños | Fallan los cinco porcentajes y el total de adultos; pasa el reparto con niños. Cumplida, más los cinco tests de la variante, que toman su objetivo del SAS: restado y recortado a 0 no es un reparto válido (tarea 4.7) |
| La densidad de la mezcla de G sin los pesos | Fallan la mezcla a mano y la media; pasa «integra 1», que por sí solo no la ve (una media simple de densidades también integra 1). Exacta tras separar «integra 1» y «da la media», que estaban en un solo test (tarea 4.7) |
| Las esperas con los dos niveles emparejadas por posición | Falla la tabla desordenada; pasa la ejecución de 3 días, porque la tabla y el ground truth van en el mismo orden. Cumplida, más el episodio que falta, por la misma causa que la primera de esta tarea (tarea 4.7) |
| La réplica m empieza el día 1 del mes, no el primer lunes (V1, tarea 4.6c) | Fallan las fechas a mano, «enero = réplica 0 de la 4.6b» y la réplica directa de julio; pasan los tests de la CLI que no miran fechas y el cumplidor. Cumplida, con fallos de más: el espía, la de diciembre, enero = réplica 0 sin fechas (el ejemplo empieza el 5 de enero) y el CSV anual de la CLI, que mira las fechas. En la primera pasada pasaron julio y diciembre, porque la fixture escribía los lunes a mano: se cambió para tomar las fechas de `window_start_dates` |
| Todas las réplicas con el hijo 0 (V2, tarea 4.6c) | Fallan las réplicas directas de julio y diciembre; pasan las fechas y «enero = réplica 0». Cumplida, más el espía |
| La réplica m con el hijo 11 − m (V3, tarea 4.6c) | Fallan «enero = réplica 0» y las réplicas directas; pasan las fechas. Cumplida, más el espía |
| 12 réplicas anuales todas desde `fecha_inicio` (V4, tarea 4.6c) | Fallan las réplicas directas de julio y diciembre y «12 fechas distintas» en el CSV; pasan «enero = réplica 0» y las fechas a mano. Cumplida, con fallos de más: las funciones de la ventana, el espía de la CLI y el «enero = réplica 0» rápido, por su guarda de que febrero no es enero; pasaron el slow y los lunes a mano |
| El cumplidor con la media de los porcentajes por réplica (V5, tarea 4.6c) | Falla solo el reparto cuya media pasa de 0,10; pasa el borde con 13 fuera. Exacta |
| Elegir sin mirar la comprobación (V6, tarea 4.6c) | Fallan los tests del veto y pasan los de la elección de siempre. Exacta: fallan los cinco del veto (también «sin veto, la comprobación no cambia nada», porque no se pide) y pasan los cuatro de la elección |

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
9. La calibración: norma frente a observación, horquillas, la ventana anual, sensibilidad de la plantilla, el veto de la semilla de comprobación, enero cerca de la saturación y objetivos de comprobación.
10. El coste del infratriaje: cumplimiento por nivel asignado frente a nivel real.
11. Centro realista frente a centro cumplidor, con los mismos pacientes.
12. Para experimentar: un perfil con muchos niveles 5 (el reparto del SAS), otro ruido de triaje, otra plantilla.
13. Resumen: las lecciones del hito en pocas frases.

**Lo que quedó** (tarea 4.7). El notebook usa `config/centro.toml` (calibrado) y `config/centro_cumplidor.toml`; el notebook 03 sigue con la plantilla del hito 3. Las cifras que cita el texto son las de la ejecución normal y lo dice, como el 03.

| # | Qué hace | Del paquete |
| --- | --- | --- |
| 2 | Un paciente infratriado de 3 días: su verdad clínica y lo que el log dice de él; el nivel asignado por banda de edad | `simulate_ed(..., profiles=)`, `ClinicalTruth` |
| 3 | Los 17 motivos en cuatro situaciones (edad, franja, día y estación) y el peso base frente al reparto del año y el catálogo | `reason_probabilities`, `global_reason_shares`, `catalog_shares` |
| 4 | La gripe (disnea ×1,5) exacta y simulada con números aleatorios comunes, en un año y en un contexto | `reason_shock_changes`, `simulate_reason_shock`, `simulate_changes` (`profiles/coupling.py`) |
| 5 | La densidad de G y de G + ε con los umbrales, la matriz P(asignado \| real), y el infra y sobretriaje al mover el ruido o el sesgo con los umbrales escritos | `SeverityMixture.pdf`, `triage_matrix`, `triage_error_rates`, `assigned_shares` |
| 6 | Los niveles 1 reales de la ejecución principal, a la puerta o asignados como 2, con su pretriaje y su reloj A | `true_level_waits` |
| 7 | Las logísticas de las cuatro pruebas de un motivo (adulto y mayor) y la valoración por nivel real y por k | `order_probability`, `workup_model`, `duration_params`, `lognormal_pdf` |
| 8 | El mismo día con A, B y C, los días fuera de cada reloj y los niveles 2 ya fuera al clasificarse | `manchester_compliance`, `classified_late`, `clock_quantiles` |
| 9 | Con la ventana anual (12 réplicas de 14 días, una por mes), la plantilla del centro y sus dos vecinas de la regla en cada mando; el veto con la semilla 2027 (\[2, 2, 1\] descartada, \[3, 2, 1\] elegida); el reloj A por mes de las tres plantillas de médicos; el TPAM del SAS por nivel frente al reloj A del modelo (tarea 4.6c) | `rule_staffings`, `evaluate_staffings`, `choose_staffing(…, check=…)`, `window_start_dates`, `calibration/sas.py` |
| 10 | El cumplimiento por nivel asignado frente al real, y los niveles 2 reales según su nivel asignado | `true_level_compliance`, `true_level_waits` |
| 11 | El calibrado frente al cumplidor con los mismos pacientes | `paired_waits`, `manchester_compliance` |
| 12 | Tres variantes: el reparto del SAS en adultos (umbrales rederivados en memoria; el ruido y el sesgo no cambian), el ruido ×1,5 con los umbrales escritos y los médicos del centro con uno más de mañana y de tarde (\[13, 12, 4\]) | `with_target_mix`, `replica_values`, `true_level_compliance` |

- **Parámetros.** La ejecución principal dura 91 días (enero a abril), con 2 de calentamiento y el día de vaciado de la calibración, y se reduce a su tabla y su ground truth nada más simularla; la usan las secciones 6, 8, 9, 10 y 11, y el cumplidor tiene la suya, con la misma semilla. Calibración con la ventana anual: 12 réplicas de 14 días, 3 plantillas por mando y la comprobación con 2027 hasta que una pasa (nueve evaluaciones). La gripe, con los pacientes de un año; los experimentos, 28 días. En modo rápido: 5 días; 2 réplicas de 3 días (enero y julio) y 2 plantillas por mando; 5.000 pacientes y 5 días.
- **Tiempos y memoria** (medidos en la tarea 4.6c): modo normal, 6 min 15 s y 603 MB de pico del kernel; modo rápido, 13 s y 271 MB (en la 4.7: 3 min 52 s y 621 MB; 26 s).
- **La calibración del notebook no sustituye al registro**: evalúa solo las plantillas del centro y sus vecinas, con la misma ventana y las mismas semillas que el registro, y llega a la misma elección: la regla elige \[2, 2, 1\] (13,20), la semilla 2027 la veta (15,16) y queda \[3, 2, 1\]; en los médicos solo pasa \[12, 11, 4\] (42,10). Las filas de médicos son las del registro; las de enfermería difieren solo por los censurados.
- **El TPAM del SAS frente al modelo** se compara por la forma, no por la cifra: el del SAS incluye menores y va por nivel asignado. En el SAS los niveles 3 a 5 esperan parecido (59,0 / 59,8 / 68,5 min); en el modelo, el 3 espera poco (29,2) y el 5 muchísimo más: 627 min en la ejecución principal (enero a abril), dos tercios de una sola semana, la del 19 al 25 de enero (3897 min de media; sin ella, 224). Con 4 médicos de noche (tarea 4.6c) esa semana llega a 129 pacientes clasificados esperando médico a las 8:00 y la cola no se vacía hasta el 30 de enero: es el enero de una plantilla anual (ver «Enero con una plantilla anual»; con \[12, 11, 5\], 229 y 985 min). Esos 3897 min (unas 65 horas) del nivel 5 no son realistas: el modelo aún no tiene abandono sin ser visto (`patient_left_wbs`, hito 5), y en un hospital real buena parte de esos pacientes se iría. Lo acotan el abandono del hito 5 y el refuerzo de invierno.
- **Hallazgo de la sección 12.** Con el reparto del SAS en adultos, el reloj A de los niveles 2 a 5 baja de 141,7 a 74,9 minutos con los mismos pacientes (de 73,5 a 47,3 con los médicos de la 4.6b): hay menos niveles 2 asignados, que retienen el box mientras esperan sus pruebas, y más 4 y 5, que lo dejan (decisión 45). El nivel asignado decide quién libera el box.

**Variante de perfiles con otro reparto objetivo** (tarea 4.7). `with_target_mix(perfiles, llegadas, reparto)` (`profiles/derivation.py`) cambia `reparto_objetivo` y rederiva los umbrales en memoria con `thresholds_for`, sin redondear, de modo que el reparto asignado exacto del año es el nuevo objetivo. El ruido y el sesgo se quedan como están, así que el infratriaje y el sobretriaje cambian (con el SAS en adultos, 14,4 % y 8,0 %). Nunca escribe en `config/`. No contradice la decisión 38: los umbrales escritos no se recalculan al cargar; una variante con otro reparto es otro perfil.

**El reparto del SAS en adultos** (`calibration/sas.py`). Del CMBD 2013 (página 30): los recuentos por nivel (30.457 / 208.635 / 989.622 / 1.312.906 / 731.808) y los menores de cada nivel (2,65 / 9,60 / 10,38 / 23,78 / 35,90 %). Quitando los menores nivel a nivel quedan 2.574.941 adultos y el reparto 1,15 / 7,32 / 34,44 / 38,86 / 18,22 %; con niños, 0,93 / 6,37 / 30,23 / 40,11 / 22,36 %. El módulo guarda también el TPAM por nivel (31,7 / 35,6 / 59,0 / 59,8 / 68,5 min; 59,7 en total).

## Decisiones del hito

Trece decisiones candidatas: de la 34 a la 44, acordadas en la sesión conceptual del 5 de noviembre de 2026, y la 45 y la 46, en la del 6 de noviembre, tras las comprobaciones clínicas de la tarea 4.5a. Si se confirman durante el hito, la tarea de cierre las convierte en los ADR 0034 a 0046 y las añade al registro del diseño. La decisión APP-0003, que solo afecta a la app, está en «App web — incrementos».

| # | Decisión | Motivo |
| --- | --- | --- |
| 34 | El hito 4 cubre población, motivo, gravedad, triaje con error, pruebas, duraciones, relojes y una primera calibración; el destino provisional no cambia, y abandono, destino, boarding y bucles de saturación van al hito 5 | Sin destino, boarding ni abandono, el ingreso, la estancia y la cola en días punta saldrían mal por construcción; los bucles necesitan el estado del servicio en el paciente |
| 35 | Solo adultos de 15 años o más, con cuatro bandas de edad (15–44, 45–64, 65–79, 80–99) y edad uniforme dentro de la banda | Los objetivos de triaje son de adultos; la pediatría pide su propio catálogo (v3) |
| 36 | `config/perfiles.toml` aparte de `centro.toml`, una tabla por motivo, unidades clínicas, factores opcionales neutros, claves desconocidas prohibidas y franjas propias | Hospital y población son preguntas distintas; perfiles intercambiables en la v3; nada derivado a mano |
| 37 | Los 17 motivos desde el principio, cada parámetro con su estado (calibrado, derivado u orientativo) y pesos base derivados del reparto del catálogo con `base_weights_for` | No hay fuente pública por motivo; el estado dice qué respaldo tiene cada número; los shocks no se renormalizan |
| 38 | Gravedad latente normal y triaje ordinal G + ε con ruido y sesgo; umbrales derivados una vez para el reparto asignado y escritos en el TOML, sin recalcularse al cargar; la prioridad usa el nivel asignado, y duraciones y pruebas, la gravedad real | Modelo del diseño; reproduce el infra y sobretriaje publicados; hace medible el daño del infratriaje; un escenario con más gravedad da más niveles urgentes |
| 39 | El nivel 1 asignado se clasifica en la puerta (triaje de duración 0, `circuito: "puerta"`, sin enfermera) y va directo al box; sin desalojo de médicos | El crítico no hace cola de triaje sin cambiar el orden de los eventos; el desalojo de médicos ahorraría un minuto a un paciente al día con una regla clínica sin datos (v1) |
| 40 | Tres relojes con nombre propio; cumplimiento Manchester desde la clasificación (C); pretriaje con indicador propio; nivel 1 sin porcentaje; cumplimiento por nivel real solo con ground truth | Antes del triaje no hay nivel; separa la cola de triaje de la de médicos; con el reloj A el nivel 2 no podía cumplir |
| 41 | Centro base realista, calibrado a horquillas observadas en `config/objetivos.toml`, con objetivos de ajuste y de comprobación; dos mandos indirectos con objetivos separados, la enfermería de triaje (pretriaje) y los médicos (tiempo hasta el médico), ajustados en ese orden; los boxes quedan fijos (30), y la sensibilidad de los mandos se mide antes de ajustar. Desde la tarea 4.6c, cada candidato se mide con la ventana anual (una réplica por mes) y la semilla de comprobación puede vetar la elección, no hacerla; después de un veto se confirma con 2028 | Un laboratorio que nunca incumple no sirve; plantilla y duraciones no son identificables sin la estancia, y plantilla y boxes tampoco con objetivos de tiempo hasta el médico; los médicos no mueven el pretriaje (1,4 minutos con la enfermería de antes); los objetivos del SAS son medias anuales, y una plantilla elegida con una semilla que falla con otra está en el borde por azar |
| 42 | Pruebas de cuatro tipos en una ronda, con un solo `test_ordered` (lista de pruebas) y un solo `test_resulted` (resultados) | Mismo comportamiento del paciente sin cambiar el contrato del log; un evento por tipo queda para versiones posteriores |
| 43 | Sorteos sincronizados: Gumbel-max para las categorías y z estándar transformadas para las variables continuas, con consumo fijo y un flujo por fuente (`child_streams(seed, 8)`) | Números aleatorios comunes también para escenarios clínicos: con la gripe cambia el 3,37 % de los pacientes, el mínimo posible, y no el 15,55 % |
| 44 | Modelo clínico opcional durante el hito (`profiles=None` usa el provisional) y por defecto en el cierre, cuando la app ya lo soporta; el `ProvisionalSampler` se queda para la validación del motor | `main` estable y `tests-app` obligatorio en todo el hito; la app no se rompe a mitad de camino |
| 45 | Con el modelo clínico, los pacientes de los niveles asignados de `espera_resultados_fuera` (`centro.toml`, `[4, 5]`) dejan el box al pedir las pruebas, esperan los resultados en una sala sin límite de capacidad y vuelven a pedir box con su misma clave de prioridad para la reevaluación; un evento nuevo en el catálogo versión 3. El provisional no cambia | El 64 % del tiempo de box era espera de resultados y saturaba los 30 boxes; en las urgencias reales los leves esperan fuera; la plantilla de médicos no puede calibrar una cola de boxes |
| 46 | La parada / crítico pasa al 0,3 % del catálogo con una gravedad alta y poco dispersa, para que casi todas sean nivel 1 real y asignado; pesos base, ruido y sesgo, umbrales y marginales de pruebas se rederivan y se escriben | Con el 0,54 % y la gravedad en el umbral, el 44 % de las paradas recibía nivel 2 y esperaba en la cola del triaje: el nivel 1 asignado del 0,4 % no dejaba sitio para todas |

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
| 4.6a | Paradas al 0,3 % con gravedad alta (46) y rederivación; espera de resultados fuera del box en los niveles 4 y 5 con el catálogo versión 3 (45). `@codex review` | Claude Code | `feat/h4-paradas-sala` | Paradas a la puerta, boxes sin la ronda de los niveles 4 y 5 y el provisional bit a bit igual |
| 4.6b | `objetivos.toml`, sensibilidad de los mandos, `calibracion evaluar` y `calibracion sensibilidad`, primera calibración de la enfermería de triaje y de los médicos (41) y registro; `centro_cumplidor.toml` | Claude Code | `feat/h4-calibracion` | Objetivos de ajuste dentro de horquilla y registro de calibración |
| 4.7 | Notebook `04_perfiles_clinicos.ipynb` | Claude Code | `feat/h4-notebook` | Notebook ejecutable de principio a fin en el CI |
| 4.6c | Recalibración con la ventana anual: una réplica por mes, de modo que la media sea la del año, como los objetivos del SAS (41); el cumplidor decidido con enteros; registro, especificación y cifras del notebook 04 con la plantilla nueva. Va después de la 4.7, que destapó que la ventana de la 4.6b era la primera quincena de enero | Claude Code | `feat/h4-recalibracion-anual` | Objetivos de ajuste dentro de horquilla con la media del año y el registro con las dos calibraciones |
| 4.8a | Núcleo de la app con perfiles (`runs/`); `run.json` versión 2 se adelanta a la 4.5b | Claude Code | `feat/h4-app-nucleo` | Ver «App web — incrementos» |
| 4.8b | Páginas de la app con perfiles | Codex | `feat/app-h4-paginas` | Ver «App web — incrementos»; etiqueta `app-v0.2.0` |
| 4.9 | Cierre: modelo clínico por defecto y separación de `centro.toml` (36, 44); ADR 0034 a 0046; diario; anexo; exportación de pestañas; ajustes de la pestaña de diseño; etiqueta `v0.4-hito4` | Claude Code | `docs/h4-cierre` | Hito cerrado |

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

Solo una rama abierta a la vez. La revisión automática con `@codex review` se pide solo en las tareas críticas: en este hito, la 4.5a (el muestreador en el motor), la 4.6a (paradas y espera de resultados fuera del box, en el motor) y la 4.9 (el cambio de modelo por defecto).

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
- Pedro sabe explicar cómo se mezcla un motivo con su contexto, por qué el nivel asignado no es el real y qué consecuencias tiene, por qué el cumplimiento se mide desde la clasificación, y por qué se calibra a lo observado con dos mandos de objetivos separados.
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
| Circuitos separados para los niveles 4 y 5 (consultas o vía rápida) | Cambia el reparto de médicos y boxes; con prioridad estricta en un solo grupo de médicos, el nivel 3 casi no espera y no se puede calibrar su reloj A (tarea 4.6b) | Por decidir: es lo que permitiría calibrar el nivel 3 |

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

### Tarea 4.5a: el ClinicalSampler en el motor

**Qué se hizo**

PR #44 (rama `feat/h4-muestreador`), fusionado con *squash and merge*: catorce commits, diez del plan y cuatro de la revisión, con revisión de Codex (tarea crítica). La 4.5 se partió en dos: esta lleva el muestreador al motor y la 4.5b, el guardado y la CLI. Por primera vez el motor simula pacientes con perfil, y el camino del modelo provisional no cambia ni un bit.

- `engine/clinical_sampler.py`: `ClinicalSampler` (flujos 1 a 7 de `child_streams(seed, 8)`, repartidos en `[5, 6]`, `[7, 1]`, `[3, 2]` y el 4 para el destino), `ClinicalTruth`, `ClinicalDraws`, `TurnaroundShifts` y `admitted_from_draw` (destino con el nivel asignado). Vive en el motor porque necesita `PatientDraws` y el destino de `CenterConfig`.
- `PatientDraws` gana `clinical` (`None` con el provisional) y `test_turnaround` pasa a `float | None`: con el clínico es `None`, sin valor inventado. Un `__post_init__` exige un modelo u otro y `needs_tests` = hay ronda.
- `patient.py`: rama explícita. Sin `clinical`, el código del hito 3; con él, payloads clínicos y la respuesta de la ronda calculada al pedir, con la franja de ese instante.
- `simulate_ed(..., profiles=None)`: con perfiles, ocho flujos, el `ClinicalSampler` y un log de la versión 2; con `profiles` y `sampler` a la vez, error de uso.
- `events.py`: un catálogo por versión (`CATALOGS`, `SCHEMA_VERSIONS`); `SCHEMA_VERSION` desaparece. Versión 2: `medio`, `edad`, `sexo`, `motivo`, `pruebas` (tupla) y `resultados` (mapping de solo lectura); las comprobaciones devuelven el valor normalizado y `_plain` los convierte para JSON y pickle.
- `invariants.py`: `door` (los dos modelos), `schema_version` y `clinical` (payloads frente a la verdad y respuesta de cada ronda frente a la franja del pedido, calculada aparte, a 1e-8 min).
- `EpisodeTruth.clinical`; `write_episodes_csv` rechaza episodios clínicos hasta la 4.5b.
- Refactor de rendimiento en `profiles/`: `arrival_context` con aritmética de Python (bit a bit igual que `context_indices`, con un test en los bordes) y pesos de banda precalculados.
- Revisión: test literal de los valores del catálogo 2; nota sobre los logs anteriores a la 4.1; convención de idioma de los tests en `AGENTS.md`, `app/AGENTS.md` y una nota a la ADR 0015.

**Conceptos**

- **Inyección de dependencias.** El motor depende de un contrato, `sampler(arrival) → PatientDraws`, no de un modelo: cambiar el muestreador no toca colas, boxes ni turnos.
- **Un valor que depende de la simulación.** La respuesta de la ronda no se conoce al llegar: se sortea la base (factor 1) y el motor la transforma en el instante del pedido. Los números aleatorios comunes se mantienen: con otra plantilla, el paciente k tiene los mismos sorteos, pero si su pedido cruza las 15:00 su ronda dura otra cosa, y eso es correcto.
- **Lo que ve el hospital y lo que no.** El log lleva lo registrable (medio, edad, sexo, motivo, nivel asignado, pruebas y resultados); G, nivel real, calidad, z, banda y respuestas base van solo al ground truth. El catálogo cerrado y un test de claves prohibidas evitan la fuga de datos.
- **Versionar el esquema.** Una versión por log; la 1 sigue intacta para el provisional. Cambiar los valores aceptados de la versión 2 exige una versión 3.
- **El motor como tubería.** El test de cableado más fuerte no es estadístico: el ground truth de `simulate_ed` es idéntico al del `ClinicalSampler` aplicado a `iter_arrivals` con los mismos flujos.
- **Referencias independientes.** El motor calcula la franja con la versión escalar y la invariante y los tests con `context_indices`: dos cálculos que se vigilan entre sí.

**Decisiones**

- Partir la 4.5 en 4.5a (motor) y 4.5b (guardado y CLI); `run.json` versión 2 se adelanta de la 4.8a a la 4.5b.
- Catálogo versionado con `schema_version`: 1 para el provisional y 2 para el clínico, una versión por log.
- `PatientDraws.clinical` opcional y `test_turnaround=None` con el clínico; la respuesta con la franja del pedido.
- `ClinicalTruth` por composición de los dataclasses de `profiles/`. Guarda la z y los 12 sorteos de las pruebas; los 7 + 17 de persona y motivo y los 3 de duraciones se reconstruyen con la semilla.
- Huella del ground truth clínico: una línea JSON por episodio (`asdict`, `separators=(",", ":")`) y un test de tipos exactos con `type(x)`, recursivo, porque `np.float64` es subclase de `float`.
- `door` como invariante general: la equivalencia puerta ⇔ nivel 1 asignado, y la condición de tiempo en un solo sentido.
- Idioma de los tests, cada zona con su práctica: `tests/` en español y `app/tests/` en inglés (nota a la ADR 0015).

**Resultados**

| Medida | Valor |
| --- | --- |
| Tests | 2.235 en la suite completa (7 min 30 s) y 2.213 rápidos al abrir el PR (2.098 y 2.076 antes); 241 de la app, sin cambios; más el literal del catálogo 2 en la revisión |
| Huellas del provisional | Sin cambios (log del motor y los tres ficheros de la caracterización) |
| Huellas del clínico | Log `1ee7e1ba…` y ground truth `c4f2c069…` (ejemplo, semilla 2026, 3 días, 1.101 episodios) |
| Coste por paciente (14 días, config/) | Provisional 252–264 µs y clínico 486–522 µs (1,93–1,98 veces; 2,46 antes de optimizar). El `ClinicalSampler` cuesta 136 µs; el motor con los sorteos hechos, 288 µs frente a 192 |
| Recuentos de las guardas | V1: la franja de la llegada cambia la respuesta de 137 pacientes en 3 días y 346 en 14; V7: 4 y 38 |

**Comprobaciones clínicas** (14 días, 2 de calentamiento, config/, semilla 2026; provisional → clínico)

| Indicador | Provisional | Clínico |
| --- | --- | --- |
| Tiempo de box por paciente sin esperas | 73,4 min | 91,2 min (+24,2 %; el chat estimó +21 % con factor 1) |
| Carga del médico por paciente | 30,71 min | 32,80 min (+6,8 %) |
| Boxes ocupados: media y pico (de 30) | 16,58 y 30 | 21,00 y 30 |
| Médicos ocupados: media y pico | 6,57 y 12 | 7,01 y 12 |
| Censo: media y pico | 18,99 y 62 | 27,47 y 78 |
| Espera de box, niveles 3 / 4 / 5 | 0,9 / 6,9 / 16,2 min | 2,9 / 36,0 / 87,5 min |
| Espera de médico, niveles 4 / 5 | 3,9 / 15,1 min | 8,1 / 15,6 min |
| Reloj C, nivel 4 (% dentro; días fuera de 12) | 99,5 %; 0 | 82,4 %; 5 |
| Reloj C, nivel 5 | 97,6 %; 1 | 88,0 %; 3 |
| Pretriaje ≤ 10 min (niveles 2 a 5) | 96,7 % | 96,6 % |

Repartos: 2 de 21 motivos fuera del IC al 95 % frente a lo exacto de esos 14 días (lo esperado por azar es uno); bandas dentro; niveles y pruebas, 3 de 15 fuera frente al año, que no es la referencia de 14 días de enero. Reloj C por nivel real con el clínico: 75,0 / 94,8 / 95,6 / 83,7 / 86,4 %. Respuesta de la ronda por franja del pedido (media / mediana / p90): mañana 78,0 / 56,7 / 158,4; tarde 81,6 / 61,8 / 164,7; noche 80,8 / 55,4 / 174,1 min.

Paradas en 60 días: 120 de 19.499 llegadas. 67 asignadas nivel 1 (puerta) y 53 nivel 2 (enfermería); 81 de nivel real 1 y 39 de nivel real 2. Las de la puerta esperan 0,6 min de media (p90 1,8); las de la enfermería, 10,5 min hasta el médico (reloj A; p90 19,4; máximo 32,2), 1,4 min hasta el inicio del triaje (p90 4,7; máximo 23,4), 7,3 hasta la clasificación (p90 11,7; máximo 25,4) y 3,2 min con el reloj C. (Hasta la tarea 4.6b, la cifra del reloj A figuraba como «hasta el triaje»; se comprobó con un worktree de `5ba157a`.)

**Comprobación de las versiones incorrectas** (temporales, con predicción firme)

| Versión incorrecta | Predicción | Observado |
| --- | --- | --- |
| V1. Franja de la llegada en el pedido | Fallan la respuesta con otra plantilla, el pedido a las 15:10, `clinical` en 14 días (las dos configuraciones) y la huella del log | Exacta; la huella del ground truth pasa |
| V2. Destino con el nivel real | Fallan la asignación de flujos y las dos huellas; pasa el destino a mano (función pura) | Exacta |
| V3. Flujos 7 y 1 intercambiados | Fallan la asignación de flujos y las dos huellas; pasa la estadística | Exacta |
| V4. Pruebas y duraciones solo si no es de puerta | Fallan la asignación de flujos, el consumo fijo y las dos huellas | Exacta |
| V5. `child_streams(seed, 8)` también sin perfiles | No falla nada (los cinco primeros hijos son iguales) | Exacta; un primer intento mal aplicado se repitió |
| V6. `gravedad` en el catálogo 2 | Fallan el literal del catálogo, los payloads a mano, las claves prohibidas y la huella; pasan las invariantes | Fallaron los previstos y además 2 de invariantes y eventos a mano: sin claves opcionales, la clave nueva pasa a ser obligatoria |
| V7. Factor del tipo de mayor base sobre la máxima de las bases | Falla solo el caso de las 22:00 (84) y pasa el de las 15:00; fallan la respuesta con otra plantilla, `clinical` y la huella | Exacta |
| V8. Puerta con el nivel real | Fallan los payloads a mano, `door` en 14 días (3 + 2 pacientes) y la huella (el 256) | Exacta |
| V9. `resultados` también de las no pedidas | Fallan los payloads a mano, `clinical` y la huella; pasan las invariantes | Fallaron los previstos y además 11 de invariantes: sus datos de prueba los genera el motor, que ya escribe un log roto |
| V10. Sin factor de franja | Fallan cuatro casos a mano (15:00, las dos de las 22:00 y 07:59), el pedido a las 15:10, la respuesta con otra plantilla, `clinical` y la huella | Exacta |

Ninguna predicción falló por un hueco de cobertura: V6 y V9 fallaron en más tests de los previstos, no en menos.

**Lecciones aprendidas**

- Lo que depende del instante de la simulación no se sortea al llegar: se sortea lo estándar y se transforma cuando se conoce el instante.
- Los sorteos comunes no implican resultados idénticos: la misma persona puede tener otra ronda si cambia la hora del pedido.
- La igualdad bit a bit con el muestreador directo prueba el cableado mejor que cualquier χ².
- Una referencia de test tiene que ser independiente del código; si comparte la función, comparte el error.
- Una predicción puede fallar por «pasan»: un fixture generado por el motor arrastra el error a tests que no lo prueban, y un catálogo cerrado convierte cualquier clave nueva en obligatoria.
- Cambiar el tipo de una constante con el mismo nombre rompe en silencio; un nombre nuevo hace que lo antiguo falle al importar.
- Un revisor automático aplica las reglas al pie de la letra: hay que escribir la práctica real, y comprobar todas las zonas antes de escribirla (`app/tests/` estaba en inglés).
- Pasar todos los tests no es ser clínicamente creíble: los boxes saturados y las paradas en la cola del triaje salieron de las comprobaciones clínicas.
- Optimizar solo con una medida y un umbral fijados antes, y sin cambiar ningún valor.

**Pendiente**

- Tarea 4.5b: CSV del ground truth clínico, `simulate_run` con perfiles (y `profiles` a `check_invariants`, con un test), `run.json` versión 2, `motor simular --perfiles` y `perfiles validar`.
- Decisión abierta para la 4.6: los boxes pasan a ser el cuello de botella (tiempo de box +24 %, nivel 4 con 5 días fuera de 12). La plantilla de médicos (decisión 41) puede no bastar: calibrar también los boxes, revisar los porcentajes orientativos de pruebas (72,8 % frente al 55,4 % del provisional) o adelantar una zona de espera de resultados.
- Decisión abierta para la 4.6: el 44 % de las paradas recibe nivel 2 y espera en la cola del triaje (hasta 32 min), y un tercio tiene nivel real 2. Opciones: puerta por motivo, más gravedad y menos dispersión para la parada, o aceptarlo hasta el circuito de críticos de la v1.
- Tarea 4.8a: la app serializa el payload con `json.dumps(dict(...))`, que no admite `resultados`; una ejecución antigua como dato de prueba debe ser posterior a la 4.1.

### Tarea 4.5b: ejecuciones clínicas, motor simular --perfiles y perfiles validar

**Qué se hizo**

PR #45 (rama `feat/h4-cli-perfiles`), fusionado con *squash and merge*: trece commits, sin revisión de Codex y sin cambios pedidos en la revisión. Una ejecución clínica ya se guarda en `resultados/` con todo lo que la generó, se lanza desde la CLI y el muestreador se valida con un comando.

- `engine/report.py`: CSV del ground truth clínico (57 columnas, con la z y los 12 sorteos), `ProfilesParameters`, y un lector (`episode_from_row`, `read_episodes_csv`) con tokens exactos y comprobaciones de coherencia. El CSV provisional, byte a byte igual.
- `runs/store.py`: `run.json` versión 2 con `model`, `clinical_profiles_path` y `clinical_profiles_fingerprint`; claves exactas por versión al leer; solo se escribe la 2; `archive` con 7 ficheros en las clínicas. `tests/data/run_v1.json`, escrito con `main` antes de tocar nada.
- `runs/service.py`: `simulate_run(..., profiles=None)` copia `perfiles.toml`, carga desde la copia y pasa los perfiles a `simulate_ed` y a `check_invariants` (el pendiente de la 4.5a).
- `runs/compare.py`: `pairing_blockers` añade el modelo y la huella de los perfiles.
- `cli.py`: `motor simular --perfiles` y `perfiles validar`. `profiles/validation.py`: evaluación separada del sorteo (refactor sin tocar tests), `validate_profiles` con un solo sorteo del año, `mixing_minimum` con margen, datos de las gráficas con IC. `profiles/report.py`: tabla y cuatro gráficas.

**Conceptos**

- **Una ejecución reproducible** guarda todo lo que la generó: copia y huella de los tres ficheros de configuración, y se carga siempre desde la copia.
- **Versionar un formato en disco.** Se escribe la versión nueva y se leen las dos; lo antiguo se lee con el significado que tenía (versión 1 = provisional). Los valores por defecto nunca rellenan claves que faltan.
- **Un formato estable va y vuelve.** Leer el CSV da el mismo `EpisodeTruth`, floats bit a bit. Eso convierte el CSV en el formato de intercambio y en la referencia de la 4.8a.
- **Misma semilla no es mismos pacientes** si cambia el modelo: el emparejamiento lo bloquea.
- **Un mínimo con recuentos aleatorios necesita margen.** La mezcla calcula lo esperado de un motivo dentro de una banda con el recuento observado de la banda: en el mínimo exacto, la comprobación se queda sin pacientes la mitad de las veces. El margen se elige con la binomial de cada banda y la unión de bandas y contextos.
- **Falsa alarma de una batería de pruebas.** Cuatro comprobaciones al 1 % dan hasta un 4 % de falsas alarmas conjuntas (desigualdad de Boole); se escribe, sin cambiar α, para que cada fila siga siendo su `check_*`.
- **Sortear una vez.** Triaje, pruebas y duraciones usan los mismos pacientes con la misma semilla: un solo sorteo del año ahorra unos 14 s y da exactamente los mismos resultados.

**Decisiones**

- `run.json` v2 para todas las ejecuciones nuevas; v1 solo lectura, como provisional. Nombres `clinical_profiles_*` para no confundirlos con el perfil de llegadas; campos opcionales explicados por `model` y comprobados en `__post_init__`.
- CSV clínico con todo `EpisodeTruth`; `banda` como índice (los límites son de los perfiles); el nivel asignado solo en `nivel`. El CSV de días, igual con los dos modelos.
- `--pacientes N`: N por contexto en la mezcla y N en el año; mínimos con margen (probabilidad de parar menor que 1e-6): 15 234 por contexto en la mezcla y 11 826 en el año.
- Semillas de `perfiles validar`: `child_streams(seed, 2)`, hijo 0 para la mezcla y 1 para el año.

**Resultados**

| Medida | Valor |
| --- | --- |
| Tests | 2.344 en la suite completa (7 min 32 s) y 2.321 rápidos (3 min 51 s); 241 de la app sin cambios en `app/` |
| Huellas del provisional | Sin cambios: log `220eb8c6…`, episodios `55a623b9…`, días `af940fff…` |
| Huellas nuevas del clínico (`motor simular --perfiles`, ejemplo, 2 días, semilla 7) | Log `306392fe…` (igual que `simulate_ed`), episodios `3f59dd25…`, días `af940fff…` (la misma que el provisional) |
| `motor simular` 14 días, config/, semilla 2026 | 0 violaciones (incluida la respuesta de cada ronda); 5,3 s frente a 3,8 s del provisional; log de 22,1 MB frente a 20,7 MB; CSV de episodios de 3,1 MB frente a 1,0 MB |
| `perfiles validar` por defecto | Código 0; 29 s en total (mezcla 11–12 s, sorteo del año 14–18 s, evaluaciones 0,0 / 0,2 / 0,2 s); 209 MiB de memoria |

| Comprobación | Pacientes | Categorías | p mínimo | α por categoría | Error detectable (80 %) |
| --- | --- | --- | --- | --- | --- |
| Mezcla de motivos | 480 000 | 2.136 | 1,65e-5 | 4,68e-6 | Un motivo del 5,0 % que pasa a 5,8 % |
| Triaje | 109 542 | 30 | 0,00705 | 3,33e-4 | Nivel 1 asignado: 0,40 % → 0,49 % |
| Pruebas | 109 542 | 134 | 0,0042 | 7,46e-5 | Analítica en el quintil 3 de G: 45,0 % → 46,6 % |
| Duraciones | 109 542 | 64 | 0,000356 | 1,56e-4 | Mediana de valoración del real 3: 50,0 % → 51,2 % |

El chat recalculó el mínimo de la mezcla con la rama: 15 234 da una probabilidad de parar de 9,9e-7 y 15 233, de 1,01e-6. También los errores detectables de la mezcla y del triaje. La app lista las tres ejecuciones (v1, provisional v2 y clínica) y abre Resultados y Replay de la clínica; Episodios y Comparar no la abren hasta la 4.8a.

**Comprobación de las versiones incorrectas**

| Versión incorrecta | Predicción | Observado |
| --- | --- | --- |
| V1. `simulate_run` sin perfiles en `check_invariants` | Fallan el espía y el de comportamiento | Cumplida, más dos espías que fijan los argumentos exactos |
| V2. Respuesta base con el factor de la franja de la llegada en el CSV | Fallan la ida y vuelta, la fila a mano de tarde y la huella del CSV clínico | Cumplida, más la lectura frente a `simulate_ed` |
| V3. `run.json` clínico con la versión 1 | `RunInfo` la rechaza y fallan todos los tests que crean una clínica | Exacta |
| V4. Perfiles del original y no de la copia | Falla solo «el original modificado no cambia el log» | Exacta |
| V5. `perfiles validar` devuelve 0 aunque falle | Falla solo el del código 1 | Exacta |
| V6. CSV provisional con las columnas de perfiles | Fallan huellas, cabeceras y lectores de cabecera exacta | Cumplida, más la ida y vuelta con `read_episodes_csv` |
| V7. Emparejamiento sin el modelo | Falla solo la tupla exacta; el bloqueo sigue por la huella | Exacta |
| V8. La CLI no valida `--perfiles` antes de simular | Fallan los de código 2 | Cumplida, más el de la cabecera |
| V9. Sortear el año en cada comprobación | Falla solo el espía del sorteo | Exacta |
| V10. `archive` sin `perfiles.toml` | Falla solo el de los 7 ficheros | Exacta |
| V11. `read` rellena claves que faltan en la v2 | Fallan 4 tests | Fallaron 10: más tests dependen de las claves exactas |
| V12. `respuesta_pruebas` vacía leída como 0,0 | Fallan la ida y vuelta y la fila a mano | Cumplida, más la lectura frente a `simulate_ed` |
| V13. Mínimo de la mezcla sin margen | Fallan las cifras y el código 2; pasan los rápidos | No cumplida: los rápidos toman su N de `mixing_minimum` y, en el mínimo exacto, la mezcla se queda sin pacientes (4,91 esperados < 5). El literal 15 234 vigila la función |

**Lecciones aprendidas**

- Un mínimo calculado con valores esperados no basta si la comprobación usa recuentos observados: hace falta un margen con su probabilidad calculada.
- Un test que calcula su tamaño con la función que se prueba hereda sus errores; un literal la vigila.
- Las predicciones de «pasa» fallan más que las de «falla»: muchos tests dependen indirectamente de lo que se rompe (V11, V13).
- Si dos comprobaciones sortean lo mismo con la misma semilla, se sortea una vez y un espía lo vigila, porque la igualdad de resultados no lo ve.
- Una batería de pruebas tiene una tasa de falsa alarma conjunta que hay que escribir.
- Leer el código resuelve dudas que la descripción de un PR deja abiertas (si los perfiles llegaban a `check_invariants`).

**Pendiente**

- Tarea 4.6: las dos decisiones abiertas de la 4.5a (boxes como cuello de botella y paradas en la cola del triaje), antes de calibrar.
- Tarea 4.8a: `runs/truth.py` con `episode_from_row`, emparejamiento clínico, `read_run_results` que recalcula invariantes sin perfiles.
- Tarea 4.8b: payload de `resultados` en la app y etiquetas de los campos nuevos en Comparar.
- Menor: el aviso «tarda unos 30 segundos» de `perfiles validar` se imprime también con `--pacientes`.

### Tarea 4.6a: paradas y espera de resultados fuera del box

**Qué se hizo**

PR #46 (rama `feat/h4-paradas-sala`), fusionado con *squash and merge*: diez commits en dos fases (A, paradas; B, sala de resultados) y dos más de la revisión, con `@codex review`. Es la primera mitad de la 4.6: la calibración queda para la 4.6b, sin mezclarla con cambios del modelo.

- Fase A. `profiles/derivation.py`: `derive_written_values` (la cascada de pesos base, ruido y sesgo y umbrales, redondeados como se escriben), `reason_level1_shares` y `severity_mean_for` (el criterio de la gravedad de un motivo). Parada al 0,3 % con media 4,21 y desviación 0,25, cascada rederivada en `config/` y `tests/data`, y `DEFAULT_MIXING_PATIENTS` de 20 000 a 25 000.
- Fase B. `recursos.espera_resultados_fuera` en `centro.toml` (opcional, `[]` si falta; `[4, 5]` en `config/`), catálogo versión 3 con `box_released`, sala de resultados en `patient.py`, invariantes de la sala y `results_wait`, `initial_box_wait` y `results_box_wait` en `EpisodeRecord`, curvas y Replay (`waiting_tests` sin box), y `tests/data/centro_sala_ejemplo.toml` con su caracterización.
- Revisión. `_variant_bytes` con listas de otra longitud (P2 de Codex) y la convención de idiomas de los auxiliares de `tests/`, escrita en la ADR 0015 y en `AGENTS.md` (P1).

**Conceptos**

- **Un valor orientativo elegido por criterio.** Sin dato, se escribe la condición que debe cumplir (≥ 99 % de nivel real 1 y ≥ 97 % de asignado 1) y una función busca el menor valor que la cumple. Un literal y una guarda con Φ a mano la vigilan.
- **Derivados en cascada.** Pesos base, ruido y sesgo y umbrales dependen unos de otros: al mover un motivo se rederivan todos en orden, y un test comprueba que la cascada entera reproduce lo escrito.
- **El cuello de botella se mueve.** Soltar el box mientras se esperan resultados baja el tiempo de box un 23 % y deja a los médicos igual: ahora la plantilla es el mando que mueve los tiempos.
- **Una invariante reconstruye desde el log.** «Nadie se cuela» no ve la clave del motor, sino la que se deduce de los eventos (nivel, llegada). Si el motor usa otra, la invariante lo detecta.
- **Una versión de catálogo por modelo, no por configuración.** El clínico escribe siempre la 3: el número dice qué eventos pueden aparecer, no cómo estaba configurado el centro.
- **Una clave opcional conserva el significado antiguo.** Si falta, vale lo que valía antes (`[]`), no el valor nuevo de `config/`: las ejecuciones guardadas siguen significando lo mismo.

**Decisiones**

- Decisión 45: la sala decide con el nivel *asignado* (4 y 5 en `config/`); el paciente vuelve con su clave de siempre y el provisional no cambia.
- Decisión 46: parada al 0,3 %, media 4,21 y desviación 0,25 por criterio (con 0,20 la media sería 4,16; con 0,30, 4,27).
- Huellas regeneradas una vez por fase. La caracterización existente sigue con `centro_ejemplo.toml`, y la sala tiene la suya, cuyos CSV solo difieren en `centro` y `huella_centro`.
- En `tests/`, los auxiliares y las fixtures pueden ir en inglés; los nombres de los tests, los docstrings y los comentarios, en español.

**Resultados**

14 días, `config/`, semilla 2026 y plantilla \[12, 12, 7\], salvo las paradas (60 días). Tiempos en minutos.

| Medida | Antes | Después |
| --- | --- | --- |
| Tests | 2.344 en la suite completa y 2.321 rápidos | 2.427 (9 min 34 s) y 2.404 (3 min 50 s); 241 de la app |
| Tiempo de box por paciente, sin esperas de médico | 91,0 | 69,8 |
| Boxes ocupados, media / pico | 21,0 / 30 | 16,5 / 30 |
| Médicos ocupados, media / pico | 7,0 / 12 | 7,0 / 12 |
| Espera de box, niveles 2 / 3 / 4 / 5 | 1,4 / 2,9 / 36,0 / 87,5 | 0,6 / 0,8 / 12,8 / 20,4 (inicial 11,6 y 13,9 y vuelta 1,1 y 0,2 en los niveles 4 y 5) |
| Reloj C, niveles 4 y 5 (cumplimiento; días fuera de 12) | 82,4 %, 5; 88,0 %, 3 | 95,4 %, 2; 92,6 %, 2 |
| Paradas en 60 días | 120 de 19.499; 67,5 % de nivel real 1, 55,8 % a la puerta, 53 por enfermería | 78; 100 %, 98,7 %, 1 |
| `perfiles validar` por defecto | 29 s | 35 s (la mezcla, 16,6 s con 25 000 por contexto) |
| Huellas del provisional | Log `70323516…`; CLI `220eb8c6…`, `55a623b9…`, `af940fff…` | Sin cambios |
| Huellas del clínico, log y ground truth | `1ee7e1ba…` y `c4f2c069…` | `0a593f3f…` y `10617910…` |
| Huellas de la CLI clínica, log y episodios | `306392fe…` y `3f59dd25…` | `2a8df1e8…` y `0d18f0a0…`; con sala, `d033762d…` (223 `box_released`) |

Lo que anticipa para la 4.6b, sin calibrar: el reloj A es de 18,8 minutos en los niveles 2 a 5 (objetivo 35–70) y de 9,3 en el nivel 3 (45–75), y el pretriaje, de 1,4 (6–15). Los 60 días de las paradas son enero y febrero, con más disnea y fiebre que el año.

**Comprobación de las versiones incorrectas**

| Versión incorrecta | Predicción | Observado |
| --- | --- | --- |
| V1. Umbrales rederivados con el ruido y el sesgo de antes | Fallan «escritos = calibrados» y el literal del ejemplo; pasan umbrales, infra y sobre, la guarda y las huellas clínicas | No cumplida en dos «pasan»: fallaron también la guarda, el shock, la cascada y las huellas (0,53 cambios de nivel esperados en 3 días, no 0,3, y la huella de `perfiles.toml` va en el CSV clínico) |
| V2. Parada al 0,3 % sin rederivar los pesos base | Fallan pesos, umbrales, ruido, reparto asignado, mínimos y huellas | Cumplida (29 fallos), con fallos de más explicados |
| V3. La sala decidida con el nivel real | Fallan el infratriado y el sobretriado a mano, `results_wait` en 14 días y la huella con sala | Exacta |
| V4. La vuelta con una clave nueva | Fallan el escenario a mano y «nadie se cuela» | Exacta (1.735 violaciones en 14 días). El chat había predicho que pasaban las invariantes |
| V5. La sala también con el provisional | `ValueError` en las guardas y en los tests provisionales con `config/centro.toml`; pasan huellas y validación | Cumplida (12 fallos) |
| V6. Soltar el box antes del `test_ordered` | Fallan `transitions`, el orden del escenario y la huella con sala | Exacta (4.021 violaciones en 14 días) |
| V7. La capacidad cuenta a los de la sala | Falla `capacity` en el escenario y en 14 días | Cumplida, más cuatro tests de violaciones a mano |
| V8. `step_curves` sin `box_released` | Fallan las curvas a mano y la utilización de boxes | Exacta |
| V9. La cola de box sin la vuelta | Fallan la curva a mano y Little | Exacta |
| V10. Parada con media 4,20 y su cascada | Fallan la guarda y el literal del criterio | Cumplida, más los literales que dependen de c₁ |
| V11. Replay sin `box_released` | Fallan «nunca dos pacientes en el mismo box» y los estados de A | Exacta |

**Revisión**

Codex dejó dos comentarios. P2, un fallo real: `_variant_bytes` editaba las listas posición a posición y, con la base `[4, 5]`, pedir `[]` dejaba `[4, 5]` sin avisar, `[5]` escribía `[5, 5]` y `[2, 4, 5]` daba `IndexError`. Ahora sustituye el array si cambia la longitud y relee lo escrito. P1: los auxiliares nuevos de un test del núcleo estaban en inglés, como en toda la carpeta; se escribió la práctica en lugar de renombrar.

**Lecciones aprendidas**

- Las predicciones de «pasa» siguen fallando más que las de «falla» (V1).
- Antes de predecir sobre una invariante, hay que mirar qué reconstruye del log (V4).
- Un supuesto implícito, como las listas de longitud fija, se rompe cuando entra una clave de otro tipo. Hay que releer los escritores y lectores que la tocan.
- Una regla escrita debe describir la práctica real: un revisor automático la aplica al pie de la letra.
- Una cifra sin su medida escrita no se puede reproducir (las esperas de las paradas del anexo 4.5a).

**Pendiente**

- Tarea 4.6b: calibrar la plantilla con la sala. Habrá que quitar médicos. El pretriaje depende de la enfermería de triaje, y el único mando de la decisión 41 no lo mueve: hay que decidirlo antes de calibrar.
- Medida de las esperas de las paradas por enfermería del anexo 4.5a (10,5 / 19,4 / 32,2 min): de la llegada al inicio del triaje salen 1,4 / 4,7 / 23,4 con la misma población. Hay que medir de la llegada a la clasificación y corregir el texto.
- Tareas 4.8a y 4.8b: Episodios y Replay con los dos tramos de box, un estado y una etiqueta propios de la sala, y `initial_box_wait` y `results_box_wait` en las tablas de la app.

### Tarea 4.6b: calibración de la enfermería de triaje y de los médicos

**Qué se hizo**

PR #48 (rama `feat/h4-calibracion`), fusionado con *squash and merge* sin cambios de la revisión: catorce commits en dos fases. En la A, el código y todas las medidas, sin tocar `config/centro.toml`. En la B, la plantilla escrita, después de fusionar el PR #47 de Codex, que desacopló de la plantilla los tests de `app/tests` en su zona (conservando los valores a mano que no dependen de `[recursos]`). Codex trabajó en un worktree aparte, en paralelo. El motor no cambia.

- `src/edsim/calibration/`: `targets.py` (`objetivos.toml`, `Target`, `load_targets`), `staffing.py` (regla de la plantilla equivalente), `evaluate.py` (réplicas con día de vaciado, horquillas, días fuera, sensibilidad, elección y cumplidor) y `report.py` (tablas y CSV).
- CLI: `edsim calibracion evaluar` y `edsim calibracion sensibilidad --mando`.
- `config/objetivos.toml` (cinco objetivos con su fuente), `config/centro.toml` con la plantilla calibrada y `config/centro_cumplidor.toml`.
- `docs/calibracion/registro.md`: parámetro, antes, después, KPI, motivo y todas las tablas con su comando.
- Lo que dependía de la plantilla del hito 3 queda fijado a ella: las simulaciones provisionales usan `tests/data/centro_ejemplo.toml`, y el notebook 03 usa `dataclasses.replace` (mismas 23 salidas y los mismos hashes de sus 16 imágenes).
- Anexo 4.5a corregido: aquella cifra de las paradas era el reloj A.

**Conceptos**

- **Un número por mando.** Personal del turno = ⌈carga del turno / u⌉: la búsqueda es de una dimensión y se explica sola. La carga es el personal que la demanda tendría ocupado sin colas.
- **Mandos separables.** El pretriaje ocurre antes del médico, así que con la misma semilla cambiar médicos no cambia ni un pretriaje: se comprueba con igualdad exacta, también en las réplicas de verdad.
- **Censura al final de la ventana.** Los que llegan al final y siguen dentro son los que más esperan; un día de vaciado los deja salir y se mide solo a los llegados en la ventana.
- **Horquilla e intervalo.** Un objetivo pasa si la media cae dentro y el IC no es más ancho que la horquilla; con 10 réplicas, t₉ = 2,262.
- **Ajuste y comprobación.** Se elige con una semilla y se comprueba con otra; una comprobación nunca elige.
- **Un objetivo que ningún mando mueve no se calibra.** La regla 5 lo convierte en comprobación, con la causa escrita, sin esconder que falla.
- **El trabajo se conserva.** Los médicos ocupados son 7,0 de media con cualquier plantilla sin censurados: cambiar la plantilla cambia las esperas, no la carga.

**Decisiones**

- Decisión 41 revisada (6 de noviembre): dos mandos con objetivos separados, la enfermería de triaje contra el pretriaje y, con ella fija, los médicos contra el reloj A.
- Las plantillas candidatas salen solo de la regla, con u de 0,55 a 0,99 en pasos de 0,0025.
- Elección entre las que pasan: la más cercana a la referencia del objetivo que decide o, sin ella, al centro de la horquilla (52,5 min en los niveles 2 a 5).
- El reloj A del nivel 3 pasa a comprobación después de medir la sensibilidad, por una discrepancia estructural (prioridad estricta en un solo grupo de médicos).
- Semillas 2026 (ajuste) y 2027 (comprobación); 10 réplicas de 14 días con 2 de calentamiento y uno de vaciado.
- Cumplidor: la misma enfermería y los médicos de la regla con el u más alto que deja como mucho un 10 % de días fuera de Manchester (reloj C) en cada nivel 2 a 5.

**Resultados**

| Medida | Antes | Después |
| --- | --- | --- |
| Enfermería de triaje | \[3, 3, 2\] | \[3, 2, 1\] (u de 0,795 a 0,8325) |
| Médicos | \[12, 12, 7\] | \[12, 11, 5\] (u de 0,81 a 0,8475); cumplidor \[15, 15, 6\] |
| Pretriaje medio, niveles 2 a 5 (6–15) | 1,37 min | 10,65 \[8,92; 12,37\] con 2026; 11,99 con 2027 |
| Reloj A, niveles 2 a 5 (35–70) | 25,0 min | 54,5 \[47,0; 62,1\] con 2026; 49,9 con 2027 |
| Reloj A, nivel 3 (comprobación, 45–75) | 10,3 min | 22,9 y 24,2: fuera, por la discrepancia |
| % sobre Manchester con el reloj A (10–30) | 9,0 % | 21,1 y 20,0 % (el nivel 2 aporta 7,5 puntos) |
| % con pretriaje de más de 5 min (30–60) | 9,3 % | 40,0 y 39,4 % |
| Ocupación por turno (mañana, tarde, noche) | — | Enfermería 59 / 78 / 63 %; médicos 76 / 82 / 85 % |
| Reloj A medio por nivel 2 / 3 / 4 / 5 | — | 17,4 / 18,5 / 57,7 / 107,3 min (p90 43 / 43 / 181 / 376) |
| Días fuera de Manchester (C), de 12, niveles 2 a 5 | — | Calibrado 0 / 1 / 6 / 6; cumplidor 0 / 0 / 2 / 1 |
| Tests | 2.427 (2.404 rápidos) | 2.539 en 8 min 7 s (2.515 rápidos en 5 min 7 s); 241 de la app con la plantilla nueva |
| Coste | — | Una réplica de 15 días, unos 2 s; una evaluación de 10 réplicas, 1 min 50 s; las sensibilidades, 5 min 44 s y 15 min 20 s |

El anticipo del chat para la enfermería, con una simulación aparte de la cola de triaje, se cumplió dentro del 15 % en tres plantillas (10,4 frente a 10,65 en la elegida) y se apartó un 36 % en \[2, 2, 1\], cerca de la saturación y con el factor de enero. Ninguna cola crece de un día al siguiente. `edsim motor validar` pasa sus 11 comprobaciones con los valores por defecto.

**Comprobación de las versiones incorrectas**

Trece, aplicadas y deshechas en el mismo turno. Diez exactas (V2 a V7, V9, V11 a V13, esta última «sin día de vaciado», añadida en la aprobación). V1 (`round` en lugar de `ceil`) no se cumplió en un caso: con u = 0,85 `round` también da \[2, 2, 1\]. V8 y V10 fallaron en más tests de los previstos, y tras pasar el nivel 3 a comprobación el test de la elección de médicos ya no veía la V10: se reforzó con una plantilla que no pasa más cerca del centro de la horquilla. La tabla completa está en «Tests y validación».

**Revisión**

Se fusionó sin cambios. Quedó un detalle sin arreglar: `compliant_staffing` compara con 0,10 una media de decimales, y el cumplidor elegido está justo en el borde (10,0 % de días fuera en los niveles 4 y 5). Con 12 de 120 días, la media puede salir 0,1000000001 en unos 3 de cada 10.000 repartos de esos días: hoy elige bien, pero conviene decidirlo con enteros.

**Lecciones aprendidas**

- Un objetivo que ningún mando puede mover se descubre midiendo la sensibilidad antes de ajustar: por eso existe la regla 5.
- Una referencia independiente (la simulación aparte de la cola de triaje) anticipa el resultado y detecta errores gruesos antes del motor.
- Una comprobación que decide el ajuste deja de comprobar: la elección tiene que usar solo los objetivos de ajuste.
- Dos agentes en paralelo necesitan carpetas distintas (un worktree por agente), o uno ve los cambios del otro.
- Una cifra sin su medida escrita confunde durante semanas: la del anexo 4.5a era el reloj A con la etiqueta de otro.
- Un umbral «como mucho» con una plantilla justo en el borde se decide con enteros, no con decimales.

**Pendiente**

- Menor: el cumplidor decidido con enteros (`compliant_staffing`).
- Pretriaje de noche: con una enfermera desde las 22 h, cuando aún llegan 12,6 pacientes por hora, los llegados a medianoche esperan 35,3 min de media (p90 79,8). Turnos escalonados por mando, para versiones posteriores.
- Circuitos separados para los niveles 4 y 5 (consultas o vía rápida): es lo que permitiría calibrar el nivel 3, y reduciría las esperas de los niveles 4 y 5 (p90 de 181 y 376 min). Por decidir.
- Tarea 4.7: el notebook 04 con el centro calibrado, el cumplidor y la sensibilidad.
- Tarea 4.9: el centro de ejemplo de los tests provisionales se retira cuando `centro.toml` pierda sus secciones provisionales.

### Tarea 4.7: notebook 04 de perfiles clínicos

**Qué se hizo**

PR #49 (rama `feat/h4-notebook`), fusionado con *squash and merge*: ocho commits y dos de la revisión. El motor y la calibración no cambian: `config/` sigue igual byte a byte.

- `engine/targets.py`: cumplimiento por nivel real con el ground truth (`true_level_compliance`, `true_levels`, `true_level_waits`) y `classified_late`, sin tocar `manchester_compliance`.
- `profiles/coupling.py`: Gumbel-max frente a la CDF inversa ante un cambio de pesos, con la fórmula exacta y simulado con números comunes.
- `profiles/derivation.py`: `with_target_mix`, una variante en memoria con otro reparto objetivo; `calibration/sas.py`: el reparto del SAS en adultos y el TPAM por nivel.
- Auxiliares: `SeverityMixture.pdf`, `lognormal_pdf` y `evaluate_staffings` (la sensibilidad evalúa una lista dada de plantillas).
- `notebooks/04_perfiles_clinicos.ipynb`, con el centro calibrado y el cumplidor, y la especificación y el registro al día.
- En la revisión: el apartado «El reloj A según el horizonte» del registro y las cifras del notebook (73,5 y 229) corregidas con lo medido.

**Conceptos**

- **El coste del infratriaje se mide en tiempo.** El mismo paciente cumple o no según el máximo de qué nivel se le aplique: por nivel asignado mide al hospital, por nivel real mide al paciente. Solo el ground truth lo sabe.
- **Acoplamiento mínimo.** Con dos repartos, la menor proporción de pacientes que tiene que cambiar de motivo es la distancia de variación total. Gumbel-max la alcanza siempre que solo crece un peso; la CDF inversa depende del orden de las categorías.
- **Clasificado tarde.** Si al terminar el triaje ya pasó el máximo del nivel, ningún médico puede hacerlo cumplir con el reloj A: el incumplimiento es del triaje, no de la consulta.
- **Una variante es otro perfil.** Cambiar el reparto objetivo rederiva los umbrales en memoria; los escritos no se recalculan al cargar (decisión 38).
- **Sesgo de inicialización frente a carga del mes.** Para saber si el arranque vacío baja las esperas se compara por bloques con la carga fija (factor mensual neutro): si el primer bloque no queda por debajo, el calentamiento basta.

**Decisiones**

- El cumplimiento por nivel real es una función aparte que exige el ground truth, para que no se pueda calcular desde el log.
- Las cifras de la gripe son las exactas de `reason_shock_changes` con los pesos de `config/`; las de la sesión conceptual eran de los pesos de entonces.
- El SAS en adultos se obtiene quitando los menores nivel a nivel, no restando puntos al reparto con niños.
- El notebook 03 sigue con la plantilla del hito 3; el 04 usa la calibrada.

**Resultados**

| Medida | Valor |
| --- | --- |
| Gripe (disnea ×1,5), un año | Gumbel-max 3,37 % (el mínimo); CDF inversa 15,55 %; simulado 3,41 y 15,52 % |
| Nivel 2 con el reloj C, 89 días | 94,6 % por nivel asignado y 93,3 % por nivel real; 14 y 21 días fuera |
| Días fuera, niveles 3 y 5 | Nivel 3, de 2 a 15; nivel 5, de 40 a 24 (muchos niveles 5 reales están asignados como 4) |
| Niveles 2 clasificados tarde | 45,5 %: con el reloj A el nivel 2 queda fuera los 89 días |
| Niveles 1 reales, ejecución principal | 141: 126 a la puerta y 15 asignados como 2 (10,6 %) |
| SAS en adultos | 1,15 / 7,32 / 34,44 / 38,86 / 18,22 % (2.574.941 adultos) |
| Variante con el SAS en adultos | Infratriaje 14,4 % y sobretriaje 8,0 %; reloj A de los niveles 2 a 5, de 73,5 a 47,3 min con los mismos pacientes |
| Calibración en el notebook (5 réplicas) | Elige \[3, 2, 1\] y \[12, 11, 5\], como el registro con 10 |
| Notebook 04 | Modo normal 3 min 52 s a 4 min 4 s, 621 a 638 MB; rápido 26 a 28 s; los cuatro notebooks en rápido, 53 s a 1 min 2 s |
| Tests | 2.613 (2.589 rápidos); 241 de la app |

**Comprobación de las versiones incorrectas**

Ocho, aplicadas y deshechas. Tres exactas (clasificados tarde con `>=`, la densidad sin pesos tras separar sus tests y la variante con los umbrales de antes en la segunda pasada). Cinco cumplidas con fallos de más, todos explicados: el episodio que falta en el ground truth lo detecta solo la búsqueda del nivel real; con sorteos independientes cambian pacientes aunque los pesos no cambien; y los tests que toman su objetivo del SAS o usan la fórmula con un cambio de pesos fallan con ellas. La tabla completa está en «Tests y validación».

**Revisión**

La sección 12 dio un reloj A de 73,5 min en 28 días y la ejecución de 91 días, 229 en el nivel 5, muy por encima de los 54,5 de la calibración. El agente lo midió sin tocar la calibración (registro, «El reloj A según el horizonte»): no es sesgo de inicialización, sino el mes y una semana mala. Con el factor mensual neutro, los bloques de 14 días dan de 26,8 a 33,9 min, y el primero no queda por debajo. Enero (factor 1,10) da 57–62 min y febrero, 34–43; en la semilla 2026, cuatro días seguidos con más llegadas (19 a 22 de enero) llevan la semana a 131,8 min y al nivel 5 a 985, el 47 % de sus minutos de espera en los 89 días. La consecuencia: la calibración mide la primera quincena de enero, y con la carga media del año el centro calibrado da unos 28 min, por debajo de la horquilla de 35–70, mientras los objetivos del SAS son medias anuales.

**Lecciones aprendidas**

- Una cifra que crece con el horizonte se descompone antes de corregirla: por bloques, con la carga fija y por semana de calendario.
- La ventana de la calibración tiene que representar lo que mide el objetivo: una media anual no se ajusta con la primera quincena de enero.
- Un solo test que comprueba dos cosas puede esconder una versión incorrecta: «integra 1» no ve una mezcla sin pesos.
- Emparejar por posición funciona mientras las tablas vienen en el mismo orden; se empareja por id.
- Las cifras de una sesión conceptual se rehacen con la configuración vigente antes de escribirlas en la especificación.

**Pendiente**

- Tarea 4.6c: recalibrar con una réplica por mes, de modo que la media sea la del año, y rehacer con la plantilla nueva las cifras del notebook 04, el registro y la especificación.
- Menor: el cumplidor decidido con enteros (`compliant_staffing`).
- Tarea 4.8a, después de la 4.6c.

### Tarea 4.6c: recalibración con la ventana anual

**Qué se hizo**

PR #50 (rama `feat/h4-recalibracion-anual`): diez commits y dos de la revisión. El agente paró dos veces antes de escribir `config/`, como pedía el prompt, y Pedro decidió con las tablas delante.

- `calibration/window.py`: la ventana anual (12 réplicas, la m desde el primer lunes del mes m+1, con el hijo m de la semilla) y la ventana `inicio` de la 4.6b; `with_start_date` cambia solo la fecha del perfil.
- `evaluate.py`: `simulate_replicas`, `evaluate_staffings` y `sensitivity` con `start_dates`; `pooled_value` (media por paciente del año, informativa); el cumplidor con días enteros (`Fraction(1, 10)`, `complies`); `choose_staffing(…, check=…)` con el veto de la semilla de comprobación; `CONFIRMATION_SEED = 2028`.
- CLI: `--ventana {anual,inicio}` en `calibracion evaluar` y `sensibilidad`, el perfil por mes y la media por paciente; en la revisión, `sensibilidad --comprobacion SEMILLA`, que aplica el veto.
- `config/centro.toml`: médicos `[12, 11, 5]` → `[12, 11, 4]` (la enfermería sigue en `[3, 2, 1]`); `config/centro_cumplidor.toml`: `[15, 15, 6]` → `[14, 14, 6]`. `tests/data/centro_4_6b.toml` guarda el centro de antes para los tests de reproducción.
- Registro (sección de la 4.6c con las sensibilidades, el veto, el perfil por mes, enero y el cumplidor), especificación y notebook 04 con la plantilla nueva.

**Conceptos**

- **La ventana representa lo que mide el objetivo.** Los objetivos del SAS son medias anuales: una réplica por mes hace que la media de las réplicas sea la del año. El IC entre réplicas incluye la variación entre meses y es conservador.
- **Números comunes con fechas.** El hijo m de la semilla y su fecha son la réplica m para todos los candidatos; el hijo i es el mismo pidas 10 o 12, así que enero reproduce bit a bit la réplica 0 de la 4.6b.
- **Una normalización que no es idempotente.** `dataclasses.replace` vuelve a pasar por `__post_init__`, que normaliza los factores otra vez y los mueve en el último bit; por eso la fecha se cambia sin reconstruir el perfil.
- **Escalones de la regla.** Con una plantilla de números enteros, el paso de 5 a 4 médicos de noche lleva la ocupación nominal de 0,68 a 0,85 (0,93 en enero): el reloj A anual salta de 28 a 42 min y no hay nada en medio.
- **Comprobar no es elegir, pero puede vetar.** Una plantilla que solo pasa con la semilla de ajuste está en el borde por azar. Si la comprobación interviene en la elección, deja de ser independiente y hace falta otra semilla.
- **Las colas se arrastran entre turnos.** Con dos enfermeras de mañana, la cola de la mañana llega a la noche aunque la noche no cambie: la regla del día medio no lo ve.

**Decisiones**

- Opción (a): una réplica por mes, desde el primer lunes, con los mismos 14 días, calentamiento, día de vaciado y regla de elección.
- Decisión 41 revisada: la semilla de comprobación (2027) puede vetar la elegida con la de ajuste (2026), y entonces se toma la siguiente candidata que pase con las dos; la confirmación independiente pasa a 2028.
- Primera parada (la regla estricta, `[2, 2, 1]` + `[12, 11, 4]`, con enero en 123,9 min, censurados en enero y el pretriaje de noche peor): se siguió la regla, porque las alarmas eran del chat y el resultado era coherente. Segunda parada: `[2, 2, 1]` falló el pretriaje con 2027 (15,16 \[10,61; 19,71\]) y el veto dejó `[3, 2, 1]`.
- Plantilla igual todo el año: enero cerca de la saturación queda escrito como rasgo conocido; el refuerzo de invierno, para versiones posteriores.
- El cumplidor se decide con días enteros sumados en las réplicas.

**Resultados**

| Medida | Valor |
| --- | --- |
| Centro de la 4.6b con la ventana anual | Pretriaje 6,78 \[5,49; 8,06\]; reloj A de los niveles 2 a 5, 27,75 \[19,12; 36,38\]: fuera por abajo (la predicción del chat, 26–36) |
| Enfermería, sensibilidad con 2026 | `[3, 3, 1]` 3,54 ✗; `[3, 2, 1]` 6,78 ✓; `[2, 2, 1]` 13,21 ✓ (la regla la elige); con 2027, `[2, 2, 1]` 15,16 ✗ (vetada) y `[3, 2, 1]` 7,86 ✓ |
| Médicos, sensibilidad con `[3, 2, 1]` | Solo `[12, 11, 4]` pasa (42,10 \[28,02; 56,18\], u = 0,85); `[12, 11, 5]` 27,75 y `[11, 11, 4]` 50,23 con un IC de 44,87 de ancho |
| `[3, 2, 1]` + `[12, 11, 4]` con 2026 / 2027 / 2028 | Pretriaje 6,78 / 7,86 / 7,76; reloj A 42,10 / 43,29 / 41,20; % sobre Manchester 16,13 / 16,79 / —; censurados 8 en enero (0,20 %) / 0 / 0 |
| Reloj A por mes (2026) | Enero 105,2, febrero 58,7, agosto 24,6 (el más bajo); con 2027, enero 78,6 y noviembre 62,3 |
| Pretriaje de noche, ventana anual | `[3, 2, 1]` 15,6 min (enero 23,8); `[2, 2, 1]` 18,4 (enero 38,7) |
| Cumplidor | `[14, 14, 6]`: 1/144, 0/144, 2/144 y 6/142 días fuera en los niveles 2 a 5; reloj A 15,65. Con `--ventana inicio`, la regla con enteros sigue eligiendo `[15, 15, 6]` |
| Notebook 04, ejecución principal (enero a abril) | Reloj A de los niveles 2 a 5, 82,0 min; nivel 5, 627; la semana del 19 al 25 de enero, 129 pacientes esperando médico a las 8:00 y 3897 min en el nivel 5 (sin abandono, que llega en el hito 5) |
| Tiempos | Una evaluación anual, 36 s; sensibilidad de la enfermería, 3 min 13 s, y de los médicos, unos 16 min; notebook 04, 6 min 15 s y 603 MB (rápido, 13 s) |
| Tests | 2.674 en 14 min 18 s (antes de la revisión); 241 de la app en 2 min 8 s, sin cambios |

**Comprobación de las versiones incorrectas**

Seis. V5 (el cumplidor con la media de proporciones) y V6 (elegir sin mirar la comprobación) fueron exactas. V2 a V4 se cumplieron con fallos de más explicados (sobre todo el espía). V1 (el día 1 del mes en lugar del primer lunes) no se cumplió a la primera: la fixture de julio y diciembre escribía los lunes a mano, así que no veía la función; se cambió para tomar las fechas de `window_start_dates` y la repetición se cumplió. La tabla completa está en «Tests y validación».

**Revisión**

Dos ajustes. La CLI no aplicaba el veto: `calibracion sensibilidad` imprimía «Elección: \[2, 2, 1\]», contra la plantilla escrita; se añadió `--comprobacion SEMILLA`, que evalúa solo las candidatas que hacen falta, y los comentarios de `centro.toml` usan ese comando. Y una frase en el registro, la especificación y el notebook: los 3897 min del nivel 5 en la peor semana de enero no son realistas porque el modelo aún no tiene abandono sin ser visto.

**Lecciones aprendidas**

- Las alarmas de un prompt son para detectar un resultado roto: cuando saltan, se mira el resultado antes de obedecerlas o descartarlas.
- Una plantilla que pasa solo con una semilla está en el borde; la semilla de comprobación sirve para descubrirlo, y si decide, hace falta otra.
- Un valor recalculado (la normalización del perfil) puede no ser idempotente: para comparar bit a bit, no reconstruir.
- Una fixture con los valores esperados escritos a mano no prueba la función que los calcula: la V1 lo destapó.
- Un valor escrito en `config/` tiene que salir de un solo comando; si la regla cambia (el veto), la CLI cambia con ella.
- Una plantilla anual y un modelo sin abandono amplifican enero: el realismo de las colas largas depende de lo que el modelo todavía no tiene.

**Pendiente**

- Refuerzo de invierno (plantilla por mes en el motor y en la regla), para versiones posteriores.
- Hito 5: con el abandono, volver a mirar la semana del 19 al 25 de enero de la semilla 2026.
- Menor: la normalización del perfil de llegadas no es idempotente (`dataclasses.replace`).
- `fecha_inicio` es el 5 de enero: las ejecuciones por defecto caen en el mes de más carga (ver la pestaña de la app).
