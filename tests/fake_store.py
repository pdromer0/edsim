"""Un Kafka y un Postgres falsos para el consumidor de bronce (tarea 7.5), sin Docker.

`FakeBroker` guarda los mensajes de cada partición y los offsets confirmados del grupo, que
sobreviven al consumidor: un `FakeBronzeConsumer` nuevo sobre el mismo broker sigue donde el
anterior confirmó, como un consumidor relanzado. Se le puede programar una caída al
confirmar.

`FakeStore` imita lo que el bucle usa de `PostgresBronze`: transacciones que se deshacen si
fallan, savepoints, la clave única de cada tabla con `ON CONFLICT DO NOTHING` y `progress`
con la regla de la última publicación. Imita la clave; que la de verdad sea (`event_id`,
`ingest_time`) lo comprueba la integración, contra Postgres.
"""

import json
from contextlib import contextmanager

from fake_kafka import LOG_APPEND_TIME, FakeRecord

from edsim.store.consumer import RunProgress, StoreDataError


class FakeBroker:
    """Los mensajes de cada (topic, partición) y los offsets confirmados."""

    def __init__(self) -> None:
        self.partitions: dict[tuple[str, int], list[FakeRecord]] = {}
        self.committed: dict[tuple[str, int], int] = {}

    def publish(self, topic, value, *, partition=0, stamp_ms=0, kind=LOG_APPEND_TIME, error=None):
        """Añade un mensaje al final de su partición; su offset."""
        log = self.partitions.setdefault((topic, partition), [])
        if isinstance(value, dict):
            value = json.dumps(value).encode("utf-8")
        log.append(FakeRecord(topic, partition, len(log), None, value, (kind, stamp_ms), error))
        return len(log) - 1


class Crash(Exception):
    """Una caída programada del consumidor."""


class FakeBronzeConsumer:
    """Un Consumer suscrito: `consume(n, timeout)` da hasta n mensajes desde su posición.

    Empieza en los offsets confirmados del broker (`earliest` si no hay). `commit` confirma
    su posición actual, como `commit(asynchronous=False)` sin offsets; `crash_on_commit`
    (número de llamada, desde 1) lanza `Crash` sin confirmar. Sin mensajes, `consume` avanza
    `clock` lo que espera.
    """

    def __init__(self, broker: FakeBroker, *, clock=None, crash_on_commit=None, log=None):
        self.broker = broker
        self.position = dict(broker.committed)
        self.clock = clock
        self.crash_on_commit = crash_on_commit
        self.commits: list[bool] = []
        self.log = log if log is not None else []
        self.closed = False
        self.on_consume = None  # si se da, se llama antes de cada consume

    def close(self):
        self.closed = True

    def consume(self, num_messages, timeout):
        if self.on_consume is not None:
            self.on_consume()
        batch = []
        for key in sorted(self.broker.partitions):
            log = self.broker.partitions[key]
            start = self.position.get(key, 0)
            taken = log[start : start + num_messages - len(batch)]
            batch.extend(taken)
            self.position[key] = start + len(taken)
            if len(batch) == num_messages:
                break
        if not batch and self.clock is not None:
            self.clock.now += timeout
        self.log.append(("consume", len(batch)))
        return batch

    def commit(self, *, asynchronous=True):
        self.commits.append(asynchronous)
        if self.crash_on_commit == len(self.commits):
            self.log.append(("crash",))
            raise Crash("caída entre guardar y apuntar")
        self.broker.committed.update(self.position)
        self.log.append(("commit", asynchronous))


class FakeStore:
    """Las tres tablas de bronce en memoria, con sus claves únicas.

    `fail_on`: un `event_id` cuyo INSERT falla con `StoreDataError`, como un dato que
    Postgres rechaza. `log` apunta transacciones, savepoints e inserts.
    """

    def __init__(self, *, fail_on=None, log=None):
        self.events: dict[tuple, object] = {}
        self.runs: dict[tuple, object] = {}
        self.rejected: dict[tuple, object] = {}
        self.fail_on = fail_on
        self.log = log if log is not None else []
        self._stack: list[tuple[dict, dict, dict]] = []

    def _snapshot(self):
        return dict(self.events), dict(self.runs), dict(self.rejected)

    @contextmanager
    def _block(self, name):
        self.log.append(name)
        self._stack.append(self._snapshot())
        try:
            yield self
        except BaseException:
            self.events, self.runs, self.rejected = self._stack.pop()
            self.log.append(f"rollback {name}")
            raise
        self._stack.pop()
        self.log.append(f"end {name}")

    def transaction(self):
        assert not self._stack, "transacción dentro de otra"
        return self._block("transaction")

    def savepoint(self):
        assert self._stack, "savepoint fuera de una transacción"
        return self._block("savepoint")

    def _insert(self, table, rows, key):
        assert self._stack, "insert fuera de una transacción"
        inserted = 0
        for row in rows:
            if self.fail_on is not None and getattr(row, "event_id", None) == self.fail_on:
                raise StoreDataError(f"dato rechazado en {row.event_id}")
            if key(row) not in table:
                table[key(row)] = row
                inserted += 1
        return inserted

    def insert_events(self, rows):
        self.log.append(("insert_events", len(rows)))
        return self._insert(self.events, rows, lambda r: (r.event_id, r.ingest_time))

    def insert_runs(self, rows):
        self.log.append(("insert_runs", len(rows)))
        return self._insert(self.runs, rows, lambda r: (r.run_id, r.tipo, r.ingest_time))

    def insert_rejected(self, rows):
        self.log.append(("insert_rejected", len(rows)))
        key = lambda r: (r.kafka_topic, r.kafka_particion, r.kafka_offset, r.ingest_time)  # noqa: E731
        return self._insert(self.rejected, rows, key)

    def progress(self, run_id):
        """La regla de la última publicación: desde el último inicio del run_id."""
        starts = [
            r.ingest_time for r in self.runs.values() if r.run_id == run_id and r.tipo == "inicio"
        ]
        if not starts:
            return RunProgress(started=False, published=None, stored=0)
        since = max(starts)
        ends = sorted(
            (r.ingest_time, json.loads(r.mensaje)["publicados"])
            for r in self.runs.values()
            if r.run_id == run_id and r.tipo == "fin" and r.ingest_time >= since
        )
        stored = {
            r.event_id
            for r in self.events.values()
            if r.run_id == run_id and r.ingest_time >= since
        }
        return RunProgress(True, ends[-1][1] if ends else None, len(stored))
