"""Bronze without Kafka: the messages the consumer would have stored for a run (task 8.8).

For tests and notebooks. ``bronze_messages`` builds, from what a run published, the messages
that ``edsim almacen consumir`` would have read from Kafka: an ``inicio`` of ``ed.runs``, one
message per line and a ``fin``, each one with its ``LogAppendTime``. ``write_bronze``
(``edsim.store.postgres``) saves them with ``save_batch``, the same path as the consumer. Bronze
ends up as after a replay that the consumer read whole, without Kafka running.

It does not replace the consumer: nothing here reads Kafka, and the timestamps are made up from
``started_ms``, not given by a broker. Unlike a replay (``edsim directo reemitir``), it takes
every line given, the warm-up too: a replay publishes as census only the episodes open at ``W``
according to the truth, so a departure that was never written down (a ghost) would not reach
bronze, and the census of a recording would come out smaller than in a real hospital.
"""

import json
from collections.abc import Sequence

from edsim.live.control import MAX_SPEED
from edsim.live.directo import REASON_HORIZON, RunEnd, RunInfo, RunStart
from edsim.live.messages import run_end_json, run_start_json
from edsim.live.topics import PATIENT_EVENTS, RESOURCE_EVENTS, RUNS
from edsim.store.bronze import LOG_APPEND_TIME, KafkaMessage


def bronze_messages(
    info: RunInfo,
    lines: Sequence[str],
    *,
    warmup: float,
    horizon: float,
    started_ms: int,
) -> list[KafkaMessage]:
    """The messages of a whole publication of ``lines``, as the consumer gets them.

    The ``inicio`` says ``W = warmup`` and ``H = horizon``, at maximum speed and with an empty
    census, and carries the block ``registro`` if ``info.record`` is set: without it, the run is
    not offered as a recording (D2 of task 8.6). Then one message per line, in the order given,
    to ``ed.patient.events`` or, without ``episode_id``, to ``ed.resource.events``; and a
    ``fin`` at the horizon. The ``n``-th message (from 0) has the timestamp and the offset
    ``started_ms + n``: strictly increasing, as ``ultimo_inicio`` and ``ultimo_fin`` of the dbt
    project order them.

    Args:
        info: The run, as in the ``inicio`` of a replay.
        lines: One JSON object per event or record, as in ``eventos.jsonl`` or
            ``registrado.jsonl`` (``record_json``); all of them, the warm-up included.
        warmup: ``W``, in minutes.
        horizon: ``H``, in minutes.
        started_ms: Milliseconds since the epoch of the ``inicio``.

    Returns:
        The ``inicio``, the ``len(lines)`` events and the ``fin``.
    """
    start = RunStart(info, warmup, horizon, MAX_SPEED, 0, 0)
    last = json.loads(lines[-1])["event_id"] if lines else None
    end = RunEnd(info.run_id, REASON_HORIZON, horizon, last, len(lines))
    values = [
        (RUNS, run_start_json(start)),
        *((_topic(line), line) for line in lines),
        (RUNS, run_end_json(end)),
    ]
    return [
        KafkaMessage(topic, 0, started_ms + n, LOG_APPEND_TIME, started_ms + n, value.encode())
        for n, (topic, value) in enumerate(values)
    ]


def _topic(line: str) -> str:
    return RESOURCE_EVENTS if json.loads(line)["episode_id"] is None else PATIENT_EVENTS
