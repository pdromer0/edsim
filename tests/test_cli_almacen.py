"""`edsim almacen preparar` y `consumir` sin Docker (tarea 7.5): los códigos de salida y los
textos, con los clientes reales sustituidos por los dobles de `fake_store.py`.

La CLI solo construye los clientes e imprime: lo que se sustituye son `prepare`,
`ensure_topics`, `bronze_store` y `connect_bronze_consumer`, tal como los importa `edsim.cli`.
Ctrl+C se simula con `signal.raise_signal(SIGINT)` desde el consumidor falso, como lo recibiría
el proceso.
"""

import signal
from contextlib import contextmanager

import pytest
from fake_store import FakeBroker, FakeBronzeConsumer, FakeStore
from test_store_consumer import STAMP_MS, publish_run

from edsim import cli
from edsim.live.kafka import BrokerUnavailableError
from edsim.store.migrations import Migration, MigrationError
from edsim.store.postgres import DatabaseUnavailableError, MissingPostgresExtraError

URL = "postgresql://edsim:secreta@localhost:5432/edsim"


def test_preparar_imprime_las_migraciones_aplicadas(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(
        cli, "prepare", lambda url: seen.append(url) or [Migration(1, "bronce", "")]
    )

    assert cli.main(["almacen", "preparar", "--postgres", URL]) == 0

    assert seen == [URL]
    assert capsys.readouterr().out == (
        "Postgres postgresql://edsim:***@localhost:5432/edsim\n"
        "Migraciones aplicadas: 001_bronce.sql\n"
    )


def test_preparar_sin_nada_que_aplicar(monkeypatch, capsys):
    monkeypatch.setattr(cli, "prepare", lambda url: [])

    assert cli.main(["almacen", "preparar"]) == 0
    assert "ninguna (la base de datos ya estaba al día)" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("error", "text"),
    [
        (DatabaseUnavailableError(URL, "connection refused"), "docker compose up --wait"),
        (MissingPostgresExtraError("Falta el extra postgres: uv sync"), "Falta el extra postgres"),
        (MigrationError("la base de datos tiene la migración 007_x"), "Error en las migraciones"),
    ],
)
def test_preparar_sale_con_1_si_postgres_falla(monkeypatch, capsys, error, text):
    def fail(url):
        raise error

    monkeypatch.setattr(cli, "prepare", fail)

    assert cli.main(["almacen", "preparar"]) == 1
    err = capsys.readouterr().err
    assert text in err
    assert "secreta" not in err


@pytest.mark.parametrize(
    "argv",
    [
        ["almacen", "consumir", "--timeout", "5"],
        ["almacen", "consumir", "--run", "r1", "--timeout", "0"],
        ["almacen", "consumir", "--run", "r1", "--timeout", "nan"],
        ["almacen", "consumir", "--postgres", "localhost:5432"],
        ["almacen", "preparar", "--postgres", "postgresql://"],
    ],
)
def test_los_errores_de_uso_salen_con_2_antes_de_conectar(monkeypatch, argv):
    monkeypatch.setattr(cli, "ensure_topics", lambda *a, **k: pytest.fail("conectó"))

    with pytest.raises(SystemExit) as caught:
        cli.main(argv)
    assert caught.value.code == 2


@pytest.fixture
def services(monkeypatch):
    """Un broker y un almacén falsos detrás de la CLI; devuelve (broker, store, consumers)."""
    broker = FakeBroker()
    store = FakeStore()
    consumers = []
    monkeypatch.setattr(cli, "ensure_topics", lambda *args, **kwargs: None)

    @contextmanager
    def fake_store(url):
        assert url == cli.DEFAULT_URL
        yield store

    def fake_consumer(bootstrap, *, watch=None):
        consumer = FakeBronzeConsumer(broker)
        consumers.append(consumer)
        return consumer

    monkeypatch.setattr(cli, "bronze_store", fake_store)
    monkeypatch.setattr(cli, "connect_bronze_consumer", fake_consumer)
    return broker, store, consumers


def test_consumir_con_run_termina_con_0_cuando_bronce_tiene_toda_la_ejecucion(services, capsys):
    broker, store, consumers = services
    publish_run(broker, "r1", [1, 2, 3], stamp_ms=STAMP_MS)

    assert cli.main(["almacen", "consumir", "--run", "r1"]) == 0

    out = capsys.readouterr().out
    assert out.startswith("r1: completa en bronce, 3 eventos de 3 publicados")
    assert "5 guardados · 0 repetidos ignorados · 0 rechazados" in out
    assert consumers[0].closed


def test_consumir_con_run_que_vence_sale_con_1_y_dice_cuantos_faltan(services, capsys):
    broker, _, consumers = services
    publish_run(broker, "r1", [1, 2, 3], stamp_ms=STAMP_MS, published=5)

    assert cli.main(["almacen", "consumir", "--run", "r1", "--timeout", "0.05"]) == 1

    out = capsys.readouterr().out
    assert out.startswith("r1: sin terminar tras 0 s; faltan 2 de 5 publicados")
    assert consumers[0].closed


def test_consumir_sin_run_para_con_ctrl_c_y_sale_con_0(services, capsys):
    broker, store, consumers = services
    publish_run(broker, "r1", [1, 2], stamp_ms=STAMP_MS)
    previous = signal.getsignal(signal.SIGINT)

    def install(consumer):
        calls = iter(range(10))
        consumer.on_consume = lambda: next(calls) == 1 and signal.raise_signal(signal.SIGINT)

    real = cli.connect_bronze_consumer

    def with_ctrl_c(bootstrap, *, watch=None):
        consumer = real(bootstrap, watch=watch)
        install(consumer)
        return consumer

    cli.connect_bronze_consumer = with_ctrl_c
    try:
        assert cli.main(["almacen", "consumir"]) == 0
    finally:
        cli.connect_bronze_consumer = real

    assert "Consumidor parado tras" in capsys.readouterr().out
    assert len(store.events) == 2  # el lote en curso se guardó y se confirmó
    assert broker.committed
    assert signal.getsignal(signal.SIGINT) is previous  # el manejador se restaura


def test_consumir_con_run_parado_con_ctrl_c_sale_con_1(services, capsys):
    broker, _, _ = services
    publish_run(broker, "r1", [1, 2, 3], stamp_ms=STAMP_MS, fin=False)
    real = cli.connect_bronze_consumer

    def with_ctrl_c(bootstrap, *, watch=None):
        consumer = real(bootstrap, watch=watch)
        consumer.on_consume = lambda: signal.raise_signal(signal.SIGINT)
        return consumer

    cli.connect_bronze_consumer = with_ctrl_c
    try:
        assert cli.main(["almacen", "consumir", "--run", "r1"]) == 1
    finally:
        cli.connect_bronze_consumer = real

    assert capsys.readouterr().out.startswith(
        "r1: parado con Ctrl+C; bronce tiene 3 eventos y aún no su fin"
    )


def test_consumir_con_una_marca_que_no_es_del_broker_sale_con_1(services, capsys):
    broker, store, _ = services
    broker.publish("ed.patient.events", b"{}", kind=1)

    assert cli.main(["almacen", "consumir"]) == 1

    assert "mal configurado" in capsys.readouterr().err
    assert store.events == {} and store.rejected == {}


def test_consumir_sin_broker_sale_con_1(monkeypatch, capsys):
    def no_broker(*args, **kwargs):
        raise BrokerUnavailableError("localhost:9092", 10.0)

    monkeypatch.setattr(cli, "ensure_topics", no_broker)
    monkeypatch.setattr(cli, "bronze_store", lambda url: pytest.fail("conectó con Postgres"))

    assert cli.main(["almacen", "consumir"]) == 1
    assert "no responde el broker de Kafka" in capsys.readouterr().err


def test_consumir_sin_postgres_sale_con_1(monkeypatch, capsys):
    monkeypatch.setattr(cli, "ensure_topics", lambda *args, **kwargs: None)

    @contextmanager
    def no_postgres(url):
        raise DatabaseUnavailableError(url, "connection refused")
        yield

    monkeypatch.setattr(cli, "bronze_store", no_postgres)
    monkeypatch.setattr(cli, "connect_bronze_consumer", lambda *a, **k: pytest.fail("Kafka"))

    assert cli.main(["almacen", "consumir"]) == 1
    assert "docker compose up --wait" in capsys.readouterr().err
