# Diario · Hito 7 — Persistencia

Lo registrado, bronce y la comparación con la verdad: EDsim produce datos con los fallos de un hospital, los guarda en Postgres y dice exactamente en qué se equivocan. Especificación, anexo y balance en [docs/specs/hito-7.md](../specs/hito-7.md); decisiones en los ADR [0084](../decisiones/0084-simulador-del-registro-clinico.md) a [0099](../decisiones/0099-ocho-tareas-en-dos-pistas-y-etiqueta-v0-7-hito7.md).

## 2026-11-14 · Tarea 7.0 — Proceso del hito 7

**Qué se hizo:** las siete mejoras de la decisión 98: el formato del plan, el subagente `revisor-plan`, las skills por `gh api` REST, la nube por defecto, la revisión del chat a la medida, la Release lanzable sola y el piloto `@claude`.

**Qué aprendí:**
- En una regla de permisos de Claude Code, `*` casa también con espacios y opciones. Por eso una lectura lleva la ruta justo detrás de `gh api`, y una escritura, `-X` delante. Si no, una regla para leer deja pasar una escritura con la opción detrás de la ruta.
- «Fusionado» es `merged == true`: un PR abierto también trae `merge_commit_sha`, el de su merge de prueba.
- La acción `@claude` solo se ejecuta con el `claude.yml` de `main`: un cambio en la condición se prueba después de fusionarlo.

**Qué costó o falló:**
- El `deny` de la fusión con `*merge*` denegaba también las lecturas que piden `merged` en el `--jq`; se acotó a la ruta de la fusión (`d3973eb`).
- El chat encontró en el plan cuatro bloqueantes, entre ellos que el piloto con una revisión no habría corrido nunca.

**Preguntas abiertas:**
- ¿Un hook `PreToolUse` que lea los argumentos de `gh api` sería más robusto que las reglas con comodines? Va como propuesta en el balance.

**Enlaces:** PR #126 · [ADR 0098](../decisiones/0098-tarea-7-0-de-proceso.md) · [portabilidad.md, los permisos de `settings.json`](../proceso/portabilidad.md#claudesettingsjson-lo-que-el-agente-puede-hacer)

## 2026-11-14 · Tarea 7.1 — Simulador del registro clínico

**Qué se hizo:** `edsim.clinical_record` con `Record`, los ocho despistes con un dado inyectable, la emisión, la renumeración, el corte, la libreta, la cuenta y los esquemas `registro-v1` a `v4`. Fue la primera tarea con el revisor del plan.

**Qué aprendí:**
- Lo registrado no puede conservar la numeración de la verdad: un hueco delataría el olvido. Por eso es una ejecución derivada y se renumera en orden de anotación (con los ids de la verdad, V1, fallan 10 tests).
- `sim_time` pasa a significar el minuto en que el sistema escribe: así el pacer del hito 6 no cambia, y el desorden sale solo del retraso.
- `exp(log 7)` da 6,999999999999999: el cuantil se escribe `mediana · exp(sigma · z)` para que z = 0 dé la mediana exacta.

**Qué costó o falló:**
- La revisión encontró, entre otros, un `OverflowError` con una z enorme y una cuenta que ningún test descuadraba (`7b0c502`, `023b325`).
- Dos decisiones de Pedro al aprobar el plan: `retraso_min` con una sola definición y la edad invertida literalmente, con errores inverosímiles a propósito.

**Preguntas abiertas:**
- Ninguna que quede del hito: el flujo real del dado llegó en la 7.2.

**Enlaces:** PR #129 · [ADR 0084](../decisiones/0084-simulador-del-registro-clinico.md) · [ADR 0086](../decisiones/0086-ocho-despistes-y-correccion-tardia.md) · [ADR 0088](../decisiones/0088-libreta-y-ejecucion-derivada.md)

## 2026-11-14 · Tarea 7.5 — Postgres con TimescaleDB y consumidor de bronce

**Qué se hizo:** Postgres con TimescaleDB `2.31.0-pg17` en `compose.yaml`, el extra `postgres`, las migraciones, las tablas de `bronce`, el consumidor, `edsim almacen preparar` y `consumir`, `read_bronze_lines` y el job `tests-integracion`. Fue la pista B, en paralelo con la 7.1.

**Qué aprendí:**
- «Guardar y después apuntar» da «al menos una vez»; con una clave única y `ON CONFLICT DO NOTHING`, una relectura no repite filas.
- Timescale exige la columna de partición en toda clave única: la clave es (`event_id`, `ingest_time`), y sin `ingest_time` falla `create_hypertable` (V14).
- Un mensaje que rompe el `INSERT` bloquea el consumidor para siempre, porque relee el mismo lote. Lo que se sabe que rompe va a `rechazados`, y lo que nadie previó lo recoge una red con un `SAVEPOINT` por fila.

**Qué costó o falló:**
- La sesión local se cortó tres veces porque WSL se quedaba sin memoria. La causa era V16: un test de la CLI giraba sin fin contra un doble que guardaba cada llamada, y llegó a 7,5 GB en un minuto. Se resolvió con el tope `RunawayLoop` en el doble (`bd6457f`), `.wslconfig` con `memory=7GB` y `swap=8GB` y, para todos los tests, el #131 (PR #132): `pytest-timeout` y `check_calls`.
- Codex encontró dos fallos ciertos: `--run` daba por completa una publicación vieja y un JSON muy anidado tumbaba el consumidor (`6345783`, `690f6ac`).

**Preguntas abiertas:**
- ¿Cómo parar `--run` cuando otro productor publica sin parar en los mismos topics? Hoy llega al `timeout`.

**Enlaces:** PR #130 · [ADR 0089](../decisiones/0089-postgres-con-timescaledb-en-compose.md) a [0093](../decisiones/0093-tres-capas-de-tests-y-tests-integracion.md) · [TimescaleDB, claves únicas](https://www.tigerdata.com/docs/learn/data-model/primary-keys-time-and-uniqueness)

## 2026-11-14 · Tarea 7.2 — Perfiles del registro clínico y `registro generar`

**Qué se hizo:** el dado real (`StreamDice`), la carga y la validación de `config/registro_clinico.toml` con sus tres perfiles, `record_run` y `edsim registro validar` y `generar`.

**Qué aprendí:**
- Para que el consumo de un flujo aleatorio sea fijo de verdad, se sacan uniformes y se invierte la normal: el *ziggurat* de `standard_normal` gasta un número variable de bits.
- «Realista ⊂ hostil» tiene dos salvedades que salen de las tasas: el hostil corrige menos, y el vacío del `destino` se une al valor erróneo.
- Ninguna fuente da tasas de despiste de urgencias: los valores son orientativos, y las fuentes dan solo órdenes de magnitud de los tiempos.

**Qué costó o falló:**
- V8 hizo fallar un test no previsto: el zip de `archive` guarda el `mtime` de cada fichero.
- La nota de que la clase `con_despistes` era «sobre todo el reloj» resultó falsa en el realista; la corrigió la 7.6.

**Preguntas abiertas:**
- ¿Hará falta un `--forzar` para volver a escribir lo registrado?

**Enlaces:** PR #133 · [ADR 0087](../decisiones/0087-tres-perfiles-y-el-truco-del-dado.md)

## 2026-11-14 · Tarea 7.3 — Comparación con la verdad

**Qué se hizo:** `compare`, con la conciliación, el retraso por sistema y los indicadores ingenuos; `edsim registro comparar`, también con `--postgres` y `read_bronze_records`.

**Qué aprendí:**
- Un indicador ingenuo se desvía de la verdad: con el realista, el censo medio sale 50,74 frente a 39,37, por los fantasmas; con el hostil, el tiempo hasta el médico sale 7,06 frente a 14,89, porque los relojes del HIS y de admisión restan 8 minutos.
- El retraso medido como `recorded_time − event_time` cancela el desfase del reloj, que se suma a las dos horas.

**Qué costó o falló:**
- Dos tests no distinguían su versión incorrecta y se arreglaron antes de lanzarlas: el de dos publicaciones (V31) y el del reparto con correcciones (V10).

**Preguntas abiertas:**
- ¿Merece la pena que `comparar` compruebe la tercera igualdad leyendo `registro.json`?

**Enlaces:** PR #134 · [ADR 0096](../decisiones/0096-una-sola-comparacion-en-python.md)

## 2026-11-15 · Tarea 7.4 — Directo y reemisión con el registro clínico

**Qué se hizo:** `--registro` en `directo lanzar` y `reemitir`: la sala de espera, el censo, el `inicio` con el bloque `registro` y «directo = lotes» de lo registrado con las versiones 1 a 4.

**Qué aprendí:**
- Una sala de espera suelta un registro cuando `s ≤ peek()`: ningún hecho futuro tiene `sim_time` menor que el del motor. En el empate decide la posición, no la llegada (V36).
- Lotes y directo comparten los despistes, pero no la ordenación: así «directo = lotes» compara dos ordenaciones distintas.

**Qué costó o falló:**
- `pytest-timeout` no estaba en el `.venv` local: tras el #132 solo se hizo `git pull`, sin `/sincronizar`. Con el `uv sync`, la N2 cayó tres veces en un test de 73 s con xdist, que pasó a llevar `timeout(180)` por decisión de Pedro.
- `test_consumidor_en_vivo_igual_a_batch[hito4]` falló una vez con −25 ms de latencia: compara el reloj del broker, en Docker, con el de WSL.

**Preguntas abiertas:**
- ¿Cómo hacer estable un test que compara relojes de dos máquinas?

**Enlaces:** PR #135 · [ADR 0085](../decisiones/0085-registro-clinico-funcion-pura-de-la-verdad.md)

## 2026-11-15 · Tarea 7.6 — Notebook `07_persistencia`

**Qué se hizo:** el notebook 07: Lucía y el escenario L, los tres perfiles, la tabla «verdad frente a registrado», bronce con SQL y las dos clases de duplicados, con modo rápido sin Docker. Pedro ejecutó en local el modo normal, y pasa entero.

**Qué aprendí:**
- Dentro de `con_despistes`, en el realista manda el retraso (81,7 % de las filas) y en el hostil, el reloj (100 %). Las cifras de las notas también se miden.
- Una republicación da el doble de filas con los mismos `event_id` (110.236 y 55.118): la clave lleva la hora de llegada, y bronce guarda lo que llegó.

**Qué costó o falló:**
- `record_run` leía el TOML relativo al directorio de trabajo, y el notebook corre desde `notebooks/`: lo destapó V2.
- El chat predijo que la republicación pararía sin leer. No falló, por el `KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS: 0` de `compose.yaml`.

**Preguntas abiertas:**
- La parada de `--run` en una republicación depende de ese retraso: ¿se arregla antes del hito 8?

**Enlaces:** PR #136 · `notebooks/07_persistencia.ipynb`

## 2026-11-15 · Tarea 7.7 — Cierre del hito 7

**Qué se hizo:** los ADR 0084 a 0099, este diario, el diseño al día («capa de observación» pasa a «simulador del registro clínico»), el balance del hito, las lecciones y la portada. Es el primer uso de `/cerrar-hito`.

**Qué aprendí:**
- Un ADR recoge también cuándo tendría sentido cada alternativa descartada: así se puede volver a la decisión sin rehacer la sesión conceptual.
- El cierre es donde se ve lo que ninguna tarea tocó: el diseño seguía diciendo que el ground truth guarda los defectos.

**Qué costó o falló:**
- El cuerpo del #136 y la API no daban la misma hora de apertura; el balance usa la API.

**Preguntas abiertas:**
- Las propuestas de velocidad del balance, por decidir.

**Enlaces:** PR de la 7.7 · [balance del hito](../specs/hito-7.md#balance-del-hito)

## Pedro sabe explicar

Los criterios del hito piden que Pedro sepa explicar estas ideas. Cada una, en pocas líneas, con las cifras del hito.

- **Por qué lo registrado se renumera.** La verdad numera sus eventos seguidos (`r2026-000000001`, `…002`…). Si lo registrado conservara esa numeración, cada olvido dejaría un hueco y cada duplicado repetiría un número: las soluciones irían dentro del examen. Con 14 días de `config/` y la semilla 2026, el realista olvida 262 hechos y duplica 263: serían 262 huecos y 263 números repetidos. Por eso lo registrado es una ejecución derivada (`r2026_realista_s2026`) que se numera de nuevo en el orden en que se anota, y las soluciones van aparte, en la libreta.
- **El truco del dado.** Cada evento verdadero tira siempre los mismos 13 números, en el mismo orden y sea cual sea el perfil; el perfil solo pone el umbral. Si el dado del valor erróneo saca 0,03, con el realista (tasa 0,01) no pasa nada y con el hostil (0,07), sí. Como el dado es el mismo, todo lo que falla en el realista falla también en el hostil: con la semilla 2026, los olvidos del realista están todos dentro de los del hostil. Al comparar perfiles, la diferencia es del perfil, no de la suerte (números comunes, decisión 43).
- **Por qué el consumidor guarda y después apunta.** Si apunta primero y se cae antes de guardar, al volver cree que ya guardó: pierde mensajes. Si guarda primero y se cae antes de apuntar, al volver los lee otra vez, y la clave única los ignora. En el ejemplo de la 7.5, 7 mensajes en lotes de 3 con una caída al confirmar el segundo lote dejan 7 filas y 3 repetidos ignorados; apuntando antes (V13), se pierden 3.
- **Por qué la clave única lleva la hora de llegada.** Timescale parte `bronce.eventos` por `ingest_time`, y exige que toda clave única incluya esa columna: sin ella, `create_hypertable` falla (V14). Además, `ingest_time` distingue una relectura (la misma llegada) de una republicación (otra llegada).
- **Las dos clases de duplicados.** El doble clic del hospital son dos registros con números distintos: el realista tiene 263, y bronce guarda los dos. La relectura del consumidor es el mismo registro, con el mismo número y la misma hora de llegada: en el notebook 07, volver a guardar 5 mensajes que bronce ya tiene da 0 guardados y 5 repetidos. Y una tercera cosa que no es un duplicado: reemitir la misma ejecución es otra llegada, así que bronce pasa de 55.118 a 110.236 filas con los mismos 55.118 `event_id`.
- **Por qué un indicador ingenuo se desvía.** Un analista con prisa toma el primer registro, ignora los vacíos y no aplica las correcciones. Con el realista, el censo medio sale 50,74 pacientes frente a 39,37 de verdad (+28,9 %), porque las salidas olvidadas dejan fantasmas. Con el hostil, ×3,96, y el tiempo hasta el médico sale 7,06 min frente a 14,89, porque el reloj del HIS va 5 min atrasado y el de admisión, 3 adelantado.

## Reflexiones de Pedro
