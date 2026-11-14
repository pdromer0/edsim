"""El aplicador de migraciones (tarea 7.5, H7-9) con una conexión falsa.

La conexión falsa apunta cada transacción y cada sentencia, y guarda las filas de
`public.migraciones`: así se ve qué se aplica, en qué orden y en qué transacción, sin Postgres.
Que el SQL de la 001 funcione de verdad lo prueba la integración (`edsim almacen preparar`).
"""

from contextlib import contextmanager

import pytest

from edsim.store.migrations import (
    CREATE_TABLE,
    RECORD,
    SELECT_APPLIED,
    Migration,
    MigrationError,
    apply_migrations,
    load_migrations,
)


class FakeConnection:
    """Una conexión que apunta lo que pasa y simula `public.migraciones`.

    `fail_on` es un texto: la sentencia que lo contiene lanza un error, como un SQL que falla.
    Lo registrado en una transacción que falla se deshace, como en Postgres.
    """

    def __init__(self, applied=(), fail_on=None):
        self.applied = list(applied)
        self.fail_on = fail_on
        self.log = []
        self._pending = None

    @contextmanager
    def transaction(self):
        self.log.append("BEGIN")
        self._pending = []
        try:
            yield self
        except Exception:
            self.log.append("ROLLBACK")
            self._pending = None
            raise
        self.applied.extend(self._pending)
        self._pending = None
        self.log.append("COMMIT")

    def execute(self, sql, params=()):
        assert self._pending is not None, f"sentencia fuera de una transacción: {sql!r}"
        self.log.append(sql)
        if self.fail_on is not None and self.fail_on in sql:
            raise RuntimeError(f"falla: {sql}")
        if sql == SELECT_APPLIED:
            return sorted(self.applied)
        if sql == RECORD:
            self._pending.append(tuple(params))
        return []


M1 = Migration(1, "bronce", "CREATE SCHEMA bronce;")
M2 = Migration(2, "columna", "ALTER TABLE bronce.eventos ADD COLUMN x text;")


def test_la_primera_vez_aplica_todas_en_orden_cada_una_en_su_transaccion():
    connection = FakeConnection()

    applied = apply_migrations(connection, [M1, M2])

    assert applied == [M1, M2]
    assert connection.log == [
        "BEGIN", CREATE_TABLE, SELECT_APPLIED, "COMMIT",
        "BEGIN", M1.sql, RECORD, "COMMIT",
        "BEGIN", M2.sql, RECORD, "COMMIT",
    ]  # fmt: skip
    assert connection.applied == [(1, "bronce"), (2, "columna")]


def test_la_segunda_vez_no_aplica_nada():
    connection = FakeConnection()
    apply_migrations(connection, [M1, M2])
    connection.log.clear()

    assert apply_migrations(connection, [M1, M2]) == []
    assert connection.log == ["BEGIN", CREATE_TABLE, SELECT_APPLIED, "COMMIT"]


def test_solo_aplica_las_que_faltan():
    connection = FakeConnection(applied=[(1, "bronce")])

    assert apply_migrations(connection, [M1, M2]) == [M2]
    assert M1.sql not in connection.log


def test_una_migracion_que_falla_no_queda_registrada_ni_sigue_con_las_demas():
    connection = FakeConnection(fail_on="ALTER TABLE")
    m3 = Migration(3, "otra", "CREATE TABLE bronce.otra ();")

    with pytest.raises(RuntimeError, match="falla"):
        apply_migrations(connection, [M1, M2, m3])

    # La 001 quedó aplicada en su transacción; la 002 se deshizo sin registrarse; la 003 no se
    # intentó.
    assert connection.applied == [(1, "bronce")]
    assert connection.log[-3:] == ["BEGIN", M2.sql, "ROLLBACK"]
    assert m3.sql not in connection.log


def test_una_version_que_el_codigo_no_conoce_es_un_error_antes_de_aplicar():
    connection = FakeConnection(applied=[(1, "bronce"), (7, "futura")])

    with pytest.raises(MigrationError, match="007_futura.*no conoce"):
        apply_migrations(connection, [M1, M2])
    assert M2.sql not in connection.log


def test_una_version_con_otro_nombre_es_un_error():
    connection = FakeConnection(applied=[(1, "plata")])

    with pytest.raises(MigrationError, match="se llama plata en la base de datos y bronce"):
        apply_migrations(connection, [M1, M2])


def test_los_ficheros_se_cargan_por_numero_y_se_ignora_lo_que_no_es_sql(tmp_path):
    (tmp_path / "010_diez.sql").write_text("SELECT 10;", encoding="utf-8")
    (tmp_path / "002_dos.sql").write_text("SELECT 2;", encoding="utf-8")
    (tmp_path / "LEEME.md").write_text("notas", encoding="utf-8")

    assert load_migrations(tmp_path) == (
        Migration(2, "dos", "SELECT 2;"),
        Migration(10, "diez", "SELECT 10;"),
    )


@pytest.mark.parametrize("name", ["1_bronce.sql", "001-bronce.sql", "001_Bronce.sql", "001_.sql"])
def test_un_nombre_que_no_es_nnn_nombre_es_un_error(tmp_path, name):
    (tmp_path / name).write_text("SELECT 1;", encoding="utf-8")

    with pytest.raises(MigrationError, match="NNN_nombre.sql"):
        load_migrations(tmp_path)


def test_dos_ficheros_con_el_mismo_numero_son_un_error(tmp_path):
    (tmp_path / "001_bronce.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "001_otra.sql").write_text("SELECT 1;", encoding="utf-8")

    with pytest.raises(MigrationError, match="dos migraciones con el número 001"):
        load_migrations(tmp_path)


def test_el_paquete_trae_la_001_bronce():
    migrations = load_migrations()

    assert [(m.version, m.name) for m in migrations] == [(1, "bronce")]
    assert "by_range('ingest_time')" in migrations[0].sql
