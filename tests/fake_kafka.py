"""Un productor de Kafka falso para los tests sin broker (tarea 6.4, pieza 7).

Imita lo que KafkaSink usa de confluent_kafka.Producer: produce(topic, key, value,
headers, on_delivery), poll, flush y len. Los mensajes aceptados quedan pendientes hasta
que se entregan, y cada entrega llama a on_delivery(error, mensaje), como librdkafka al
servir los avisos. Se puede programar un BufferError en una llamada a produce y un aviso
con error en un mensaje, y entregar los mensajes a mano y en otro orden.
"""

from dataclasses import dataclass, field


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
    ) -> None:
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
