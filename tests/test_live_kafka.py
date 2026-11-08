"""Acceso perezoso al cliente de Kafka (edsim.live.kafka), sin broker y sin el extra."""

import sys
import types

import pytest

from edsim.live.kafka import (
    MISSING_EXTRA_MESSAGE,
    MissingKafkaExtraError,
    import_confluent_kafka,
)


def test_sin_el_extra_el_error_dice_como_instalarlo(monkeypatch):
    """Sin confluent_kafka, el error es el nuestro, con el comando exacto que lo instala."""
    # Con None en sys.modules, `import confluent_kafka` falla aunque el paquete esté instalado.
    monkeypatch.setitem(sys.modules, "confluent_kafka", None)

    with pytest.raises(MissingKafkaExtraError) as excinfo:
        import_confluent_kafka()

    assert str(excinfo.value) == "Falta el extra kafka: uv sync --all-packages --extra kafka"
    assert MISSING_EXTRA_MESSAGE == str(excinfo.value)
    assert isinstance(excinfo.value, ImportError)
    assert isinstance(excinfo.value.__cause__, ImportError)


def test_con_el_paquete_devuelve_el_modulo(monkeypatch):
    """Con el paquete disponible, la función devuelve el módulo importado, no una copia."""
    # Un módulo falso: el test no necesita el extra y corre también en el job tests del CI.
    fake = types.ModuleType("confluent_kafka")
    monkeypatch.setitem(sys.modules, "confluent_kafka", fake)

    assert import_confluent_kafka() is fake
