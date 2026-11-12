"""El consumidor del directo contra un Kafka real (tarea 6.6): read_run y LiveTracker.

Un directo corto con la CLI en un subproceso (tests/data con sala, 2 días, W = 1 día, a
×14.400: el día de directo en 6 s) y, a la vez, el consumidor del paquete en este proceso.
La prueba central: «consumidor = batch», el estado final de cada episodio leído en vivo es
el del batch filtrado con el mismo run_id. Además, el grupo de la lectura existe en el
broker con retraso 0, y una segunda lectura con otro grupo vuelve a leerlo todo.

Límites fijados antes de medir: 60 s por lectura; latencias entre −5 ms (relojes del mismo
núcleo, marca truncada al ms) y 5.000 ms.
"""

import subprocess

import pytest
from confluent_kafka import ConsumerGroupTopicPartitions, TopicPartition
from kafka_testing import TIMEOUT
from test_cli_directo import EDSIM, LAUNCH, LAUNCH_H5, expected_of, finish, new_consumer
from test_kafka_edsim import unique, watermarks

from edsim.live.kafka import READ_TOPICS, read_run
from edsim.live.tracker import LiveTracker, fold_states

READ_LIMIT = 60.0
LATENCY_MIN_MS, LATENCY_MAX_MS = -5.0, 5000.0
SPEED = "14400"


def committed(admin, group_id: str) -> dict[tuple[str, int], int]:
    """Los offsets confirmados del grupo, por partición."""
    futures = admin.list_consumer_group_offsets([ConsumerGroupTopicPartitions(group_id)])
    result = futures[group_id].result(timeout=TIMEOUT)
    return {(tp.topic, tp.partition): tp.offset for tp in result.topic_partitions}


MODELS = {
    # modelo: (argumentos de lanzar, centro, perfiles)
    "hito4": (LAUNCH, "centro_sala_ejemplo.toml", "perfiles_ejemplo.toml"),
    "hito5": (LAUNCH_H5, "centro_h5_ejemplo.toml", "perfiles_h5_ejemplo.toml"),
}
"""El del hito 5 (tarea 5.4) lleva el catálogo 4: abandonos, camas y pasillo por Kafka."""


@pytest.mark.parametrize("model", sorted(MODELS))
def test_consumidor_en_vivo_igual_a_batch(bootstrap, edsim_topics, admin, model):
    launch, center, profiles = MODELS[model]
    run_id = unique("test")
    expected = expected_of(run_id, center, profiles)
    process = subprocess.Popen(
        [EDSIM, *launch, "--velocidad", SPEED, "--run-id", run_id, "--kafka", bootstrap],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    tracker = LiveTracker(run_id)
    try:
        report = read_run(bootstrap, run_id, tracker, timeout=READ_LIMIT)
        code, out, err = finish(process)
    finally:
        if process.poll() is None:
            process.kill()

    assert code == 0, err
    assert report.complete, report
    assert (tracker.duplicates, tracker.missing) == (0, 0)
    assert tracker.distinct == len(expected) == tracker.run_end.published
    assert tracker.states == fold_states(expected)
    assert tracker.episode_order_errors == 0
    if model == "hito5":  # guarda: los abandonos y las camas viajan por Kafka
        kinds = {e.event_type for e in tracker.events}
        assert {"patient_left_wbs", "bed_requested", "bed_assigned"} <= kinds
        assert {e.schema_version for e in tracker.events} == {4}
        assert tracker.occupancy().left > 0

    summary = tracker.latency_summary()
    assert summary.count == tracker.distinct
    assert LATENCY_MIN_MS <= min(tracker.latencies_ms)
    assert summary.max_ms < LATENCY_MAX_MS
    print(
        f"\nlatencias: mediana {summary.median_ms:.1f} ms, p95 {summary.p95_ms:.1f} ms,"
        f" máximo {summary.max_ms:.1f} ms; inversiones {tracker.cross_partition_inversions}"
    )

    # El grupo existe en el broker y su retraso es 0: lo confirmado es el final de cada
    # partición leída.
    groups = admin.list_consumer_groups(request_timeout=TIMEOUT).result(timeout=TIMEOUT)
    assert report.group_id in {g.group_id for g in groups.valid}
    consumer = new_consumer(bootstrap)
    try:
        highs = watermarks(consumer)
    finally:
        consumer.close()
    offsets = committed(admin, report.group_id)
    read = {k: v for k, v in highs.items() if k[0] in READ_TOPICS}
    assert offsets == read

    # Otra lectura, con otro grupo, vuelve a leerlo todo desde el principio.
    again = LiveTracker(run_id)
    second = read_run(bootstrap, run_id, again, timeout=READ_LIMIT)
    assert second.complete and second.group_id != report.group_id
    assert again.distinct == tracker.distinct
    assert again.states == tracker.states


def test_sin_el_directo_la_lectura_dice_lo_que_falta(bootstrap, edsim_topics):
    # Un run_id que nadie publica: vence el límite y no hay fin.
    tracker = LiveTracker("test-nadie")
    report = read_run(bootstrap, "test-nadie", tracker, timeout=3)
    assert (report.complete, report.timed_out, report.missing) == (False, True, None)
    assert report.seconds == pytest.approx(3, abs=1.5)


def test_topic_partition_de_lectura():
    # Guarda: READ_TOPICS son los tres que lee un consumidor del directo.
    assert [TopicPartition(t, 0).topic for t in READ_TOPICS] == [
        "ed.patient.events",
        "ed.resource.events",
        "ed.runs",
    ]
