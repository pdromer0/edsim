# Diario · Hito 6 — Tiempo real

Especificación: [docs/specs/hito-6.md](../specs/hito-6.md). Su anexo tiene el detalle de cada tarea: decisiones del diff, medidas y versiones incorrectas. Las decisiones del hito son las ADR [0048](../decisiones/0048-hito-6-antes-que-el-5.md) a [0066](../decisiones/0066-run-id-del-directo.md).

## 2026-11-08 · Tarea 6.1 — Kafka en local

**Qué se hizo:** `compose.yaml` con Kafka 4.4.0 en modo KRaft combinado y Redpanda Console v3.13.1, el extra opcional `kafka` (`confluent-kafka` 2.16.1), el test de frontera ampliado al cliente, `tests_integracion/` con la prueba de humo, `scripts/tests-integracion.sh` y el job `tests-kafka` del CI.

**Qué aprendí:**
- Un cliente de Kafka se conecta en dos pasos: llama a la dirección de arranque y vuelve a llamar a la que le anuncia el broker. Por eso hay dos listeners, uno para cada lado de Docker.
- La imagen de Kafka configurada solo con variables escribe un `server.properties` sin sus valores por defecto: con un nodo hay que bajar a 1 la réplica de los topics internos.
- El aviso `GETPID` («Coordinator load in progress») del primer productor idempotente tras arrancar Kafka es normal: librdkafka reintenta solo.

**Qué costó o falló:**
- Con un listener mal anunciado, el resultado dependía de una carrera de librdkafka (de 10 s a 3 min 30 s, sin decir la causa). La fixture `bootstrap` comprueba en tres pasos que cada dirección anunciada se alcanza, y falla en menos de 1 s con la causa.
- La completa tardó 6 minutos más con Kafka en marcha: desde la 6.2 se mide sin contenedores.

**Preguntas abiertas:**
- Redpanda Console v3.14.0 (resuelta en la 6.6: se queda la v3.13.1).

**Enlaces:** PR #56 · [ADR 0049](../decisiones/0049-subpaquete-live-y-extra-kafka.md) · [ADR 0062](../decisiones/0062-versiones-fijadas.md) · [ADR 0063](../decisiones/0063-job-tests-kafka.md) · [ADR 0065](../decisiones/0065-simulador-fuera-de-docker.md)

## 2026-11-08 · Tarea 6.2 — Motor por pasos y censo inicial

**Qué se hizo:** el motor avanza evento a evento (`peek`, `step`, `advance_until`, `alive_episodes`, `finish`) sin cambiar un byte del log, `TERMINAL_EVENTS` por versión del catálogo y el censo inicial (`open_episodes`, `census`, `live_events`).

**Qué aprendí:**
- `run(until)` de SimPy es un bucle de `step()`: el batch y el directo pueden compartir el mismo bucle.
- El censo como eventos del log, y no como una foto del estado, deja al consumidor un solo código para el censo y el directo.
- «Abierto» depende del catálogo: los eventos terminales van por versión, junto a `CATALOGS`.

**Qué costó o falló:**
- Varias versiones incorrectas (un terminal con `<=`, el censo con los recursos al final) solo las ve un test construido para ellas: ni la ejecución de referencia ni el log a mano las ejercitan.

**Preguntas abiertas:**
- Ninguna.

**Enlaces:** PR #57 · [ADR 0051](../decisiones/0051-motor-por-pasos.md) · [ADR 0058](../decisiones/0058-censo-inicial-con-eventos.md)

## 2026-11-09 · Tarea 6.3 — Reloj, pacer, órdenes y directo en memoria

**Qué se hizo:** el reloj inyectable (`SystemClock`, `FakeClock`), las órdenes (`ScriptedControl`, `NoControl`), el pacer con objetivos absolutos, `run_live` con el motor y con un log guardado, el anclaje al calendario y «directo = batch» en las versiones 1, 2 y 3.

**Qué aprendí:**
- Esperar hasta instantes absolutos desde un ancla, y reanclar al cambiar la velocidad, evita que los excesos de cada `sleep` se sumen.
- Un reloj falso en coma flotante se equivoca: 150 tramos de 0,2 s suman 29,999999999999925 s. En nanosegundos enteros, 30 s exactos.
- `dataclasses.replace` no es inocuo: vuelve a ejecutar `__post_init__` y renormaliza el perfil de llegadas.

**Qué costó o falló:**
- Cambiar la fecha del perfil con `replace` movía el último bit de 16 factores y el log desde el minuto 3.324. Se resolvió con `with_start_date`, comprobado bit a bit contra un TOML con esa fecha.

**Preguntas abiertas:**
- `runs/offered.py` sigue usando `replace` para la carga ofrecida (fuera del hito).

**Enlaces:** PR #58 · [ADR 0052](../decisiones/0052-pacer-sincrono-con-objetivos-absolutos.md) · [ADR 0059](../decisiones/0059-dos-arranques-fecha-del-perfil-o-anclado.md)

## 2026-11-09 · Tarea 6.4 — Esquemas, topics, mensajes y Kafka

**Qué se hizo:** JSON Schema generado del catálogo, los cuatro topics y su creación (`ensure_topics`), los mensajes de `ed.runs` y `ed.control`, el `KafkaSink` idempotente y `KafkaControl`, con tests sin broker y de integración.

**Qué aprendí:**
- Enviar es asíncrono: `produce` deja el mensaje en una cola, y el resultado llega después, en un aviso de entrega que se sirve con `poll`.
- Un `fin` publicado antes de las confirmaciones puede decir «horizonte» de una ejecución incompleta: primero `flush`, después decidir.
- El esquema tiene que decir lo mismo que el validador de Python; lo que no puede expresar se escribe en una lista y se prueba en los dos sentidos.

**Qué costó o falló:**
- Justo después de crear un topic, a veces no aparecía en los metadatos (7 de 60): `ensure_topics` espera a verlos.
- La revisión de Codex encontró dos fallos: el `fin` antes de las confirmaciones y un entero de 401 cifras que paraba el directo sin aviso (`edsim.finite.to_float`).

**Preguntas abiertas:**
- Las comprobaciones de fuera del directo con el mismo hueco de los enteros enormes (para una tarea de proceso).

**Enlaces:** PR #59 · [ADR 0054](../decisiones/0054-cuatro-topics-con-reparto-por-episodio.md) · [ADR 0055](../decisiones/0055-productor-idempotente-y-al-menos-una-vez.md) · [ADR 0056](../decisiones/0056-valor-jsonl-y-hora-de-llegada-del-broker.md) · [ADR 0057](../decisiones/0057-json-schema-generado-del-catalogo.md)

## 2026-11-09 · Tarea 6.5 — CLI `edsim directo`

**Qué se hizo:** `edsim directo preparar`, `lanzar`, `reemitir` y `control`, la línea de estado cada 10 s, Ctrl+C con su `fin` y los errores de uso antes de conectar. Comprobado en vivo con Pedro: un corte de Kafka de casi un minuto sin perder ni repetir un evento.

**Qué aprendí:**
- `len(producer)` cuenta también los mensajes ya confirmados cuyo aviso no se ha servido: los pendientes se cuentan tras `poll(0)`.
- Una línea cada 10 s calculada desde la anterior arrastra el retraso; una rejilla fija desde el ancla, no.
- Un corte del broker retrasa la confirmación, no la publicación: los publicados siguen igual y los pendientes vuelven a 0 al volver Kafka.

**Qué costó o falló:**
- Durante el corte, librdkafka escribía unas 22 líneas por segundo en stderr y enterraba la línea de estado (resuelto en la 6.6).

**Preguntas abiertas:**
- Por qué el consumidor de órdenes reintentaba cada 50 ms (resuelta en la 6.6).

**Enlaces:** PR #60 · [ADR 0053](../decisiones/0053-control-en-vivo-por-ed-control.md) · [ADR 0060](../decisiones/0060-replay-con-el-mismo-pacer.md) · [ADR 0061](../decisiones/0061-horizonte-finito-y-fin-limpio.md) · [ADR 0066](../decisiones/0066-run-id-del-directo.md)

## 2026-11-09 · Tarea 6.6 — Cierre: ruido de librdkafka, consumidor y notebook 06

**Qué se hizo:** el vigilante de la conexión (`BrokerWatch`): un aviso al perder Kafka y otro al recuperarlo, y el resumen de librdkafka al final (`--registro-kafka FICHERO` para guardarlo entero). El consumidor del paquete, `read_run` y `LiveTracker`, con consumidor = batch. El notebook 06, las ADR 0048 a 0066 y este cierre.

**Qué aprendí:**
- El consumidor de órdenes reintentaba cada 50 ms por el grupo, no por su partición: la biblioteca exige un `group.id`, librdkafka busca entonces el coordinador del grupo y pide conexiones cada `reconnect.backoff.ms` / 2, sin retroceso exponencial.
- Un `_TRANSPORT` no siempre es un corte: el broker cierra las conexiones inactivas a los 10 minutos. Se cruza con las estadísticas del cliente (¿hay algún broker `UP`?).
- Un grupo de consumidores recuerda su posición: para releer, otro grupo; y `earliest`, para que un grupo nuevo empiece por el principio.
- Con la confirmación automática activada, librdkafka confirma también al cerrar el consumidor: el retraso del grupo queda en 0 aunque falte el `commit` final.

**Qué costó o falló:**
- La V11 (sin `commit` final) no la detectaba la integración, por la confirmación al cerrar; se añadió al test de la configuración que la confirmación automática no se desactiva.
- Las predicciones de V7 y V14 se quedaron cortas: más tests de los contados simulan un corte o pasan líneas por el `logger`.

**Preguntas abiertas:**
- Publicar el puerto de la consola solo en la máquina (`127.0.0.1:8080:8080`), si algún día hace falta.

**Enlaces:** PR de la 6.6 · [ADR 0050](../decisiones/0050-tres-capas-de-tests.md) · [ADR 0055](../decisiones/0055-productor-idempotente-y-al-menos-una-vez.md) · [ADR 0062](../decisiones/0062-versiones-fijadas.md) · [librdkafka 2.16.0, CONFIGURATION.md](https://github.com/confluentinc/librdkafka/blob/v2.16.0/CONFIGURATION.md)

## Reflexiones de Pedro
