# Hito 4 — Perfiles clínicos

## Objetivo y alcance

Al terminar el hito 4, cada paciente de EDsim llega con edad, sexo, medio de llegada y motivo de consulta, tiene una gravedad real que el hospital no ve y recibe un nivel de triaje con error. Sus pruebas y duraciones dependen de esa gravedad y de su motivo. Todo sale de un muestreador clínico que se enchufa en el punto de muestreo inyectable del hito 3, sin cambiar la lógica de colas, recursos ni turnos. El centro base queda calibrado, por primera vez, contra datos españoles observados: pretriaje y tiempo hasta el médico.

Dentro del alcance

- Población de adultos (15 años o más): banda y edad, sexo y medio de llegada, condicionados al contexto (franja, tipo de día y estación).
- Los 17 motivos de consulta del catálogo como perfiles, con una categórica log-lineal sorteada con Gumbel-max.
- Gravedad latente G y triaje ordinal con ruido y sesgo (G + ε cortada por umbrales calculados); nivel real, calidad del triaje e infra y sobretriaje en el ground truth.
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
| Triaje ordinal | Nivel asignado = umbrales(G + ε); nivel real = umbrales(G). Los umbrales se calculan para dar el reparto asignado objetivo |
| Infra y sobretriaje | Asignado menos o más urgente que el real. Con ruido 0,32 y sesgo −0,08 salen un 10,1 % y un 6,3 %; el 31 % de los niveles 1 reales se asigna como 2 |
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

**Gravedad** (flujo 7, una normal z por paciente): `G = media_motivo + por_edad[b] + desviacion_motivo × z`. G se mide en desviaciones típicas de la población de referencia: 0 es la gravedad media de un adulto. Más G es más grave.

**Triaje** (flujo 1, una normal zₑ por paciente): `ε = sesgo + ruido × zₑ`. El nivel asignado es G + ε cortada por los umbrales c₁ > c₂ > c₃ > c₄ (nivel 1 si supera c₁, nivel 5 si queda por debajo de c₄). El nivel real es G cortada por los mismos umbrales.

**Umbrales calculados, no escritos.** Los umbrales se calculan para que el reparto *asignado*, sobre la mezcla de G + ε de toda la población, sea el objetivo del TOML (adultos de Emergencias 2013: 0,4 / 12,1 / 33,6 / 52,6 / 1,4 %). Se calculan una vez al cargar los perfiles, con una muestra grande de pacientes de referencia o numéricamente sobre la mezcla, y se comprueban con un test. Como el ruido ensancha la distribución observada, el reparto real es más estrecho que el asignado: el ruido «inventa» niveles 1 y 5.

**Calibración del error.** Con G normal estándar y el reparto de adultos, un ruido de 0,32 y un sesgo de −0,08 reproducen un 10,1 % de infratriaje y un 6,3 % de sobretriaje (el dato más reciente, de Asturias). Un ruido simétrico sin sesgo daría más sobretriaje que infratriaje. Con esos valores, el 31 % de los niveles 1 reales se asigna como 2 y el 17 % de los niveles 5 reales sube a 4: los errores se concentran en los niveles raros, de franjas estrechas.

| Nivel real \\ asignado (%) | 1 | 2 | 3 | 4 | 5 |
| --- | --- | --- | --- | --- | --- |
| 1 | 68,7 | 31,3 | 0 | 0 | 0 |
| 2 | 1,3 | 76,7 | 22,0 | 0 | 0 |
| 3 | 0 | 6,6 | 75,3 | 18,1 | 0 |
| 4 | 0 | 0 | 7,2 | 91,4 | 1,4 |
| 5 | 0 | 0 | 0 | 17,1 | 82,9 |

Calculado con un millón de pacientes, G normal estándar; con la mezcla de motivos real, la tarea 4.3 lo vuelve a medir.

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

El TOML da p\_{t,m}, el porcentaje para un adulto de gravedad media de cada motivo (por ejemplo, analítica 40 % en dolor abdominal: a = logit(0,40) = −0,41), y dos odds ratios por tipo. Con b = 1,2 y c = 0,8, la probabilidad a gravedad media es 40,1 % en un adulto y 59,9 % en un mayor. «Mayor» son las bandas de 65 años o más.

**Resultado y respuesta.** Cada tipo sortea también su resultado (normal o alterado, otra logística sobre G) y su tiempo de respuesta (lognormal por mediana y p90, con un factor por franja). El paciente espera a la prueba más lenta de las pedidas; con ninguna pedida no hay ronda. El resultado no lo usa nadie todavía: lo usará el destino del hito 5, y se sortea ya para que el flujo de pruebas no cambie de consumo entre hitos.

**Consumo fijo** (flujo 3): tres sorteos por tipo (pedir, resultado, respuesta), doce por paciente, se pida o no cada prueba.

**En el log**, un solo pedido y un solo resultado por ronda, con la lista dentro: `test_ordered` lleva `pruebas` (por ejemplo `["analitica", "ecg"]`) y `test_resulted` llega con la más lenta y lleva `resultados` (por ejemplo `{"analitica": "alterado", "ecg": "normal"}`). El orden de los eventos no cambia. El tiempo de respuesta de cada tipo va al ground truth.

**Duraciones** (flujo 2, tres normales por paciente: triaje, valoración y reevaluación). La parametrización es la del hito 3: μ = ln(mediana) y σ = (ln p90 − ln mediana) / z₀,₉, con z₀,₉ = 1,28155. La valoración y la reevaluación tienen una base por nivel real, y cada motivo aplica un factor sobre la mediana:

```latex
\mu = \ln(k_m \cdot \text{mediana}_{n}), \qquad \sigma = \sigma_{n}, \qquad E[S] = k_m \cdot E[S_{n}]
```

Multiplicar la mediana por k desplaza la lognormal sin cambiar σ, y la media también queda multiplicada por k. Con base 20 y 45 minutos, la media es 24,43; con k = 1,2 es 29,32. El triaje tiene una sola lognormal para los niveles 2 a 5; el nivel 1 no consume triaje. Las duraciones son orientativas y fijas durante la calibración del hito 4 (ver «Calibración»).

## El muestreador clínico en el motor

El `ClinicalSampler` tiene el mismo contrato que el `ProvisionalSampler` del hito 3, `sampler(arrival) → PatientDraws`: el motor sigue leyendo nivel, duraciones, pruebas y destino, y el resto de campos solo los copia a los payloads y al ground truth.

```python
class ClinicalSampler:
    """Same contract as ProvisionalSampler: sampler(arrival) -> PatientDraws."""

    def __call__(self, arrival):
        ctx = self._calendar.context(arrival.time)  # shift band, day type, season
        person = self._population(ctx)  # stream 5: 4 Gumbel + 3 uniforms
        reason = self._reason(ctx, person)  # stream 6: 17 Gumbel draws
        g = self._severity(reason, person)  # stream 7: 1 normal
        level, true_level = self._triage(g)  # stream 1: 1 normal (noise)
        tests = self._tests(g, reason, person, ctx)  # stream 3: 3 draws per test type
        times = self._durations(true_level, reason)  # stream 2: 3 normals
        disposition = self._disposition(level)  # stream 4: 1 uniform (provisional)
        return PatientDraws(...)
```

**Flujos y consumo** (decisión candidata 43). `child_streams(seed, 8)` da los mismos cinco primeros hijos que `child_streams(seed, 5)`, porque cada hijo depende solo de su índice: las llegadas (flujo 0) no cambian ni un bit.

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

**Cambios en el motor**, pequeños y explícitos; la lógica de colas, recursos y turnos no cambia:

1. Payloads que el catálogo del hito 3 dejó para el hito 4: `patient_arrived` lleva `medio`; `patient_registered`, `edad` y `sexo`; `triage_completed`, `motivo` además de `nivel`; `triage_started`, `circuito`; `test_ordered`, `pruebas`; `test_resulted`, `resultados`.
2. El nivel 1 en la puerta: una rama en `patient.py` sin petición de enfermera.
3. `check_capacity`, la escalera de enfermeras y la identidad de utilización no cuentan los triajes con `circuito: "puerta"`; «nadie se cuela» se amplía al triaje (nadie adelanta en su cola salvo un nivel 1).

**Ground truth de episodios**, añadido a lo del hito 3: G, nivel real, calidad del triaje y salto en niveles, z de gravedad, motivo, banda y edad, pruebas pedidas con su resultado y su tiempo de respuesta por tipo. La paciencia llega en el hito 5.

**Modelo opcional durante el hito** (decisión candidata 44). `simulate_ed` y la CLI aceptan unos perfiles. Con ellos usan el `ClinicalSampler`; sin ellos, el `ProvisionalSampler`, y la app y `runs/` siguen funcionando sin cambios. El cambio de modelo por defecto y la separación de `centro.toml` (decisión candidata 36) se hacen en la tarea de cierre, cuando la app ya trabaje con perfiles. El `ProvisionalSampler` se queda para la validación del motor (M/G/1, escenario de tres boxes), que necesita un modelo sencillo con teoría conocida.

**Huellas.** Con el modelo clínico, el log y el ground truth cambian. Las huellas SHA-256 del modelo provisional cambian una sola vez, en la tarea 4.1, por el nivel 1 en la puerta y el campo `circuito`; su PR lo justifica. Después no deben cambiar en ninguna tarea del hito.

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
reparto_objetivo = [0.4, 12.1, 33.6, 52.6, 1.4]   # % asignado; los umbrales salen del código
ruido = 0.32                        # desviación del error, en unidades de G
sesgo = -0.08                       # negativo: tiende a infratriar
duracion = [5, 10]                  # [mediana, p90] en minutos, niveles 2 a 5

[duraciones]
valoracion = [[40, 90], [30, 70], [22, 50], [15, 35], [10, 25]]   # por nivel real
reevaluacion = [[15, 30], [12, 25], [10, 20], [8, 15], [6, 12]]

[pruebas.analitica]
respuesta = [60, 150]               # [mediana, p90] en minutos
respuesta_franja = [1.0, 1.1, 0.9]  # factor sobre la mediana
or_gravedad = 3.3                   # odds ratio por unidad de G
or_mayor = 2.2
alterado = { base = 30, or_gravedad = 2.5 }   # % alterado a gravedad media

[motivos.dolor_toracico]
nombre = "Dolor torácico"
peso_base = 5                       # derivado con base_weights_for
edad = [0.5, 1.0, 1.6, 1.6]
franja = [1.0, 1.1, 0.8]
dia = [1.0, 0.9]                    # laborable; fin de semana
estacion = [1.1, 1.0, 0.9, 1.0]     # invierno, primavera, verano, otoño
gravedad = { media = 0.6, por_edad = [-0.3, 0.0, 0.3, 0.5], desviacion = 0.9 }
pruebas = { ecg = 98, analitica = 90, radiografia = 70, imagen = 10 }   # % en adulto de gravedad media
duracion = 1.2                      # factor sobre la mediana de su nivel
```

**Reglas de `perfiles.toml`:**

- `ClinicalProfiles` inmutable, validado y normalizado al construirse, y `load_profiles(path)` con `tomllib`, como `CenterConfig`.
- Unidades clínicas en el fichero (porcentajes, minutos, factores, odds ratios); el código calcula pesos normalizados, umbrales, interceptos y μ y σ. Ningún número derivado se escribe a mano, salvo los pesos base, que escribe `base_weights_for` con un comentario.
- Factores opcionales: si faltan valen 1. Claves desconocidas prohibidas, con un error que nombra la clave y el motivo. Longitudes validadas: 4 bandas, 3 franjas, 2 tipos de día, 4 estaciones, 5 niveles y 4 tipos de prueba.
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
  severity.py            gravedad latente, umbrales calculados, triaje con error
  workup.py              pruebas por tipo, resultado y respuesta
  durations.py           lognormales por nivel real y motivo
  sampler.py             ClinicalSampler y PatientDraws ampliado
  validation.py          comprobaciones estadísticas del muestreador
src/edsim/calibration/
  __init__.py
  targets.py             objetivos.toml: Target, load_targets
  evaluate.py            réplicas, comparación con horquillas, días fuera
src/edsim/engine/        cambios acotados
  patient.py             nivel 1 en la puerta, payloads nuevos
  events.py              catálogo: circuito, medio, edad, sexo, motivo, pruebas, resultados
  engine.py              simulate_ed(..., profiles=None)
  analysis.py            triage_start_to_doctor y classified_to_doctor
  targets.py             cumplimiento con medida, pretriaje, nivel 1 sin porcentaje
  invariants.py          capacidad sin triajes de puerta, nadie se cuela en el triaje
  ground_truth.py        campos clínicos del episodio
  validation.py          M/G/1 con λ·(1 − p₁)
src/edsim/cli.py         --perfiles, perfiles validar, calibracion evaluar
notebooks/04_perfiles_clinicos.ipynb
tests/test_profiles_config.py, test_context.py, test_mixing.py, test_population.py,
      test_severity.py, test_workup.py, test_durations.py, test_sampler.py,
      test_profiles_validation.py, test_calibration.py, test_door_triage.py
```

`ProvisionalSampler` sigue en `engine/clinical.py` para la validación del motor. Sin dependencias nuevas: `tomllib`, NumPy y SciPy cubren la Gumbel, la logística y la búsqueda de umbrales. Los nombres de módulos los confirma el plan de cada tarea.

## Tests y validación

La filosofía es la del hito 3, por capas: valores a mano, versiones incorrectas con predicción y pruebas estadísticas con su potencia.

| Grupo | Qué comprueba |
| --- | --- |
| Perfiles | Carga del TOML de ejemplo y del real; factores opcionales neutros; errores con claves desconocidas, longitudes, porcentajes y medianas inválidos |
| Contexto | Franja en los bordes (7:59 y 8:00), tipo de día en el paso de domingo a lunes, estación por mes |
| Mezcla | Valor a mano (22,7 % de disnea en mayores en invierno); Gumbel-max con sorteos fijados a mano; reparto global de `base_weights_for` dentro de ±0,5 puntos; «con más disnea solo cambian los que pasan a disnea» |
| Triaje | Umbrales a partir del reparto; reparto asignado y real; infra y sobretriaje con IC binomial; orden clínico de gravedad por motivo; nivel 1 en la puerta con un escenario a mano |
| Pruebas y duraciones | logit(0,40) = −0,41; probabilidad por tramos de G; máxima de las pedidas; media lognormal 24,43 → 29,32 con el factor 1,2; cuantiles con la binomial, como en la tarea 3.1 |
| Muestreador | Consumo fijo por flujo; el paciente k es el mismo con otra plantilla y conserva sus z con otro parámetro clínico; llegadas idénticas a `iter_arrivals` |
| Motor | Payloads del catálogo, sin campos ocultos; invariantes con triajes de puerta; huellas del modelo provisional y del clínico |
| Relojes | Las tres medidas en un log a mano; cumplimiento con C; pretriaje; nivel 1 sin porcentaje; cumplimiento por nivel real |
| Calibración (slow) | Objetivos cargados con su fuente; evaluación con réplicas; semillas de ajuste y de comprobación distintas |
| CLI | Subcomandos nuevos, ficheros y código 2 ante errores de uso |

**Potencia.** El muestreador se prueba sin el motor, con 20 000 pacientes en décimas de segundo. Con el χ² por motivo, nivel 0,01 y Bonferroni entre 17, se detecta un 5 % que pasa a 6 % con una potencia del 99,7 %, pero un 5 % que pasa a 5,5 % solo con un 43 %. Cada prueba escribe qué tamaño de error ve. Los motivos raros (crítico, 0,5 %) necesitan comprobar que hay pacientes suficientes, para que el test no pase de forma vacía.

**Versiones incorrectas con predicción** (ejemplos; cada plan añade las suyas):

| Versión incorrecta | Predicción |
| --- | --- |
| Factores sumados en lugar de multiplicados | Falla el valor a mano y el χ² del contexto de mayores en invierno |
| Gumbel-max sin el logaritmo (w + g) | Falla el χ² de la mezcla en todos los contextos |
| CDF inversa en lugar de Gumbel-max | Pasan las frecuencias; falla «con más disnea solo cambian los que pasan a disnea» |
| Olvidar renormalizar con Gumbel-max | No falla nada: el argmax no depende de la escala (decisión de diseño) |
| Umbrales sobre G en lugar de G + ε | Falla el reparto asignado (más niveles 1 y 5); pasa el real |
| Pruebas con el nivel asignado en lugar de G | Pasan las pruebas marginales; falla solo el test sobre los infratriados |
| Resultado sorteado solo si se pide la prueba | Fallan los tests de independencia, no los estadísticos |
| Hora en UTC en lugar de +01:00 | Falla la franja en el borde de las 8:00 |
| Triaje de puerta contado como enfermera | Falla la capacidad con las enfermeras ocupadas |
| Prioridad de triaje por nivel completo (1 a 5) | Falla «los niveles 2 a 5 siguen en FIFO entre sí» |

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
| 38 | Gravedad latente normal y triaje ordinal G + ε con ruido y sesgo y umbrales calculados para el reparto asignado; la prioridad usa el nivel asignado, y duraciones y pruebas, la gravedad real | Modelo del diseño; reproduce el infra y sobretriaje publicados; hace medible el daño del infratriaje |
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
| 4.3 | Gravedad latente, umbrales calculados y triaje con ruido y sesgo; nivel real y calidad (38) | Claude Code | `feat/h4-triaje` | Reparto asignado, infra y sobretriaje en verde |
| 4.4 | Pruebas por tipo con resultado y respuesta (42); duraciones por nivel real y motivo | Claude Code | `feat/h4-pruebas` | Logísticas y lognormales validadas |
| 4.5 | `ClinicalSampler` en el motor como opción (44): payloads, catálogo, ground truth, `--perfiles`, `run.json` con la huella de los perfiles; `perfiles validar` | Claude Code | `feat/h4-muestreador` | Primer log con pacientes con perfil, sin invariantes violadas |
| 4.6 | `objetivos.toml`, `calibracion evaluar` y primera calibración de la plantilla (41); `centro_cumplidor.toml` | Claude Code | `feat/h4-calibracion` | Objetivos de ajuste dentro de horquilla y registro de calibración |
| 4.7 | Notebook `04_perfiles_clinicos.ipynb` | Claude Code | `feat/h4-notebook` | Notebook ejecutable de principio a fin en el CI |
| 4.8a | Núcleo de la app con perfiles (`runs/`) | Claude Code | `feat/h4-app-nucleo` | Ver «App web — incrementos» |
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

Solo una rama abierta a la vez. La revisión automática con `@codex review` se pide solo en las tareas críticas: en este hito, la 4.5 (el muestreador en el motor) y la 4.9 (el cambio de modelo por defecto).

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
