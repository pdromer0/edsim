"""Kafka client access for the live mode.

``confluent-kafka`` is the optional ``kafka`` extra. This is the only module that imports it,
and only inside functions (a lazy import): importing this module never loads the client, so
the core and its tests run without the extra installed.
"""

from types import ModuleType

MISSING_EXTRA_MESSAGE = "Falta el extra kafka: uv sync --all-packages --extra kafka"


class MissingKafkaExtraError(ImportError):
    """The optional ``kafka`` extra (``confluent-kafka``) is not installed."""


def import_confluent_kafka() -> ModuleType:
    """Return the ``confluent_kafka`` module, importing it on first use.

    Raises:
        MissingKafkaExtraError: if the package is not installed, with the command that
            installs it.
    """
    try:
        import confluent_kafka
    except ImportError as exc:
        raise MissingKafkaExtraError(MISSING_EXTRA_MESSAGE) from exc
    return confluent_kafka
