"""La lectura de un directo en Kafka (tarea 6.6): read_run con un consumidor falso.

Con el módulo confluent_kafka falso de tests/fake_kafka.py, sin broker ni el extra: los
mensajes del directo del log a mano (test_tracker.py) se leen como los daría Kafka, con su
topic, partición, offset y marca. Se prueba que la lectura espera a los publicados aunque
el fin llegue antes, que termina por tiempo límite si falta alguno y lo dice, que filtra por
el run_id del valor y no por la clave, y la configuración del grupo.
"""

import json
from collections import Counter

import pytest
from fake_kafka import (
    CREATE_TIME,
    LOG_APPEND_TIME,
    FakeKafkaException,
    FakeRecord,
    ManualClock,
    ScriptedReader,
    install_fake_confluent_kafka,
)
from test_tracker import hand_run, occupancy_log

from edsim.engine.events import Event, to_json
from edsim.live.directo import RunStart
from edsim.live.kafka import READ_TOPICS, read_run, reader_group_id
from edsim.live.messages import run_end_json, run_start_json
from edsim.live.topics import RUNS, route
from edsim.live.tracker import LiveTracker

RUN = "rocupa"


def records(items, *, broker_ms: int = 1_000_000) -> list[FakeRecord]:
    """Los mensajes de Kafka de un directo: el inicio y el fin en ed.runs con el run_id de
    clave; cada evento en su topic, con su clave y en la partición número de episodio
    módulo 3. Las marcas avanzan 10 ms por mensaje."""
    offsets: Counter = Counter()
    out = []
    for i, item in enumerate(items):
        if isinstance(item, Event):
            topic, key = route(item)
            partition = 0 if item.episode_id is None else int(item.episode_id[3:]) % 3
            value = to_json(item)
        else:
            topic, key, partition = RUNS, RUN.encode(), 0
            value = run_start_json(item) if isinstance(item, RunStart) else run_end_json(item)
        offset = offsets[topic, partition]
        offsets[topic, partition] += 1
        out.append(
            FakeRecord(
                topic, partition, offset, key, value.encode(), (LOG_APPEND_TIME, broker_ms + 10 * i)
            )
        )
    return out


class Reading:
    """Una lectura con el consumidor falso: guarda el lector y la configuración."""

    def __init__(self, monkeypatch, recs) -> None:
        self.kafka = install_fake_confluent_kafka(monkeypatch)
        self.clock = ManualClock()
        self.readers: list[ScriptedReader] = []
        self.recs = recs

        def consumer(config):
            reader = ScriptedReader(config, self.recs, self.clock)
            self.readers.append(reader)
            return reader

        self.kafka.Consumer = consumer

    def run(self, **kwargs):
        tracker = LiveTracker()
        wall = iter(1000.0 + 0.01 * i for i in range(10_000))
        report = read_run(
            "localhost:9092", RUN, tracker, clock=self.clock, wall=lambda: next(wall), **kwargs
        )
        return tracker, report


def test_lee_hasta_el_fin_y_los_publicados(monkeypatch):
    # El fin llega antes que los dos últimos eventos (va en otro topic): se siguen leyendo.
    start, *events, end = hand_run().items
    reading = Reading(monkeypatch, records([start, *events[:-2], end, *events[-2:]]))

    tracker, report = reading.run()

    assert (tracker.distinct, tracker.complete) == (27, True)
    assert (report.complete, report.timed_out, report.missing) == (True, False, 0)
    assert report.messages == 29


def test_un_evento_que_no_llega_termina_por_tiempo_limite(monkeypatch):
    start, *events, end = hand_run().items
    reading = Reading(monkeypatch, records([start, *events[:-2], end, events[-2]]))

    tracker, report = reading.run(timeout=30)

    assert (report.complete, report.timed_out, report.missing) == (False, True, 1)
    assert report.seconds == pytest.approx(30)
    assert tracker.distinct == 26


def test_filtra_por_el_run_id_del_valor_no_por_la_clave(monkeypatch):
    # Los eventos de otra ejecución, con las mismas claves (episode_id), intercalados.
    start, *events, end = hand_run().items
    other = occupancy_log("rotra")
    mixed = [x for pair in zip(events, other, strict=False) for x in pair]
    reading = Reading(monkeypatch, records([start, *mixed, end]))

    tracker, report = reading.run()

    assert report.complete and tracker.distinct == 27
    assert {e.run_id for e in tracker.events} == {RUN}
    assert report.messages == 2 + 27 + 27


def test_configuracion_de_la_lectura(monkeypatch):
    items = hand_run().items
    reading = Reading(monkeypatch, records(items))
    reading.run()
    reading.recs = records(items)
    reading.run()

    first, second = (r.config for r in reading.readers)
    assert first["auto.offset.reset"] == "earliest"
    assert first["group.id"] != second["group.id"]
    assert first["group.id"].startswith(f"edsim-lector-{RUN}-")
    assert first["client.id"] == first["group.id"]
    # La confirmación automática se queda activada (por defecto): con ella, librdkafka
    # confirma también al cerrar, y el retraso queda en 0 aunque falte el commit final
    # (V11 de la 6.6: sin el commit, la integración seguía en 0 por esto).
    assert first.get("enable.auto.commit", True) is True
    assert reading.readers[0].subscribed == list(READ_TOPICS)


def test_el_grupo_por_defecto_es_nuevo_en_cada_lectura():
    assert reader_group_id(RUN) != reader_group_id(RUN)


def test_cada_evento_con_su_particion_offset_y_marca(monkeypatch):
    start, *events, end = hand_run().items
    recs = records([start, *events, end])
    reading = Reading(monkeypatch, recs)

    tracker, _ = reading.run()

    expected = Counter((r.topic_, r.partition_) for r in recs if r.topic_ != RUNS)
    assert dict(tracker.by_partition) == dict(expected)
    # El primer evento: marca 1.000.010 ms (es el segundo mensaje) y recibido en 1000,01 s.
    assert tracker.latencies_ms[0] == pytest.approx(0)
    assert len(tracker.latencies_ms) == 27


def test_un_mensaje_repetido_en_kafka_cuenta_una_vez(monkeypatch):
    start, *events, end = hand_run().items
    recs = records([start, *events, events[5], end])
    reading = Reading(monkeypatch, recs)

    tracker, report = reading.run()

    assert (tracker.duplicates, tracker.distinct, report.complete) == (1, 27, True)


def test_confirma_los_offsets_y_cierra(monkeypatch):
    reading = Reading(monkeypatch, records(hand_run().items))
    reading.run()
    [reader] = reading.readers
    assert reader.commits == [False] and reader.closed


def test_confirmar_sin_nada_leido_no_falla(monkeypatch):
    reading = Reading(monkeypatch, [])

    def nothing(asynchronous=True):
        raise FakeKafkaException("_NO_OFFSET")

    original = reading.kafka.Consumer

    def consumer(config):
        reader = original(config)
        reader.commit = nothing
        return reader

    reading.kafka.Consumer = consumer
    _, report = reading.run(timeout=1)
    assert report.timed_out and report.missing is None and reading.readers[0].closed


def test_una_marca_que_no_es_log_append_time_no_da_latencia(monkeypatch):
    recs = records(hand_run().items)
    for r in recs:
        r.stamp = (CREATE_TIME, r.stamp[1])
    reading = Reading(monkeypatch, recs)

    tracker, report = reading.run()

    assert report.complete and tracker.latencies_ms == []


def test_avisa_del_progreso(monkeypatch):
    start, *events, end = hand_run().items
    reading = Reading(monkeypatch, records([start, *events[:-1]]))
    seen = []

    reading.run(timeout=12, on_progress=lambda t: seen.append(t.distinct), progress_interval=5)

    assert seen == [26, 26]  # a los 5 y a los 10 s, sin el último ni el fin


def test_el_valor_es_el_jsonl():
    # Guarda del doble: el valor es la línea del log, como en KafkaSink.
    [record] = records([occupancy_log()[0]])
    assert json.loads(record.value_)["event_id"] == "rocupa-000000000"
