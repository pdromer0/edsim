"""ensure_topics espera a que los topics nuevos se vean en los metadatos (tarea 6.4).

`create_topics` termina cuando el controlador tiene el topic, pero los metadatos del
broker pueden ir unos milisegundos por detrás. En la 6.4 se vio contra el broker de
compose.yaml: justo después de crearlos, 7 de 60 topics aún no aparecían, y una segunda
llamada a ensure_topics los intentaba crear otra vez (TOPIC_ALREADY_EXISTS) en 5 de 60.
Contra el broker no se reproduce a voluntad, así que la espera se prueba aquí, sin broker,
con un cliente de administración falso cuyos metadatos tardan en mostrar el topic.
"""

from types import SimpleNamespace

import pytest

from edsim.live.kafka import _wait_until_visible
from edsim.live.topics import TOPIC_CONFIG, Topic


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
