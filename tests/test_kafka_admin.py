"""ensure_topics espera a que los topics nuevos se vean en los metadatos (tarea 6.4), y
crea o solo comprueba, con un primer contacto corto con el broker (tarea 6.5).

`create_topics` termina cuando el controlador tiene el topic, pero los metadatos del
broker pueden ir unos milisegundos por detrás. En la 6.4 se vio contra el broker de
compose.yaml: justo después de crearlos, 7 de 60 topics aún no aparecían, y una segunda
llamada a ensure_topics los intentaba crear otra vez (TOPIC_ALREADY_EXISTS) en 5 de 60.
Contra el broker no se reproduce a voluntad, así que la espera se prueba aquí, sin broker,
con un cliente de administración falso cuyos metadatos tardan en mostrar el topic.
"""

from types import SimpleNamespace

import pytest
from fake_kafka import FakeAdmin, install_fake_confluent_kafka

from edsim.live.kafka import (
    CONNECT_TIMEOUT,
    BrokerUnavailableError,
    MissingTopicsError,
    TopicMismatchError,
    TopicsReport,
    _wait_until_visible,
    ensure_topics,
)
from edsim.live.topics import CONTROL, PATIENT_EVENTS, TOPIC_CONFIG, TOPICS, Topic


class LaggingAdmin:
    """Un AdminClient falso: list_topics da, en cada llamada, la siguiente foto de `views`
    (y la última para siempre). Cada foto es {nombre: (particiones, error)}."""

    def __init__(self, views):
        self.views = list(views)
        self.calls = 0

    def list_topics(self, timeout=None):
        view = self.views[min(self.calls, len(self.views) - 1)]
        self.calls += 1
        topics = {
            name: SimpleNamespace(partitions=dict.fromkeys(range(n)), error=error)
            for name, (n, error) in view.items()
        }
        return SimpleNamespace(topics=topics)


NEW = [Topic("ed.patient.events", 3, "episode_id", TOPIC_CONFIG)]


def test_espera_a_que_el_topic_se_vea_entero():
    # Primero no aparece, después con error de líder y sin particiones, después entero.
    admin = LaggingAdmin(
        [
            {},
            {"ed.patient.events": (0, "LEADER_NOT_AVAILABLE")},
            {"ed.patient.events": (3, None)},
        ]
    )

    _wait_until_visible(admin, NEW, timeout=5)

    assert admin.calls == 3


def test_si_ya_se_ve_no_espera():
    admin = LaggingAdmin([{"ed.patient.events": (3, None)}])

    _wait_until_visible(admin, NEW, timeout=5)

    assert admin.calls == 1


def test_si_no_llega_a_verse_da_un_error_que_lo_nombra():
    admin = LaggingAdmin([{"ed.patient.events": (2, None)}])

    with pytest.raises(TimeoutError, match=r"ed\.patient\.events"):
        _wait_until_visible(admin, NEW, timeout=0.2)

    assert admin.calls > 1


# --- Crear o solo comprobar (tarea 6.5) -----------------------------------------------
#
# Con un módulo confluent_kafka falso (tests/fake_kafka.py): corren sin el extra.

LOG_APPEND = "LogAppendTime"
ALL_FOUR = {t.name: (t.partitions, LOG_APPEND) for t in TOPICS}


def test_sin_crear_falta_un_topic_y_lo_nombra(monkeypatch):
    admin = FakeAdmin({n: v for n, v in ALL_FOUR.items() if n != CONTROL})
    install_fake_confluent_kafka(monkeypatch, admin)

    with pytest.raises(MissingTopicsError, match=r"ed\.control.*edsim directo preparar"):
        ensure_topics("localhost:9092", TOPICS, create=False)

    assert admin.created == []
    assert CONTROL not in admin.topics


def test_sin_crear_con_los_cuatro_no_crea_nada(monkeypatch):
    admin = FakeAdmin(ALL_FOUR)
    install_fake_confluent_kafka(monkeypatch, admin)

    report = ensure_topics("localhost:9092", TOPICS, create=False)

    assert report == TopicsReport(created=(), existing=tuple(t.name for t in TOPICS))
    assert admin.created == []


def test_sin_crear_detecta_antes_uno_distinto(monkeypatch):
    # Uno distinto y otro que falta: el error es el de preparar, el mismo con o sin crear.
    topics = {n: v for n, v in ALL_FOUR.items() if n != CONTROL}
    topics[PATIENT_EVENTS] = (2, LOG_APPEND)
    install_fake_confluent_kafka(monkeypatch, FakeAdmin(topics))

    with pytest.raises(TopicMismatchError, match="2 partitions, expected 3"):
        ensure_topics("localhost:9092", TOPICS, create=False)


def test_crear_por_defecto_crea_los_que_faltan(monkeypatch):
    admin = FakeAdmin({n: v for n, v in ALL_FOUR.items() if n != CONTROL})
    install_fake_confluent_kafka(monkeypatch, admin)

    report = ensure_topics("localhost:9092", TOPICS)

    assert report.created == (CONTROL,)
    assert admin.created == [CONTROL]


def test_sin_broker_avisa_en_el_tiempo_de_conexion(monkeypatch):
    admin = FakeAdmin(unreachable=True)
    install_fake_confluent_kafka(monkeypatch, admin)

    with pytest.raises(BrokerUnavailableError, match="localhost:1 in 2.5 s") as raised:
        ensure_topics("localhost:1", TOPICS, connect_timeout=2.5)

    # La primera consulta usa el tiempo de conexión, no los 30 s de las demás.
    assert admin.list_timeouts == [2.5]
    assert (raised.value.bootstrap, raised.value.timeout) == ("localhost:1", 2.5)
    assert CONNECT_TIMEOUT == 10.0
