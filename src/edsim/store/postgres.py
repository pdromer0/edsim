"""Postgres for the bronze layer: the connection, the store and the reading (milestone 7).

``psycopg`` 3 is the optional ``postgres`` extra. This is the only module that imports it,
and only inside the functions that connect: importing this module never loads the client,
so the core and its tests run without the extra installed (the pattern of decision 49).

**The connection** (``connect``) is in autocommit mode, so each ``transaction()`` is a real
``BEGIN … COMMIT`` and a ``transaction()`` inside another one is a savepoint. That is what the
migrations (``edsim.store.migrations``) and the consumer (``edsim.store.consumer``) need.

**The store** (``PostgresBronze``) gives the consumer its primitives: transactions,
savepoints and the inserts with ``ON CONFLICT DO NOTHING``, each returning how many rows went
in. An error of the data (``psycopg.DataError``, ``psycopg.IntegrityError``, or a text the
client cannot encode) becomes ``StoreDataError``, which the consumer's safety net handles.

**The reading** (``read_bronze_lines``) gives back what was published of a run, as it came:
the ``valor`` of each ``event_id`` once, in order of ``sim_time`` and ``event_id``. Building
``Record`` from it is for the task that brings ``registro comparar --postgres`` (7.3).
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import astuple
from types import ModuleType

from edsim.store.bronze import EventRow, RejectedRow, RunRow
from edsim.store.consumer import RunProgress, StoreDataError
from edsim.store.migrations import Migration, apply_migrations

DEFAULT_URL = "postgresql://edsim:edsim@localhost:5432/edsim"
"""The Postgres of ``compose.yaml``."""

MISSING_EXTRA_MESSAGE = "Falta el extra postgres: uv sync --all-packages --extra postgres"

CONNECT_TIMEOUT = 10
"""Seconds to wait for Postgres before giving up."""


class MissingPostgresExtraError(ImportError):
    """The ``postgres`` extra (``psycopg``) is not installed."""


class DatabaseUnavailableError(RuntimeError):
    """Postgres does not answer at the URL, or refuses the connection."""

    def __init__(self, url: str, detail: str) -> None:
        self.url = url
        self.detail = detail
        super().__init__(f"no se puede conectar con Postgres en {safe_url(url)}: {detail}")


def safe_url(url: str) -> str:
    """``url`` without its password, to print it."""
    scheme, sep, rest = url.partition("://")
    credentials, at, host = rest.rpartition("@")
    if not sep or not at or ":" not in credentials:
        return url
    user = credentials.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"


def import_psycopg() -> ModuleType:
    """The ``psycopg`` module, or ``MissingPostgresExtraError`` if it is not installed."""
    try:
        import psycopg
    except ImportError as error:
        raise MissingPostgresExtraError(MISSING_EXTRA_MESSAGE) from error
    return psycopg


def _data_errors(psycopg: ModuleType) -> tuple[type[BaseException], ...]:
    return (psycopg.DataError, psycopg.IntegrityError, UnicodeEncodeError)


class PostgresConnection:
    """A psycopg connection in autocommit mode, with what the migrations need.

    Use it as a context manager, or call ``close``.
    """

    def __init__(self, connection) -> None:
        self._connection = connection

    @property
    def raw(self):
        """The ``psycopg.Connection`` underneath."""
        return self._connection

    def transaction(self):
        """A transaction; inside another one, a savepoint."""
        return self._connection.transaction()

    def execute(self, sql: str, params: Sequence[object] = ()) -> list[tuple]:
        """Run ``sql`` (a script without parameters is run as it is) and return its rows."""
        cursor = self._connection.execute(sql, params or None)
        return cursor.fetchall() if cursor.description is not None else []

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "PostgresConnection":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


def connect(
    url: str = DEFAULT_URL, *, connect_timeout: int = CONNECT_TIMEOUT
) -> PostgresConnection:
    """Connect to Postgres at ``url``, in autocommit mode.

    Raises:
        MissingPostgresExtraError: If the ``postgres`` extra is not installed.
        DatabaseUnavailableError: If Postgres does not answer or refuses the connection.
    """
    psycopg = import_psycopg()
    try:
        connection = psycopg.connect(url, autocommit=True, connect_timeout=connect_timeout)
    except psycopg.OperationalError as error:
        raise DatabaseUnavailableError(url, str(error).strip()) from error
    return PostgresConnection(connection)


def prepare(url: str = DEFAULT_URL) -> list[Migration]:
    """Apply the migrations that are missing in the database at ``url``; the ones applied.

    Raises:
        MissingPostgresExtraError: If the ``postgres`` extra is not installed.
        DatabaseUnavailableError: If Postgres does not answer.
        edsim.store.migrations.MigrationError: If the files and the database disagree.
    """
    with connect(url) as connection:
        return apply_migrations(connection)


INSERT_EVENTS = """\
INSERT INTO bronce.eventos (
    event_id, event_type, schema_version, run_id, episode_id, patient_id, source_system,
    sim_time, event_time, recorded_time, ingest_time, payload, kafka_topic, kafka_particion,
    kafka_offset, valor
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
ON CONFLICT DO NOTHING"""

INSERT_RUNS = """\
INSERT INTO bronce.ejecuciones (run_id, tipo, mensaje, ingest_time, kafka_offset)
VALUES (%s, %s, %s::jsonb, %s, %s)
ON CONFLICT DO NOTHING"""

INSERT_REJECTED = """\
INSERT INTO bronce.rechazados (
    valor, motivo, kafka_topic, kafka_particion, kafka_offset, ingest_time
) VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT DO NOTHING"""

PROGRESS = """\
WITH ultima AS (
    SELECT max(ingest_time) AS desde
    FROM bronce.ejecuciones
    WHERE run_id = %(run_id)s AND tipo = 'inicio'
)
SELECT
    ultima.desde,
    (
        SELECT (mensaje ->> 'publicados')::bigint
        FROM bronce.ejecuciones
        WHERE run_id = %(run_id)s AND tipo = 'fin' AND ingest_time >= ultima.desde
        ORDER BY ingest_time DESC
        LIMIT 1
    ),
    (
        SELECT count(DISTINCT event_id)
        FROM bronce.eventos
        WHERE run_id = %(run_id)s AND ingest_time >= ultima.desde
    )
FROM ultima"""

READ_LINES = """\
SELECT valor FROM (
    SELECT DISTINCT ON (event_id) event_id, sim_time, valor
    FROM bronce.eventos
    WHERE run_id = %s
    ORDER BY event_id, ingest_time
) AS una_por_evento
ORDER BY sim_time, event_id"""


class PostgresBronze:
    """The bronze store of the consumer (``edsim.store.consumer.Store``) on Postgres.

    Args:
        connection: From ``connect``.
    """

    def __init__(self, connection: PostgresConnection) -> None:
        self._connection = connection
        self._data_errors = _data_errors(import_psycopg())

    def transaction(self):
        return self._connection.transaction()

    def savepoint(self):
        return self._connection.transaction()

    def _insert(self, sql: str, rows: Sequence[tuple]) -> int:
        if not rows:
            return 0
        try:
            with self._connection.raw.cursor() as cursor:
                cursor.executemany(sql, rows)
                return cursor.rowcount
        except self._data_errors as error:
            raise StoreDataError(str(error).strip()) from error

    def insert_events(self, rows: Sequence[EventRow]) -> int:
        return self._insert(INSERT_EVENTS, [astuple(row) for row in rows])

    def insert_runs(self, rows: Sequence[RunRow]) -> int:
        return self._insert(INSERT_RUNS, [astuple(row) for row in rows])

    def insert_rejected(self, rows: Sequence[RejectedRow]) -> int:
        return self._insert(INSERT_REJECTED, [astuple(row) for row in rows])

    def progress(self, run_id: str) -> RunProgress:
        ((since, published, stored),) = self._connection.execute(PROGRESS, {"run_id": run_id})
        return RunProgress(since is not None, published, stored)


def read_bronze_lines(url: str, run_id: str) -> list[str]:
    """What was published of ``run_id``, from bronze: one ``valor`` per ``event_id``.

    If a run was published twice, bronze has two rows per ``event_id`` (they arrived at
    different times); this gives the one that arrived first. In order of ``sim_time`` and
    ``event_id``.

    Raises:
        MissingPostgresExtraError: If the ``postgres`` extra is not installed.
        DatabaseUnavailableError: If Postgres does not answer.
    """
    with connect(url) as connection:
        return [valor for (valor,) in connection.execute(READ_LINES, (run_id,))]


@contextmanager
def bronze_store(url: str = DEFAULT_URL) -> Iterator[PostgresBronze]:
    """A ``PostgresBronze`` on a new connection to ``url``, closed at the end."""
    with connect(url) as connection:
        yield PostgresBronze(connection)
