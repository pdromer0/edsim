"""Fixtures de los tests de integración contra un Kafka real (H6-3).

Esta carpeta está fuera de `testpaths`: solo corre cuando se pide, con
`uv run --extra kafka pytest tests_integracion`, normalmente desde
`scripts/tests-integracion.sh`, que levanta el `compose.yaml` si hace falta.

Cada espera tiene un límite explícito (`TIMEOUT`): ningún test puede quedarse colgado.
"""

import os
import uuid

import pytest
from confluent_kafka import KafkaError, KafkaException
from confluent_kafka.admin import AdminClient
from kafka_testing import BROKER_TIMEOUT, DEFAULT_BOOTSTRAP, TIMEOUT, TOPIC_PART, reachable

from edsim.live.kafka import TopicsReport, ensure_topics
from edsim.live.topics import TOPIC_CONFIG, Topic

LISTENER_HINT = (
    "Suele ser una dirección anunciada que no se alcanza desde aquí: el cliente vuelve a llamar "
    "a la que le devuelve el broker, no a la de arranque. Revisa KAFKA_ADVERTISED_LISTENERS: en "
    "compose.yaml, el listener EXTERNAL anuncia localhost:9092 (docs/specs/hito-6.md, pieza 5)."
)


@pytest.fixture(scope="session")
def bootstrap() -> str:
    """La dirección del broker: `EDSIM_KAFKA` o `localhost:9092`, comprobada en tres pasos.

    Si algo falla, los tests fallan (no se saltan: un salto escondería que no se han probado)
    con un mensaje que dice qué pasa: que no hay broker y cómo levantarlo, o que el broker
    escucha pero se anuncia en una dirección que no se alcanza desde aquí. Sin el tercer paso,
    con un listener mal anunciado, el resultado dependía de una carrera de librdkafka.
    """
    servers = os.environ.get("EDSIM_KAFKA", DEFAULT_BOOTSTRAP)
    # 1. Alguien acepta conexiones en la dirección de arranque.
    if not any(reachable(address, BROKER_TIMEOUT) for address in servers.split(",")):
        pytest.fail(
            f"No responde ningún broker de Kafka en {servers} en {BROKER_TIMEOUT:.0f} s. "
            "Levántalo con «docker compose up --wait» o ejecuta scripts/tests-integracion.sh; "
            "para otro broker, EDSIM_KAFKA=host:puerto.",
            pytrace=False,
        )
    # 2. El cliente obtiene los metadatos del clúster. librdkafka cierra la conexión de arranque
    #    en cuanto conoce las direcciones anunciadas: si no las alcanza, esto puede vencer.
    try:
        metadata = AdminClient({"bootstrap.servers": servers}).list_topics(timeout=BROKER_TIMEOUT)
    except KafkaException as exc:
        pytest.fail(
            f"El broker acepta conexiones en {servers}, pero el cliente no obtiene sus metadatos "
            f"en {BROKER_TIMEOUT:.0f} s ({exc}). {LISTENER_HINT}",
            pytrace=False,
        )
    # 3. Cada dirección anunciada se alcanza desde aquí.
    advertised = [f"{broker.host}:{broker.port}" for broker in metadata.brokers.values()]
    unreachable = [address for address in advertised if not reachable(address, BROKER_TIMEOUT)]
    if unreachable:
        pytest.fail(
            f"El broker se anuncia como {', '.join(unreachable)}, que no se alcanza desde aquí. "
            f"{LISTENER_HINT}",
            pytrace=False,
        )
    return servers


@pytest.fixture(scope="session")
def admin(bootstrap: str) -> AdminClient:
    return AdminClient({"bootstrap.servers": bootstrap})


@pytest.fixture(scope="session")
def edsim_topics(bootstrap: str) -> TopicsReport:
    """Los cuatro topics reales de EDsim, con `ensure_topics`, como `edsim directo preparar`.

    KafkaSink y KafkaControl publican y leen en los nombres de la tabla, que no se pueden
    pasar: los tests que los usan necesitan que existan, y el broker no autocrea topics y
    queda vacío tras `docker compose down`. No se borran al terminar; los independizan el
    `run_id` único de cada test y los offsets altos anotados antes de publicar.
    """
    return ensure_topics(bootstrap)


@pytest.fixture
def make_topic(bootstrap: str, admin: AdminClient):
    """Crea topics `test.<nombre>.<uuid8>` y los borra al terminar el test, también si falla.

    Los crea con `ensure_topics`, como los de EDsim: una réplica, la marca de tiempo del
    broker (`LogAppendTime`) y borrado por antigüedad. `config` cambia esa configuración.
    """
    created: list[str] = []

    def make(name: str, partitions: int, config: dict | None = None) -> str:
        if not TOPIC_PART.fullmatch(name):
            raise ValueError(f"Nombre de topic de test no válido: {name!r}")
        topic = f"test.{name}.{uuid.uuid4().hex[:8]}"
        # Se apunta antes de crearlo: si la creación vence pero el topic llega a existir, el
        # teardown también lo borra.
        created.append(topic)
        report = ensure_topics(
            bootstrap, [Topic(topic, partitions, "test", {**TOPIC_CONFIG, **(config or {})})]
        )
        assert report.created == (topic,)
        return topic

    yield make

    if created:
        futures = admin.delete_topics(created, request_timeout=TIMEOUT)
        for future in futures.values():
            try:
                future.result(timeout=TIMEOUT)
            except KafkaException as exc:
                # Un topic cuya creación falló no existe: no hay nada que borrar.
                if exc.args[0].code() != KafkaError.UNKNOWN_TOPIC_OR_PART:
                    raise
