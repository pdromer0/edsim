# EDsim

Simulador de urgencias hospitalarias que genera datos sintéticos realistas, en tiempo real y por lotes, para un laboratorio de analítica: ingeniería de datos, modelos predictivos y análisis de escenarios.

El proyecto se construye paso a paso, por hitos, con un doble objetivo: obtener el sistema y aprender sus fundamentos.

**Estado:** hitos 0 a 6 cerrados (el 6, antes que el 5); el modelo v0 está completo, con abandono, cuatro destinos y espera de cama (`v0.5-hito5`). El siguiente es el hito 7, persistencia ([hoja de ruta](docs/diseno.md#hoja-de-ruta)).

## Requisitos

- [uv](https://docs.astral.sh/uv/getting-started/installation/). Instala Python 3.13 automáticamente según `.python-version`.
- git

## Preparar el entorno

```bash
uv sync                      # crea .venv con el paquete y las herramientas de desarrollo
uv run pre-commit install    # activa los hooks de pre-commit (una vez)
```

## Comandos principales

```bash
uv run edsim --version       # CLI
uv run edsim mm1 comparar    # M/M/1: tabla de teoría frente a simulación
uv run edsim mm1 barrido     # M/M/1: CSV y gráfica de Wq frente a ρ en resultados/mm1/
uv run edsim llegadas generar  # llegadas: dos CSV en resultados/llegadas/
uv run edsim llegadas validar  # llegadas: cinco pruebas y tres gráficas
uv run edsim motor simular   # motor, modelo del hito 5 (config/): log JSONL, ground truth y resumen en resultados/ejecuciones/<run_id>/
uv run edsim motor simular --provisional --centro tests/data/centro_ejemplo.toml  # el modelo provisional del hito 3
uv run edsim motor validar   # motor, con el modelo provisional y su centro: tabla de validación y cuatro gráficas (unos 2 min)
uv run pytest                # tests
uv run ruff check .          # lint
uv run ruff format .         # formato
uv run pre-commit run --all-files
```

## Kafka en local

Desde el hito 6, EDsim publica sus eventos en Apache Kafka. El broker y Redpanda
Console corren en Docker con `compose.yaml`; el simulador, los tests y los notebooks
corren fuera, en WSL2. Detalle en [docs/specs/hito-6.md](docs/specs/hito-6.md), pieza 5.

**Requisitos.** Docker Desktop en marcha, con la integración de WSL2 activada para tu
distribución (Settings → Resources → WSL integration). Comprueba que `docker compose
version` responde desde la terminal de WSL2.

**Entorno.** El cliente de Kafka (`confluent-kafka`) es un extra opcional:

```bash
uv sync --all-packages --extra kafka
```

`uv sync` deja el entorno exactamente como lo pide la orden. Por eso, un `uv sync` o
un `uv sync --all-packages` sin `--extra kafka` **desinstala** el cliente. Sin él, todo
EDsim se importa y sus tests pasan; solo lo que habla con Kafka pide el extra.
`uv run --extra kafka …` lo instala si falta, sin quitar nada.

**Levantar y parar.**

```bash
docker compose up --wait     # arranca Kafka y la consola y espera a que estén sanos (unos 10 s)
docker compose ps            # estado
docker compose logs -f kafka # registro del broker
docker compose stop          # para los contenedores: los topics y los mensajes se conservan
docker compose start         # los vuelve a arrancar tal cual
docker compose down          # para y borra los contenedores
```

Redpanda Console queda en <http://localhost:8080>: topics, particiones, mensajes con
su clave y su marca de tiempo, y grupos de consumidores. El broker no tiene volumen: tras
`down`, el siguiente `up` empieza vacío, sin topics ni mensajes. Para conservarlos, usa
`stop` y `start`.

**Tests de integración.**

```bash
scripts/tests-integracion.sh
```

Si el broker ya está en marcha, lo usa y lo deja así. Si no, lo levanta y lo baja al
terminar. Ejecuta `tests_integracion/`, que no forma parte de `uv run pytest`. Para
probar contra otro broker: `EDSIM_KAFKA=host:puerto uv run --extra kafka pytest tests_integracion`.

**Si el cliente no conecta.** Kafka tiene dos direcciones, una para cada lado de Docker:

| Desde | Dirección | Quién |
| --- | --- | --- |
| WSL2 (fuera de Docker) | `localhost:9092` | Simulador, tests y notebooks |
| Dentro de la red de Docker | `kafka:19092` | Redpanda Console |

El cliente pide al broker la lista de direcciones a la que conectarse y usa la que
le devuelve, no la que le diste. Si desde WSL2 usas `kafka:19092`, el nombre `kafka`
no existe fuera de Docker y la conexión falla. Si un contenedor usa `localhost:9092`,
se llama a sí mismo. Si nada conecta, comprueba con `docker compose ps` que `kafka`
está `healthy` y que el puerto 9092 no lo usa otro programa.

## Directo con Kafka

`edsim directo` publica los eventos del motor en vivo, al ritmo que se le diga. Primero
calienta sin emitir, después publica el censo (la historia de los pacientes que siguen
dentro) y luego cada evento cuando le toca. Detalle en
[docs/specs/hito-6.md](docs/specs/hito-6.md), piezas 1 y 6.

**Preparar y lanzar.**

```bash
docker compose up --wait
uv run edsim directo preparar   # crea los cuatro topics; la segunda vez dice «Ya estaban»
uv run edsim directo lanzar     # 14 días de config/ a ×60: una hora simulada por minuto real
```

`lanzar` imprime su `run_id` (como `r2026_20261109T172300`: la semilla y la hora de
arranque), el censo y una línea de estado cada 10 s:

```
+10 s · 2026-01-07T00:10:08.215+01:00 (minuto 2890.1) · ×60 · 533 publicados · retraso 0.6 ms · 0 pendientes
```

Termina al llegar al horizonte, con una orden `parar` o con Ctrl+C (código 130). En
los tres casos publica el mensaje `fin` en `ed.runs`. Opciones: las del modelo de
`edsim motor simular` (`--centro`, `--llegadas`, `--perfiles` o `--provisional`,
`--semilla`, `--dias`, `--calentamiento`, `--run-id`), `--velocidad` (un número o
`max`), `--anclar` (empieza hoy, a la hora real), `--kafka HOST:PUERTO` y `--memoria`
(sin Kafka, para probar).

**Mandar órdenes**, desde otra terminal y con el `run_id` de la cabecera. El directo las
atiende en menos de 0,2 s:

```bash
uv run edsim directo control --run r2026_20261109T172300 --velocidad 600
uv run edsim directo control --run r2026_20261109T172300 --pausar
uv run edsim directo control --run r2026_20261109T172300 --reanudar
uv run edsim directo control --run r2026_20261109T172300 --parar
```

**Ver los mensajes** en Redpanda Console (<http://localhost:8080>):

- en *Topics*, los cuatro `ed.*`;
- `ed.patient.events` con sus 3 particiones;
- en cada mensaje, la clave (`episode_id`), las cabeceras `event_type` y
  `schema_version` y la marca de tiempo del broker (`LogAppendTime`);
- en `ed.runs`, el `inicio` y el `fin` de cada ejecución.

**Reemitir una ejecución guardada**, con los mismos bytes:

```bash
uv run edsim motor simular --run-id r2026                   # la guarda en resultados/ejecuciones/r2026
uv run edsim directo reemitir r2026 --velocidad max         # la publica de golpe
```

Sin el broker en marcha, `lanzar`, `reemitir`, `preparar` y `control` avisan en 10 s:
«no responde el broker de Kafka en localhost:9092 en 10 s: ¿está levantado? docker
compose up --wait».

**Si Kafka se cae a mitad de un directo**, nada se pierde: los eventos esperan en la cola
del productor (hasta 5 minutos) y salen al volver. La terminal muestra un aviso al perder
el broker y otro al recuperarlo; las líneas de librdkafka no van a la terminal, y al final
se imprime su recuento por cliente y por tipo. Para guardarlas todas, con su hora:

```bash
uv run edsim directo lanzar --registro-kafka /tmp/librdkafka.log
```

## Leer un directo

El consumidor del hito 6 está en el paquete: `edsim.live.kafka.read_run` lee los eventos
de un `run_id` (y su `inicio` y su `fin`) en un grupo de consumidores propio, desde el
principio, y los pasa a un `edsim.live.tracker.LiveTracker`, que mantiene el censo en vivo
(cuántos pacientes hay en cada ubicación), descarta los repetidos por `event_id`, mide el
orden por partición y la latencia desde el broker.

El notebook `notebooks/06_tiempo_real.ipynb` lo enseña paso a paso: lanza un directo corto,
lo lee a la vez y comprueba que lo leído es el batch. Con Kafka:

```bash
docker compose up --wait
uv run edsim directo preparar
uv sync --all-packages --extra kafka    # confluent-kafka en .venv, para el kernel
```

y se abre en Cursor con el kernel de `.venv` (o con
`uv run --all-packages --extra kafka --with jupyterlab jupyter lab notebooks/06_tiempo_real.ipynb`).
Con `EDSIM_NB_RAPIDO=1` corre sin Docker ni el extra, con el directo en memoria. Mientras
corre, Redpanda Console muestra su grupo (`edsim-lector-…`) en *Consumer Groups*.

## Flujo de trabajo

GitHub Flow: cada tarea en una rama corta que entra en `main` por pull request, con el CI (lint, formato y tests) en verde.

## Documentación

- [EDsim Lab: uso y tests de la app local](app/README.md)
- [Documento de diseño](docs/diseno.md)
- [Especificaciones por hito](docs/specs/)
- [Registro de decisiones (ADR)](docs/decisiones/README.md)
- [Diario de aprendizaje](docs/diario/README.md)
- [CLAUDE.md](CLAUDE.md): instrucciones para Claude Code

### Ejecuciones del motor

`edsim motor simular` guarda por defecto en `resultados/ejecuciones/<run_id>/`
(por ejemplo, `r2026` con la semilla predeterminada). La carpeta contiene el log,
los dos CSV de ground truth, copias exactas de `centro.toml`, `llegadas.toml` y,
con el modelo clínico, `perfiles.toml`, y los metadatos versionados de `run.json`
(el modelo y la huella de los perfiles). La CLI y la app comparten el servicio
público `edsim.runs.simulate_run` para escribir este formato de forma atómica.

Desde el cierre del hito 4, `motor simular` usa el modelo clínico: cada paciente
sale de los perfiles, `config/perfiles.toml` u otro con `--perfiles`. Desde la tarea
5.6, `config/` es el modelo del hito 5 (abandono, destinos y espera de cama: el bloque
del hito 5 en `perfiles.toml` y `[camas]` en `centro.toml`); el del hito 4 se simula
con sus ficheros, congelados en `tests/data/` (`--centro tests/data/centro_h4.toml
--perfiles tests/data/perfiles_h4.toml`). Con
`--provisional`, simula el modelo provisional del hito 3, que se queda para la
validación del motor y necesita un centro con `[triaje]`, `[duraciones]` y
`[pruebas]`: `config/centro.toml` ya no las tiene, y el centro del provisional es
`tests/data/centro_ejemplo.toml` (también el de `motor validar` por defecto).
`--provisional` y `--perfiles` no se pueden usar juntos.

Una ejecución guardada no se sobrescribe: elige otro `--run-id` o una carpeta
inexistente con `--salida`. El identificador admite de 1 a 64 letras ASCII,
cifras, puntos, guiones y guiones bajos, empezando por letra o cifra.
Las violaciones de invariantes se guardan para diagnóstico y dan código de salida 1.
Los errores de uso, incluido un destino ocupado, dan código 2.

Para reproducir el log de una ejecución, usa sus copias con `--centro`,
`--llegadas` y, si es clínica, `--perfiles` (si es provisional, `--provisional`),
los mismos días, calentamiento, semilla y `--run-id` registrados en `run.json`, y
un destino nuevo. Las rutas de procedencia de los CSV cambiarán
si cambian las cadenas de ruta de entrada; el log seguirá siendo idéntico.
