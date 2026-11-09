"""Kafka for the live mode: the producer, the sink and the client access.

``confluent-kafka`` is the optional ``kafka`` extra. This is the only module that imports it,
and only inside functions (a lazy import): importing this module never loads the client, so
the core and its tests run without the extra installed. ``KafkaSink`` takes a producer
already built, the real one (``connect_producer``) or a double in the tests.

**The producer** (docs/specs/hito-6.md, "Productor", H6-8) is idempotent, waits for every
replica (``acks=all``) and partitions with murmur2, as Java and Kafka Streams do. Everything
else keeps librdkafka's defaults.

**The orders** come from ``ed.control`` through ``KafkaControl``, which reads exactly the
orders published after it was created, and ``publish_order`` sends one (``edsim directo
control``). **The topics** are created and checked by ``ensure_topics`` from the table of
``edsim.live.topics``; with ``create=False`` it only checks. The first request to the broker
waits ``CONNECT_TIMEOUT``: without an answer, ``BrokerUnavailableError``.

**The sink** publishes the ``inicio`` and the ``fin`` of the run in ``ed.runs`` and each
event in its topic (``edsim.live.topics.route``), with the line of the JSONL as value, byte
for byte, and the headers ``event_type`` and ``schema_version``. It never sets a timestamp:
the topics use ``LogAppendTime``, the arrival time at the broker (H6-9).

Sending is asynchronous: ``produce`` queues the message and the result arrives later, in a
delivery report served by ``poll``. A full queue raises ``BufferError``: the sink serves the
reports for 0.1 s and tries again, so the pacer falls behind instead of losing a message. A
report with an error marks the sink as failed, and the next ``write`` raises ``SinkError``:
the run never goes on with a gap. And the ``fin`` waits for the confirmations: ``end``
flushes first, and if an event was not confirmed, the ``fin`` says ``error``.

**The watch** (task 6.6): ``BrokerWatch`` takes the lines, errors and statistics of
librdkafka instead of stderr, and warns once when the broker is lost and once when it is
back. **The reading** (task 6.6): ``read_run`` reads one run from Kafka into a
``LiveTracker`` (``edsim.live.tracker``), in a consumer group of its own, from the
beginning, until the ``fin`` and every event it published have arrived.
"""

import json
import logging
import time
import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from types import ModuleType, TracebackType
from typing import Protocol, Self

from edsim.engine.events import Event, from_json, to_json
from edsim.live.control import Command
from edsim.live.directo import REASON_ERROR, RunEnd, RunStart, SinkError
from edsim.live.messages import (
    END,
    START,
    control_json,
    parse_control,
    parse_run_message,
    run_end_json,
    run_start_json,
)
from edsim.live.report import (
    format_broker_back,
    format_broker_lost,
    format_kafka_error,
    format_kafka_log_summary,
)
from edsim.live.topics import (
    CONTROL,
    PATIENT_EVENTS,
    REPLICATION_FACTOR,
    RESOURCE_EVENTS,
    RUNS,
    TOPICS,
    Topic,
    route,
)
from edsim.live.tracker import LiveTracker, ReceivedEvent

MISSING_EXTRA_MESSAGE = "Falta el extra kafka: uv sync --all-packages --extra kafka"

FLUSH_TIMEOUT = 30.0
"""Seconds that leaving the sink waits for the pending messages."""

RETRY_POLL = 0.1
"""Seconds served on a full queue (``BufferError``) before trying again."""

ADMIN_TIMEOUT = 30.0
"""Seconds of each request to the broker of ``KafkaControl`` and ``ensure_topics``."""

CONNECT_TIMEOUT = 10.0
"""Seconds of the first look at the broker: without an answer, ``BrokerUnavailableError``.

Shorter than ``ADMIN_TIMEOUT`` and ``FLUSH_TIMEOUT``, which stay for creating topics and
for ``flush``: a broker that is not up is reported soon.
"""


class MissingKafkaExtraError(ImportError):
    """The optional ``kafka`` extra (``confluent-kafka``) is not installed."""


class BrokerUnavailableError(RuntimeError):
    """The broker did not answer in time: it is probably not up.

    Args:
        bootstrap: ``host:port`` that was tried.
        timeout: Seconds waited.
        detail: What the client said, if anything.
    """

    def __init__(self, bootstrap: str, timeout: float, detail: str = "") -> None:
        text = f"no answer from the Kafka broker at {bootstrap} in {timeout:g} s"
        super().__init__(f"{text} ({detail})" if detail else text)
        self.bootstrap = bootstrap
        self.timeout = timeout


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


# --- The connection watch ------------------------------------------------------------

STATS_INTERVAL_MS = 1000
"""Milliseconds between two statistics of each client: how soon a recovery is seen."""

ALL_BROKERS_DOWN = "_ALL_BROKERS_DOWN"
TRANSPORT = "_TRANSPORT"
TRANSPORT_ERRORS = frozenset({ALL_BROKERS_DOWN, TRANSPORT})
"""The errors of a lost connection: they warn once per outage, never one by one."""

_NOT_A_BROKER = frozenset({"logical", "internal"})
"""Handles in the statistics that are no connection of their own (the group coordinator)."""


@dataclass
class _Client:
    seen_up: bool = False  # it has had a broker UP: a later loss is an outage
    up_now: bool = False  # its last statistics had a broker UP
    down: bool = False  # it is in an outage


class _LogHandler(logging.Handler):
    """Gets the lines of librdkafka of one client (``logger`` of its configuration)."""

    def __init__(self, watch: "BrokerWatch", client: str) -> None:
        super().__init__(logging.DEBUG)
        self._watch = watch
        self._client = client

    def emit(self, record: logging.LogRecord) -> None:
        # confluent-kafka logs ("%s [%s] %s", facility, client name, text).
        facility = str(record.args[0]) if record.args else record.levelname
        self._watch._line(self._client, facility, record.getMessage())


class BrokerWatch:
    """Watches the connection of the Kafka clients of one command (task 6.6).

    librdkafka writes every failed connection on stderr: during an outage, about 22 lines
    per second, which buried the status line in task 6.5. Each client built with
    ``config(client)`` sends its lines to a logger of this watch instead, which counts them
    by client and type (and writes them to ``log_path``, if given), and its errors and
    statistics here:

    - **Lost.** A client that has been connected is down with ``_ALL_BROKERS_DOWN``, or with
      ``_TRANSPORT`` if its last statistics had no broker ``UP``: a lone ``_TRANSPORT`` with
      a broker still ``UP`` is the broker closing an idle connection
      (``connections.max.idle.ms``, 10 minutes), not an outage. The first client down
      gives one warning; the rest of the outage, none.
    - **Back.** A client is back when its statistics show a broker ``UP`` again; that does
      not need any message, so it also works for the consumer of the orders, which keeps a
      connection to the leader of its partition. When every client down is back, one
      warning with the seconds lost.
    - **Other errors** warn the first time of each code and are counted afterwards: a real
      problem is never hidden, and a repeated one does not flood the terminal.

    A failed delivery does not come here: it stays in the delivery report of
    ``KafkaSink`` (``SinkError`` and a ``fin`` with reason ``error``).

    Args:
        bootstrap: ``host:port`` of the broker, for the warnings.
        on_warning: Called with the text of each warning, in Spanish.
        log_path: If given, every line of librdkafka is written there with its time.
        clock: Monotonic seconds, for the length of an outage.

    Attributes:
        lines: Lines of librdkafka by ``(client, type)``.
        first_lines: The first line of each ``(client, type)``.
        errors: Errors by ``(client, code)``.
    """

    def __init__(
        self,
        bootstrap: str,
        on_warning: Callable[[str], None],
        *,
        log_path: str | Path | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.bootstrap = bootstrap
        self._on_warning = on_warning
        self._clock = clock
        self.log_path = None if log_path is None else Path(log_path)
        self._file = None if log_path is None else open(log_path, "w", encoding="utf-8")  # noqa: SIM115
        self._clients: dict[str, _Client] = {}
        self._lost_at: float | None = None
        self._warned: set[str] = set()
        self.lines: Counter[tuple[str, str]] = Counter()
        self.first_lines: dict[tuple[str, str], str] = {}
        self.errors: Counter[tuple[str, str]] = Counter()

    def config(self, client: str) -> dict[str, object]:
        """The part of the configuration of a client that reports to this watch."""
        self._clients.setdefault(client, _Client())
        logger = logging.getLogger(f"edsim.librdkafka.{id(self)}.{client}")
        logger.handlers = [_LogHandler(self, client)]
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        return {
            "logger": logger,
            "error_cb": lambda error: self.on_error(client, error),
            "stats_cb": lambda text: self.on_stats(client, text),
            "statistics.interval.ms": STATS_INTERVAL_MS,
        }

    @property
    def lost(self) -> bool:
        """Whether an outage is going on."""
        return self._lost_at is not None

    def on_error(self, client: str, error) -> None:
        """An error of ``error_cb`` (a ``KafkaError``: ``name()`` and ``str()``)."""
        name = error.name()
        self.errors[client, name] += 1
        state = self._clients.setdefault(client, _Client())
        if name in TRANSPORT_ERRORS:
            if name == TRANSPORT and state.up_now:
                return  # an idle connection closed by the broker, while still UP
            if state.seen_up and not state.down:
                state.down = True
                if self._lost_at is None:
                    self._lost_at = self._clock()
                    self._on_warning(format_broker_lost(self.bootstrap, error.str()))
            return
        if name not in self._warned:
            self._warned.add(name)
            self._on_warning(format_kafka_error(client, name, error.str()))

    def on_stats(self, client: str, text: str) -> None:
        """The statistics of a client (``stats_cb``): JSON with the state of each broker."""
        brokers = json.loads(text).get("brokers", {})
        up = any(
            b.get("state") == "UP" and b.get("source") not in _NOT_A_BROKER
            for b in brokers.values()
        )
        state = self._clients.setdefault(client, _Client())
        state.up_now = up
        if not up:
            return
        state.seen_up = True
        state.down = False
        if self._lost_at is not None and not any(c.down for c in self._clients.values()):
            seconds = self._clock() - self._lost_at
            self._lost_at = None
            self._on_warning(format_broker_back(self.bootstrap, seconds))

    def summary(self) -> str | None:
        """What librdkafka wrote, for the end of the command; ``None`` if nothing."""
        return format_kafka_log_summary(self.lines, self.first_lines, self.errors, self.log_path)

    def close(self) -> None:
        """Close the file of the lines, if any."""
        if self._file is not None:
            self._file.close()
            self._file = None

    def _line(self, client: str, facility: str, text: str) -> None:
        key = (client, facility)
        self.lines[key] += 1
        self.first_lines.setdefault(key, text)
        if self._file is not None:
            stamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
            self._file.write(f"{stamp} {client} {text}\n")
            self._file.flush()


PRODUCER_CLIENT = "productor"
CONTROL_CLIENT = "órdenes"
ADMIN_CLIENT = "administración"
READER_CLIENT = "lector"
"""Names of the clients in the warnings and in the summary of librdkafka."""


def _with_watch(config: dict[str, object], watch: BrokerWatch | None, client: str) -> dict:
    return config if watch is None else {**config, **watch.config(client)}


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


def connect_producer(bootstrap: str, run_id: str, *, watch: BrokerWatch | None = None):
    """A real ``confluent_kafka.Producer`` with ``producer_config``.

    With ``watch``, its lines, errors and statistics go to that ``BrokerWatch`` (client
    ``productor``) instead of stderr.

    Raises:
        MissingKafkaExtraError: If the ``kafka`` extra is not installed.
    """
    config = _with_watch(producer_config(bootstrap, run_id), watch, PRODUCER_CLIENT)
    return import_confluent_kafka().Producer(config)


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


def pending_messages(producer: Producer) -> int:
    """Messages still waiting for their confirmation, for the status line.

    It serves the delivery reports already arrived (``poll(0)``) and then counts what is
    left: ``len(producer)`` alone also counts the messages whose confirmation arrived but
    was not served yet, and between two events at ×60 nobody calls ``poll``.
    """
    producer.poll(0)
    return len(producer)


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
        """Wait for the confirmations, then publish the ``fin`` of the run in ``ed.runs``.

        The ``fin`` never gets ahead of the confirmations: a delivery can fail after the
        last ``write``, and then no ``write`` is left to notice it. So this first calls
        ``flush(FLUSH_TIMEOUT)`` and then decides:

        a) If something failed (an event or the ``inicio``), something is still pending,
           or the events confirmed are not ``message.published``: it publishes a ``fin``
           with reason ``error``, the same ``sim_time``, ``publicados`` = the events
           confirmed and ``ultimo_event_id`` = the highest one confirmed, and then
           raises ``SinkError``.
        b) If ``message`` is already a ``fin`` with reason ``error`` (``run_live`` after a
           ``SinkError``): it publishes it with the values after the flush, which may be
           more than those of the error, and does not raise.
        c) If every event is confirmed: it publishes ``message`` as it is.

        The ``fin`` is published even if the sink failed.

        Raises:
            SinkError: In case a), after publishing the ``fin`` with reason ``error``.
            ValueError: If the message is of another run.
        """
        self._check_run_id("RunEnd", message.run_id)
        pending = self._producer.flush(FLUSH_TIMEOUT)
        confirmed = replace(message, last_event_id=self.last_delivered, published=self.delivered)
        if message.reason == REASON_ERROR:
            self._publish_end(confirmed)
            return
        if not self.failed and not pending and self.delivered == message.published:
            self._publish_end(message)
            return
        self._publish_end(replace(confirmed, reason=REASON_ERROR))
        self._reported = len(self.failed)
        raise self._error(
            f"the run published {message.published} events and {self.delivered} were "
            f"confirmed ({pending} pending)",
            pending=pending,
        )

    def _publish_end(self, message: RunEnd) -> None:
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


# --- The orders ----------------------------------------------------------------------


class KafkaControl:
    """The orders of ``ed.control`` for one run: a ``ControlSource``.

    It joins no consumer group. On creation it reads the high offset of the only
    partition of ``ed.control`` and assigns itself that partition at that offset: it reads
    exactly the orders published after it was created, without the old ones and without
    waiting for a group to form (with ``subscribe`` and ``auto.offset.reset=latest``, an
    order sent while the group forms could be lost). It commits no offsets.

    Args:
        bootstrap: ``host:port`` of the broker.
        run_id: The run; orders of another run are ignored without a warning.
        on_invalid: Called with the reason of each invalid message, and with the errors of
            the consumer; the run goes on.
        watch: If given, its lines, errors and statistics go to that ``BrokerWatch``
            (client ``órdenes``) instead of stderr.

    Raises:
        MissingKafkaExtraError: If the ``kafka`` extra is not installed.
        BrokerUnavailableError: If the broker does not give the offsets in time.
    """

    def __init__(
        self,
        bootstrap: str,
        run_id: str,
        on_invalid: Callable[[str], None],
        *,
        watch: BrokerWatch | None = None,
    ) -> None:
        kafka = import_confluent_kafka()
        self.run_id = run_id
        self._on_invalid = on_invalid
        # The Python client needs a group.id even without subscribe: with it, librdkafka
        # also looks for the group coordinator, which retries every 50 ms without a broker
        # (reconnect.backoff.ms / 2). The client.id names its lines apart from the producer.
        self._consumer = kafka.Consumer(
            _with_watch(
                {
                    "bootstrap.servers": bootstrap,
                    "group.id": f"edsim-control-{run_id}",
                    "client.id": f"edsim-control-{run_id}",
                    "enable.auto.commit": False,
                },
                watch,
                CONTROL_CLIENT,
            )
        )
        try:
            partition = kafka.TopicPartition(CONTROL, 0)
            try:
                _, high = self._consumer.get_watermark_offsets(
                    partition, timeout=ADMIN_TIMEOUT, cached=False
                )
            except kafka.KafkaException as exc:
                raise BrokerUnavailableError(bootstrap, ADMIN_TIMEOUT, str(exc)) from exc
            self._consumer.assign([kafka.TopicPartition(CONTROL, 0, high)])
        except BaseException:
            self._consumer.close()
            raise
        self.start_offset = high
        """The offset of the first order it can read."""

    def poll(self) -> Command | None:
        """The next order for this run, if one has arrived; never waits."""
        message = self._consumer.poll(0)
        if message is None:
            return None
        if message.error():
            self._on_invalid(f"error reading ed.control: {message.error()}")
            return None
        return parse_control(message.value() or b"", self.run_id, self._on_invalid)

    def close(self) -> None:
        """Leave the partition and close the consumer."""
        self._consumer.close()


# --- Reading a run ------------------------------------------------------------------

READ_TOPICS = (PATIENT_EVENTS, RESOURCE_EVENTS, RUNS)
"""What a consumer of a run reads: its events and its ``inicio`` and ``fin``."""

READ_TIMEOUT = 120.0
"""Seconds a reading waits for the whole run before saying what is missing."""

READ_POLL = 0.1
"""Seconds of each ``poll`` of the reader."""

PROGRESS_INTERVAL = 5.0
"""Real seconds between two calls to ``on_progress``."""


def reader_group_id(run_id: str) -> str:
    """A new consumer group for one reading of ``run_id``: ``edsim-lector-<run_id>-<8 hex>``.

    A group keeps its position: a second reading in the same group would start where the
    first one ended and read nothing. One group per reading reads the whole run again, and
    Redpanda Console shows each one with its lag.
    """
    return f"edsim-lector-{run_id}-{uuid.uuid4().hex[:8]}"


def reader_config(
    bootstrap: str, group_id: str, watch: BrokerWatch | None = None
) -> dict[str, object]:
    """The configuration of a reader: a group of its own, read from the beginning.

    ``auto.offset.reset=earliest``: a new group without a position starts at the first
    message, not at the end (librdkafka's default, ``latest``), so the census, published
    before the reader joined, is read too. Offsets are committed automatically (the
    default) and once more at the end, so the group shows a lag of 0.
    """
    return _with_watch(
        {
            "bootstrap.servers": bootstrap,
            "group.id": group_id,
            "client.id": group_id,
            "auto.offset.reset": "earliest",
        },
        watch,
        READER_CLIENT,
    )


@dataclass(frozen=True, slots=True)
class ReadReport:
    """How a reading ended.

    Attributes:
        group_id: The consumer group of the reading.
        complete: Whether it saw the ``fin`` and as many distinct events as it published.
        timed_out: Whether it stopped because ``timeout`` ran out.
        missing: Events published and not read; ``None`` if the ``fin`` never arrived.
        seconds: How long it read.
        messages: Messages read, of any run.
        unreadable: Messages of the event topics that are not a JSON object, so of no
            run: skipped.
    """

    group_id: str
    complete: bool
    timed_out: bool
    missing: int | None
    seconds: float
    messages: int
    unreadable: int = 0


def read_run(
    bootstrap: str,
    run_id: str,
    tracker: LiveTracker,
    *,
    group_id: str | None = None,
    timeout: float = READ_TIMEOUT,
    watch: BrokerWatch | None = None,
    on_progress: Callable[[LiveTracker], None] | None = None,
    progress_interval: float = PROGRESS_INTERVAL,
    clock: Callable[[], float] = time.monotonic,
    wall: Callable[[], float] = time.time,
) -> ReadReport:
    """Read the run ``run_id`` from Kafka into ``tracker``, live or once it has ended.

    It subscribes to ``READ_TOPICS`` in a group of its own (``reader_group_id``), from the
    beginning. The events are those whose ``run_id``, in the value, is ``run_id``: their key
    is the ``episode_id``, so the topics mix every run. It looks at that ``run_id`` before
    validating: only the events of the run are checked, and a message that is not a JSON
    object is skipped and counted (``unreadable``). The ``inicio`` and the ``fin`` are
    the messages of ``ed.runs`` with ``run_id`` as key. Each event goes to the tracker with
    its topic, partition, offset, ``LogAppendTime`` timestamp and the time it was received.

    It ends when the tracker is complete: the ``fin`` says how many events were published,
    and it can arrive before the last events, because it travels in another topic. Or when
    ``timeout`` runs out, and then the report says how many are missing. In both cases it
    commits its offsets and closes.

    Args:
        bootstrap: ``host:port`` of the broker.
        run_id: The run to read.
        tracker: Where the events go.
        group_id: The consumer group; a new one if ``None``.
        timeout: Seconds to wait for the whole run.
        watch: If given, the lines and errors of librdkafka go there (client ``lector``).
        on_progress: Called with the tracker every ``progress_interval`` seconds.
        progress_interval: Seconds between two calls to ``on_progress``.
        clock: Monotonic seconds, for the timeout.
        wall: Seconds since the epoch, for the time of reception.

    Raises:
        MissingKafkaExtraError: If the ``kafka`` extra is not installed.
        ValueError: If a message of the run is not valid (an event of the run, or its
            ``inicio`` or ``fin``).
    """
    kafka = import_confluent_kafka()
    group_id = group_id or reader_group_id(run_id)
    consumer = kafka.Consumer(reader_config(bootstrap, group_id, watch))
    key = run_id.encode("utf-8")
    started = clock()
    limit = started + timeout
    next_progress = started + progress_interval
    messages = 0
    unreadable = 0
    try:
        consumer.subscribe(list(READ_TOPICS))
        while not tracker.complete and (now := clock()) < limit:
            message = consumer.poll(min(READ_POLL, limit - now))
            if on_progress is not None and clock() >= next_progress:
                on_progress(tracker)
                next_progress += progress_interval
            if message is None:
                continue
            if message.error():
                if watch is not None:
                    watch.on_error(READER_CLIENT, message.error())
                continue
            messages += 1
            received = wall()
            topic = message.topic()
            if topic == RUNS:
                if message.key() == key:
                    run_message = parse_run_message(message.value())
                    if isinstance(run_message, RunStart):
                        tracker.start(run_message)
                    else:
                        tracker.end(run_message)
                continue
            # Filter before validating: the topics mix every run, and a message of another
            # one (or one that is not even JSON) must not stop this reading. Only the events
            # of this run go through from_json and its checks.
            value = message.value()
            try:
                data = json.loads(value) if value is not None else None
            except ValueError:  # also UnicodeDecodeError
                data = None
            if not isinstance(data, dict):
                unreadable += 1
                continue
            if data.get("run_id") != run_id:
                continue
            event = from_json(value.decode("utf-8"))
            kind, stamp = message.timestamp()
            tracker.add(
                ReceivedEvent(
                    event,
                    topic=topic,
                    partition=message.partition(),
                    offset=message.offset(),
                    broker_ms=stamp if kind == kafka.TIMESTAMP_LOG_APPEND_TIME else None,
                    received=received,
                )
            )
    finally:
        try:
            consumer.commit(asynchronous=False)
        except kafka.KafkaException:
            pass  # nothing read, nothing to commit (_NO_OFFSET)
        consumer.close()
    return ReadReport(
        group_id=group_id,
        complete=tracker.complete,
        timed_out=not tracker.complete,
        missing=tracker.missing,
        seconds=clock() - started,
        messages=messages,
        unreadable=unreadable,
    )


class OrderNotDeliveredError(RuntimeError):
    """The broker answered the delivery of an order with an error."""


def publish_order(
    producer: Producer,
    run_id: str,
    command: Command,
    *,
    bootstrap: str,
    connect_timeout: float = CONNECT_TIMEOUT,
    timeout: float = FLUSH_TIMEOUT,
) -> int:
    """Publish one order for the run ``run_id`` in ``ed.control`` and wait for its delivery.

    First it asks the broker for the metadata of ``ed.control`` (``connect_timeout``), so a
    broker that is not up is reported soon; then it sends ``control_json`` with ``run_id`` as
    key and waits up to ``timeout`` for the confirmation.

    Args:
        producer: A ``confluent_kafka.Producer`` (``connect_producer``) or a double.
        run_id: The run the order is for; the key of the message.
        command: The order.
        bootstrap: ``host:port`` of the broker, for the error messages.
        connect_timeout: Seconds of the first look at the broker.
        timeout: Seconds to wait for the confirmation.

    Returns:
        The offset of the order in ``ed.control``.

    Raises:
        BrokerUnavailableError: If the broker does not answer in ``connect_timeout`` or the
            order is still pending after ``timeout``.
        OrderNotDeliveredError: If the broker answered the delivery with an error.
        MissingKafkaExtraError: If the ``kafka`` extra is not installed.
    """
    kafka = import_confluent_kafka()
    try:
        producer.list_topics(CONTROL, timeout=connect_timeout)
    except kafka.KafkaException as exc:
        raise BrokerUnavailableError(bootstrap, connect_timeout, str(exc)) from exc

    reports: list[tuple[object, object]] = []
    producer.produce(
        CONTROL,
        key=run_id.encode("utf-8"),
        value=control_json(run_id, command).encode("utf-8"),
        on_delivery=lambda error, message: reports.append((error, message)),
    )
    if producer.flush(timeout) or not reports:
        raise BrokerUnavailableError(bootstrap, timeout, "the order was not confirmed")
    [(error, message)] = reports
    if error is not None:
        raise OrderNotDeliveredError(f"the order was not delivered to {CONTROL}: {error}")
    return message.offset()


# --- The topics ----------------------------------------------------------------------


class TopicMismatchError(RuntimeError):
    """A topic exists with another number of partitions or another timestamp type."""


class MissingTopicsError(RuntimeError):
    """Some topics do not exist and the caller asked not to create them."""


@dataclass(frozen=True, slots=True)
class TopicsReport:
    """What ``ensure_topics`` did.

    Attributes:
        created: The topics it created.
        existing: The topics that were already there, as expected.
    """

    created: tuple[str, ...]
    existing: tuple[str, ...]


TIMESTAMP_TYPE = "message.timestamp.type"

VISIBILITY_POLL = 0.05
"""Seconds between two looks at the metadata while a new topic becomes visible."""


def _wait_until_visible(admin, topics: list[Topic], timeout: float) -> None:
    """Wait until the broker's metadata lists each new topic with all its partitions.

    ``create_topics`` is done when the controller has the topic, but the metadata of
    the broker can lag a few milliseconds (measured in task 6.4: right after creating,
    7 of 60 topics were not listed yet). A caller that looked then would think the topic
    missing, try to create it again and get ``TOPIC_ALREADY_EXISTS``.

    Raises:
        TimeoutError: If a topic is not visible after ``timeout`` seconds.
    """
    waiting = {t.name: t.partitions for t in topics}
    limit = time.monotonic() + timeout
    while True:
        metadata = admin.list_topics(timeout=timeout)
        for name in list(waiting):
            found = metadata.topics.get(name)
            if found is not None and found.error is None and len(found.partitions) == waiting[name]:
                del waiting[name]
        if not waiting:
            return
        if time.monotonic() >= limit:
            raise TimeoutError(
                f"topics created but not visible after {timeout:g} s: {sorted(waiting)}"
            )
        time.sleep(VISIBILITY_POLL)


def ensure_topics(
    bootstrap: str,
    topics: Iterable[Topic] = TOPICS,
    *,
    create: bool = True,
    timeout: float = ADMIN_TIMEOUT,
    connect_timeout: float = CONNECT_TIMEOUT,
    client_config: Mapping[str, object] | None = None,
) -> TopicsReport:
    """Create the topics that are missing and check the ones that exist.

    When it returns, the topics it created are listed in the broker's metadata with all
    their partitions. An existing topic must have the number of partitions and the timestamp type
    (``message.timestamp.type``) of its definition. Everything is checked before anything
    is created: if a topic differs, nothing is created. With ``create=False`` it only
    checks: ``edsim directo lanzar`` and ``reemitir`` never create a topic, so that a wrong
    ``--kafka`` does not leave new topics in another broker; only ``preparar`` creates.

    Args:
        bootstrap: ``host:port`` of the broker.
        topics: The definitions; the four of the live mode by default.
        create: Whether to create the missing topics.
        timeout: Seconds of each request after the first one.
        connect_timeout: Seconds of the first request, the one that finds out whether the
            broker is up.
        client_config: More configuration of the ``AdminClient``, such as
            ``BrokerWatch.config``. Its logs and errors are served (``poll(0)``) before
            returning or raising, so they are not lost.

    Returns:
        Which topics it created and which were already there.

    Raises:
        BrokerUnavailableError: If the broker does not answer in ``connect_timeout``.
        TopicMismatchError: If an existing topic differs, saying which and how.
        MissingTopicsError: With ``create=False``, if some topic does not exist.
        TimeoutError: If a topic created is not visible after ``timeout`` seconds.
        MissingKafkaExtraError: If the ``kafka`` extra is not installed.
    """
    topics = list(topics)
    kafka = import_confluent_kafka()  # the message that says how to install the extra
    from confluent_kafka.admin import AdminClient

    admin = AdminClient({"bootstrap.servers": bootstrap, **(client_config or {})})
    try:
        return _ensure_topics(admin, kafka, bootstrap, topics, create, timeout, connect_timeout)
    finally:
        admin.poll(0)  # serve its logs and errors to the watch before letting it go


def _ensure_topics(
    admin, kafka, bootstrap, topics: list[Topic], create, timeout, connect_timeout
) -> TopicsReport:
    from confluent_kafka.admin import ConfigResource, NewTopic, ResourceType

    try:
        metadata = admin.list_topics(timeout=connect_timeout)
    except kafka.KafkaException as exc:
        raise BrokerUnavailableError(bootstrap, connect_timeout, str(exc)) from exc
    existing = [t for t in topics if t.name in metadata.topics]
    missing = [t for t in topics if t.name not in metadata.topics]

    problems = []
    for topic in existing:
        partitions = len(metadata.topics[topic.name].partitions)
        if partitions != topic.partitions:
            problems.append(f"{topic.name}: {partitions} partitions, expected {topic.partitions}")
    if existing:
        resources = [ConfigResource(ResourceType.TOPIC, t.name) for t in existing]
        futures = admin.describe_configs(resources, request_timeout=timeout)
        for topic, resource in zip(existing, resources, strict=True):
            configs = futures[resource].result(timeout=timeout)
            found = configs[TIMESTAMP_TYPE].value
            wanted = topic.config[TIMESTAMP_TYPE]
            if found != wanted:
                problems.append(f"{topic.name}: {TIMESTAMP_TYPE} is {found}, expected {wanted}")
    if problems:
        raise TopicMismatchError("topics that differ: " + "; ".join(problems))
    if missing and not create:
        raise MissingTopicsError(
            f"topics missing: {', '.join(t.name for t in missing)}; "
            "create them with `edsim directo preparar`"
        )

    if missing:
        new = [
            NewTopic(
                t.name,
                num_partitions=t.partitions,
                replication_factor=REPLICATION_FACTOR,
                config=dict(t.config),
            )
            for t in missing
        ]
        futures = admin.create_topics(new, request_timeout=timeout)
        for topic in missing:
            futures[topic.name].result(timeout=timeout)
        _wait_until_visible(admin, missing, timeout)
    return TopicsReport(
        created=tuple(t.name for t in missing), existing=tuple(t.name for t in existing)
    )
