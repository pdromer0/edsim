# Diario · Hito 8 — Analítica

dbt, la verdad en Postgres y Grafana: EDsim tiene ya las tablas de un analista de hospital, un cuadro de mando que se mueve con el directo y la medida de cuánto recupera la limpieza. Especificación, anexo y balance en [docs/specs/hito-8.md](../specs/hito-8.md); decisiones en los ADR [0100](../decisiones/0100-alcance-del-hito-8.md) a [0112](../decisiones/0112-notebook-08-y-etiqueta-v0-8-hito8.md).

## 2026-11-16 · Tarea 8.1 — Proyecto dbt, preparación y limpieza

**Qué se hizo:** `analitica/`, un proyecto uv aparte con su lock; `profiles.yml`, las macros `generate_schema_name` y `fuente_registros`, `preparacion.registros` (vista) y `registros_vigentes` (tabla, la limpieza), con ocho unit tests en el job `tests-integracion`.

**Qué aprendí:**
- Un modelo de dbt es un `SELECT`; `ref()` y `source()` dicen de qué depende, y con eso dbt arma el grafo y construye en orden. La materialización decide si es una vista (se calcula al consultar) o una tabla (al construir).
- Un unit test da filas inventadas y prueba la lógica; un test de datos mira la tabla construida y prueba los datos.
- En un `PARTITION BY`, los nulos caen todos en el mismo grupo: los eventos de recursos, sin `episode_id`, se apartan antes de buscar duplicados.
- dbt sale con 0 si no ejecuta nada: el test lee `run_results.json` y exige los unit tests y los modelos.

**Qué costó o falló:**
- El `r2026` del disco era del modelo provisional (esquema 1): lo detectó el revisor del plan, y la medida de la clave de duplicados se repitió (0 pares).
- Tras el primer unit test que falla, `dbt build` salta los demás (SKIP), y el informe solo enseña el primero. Los mutantes comprobaron el resto con `dbt test --select test_type:unit`.
- La revisión encontró que la vista se leía dos veces (`e3caf26`).

**Preguntas abiertas:**
- Ninguna que quede del hito: la medida del sync de `analitica/` en el CI quedó en el PR.

**Enlaces:** PR #149 · [ADR 0101](../decisiones/0101-dbt-en-un-proyecto-uv-aparte.md) · [ADR 0102](../decisiones/0102-preparacion-vigentes-y-reconstruccion-completa.md) · [ADR 0103](../decisiones/0103-limpieza-conservadora.md) · [ADR 0111](../decisiones/0111-tests-de-dbt-y-punta-a-punta.md)

## 2026-11-16 · Tarea 8.2 — El directo publica lo registrado por defecto

**Qué se hizo:** `lanzar` y `reemitir` publican lo registrado realista si no se pide otra cosa; la verdad, con `--verdad`. Solo cambió `src/edsim/cli.py`. Se hizo en la nube.

**Qué aprendí:**
- Un `default=None` distingue «no escrito» de «escrito con el valor por defecto»: la cabecera avisa solo cuando nadie escribió el perfil.
- Cambiar un valor por defecto en la CLI, y no en el paquete, deja intactas las huellas de los hitos 3 a 7.

**Qué costó o falló:**
- Un `--run-id` de más de 49 caracteres deja de caber con el valor por defecto, porque el derivado pasa de 64; el mensaje apunta ahora a `--verdad`, también en `reemitir` (`d9b5bde`).
- El arranque de `lanzar` calcula todo el registro: unos 2 s más con 14 días.

**Preguntas abiertas:**
- Ninguna.

**Enlaces:** PR #150 · [ADR 0110](../decisiones/0110-el-directo-publica-lo-registrado.md)

## 2026-11-16 · Tarea 8.3 — Plata: las ocho tablas con la forma de un HIS

**Qué se hizo:** las ocho tablas de plata, que leen solo `registros_vigentes`; las macros `primero` y `emparejar`; los tests de clave compuesta propios y sus unit tests. En paralelo con la 8.4.

**Qué aprendí:**
- El grano, «una fila por qué», es lo primero que se prueba: si está mal, los KPIs se duplican sin avisar.
- Emparejar inicio y fin por tiempo, con `lag` y `lead`, aguanta un inicio olvidado; emparejar por orden daría duraciones negativas.
- Los tests de datos comprueban la forma, no la lógica: con una versión incorrecta, los 40 siguen en verde.

**Qué costó o falló:**
- `unique` y `relationships` de dbt solo admiten una columna, y sin `dbt_utils` hubo que escribir `clave_unica` y `relacion`.
- La frase del anexo de la 8.1 que decía que apartar los recursos era necesario se corrigió (`59b08c0`).

**Preguntas abiertas:**
- ¿Pesaría plata con un año en bronce? Lo midió la 8.7: `registros_vigentes` es lo más caro.

**Enlaces:** PR #151 · [ADR 0104](../decisiones/0104-ocho-tablas-de-plata.md)

## 2026-11-16 · Tarea 8.4 — La verdad en Postgres y los roles

**Qué se hizo:** la migración `002_verdad.sql` con el esquema `verdad` y los roles `hospital` y `laboratorio`, y `edsim almacen cargar-verdad`, que borra y copia con `COPY` en una transacción. En paralelo con la 8.3.

**Qué aprendí:**
- `COPY` carga 1,4 millones de eventos de un año en 56,6 s con 153 MiB: las filas van de una en una, en generadores.
- Un esquema nuevo no da `USAGE` a `PUBLIC`: `hospital` no entra en `verdad` sin que nadie se lo niegue.
- `ALTER DEFAULT PRIVILEGES` hace que lo que cree `edsim` después nazca legible para `laboratorio`.

**Qué costó o falló:**
- La libreta necesitaba `run_id_origen`: con solo el `run_id` derivado, recargar no sabría qué borrar.
- En V7, la segunda carga falla con una clave duplicada, no con «recuentos dobles», y cae también un test que la predicción no veía.

**Preguntas abiertas:**
- Cuánta memoria pide todo levantado: se midió en el cierre (8.9).

**Enlaces:** PR #152 · [ADR 0105](../decisiones/0105-la-verdad-en-postgres-con-roles.md)

## 2026-11-17 · Tarea 8.5 — Oro, las tres construcciones y la prueba de punta a punta

**Qué se hizo:** oro (censo, cohorte, KPIs por hora, por turno y de la ejecución, y calidad), las semillas, los `grants`, la tabla de tres columnas y la punta a punta, con sus siete tests. Tarea crítica.

**Qué aprendí:**
- Una cohorte de llegada apunta cada espera a la hora en que llegó el paciente.
- El censo, como un torniquete: una suma acumulada de llegadas y salidas, en vez de cruzar cada hora con cada estancia.
- En Postgres, `greatest` ignora los nulos: traducido sin más de Python, quien no tenía salida salía al llegar. Lo cazó la comparación con Python (censo medio de 62,4 frente a 67,375).
- Un `avg` de `double precision` depende del orden de las filas: las medias de oro van con aritmética exacta.

**Qué costó o falló:**
- El plan llevaba una tabla de «sigue dentro» calculada con la semilla 1 del registro en vez de la 2026; la cazó el revisor del plan.
- `grants` de dbt da `SELECT`, pero no `USAGE`: hizo falta la macro `dar_uso_de_esquemas`.
- El PR estuvo abierto toda la noche (510 min de la apertura a la fusión).

**Preguntas abiertas:**
- Las horas futuras de un directo en `kpi_hora`: las cortó la 8.7 con el fin del dato.

**Enlaces:** PR #153 · [ADR 0106](../decisiones/0106-oro-tres-familias-de-kpis.md) · [ADR 0107](../decisiones/0107-tres-construcciones-con-la-variable-hoja.md) · [ADR 0111](../decisiones/0111-tests-de-dbt-y-punta-a-punta.md)

## 2026-11-17 · Tarea 8.6 — Grafana: aprovisionamiento y los tres cuadros

**Qué se hizo:** Grafana 13.3.1 en compose con el perfil `analitica`, las dos fuentes y los tres cuadros desde `grafana/`, y los tests de los paneles y del arranque. En paralelo con la 8.7, en otra carpeta.

**Qué aprendí:**
- Con el aprovisionamiento, el repositorio manda: Grafana lee sus fuentes y sus cuadros al arrancar, y sin volumen cada `up` es un arranque limpio.
- En Grafana 13, un panel *time series* ata su eje al rango de tiempo del cuadro; para el reloj simulado van barras por hora con la hora simulada como etiqueta.
- Grafana no es una frontera de permisos: un visitante anónimo puede consultar la fuente Laboratorio.

**Qué costó o falló:**
- Sin red, Grafana intentaba instalar sus apps por defecto en cada arranque: hizo falta `GF_PLUGINS_PREINSTALL_DISABLED`.
- M4 sobrevivió: la premisa «el valor por defecto pide TLS» era falsa (`902306e`).
- El reloj de Docker Desktop se desfasó al suspender el portátil y dio latencias negativas en los tests (#158).

**Preguntas abiertas:**
- ¿La variable de Urgencias debería abrir con la ejecución más reciente? Va al #159.

**Enlaces:** PR #154 · [ADR 0108](../decisiones/0108-grafana-aprovisionado.md) · [ADR 0109](../decisiones/0109-micro-lotes-de-dbt.md)

## 2026-11-17 · Tarea 8.7 — Tiempo real: micro-lotes de dbt

**Qué se hizo:** el fin del dato en `preparacion.parametros`, `edsim.analytics.refresh` y `edsim analitica refrescar`, y la medida con un año en bronce. En paralelo con la 8.6, en otra carpeta.

**Qué aprendí:**
- Un micro-lote es un periódico que se reimprime cada minuto: oro se reconstruye entero y Grafana lo lee cada 30 s.
- El fin del dato evita horas aún por llegar con un censo congelado: el `fin` de la ejecución o su última anotación, nunca más que el horizonte.
- `subprocess.run` mata al hijo a los 0,25 s de un Ctrl+C: la vuelta tiene que esperar a dbt (`bd9e58d`).

**Qué costó o falló:**
- Con un año en bronce, la vuelta tarda 60,1 s y pasa del intervalo. Pedro lo aceptó para el hito 8, y el plan B pasó al #156.
- Medir en la base compartida habría cambiado lo que veía la otra sesión, porque `ultimo_inicio` ordena por `ingest_time`: la medida fue a `edsim_h87`.
- La integración, con los topics llenos de la medida (1,4 millones de mensajes), dio 5 fallos por tiempo; se recreó Kafka (#158).

**Preguntas abiertas:**
- El fin del dato con el reloj del sistema que anota, y una reemisión a `max`: #159.

**Enlaces:** PR #155 · [ADR 0109](../decisiones/0109-micro-lotes-de-dbt.md)

## 2026-11-17 · Tarea 8.8 — Notebook `08_analitica`

**Qué se hizo:** el notebook 08 (Lucía paso a paso, la tabla de tres columnas, lo que no se arregla y cada regla frente a la libreta), con modo rápido; en el paquete, `bronze_messages` y `write_bronze` para escribir bronce sin Kafka.

**Qué aprendí:**
- La limpieza conservadora apenas mueve los indicadores del flujo: el censo y las medianas salen iguales en ingenuo y limpio.
- Las llegadas ingenuas casi aciertan por casualidad (+3), porque los dobles clics compensan los olvidos; las limpias, −15, las olvidadas en la ventana.
- Las correcciones sin registro son 0 por construcción: una corrección apunta al original, y la limpieza se queda con él.

**Qué costó o falló:**
- El primer intento, en la nube y sin su sesión conceptual, se paró: costó una vuelta.
- La revisión puso `write_bronze` en una transacción (`9d26816`) y dbt contra la misma base que el notebook (`74c2820`).

**Preguntas abiertas:**
- Ninguna que quede del hito.

**Enlaces:** PR #157 · [ADR 0112](../decisiones/0112-notebook-08-y-etiqueta-v0-8-hito8.md) · `notebooks/08_analitica.ipynb`

## 2026-11-18 · Tarea 8.9 — Cierre del hito 8

**Qué se hizo:** las ADR 0100 a 0112, el balance, `docs/diseno.md` (las capas, la hoja de ruta con el hito 9 y el registro), este diario, las lecciones, `portabilidad.md`, la portada y la memoria con todo levantado.

**Qué aprendí:**
- Al cerrar se ve lo que cambió en cada decisión: la 109 decía «si no llega, plan B», y lo que pasó es que no llegó, se aceptó y el plan B quedó como issue.

**Qué costó o falló:**
- Dos fuentes con cifras distintas de la memoria de la 8.7 (las notas del chat y el PR #155): manda el PR.

**Preguntas abiertas:**
- Si el plan B (#156) entra en el hito 9 junto al orquestador.

**Enlaces:** PR de la 8.9 · [balance del hito](../specs/hito-8.md#balance-del-hito)

## Pedro sabe explicar

Los criterios del hito piden que Pedro sepa explicar estas ideas. Cada una, en pocas líneas, con las cifras del hito.

- **Qué es el grano y por qué se prueba.** El grano responde a «¿una fila por qué?». Lucía tiene una llegada, un triaje, dos valoraciones y una analítica con dos pruebas: `episodio` tiene 1 fila, `triaje` 1, `valoracion` 2 y `prueba` 2. Si una tabla tuviera dos filas por episodio sin querer, cada KPI que la cruce se duplicaría sin dar ningún error. Por eso cada tabla de plata tiene su test de clave: con `h8demo` y el perfil realista, 3.776 episodios y 6.277 valoraciones, sin una clave repetida.
- **Por qué la limpieza no arregla el reloj desajustado.** El reloj del triaje va 2 min adelantado en el perfil realista y no deja rastro, salvo si un triaje cae antes de la llegada (un tiempo negativo). Arreglarlo exigiría saber cuánto se desvía cada reloj, y eso solo lo sabe la verdad. Por eso la mediana hasta el triaje sale +2,02 min frente a la verdad, igual en ingenuo y en limpio (en el hostil, +4,05).
- **Por qué hay tres construcciones y no una columna.** Con una columna `hoja` en cada tabla, el hospital solo dejaría de ver la verdad si cada política por filas estuviera bien escrita: un olvido y la ve. Con tres construcciones en sus propios esquemas (`plata`, `verdad_plata`, `ingenuo_plata`), el rol `hospital` no tiene `USAGE` en las otras dos, y el test de permisos lo vigila. Además, el mismo código corrige las tres hojas, así que las diferencias de la tabla de tres columnas vienen de los datos y no de haber programado dos veces.
- **Por qué la mediana de la última hora sale mejor en el directo.** Cada espera se apunta a la hora en que llegó el paciente (la cohorte). En la hora en curso, solo cuentan los que ya han sido triados, que son los rápidos; los que aún esperan no tienen espera que contar. Por eso Urgencias enseña al lado «Pendientes ahora»: la mediana de esa hora empeorará cuando lleguen sus esperas largas.
- **Qué hace `generate_schema_name`.** dbt la llama para cada modelo y decide en qué esquema va. La de serie pone delante el esquema del destino (`public_preparacion`); la de EDsim da `preparacion`, `plata` y `oro` en la hoja del hospital, y `verdad_plata` o `ingenuo_plata` en las otras dos.
- **Por qué micro-lotes y no Quix Streams ni un orquestador.** Quix Streams pide `confluent-kafka<2.12` y EDsim fija la 2.16, y lo que aporta (ventanas y eventos tardíos) es una lección más que una pieza. Un orquestador brilla con lotes que tienen calendario, reintentos e historial, no con una reconstrucción cada minuto, y el consumidor es un servicio que no termina. Con un directo, la vuelta de dbt tarda 3,8 s de mediana; con un año en bronce, 60,1 s. Encaja en el hito 9, con las réplicas.

## Reflexiones de Pedro
