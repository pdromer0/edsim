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
from confluent_kafka.admin import AdminClient, NewTopic
from kafka_testing import BROKER_TIMEOUT, DEFAULT_BOOTSTRAP, TIMEOUT, TOPIC_PART


@pytest.fixture(scope="session")
def bootstrap() -> str:
    """La dirección del broker: `EDSIM_KAFKA` o `localhost:9092`.

    Si no responde en 10 s, los tests fallan (no se saltan: un salto escondería que no se han
    probado) con un mensaje que dice cómo levantarlo.
    """
    servers = os.environ.get("EDSIM_KAFKA", DEFAULT_BOOTSTRAP)
    try:
        AdminClient({"bootstrap.servers": servers}).list_topics(timeout=BROKER_TIMEOUT)
    except KafkaException as exc:
        pytest.fail(
            f"No responde ningún broker de Kafka en {servers} en {BROKER_TIMEOUT:.0f} s ({exc}). "
            "Levántalo con «docker compose up --wait» o ejecuta scripts/tests-integracion.sh; "
            "para otro broker, EDSIM_KAFKA=host:puerto.",
            pytrace=False,
        )
    return servers


@pytest.fixture(scope="session")
def admin(bootstrap: str) -> AdminClient:
    return AdminClient({"bootstrap.servers": bootstrap})


@pytest.fixture
def make_topic(admin: AdminClient):
    """Crea topics `test.<nombre>.<uuid8>` y los borra al terminar el test, también si falla.

    Los crea como los de EDsim: una réplica y la marca de tiempo del broker (`LogAppendTime`).
    """
    created: list[str] = []

    def make(name: str, partitions: int) -> str:
        if not TOPIC_PART.fullmatch(name):
            raise ValueError(f"Nombre de topic de test no válido: {name!r}")
        topic = f"test.{name}.{uuid.uuid4().hex[:8]}"
        new = NewTopic(
            topic,
            num_partitions=partitions,
            replication_factor=1,
            config={"message.timestamp.type": "LogAppendTime"},
        )
        # Se apunta antes de esperar: si la creación vence pero el topic llega a existir, el
        # teardown también lo borra.
        created.append(topic)
        admin.create_topics([new], request_timeout=TIMEOUT)[topic].result(timeout=TIMEOUT)
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
