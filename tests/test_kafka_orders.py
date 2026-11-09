"""Publicar una orden en ed.control (tarea 6.5): lo que hace `edsim directo control`; y
los mensajes pendientes de la línea de estado.

Con el productor falso y un módulo confluent_kafka falso (tests/fake_kafka.py), sin broker
y sin el extra: la orden va a ed.control con el run_id como clave y el texto de
control_json, y se espera su confirmación. Sin broker, el error dice dónde se buscó.
"""

import pytest
from fake_kafka import FakeProducer, install_fake_confluent_kafka

from edsim.live.control import PAUSE, SPEED, STOP, Command
from edsim.live.kafka import (
    BrokerUnavailableError,
    OrderNotDeliveredError,
    pending_messages,
    publish_order,
)
from edsim.live.messages import control_json
from edsim.live.topics import CONTROL


@pytest.fixture(autouse=True)
def fake_client(monkeypatch):
    install_fake_confluent_kafka(monkeypatch)


def test_publica_la_orden_con_su_clave_y_espera_la_confirmacion():
    producer = FakeProducer(deliver_on_poll=False)
    command = Command(SPEED, 600)

    offset = publish_order(producer, "r2026_x", command, bootstrap="localhost:9092")

    [(topic, kwargs)] = producer.calls
    assert topic == CONTROL
    assert kwargs["key"] == b"r2026_x"
    assert kwargs["value"] == control_json("r2026_x", command).encode()
    assert producer.list_calls == [(CONTROL, 10.0)]
    assert producer.flushes == [30.0]
    assert offset == 0


def test_sin_broker_no_publica():
    producer = FakeProducer(unreachable=True)

    with pytest.raises(BrokerUnavailableError, match="localhost:1 in 1 s"):
        publish_order(producer, "r1", Command(STOP), bootstrap="localhost:1", connect_timeout=1)

    assert producer.calls == []


def test_orden_sin_confirmar_tras_el_flush():
    producer = FakeProducer(deliver_on_poll=False, stuck=1)

    with pytest.raises(BrokerUnavailableError, match="in 30 s"):
        publish_order(producer, "r1", Command(PAUSE), bootstrap="localhost:9092")


def test_orden_con_error_de_entrega():
    producer = FakeProducer(delivery_errors={1})

    with pytest.raises(OrderNotDeliveredError, match="Message timed out"):
        publish_order(producer, "r1", Command(PAUSE), bootstrap="localhost:9092")


# --- Pendientes de la línea de estado --------------------------------------------------


def test_pendientes_sirve_antes_los_avisos():
    # Tres mensajes en la cola sin servir sus avisos: len() da 3 aunque dos ya se pueden
    # confirmar. pending_messages los sirve primero y cuenta solo el que sigue esperando.
    producer = FakeProducer(hold={2})
    for value in (b"a", b"b", b"c"):
        producer.produce(CONTROL, value=value)
    assert len(producer) == 3

    assert pending_messages(producer) == 1
    assert producer.polls == [0]
