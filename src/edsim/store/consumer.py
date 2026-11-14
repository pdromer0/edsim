"""The consumer from Kafka to bronze: save, then commit (docs/specs/hito-7.md, piece 4, H7-8).

**The order is the heart of it.** The consumer reads a batch, saves it in one transaction with
``ON CONFLICT DO NOTHING`` and only then commits its offsets, synchronously. If it falls
between the two, it reads the batch again when it comes back, and the unique key
(``event_id``, ``ingest_time``) makes saving it twice the same as saving it once: at least
once, plus idempotent inserts. Committing first would lose the batch instead.

**The clients are injected.** ``run_consumer`` takes the Kafka consumer (``confluent_kafka``
through ``edsim.live.kafka.connect_bronze_consumer``, or a double) and the store (the
primitives of ``edsim.store.postgres.PostgresBronze``, or a double), so the loop, the order and
the safety net are tested without Docker.

**The safety net.** ``edsim.store.bronze`` already rejects what Postgres is known to refuse.
If the INSERT of a batch still fails on the data (``StoreDataError``), the batch is saved
again row by row, each row in a savepoint: only the row that fails goes to ``rechazados``,
with the message of Postgres. No unexpected message can block the consumer. An error that is
not about the data (the connection drops) goes up without committing.

**How it stops.** Continuously, until ``should_stop`` says so between two batches (the CLI
sets it on Ctrl+C), the batch in progress saved and committed. Or, with ``run_id``, when bronze
holds the whole last publication of that run (``Store.progress``), or when ``timeout`` runs
out.

Standard library only.
"""

import time
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol

from edsim.store.bronze import EventRow, KafkaMessage, RejectedRow, Row, RunRow, printable, to_row

BATCH_SIZE = 500
"""Messages of a batch at most (``consume(500, 1.0)``)."""

POLL_TIMEOUT = 1.0
"""Seconds a ``consume`` waits for its batch."""

RUN_TIMEOUT = 120.0
"""Seconds ``--run`` waits for the whole run before saying what is missing."""

PROGRESS_INTERVAL = 10.0
"""Seconds between two calls to ``on_progress``."""


class StoreDataError(Exception):
    """The store refused a row because of its data (``psycopg.DataError`` and the like)."""


@dataclass(frozen=True, slots=True)
class RunProgress:
    """How much of the last publication of a run bronze holds.

    Attributes:
        started: Whether bronze has an ``inicio`` of the run.
        published: ``publicados`` of the ``fin`` of the last publication; ``None`` without it.
        stored: Distinct ``event_id`` of the last publication in ``bronce.eventos``.
    """

    started: bool
    published: int | None
    stored: int

    @property
    def complete(self) -> bool:
        return self.published is not None and self.stored >= self.published

    @property
    def missing(self) -> int | None:
        """Events published and not in bronze; ``None`` if the ``fin`` has not arrived."""
        return None if self.published is None else max(self.published - self.stored, 0)


class Store(Protocol):
    """The primitives of a bronze store (``edsim.store.postgres.PostgresBronze``).

    ``transaction`` commits when its block ends and rolls back if it raises; ``savepoint``,
    inside a transaction, rolls back only its own block. Each ``insert_*`` inserts with ``ON
    CONFLICT DO NOTHING`` and returns how many rows were inserted (the rest were already
    there), and raises ``StoreDataError`` if a row is refused for its data.
    """

    def transaction(self) -> AbstractContextManager[object]: ...

    def savepoint(self) -> AbstractContextManager[object]: ...

    def insert_events(self, rows: Sequence[EventRow]) -> int: ...

    def insert_runs(self, rows: Sequence[RunRow]) -> int: ...

    def insert_rejected(self, rows: Sequence[RejectedRow]) -> int: ...

    def progress(self, run_id: str) -> RunProgress: ...


class Message(Protocol):
    """What the loop reads from a ``confluent_kafka.Message``."""

    def error(self) -> object: ...

    def topic(self) -> str: ...

    def partition(self) -> int: ...

    def offset(self) -> int: ...

    def timestamp(self) -> tuple[int, int]: ...

    def value(self) -> bytes | None: ...


class Consumer(Protocol):
    """What the loop needs from a ``confluent_kafka.Consumer`` already subscribed."""

    def consume(self, num_messages: int, timeout: float) -> list[Message]: ...

    def commit(self, *, asynchronous: bool) -> object: ...


@dataclass(frozen=True, slots=True)
class BatchResult:
    """What saving one batch did.

    Attributes:
        saved: Events and messages of ``ed.runs`` inserted.
        repeated: Those already in bronze, ignored (a reading after a crash).
        rejected: Messages that went to ``rechazados``, by ``bronze`` or by the safety net.
        retried: Whether the batch went through the safety net.
    """

    saved: int
    repeated: int
    rejected: int
    retried: bool


@dataclass(slots=True)
class ConsumeReport:
    """How a consumption went; it grows while the loop runs (``on_progress`` sees it).

    Attributes:
        messages: Messages read with a value, of any run.
        saved: Rows inserted in ``eventos`` and ``ejecuciones``.
        repeated: Rows that were already there, ignored.
        rejected: Messages sent to ``rechazados``.
        errors: Messages that were an error of the client, set aside.
        batches: Batches saved and committed.
        retried: Batches that went through the safety net.
        seconds: How long it ran.
        progress: With ``run_id``, the last ``Store.progress`` read.
        complete: With ``run_id``, whether bronze holds the whole last publication.
        timed_out: Whether ``timeout`` ran out.
        stopped: Whether ``should_stop`` stopped it.
    """

    messages: int = 0
    saved: int = 0
    repeated: int = 0
    rejected: int = 0
    errors: int = 0
    batches: int = 0
    retried: int = 0
    seconds: float = 0.0
    progress: RunProgress | None = None
    complete: bool = False
    timed_out: bool = False
    stopped: bool = False

    @property
    def missing(self) -> int | None:
        """With ``run_id``, events published and not in bronze; ``None`` without the ``fin``."""
        return None if self.progress is None else self.progress.missing


def _rejection(message: KafkaMessage, row: Row, reason: str) -> RejectedRow:
    return RejectedRow(
        valor=printable(message.value),
        motivo=reason,
        kafka_topic=message.topic,
        kafka_particion=message.partition,
        kafka_offset=message.offset,
        ingest_time=row.ingest_time,
    )


def save_batch(store: Store, batch: Sequence[tuple[KafkaMessage, Row]]) -> BatchResult:
    """Save ``batch`` in one transaction; if the data fails, row by row with savepoints.

    Raises:
        Exception: Whatever the store raises that is not ``StoreDataError``; nothing is saved.
    """
    events = [row for _, row in batch if isinstance(row, EventRow)]
    runs = [row for _, row in batch if isinstance(row, RunRow)]
    rejected = [row for _, row in batch if isinstance(row, RejectedRow)]
    try:
        with store.transaction():
            saved = store.insert_events(events) + store.insert_runs(runs)
            store.insert_rejected(rejected)
        return BatchResult(saved, len(events) + len(runs) - saved, len(rejected), retried=False)
    except StoreDataError:
        pass
    saved = repeated = 0
    with store.transaction():
        for message, row in batch:
            if isinstance(row, RejectedRow):
                continue
            insert = store.insert_events if isinstance(row, EventRow) else store.insert_runs
            try:
                with store.savepoint():
                    inserted = insert([row])
            except StoreDataError as error:
                rejected.append(_rejection(message, row, f"Postgres lo rechaza: {error}"))
                continue
            saved += inserted
            repeated += 1 - inserted
        store.insert_rejected(rejected)
    return BatchResult(saved, repeated, len(rejected), retried=True)


def run_consumer(
    consumer: Consumer,
    store: Store,
    *,
    run_id: str | None = None,
    timeout: float | None = None,
    batch_size: int = BATCH_SIZE,
    poll_timeout: float = POLL_TIMEOUT,
    should_stop: Callable[[], bool] = lambda: False,
    on_progress: Callable[[ConsumeReport], None] | None = None,
    on_error: Callable[[object], None] | None = None,
    progress_interval: float = PROGRESS_INTERVAL,
    clock: Callable[[], float] = time.monotonic,
) -> ConsumeReport:
    """Read batches from ``consumer`` and keep them in ``store``: save, then commit.

    Each batch: the messages that are an error of the client go to ``on_error`` and are set
    aside; every other one becomes a row (``bronze.to_row``); the rows are saved
    (``save_batch``) and only then the offsets are committed, synchronously. A batch with
    nothing to save is not committed.

    Args:
        consumer: Subscribed to the topics; the caller closes it.
        store: Where the rows go.
        run_id: If given, stop when bronze holds the whole last publication of this run.
        timeout: With ``run_id``, seconds to wait for it; ``None``, no limit.
        batch_size: Messages of a batch at most.
        poll_timeout: Seconds a ``consume`` waits.
        should_stop: Asked between two batches; ``True`` ends the loop.
        on_progress: Called with the report every ``progress_interval`` seconds.
        on_error: Called with the error of each message that is one.
        progress_interval: Seconds between two calls to ``on_progress``.
        clock: Monotonic seconds.

    Raises:
        edsim.store.bronze.TimestampTypeError: If a message does not carry the
            ``LogAppendTime`` timestamp; its batch is neither saved nor committed.
    """
    report = ConsumeReport()
    started = clock()
    limit = None if run_id is None or timeout is None else started + timeout
    next_progress = started + progress_interval
    try:
        while True:
            if run_id is not None:
                report.progress = store.progress(run_id)
                if report.progress.complete:
                    report.complete = True
                    break
            if should_stop():
                report.stopped = True
                break
            if limit is not None and clock() >= limit:
                report.timed_out = True
                break
            batch = []
            for message in consumer.consume(batch_size, poll_timeout):
                if message.error():
                    report.errors += 1
                    if on_error is not None:
                        on_error(message.error())
                    continue
                kind, stamp = message.timestamp()
                data = KafkaMessage(
                    message.topic(),
                    message.partition(),
                    message.offset(),
                    kind,
                    stamp,
                    message.value(),
                )
                batch.append((data, to_row(data)))
            if batch:
                result = save_batch(store, batch)
                consumer.commit(asynchronous=False)
                report.messages += len(batch)
                report.saved += result.saved
                report.repeated += result.repeated
                report.rejected += result.rejected
                report.batches += 1
                report.retried += result.retried
            if on_progress is not None and clock() >= next_progress:
                report.seconds = clock() - started
                on_progress(report)
                next_progress += progress_interval
    finally:
        report.seconds = clock() - started
    return report
