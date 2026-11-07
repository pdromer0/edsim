# App web — incrementos

Nov 5, 2026 · @Pedro

Cada hito añade a EDsim Lab lo nuevo del modelo, y esta pestaña especifica cada incremento: objetivo, cambios en el núcleo y en las páginas, tests, decisiones, tareas y anexo. La pestaña del hito solo lista las tareas de la app y enlaza aquí. La fase 1, cerrada con `app-v0.1.0`, sigue en App web — fase 1.

Esto cambia una idea de la decisión 31, que preveía documentar cada incremento en la especificación de su hito: el cierre del hito 4 añade una nota de actualización a la ADR 0031.

## Hito 4 — Perfiles clínicos

Especificación del hito: Hito 4 — Perfiles clínicos. Incremento de la app: tareas 4.8a (núcleo, Claude Code) y 4.8b (páginas, Codex), con la etiqueta `app-v0.2.0` al terminar.

### Objetivo y alcance

Al terminar el incremento, EDsim Lab simula con el modelo clínico del hito 4 y enseña lo que trae: quién es cada paciente (edad, sexo, medio y motivo), con qué nivel lo clasificaron frente a su nivel real, y los tiempos medidos con los tres relojes. Los perfiles se pueden ver y elegir, pero no editar.

Dentro del alcance

- Simular con perfiles: elegir el fichero de perfiles, ver su resumen y la carga prevista calculada con él.
- Las ejecuciones guardan el modelo usado y la huella de los perfiles; las ejecuciones antiguas, del modelo provisional, se siguen abriendo.
- Resultados con los tres relojes, el cumplimiento desde la clasificación, el pretriaje y el nivel 1 sin porcentaje.
- Episodios con edad, sexo, medio, motivo y pruebas; «ver la verdad» con G, nivel real, calidad del triaje y tiempos de respuesta por prueba.
- Comparar con el emparejamiento de los perfiles: mismos pacientes con otra plantilla, o mismos sorteos estándar con otros parámetros clínicos.

Fuera del alcance

- Editar perfiles en la app (decisión APP-0004): fase 2.
- Calibrar desde la app: la calibración vive en la CLI y en el notebook 04.
- Destino, abandono y boarding: incremento del hito 5.

Principios que se mantienen: capa fina (si una página necesita calcular algo, falta una función en el núcleo), los ficheros son la verdad, lo derivado sale del log y el ground truth solo aparece donde se muestra como verdad.

### Cambios en el núcleo (tarea 4.8a, Claude Code)

Todo lo que las páginas necesitan calcular vive en `src/edsim/runs/`, con tests, como en las tareas A.2a y A.3a. Los nombres exactos los confirma el plan.

**Adelantado a la tarea 4.5b.** `simulate_run` con perfiles y `run.json` en la versión 2 del formato (modelo, copia de `perfiles.toml` y su huella, lectura de la versión 1) se hacen en la tarea 4.5b del hito, porque `edsim motor simular --perfiles` escribe con `simulate_run` y no puede guardar la huella sin el formato 2. La 4.8a parte de ellos: la primera fila de la tabla queda como comprobación heredada (la CLI y la app dan el mismo log con los mismos perfiles).

**Sala de resultados (tarea 4.6a).** Con el modelo clínico, los pacientes de los niveles asignados 4 y 5 dejan el box al pedir pruebas y vuelven con los resultados (`box_released`, catálogo versión 3). `runs/_location` ya los muestra sin box, en `waiting_tests` mientras esperan y en `waiting_box` al volver, así que la app funciona sin cambios. Para la 4.8a y la 4.8b quedan un estado propio de la sala con su etiqueta («En box esperando pruebas» es inexacta), Episodios y Replay con los dos tramos de box, y `initial_box_wait` y `results_box_wait` en las tablas. La app no edita `espera_resultados_fuera`, y las variantes la conservan.

**Centro calibrado (tareas 4.6b y 4.6c).** `config/centro.toml` tiene desde la 4.6c la plantilla calibrada con la ventana anual (enfermería de triaje `[3, 2, 1]`, médicos `[12, 11, 4]`; en la 4.6b eran `[12, 11, 5]`), y hay un `config/centro_cumplidor.toml` con médicos `[14, 14, 6]` (`[15, 15, 6]` en la 4.6b). Con una plantilla igual todo el año, enero queda cerca de la saturación, y `fecha_inicio` es el 5 de enero: las ejecuciones por defecto de la app caen en el mes peor. Los tests de `app/tests` leen la plantilla del fichero copiado y ya no dependen de ella (PR #47, de Codex); los valores a mano que no dependen de `[recursos]` siguen siendo literales. Para la 4.8a y la 4.8b: la app sigue abriendo el centro base para editar variantes; mostrar el cumplidor como variante y los objetivos de `objetivos.toml` es una opción por decidir.

| Módulo | Cambio | Comprobación clave |
| --- | --- | --- |
| `service.py`, `store.py` | `simulate_run` acepta perfiles; `run.json` pasa a la versión 2 del formato, con el modelo (`provisional` o `clinico`), la copia de `perfiles.toml` y su huella; las ejecuciones de la versión 1 se siguen leyendo | La CLI y la app dan el mismo log con los mismos perfiles; una ejecución de la versión 1 se abre igual que antes |
| `summary.py` | Resumen de los perfiles: reparto esperado de motivos y de niveles asignados, porcentaje esperado de pruebas | Valores calculados a mano con un perfil pequeño |
| `offered.py` | La carga prevista usa el muestreador de la ejecución (provisional o clínico) para estimar los minutos de médico y de box por paciente | Con perfiles de un solo motivo coincide con el cálculo a mano |
| `metrics.py` | Los tres relojes; cumplimiento con el reloj C; pretriaje; nivel 1 solo con su tiempo | Los mismos números que `engine/targets.py` en un log a mano |
| `episodes.py`, `filters.py` | Edad, sexo, medio, motivo y pruebas en la tabla y en los filtros | Filtros combinados en un log a mano |
| `truth.py` | `EpisodeTruth` con G, nivel real, calidad del triaje, salto y respuesta por prueba; cumplimiento por nivel real | Solo se lee del ground truth, nunca del log |
| `compare.py` | Tipos de emparejamiento: plantilla (mismos pacientes), clínico (mismos sorteos estándar, valores distintos) o sin emparejar | Una ejecución frente a sí misma da cero; con la disnea ×1,5 solo cambian de motivo los pacientes que pasan a disnea |

La 4.8b dejó en Simular la opción del modelo provisional, que edita las secciones `[triaje]`, `[duraciones]` y `[pruebas]` de `config/centro.toml`. La 4.8c la quita (ver «Preparación del cierre»), para que la separación de `centro.toml` en la 4.9 solo toque el núcleo.

### Cambios en las páginas (tarea 4.8b, Codex)

| Página | Qué cambia |
| --- | --- |
| Ejecuciones | Columnas de modelo (provisional o clínico) y huella de los perfiles |
| Simular | Selector de perfiles con su resumen de solo lectura (motivos, niveles, pruebas esperadas); el editor del centro se queda con turnos, plantilla, boxes y destino provisional; la carga prevista sale de los perfiles. Desaparecen los bloques de triaje, duraciones y pruebas del centro |
| Resultados | KPIs con los tres relojes etiquetados («Puerta-médico (A)», «Desde el inicio del triaje (B)», «Desde la clasificación (C)»); el cumplimiento dice que se mide desde la clasificación; pretriaje; nivel 1 con mediana y p90; reparto de motivos y niveles de la ejecución |
| Episodios | Edad, sexo, medio, motivo y pruebas en la tabla, los filtros y la ficha; «ver la verdad» con G, nivel real, calidad del triaje y respuesta por prueba |
| Comparar | El tipo de emparejamiento (plantilla, clínico o sin emparejar) y las claves que cambian en el centro y en los perfiles |
| Replay | La ficha del paciente muestra motivo y edad; los colores siguen el nivel asignado |
| «¿Qué estoy viendo?» | Textos nuevos: nivel asignado frente a real, los tres relojes y el emparejamiento clínico |

La app usa el modelo clínico desde la 4.8b, aunque el núcleo no lo haga por defecto hasta la 4.9.

### Preparación del cierre (tarea 4.8c, Codex)

La tarea 4.9 hace del modelo clínico el de por defecto en el núcleo y quita de `config/centro.toml` las secciones `[triaje]`, `[duraciones]` y `[pruebas]`, que solo usa el modelo provisional. La 4.8b dejó en Simular la opción Provisional, que edita esas secciones, y 27 tests de `app/tests/test_simulate.py` simulan con ellas: con la separación, `tests-app` se rompería. La 4.8c deja la app lista para que la 4.9 solo toque el núcleo, y pone al día las ayudas.

| Cambio | Detalle |
| --- | --- |
| Simular solo crea ejecuciones clínicas | Sin selector de modelo. Ningún paso de Simular (editor, validación, resumen, carga prevista y ejecución) lee `triaje.*`, `duraciones.*` ni `pruebas.*`; las variantes conservan tal cual las claves que la app no edita |
| Ejecuciones provisionales | Se siguen listando y abriendo en las otras cinco páginas, como hasta ahora; la app ya no las crea (el núcleo sí, para la validación del motor) |
| Valores ausentes | Un campo del centro sin valor (`None`) se muestra «—» en Comparar y en la tabla de la verdad, nunca «None» |
| Ayudas | «¿Qué estoy viendo?» de Simular y Ejecuciones con el modelo clínico; las otras cuatro se revisan para que nada deje de ser cierto tras la 4.9 |
| Contrato con la 4.9 | Un test de la app con un centro sin las tres secciones, marcado `xfail(strict=True)` mientras el núcleo las exija; la 4.9 quita la marca |
| Menores | «— min» en la ficha del episodio cuando falta el valor; nota en `app/AGENTS.md`: `scripts/tests-completos.sh` falla en los notebooks dentro del sandbox de Codex y se ejecuta fuera, como los comandos de git |
| Manual de usuario | `app/README.md` sigue diciendo que la app usa el motor del hito 3: introducción con el modelo clínico, tabla de las seis páginas con lo que añadió la 4.8b, `config/perfiles.toml` en «Datos en disco» y enlace a esta especificación |

Qué cuentan las ayudas nuevas:

- **Simular:** las ejecuciones nuevas usan el modelo clínico. Cada paciente sale de los perfiles (edad, sexo, medio, motivo, gravedad, triaje con error, pruebas y duraciones), y del centro solo cuentan turnos, plantilla, boxes, los niveles que esperan los resultados fuera y el destino provisional. El resumen de los perfiles es su expectativa anual, no lo que dará una ejecución. La carga prevista sale de una muestra del muestreador clínico: tarda unos segundos la primera vez y se reutiliza al cambiar la plantilla; quien espera los resultados fuera no ocupa box mientras espera.
- **Ejecuciones:** el modelo de cada ejecución; una clínica guarda también la copia de sus perfiles y su huella, para poder reproducirla; las provisionales (hito 3) se abren, pero la app ya no las crea.

Etiqueta `app-v0.2.1` tras la fusión.

### Tests

- Núcleo (`tests/`): tests primero y valores a mano, como siempre; las comprobaciones cruzadas de la tabla de la 4.8a; un test con una ejecución de la versión 1 del formato guardada en `tests/data`.
- Páginas (`app/tests/`): un `AppTest` por página con una ejecución de 3 días con perfiles y otra del modelo provisional; Simular con perfiles en 1 día.
- Frontera: el test de que el núcleo no importa Streamlit, pandas ni `edsim_app` sigue en verde.
- Prueba manual: Pedro abre la app, recorre las páginas cambiadas y revisa el PR.

### Decisiones

| # | Serie | Decisión | Motivo |
| --- | --- | --- | --- |
| APP-0004 | App | Los perfiles se ven y se eligen en la app, pero no se editan | Editar 17 motivos con validación en vivo es una tarea grande; encaja con la fase 2 |
| APP-0005 | App | Desde la 4.8c, Simular solo crea ejecuciones del modelo clínico; las provisionales se siguen abriendo en el resto de páginas | El provisional queda para la validación del motor (decisión 44) y sus parámetros salen de `centro.toml` en la 4.9; la app es el laboratorio del modelo clínico |
| Nota a la 0032 | Núcleo | `run.json` pasa a la versión 2 (modelo, copia y huella de los perfiles) y se siguen leyendo las ejecuciones de la versión 1 | Una ejecución tiene que poder reproducirse con todo lo que la generó |
| Nota a la 0031 | Núcleo | Los incrementos de la app se documentan en esta pestaña, no en la del hito | Documentación de la app independiente, con su propio anexo |

La decisión de los perfiles de solo lectura se numeró APP-0003 hasta el cierre de la 4.8b, pero ese número ya era la ADR «Codex para la fase 1» (`app/docs/decisiones/`): pasa a APP-0004. La 4.8c escribe las ADR APP-0004 y APP-0005.

### Tareas

Van después del notebook 04 (tarea 4.7) y antes del cierre del hito (4.9), con el flujo de git de la pestaña del hito. La revisión con `@codex review` no se pide en estas tres tareas.

| # | Tarea | Quién | Rama | Resultado |
| --- | --- | --- | --- | --- |
| 4.8a | Núcleo de la app con perfiles en `runs/`: resumen, carga prevista, relojes, episodios, verdad y emparejamiento | Claude Code | `feat/h4-app-nucleo` | `runs/` trabaja con los dos modelos y la app sigue verde sin cambios |
| 4.8b | Páginas con perfiles: Ejecuciones, Simular, Resultados, Episodios, Comparar, Replay y ayudas | Codex | `feat/app-h4-paginas` | La app usa el modelo clínico; etiqueta `app-v0.2.0` tras la fusión |
| 4.8c | Preparación del cierre: Simular solo clínico, valores ausentes como «—», ayudas de Simular y Ejecuciones, test con un centro sin secciones provisionales (xfail hasta la 4.9) y menores | Codex | `feat/app-h4-cierre` | La 4.9 puede quitar las secciones provisionales sin tocar la app; etiqueta `app-v0.2.1` tras la fusión |

### Criterios de aceptación

- Desde la app se elige un perfil, se ve su resumen y su carga prevista y se simula sin tocar la terminal.
- Una ejecución de la app y otra de `edsim motor simular --perfiles` con los mismos parámetros tienen el mismo log.
- Resultados muestra los mismos KPIs que el resumen de la CLI, con los tres relojes etiquetados y el cumplimiento desde la clasificación.
- Cualquier episodio muestra su perfil y, con «ver la verdad», su gravedad, su nivel real y la calidad de su triaje.
- Comparar detecta el emparejamiento clínico y, con una ejecución consigo misma, da cero en todo.
- Las ejecuciones antiguas (versión 1 y provisionales) se siguen listando y abriendo. Tras la 4.8c, la app ya no crea ejecuciones provisionales ni lee en Simular las secciones provisionales del centro; la 4.9 añade al núcleo el lector compatible y quita la marca `xfail` del test de la app con un centro sin esas secciones.
- CI en verde con `tests` y `tests-app`, y las etiquetas `app-v0.2.0` y `app-v0.2.1` existen.

### Anexo del incremento del hito 4

Este anexo se amplía al cerrar las tareas 4.8a, 4.8b y 4.8c con lo que se hizo, los conceptos, las decisiones, los resultados, las versiones incorrectas y las lecciones aprendidas.

#### Tarea 4.8a: núcleo de la app con perfiles clínicos

**Qué se hizo**

PR #51 (rama `feat/h4-app-nucleo`, Claude Code): doce commits y tres de la revisión, solo en `src/edsim/runs/`, `tests/` y `docs/specs/hito-4.md`. `app/` no cambia y sus 241 tests siguen en verde. El detalle de cada pieza está en la pestaña del hito 4, «Hecho en la tarea 4.8a».

- `RunResults` con `model`, `profiles` (de la copia de la carpeta) y `observed`; recuento de violaciones de una clínica con los perfiles y el ground truth leído de disco, episodios y días (`runs/_truth_csv.py`).
- Relojes: `window_clocks`, `level_one_clocks`, `window_pretriage` y `window_compliance(..., measure=)`, con el reloj A por defecto.
- Verdad clínica: lectura del CSV de 57 columnas contra `run.json`, `compare_episode_truth` con la franja del pedido, `episode_clinical_truth` («ver la verdad») y `true_level_window_compliance`.
- Perfil observable del log (`observed_profiles`) y filtros por banda de edad, sexo, medio, motivo y prueba.
- Sala de resultados: `results_room` en los tramos y en el Replay, sin estados nuevos.
- `summarize_profiles` y la carga prevista con el muestreador clínico, en dos partes: `offered_load` y `offered_work_from_load`.
- Emparejamiento de plantilla, clínico y sin emparejar (`pairing_category`, `clinical_differences`).

**Conceptos**

- **Cambiar de forma aditiva.** Un núcleo que otra parte ya usa cambia con campos al final, parámetros con el valor de antes por defecto y funciones nuevas; así el núcleo y las páginas van en tareas y agentes distintos.
- **Lo observable sale del log; la verdad, solo donde se muestra.** El perfil del paciente se lee de los eventos, y una ejecución sin el CSV de verdad lo sigue mostrando.
- **Mismos sorteos estándar.** Dos clínicas con la misma semilla y otros perfiles son los mismos pacientes con otros valores: se comprueba con la z de la gravedad y los 12 sorteos de las pruebas guardados en la verdad.
- **Separar lo lento de lo que cambia.** La carga prevista depende de las llegadas y los perfiles, no de la plantilla: se calcula una vez y la capacidad se recalcula en milisegundos.
- **El trabajo llega después que el paciente.** La carga de cada turno no es la de los pacientes que llegan en él: la reevaluación cae horas después y desplaza trabajo hacia la tarde y la noche.

**Decisiones**

- Solo núcleo; todo lo que la app usa, aditivo; la app sigue con el reloj A hasta la 4.8b.
- La sala se marca con un booleano, no con un estado nuevo.
- Perfiles distintos no bloquean el emparejamiento entre dos clínicas; modelos distintos sí.
- Con el modelo clínico, del centro solo el destino cambia sorteos (`CLINICAL_DRAW_EFFECTS`).
- El test de la carga prevista frente a `knob_loads` usa perfiles neutros y llegadas planas, donde la comparación es exacta en esperanza.

**Resultados**

| Medida | Valor |
| --- | --- |
| CLI frente a `simulate_run` (3 días, `config/`) | La misma huella del log |
| Clínica de 14 días con `config/` | `runs/` = CLI. Nivel 2: A 10,8 / 45,6, B 7,6 / 16,4, C 1,1 / 10,2 (mediana / p90); cumple C el 89,7 %, 4 de 12 días fuera. Pretriaje de los niveles 2 a 5: 78,0 % en 10 min o menos, 33,8 % por encima de 5. Nivel 1: mediana 0,5 y p90 6,5 |
| `summarize_profiles` con `config/` | Asignado 0,3998 / 12,0960 / 33,5610 / 52,5431 / 1,4002 %; real 0,3881 / 12,5147 / 35,8221 / 50,6227 / 0,6524 %; infra 10,10 y sobre 6,29; alguna prueba 72,75 %; médico 24,20 + 8,18 = 32,37 min |
| Carga prevista frente a `knob_loads` | Con perfiles neutros, dentro del 0,72 %. Con `config/` en el año, médicos −7,7 / +0,7 / +15,1 % y enfermería −0,8 / −0,3 / +2,3 % (mañana, tarde, noche) |
| Emparejamiento | Plantilla `[12, 11, 4]` frente a `[12, 11, 5]`: todo a cero. Gripe en 3 días de enero: 43 de 1101 cambian de motivo, todos a disnea (48,4 esperados, intervalo \[28, 72\]) |
| Ejecuciones antiguas | v1, provisional y clínica se abren en resultados, episodios, verdad, Replay y Comparar |
| Tiempos | `offered_work` con perfiles, 7,1 s (una semana) y 9,3 s (un año); `offered_work_from_load`, unos 2 ms. Suite 2.750 tests en 19 min 29 s; app 241 en 2 min 56 s |

**Comprobación de las versiones incorrectas**

Ocho. Seis exactas (V1, V2, V4, V6, V8 y V3, esta con −4,8 % frente al −5,0 % previsto). V5 tuvo un fallo de más explicado (sin usar la medida tampoco se valida). V7 se rehizo: la primera mutación cambió también el campo que decide el estado y fallaron 13 tests de estados.

**Revisión**

La validación del plan encontró que el recuento clínico construía la verdad sin días, y la invariante de la respuesta de las pruebas lee la fecha del día 0: habría dado `IndexError`. Se añadió el lector de `ground_truth_dias.csv`, un test contra la verdad en memoria de la simulación y la V8. En el PR, dos ajustes: la carga prevista en dos partes, para que la página Simular no repita 7 s de muestra en cada edición de la plantilla, y el número de franjas sacado de los perfiles en lugar de un 3 fijo.

**Lecciones aprendidas**

- Un test que compara una función con la misma llamada que hace ella no prueba nada: la referencia tiene que venir de otro sitio (aquí, la verdad en memoria de la simulación).
- Antes de dar por exacta una referencia, comprobar qué supone: `knob_loads` reparte por la llegada, y el trabajo llega después.
- Una predicción sobre la causa de una diferencia se comprueba descomponiéndola (desfase, contexto, modelo).
- Una mutación tiene que tocar solo lo que dice su nombre.

**Pendiente**

- Tarea 4.8b (Codex): las páginas con perfiles, el reloj C con sus etiquetas, la etiqueta de la sala, las dos esperas de box en las tablas, el payload de `resultados` y las etiquetas de los campos nuevos en Comparar. La carga prevista se guarda en caché por llegadas, perfiles y `espera_resultados_fuera`, y la plantilla usa `offered_work_from_load`.
- Calibración, para versiones posteriores: `knob_loads` reparte la carga con la tasa de llegadas de cada turno y no ve el desfase; la noche queda un 15 % por debajo de su carga real de médicos en el año. Usar la carga prevista por turno en la regla.
- Tarea 4.9: el docstring de `manchester_compliance` (`engine/targets.py`) aún dice «until task 4.8a».

#### Tarea 4.8b: páginas de la app con perfiles clínicos

**Qué se hizo**

PR #53 (rama `feat/app-h4-paginas`, Codex): ocho commits y uno de la revisión, en `app/`, con una sola excepción autorizada en el núcleo: `edsim.runs` reexporta `load_profiles`, y el test de frontera lo admite. La etiqueta `app-v0.2.0` apunta a la fusión (`056f18c`).

- **Simular:** selector de modelo, con el clínico por defecto y el provisional como opción; ruta editable del fichero de perfiles, con su huella; resumen de solo lectura (motivos, niveles asignado y real, infra y sobretriaje, pruebas y minutos de médico esperados). Con el modelo clínico, el editor solo muestra turnos, recursos y destino.
- **Carga prevista:** `cached_offered_load` guarda la parte lenta (unos 7 s) con una clave sin la plantilla: modelo, huellas de llegadas y perfiles, valores clínicos del centro, días y muestra. `preview_work` aplica después `offered_work_from_load`, así que editar la plantilla no repite la muestra.
- **Resultados:** los tres relojes, con las etiquetas «Puerta-médico (A)», «Desde el inicio del triaje (B)» y «Desde la clasificación (C)»; Manchester con el reloj C, calculado sobre una copia de `RunResults` en la caché de la app (`window_compliance(..., measure="classified_to_doctor")`), porque el núcleo sigue con A por defecto hasta la 4.9; pretriaje; nivel 1 con mediana y p90; reparto observado de motivos y niveles.
- **Episodios:** perfil observable en la tabla, los filtros y la ficha; «Ver la verdad»; la sala de resultados y las dos esperas de box.
- **Comparar:** tipo de emparejamiento (plantilla, clínico o sin emparejar) con su etiqueta, y cambios campo a campo, también los de `run.json` versión 2.
- **Replay:** ficha con edad y motivo cuando ya constan en el log, sala de resultados y colores por nivel asignado.
- **Payloads:** `plain_payload` muestra los eventos clínicos, también `resultados`, que `json.dumps` no admitía tal cual.
- **Ayudas «¿Qué estoy viendo?»:** textos nuevos en Resultados, Episodios, Comparar y Replay.

**Conceptos**

- **La clave de una caché es lo que cambia la respuesta.** La carga prevista depende de las llegadas y los perfiles, no de la plantilla: sin la plantilla en la clave, cambiar un médico cuesta milisegundos.
- **Otra medida en la app sin tocar el núcleo.** La app pide el cumplimiento con el reloj C y guarda una copia de los resultados con él; el núcleo conserva su valor por defecto hasta que la 4.9 lo cambie para todos.
- **Qué población entra en cada cifra.** El reparto observado cuenta las llegadas de la ventana, también las que no han terminado, y nunca usa niveles reales; las esperas, solo los completados.
- **Nivel asignado en la interfaz, real solo como verdad.** Colores, KPI y filtros usan el nivel asignado; el real, la gravedad y la calidad del triaje solo aparecen con «Ver la verdad».

**Decisiones**

- `load_profiles` se reexporta en `edsim.runs` para que la app no importe nada fuera de `__all__` (excepción a la regla de zonas, autorizada en la tarea).
- Los perfiles se eligen por ruta, como el centro, y se validan al cargar; no se editan (APP-0004).
- El reparto observado se calcula sobre las llegadas de la ventana.
- La opción Provisional se queda en Simular, con el editor completo del centro.

**Resultados**

| Medida | Valor |
| --- | --- |
| Tests de la app | En serie, unos 4 min 23 s (unos 2 min 30 s tras la P.1) |
| Ejecuciones antiguas | v1, provisional y clínica se abren en las seis páginas |
| Etiqueta | `app-v0.2.0` sobre `056f18c` |

**Comprobación de las versiones incorrectas**

Las del plan, aplicadas y deshechas; el detalle está en la descripción del PR #53.

**Revisión**

Aprobado con un commit de la revisión: comprobaciones de los datos de la sala, de la caché y de la selección de perfiles.

**Lecciones aprendidas**

- Una promesa de la especificación se comprueba en el código al cerrar la tarea: esta pestaña decía que, tras la 4.8b, la separación de `centro.toml` solo tocaría el núcleo, pero la opción Provisional de Simular sigue editando las secciones `[triaje]`, `[duraciones]` y `[pruebas]` de `config/centro.toml`, y 27 tests de `app/tests/test_simulate.py` simulan con ellas.
- Lo lento se separa de lo que cambia y se guarda con una clave que no incluye lo que cambia.

**Pendiente**

- **Antes de la 4.9 (decidido al cerrar la 4.8b):** la tarea 4.8c (Codex) quita la opción Provisional de Simular, para que la separación de `centro.toml` no rompa `tests-app` (ver «Preparación del cierre»).
- Ayudas de Simular y Ejecuciones: no explican el selector de modelo, el resumen de perfiles (expectativa anual, no observación), qué campos del centro usa cada modelo ni que una ejecución clínica guarda la copia de sus perfiles.
- «— min» en la ficha del episodio cuando falta el valor.
- La app no muestra `true_level_window_compliance` (cumplimiento por nivel real).
- Comparar no muestra las diferencias de los perfiles clave a clave.
- Los notebooks fallan dentro del sandbox de Codex en `scripts/tests-completos.sh`: anotarlo en `AGENTS.md`.
- **Desde la revisión de la 4.8c (PR #54):** ningún test comprueba ya el aviso «No hay diferencias frente al centro base» de Simular; la única aserción usaba el reparto de triaje normalizado, que salió del editor. Se fusionó sin el ajuste por ser menor: añadir el test con los campos del editor clínico (o explicar en qué estado se muestra el aviso) en la próxima tarea de la app.

#### Tarea 4.8c: preparación del cierre en la app

**Qué se hizo**

PR #54 (rama `feat/app-h4-cierre`, Codex): cuatro commits, todos en `app/`. El primero es la exportación de esta pestaña, tal cual. Fusión `103e797`; etiqueta `app-v0.2.1`.

- **Simular solo crea ejecuciones clínicas (APP-0005).** Desaparecen el selector de modelo, el ajuste `model` del estado y todo lo que solo servía al provisional: el resumen del centro (`summarize_center`), las curvas de duraciones (`duration_chart` y su test) y la rama provisional de la carga prevista. La ejecución siempre pasa los perfiles elegidos. La clave de `cached_offered_load` pierde el modelo y sigue sin la plantilla.
- **Errores de claves que no se editan.** Antes solo se mostraban los de claves que no estaban en `FIELDS`. Una clave provisional no válida, que sigue en `FIELDS` por las etiquetas de Comparar, bloqueaba Simular sin decir por qué (ya pasaba con el modelo clínico de la 4.8b). Ahora se muestra todo error cuya clave no tenga campo en el editor, con su clave y el aviso de corregirlo fuera de la app. Lo encontró la validación del plan.
- **Valores ausentes.** `format_change_value(None)` da «—», también en la tabla de cambios del centro, a cualquiera de los dos lados. En la ficha del episodio, las dos esperas de box ausentes muestran «—» sin unidad.
- **Contrato con la 4.9.** `test_clinical_center_contract.py`: con un centro sin `[triaje]`, `[duraciones]` ni `[pruebas]`, Simular abre sin errores, guarda una variante sin esas tablas, calcula la carga prevista y simula un día como ejecución clínica. Está marcado `xfail(strict=True, raises=AssertionError)`: hoy falla la primera aserción porque el núcleo muestra seis errores «missing keys». La 4.9 quita la marca.
- **Manual de usuario.** `app/README.md` presenta el modelo clínico, la tabla de las seis páginas con lo que añadió la 4.8b, `config/perfiles.toml` en «Datos en disco» y el enlace a esta especificación. Las ayudas de Simular y Ejecuciones explican el modelo clínico, qué cuenta del centro, el resumen como expectativa anual, la carga prevista y la copia de los perfiles.
- **ADR** APP-0004 y APP-0005 en `app/docs/decisiones/`, con su índice. Nota en `app/AGENTS.md`: `scripts/tests-completos.sh` se ejecuta fuera del sandbox, porque el kernel de Jupyter necesita abrir sockets locales.
- **Tests de Simular** pasan al modelo clínico. Se reescriben con turnos, recursos o destino los casos de errores múltiples, tipos, lista de cambios y cambios sin guardar. El de alternar modelos pasa a ser de navegación. El de parámetros provisionales absurdos comprueba además que no se recalcula la carga y que al guardar se conservan esas claves.

**Conceptos**

- **Un contrato entre dos tareas, escrito como test.** Un `xfail` estricto documenta lo que la tarea siguiente tiene que hacer posible. Si un día pasa sin que nadie quite la marca, el test falla: nadie puede olvidarlo, y la tarea del núcleo sabe cuándo ha terminado.
- **Un bloqueo siempre dice por qué.** Si la validación impide guardar o simular, cada error tiene que verse, aunque su campo no esté en el editor.
- **El manual de usuario de la app** es `app/README.md` más las ayudas «¿Qué estoy viendo?» de cada página; se revisan en cada incremento.

**Decisiones**

- APP-0005: Simular solo crea ejecuciones clínicas; las provisionales se siguen abriendo en las otras cinco páginas, y el núcleo las sigue creando para la validación del motor.
- APP-0003 era ya «Codex para la fase 1»: la decisión de los perfiles de solo lectura pasa a ser APP-0004.
- Lo que solo servía al provisional en Simular se borra, no se esconde.

**Revisión**

Aprobado en el código. La descripción del PR no se pudo leer desde el chat (límite de peticiones de GitHub): los tiempos de la suite de la app y los resultados de las versiones incorrectas están allí. Ajuste propuesto y no aplicado, por menor: ningún test comprueba ya el aviso «No hay diferencias frente al centro base» (ver «Pendiente»).

**Lecciones aprendidas**

- Al cambiar qué campos muestra un formulario, revisar también dónde se muestran sus errores: un filtro pensado para otro conjunto de campos puede esconderlos.
- Al borrar los tests de un camino que desaparece, comprobar qué aserciones de otras cosas viajaban en ellos.
- El contrato del `xfail` cubre el flujo de Simular, pero no los fixtures de los tests: varios tests de la app siguen leyendo las secciones provisionales de `config/centro.toml` (el catálogo clínico de `conftest.py`, que simula una ejecución provisional y escribe una variante con valores provisionales absurdos; el test de parámetros absurdos y el de errores de claves no editables). La 4.9 los adapta, con una excepción de zona limitada a `app/tests/`.

**Pendiente**

- Un test del aviso «No hay diferencias frente al centro base» con los campos del editor clínico, o la explicación de en qué estado se muestra (próxima tarea de la app).
- Sin cambios desde la 4.8b: `true_level_window_compliance` no se muestra; Comparar no muestra las diferencias de los perfiles clave a clave.
