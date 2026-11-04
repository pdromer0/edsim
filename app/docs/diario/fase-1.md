# Diario · Fase 1 — EDsim Lab

La [especificación y su anexo](../specs/fase-1.md#anexo-guía-de-referencia-de-la-fase-1)
conservan el detalle de cada tarea. Las entradas siguientes parten de las
«Notas para el diario» de los PR; las fechas son las de fusión, consultadas en
GitHub. El PR #28 no tiene esa sección: A.0 usa su cuerpo y el anexo, sin
atribuirle notas que no existen. Las divisiones A.2a/A.2b y A.3a/A.3b se conservan;
el PR #34 pertenece a las correcciones de A.3b.

## 2026-11-03 · Tarea A.0 — Preparar Codex

**Qué se hizo:** instrucciones compartidas en `AGENTS.md`, configuración de
Codex con sandbox, reglas y hook Stop, y prueba del ciclo con GitHub. El núcleo
no cambió.

**Qué aprendí:**

- Una regla que permite un comando autoriza su escalada; no elimina los límites
  del sandbox. La configuración del agente también queda protegida.
- Una fuente única evita que Codex y Claude Code reciban instrucciones
  contradictorias; cada uno conserva su configuración específica.

**Qué costó o falló:**

- La regla de revisión «código nuevo sin tests» produjo un P1 sobre el hook. Se
  precisó su alcance y se documentó su verificación manual.
- La caché de uv necesitó acceso fuera del sandbox. La primera publicación del
  entorno cloud falló por el servicio y la revisión funcionó después.

**Preguntas abiertas:** comprobar la confianza y aprobación locales del hook en
cada máquina; las fuentes no registran una pregunta nueva de diseño.

**Enlaces:** [PR #28](https://github.com/pdromer0/edsim/pull/28) ·
[APP-0003](../decisiones/APP-0003-codex-para-la-fase-1.md) ·
[anexo A.0](../specs/fase-1.md#tarea-a0-preparar-codex)

## 2026-11-03 · Tarea A.1 — Esqueleto y workspace

**Qué se hizo:** paquete `edsim-app`, navegación de las seis páginas, lanzador,
tests de frontera y job `tests-app`. El hook de Codex pasó a probar también la app.

**Qué aprendí:**

- El workspace usa el núcleo de la rama con un solo entorno y lockfile.
- Declarar dependencias no impide imports desde un entorno compartido: la
  frontera necesita comprobaciones dinámicas, estáticas y CI sin la interfaz.
- Un test de navegación comprueba el contenido de destino, además de no fallar.

**Qué costó o falló:**

- `uv sync` simple retiró la app; el comando habitual quedó en
  `uv sync --all-packages` y el arranque selecciona `--package edsim-app`.
- Git no pudo escribir dentro del sandbox; se pidió directamente la escalada.
  Streamlit ignora el `url_path` de la página predeterminada, que abre en `/`.

**Preguntas abiertas:** los retoques del enlace al hito y de la fuente única de
imports prohibidos pasaron a A.2a; Pedro debía añadir el check al ruleset.

**Enlaces:** [PR #29](https://github.com/pdromer0/edsim/pull/29) ·
[APP-0001](../decisiones/APP-0001-interfaz-streamlit-sin-api.md) ·
[APP-0002](../decisiones/APP-0002-paquete-app-en-workspace-uv.md) ·
[anexo A.1](../specs/fase-1.md#tarea-a1-esqueleto-de-la-app-y-workspace-de-uv)

## 2026-11-03 · Tarea A.2a — Núcleo de ejecuciones

**Qué se hizo:** catálogo, metadatos y `simulate_run` compartidos con la CLI.
La caracterización se congeló antes del refactor y las configuraciones se
copian antes de simular.

**Qué aprendí:**

- Los metadatos persistidos y el resultado transitorio de una operación son
  tipos distintos. Un nombre ocupado tampoco implica una ejecución válida.
- Los hashes de los CSV incluyen las cadenas de procedencia: las rutas también
  forman parte de una caracterización reproducible.

**Qué costó o falló:**

- La primera mutación de atomicidad fallaba por dónde buscaba el test el log,
  antes de comprobar el defecto previsto. Se corrigió el test y se repitió.
- La revisión del chat encontró errores internos convertidos en errores de uso,
  cabecera tardía y permisos privados heredados del temporal; se corrigieron.
  `@codex review` no había encontrado problemas importantes.

**Preguntas abiertas:** mostrar en A.2b las carpetas no válidas que el borrado
seguro no admite eliminar; el límite medido se conservó en 60 días.

**Enlaces:** [PR #30](https://github.com/pdromer0/edsim/pull/30) ·
[0032](../../../docs/decisiones/0032-ejecuciones-en-carpetas-reproducibles.md) ·
[anexo A.2a](../specs/fase-1.md#tarea-a2a-núcleo-de-ejecuciones)

## 2026-11-03 · Tarea A.2b — Catálogo y estado compartido

**Qué se hizo:** selección de ejecuciones, marcas A/B, descarga diferida,
borrado confirmado y simulación del centro base, con selección compartida y URL.

**Qué aprendí:**

- El estado que debe sobrevivir a la navegación necesita claves propias,
  separadas de las claves de widgets que Streamlit limpia.
- AppTest puede conservar parámetros que el navegador borra: la prueba tiene
  que reproducir ese comportamiento del navegador.

**Qué costó o falló:**

- `pages/` activaba la navegación antigua y Replay se saltaba el punto de
  entrada. Se paró para aprobar `views/` y se añadió una guarda.
- `st.dialog` no persistía en AppTest; el borrado quedó en dos pasos. La lectura
  del original se separó de la escritura para clasificar bien los errores.

**Preguntas abiertas:** explicitar UTC+1 en la cabecera en A.3b y abrir con
validación completa los resultados en A.4.

**Enlaces:** [PR #31](https://github.com/pdromer0/edsim/pull/31) ·
[0032](../../../docs/decisiones/0032-ejecuciones-en-carpetas-reproducibles.md) ·
[APP-0001](../decisiones/APP-0001-interfaz-streamlit-sin-api.md) ·
[anexo A.2b](../specs/fase-1.md#tarea-a2b-página-ejecuciones-y-estado-compartido)

## 2026-11-03 · Tarea A.3a — Núcleo de Simular

**Qué se hizo:** validación por campo, escritura de variantes con tomlkit,
diferencias normalizadas y carga ofrecida antes de ejecutar.

**Qué aprendí:**

- Valor bruto, valor normalizado y representación textual son cosas distintas.
- Publicar sin sobrescribir requiere una operación que rechace un destino
  existente: comprobar antes de sustituir deja una carrera.
- Little en una ventana necesita condiciones sobre la tasa y sus bordes.

**Qué costó o falló:**

- Las preguntas del plan cambiaron un día previo fijo por días adaptativos y
  limitaron dónde exigir Little. No se cambió la semilla para forzar un día.
- Un test sobre el efecto diario tropezó con la renormalización del perfil; se
  aisló el CV usando factores unidad, sin ampliar tolerancias.
- La autorrevisión encontró la confusión de una clave literal con punto con una
  clave de tabla; se conservó el diagnóstico histórico con regresiones.

**Preguntas abiertas:** guardar la carga en caché en A.3b. La comparación de dos
semillas es un diagnóstico empírico, no una garantía del error de Monte Carlo.

**Enlaces:** [PR #32](https://github.com/pdromer0/edsim/pull/32) ·
[0033](../../../docs/decisiones/0033-variantes-toml-con-comentarios.md) ·
[anexo A.3a](../specs/fase-1.md#tarea-a3a-núcleo-de-simular)

## 2026-11-03 · Tarea A.3b — Editor y simulación

**Qué se hizo:** borrador persistente, editor, guardado confirmado, carga prevista
y simulación del fichero guardado. Las correcciones de revisión entraron en #34.

**Qué aprendí:**

- El modo automático o manual del identificador también forma parte del estado.
- Una confirmación autoriza unos valores concretos; editarlos la invalida.
- La caché necesita la huella del contenido y los comentarios se conservan
  escribiendo desde la variante de origen.

**Qué costó o falló:**

- La fixture nueva invadía una ruta usada por otros tests; se aisló su carpeta.
- Los tests no mostraron el ruido visual de `%.17g`; la revisión pidió `%.15g`,
  validación previa de tipos representables y fechas sin zona para Altair.
- El commit corrector seguía local cuando se fusionó #33. Se trasladó a #34 con
  el mismo árbol; un commit local no acredita lo publicado en un PR.

**Preguntas abiertas:** las correcciones quedaron resueltas en #34. La revisión
visual del navegador sigue siendo necesaria aunque AppTest compruebe valores.

**Enlaces:** [PR #33](https://github.com/pdromer0/edsim/pull/33) ·
[PR #34](https://github.com/pdromer0/edsim/pull/34) ·
[0033](../../../docs/decisiones/0033-variantes-toml-con-comentarios.md) ·
[APP-0001](../decisiones/APP-0001-interfaz-streamlit-sin-api.md) ·
[anexo A.3b](../specs/fase-1.md#tarea-a3b-página-simular)

## 2026-11-03 · Tarea A.4 — Resultados

**Qué se hizo:** KPIs, Manchester, ocupación, curvas, Little, invariantes y
descargas desde los servicios del núcleo, contrastados con la CLI.

**Qué aprendí:**

- `cache_resource` comparte el objeto; sus consumidores deben mantenerlo de
  solo lectura. La identidad de una ejecución incluye la huella de sus metadatos.
- Un recuento vacío es cero; una estadística sin población es desconocida.
- El máximo de un bloque necesita el estado vigente antes de su primer evento.

**Qué costó o falló:**

- `mappingproxy` impedía serializar el análisis con pickle. Se eligió caché de
  recursos y se comprobó que navegar y dibujar no mutan lo compartido.
- La revisión añadió aviso de carga, explicación del nivel 1, intervalos
  semiabiertos en las semanas y contraste del texto del mapa de ocupación.

**Preguntas abiertas:** A.5 necesitaba acceso independiente a eventos de un
episodio y a su verdad. El reloj de Manchester y el triaje sin prioridad siguen
siendo cuestiones del modelo para el hito 4, explicadas en la ayuda.

**Enlaces:** [PR #35](https://github.com/pdromer0/edsim/pull/35) ·
[0032](../../../docs/decisiones/0032-ejecuciones-en-carpetas-reproducibles.md) ·
[APP-0001](../decisiones/APP-0001-interfaz-streamlit-sin-api.md) ·
[anexo A.4](../specs/fase-1.md#tarea-a4-página-resultados)

## 2026-11-04 · Tarea A.5 — Episodios

**Qué se hizo:** índice por posiciones en bytes, tramos, filtros y ficha con
comparación frente a la verdad. La corrección de revisión aisló la ficha en un
fragmento y añadió pruebas de peticiones parciales reales.

**Qué aprendí:**

- La ubicación del paciente y el laboratorio son procesos distintos: las
  pruebas pueden seguir mientras espera un nuevo box.
- Una estancia censurada aporta una cota; no se convierte en una estancia final.
- El coste visible puede estar en presentar la tabla, aunque leer la ficha sea
  barato. Construcción y serialización del `Styler` deben medirse por separado.

**Qué costó o falló:**

- Integrar el índice en el lector de Resultados empeoró la apertura por encima
  del umbral fijado. Se paró y se eligió un índice independiente, sin repetir
  muestras para aprobar la primera opción.
- La fixture inicial no generaba desalojos; la aserción lo reveló. Se redujeron
  los boxes del escenario manteniendo la semilla.
- Una reejecución normal de AppTest no prueba el aislamiento del fragmento;
  `FragmentRunner` comprobó la petición parcial y la URL desde el callback.

**Preguntas abiertas:** el filtrado de tablas grandes sigue siendo costoso y el
adaptador depende de detalles internos de Streamlit. El enlace al replay llegó
en A.7.

**Enlaces:** [PR #36, ambas secciones de notas](https://github.com/pdromer0/edsim/pull/36) ·
[0032](../../../docs/decisiones/0032-ejecuciones-en-carpetas-reproducibles.md) ·
[APP-0001](../decisiones/APP-0001-interfaz-streamlit-sin-api.md) ·
[anexo A.5](../specs/fase-1.md#tarea-a5-página-episodios)

## 2026-11-04 · Tarea A.6 — Comparar

**Qué se hizo:** resumen de ambos lados y comparación paciente a paciente con
emparejamiento comprobado frente al ground truth, diferencias y enlaces a fichas.

**Qué aprendí:**

- Compartir semilla no basta: la configuración establece qué debería
  conservarse y la verdad comprueba qué ocurrió.
- El resumen y la comparación validada usan tipos distintos, para no presentar
  historias de pacientes que no se han comprobado.
- La simetría no fija el signo: hace falta un oráculo explícito de B − A.

**Qué costó o falló:**

- La censura afecta al promedio de cada lado y a qué pacientes se emparejan;
  excluirlos o imputarlos sin explicarlo cambia la pregunta.
- La revisión unificó los formatos repetidos y fijó cero como borde de los
  histogramas para separar mejoras y empeoramientos.
- Abrir una ficha desde un fragmento exige actualizar identidad y estado antes
  de navegar, sin depender de una reejecución del punto de entrada.

**Preguntas abiertas:** la comparación sigue siendo de una réplica por lado;
los intervalos de confianza llegan con los experimentos del hito 9.

**Enlaces:** [PR #37](https://github.com/pdromer0/edsim/pull/37) ·
[0007](../../../docs/decisiones/0007-un-flujo-aleatorio-por-fuente.md) ·
[APP-0001](../decisiones/APP-0001-interfaz-streamlit-sin-api.md) ·
[anexo A.6](../specs/fase-1.md#tarea-a6-página-comparar)

## 2026-11-04 · Tarea A.7 — Replay

**Qué se hizo:** reductor de ubicación compartido, índice por horas, plano SVG,
reproducción y navegación desde la ficha. Se aligeró la suite rápida antes de
añadir la página.

**Qué aprendí:**

- Una foto anterior a la frontera y todos los eventos hasta el instante elegido
  eliminan ambigüedades en horas exactas, minuto cero y horizonte.
- Un estado reanudable necesita indicadores completos; la etiqueta de ubicación
  no representa las pruebas pendientes.
- Los contadores de las curvas y los pacientes del índice son un control cruzado
  que se complementa con casos escritos a mano.

**Qué costó o falló:**

- AppTest necesitó sincronizar su ruta de cliente después de comprobar el salto
  a Replay para poder continuar interactuando; se consultó y aprobó el ajuste.
- Las marcas `slow` en la colección preservaron los tests anteriores, pero
  dependen del fichero y las fixtures: un fichero nuevo no queda cubierto solo.
- La primera entrada valida el log dos veces, para resultados e índice. El PR
  publica ese coste por separado de los fotogramas, sin rebajar el límite.

**Preguntas abiertas:** documentar las marcas en A.8 y revisar visualmente la
gráfica de esperas. Quedan para fases siguientes la apertura fría del replay,
el filtrado de Episodios y el mantenimiento del adaptador de fragmentos.

**Enlaces:** [PR #38](https://github.com/pdromer0/edsim/pull/38) ·
[0006](../../../docs/decisiones/0006-log-de-eventos-y-ground-truth.md) ·
[APP-0001](../decisiones/APP-0001-interfaz-streamlit-sin-api.md) ·
[anexo A.7](../specs/fase-1.md#tarea-a7-página-replay)

## Codex frente a Claude Code

La comparación usa los PR de esta fase y el
[diario del hito 3](../../../docs/diario/hito-3.md), contrastado con los PR
[#19](https://github.com/pdromer0/edsim/pull/19) a
[#27](https://github.com/pdromer0/edsim/pull/27). Son trabajos con alcances
distintos. Este registro describe hechos documentados y no asigna una
preferencia entre herramientas.

### Plan y preguntas

Ambos trabajaron con explicación conceptual, plan aprobado y decisiones de
Pedro. Con Claude Code, la tarea 3.2 preguntó por «reevaluación» antes de escribir
un test contra un catálogo sin tildes, y 3.6 consultó aumentar las réplicas cuando
la comprobación de potencia no bastaba
([diario 3.2 y 3.6](../../../docs/diario/hito-3.md),
[PR #24](https://github.com/pdromer0/edsim/pull/24)).
Con Codex, las preguntas del plan de A.3a cambiaron los días previos y las
condiciones de Little; durante A.2b se paró para aprobar `views/` al observar el
comportamiento de la biblioteca
([PR #32](https://github.com/pdromer0/edsim/pull/32),
[anexo A.3a](../specs/fase-1.md#tarea-a3a-núcleo-de-simular),
[PR #31](https://github.com/pdromer0/edsim/pull/31)).

### Permisos y sandbox

Los PR de Codex registran escrituras de Git con escalada, caché de uv externa,
sincronizaciones con permiso y publicación autorizada. A.5 documenta el fallo de
Jupyter por no poder abrir sockets y la misma comprobación fuera del sandbox;
A.7 usa caché temporal y entorno instalado sin sincronizar
([PR #29](https://github.com/pdromer0/edsim/pull/29),
[#31](https://github.com/pdromer0/edsim/pull/31),
[#36](https://github.com/pdromer0/edsim/pull/36),
[#38](https://github.com/pdromer0/edsim/pull/38)).
El diario del hito 3 y sus PR #19–#27 no ofrecen un registro equivalente de
permisos o incidencias de sandbox: no se puede comparar su frecuencia ni inferir
que Claude Code no los necesitara
([diario del hito 3](../../../docs/diario/hito-3.md)).

### Errores y correcciones tras la revisión

Con Claude Code quedaron documentadas expectativas de tests insuficientes y
predicciones incorrectas: la mutación de emparejar por posición pasó hasta añadir
el caso que faltaba; la recomendación de réplicas no tuvo potencia suficiente;
y una gráfica tenía un título contradictorio
([PR #26](https://github.com/pdromer0/edsim/pull/26),
[diario 3.6 y 3.8](../../../docs/diario/hito-3.md)). La revisión del PR completo
se adoptó desde 3.6
([PR #27](https://github.com/pdromer0/edsim/pull/27)).
Con Codex, la autorrevisión de A.3a conservó el rechazo de claves literales con
punto; la revisión del chat corrigió captura de errores y permisos en A.2a y
aisló la ficha en un fragmento en A.5. En A.3b se fusionó el PR antes de publicar
el commit corrector, que tuvo que entrar en #34. Son orígenes y momentos de
corrección distintos
([PR #32](https://github.com/pdromer0/edsim/pull/32),
[#30](https://github.com/pdromer0/edsim/pull/30),
[#36](https://github.com/pdromer0/edsim/pull/36),
[#34](https://github.com/pdromer0/edsim/pull/34)).

### Hallazgos de `@codex review`

En A.0 señaló el hook sin tests aplicando la regla escrita; se precisó la regla
para herramientas de desarrollo. En A.2a y A.3a no encontró problemas
importantes, mientras el chat sí detectó los problemas de CLI y permisos de
A.2a. No son revisiones intercambiables
([anexo A.0](../specs/fase-1.md#tarea-a0-preparar-codex),
[A.2a](../specs/fase-1.md#tarea-a2a-núcleo-de-ejecuciones),
[A.3a](../specs/fase-1.md#tarea-a3a-núcleo-de-simular)).
No consta una revisión con `@codex review` en las fuentes del hito 3. La ausencia
de ese segundo revisor impide comparar sus hallazgos entre las dos fases
([diario del hito 3](../../../docs/diario/hito-3.md),
[implementación de la app](../specs/fase-1.md#implementación-con-codex)).

### Tiempo y consumo

Hay duraciones de comprobaciones, no un cronometraje homogéneo de trabajo de los
agentes. Por ejemplo, el cierre de Claude Code registra 1.041 tests completos en
4 min 3 s; A.1 con Codex registra 1.043 en 176,02 s. Son ejecuciones distintas y
no demuestran una diferencia de productividad
([PR #27](https://github.com/pdromer0/edsim/pull/27),
[#29](https://github.com/pdromer0/edsim/pull/29)). Las medidas de la app distinguen
servicio, página y peticiones parciales; A.5 advierte que sus suites completas
compartieron CPU, mientras las medidas de página fueron secuenciales
([PR #36](https://github.com/pdromer0/edsim/pull/36)).

Los PR de Codex que hablan de consumo indican que la sesión no expone una cifra
fiable de tokens, créditos o coste. El diario del hito 3 y sus PR tampoco aportan
una serie comparable. No se calcula un total, un ahorro ni una clasificación de
velocidad con esos datos
([PR #29](https://github.com/pdromer0/edsim/pull/29),
[#30](https://github.com/pdromer0/edsim/pull/30),
[#31](https://github.com/pdromer0/edsim/pull/31),
[diario del hito 3](../../../docs/diario/hito-3.md)).

## Reflexiones de Pedro
