# App web — incrementos


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

- Editar perfiles en la app (decisión APP-0003): fase 2.
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

Antes del cierre del hito (tarea 4.9), la app deja de leer los campos clínicos de `CenterConfig` (reparto de niveles, duraciones, pruebas). Así, la separación de `centro.toml` en la 4.9 solo toca el núcleo.

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

### Tests

- Núcleo (`tests/`): tests primero y valores a mano, como siempre; las comprobaciones cruzadas de la tabla de la 4.8a; un test con una ejecución de la versión 1 del formato guardada en `tests/data`.
- Páginas (`app/tests/`): un `AppTest` por página con una ejecución de 3 días con perfiles y otra del modelo provisional; Simular con perfiles en 1 día.
- Frontera: el test de que el núcleo no importa Streamlit, pandas ni `edsim_app` sigue en verde.
- Prueba manual: Pedro abre la app, recorre las páginas cambiadas y revisa el PR.

### Decisiones

| # | Serie | Decisión | Motivo |
| --- | --- | --- | --- |
| APP-0003 | App | Los perfiles se ven y se eligen en la app, pero no se editan | Editar 17 motivos con validación en vivo es una tarea grande; encaja con la fase 2 |
| Nota a la 0032 | Núcleo | `run.json` pasa a la versión 2 (modelo, copia y huella de los perfiles) y se siguen leyendo las ejecuciones de la versión 1 | Una ejecución tiene que poder reproducirse con todo lo que la generó |
| Nota a la 0031 | Núcleo | Los incrementos de la app se documentan en esta pestaña, no en la del hito | Documentación de la app independiente, con su propio anexo |

### Tareas

Van después del notebook 04 (tarea 4.7) y antes del cierre del hito (4.9), con el flujo de git de la pestaña del hito. La revisión con `@codex review` no se pide en estas dos tareas.

| # | Tarea | Quién | Rama | Resultado |
| --- | --- | --- | --- | --- |
| 4.8a | Núcleo de la app con perfiles en `runs/`: resumen, carga prevista, relojes, episodios, verdad y emparejamiento | Claude Code | `feat/h4-app-nucleo` | `runs/` trabaja con los dos modelos y la app sigue verde sin cambios |
| 4.8b | Páginas con perfiles: Ejecuciones, Simular, Resultados, Episodios, Comparar, Replay y ayudas | Codex | `feat/app-h4-paginas` | La app usa el modelo clínico; etiqueta `app-v0.2.0` tras la fusión |

### Criterios de aceptación

- Desde la app se elige un perfil, se ve su resumen y su carga prevista y se simula sin tocar la terminal.
- Una ejecución de la app y otra de `edsim motor simular --perfiles` con los mismos parámetros tienen el mismo log.
- Resultados muestra los mismos KPIs que el resumen de la CLI, con los tres relojes etiquetados y el cumplimiento desde la clasificación.
- Cualquier episodio muestra su perfil y, con «ver la verdad», su gravedad, su nivel real y la calidad de su triaje.
- Comparar detecta el emparejamiento clínico y, con una ejecución consigo misma, da cero en todo.
- Las ejecuciones antiguas (versión 1) se siguen listando y abriendo. Después de la 4.9, que quita las secciones clínicas de `centro.toml`, abrirlas necesita un lector compatible: el plan de la 4.9 lo decide y lo prueba.
- CI en verde con `tests` y `tests-app`, y la etiqueta `app-v0.2.0` existe.

### Anexo del incremento del hito 4

Este anexo se amplía al cerrar las tareas 4.8a y 4.8b con lo que se hizo, los conceptos, las decisiones, los resultados, las versiones incorrectas y las lecciones aprendidas.

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
