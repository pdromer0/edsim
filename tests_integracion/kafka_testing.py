"""Constantes y ayudas de los tests de integración, compartidas por conftest.py y los tests."""

import re
import time

DEFAULT_BOOTSTRAP = "localhost:9092"
BROKER_TIMEOUT = 10.0
"""Segundos para que el broker responda antes de dar los tests por fallidos."""
TIMEOUT = 30.0
"""Límite de cada operación de administración, `flush` y bucle de `poll`."""

PRODUCER_CONFIG = {
    "enable.idempotence": True,
    "acks": "all",
    "partitioner": "murmur2_random",
}
"""La configuración del productor de la especificación (H6-8), que la 6.4 llevará a KafkaSink."""

TOPIC_PART = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
"""Minúsculas, cifras y guiones: Kafka avisa si un nombre mezcla «.» y «_»."""


def deadline(seconds: float = TIMEOUT) -> float:
    """El instante del reloj monótono en que vence una espera."""
    return time.monotonic() + seconds
