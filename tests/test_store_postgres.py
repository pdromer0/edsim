"""Lo que `store/postgres.py` hace sin Postgres (tarea 7.5): el extra que falta, la URL sin la
contraseña y el error de conexión. Lo demás (el SQL, `ON CONFLICT`, el recuento, la
traducción de los errores de datos, `progress` y la lectura) lo prueba la integración, contra
el Postgres de `compose.yaml`."""

import sys
from types import ModuleType

import pytest

from edsim.store.postgres import (
    MISSING_EXTRA_MESSAGE,
    DatabaseUnavailableError,
    MissingPostgresExtraError,
    connect,
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
