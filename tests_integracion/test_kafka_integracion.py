"""Prueba de humo contra el Kafka de compose.yaml, desde fuera de Docker (listener EXTERNAL)."""

import time
import uuid

import pytest
from confluent_kafka import TIMESTAMP_LOG_APPEND_TIME, Consumer, Producer
from confluent_kafka.admin import ConfigResource, ResourceType
from kafka_testing import PRODUCER_CONFIG, TIMEOUT, deadline

KEY = b"EP-000184"
VALUE = b'{"prueba": "humo", "episode_id": "EP-000184"}'


def test_humo_publica_y_lee_un_mensaje_por_localhost(bootstrap, make_topic):
    """Publicar y leer un mensaje por localhost:9092, con la marca de tiempo del broker."""
    topic = make_topic("humo-publica", partitions=3)
    producer = Producer({"bootstrap.servers": bootstrap, **PRODUCER_CONFIG})
    reports = []

    t0 = int(time.time() * 1000)
    producer.produce(topic, key=KEY, value=VALUE, on_delivery=lambda e, m: reports.append((e, m)))
    assert producer.flush(TIMEOUT) == 0, "El mensaje no se entregó en 30 s"
    [(error, delivered)] = reports
    assert error is None, error

    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": f"test-humo-{uuid.uuid4().hex[:8]}",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    message = None
    errors = []
    try:
        consumer.subscribe([topic])
        limit = deadline()
        while message is None and time.monotonic() < limit:
            candidate = consumer.poll(1.0)
            if candidate is None:
                continue
            if candidate.error():
                errors.append(candidate.error())
                continue
            message = candidate
            t1 = int(time.time() * 1000)
    finally:
        consumer.close()

    assert message is not None, f"El consumidor no recibió el mensaje en 30 s (errores: {errors})"
    assert message.key() == KEY
    assert message.value() == VALUE
    # Con murmur2 y 3 particiones, EP-000184 va a la 0 (valor a mano).
    assert delivered.partition() == message.partition() == 0
    timestamp_type, timestamp = message.timestamp()
    assert timestamp_type == TIMESTAMP_LOG_APPEND_TIME
    print(f"marca − t0 = {timestamp - t0} ms; t1 − marca = {t1 - timestamp} ms")
    # Sin margen: el broker y este proceso leen el mismo reloj (Docker Desktop corre en la VM de
    # WSL2, y en el CI el contenedor comparte el núcleo del ejecutor).
    assert t0 <= timestamp <= t1, (t0, timestamp, t1)


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        # La configuración de EDsim tal cual (murmur2_random, H6-8), como Java y Kafka Streams.
        ({}, [0, 0, 1, 2]),
        # El particionador por defecto de librdkafka (CRC32): la trampa de la pieza 2.
        ({"partitioner": "consistent_random"}, [0, 2, 2, 1]),
    ],
    ids=["murmur2", "crc32"],
)
def test_particiones_de_las_claves(bootstrap, make_topic, request, override, expected):
    """Con 3 particiones, cada clave cae en la partición calculada a mano para su hash."""
    topic = make_topic(f"particiones-{request.node.callspec.id}", partitions=3)
    producer = Producer({"bootstrap.servers": bootstrap, **PRODUCER_CONFIG, **override})
    reports = []

    def record(error, message):
        reports.append((error, message))

    for key in (b"EP-000184", b"EP-000185", b"EP-000186", b"EP-000187"):
        producer.produce(topic, key=key, value=b"{}", on_delivery=record)
        # Uno a uno, para que los avisos de entrega lleguen en el orden de las claves.
        assert producer.flush(TIMEOUT) == 0, "Un mensaje no se entregó en 30 s"

    assert [error for error, _ in reports] == [None] * 4
    assert [message.partition() for _, message in reports] == expected


def test_el_broker_no_autocrea_topics(admin):
    """La autocreación está desactivada: un nombre mal escrito no crea un topic (H6-7)."""
    brokers = admin.list_topics(timeout=TIMEOUT).brokers
    [broker_id] = brokers
    resource = ConfigResource(ResourceType.BROKER, str(broker_id))

    futures = admin.describe_configs([resource], request_timeout=TIMEOUT)
    configs = futures[resource].result(timeout=TIMEOUT)

    assert configs["auto.create.topics.enable"].value == "false"
