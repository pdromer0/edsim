"""SQL migrations of the store (docs/specs/hito-7.md, piece 5, H7-9).

A migration is a numbered SQL file in ``edsim/store/sql/`` (``001_bronce.sql``, …) that takes
the database from one version to the next. The table ``public.migraciones`` keeps the versions
already applied; ``apply_migrations`` applies only the missing ones, in order, each in its own
transaction, which also records it: a migration that fails leaves no trace.

Before applying anything it checks that the files and the database agree: every file name is
``NNN_nombre.sql``, no two files share a number, and every version recorded in the database is
a file of this code. A database migrated by a newer EDsim is an error, not something to ignore.

Standard library only: the connection is injected (``edsim.store.postgres`` gives the real one).
"""

import re
from collections.abc import Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from typing import Protocol

FILE_NAME = re.compile(r"(\d{3})_([a-z0-9]+(?:_[a-z0-9]+)*)\.sql")
"""``NNN_nombre.sql``: three digits, an underscore and a lowercase name."""

CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS public.migraciones (
    version integer PRIMARY KEY,
    nombre text NOT NULL,
    aplicada timestamptz NOT NULL
)"""
SELECT_APPLIED = "SELECT version, nombre FROM public.migraciones ORDER BY version"
RECORD = "INSERT INTO public.migraciones (version, nombre, aplicada) VALUES (%s, %s, now())"


class MigrationError(RuntimeError):
    """The migration files or the database are not as expected; nothing was applied."""


@dataclass(frozen=True, slots=True)
class Migration:
    """One migration file.

    Attributes:
        version: Its number, ``1`` for ``001_bronce.sql``.
        name: The name after the number, ``bronce``.
        sql: The text of the file, run as it is.
    """

    version: int
    name: str
    sql: str

    @property
    def file_name(self) -> str:
        return f"{self.version:03d}_{self.name}.sql"


class Connection(Protocol):
    """What the migrations need from a connection (``edsim.store.postgres`` gives it).

    ``transaction`` opens a transaction that commits when the block ends and rolls back if it
    raises. ``execute`` runs one statement, or a script without parameters, and returns its
    rows (none if it returns nothing).
    """

    def transaction(self) -> AbstractContextManager[object]: ...

    def execute(self, sql: str, params: Sequence[object] = ()) -> list[tuple]: ...


def sql_directory() -> Traversable:
    """The folder with the migrations of the package, ``edsim/store/sql/``."""
    return resources.files("edsim.store") / "sql"


def load_migrations(directory: Traversable | None = None) -> tuple[Migration, ...]:
    """The migrations of ``directory`` (by default, the package's), in order of version.

    Raises:
        MigrationError: If a ``.sql`` file is not named ``NNN_nombre.sql`` or two files share
            a number.
    """
    directory = sql_directory() if directory is None else directory
    by_version: dict[int, Migration] = {}
    for entry in sorted(directory.iterdir(), key=lambda item: item.name):
        if not entry.name.endswith(".sql"):
            continue
        match = FILE_NAME.fullmatch(entry.name)
        if match is None:
            raise MigrationError(
                f"{entry.name}: una migración se llama NNN_nombre.sql, como 001_bronce.sql"
            )
        version = int(match[1])
        if version in by_version:
            raise MigrationError(
                f"dos migraciones con el número {version:03d}: "
                f"{by_version[version].file_name} y {entry.name}"
            )
        by_version[version] = Migration(version, match[2], entry.read_text(encoding="utf-8"))
    return tuple(by_version[version] for version in sorted(by_version))


def pending_migrations(
    applied: Sequence[tuple[int, str]], migrations: Sequence[Migration]
) -> list[Migration]:
    """The migrations not applied yet, after checking that the database is one of this code.

    Args:
        applied: ``(version, nombre)`` of each row of ``public.migraciones``.
        migrations: Those of the code, as ``load_migrations`` gives them.

    Raises:
        MigrationError: If the database has a version the code does not know, or a known
            version under another name.
    """
    known = {migration.version: migration for migration in migrations}
    for version, name in applied:
        migration = known.get(version)
        if migration is None:
            raise MigrationError(
                f"la base de datos tiene la migración {version:03d}_{name}, que este EDsim no "
                "conoce: ¿la preparó una versión más nueva?"
            )
        if migration.name != name:
            raise MigrationError(
                f"la migración {version:03d} se llama {name} en la base de datos y "
                f"{migration.name} en el código"
            )
    done = {version for version, _ in applied}
    return [migration for migration in migrations if migration.version not in done]


def apply_migrations(
    connection: Connection, migrations: Sequence[Migration] | None = None
) -> list[Migration]:
    """Apply the migrations that are missing, each in its own transaction; the ones applied.

    The table ``public.migraciones`` is created first if it does not exist. Every check comes
    before the first migration: an error leaves the database as it was.

    Raises:
        MigrationError: See ``load_migrations`` and ``pending_migrations``.
    """
    migrations = load_migrations() if migrations is None else migrations
    with connection.transaction():
        connection.execute(CREATE_TABLE)
        rows = connection.execute(SELECT_APPLIED)
    applied = [(int(version), str(name)) for version, name in rows]
    pending = pending_migrations(applied, migrations)
    for migration in pending:
        with connection.transaction():
            connection.execute(migration.sql)
            connection.execute(RECORD, (migration.version, migration.name))
    return pending
