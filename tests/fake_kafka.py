"""Un productor de Kafka falso para los tests sin broker (tarea 6.4, pieza 7).

Imita lo que KafkaSink usa de confluent_kafka.Producer: produce(topic, key, value,
headers, on_delivery), poll, flush y len. Los mensajes aceptados quedan pendientes hasta
que se entregan, y cada entrega llama a on_delivery(error, mensaje), como librdkafka al
servir los avisos. Se puede programar un BufferError en una llamada a produce y un aviso
con error en un mensaje, y entregar los mensajes a mano y en otro orden.
"""

import sys
from dataclasses import dataclass, field
from types import ModuleType, SimpleNamespace


@dataclass
class FakeMessage:
    """Un mensaje aceptado: lo que se pasó a produce, sin on_delivery."""

    number: int  # orden de aceptación, desde 1
    topic: str
    kwargs: dict = field(repr=False)

    @property
    def key(self):
        return self.kwargs.get("key")

    @property
    def value(self):
        return self.kwargs.get("value")

    @property
    def headers(self):
        return self.kwargs.get("headers")

    def offset(self) -> int:
        """El offset de un mensaje entregado, como Message.offset(): desde 0."""
        return self.number - 1


@dataclass(frozen=True)
class FakeError:
    """Un error de entrega, como un KafkaError: se imprime con su texto."""

    text: str

    def __str__(self) -> str:
        return self.text


class FakeProducer:
    """El doble del productor.

    Args:
        buffer_errors: Números de llamada a produce (desde 1) que lanzan BufferError sin
            aceptar el mensaje.
        delivery_errors: Números de mensaje aceptado (desde 1) cuyo aviso llega con error.
        deliver_on_poll: Si poll entrega todo lo pendiente (por defecto). Con False, solo
            flush y release entregan.
        hold: Números de mensaje aceptado que poll no entrega: esperan al flush, como un
            mensaje cuya confirmación tarda.
        stuck: Mensajes que flush deja sin entregar, los últimos.
        unreachable: Si list_topics falla como sin broker (FakeKafkaException).

    Attributes:
        calls: Cada llamada a produce: (topic, kwargs sin on_delivery), también las que
            lanzaron BufferError.
        polls: El timeout de cada poll.
        delivered: Los mensajes entregados, en orden de entrega, con su error o None.
        ops: Cada produce aceptado ("produce", topic) y cada flush ("flush",), en orden.
    """

    def __init__(
        self,
        *,
        buffer_errors=(),
        delivery_errors=(),
        deliver_on_poll: bool = True,
        hold=(),
        stuck: int = 0,
        unreachable: bool = False,
    ) -> None:
        self.unreachable = unreachable
        self.list_calls: list[tuple] = []
        self.hold = set(hold)
        self.buffer_errors = set(buffer_errors)
        self.delivery_errors = set(delivery_errors)
        self.deliver_on_poll = deliver_on_poll
        self.stuck = stuck
        self.calls: list[tuple[str, dict]] = []
        self.polls: list[float] = []
        self.flushes: list[float] = []
        self.delivered: list[tuple[FakeMessage, FakeError | None]] = []
        self._pending: list[tuple[FakeMessage, object]] = []
        self._accepted = 0
        self.ops: list[tuple] = []

    def produce(self, topic, value=None, key=None, **kwargs):
        on_delivery = kwargs.pop("on_delivery", None)
        kwargs = {"key": key, "value": value, **kwargs}
        self.calls.append((topic, kwargs))
        if len(self.calls) in self.buffer_errors:
            raise BufferError("Local: Queue full")
        self._accepted += 1
        self.ops.append(("produce", topic))
        self._pending.append((FakeMessage(self._accepted, topic, kwargs), on_delivery))

    def _deliver(self, position: int) -> None:
        message, on_delivery = self._pending.pop(position)
        error = (
            FakeError("Local: Message timed out")
            if message.number in self.delivery_errors
            else None
        )
        self.delivered.append((message, error))
        if on_delivery is not None:
            on_delivery(error, message)

    def release(self, number: int) -> None:
        """Entrega ya el mensaje aceptado número ``number``, aunque haya otros antes."""
        [position] = [i for i, (m, _) in enumerate(self._pending) if m.number == number]
        self._deliver(position)

    def poll(self, timeout=None) -> int:
        self.polls.append(timeout)
        if not self.deliver_on_poll:
            return 0
        ready = [m.number for m, _ in self._pending if m.number not in self.hold]
        for number in ready:  # en orden de aceptación
            self.release(number)
        return len(ready)

    def flush(self, timeout=None) -> int:
        self.flushes.append(timeout)
        self.ops.append(("flush",))
        while len(self._pending) > self.stuck:
            self._deliver(0)
        return len(self._pending)

    def __len__(self) -> int:
        return len(self._pending)

    def list_topics(self, topic=None, timeout=None):
        """Los metadatos, como Producer.list_topics; sin broker, FakeKafkaException."""
        self.list_calls.append((topic, timeout))
        if self.unreachable:
            raise FakeKafkaException(NO_BROKER)
        return SimpleNamespace(topics={})


@dataclass
class FakeConsumerMessage:
    """Un mensaje leído, como el de confluent_kafka: value() y error()."""

    payload: bytes
    problem: object = None

    def value(self) -> bytes:
        return self.payload

    def error(self):
        return self.problem


class FakeConsumer:
    """Un consumidor falso: poll(timeout) da los mensajes de la lista, uno por llamada."""

    def __init__(self, values) -> None:
        self._messages = [FakeConsumerMessage(v) for v in values]

    def poll(self, timeout=None):
        return self._messages.pop(0) if self._messages else None

    def close(self) -> None:
        pass


# --- Un módulo confluent_kafka falso -------------------------------------------------

NO_BROKER = 'KafkaError{code=_TRANSPORT,val=-195,str="Local: Broker transport failure"}'
"""El texto de la excepción del cliente sin broker."""


class FakeKafkaException(Exception):
    """Como confluent_kafka.KafkaException."""


@dataclass(frozen=True)
class FakeConfigResource:
    """Como confluent_kafka.admin.ConfigResource: se usa de clave en un diccionario."""

    restype: object
    name: str


@dataclass
class FakeNewTopic:
    """Como confluent_kafka.admin.NewTopic."""

    topic: str
    num_partitions: int
    replication_factor: int
    config: dict


class FakeFuture:
    """Un futuro ya resuelto."""

    def __init__(self, value) -> None:
        self.value = value

    def result(self, timeout=None):
        return self.value


class FakeAdmin:
    """Un AdminClient falso con los topics del broker: {nombre: (particiones, marca)}.

    Attributes:
        list_timeouts: El timeout de cada list_topics, en orden.
        created: Los topics creados, en orden.
    """

    def __init__(self, topics=None, *, unreachable: bool = False) -> None:
        self.topics = dict(topics or {})
        self.unreachable = unreachable
        self.list_timeouts: list[float] = []
        self.created: list[str] = []

    def list_topics(self, timeout=None):
        self.list_timeouts.append(timeout)
        if self.unreachable:
            raise FakeKafkaException(NO_BROKER)
        topics = {
            name: SimpleNamespace(partitions=dict.fromkeys(range(n)), error=None)
            for name, (n, _) in self.topics.items()
        }
        return SimpleNamespace(topics=topics)

    def describe_configs(self, resources, request_timeout=None):
        return {
            r: FakeFuture({"message.timestamp.type": SimpleNamespace(value=self.topics[r.name][1])})
            for r in resources
        }

    def create_topics(self, new, request_timeout=None):
        for topic in new:
            self.created.append(topic.topic)
            self.topics[topic.topic] = (
                topic.num_partitions,
                topic.config["message.timestamp.type"],
            )
        return {topic.topic: FakeFuture(None) for topic in new}


def install_fake_confluent_kafka(monkeypatch, admin: FakeAdmin | None = None) -> ModuleType:
    """Pone en sys.modules un confluent_kafka falso (y su .admin) mientras dure el test.

    Así ensure_topics y publish_order corren sin el extra, en el job tests del CI. El
    AdminClient que crean es ``admin``.
    """
    kafka = ModuleType("confluent_kafka")
    kafka.KafkaException = FakeKafkaException
    admin_module = ModuleType("confluent_kafka.admin")
    admin_module.AdminClient = lambda config: admin
    admin_module.ConfigResource = FakeConfigResource
    admin_module.NewTopic = FakeNewTopic
    admin_module.ResourceType = SimpleNamespace(TOPIC="TOPIC")
    kafka.admin = admin_module
    monkeypatch.setitem(sys.modules, "confluent_kafka", kafka)
    monkeypatch.setitem(sys.modules, "confluent_kafka.admin", admin_module)
    return kafka
