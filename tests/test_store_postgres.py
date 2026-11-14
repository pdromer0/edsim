"""Lo que `store/postgres.py` hace sin Postgres (tarea 7.5): el extra que falta, la URL sin la
contraseña, el error de conexión y la traducción de los errores de Postgres a los que la CLI
dice con código 1 (con un psycopg falso). Lo demás (el SQL, `ON CONFLICT`, el recuento, la
traducción de los errores de datos, `progress` y la lectura) lo prueba la integración, contra
el Postgres de `compose.yaml`."""

import sys
from contextlib import nullcontext
from types import ModuleType

import pytest

from edsim.store.migrations import MigrationError
from edsim.store.postgres import (
    MISSING_EXTRA_MESSAGE,
    DatabaseUnavailableError,
    MissingPostgresExtraError,
    PostgresBronze,
    bronze_store,
    connect,
    prepare,
    safe_url,
)


def test_sin_el_extra_el_error_dice_como_instalarlo(monkeypatch):
    monkeypatch.setitem(sys.modules, "psycopg", None)  # import psycopg lanza ImportError

    with pytest.raises(MissingPostgresExtraError, match="uv sync --all-packages --extra postgres"):
        connect("postgresql://edsim:edsim@localhost:5432/edsim")
    assert MISSING_EXTRA_MESSAGE.startswith("Falta el extra postgres")


@pytest.mark.parametrize(
    ("url", "printed"),
    [
        (
            "postgresql://edsim:edsim@localhost:5432/edsim",
            "postgresql://edsim:***@localhost:5432/edsim",
        ),
        ("postgresql://a:b:c@h/db", "postgresql://a:***@h/db"),
        ("postgresql://edsim@localhost/edsim", "postgresql://edsim@localhost/edsim"),
        ("postgresql://localhost/edsim", "postgresql://localhost/edsim"),
    ],
)
def test_la_url_se_imprime_sin_la_contrasena(url, printed):
    assert safe_url(url) == printed


def test_sin_postgres_el_error_lleva_la_url_sin_la_contrasena(monkeypatch):
    fake = ModuleType("psycopg")

    class OperationalError(Exception):
        pass

    def refuse(url, **kwargs):
        assert kwargs == {"autocommit": True, "connect_timeout": 10}
        raise OperationalError("connection refused\n")

    fake.OperationalError = OperationalError
    fake.connect = refuse
    monkeypatch.setitem(sys.modules, "psycopg", fake)

    with pytest.raises(DatabaseUnavailableError) as caught:
        connect("postgresql://edsim:secreta@localhost:5432/edsim")

    assert "secreta" not in str(caught.value)
    assert str(caught.value) == (
        "no se puede conectar con Postgres en postgresql://edsim:***@localhost:5432/edsim: "
        "connection refused"
    )


def fake_psycopg(monkeypatch, connection):
    """Un módulo psycopg falso con la jerarquía de errores de verdad y `connect` que da
    `connection`."""
    fake = ModuleType("psycopg")
    fake.Error = type("Error", (Exception,), {})
    for name in ("OperationalError", "InterfaceError", "DataError", "IntegrityError"):
        setattr(fake, name, type(name, (fake.Error,), {}))
    fake.ProgrammingError = type("ProgrammingError", (fake.Error,), {})
    fake.connect = lambda url, **kwargs: connection
    monkeypatch.setitem(sys.modules, "psycopg", fake)
    return fake


class FailingConnection:
    """Una conexión cuya primera sentencia lanza `error`; apunta si se cerró."""

    def __init__(self):
        self.error = None
        self.closed = False

    def transaction(self):
        return nullcontext()

    def execute(self, sql, params=None):
        raise self.error

    def close(self):
        self.closed = True


URL = "postgresql://edsim:secreta@localhost:5432/edsim"


def test_una_conexion_perdida_a_mitad_del_consumo_es_postgres_no_disponible(monkeypatch):
    connection = FailingConnection()
    psycopg = fake_psycopg(monkeypatch, connection)

    with pytest.raises(DatabaseUnavailableError) as caught:
        with bronze_store(URL) as store:
            raise psycopg.OperationalError("server closed the connection unexpectedly\n")

    assert str(caught.value) == (
        "no se puede conectar con Postgres en postgresql://edsim:***@localhost:5432/edsim: "
        "se perdió la conexión: server closed the connection unexpectedly"
    )
    assert isinstance(store, PostgresBronze) and connection.closed


def test_sin_las_tablas_de_bronce_el_error_dice_que_falta_preparar(monkeypatch):
    connection = FailingConnection()
    psycopg = fake_psycopg(monkeypatch, connection)
    connection.error = psycopg.ProgrammingError('relation "bronce.ejecuciones" does not exist')

    with pytest.raises(MigrationError, match="does not exist; ¿falta «edsim almacen preparar»?"):
        with bronze_store(URL) as store:
            store.progress("r1")


def test_una_migracion_que_postgres_rechaza_es_un_error_de_migraciones(monkeypatch):
    connection = FailingConnection()
    psycopg = fake_psycopg(monkeypatch, connection)
    connection.error = psycopg.Error('extension "timescaledb" is not available')

    with pytest.raises(MigrationError, match='rechazó la migración: extension "timescaledb"'):
        prepare(URL)
    assert connection.closed


def test_una_conexion_perdida_al_preparar_es_postgres_no_disponible(monkeypatch):
    connection = FailingConnection()
    psycopg = fake_psycopg(monkeypatch, connection)
    connection.error = psycopg.InterfaceError("the connection is lost")

    with pytest.raises(DatabaseUnavailableError, match="se perdió la conexión: the connection"):
        prepare(URL)
