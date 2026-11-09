# 0049. Código en `edsim.live`; `confluent-kafka` como extra opcional importado solo en `live/kafka.py`

- **Estado:** Aceptada
- **Fecha:** 2026-11-06

## Contexto

El pacer y el motor por pasos son piezas del motor, pero el cliente de Kafka es una dependencia pesada (una biblioteca en C) que no necesitan el batch, la app ni los tests rápidos. El job `tests` del CI no tiene Docker ni el cliente ([especificación, «Estructura del código»](../specs/hito-6.md#estructura-del-código)).

## Decisión

- Todo el código del hito vive en el subpaquete `edsim.live` del núcleo.
- `confluent-kafka` es el extra opcional `kafka` (`confluent-kafka>=2.16.1,<2.17`). Solo `live/kafka.py` lo importa, y solo dentro de las funciones que crean clientes reales (import perezoso). Un test de frontera lo comprueba.
- El cliente es `confluent-kafka`: envuelve librdkafka, el cliente en C de Confluent, tiene productor idempotente y es la base de Quix Streams, el de los consumidores del hito 8.
- `compose.yaml` va en la raíz del repositorio.

## Alternativas consideradas

- Un paquete aparte en el workspace (`edsim-live`): duplicaría el acceso al motor y los dobles de los tests, y la frontera ya se consigue con el import perezoso.
- `kafka-python` (Python puro) o `aiokafka` (asyncio): no aportan nada que EDsim necesite, y obligarían a cambiar de cliente en el hito 8.
- Importar `confluent_kafka` a nivel de módulo: el núcleo no se podría importar ni probar sin el extra.

## Consecuencias

- `import edsim` funciona sin el extra; los tests de `KafkaSink` corren con un productor falso en el job `tests`.
- Sin el extra, los comandos que hablan con Kafka dicen cómo instalarlo: «Falta el extra kafka: uv sync --all-packages --extra kafka». Un `uv sync` sin `--extra kafka` lo desinstala.

## Qué cambió al implementarla

- 6.1: `import_confluent_kafka()` y `MissingKafkaExtraError` (hereda de `ImportError`). El detector de la frontera recorre el código con `ast` y ve `import`, `from … import`, `importlib.import_module` y `__import__`; un test prueba el propio detector.
- 6.5: un módulo `confluent_kafka` falso en `sys.modules` (`tests/fake_kafka.py`) prueba `ensure_topics`, `publish_order` y `KafkaControl` sin el extra.
- 6.6: el vigilante de la conexión (`BrokerWatch`) y la lectura de un directo (`read_run`) van en `live/kafka.py`. El estado del consumidor (`live/tracker.py`) no importa el cliente y se usa en el modo rápido del notebook 06. Reutiliza `LocationState` de `edsim.runs._location`, así que importarlo carga el paquete `edsim.runs` (y SimPy), como la app.
