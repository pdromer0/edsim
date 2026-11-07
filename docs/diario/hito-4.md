# Diario · Hito 4 — Perfiles clínicos

Especificación: [docs/specs/hito-4.md](../specs/hito-4.md); las tareas 4.8a, 4.8b y 4.8c, en [App web — incrementos](../../app/docs/specs/incrementos.md). Los anexos de las dos tienen el detalle de cada tarea.

## 2026-11-05 · Tarea 4.1 — Relojes, pretriaje y nivel 1 en la puerta

**Qué se hizo:** tres relojes hasta el médico (A, B y C) en `EpisodeRecord`, cumplimiento Manchester con la medida como parámetro y C por defecto, indicador de pretriaje y nivel 1 clasificado en la puerta, sin enfermera. Primera tarea con el plan aprobado en modo auto: el agente hace push y abre el PR.

**Qué aprendí:**
- Los tres relojes salen de los mismos instantes del log; lo que cambia es desde cuándo se cuenta, y con ello qué cola se juzga.
- Se puede cambiar un valor por defecto sin cambiar el significado: quien usaba el reloj A lo pide de forma explícita.
- Si cada llegada es nivel 1 con probabilidad p₁, las que llegan a la enfermera son un Poisson de tasa λ·(1 − p₁): el *thinning* del hito 2, al revés.
- El incumplimiento del nivel 2 era del reloj, no del centro: con A quedaba fuera 25 de 26 días; con C, 0.
- Escritor estricto y lector tolerante: así la tolerancia con los logs antiguos no tapa un fallo del motor.

**Qué costó o falló:**
- La puerta volvió imposible el escenario de un test de desalojo. La comprobación se movió al test unitario de `should_displace`, en lugar de borrarla.
- Un test nuevo encontró un fallo antiguo: `offered_load_by_pool` fallaba cuando nadie ocupaba un recurso.
- Los ajustes de la revisión del plan no llegaron al agente.

**Preguntas abiertas:**
- La política de versiones del catálogo de eventos (resuelta en la 4.5a).

**Enlaces:** PR #40 · [ADR 0039](../decisiones/0039-nivel-1-en-la-puerta.md) · [ADR 0040](../decisiones/0040-tres-relojes-y-cumplimiento-desde-la-clasificacion.md)

## 2026-11-05 · Tarea 4.2 — Perfiles, contexto, población y motivo

**Qué se hizo:** el subpaquete `profiles/`, suelto del motor: `config/perfiles.toml` y `ClinicalProfiles`, el contexto de la llegada, la población (banda, edad, sexo y medio) y los 17 motivos con una categórica log-lineal sorteada con Gumbel-max, con los pesos base derivados.

**Qué aprendí:**
- El peso base no es el reparto global: `base_weights_for` resuelve un punto fijo, como el *raking* de las encuestas. Sin derivar, la intoxicación saldría en un 2,99 % en lugar del 2,01 %.
- Con Gumbel-max, reforzar un motivo solo atrae pacientes hacia él; con la CDF inversa cambian también motivos que nadie ha tocado.
- Un χ² marginal no ve una relación conjunta rota: hay que probar el motivo dentro de cada banda.
- La potencia se calcula antes de escribir un test de detección.

**Qué costó o falló:**
- Seis de nueve predicciones de las versiones incorrectas fallaron en la primera ronda; cada fallo dijo qué test cubría qué.
- Los ajustes de la aprobación volvieron a llegar a medias, e hizo falta una ronda de revisión del PR. Desde la 4.3, el PR lleva una sección «Ajustes de la aprobación».

**Preguntas abiertas:**
- El menor esperado dentro de una banda depende de los pacientes sorteados en ella (resuelto en la 4.5b con un margen).

**Enlaces:** PR #41 · [ADR 0035](../decisiones/0035-solo-adultos-con-cuatro-bandas.md) · [ADR 0036](../decisiones/0036-perfiles-clinicos-aparte-del-centro.md) · [ADR 0037](../decisiones/0037-diecisiete-motivos-con-estado-y-pesos-derivados.md)

## 2026-11-05 · Tarea 4.3 — Gravedad latente y triaje

**Qué se hizo:** gravedad G por motivo y edad, triaje con ruido y sesgo cortado por umbrales derivados y escritos, nivel real, calidad del triaje y salto. Todo exacto: el reparto es una suma de Φ, cada umbral una raíz y la matriz una integral.

**Qué aprendí:**
- Lo que se recalcula al cargar absorbe los shocks: con los umbrales escritos, la disnea ×1,5 sube el nivel 2 asignado; recalculados, volvería al objetivo.
- Ruido y sesgo son identificables: el ruido sube los dos errores y el sesgo los reparte entre infra y sobretriaje.
- Una simulación no es un valor exacto: la tabla de la especificación salía de un millón de pacientes, con 0,8 puntos de error en la fila del nivel 1.
- Con menos de 5 esperados, la binomial exacta en lugar del χ².

**Qué costó o falló:**
- Un modelo puede pasar todos los tests y ser clínicamente raro: dos de cada tres paradas hacían cola en el triaje.
- Los ajustes se perdían en el diálogo de aprobación: «Yes, and use auto mode» aprueba sin texto. Desde la 4.4, «No, keep planning» con el texto.
- El hook Stop ejecutó los tests con una versión incorrecta aplicada: se aplican y se deshacen en el mismo turno.

**Preguntas abiertas:**
- La espera de las paradas que reciben nivel 2 (resuelta en la 4.6a).

**Enlaces:** PR #42 · [ADR 0038](../decisiones/0038-gravedad-latente-y-triaje-con-error.md)

## 2026-11-05 · Tarea 4.4 — Pruebas por tipo y duraciones por nivel real y motivo

**Qué se hizo:** cuatro tipos de prueba con probabilidad logística, resultado y respuesta; duraciones lognormales por nivel real con un factor k por motivo; modelos exactos y validación del muestreador.

**Qué aprendí:**
- La logística trabaja en odds: un odds ratio multiplica las odds y, en la escala del logit, se suma.
- El porcentaje del TOML no es el del paciente típico, sino el de G = 0: se eligió por su marginal del año, que es la que se lee clínicamente.
- Multiplicar una lognormal por k es multiplicar su mediana: el factor de la franja se puede aplicar al pedir.
- Un error que comparten el muestreador y lo exacto no lo ve la estadística, porque mueve también la hipótesis; solo lo ven los valores a mano.

**Qué costó o falló:**
- Una predicción fallida (V4) destapó un error de verdad: el modelo exacto tomaba σ sin k. Se corrigió en un commit aparte.
- Un test de integración que usa las funciones como referencia comprueba el cableado, no las fórmulas.

**Preguntas abiertas:**
- La carga del médico sube un 5 % frente al provisional (32,38 frente a 30,84 min): la absorbió la calibración.

**Enlaces:** PR #43 · [ADR 0042](../decisiones/0042-pruebas-de-cuatro-tipos-en-una-ronda.md)

## 2026-11-06 · Tarea 4.5a — El ClinicalSampler en el motor

**Qué se hizo:** el `ClinicalSampler` une los tres muestreadores con ocho flujos y entra en el motor por el punto inyectable del hito 3. Catálogo versionado (1 provisional, 2 clínico), invariantes `door`, `schema_version` y `clinical`, y ground truth clínico. El provisional no cambia ni un bit.

**Qué aprendí:**
- El motor depende de un contrato, `sampler(arrival) → PatientDraws`, no de un modelo.
- Lo que depende del instante de la simulación no se sortea al llegar: se sortea la base y se transforma al pedir.
- Lo que ve el hospital va al log; G, nivel real y calidad, solo al ground truth. Un catálogo cerrado evita la fuga.
- La igualdad bit a bit con el muestreador directo prueba el cableado mejor que cualquier χ².

**Qué costó o falló:**
- Las comprobaciones clínicas mostraron boxes saturados (+24 % de tiempo de box) y el 44 % de las paradas en la cola del triaje, con todos los tests en verde.
- Un fixture generado por el motor arrastró un error a tests que no lo probaban, y fallaron de más.

**Preguntas abiertas:**
- Boxes como cuello de botella y paradas en la cola del triaje (resueltas en la 4.6a).

**Enlaces:** PR #44 · [ADR 0043](../decisiones/0043-sorteos-sincronizados-con-gumbel-max.md) · [ADR 0044](../decisiones/0044-modelo-clinico-por-defecto-en-el-cierre.md)

## 2026-11-06 · Tarea 4.5b — Ejecuciones clínicas, `motor simular --perfiles` y `perfiles validar`

**Qué se hizo:** CSV del ground truth clínico de 57 columnas, que va y vuelve bit a bit; `run.json` versión 2 con el modelo y la huella de los perfiles; `simulate_run` con perfiles; `motor simular --perfiles` y `perfiles validar`.

**Qué aprendí:**
- Una ejecución reproducible guarda copia y huella de todo lo que la generó y se carga desde la copia.
- Versionar un formato en disco: se escribe la versión nueva y se leen las dos, cada una con su significado; los valores por defecto nunca rellenan claves que faltan.
- Un mínimo calculado con valores esperados no basta si la comprobación usa recuentos observados: hace falta un margen con su probabilidad.
- Una batería de cuatro pruebas al 1 % tiene hasta un 4 % de falsas alarmas conjuntas.

**Qué costó o falló:**
- Las predicciones de «pasa» fallan más que las de «falla»: muchos tests dependen indirectamente de lo que se rompe (V11, V13).

**Preguntas abiertas:** ninguna nueva; las dos de la 4.5a pasan a la 4.6.

**Enlaces:** PR #45 · [nota de la ADR 0032](../decisiones/0032-ejecuciones-en-carpetas-reproducibles.md)

## 2026-11-06 · Tarea 4.6a — Paradas y espera de resultados fuera del box

**Qué se hizo:** la parada pasa al 0,3 % con una gravedad alta y poco dispersa, con la cascada de derivados rederivada; los niveles 4 y 5 esperan los resultados fuera del box, con el evento `box_released` del catálogo versión 3.

**Qué aprendí:**
- Un valor orientativo sin dato se elige por criterio: se escribe la condición y una función busca el menor valor que la cumple.
- Los derivados dependen unos de otros y se rederivan en cascada.
- El cuello de botella se mueve: soltar el box baja su tiempo un 23 % y deja la plantilla como el mando que mueve las esperas.
- Una clave opcional conserva el significado antiguo: si falta, vale `[]`, no el valor nuevo de `config/`.

**Qué costó o falló:**
- Codex encontró un fallo real en `_variant_bytes`: con listas de otra longitud, `[]` dejaba `[4, 5]` sin avisar.
- Antes de predecir sobre una invariante hay que mirar qué reconstruye del log (V4 dio 1.735 violaciones).

**Preguntas abiertas:**
- El pretriaje depende de la enfermería de triaje, que el único mando de la calibración no mueve (resuelto en la 4.6b).

**Enlaces:** PR #46 · [ADR 0045](../decisiones/0045-espera-de-resultados-fuera-del-box.md) · [ADR 0046](../decisiones/0046-parada-a-la-puerta.md)

## 2026-11-06 · Tarea 4.6b — Calibración de la enfermería de triaje y de los médicos

**Qué se hizo:** `config/objetivos.toml`, la regla de la plantilla equivalente, `calibracion evaluar` y `calibracion sensibilidad`, la primera calibración (`[3, 2, 1]` y `[12, 11, 5]`), el centro cumplidor y el registro de calibración. Codex desacopló a la vez los tests de la app de la plantilla, en otro worktree.

**Qué aprendí:**
- Un número por mando: personal = ⌈carga / u⌉. La búsqueda es de una dimensión y se explica sola.
- Mandos separables: con la misma semilla, cambiar médicos no cambia ni un pretriaje.
- Un día de vaciado evita la censura de los que más esperan al final de la ventana.
- Se elige con una semilla y se comprueba con otra; una comprobación nunca elige.

**Qué costó o falló:**
- El reloj A del nivel 3 no lo mueve ningún mando: pasó a comprobación, con la causa escrita, después de medir la sensibilidad.
- El cumplidor quedó justo en el borde del 10 % y se comparaba con decimales (resuelto con enteros en la 4.6c).
- Una cifra del anexo 4.5a era el reloj A con la etiqueta de otro.

**Preguntas abiertas:**
- Pretriaje de noche con una sola enfermera; circuitos separados para los niveles 4 y 5.

**Enlaces:** PR #48 · [ADR 0041](../decisiones/0041-centro-realista-calibrado-con-dos-mandos.md) · [registro de calibración](../calibracion/registro.md)

## 2026-11-06 · Tarea 4.7 — Notebook 04 de perfiles clínicos

**Qué se hizo:** `notebooks/04_perfiles_clinicos.ipynb`, con el cumplimiento por nivel real, los clasificados tarde, el acoplamiento de Gumbel-max frente a la CDF inversa y una variante con el reparto del SAS en adultos.

**Qué aprendí:**
- El coste del infratriaje se mide en tiempo: por nivel asignado se mide al hospital; por nivel real, al paciente.
- Si al clasificarse ya pasó el máximo, ningún médico puede hacerlo cumplir con el reloj A: el 45,5 % de los niveles 2.
- El acoplamiento mínimo entre dos repartos es la distancia de variación total, y Gumbel-max la alcanza cuando solo crece un peso.

**Qué costó o falló:**
- El reloj A crecía con el horizonte. Descompuesto por bloques y con la carga fija, no era el calentamiento: la calibración medía la primera quincena de enero, el mes de más carga.

**Preguntas abiertas:**
- Recalibrar con una réplica por mes (la 4.6c).

**Enlaces:** PR #49 · [ADR 0038](../decisiones/0038-gravedad-latente-y-triaje-con-error.md) · [ADR 0040](../decisiones/0040-tres-relojes-y-cumplimiento-desde-la-clasificacion.md)

## 2026-11-07 · Tarea 4.6c — Recalibración con la ventana anual

**Qué se hizo:** una réplica por mes, desde el primer lunes, para que la media sea la del año; la semilla de comprobación puede vetar; el cumplidor con días enteros. El centro base queda con `[3, 2, 1]` y `[12, 11, 4]`, y el cumplidor, con `[14, 14, 6]`.

**Qué aprendí:**
- La ventana de la calibración tiene que representar lo que mide el objetivo: los del SAS son medias anuales.
- Comprobar no es elegir, pero puede vetar; si la comprobación interviene, hace falta otra semilla (2028).
- Con plantillas enteras hay escalones: de 5 a 4 médicos de noche, el reloj A anual salta de 28 a 42 min y no hay nada en medio.
- Una normalización que no es idempotente impide comparar bit a bit si se reconstruye el objeto.

**Qué costó o falló:**
- La regla eligió `[2, 2, 1]` y la semilla 2027 lo vetó: el agente paró dos veces y decidí con las tablas delante.
- La CLI no aplicaba el veto e imprimía otra elección: se añadió `--comprobacion`.
- Una fixture con las fechas escritas a mano no veía la función que las calcula.

**Preguntas abiertas:**
- Refuerzo de invierno; la semana del 19 al 25 de enero con abandono, en el hito 5.

**Enlaces:** PR #50 · [ADR 0041](../decisiones/0041-centro-realista-calibrado-con-dos-mandos.md)

## 2026-11-07 · Tarea 4.8a — Núcleo de la app con perfiles clínicos

**Qué se hizo:** en `runs/`, sin tocar `app/`: resultados con modelo y perfiles, los tres relojes, la verdad clínica, el perfil observable, la carga prevista con el muestreador clínico en dos partes y los tres tipos de emparejamiento.

**Qué aprendí:**
- Un núcleo que otra parte ya usa cambia de forma aditiva, y así núcleo y páginas van en tareas y agentes distintos.
- Lo lento se separa de lo que cambia: la carga prevista no depende de la plantilla.
- El trabajo llega después que el paciente: la reevaluación desplaza carga a la tarde y la noche.

**Qué costó o falló:**
- La validación del plan encontró que el recuento clínico construía la verdad sin días y habría fallado con `IndexError`.
- Un test que compara una función con la misma llamada que hace ella no prueba nada.

**Preguntas abiertas:**
- `knob_loads` reparte la carga por la llegada y no ve el desfase: la noche queda un 15 % por debajo.

**Enlaces:** PR #51 · [App web — incrementos](../../app/docs/specs/incrementos.md)

## 2026-11-07 · Tarea 4.8b — Páginas de la app con perfiles clínicos

**Qué se hizo:** Codex llevó los perfiles a las seis páginas: selector y resumen de perfiles en Simular, tres relojes en Resultados, perfil y «Ver la verdad» en Episodios, tipos de emparejamiento en Comparar y sala de resultados en Replay. Etiqueta `app-v0.2.0`.

**Qué aprendí:**
- La clave de una caché es lo que cambia la respuesta: sin la plantilla en ella, cambiar un médico cuesta milisegundos.
- La app pudo pedir el reloj C sin tocar el núcleo, con una copia de los resultados en su caché.
- Nivel asignado en la interfaz; el real, solo como verdad.

**Qué costó o falló:**
- Una promesa de la especificación no se cumplía: la opción Provisional de Simular seguía editando las tablas provisionales del centro, y la separación de la 4.9 habría roto `tests-app`. Nació la 4.8c.

**Preguntas abiertas:**
- Cumplimiento por nivel real y diferencias de perfiles clave a clave en la app.

**Enlaces:** PR #53 · [APP-0004](../../app/docs/decisiones/APP-0004-perfiles-de-solo-lectura.md)

## 2026-11-07 · Tarea 4.8c — Preparación del cierre en la app

**Qué se hizo:** Codex dejó Simular solo con el modelo clínico, mostró los errores de las claves que el editor no enseña, los valores ausentes como «—», el manual de usuario al día y un test de contrato con la 4.9, marcado `xfail` estricto. Etiqueta `app-v0.2.1`.

**Qué aprendí:**
- Un contrato entre dos tareas se puede escribir como test: un `xfail` estricto falla si pasa sin que nadie quite la marca.
- Un bloqueo siempre dice por qué: cada error tiene que verse, aunque su campo no esté en el editor.

**Qué costó o falló:**
- Al borrar los tests de un camino que desaparece se fue también la única aserción del aviso «No hay diferencias frente al centro base».
- El contrato cubría el flujo de Simular, no los fixtures: varios tests de la app seguían leyendo las tablas provisionales de `config/centro.toml`.

**Preguntas abiertas:**
- Un test del aviso «No hay diferencias» con los campos del editor clínico.

**Enlaces:** PR #54 · [APP-0005](../../app/docs/decisiones/APP-0005-simular-solo-clinico.md)

## 2026-11-07 · Tarea 4.9 — Cierre del hito 4

**Qué se hizo:** `config/centro.toml` pierde `[triaje]`, `[duraciones]` y `[pruebas]`, con un lector que los acepta como bloque opcional de todo o nada; el modelo clínico es el de por defecto en `motor simular` (`--provisional` para el otro) y el reloj C, en `runs/`. ADRs 0034 a 0047, notas en la 0017, la 0031 y la 0032, y este diario.

**Qué aprendí:**
- Un bloque opcional «todo o nada» se valida en dos sitios: el lector, con un error por clave, y la construcción directa, que no deja mezclar campos con y sin valor.
- Un valor por defecto escondido cambia el significado en silencio; sin bloque, `None`, y el modelo que lo necesita falla pronto, antes de escribir nada.
- Mover un fichero de configuración mueve también lo que lo usa: `motor validar` compartía el centro con `motor simular`, y un test de la app usaba el reloj por defecto sin decirlo.
- Cuando un CSV lleva la huella de su configuración, el mismo log da otro CSV si cambian los bytes del fichero, aunque no cambie ningún valor.

**Qué costó o falló:**
- Un test de la CLI en `test_runs.py` se quedó fuera del commit del modelo por defecto y quedó en rojo durante dos commits: buscar con grep todas las llamadas, no solo las del fichero de la CLI.
- El orden de los commits importa para que cada uno pase su área: la CLI tuvo que ir antes que el centro sin bloque.

**Preguntas abiertas:**
- El hito 6 está en preparación, sin especificación exportada todavía.

**Enlaces:** PR #55 · ADRs 0034 a 0047 · [ADR 0044](../decisiones/0044-modelo-clinico-por-defecto-en-el-cierre.md)

## Reflexiones de Pedro
