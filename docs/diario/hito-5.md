# Diario · Hito 5 — Cierre del flujo

Abandono, destinos y espera de cama: el motor deja de tener colas que no se cortan nunca y pacientes que solo salen con alta o ingreso. Especificación y anexo en [docs/specs/hito-5.md](../specs/hito-5.md); decisiones en los ADR [0067](../decisiones/0067-ruido-de-triaje-y-re-triaje-a-la-v2.md) a [0079](../decisiones/0079-ocho-tareas-en-orden-y-etiqueta-v0-5-hito5.md).

## 2026-11-11 · Tarea 5.1 — Motor con pacientes a mano

**Qué se hizo:** el catálogo versión 4 y su esquema; el abandono desde tres sitios con su empate, los cuatro destinos y la espera de cama en el box y en el pasillo; las invariantes nuevas. Todo con pacientes cuyos instantes se calculan a mano, sin perfiles.

**Qué aprendí:**
- En SimPy, el orden de los eventos de un mismo instante es la prioridad y después el orden de creación. Una regla de empate («si le dan el recurso en el instante en que vence su paciencia, se queda») no puede depender de quién se creó antes: necesita un evento con prioridad propia, `Deadline`, que va después de todo lo demás de su instante.
- «El recurso o la paciencia, lo que llegue antes» es un evento de condición (`request | deadline`). La petición que pierde se cancela.
- Una espera que debe acabar con dos eventos juntos (`bed_assigned` y `patient_departed`) se escribe como `timeout` del propio paciente: así nada se cuela entre los dos, ni siquiera un desalojo en el mismo instante.

**Qué costó o falló:**
- El plazo que vence durante el triaje no estaba en la especificación: nadie abandona en el triaje, pero la paciencia sigue corriendo. Se decidió al aprobar el plan: al acabar el triaje se va, salvo que reciba box y médico en ese instante.
- La revisión encontró un `KeyError` con logs que mezclan versiones (`a23e910`).

**Preguntas abiertas:**
- Dos plazos en el mismo instante exacto se resuelven por orden de llegada. Es de probabilidad 0 con sorteos continuos, pero ¿y en un escenario con tiempos redondeados?

**Enlaces:** PR #98 · [ADR 0070](../decisiones/0070-paciencia-lognormal-por-nivel-real.md) · [ADR 0073](../decisiones/0073-catalogo-version-4.md) · [SimPy, eventos de condición](https://simpy.readthedocs.io/en/latest/topical_guides/events.html)

## 2026-11-11 · Tarea 5.2 — Perfiles del abandono, los destinos y la espera de cama

**Qué se hizo:** `[abandono]`, `[destinos]` e `ingreso` por motivo en `perfiles.toml`; `[camas]` en `centro.toml`; las probabilidades exactas del destino y sus marginales de un año, sin simular, y el muestreador.

**Qué aprendí:**
- Una logística multinomial reparte el 100 % entre destinos con unas odds frente a una referencia (el alta). Los odds ratios multiplican odds, no suman puntos: subir el ingreso baja un poco el traslado y el exitus.
- Gumbel-max sirve igual para cuatro destinos que para 17 motivos: gana el mayor log odds + g. Si cambia un odds ratio, solo cambian los pacientes que entran o salen de ese destino.
- El factor común se aplica a las odds binarias de cada partida, no a las odds frente al alta, que dependen de las otras bases.

**Qué costó o falló:**
- Los odds ratios de partida no cuadraban con el SAS ni concentraban el exitus en las paradas: Pedro los cambió en el plan (ingreso 1,5 y exitus 15).
- El primer piloto del subagente `mutante`: funcionó en paralelo (unos 5 min frente a 12), pero el tipo, creado a mitad de sesión, no existía hasta la siguiente, y dos informes contaron mal los tests.

**Preguntas abiertas:**
- La base del exitus es del 0,001937 %: ¿cuántos pacientes hacen falta para ver su efecto en una simulación?

**Enlaces:** PR #99 · [ADR 0071](../decisiones/0071-cuatro-destinos-con-logistica-multinomial.md) · Agresti, *An Introduction to Categorical Data Analysis*

## 2026-11-11 · Tarea 5.3 — El modelo del hito 5 en el motor

**Qué se hizo:** el motor elige el modelo por los bloques de los ficheros; `child_streams(seed, 10)`; el ground truth del desenlace (65 columnas) y `run.json` versión 3; la CLI y las huellas del hito 5 con los ficheros de `tests/data`.

**Qué aprendí:**
- Cada hijo de `child_streams` depende solo de su índice: pedir 10 da los mismos 8 primeros que pedir 8. Por eso el hito 5 no cambia ni un bit de lo que ya se sorteaba.
- Para que la huella de un formato no cambie al añadirle un campo, el campo nuevo se omite cuando vale `None`.

**Qué costó o falló:**
- La regla del triaje tenía un hueco: con «max(plazo, fin del triaje)» siempre, un motor que ignorase el plazo esperando enfermera la pasaba. Se vio al escribir la predicción de una versión incorrecta (`0c20622`).
- La «tercera regla de Pedro»: nadie puede seguir esperando sin ser visto al final con su instante de abandono antes del horizonte.

**Preguntas abiertas:**
- Ninguna.

**Enlaces:** PR #102 · [ADR 0068](../decisiones/0068-bloque-del-hito-5-de-todo-o-nada.md) · [ADR 0076](../decisiones/0076-ground-truth-con-lo-sorteado-y-el-contrafactual.md)

## 2026-11-12 · Tarea 5.4 — Núcleo de la app y directo con la versión 4

**Qué se hizo:** métricas con censura, indicadores del abandono, la cama y el destino, filtros, «esperando cama» y el pasillo en el Replay y el consumidor, «Ver la verdad» del desenlace; «directo = batch» con la versión 4.

**Qué aprendí:**
- Un dato censurado es uno del que solo sabemos que duró al menos X. Con censurados, un cuantil no tiene un valor sino un rango: el mínimo con ellos en su cota y el máximo con ellos por encima de todos. Si coinciden, el valor es exacto; si no, se da la cota («≥»).
- Quien se va en el instante t no fue visto en t. Con el reloj justo en su máximo, su espera habría sido mayor: incumple.

**Qué costó o falló:**
- El motivo de la decisión 74, «más abandono nunca mejora el cumplimiento», era falso con el ejemplo de su propia pieza. Lo vio la revisión, y se corrigió el docstring.
- El notebook 06 emparejaba siete colores con las ubicaciones, y la ubicación nueva lo rompió. El plan buscó los lectores de las ubicaciones en el paquete, no en los notebooks; la primera N3 lo vio.

**Preguntas abiertas:**
- La carga prevista del modelo del hito 5 (#103): ¿cómo se prevé la ocupación de boxes cuando parte de ella es espera de cama?

**Enlaces:** PR #104 · [ADR 0074](../decisiones/0074-metricas-con-censura-del-abandono.md) · [ADR 0077](../decisiones/0077-estado-esperando-cama-con-marca-de-pasillo.md)

## 2026-11-12 · Tarea 5.5 — Páginas de la app del hito 5

**Qué se hizo:** las seis páginas enseñan el hito 5 cuando el log es de la versión 4, y los cinco pendientes del hito 4 quedan cerrados. Etiqueta `app-v0.3.0`.

**Qué aprendí:**
- Una página que enseña lo que el núcleo ya recorta no lo vuelve a filtrar: se repetiría la regla en dos sitios, y se separarían.
- En «Ver la verdad», lo que quien se va nunca alcanza no está «pendiente», está «no usado» (#105). Pendiente es lo que aún puede ocurrir.

**Qué costó o falló:**
- La tarea era de Codex y la hizo Claude Code (decisión de Pedro del 12 de noviembre).
- `curve_blocks` solo aceptaba las curvas de `CURVES`, y las de la cama viven fuera. Lo vio un test de Resultados.

**Preguntas abiertas:**
- El rendimiento de la app: la caché de los indicadores de nivel real y de `profiles_diff`.

**Enlaces:** PR #106 · [ADR 0078](../decisiones/0078-la-app-ensena-el-hito-5.md) · [incrementos de la app](../../app/docs/specs/incrementos.md#hito-5--abandono-destinos-y-espera-de-cama)

## 2026-11-12 · Tarea 5.6 — Calibración del abandono y la espera de cama

**Qué se hizo:** cinco objetivos nuevos, los mandos de la paciencia y de la cama, la plantilla medida de nuevo y los bloques del hito 5 en `config/`, que pasa a ser el modelo por defecto.

**Qué aprendí:**
- Con mandos acoplados, el orden importa: los destinos, que no dependen de las colas; luego la paciencia y la cama con la plantilla fija; luego se vuelve a medir la plantilla.
- La ley de Little da un derivado: los boxes que bloquean los ingresados son λ · W, y los boxes del centro son los del hito 4 más esos.
- Antes de tocar `config/` se congela lo antiguo: las copias del hito 4 en `tests/data/` demuestran que ninguna cifra del hito 4 cambia.

**Qué costó o falló:**
- Dos paradas. La primera: con 30 boxes, ningún k pasaba el abandono, porque los boxes eran el cuello de botella (52 min de espera de box frente a 16 de médico); Pedro decidió los boxes derivados. La segunda: k ≥ 4, lejos de lo que declaran las encuestas; tras un diagnóstico, Pedro lo aceptó como discrepancia estructural.
- La invariante `nobody_jumps_the_queue` daba falsos saltos con dos concesiones del mismo recurso en el mismo instante: se corrigió la invariante, no el motor.

**Preguntas abiertas:**
- La forma de la espera de cama: la media cuadra, pero el 78,7 % de los ingresados pasa más de 4 h, frente al 49,69 % (#109).
- k depende de la plantilla anual: con el refuerzo de invierno, hay que recalibrarlo (#108).

**Enlaces:** PR #107 · [ADR 0075](../decisiones/0075-calibracion-en-orden-con-un-mando-por-objetivo.md) · [registro de calibración](../calibracion/registro.md)

## 2026-11-12 · Tarea 5.7 — Notebook 05_cierre_del_flujo

**Qué se hizo:** el notebook del hito: abandono frente a saturación, destinos frente a G, boxes bloqueados y la ley de Little, la semana de enero antes y después, el contrafactual y el Kaplan–Meier de la paciencia. Primera tarea hecha en una sesión en la nube.

**Qué aprendí:**
- El Kaplan–Meier estima la supervivencia («seguir esperando») con censurados: el que ve al médico y el que sigue en el horizonte. Solo dice algo hasta el mayor tiempo observado, y con pocos en riesgo es ruidoso.
- El error típico de Greenwood dice cuándo un desvío del KM frente a la verdad no es azar.

**Qué costó o falló:**
- En la nube, GitHub solo responde por REST: `gh issue view` y `gh project` (GraphQL) dan 403 en el proxy, así que el tablero lo movió Pedro.

**Preguntas abiertas:**
- Ninguna.

**Enlaces:** PR #111 · [notebook 05](../../notebooks/05_cierre_del_flujo.ipynb) · Hernán y Robins, *Causal Inference: What If*, capítulo 1

## 2026-11-12 · Tarea 5.8 — Cierre del hito 5

**Qué se hizo:** los ADR 0067 a 0079, este diario, el diseño al día, el manual de la app con un recorrido del hito 5, el balance del hito y la skill `cerrar-hito`.

**Qué aprendí:**
- Un ADR no se reescribe: el de cada decisión del hito llega al cierre con «Qué cambió al implementarla», y así se ve qué se decidió y qué hubo que ajustar.
- Una frase de motivo puede ser más fuerte que lo que la regla garantiza. «Más abandono nunca mejora el cumplimiento» sonaba bien, y el ejemplo de al lado la desmentía.

**Qué costó o falló:**
- Ejecuciones decía «Clínico» para el hito 4 y para el 5: el manual no podía explicar cómo distinguirlas sin un cambio en la app.

**Preguntas abiertas:**
- Las propuestas de velocidad del balance, por decidir.

**Enlaces:** PR de la 5.8 · [balance del hito](../specs/hito-5.md#balance-del-hito)

## Pedro sabe explicar

Los criterios del hito piden que Pedro sepa explicar estas ideas. Cada una, en pocas líneas, con las cifras del hito.

- **La censura en el cumplimiento (66,7 % frente a 100 %).** Tres pacientes de nivel 4 (máximo 120 min) se clasifican en el minuto 10. El primero ve al médico en el 40 (reloj C = 30), el segundo en el 100 (C = 90) y el tercero se va en el 160 (C = 150).
  - No sabemos cuánto habría esperado el tercero, pero sí que más de 150, así que incumplió: 2 de 3, el 66,7 %. Quitarlo daría un 100 %, como si irse mejorara el servicio.
  - Si se hubiera ido en el minuto 30 (C = 20), no sabríamos si lo habrían visto a tiempo: no cuenta (está censurado), y el cumplimiento sería 2 de 2.
  - Por eso la regla no garantiza que más abandono nunca mejore el porcentaje. Garantiza que irse nunca esconde un incumplimiento seguro: quien se va con C en su máximo o por encima incumple.
- **Por qué lo observado de los que se van no es su paciencia.** Es un sesgo de selección.
  - Lo que se observa es la espera de cada uno que se fue, y solo se van los que tenían poca paciencia. Esa espera describe a ese grupo, no a todos.
  - De los que ven al médico solo sabemos que su paciencia era mayor que su espera: son justo los más pacientes, y no aparecen en la muestra de los que se van.
  - Por eso la espera de los que se van (en la 5.7, 228 min de mediana en el nivel real 4) se queda muy por debajo de la paciencia de todos (534 min de mediana verdadera).
- **El Kaplan–Meier y el rango que identifica.** El KM usa también a los que no se van, como censurados, y por eso se acerca a la verdad: 504 min de mediana frente a 534. Pero solo estima hasta el mayor tiempo observado, y con menos de 10 en riesgo es ruido. Con k = 4 casi nadie espera tanto como la mediana de la paciencia: el abandono informa de la cola izquierda, no del centro.
- **El contrafactual.** El simulador sortea al llegar el destino de todos, también de quien se va, aunque no lo use. Así sabe lo que ningún hospital sabe: en la 5.7, de los 1.061 que se fueron, 55 habrían ingresado (5,2 %) y uno era grave de verdad.
- **Por qué el destino usa la gravedad real.** El médico atiende al paciente que tiene delante, no a su etiqueta: el nivel asignado decide la prioridad y la gravedad real decide la clínica (decisión 38). Un nivel 2 infratriado como 4 espera como un 4 e ingresa como un 2.
- **La ley de Little y los boxes derivados.** L = λ · W: los boxes ocupados de media por ingresados que esperan cama son los ingresos por minuto por la espera media. En la ventana anual de la 5.6, λ · W = 6,44. El hito 4 se calibró sin esos boxes bloqueados, así que el centro necesita los 30 de entonces más 6,44, redondeado: 36.
- **Por qué k = 4.** El abandono (1–4 %) y el reloj A de los niveles 2 a 5 (35–70 min) piden los dos una paciencia larga. Con k = 2 el abandono ya pasa (3,52 %), pero se va tanta gente que los atendidos esperan menos y el reloj A cae a 27,31, fuera de su horquilla. Con k = 4 los dos pasan (1,68 % y 35,31). El precio son medianas de 10 h en el nivel 4, frente a las 2 h que declaran los pacientes en una encuesta. Se acepta como discrepancia estructural: la encuesta mide lo que se declara, y el dato del SAS mezcla fugas y altas voluntarias.
- **Por qué la calibración va en orden.** Los mandos se influyen: la paciencia cambia la cola, la cama cambia los boxes libres, y los dos mueven el tiempo hasta el médico, que es el objetivo de los médicos. Ajustados a la vez, varias combinaciones darían lo mismo. En orden, cada mando elige con los anteriores fijos, con una vuelta como máximo.

## Reflexiones de Pedro
