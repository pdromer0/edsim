# Diario · Hito 3 — Motor y eventos

Especificación: [docs/specs/hito-3.md](../specs/hito-3.md). El anexo de la especificación tiene el detalle de cada tarea.

## 2026-10-29 · Tarea 3.1 — Configuración del centro y sorteos del paciente

**Qué se hizo:** `config/centro.toml` con plantilla por turno, triaje, duraciones, pruebas y destino provisionales. `CenterConfig` lo valida al construirse y `ProvisionalSampler` sortea todo lo del paciente al llegar.

**Qué aprendí:**
- `rng.lognormal` pide μ y σ de la normal de dentro. Si le paso la mediana, el triaje dura 148 min de mediana y todo sigue siendo reproducible.
- No basta con un flujo por fuente. Dentro de cada flujo, el número de sorteos tiene que ser siempre el mismo, salga lo que salga.
- Un cuantil empírico se comprueba con una binomial y su IC de Clopper–Pearson, sin inventar una tolerancia.
- El nivel sale de la suma acumulada y una uniforme. En coma flotante la suma puede quedarse en 0,9999999999999999, y hay que forzar el 1.
- Pasar la llegada al muestreador aunque hoy no la use deja el motor listo para el hito 4.

**Qué costó o falló:**
- Al sortear la respuesta solo con pruebas (versión B) cayó también el test de rangos, que no estaba en la predicción: el 0 no es una duración positiva.
- La normalización del reparto no era idempotente en el último bit, y un `approx` lo escondía. Quedó para la 3.2.

**Preguntas abiertas:** ninguna.

**Enlaces:** PR #19 · [ADR 0024](../decisiones/0024-paciente-como-proceso-con-sorteos-al-llegar.md) · [ADR 0019](../decisiones/0019-perfiles-de-llegadas-en-toml.md)

## 2026-10-29 · Tarea 3.2 — Log de eventos

**Qué se hizo:** `events.py` con el catálogo de 13 tipos, el sobre de 12 campos, `EventLog` con un sink en memoria o JSONL y la lectura línea a línea. Se arregló la normalización pendiente de la 3.1.

**Qué aprendí:**
- En *event sourcing* el log solo crece y el estado se calcula recorriéndolo. Por eso tiene que ser exacto y cerrado.
- Validar al emitir hace que un error salte en el primer evento, no en la línea 100.000.
- Los bytes de un JSON son reproducibles si fijo el orden de claves, la codificación, el salto de línea y el identificador.
- Truncar y redondear solo se distinguen pegados a un cambio de segundo o de día. Los casos límite se eligen a propósito.
- Un tipo inmutable puede romper `pickle`. Hay que pensar en cómo se usará el código, no solo en lo que pide el test.

**Qué costó o falló:**
- Sin la comprobación de nan, `math.floor` seguía lanzando un error. Solo exigir que el mensaje nombre `sim_time` detectó el cambio.
- La predicción de la versión `uuid4` se quedó corta: la ida y vuelta compara con un segundo log emitido aparte.
- El prompt pedía buscar "reevaluación" con tilde en un catálogo sin tildes. Claude Code lo preguntó antes de escribir el test.

**Preguntas abiertas:** ninguna.

**Enlaces:** PR #20 · [ADR 0027](../decisiones/0027-log-jsonl-con-sobre-comun.md)

## 2026-10-29 · Tarea 3.3 — El paciente como proceso

**Qué se hizo:** el proceso del paciente con tres pools FIFO, `simulate_ed` con las llegadas del hito 2, el ground truth y las primeras invariantes. Primer log completo y reproducible: 14 días, 4.439 pacientes y cero violaciones.

**Qué aprendí:**
- El box se retiene con un `with` que envuelve toda la estancia; el médico se pide y se suelta en cada valoración. Así se ve por qué el box es el cuello de botella.
- Emitir el evento de fin antes de liberar el recurso deja el relevo en orden en el log.
- "Llegadas = salidas + dentro" calculado solo con el log no puede fallar. Comprobarlo contra el ground truth sí prueba algo.
- `now + (t − now)` no siempre es t: en una de cada 92.000 llegadas cambia el último bit.
- El log cuesta 18 µs por evento y SimPy, 4. Si un día hace falta velocidad, ya sé dónde mirar.

**Qué costó o falló:**
- Las invariantes no vieron un `test_resulted` adelantado: el orden era válido. Solo lo detectaron los tests con instantes conocidos.
- Sortear al asignar el box pasó varios tests, porque con 30 boxes en 3 días el orden coincidía con el de llegada.
- La especificación pedía llegadas idénticas bit a bit en el log. Se corrigió: bit a bit en el ground truth y como mucho a 1 ulp en el log.

**Preguntas abiertas:** ninguna.

**Enlaces:** PR #21 · [ADR 0024](../decisiones/0024-paciente-como-proceso-con-sorteos-al-llegar.md) · [ADR 0028](../decisiones/0028-ground-truth-del-motor-aparte.md)

## 2026-10-30 · Tarea 3.4 — Prioridad y desalojo

**Qué se hizo:** boxes y médicos con prioridad `(nivel, llegada)`, desalojo solo del nivel 1 con reanudación, el laboratorio como proceso propio y las invariantes "nadie se cuela" y "desalojo". Un test fija el comportamiento de SimPy 4.1.2.

**Qué aprendí:**
- Con la tupla, quien vuelve a pedir un recurso se coloca por su llegada y no por cuándo pide.
- SimPy solo intenta conceder la cabeza de la cola. Por eso basta con decidir el desalojo al pedir.
- Leer el código de la biblioteca y fijarlo con un test sacó a la luz detalles que el diseño no veía.
- Si la etapa avanza después de emitir su evento, una interrupción no pierde ni duplica nada.
- La prioridad casi no cambia la espera media: la reparte. El nivel 1 deja de esperar y el 5 espera cuatro veces más.

**Qué costó o falló:**
- Con la configuración real solo hubo 4 desalojos en 14 días. Para ejercitar el desalojo hicieron falta escenarios a mano y una prueba de estrés.
- Ninguna invariante vio la valoración reiniciada ni las pruebas como `timeout` del paciente.
- La versión E la detectó el control de que el estrés ejercita lo que dice, no una invariante.

**Preguntas abiertas:** ninguna.

**Enlaces:** PR #22 · [ADR 0025](../decisiones/0025-tres-pools-con-prioridad-y-desalojo-del-nivel-1.md) · [documentación de recursos de SimPy](https://simpy.readthedocs.io/en/latest/topical_guides/resources.html)

## 2026-11-02 · Tarea 3.5 — Turnos y calentamiento

**Qué se hizo:** plantilla por turnos con reservas de capacidad, `staffing_changed` desde el minuto 0, la capacidad comparada con la plantilla vigente y `warmup_days`. Dos días de calentamiento bastan, con margen.

**Qué aprendí:**
- Un recurso de SimPy no cambia de capacidad. Las plazas que sobran las ocupan peticiones del motor que esperan a que alguien termine.
- Cancelar y liberar no son lo mismo: liberar una reserva que espera la deja en la cola como una reserva fantasma.
- Un error por defecto, una plantilla que se queda corta, no lo ve ninguna invariante de máximos.
- El orden de lo simultáneo se puede diseñar, en vez de depender de cómo desempata SimPy.
- El calentamiento se mide frente al mismo día de la semana siguiente. Frente a la media de la semana, el lunes parece arranque vacío.

**Qué costó o falló:**
- El primer test de "la plaza de las 22:00 va a la reserva" pasaba también con la versión ingenua. Hizo falta otro que comprueba que el cambio de turno es el primer evento de su instante.
- La regla del `anterior` detectó un error de contabilidad que no estaba en la predicción.

**Preguntas abiertas:** ninguna.

**Enlaces:** PR #23 · [ADR 0026](../decisiones/0026-plantilla-por-turnos-con-reservas.md) · [ADR 0029](../decisiones/0029-calentamiento-y-horizonte-en-dias-completos.md)

## 2026-11-02 · Tarea 3.6 — Estado, métricas y validación del motor

**Qué se hizo:** `analysis.py` pliega el log en episodios, escaleras y métricas en la ventana. `validation.py` compara con Little, la M/G/1, la Mₜ/G/∞, la capacidad infinita y "más médicos". Fue la primera tarea con revisión solo del PR.

**Qué aprendí:**
- Las invariantes dicen si el log es coherente; la validación, si es correcto donde hay teoría.
- La identidad de utilización es exacta porque compara dos caminos de cálculo distintos sobre el mismo log.
- El triaje, con λ constante y una enfermera, es una M/G/1 de verdad. La variabilidad del servicio, no solo su media, produce espera.
- La curva de carga ofrecida de la sesión conceptual se convierte en un test con la Mₜ/G/∞.
- La potencia no depende solo del tamaño del efecto: con 5 réplicas y una cola con memoria larga, un 49 % no se veía.

**Qué costó o falló:**
- La recomendación de 5 réplicas en la revisión del plan fue un error, y lo descubrió la medida.
- Little calculado con todos los que terminan pasaba, porque los recortes se compensan a medianoche. Solo lo vio un test a mano.
- Quedó deuda para el cierre: ayudantes copiados entre `arrivals/` y `engine/`.

**Preguntas abiertas:** ninguna nueva; los hallazgos del modelo pasan a la 3.9.

**Enlaces:** PR #24 · [ADR 0030](../decisiones/0030-validacion-del-motor-por-niveles.md) · [ADR 0008](../decisiones/0008-claude-code-escribe-el-codigo.md)

## 2026-11-02 · Tarea 3.7 — CLI `edsim motor simular` y `edsim motor validar`

**Qué se hizo:** dos subcomandos con resumen, tabla de validación, los CSV del ground truth y cuatro gráficas. La presentación vive en `engine/report.py`.

**Qué aprendí:**
- En una capa fina lo que importa es el orden de las comprobaciones: ningún error de uso deja ficheros a medias.
- `simular` relee el fichero que acaba de escribir, así el resumen describe exactamente lo que recibirá el laboratorio.
- Un test lento se puede sustituir por un resultado pequeño construido a mano, si lo que se prueba es la interfaz.
- Una referencia calculada por otro camino vale más que copiar la fórmula del código.
- Las medias esconden los días malos: con una ocupación del 70 %, tres días del mes los niveles 4 y 5 esperan una hora o más.

**Qué costó o falló:**
- El solape de etiquetas y un contorno que caía a 0 solo se vieron al abrir los PNG con datos reales.
- `test_validar_motor_de_verdad` repetía `validate_engine` entero y alargaba el CI 2 minutos. Quedó para la 3.8.

**Preguntas abiertas:** ninguna nueva; el hallazgo de los días punta pasa a la 3.9.

**Enlaces:** PR #25 · [ADR 0028](../decisiones/0028-ground-truth-del-motor-aparte.md)

## 2026-11-02 · Tarea 3.8 — Notebook de exploración del motor

**Qué se hizo:** `notebooks/03_motor_exploracion.ipynb` con 12 secciones, y en el paquete los escenarios didácticos, la línea de tiempo, el Gantt y el cumplimiento de Manchester por día. `validate_engine` se ejecuta una sola vez en los tests lentos.

**Qué aprendí:**
- Plegar solo el prefijo del log da lo que se sabía en un instante: es la base de las *features* sin *data leakage*.
- Repartir intervalos en carriles por orden de inicio usa el mínimo de carriles posible.
- Un médico menos suma 19 min de espera el lunes y 3 el domingo. La plantilla se dimensiona con el día punta.
- Para calibrar hay que contar los días fuera de objetivo, no mirar la media.
- Emparejar por semilla reduce la varianza, pero el sistema no es monótono paciente a paciente.

**Qué costó o falló:**
- Un test pasó por casualidad: el episodio elegido coincidía por posición y por identificador. Se arregló con el test que faltaba, no cambiando la predicción.
- Una trasposición no se notaba con un solo día ni mirando solo la forma.
- El Gantt de tres boxes tiene 3 carriles y no 4. Se corrigió razonando los instantes.
- Una de las 16 gráficas tenía un título que contradecía los datos. Ningún test lo habría visto.

**Preguntas abiertas:** ninguna nueva; los hallazgos pasan a la 3.9.

**Enlaces:** PR #26 · [ADR 0018](../decisiones/0018-notebooks-jupyter-sin-logica.md)

## 2026-11-03 · Tarea 3.9 — Cierre del hito 3

**Qué se hizo:** ADRs 0024 a 0030, notas en la 0008 y la 0019, este diario y la exportación del diseño y de la especificación. Se pagó la deuda de ayudantes duplicados en `edsim/checks.py` y `time_in_window`, y se cerraron los dos pendientes del notebook 03.

**Qué aprendí:**
- Una refactorización se demuestra con la suite completa y las huellas sin tocar, no con tests nuevos.
- Mover código entre módulos puede crear una importación circular. `ValidationResult` tuvo que ir al módulo común.
- Quitar un solo evento del log da 2.515 violaciones, y casi todas son de una regla: el paciente sin `box_assigned` sigue esperando box toda la ejecución, y todos los que reciben box después "se cuelan".

**Qué costó o falló:**
- La deuda no estaba donde decía el prompt: `_check_number` vive en la validación de los TOML, no en los módulos de validación estadística.

**Preguntas abiertas:**
- ¿Desde cuándo cuenta el reloj de Manchester, desde la llegada o desde el triaje? El nivel 2 queda fuera 25 de 26 días, con unos 6 minutos de triaje dentro de su puerta-médico.
- ¿El nivel 1 debe esperar detrás de un triaje FIFO? Hoy tarda unos 9 minutos hasta el médico, frente al "inmediato" de Manchester.
- ¿Cómo se calibra el centro "holgado"? La media parece cómoda (estancia de 88 min, ocupación del 70 %), pero los niveles 4 y 5 esperan horas en unos pocos días punta. Hay que calibrar con el porcentaje de días fuera de objetivo.

**Enlaces:** PR #27 · ADRs 0024 a 0030

## Reflexiones de Pedro
