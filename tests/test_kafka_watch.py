"""El vigilante de la conexión con Kafka (tarea 6.6): avisos de corte y registro de librdkafka.

En la comprobación en vivo de la 6.5, con Kafka parado, librdkafka escribió unas 22 líneas
por segundo en stderr y enterró la línea de estado. BrokerWatch recibe las líneas, los
errores y las estadísticas de cada cliente y deja en la terminal, como mucho, un aviso al
perder el broker y otro al recuperarlo. Se prueba sin broker: los errores, las estadísticas
y las líneas se le pasan a mano, como los pasaría librdkafka en cada poll.
"""

import pytest
from fake_kafka import (
    REFUSED,
    FakeAdmin,
    FakeKafkaError,
    FakeProducer,
    install_fake_confluent_kafka,
    log_line,
    stats_json,
)

from edsim.engine.events import EventLog, MemorySink
from edsim.engine.scenarios import SCENARIO_START
from edsim.live.directo import SinkError
from edsim.live.kafka import (
    BrokerUnavailableError,
    BrokerWatch,
    KafkaControl,
    KafkaSink,
    connect_producer,
    ensure_topics,
)

PRODUCER, ORDERS = "productor", "órdenes"
LOST = (
    "se perdió la conexión con Kafka en localhost:9092 (" + REFUSED + "); librdkafka reintenta"
    " solo y los eventos esperan en la cola del productor"
)


class Clock:
    """Segundos a mano, para la duración del corte."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def watch():
    warnings: list[str] = []
    clock = Clock()
    watch = BrokerWatch("localhost:9092", warnings.append, clock=clock)
    watch.warnings, watch.clock = warnings, clock
    watch.configs = {client: watch.config(client) for client in (PRODUCER, ORDERS)}
    return watch


def stats(watch, client: str, up: bool) -> None:
    watch.configs[client]["stats_cb"](stats_json(up))


def error(watch, client: str, code: str, text: str = REFUSED) -> None:
    watch.configs[client]["error_cb"](FakeKafkaError(code, text))


def connected(watch) -> None:
    for client in (PRODUCER, ORDERS):
        stats(watch, client, True)


def cut(watch, errors: int = 40) -> None:
    """Un corte: el primer error llega con las estadísticas aún en UP (la conexión se
    rompe), después las estadísticas sin UP y los reintentos de los dos clientes."""
    error(watch, PRODUCER, "_TRANSPORT")
    for client in (PRODUCER, ORDERS):
        stats(watch, client, False)
    for i in range(errors):
        client = (PRODUCER, ORDERS)[i % 2]
        error(watch, client, "_ALL_BROKERS_DOWN" if i % 10 == 0 else "_TRANSPORT")


def back(watch, seconds: float) -> None:
    watch.clock.now += seconds
    connected(watch)


def test_un_corte_avisa_al_perder_y_al_recuperar(watch):
    connected(watch)
    cut(watch)
    back(watch, 62)

    assert watch.warnings == [LOST, "Kafka en localhost:9092 vuelve a responder tras 62 s"]
    # El primero, más los 16 de los 20 índices pares que no son _ALL_BROKERS_DOWN (0, 10,
    # 20 y 30, todos del productor).
    assert watch.errors[PRODUCER, "_TRANSPORT"] == 1 + 16
    assert watch.errors[PRODUCER, "_ALL_BROKERS_DOWN"] == 4
    assert not watch.lost


def test_dos_cortes_seguidos_avisan_cuatro_veces(watch):
    connected(watch)
    cut(watch)
    back(watch, 30)
    cut(watch)
    back(watch, 5)

    assert len(watch.warnings) == 4
    assert watch.warnings[2] == LOST
    assert watch.warnings[3].endswith("tras 5 s")


def test_la_vuelta_espera_a_los_dos_clientes(watch):
    connected(watch)
    cut(watch)
    watch.clock.now += 10
    stats(watch, PRODUCER, True)
    assert watch.warnings == [LOST]  # el consumidor de órdenes sigue sin broker
    assert watch.lost

    watch.clock.now += 2
    stats(watch, ORDERS, True)
    assert watch.warnings[1:] == ["Kafka en localhost:9092 vuelve a responder tras 12 s"]


def test_un_error_que_no_es_de_conexion_avisa_la_primera_vez_de_cada_codigo(watch):
    connected(watch)
    cut(watch)
    for _ in range(3):
        error(watch, PRODUCER, "_TIMED_OUT", "Request timed out")
    error(watch, ORDERS, "TOPIC_AUTHORIZATION_FAILED", "ed.control")
    error(watch, ORDERS, "TOPIC_AUTHORIZATION_FAILED", "ed.control")

    assert watch.warnings == [
        LOST,
        "error de Kafka en el cliente productor: _TIMED_OUT (Request timed out);"
        " los repetidos se cuentan al final",
        "error de Kafka en el cliente órdenes: TOPIC_AUTHORIZATION_FAILED (ed.control);"
        " los repetidos se cuentan al final",
    ]
    summary = watch.summary()
    assert "_TIMED_OUT 3" in summary
    assert "TOPIC_AUTHORIZATION_FAILED 2" in summary


def test_antes_de_conectar_no_avisa_de_perdida(watch):
    # El broker caído al arrancar ya lo dice BrokerUnavailableError.
    for _ in range(10):
        error(watch, PRODUCER, "_TRANSPORT")
        error(watch, ORDERS, "_ALL_BROKERS_DOWN")
    assert watch.warnings == []
    assert not watch.lost


def test_una_conexion_inactiva_cerrada_no_es_un_corte(watch):
    # connections.max.idle.ms: el broker cierra una conexión inactiva a los 10 minutos y
    # librdkafka lo notifica con _TRANSPORT; las estadísticas siguen diciendo UP.
    connected(watch)
    error(watch, PRODUCER, "_TRANSPORT", "localhost:9092/1: Disconnected (after 600000ms)")
    stats(watch, PRODUCER, True)
    assert watch.warnings == []

    # Con la siguiente estadística sin UP, otro _TRANSPORT sí es un corte.
    stats(watch, PRODUCER, False)
    error(watch, PRODUCER, "_TRANSPORT")
    assert watch.warnings == [LOST]


def test_ensure_topics_sirve_los_registros_del_admin_antes_de_fallar(monkeypatch, watch):
    admin = FakeAdmin(unreachable=True)
    install_fake_confluent_kafka(monkeypatch, admin)

    with pytest.raises(BrokerUnavailableError):
        ensure_topics("localhost:9092", connect_timeout=1, client_config=watch.config("admin"))

    assert admin.polls == [0]
    assert admin.config["logger"] is watch.config("admin")["logger"]


def test_ensure_topics_tambien_los_sirve_si_va_bien(monkeypatch, watch):
    admin = FakeAdmin()
    install_fake_confluent_kafka(monkeypatch, admin)

    ensure_topics("localhost:9092", client_config=watch.config("admin"))
    assert admin.polls == [0]


def test_el_resumen_por_cliente_y_tipo_con_la_primera_linea(tmp_path):
    path = tmp_path / "librdkafka.log"
    watch = BrokerWatch("localhost:9092", print, log_path=path)
    producer, orders = watch.config(PRODUCER), watch.config(ORDERS)
    for i in range(3):
        log_line(orders, "FAIL", f"refused {i}")
    log_line(producer, "FAIL", "refused p")
    log_line(producer, "GETPID", "Coordinator load in progress")
    watch.close()

    assert watch.summary().splitlines() == [
        f"librdkafka: 5 líneas (órdenes 3, productor 2); todas en {path}",
        "  órdenes · FAIL × 3: FAIL [edsim-x#producer-1] refused 0",
        "  productor · FAIL × 1: FAIL [edsim-x#producer-1] refused p",
        "  productor · GETPID × 1: GETPID [edsim-x#producer-1] Coordinator load in progress",
    ]
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5
    assert lines[0].endswith(" órdenes FAIL [edsim-x#producer-1] refused 0")


def test_sin_nada_que_contar_no_hay_resumen(watch):
    connected(watch)
    assert watch.summary() is None


def test_sin_fichero_el_resumen_dice_como_guardarlas(watch):
    log_line(watch.configs[ORDERS], "FAIL", "refused")
    error(watch, ORDERS, "_TRANSPORT")
    assert watch.summary().splitlines()[0] == (
        "librdkafka: 1 líneas (órdenes 1); 1 errores (_TRANSPORT 1);"
        " para guardarlas, --registro-kafka FICHERO"
    )


def test_la_configuracion_de_cada_cliente(watch):
    config = watch.config(PRODUCER)
    assert set(config) == {"logger", "error_cb", "stats_cb", "statistics.interval.ms"}
    assert config["statistics.interval.ms"] == 1000
    assert config["logger"].handlers and not config["logger"].propagate


def test_kafka_control_se_nombra_y_avisa_al_vigilante(monkeypatch, watch):
    kafka = install_fake_confluent_kafka(monkeypatch)

    control = KafkaControl("localhost:9092", "r2026_x", print, watch=watch)

    [consumer] = kafka.clients
    assert consumer.config["client.id"] == "edsim-control-r2026_x"
    assert consumer.config["group.id"] == "edsim-control-r2026_x"
    assert consumer.config["logger"].name.endswith(f".{ORDERS}")
    assert control.start_offset == 5


def test_el_productor_avisa_al_vigilante(monkeypatch, watch):
    kafka = install_fake_confluent_kafka(monkeypatch)

    connect_producer("localhost:9092", "r2026_x", watch=watch)

    [producer] = kafka.clients
    assert producer.config["client.id"] == "edsim-r2026_x"
    assert producer.config["enable.idempotence"] is True
    assert producer.config["logger"].name.endswith(f".{PRODUCER}")


def test_una_entrega_fallida_durante_un_corte_sigue_siendo_sink_error(watch):
    # El vigilante no toca los avisos de entrega: un mensaje que no llega para el directo.
    connected(watch)
    cut(watch)
    sink_ = MemorySink()
    log = EventLog("r1", SCENARIO_START, sink_, schema_version=3)
    for t in range(4):
        log.emit("staffing_changed", float(t), recurso="medicos", anterior=t, nueva=t + 1)
    sink = KafkaSink(FakeProducer(delivery_errors={2}), "r1")

    sink.write(sink_.events[0])
    sink.write(sink_.events[1])
    with pytest.raises(SinkError, match="Message timed out"):
        sink.write(sink_.events[2])
    assert watch.warnings == [LOST]
