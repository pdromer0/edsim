"""Kafka for the live mode: the producer, the sink and the client access.

``confluent-kafka`` is the optional ``kafka`` extra. This is the only module that imports it,
and only inside functions (a lazy import): importing this module never loads the client, so
the core and its tests run without the extra installed. ``KafkaSink`` takes a producer
already built, the real one (``connect_producer``) or a double in the tests.

**The producer** (docs/specs/hito-6.md, "Productor", H6-8) is idempotent, waits for every
replica (``acks=all``) and partitions with murmur2, as Java and Kafka Streams do. Everything
else keeps librdkafka's defaults.

**The sink** publishes the ``inicio`` and the ``fin`` of the run in ``ed.runs`` and each
event in its topic (``edsim.live.topics.route``), with the line of the JSONL as value, byte
for byte, and the headers ``event_type`` and ``schema_version``. It never sets a timestamp:
the topics use ``LogAppendTime``, the arrival time at the broker (H6-9).

Sending is asynchronous: ``produce`` queues the message and the result arrives later, in a
delivery report served by ``poll``. A full queue raises ``BufferError``: the sink serves the
reports for 0.1 s and tries again, so the pacer falls behind instead of losing a message. A
report with an error marks the sink as failed, and the next ``write`` raises ``SinkError``:
the run never goes on with a gap.
"""

from collections.abc import Callable
from types import ModuleType, TracebackType
from typing import Protocol, Self

from edsim.engine.events import Event, to_json
from edsim.live.directo import RunEnd, RunStart, SinkError
from edsim.live.messages import END, START, run_end_json, run_start_json
from edsim.live.topics import RUNS, route

MISSING_EXTRA_MESSAGE = "Falta el extra kafka: uv sync --all-packages --extra kafka"

FLUSH_TIMEOUT = 30.0
"""Seconds that leaving the sink waits for the pending messages."""

RETRY_POLL = 0.1
"""Seconds served on a full queue (``BufferError``) before trying again."""


class MissingKafkaExtraError(ImportError):
    """The optional ``kafka`` extra (``confluent-kafka``) is not installed."""


def import_confluent_kafka() -> ModuleType:
    """Return the ``confluent_kafka`` module, importing it on first use.

    Raises:
        MissingKafkaExtraError: if the package is not installed, with the command that
            installs it.
    """
    try:
        import confluent_kafka
    except ImportError as exc:
        raise MissingKafkaExtraError(MISSING_EXTRA_MESSAGE) from exc
    return confluent_kafka


# --- The producer --------------------------------------------------------------------


def producer_config(bootstrap: str, run_id: str) -> dict[str, object]:
    """The configuration of the producer of a run: four values on top of librdkafka's.

    ``enable.idempotence``: retries without duplicates nor disorder; ``acks``: explicit,
    so that it holds in a cluster; ``partitioner``: murmur2, as Java and Kafka Streams;
    ``client.id``: the run, to recognize it in Redpanda Console.
    """
    return {
        "bootstrap.servers": bootstrap,
        "enable.idempotence": True,
        "acks": "all",
        "partitioner": "murmur2_random",
        "client.id": f"edsim-{run_id}",
    }


def connect_producer(bootstrap: str, run_id: str):
    """A real ``confluent_kafka.Producer`` with ``producer_config``.

    Raises:
        MissingKafkaExtraError: If the ``kafka`` extra is not installed.
    """
    return import_confluent_kafka().Producer(producer_config(bootstrap, run_id))


class Producer(Protocol):
    """What the sink uses of a ``confluent_kafka.Producer``."""

    def produce(
        self,
        topic: str,
        value: bytes | None = None,
        key: bytes | None = None,
        *,
        headers: list[tuple[str, bytes]] | None = None,
        on_delivery: Callable[[object, object], None] | None = None,
    ) -> None: ...

    def poll(self, timeout: float) -> int: ...

    def flush(self, timeout: float) -> int: ...

    def __len__(self) -> int: ...


class KafkaSink:
    """Publishes a live run in Kafka: a ``LiveSink`` and a context manager.

    ::

        with KafkaSink(connect_producer(bootstrap, run_id), run_id) as sink:
            run_live(source, pacer, control, sink, ...)

    Leaving the ``with`` waits up to ``FLUSH_TIMEOUT`` for the pending messages.

    Args:
        producer: A ``confluent_kafka.Producer`` or a double with ``produce``, ``poll``,
            ``flush`` and ``len``.
        run_id: The run; the key of its messages in ``ed.runs``.

    Attributes:
        delivered: Events whose delivery was confirmed.
        failed: What was not delivered: the ``event_id`` of each event, or ``inicio``
            and ``fin``.
        last_delivered: ``event_id`` of the confirmed event written last (the highest
            emission number), whatever the order of the confirmations.
    """

    def __init__(self, producer: Producer, run_id: str) -> None:
        if not isinstance(run_id, str) or not run_id:
            raise ValueError(f"run_id must be a non-empty string, got {run_id!r}")
        self._producer = producer
        self.run_id = run_id
        self._key = run_id.encode("utf-8")
        self._written = 0  # events handed to produce, in emission order
        self._best = -1  # highest write index confirmed
        self.delivered = 0
        self.failed: list[str] = []
        self._errors: list[str] = []
        self._reported = 0  # failures already raised by a write
        self.last_delivered: str | None = None

    # -- LiveSink ---------------------------------------------------------------------

    def start(self, message: RunStart) -> None:
        """Publish the ``inicio`` of the run in ``ed.runs``."""
        self._check_run_id("RunStart", message.info.run_id)
        self._produce(RUNS, self._key, run_start_json(message).encode("utf-8"), None, START)

    def write(self, event: Event) -> None:
        """Publish one event in its topic.

        Raises:
            SinkError: If a message before it was not delivered (this one is not sent).
            ValueError: If the event is of another run.
        """
        if self.failed:
            # Once failed, every write refuses: the run never goes on with a gap.
            self._reported = len(self.failed)
            raise self._error("a message was not delivered")
        self._check_run_id("event", event.run_id)
        topic, key = route(event)
        headers = [
            ("event_type", event.event_type.encode("utf-8")),
            ("schema_version", str(event.schema_version).encode("utf-8")),
        ]
        index = self._written
        self._written += 1
        self._produce(
            topic,
            key,
            to_json(event).encode("utf-8"),
            headers,
            event.event_id,
            index=index,
        )

    def end(self, message: RunEnd) -> None:
        """Publish the ``fin`` of the run in ``ed.runs``, even if the sink failed."""
        self._check_run_id("RunEnd", message.run_id)
        self._produce(RUNS, self._key, run_end_json(message).encode("utf-8"), None, END)

    # -- Context manager --------------------------------------------------------------

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        pending = self._producer.flush(FLUSH_TIMEOUT)
        problems = []
        if pending:
            problems.append(f"{pending} messages still pending after flush({FLUSH_TIMEOUT:g})")
        if len(self.failed) > self._reported:
            problems.append(f"{len(self.failed) - self._reported} more messages not delivered")
        if not problems:
            return
        text = "; ".join(problems)
        if exc is not None:
            # An exception is already going on: add to it, do not hide it.
            exc.add_note(f"KafkaSink: {text}")
            return
        self._reported = len(self.failed)
        raise self._error(text, pending=pending)

    # -- Internals --------------------------------------------------------------------

    def _check_run_id(self, what: str, run_id: str) -> None:
        if run_id != self.run_id:
            raise ValueError(f"{what} of run {run_id!r} in the sink of run {self.run_id!r}")

    def _error(self, text: str, pending: int = 0) -> SinkError:
        details = "; ".join(self._errors)
        return SinkError(
            f"{text}: {self.delivered} events delivered, failed {self.failed} ({details})",
            delivered=self.delivered,
            failed=tuple(self.failed),
            pending=pending,
            last_delivered=self.last_delivered,
        )

    def _produce(
        self,
        topic: str,
        key: bytes | None,
        value: bytes,
        headers: list[tuple[str, bytes]] | None,
        label: str,
        *,
        index: int | None = None,
    ) -> None:
        def on_delivery(error: object, _message: object) -> None:
            if error is not None:
                self.failed.append(label)
                self._errors.append(f"{label}: {error}")
            elif index is not None:
                self.delivered += 1
                if index > self._best:
                    self._best = index
                    self.last_delivered = label

        kwargs: dict[str, object] = {"key": key, "value": value, "on_delivery": on_delivery}
        if headers is not None:
            kwargs["headers"] = headers
        while True:
            try:
                self._producer.produce(topic, **kwargs)
                break
            except BufferError:
                # The local queue is full: serve the reports and try again, never drop.
                self._producer.poll(RETRY_POLL)
        self._producer.poll(0)
