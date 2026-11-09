"""The topics of the live mode and the rule that sends each event to one (H6-7).

Four topics, all with the broker's timestamp (``LogAppendTime``), deletion by
age and one replica (docs/specs/hito-6.md, "Especificación: topics y
mensajes"). The table is literal on purpose: a test compares it with a copy of
the specification, and ``edsim.live.kafka.ensure_topics`` creates and checks
the topics from it.

The rule looks only at ``episode_id``, never at the event type, so it holds for
any version of the catalog: an event with an episode goes to the patients'
topic, keyed by its episode, so the events of one patient are read in order;
one without it goes to the resources' topic, keyed by its ``recurso`` if the
payload has one.

Standard library only: no Kafka client.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from edsim.engine.events import Event

PATIENT_EVENTS = "ed.patient.events"
RESOURCE_EVENTS = "ed.resource.events"
RUNS = "ed.runs"
CONTROL = "ed.control"

REPLICATION_FACTOR = 1
"""One broker in milestone 6: every topic has one replica."""

TOPIC_CONFIG: Mapping[str, str] = MappingProxyType(
    {"message.timestamp.type": "LogAppendTime", "cleanup.policy": "delete"}
)
"""Configuration of the four topics; ``retention.ms`` keeps the broker's default (7 days).

``LogAppendTime``: the timestamp of a message is when the broker stored it, the
arrival time (H6-9). The producer never sets one.
"""


@dataclass(frozen=True, slots=True)
class Topic:
    """One topic of the live mode.

    Attributes:
        name: Name of the topic.
        partitions: Number of partitions.
        key: What the key of its messages is, as in the specification.
        config: Topic configuration for the broker.
    """

    name: str
    partitions: int
    key: str
    config: Mapping[str, str]


TOPICS: tuple[Topic, ...] = (
    Topic(PATIENT_EVENTS, 3, "episode_id", TOPIC_CONFIG),
    Topic(RESOURCE_EVENTS, 1, "recurso", TOPIC_CONFIG),
    Topic(RUNS, 1, "run_id", TOPIC_CONFIG),
    Topic(CONTROL, 1, "run_id", TOPIC_CONFIG),
)
"""The four topics, as in the table of the specification."""


def route(event: Event) -> tuple[str, bytes | None]:
    """The topic and the key of an event.

    With ``episode_id``: ``ed.patient.events`` and the episode as key. Without
    it: ``ed.resource.events`` and the ``recurso`` of the payload as key, or no
    key if the payload has none. The event type is never looked at.
    """
    if event.episode_id is not None:
        return PATIENT_EVENTS, event.episode_id.encode("utf-8")
    resource = event.payload.get("recurso")
    return RESOURCE_EVENTS, None if resource is None else str(resource).encode("utf-8")
