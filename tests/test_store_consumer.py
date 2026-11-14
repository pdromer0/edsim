"""El bucle del consumidor de bronce (tarea 7.5, H7-8) con un Kafka y un Postgres falsos.

Lo que pilla cada test que no pilla ningún otro: el orden guardar y después apuntar (V13), la
caída entre las dos cosas sin pérdida ni repetición, la marca del broker en la fila (V15), el
tipo de marca (V16), la red de seguridad (V21), el fin de `--run` contado en bronce (V18) y
desde la última publicación, y los mensajes que son errores del cliente.

Las cifras de la caída salen del cálculo del plan (una simulación propia del protocolo): 7
mensajes, lotes de 3 y caída al confirmar el lote 2 dan 7 filas, 3 repetidos y ninguno
perdido.
"""

import json
from datetime import UTC, datetime

import pytest
from fake_kafka import CREATE_TIME, ManualClock, install_fake_confluent_kafka
from fake_store import (
    MAX_CONSUMES,
    Crash,
    FakeBroker,
    FakeBronzeConsumer,
    FakeStore,
    RunawayLoop,
)

from edsim.live.kafka import (
    BRONZE_GROUP,
    READ_TOPICS,
    bronze_consumer_config,
    connect_bronze_consumer,
)
from edsim.store.bronze import TimestampTypeError
from edsim.store.consumer import run_consumer

STAMP_MS = 1_767_225_600_123
INGEST = datetime(2026, 1, 1, 0, 0, 0, 123_000, tzinfo=UTC)
PATIENTS = "ed.patient.events"
RUNS = "ed.runs"


def event(number, run_id="r1"):
    return {
        "event_id": f"{run_id}-{number:09d}",
        "event_type": "patient_arrived",
        "schema_version": 4,
        "run_id": run_id,
        "episode_id": f"EP-{number:06d}",
        "patient_id": f"PT-{number:06d}",
        "source_system": "admision",
        "sim_time": float(number),
        "event_time": "2026-01-05T00:00:00.000+01:00",
        "recorded_time": "2026-01-05T00:00:00.000+01:00",
        "ingest_time": None,
        "payload": {},
    }


def publish_run(broker, run_id, numbers, *, stamp_ms, fin=True, published=None):
    """Una publicación: inicio, los eventos y (si `fin`) el fin, con la misma marca."""
    broker.publish(RUNS, {"tipo": "inicio", "run_id": run_id}, stamp_ms=stamp_ms)
    for number in numbers:
        broker.publish(PATIENTS, event(number, run_id), stamp_ms=stamp_ms)
    if fin:
        count = len(numbers) if published is None else published
        broker.publish(
            RUNS, {"tipo": "fin", "run_id": run_id, "publicados": count}, stamp_ms=stamp_ms
        )


def stop_after(batches):
    """Un should_stop que dice que pare tras `batches` llamadas que vuelven False."""
    calls = iter(range(batches + 1))
    return lambda: next(calls, batches) >= batches


def stored_ids(store):
    return sorted(event_id for event_id, _ in store.events)


def test_guarda_el_lote_en_una_transaccion_y_despues_confirma_de_forma_sincrona():
    broker = FakeBroker()
    for number in range(1, 4):
        broker.publish(PATIENTS, event(number), stamp_ms=STAMP_MS)
    log = []
    consumer = FakeBronzeConsumer(broker, log=log)
    store = FakeStore(log=log)

    report = run_consumer(consumer, store, batch_size=3, should_stop=stop_after(1))

    assert log == [
        ("consume", 3),
        "transaction", ("insert_events", 3), ("insert_runs", 0), ("insert_rejected", 0),
        "end transaction",
        ("commit", False),
    ]  # fmt: skip
    assert (report.saved, report.repeated, report.batches) == (3, 0, 1)


def test_la_caida_entre_guardar_y_apuntar_no_pierde_ni_repite_nada():
    broker = FakeBroker()
    for number in range(7):
        broker.publish(PATIENTS, event(number), stamp_ms=STAMP_MS)
    store = FakeStore()

    with pytest.raises(Crash):
        run_consumer(FakeBronzeConsumer(broker, crash_on_commit=2), store, batch_size=3)
    # El lote 2 (mensajes 3 a 5) se guardó, pero su confirmación no llegó.
    assert broker.committed == {(PATIENTS, 0): 3}
    assert len(store.events) == 6

    relaunched = FakeBronzeConsumer(broker)
    report = run_consumer(relaunched, store, batch_size=3, should_stop=stop_after(2))

    assert stored_ids(store) == [f"r1-{n:09d}" for n in range(7)]
    assert (report.messages, report.saved, report.repeated) == (4, 1, 3)
    assert broker.committed == {(PATIENTS, 0): 7}


def test_la_fila_guardada_lleva_la_marca_del_broker_como_ingest_time():
    broker = FakeBroker()
    broker.publish(PATIENTS, event(1), stamp_ms=STAMP_MS)
    store = FakeStore()

    run_consumer(FakeBronzeConsumer(broker), store, should_stop=stop_after(1))

    (row,) = store.events.values()
    assert row.ingest_time == INGEST
    assert row.ingest_time.isoformat() == "2026-01-01T00:00:00.123000+00:00"


def test_una_marca_create_time_para_el_lote_sin_guardar_ni_confirmar():
    broker = FakeBroker()
    broker.publish(PATIENTS, event(1), stamp_ms=STAMP_MS)
    broker.publish(PATIENTS, event(2), stamp_ms=STAMP_MS, kind=CREATE_TIME)
    consumer = FakeBronzeConsumer(broker)
    store = FakeStore()

    with pytest.raises(TimestampTypeError, match="mal configurado"):
        run_consumer(consumer, store, should_stop=stop_after(1))

    assert store.events == {}
    assert consumer.commits == []


def test_la_red_de_seguridad_rechaza_solo_la_fila_que_postgres_no_acepta_y_confirma():
    broker = FakeBroker()
    for number in range(1, 4):
        broker.publish(PATIENTS, event(number), stamp_ms=STAMP_MS)
    consumer = FakeBronzeConsumer(broker)
    store = FakeStore(fail_on="r1-000000002")

    report = run_consumer(consumer, store, should_stop=stop_after(1))

    assert stored_ids(store) == ["r1-000000001", "r1-000000003"]
    (rejected,) = store.rejected.values()
    assert rejected.motivo == "Postgres lo rechaza: dato rechazado en r1-000000002"
    assert json.loads(rejected.valor)["event_id"] == "r1-000000002"
    assert (rejected.kafka_topic, rejected.kafka_offset, rejected.ingest_time) == (
        PATIENTS,
        1,
        INGEST,
    )
    assert (report.saved, report.rejected, report.retried) == (2, 1, 1)
    assert consumer.commits == [False]


def test_un_error_que_no_es_de_datos_se_propaga_sin_confirmar():
    broker = FakeBroker()
    broker.publish(PATIENTS, event(1), stamp_ms=STAMP_MS)
    consumer = FakeBronzeConsumer(broker)
    store = FakeStore()

    def connection_lost(rows):
        raise ConnectionError("se cayó la conexión")

    store.insert_events = connection_lost

    with pytest.raises(ConnectionError):
        run_consumer(consumer, store, should_stop=stop_after(1))
    assert consumer.commits == []


def test_con_run_termina_cuando_bronce_tiene_toda_la_publicacion():
    broker = FakeBroker()
    publish_run(broker, "r1", [1, 2, 3], stamp_ms=STAMP_MS)
    publish_run(broker, "otra", [1, 2], stamp_ms=STAMP_MS)
    store = FakeStore()

    report = run_consumer(FakeBronzeConsumer(broker), store, run_id="r1", timeout=60)

    assert report.complete and not report.timed_out
    assert report.missing == 0
    assert (report.progress.published, report.progress.stored) == (3, 3)


def test_relanzar_con_run_termina_aunque_no_vuelva_a_ver_lo_ya_confirmado():
    broker = FakeBroker()
    publish_run(broker, "r1", list(range(1, 9)), stamp_ms=STAMP_MS)
    store = FakeStore()
    first = run_consumer(FakeBronzeConsumer(broker), store, batch_size=3, should_stop=stop_after(1))
    assert 0 < first.saved < 8  # se paró a mitad

    clock = ManualClock()
    second = run_consumer(
        FakeBronzeConsumer(broker, clock=clock), store, run_id="r1", timeout=60, clock=clock
    )

    assert second.complete and not second.timed_out
    assert second.repeated == 0
    assert len(store.events) == 8


def test_con_run_vence_el_timeout_y_dice_cuantos_faltan():
    broker = FakeBroker()
    publish_run(broker, "r1", [1, 2, 3], stamp_ms=STAMP_MS, published=5)
    clock = ManualClock()

    report = run_consumer(
        FakeBronzeConsumer(broker, clock=clock), FakeStore(), run_id="r1", timeout=10, clock=clock
    )

    assert report.timed_out and not report.complete
    assert report.missing == 2
    assert report.seconds == pytest.approx(10)


def test_con_run_cuenta_desde_la_ultima_publicacion():
    """Una publicación anterior completa de la misma ejecución no da por terminada la nueva."""
    broker = FakeBroker()
    publish_run(broker, "r1", [1, 2, 3], stamp_ms=STAMP_MS)
    publish_run(broker, "r1", [1, 2, 3], stamp_ms=STAMP_MS + 60_000, fin=False)
    clock = ManualClock()

    report = run_consumer(
        FakeBronzeConsumer(broker, clock=clock), FakeStore(), run_id="r1", timeout=5, clock=clock
    )

    # Bronce guarda las dos publicaciones (llegaron en momentos distintos), pero la nueva no
    # tiene su fin.
    assert report.timed_out
    assert report.progress.started and report.progress.published is None
    assert report.progress.stored == 3
    assert report.missing is None


def test_con_run_no_da_por_completa_una_publicacion_vieja_si_kafka_tiene_otra():
    """Bronce tiene completa la publicación 1 y Kafka guarda la 2 sin leer: --run tiene que
    leerla antes de terminar. Solo se da por completa con el consumidor al día (el último
    consume volvió vacío)."""
    broker = FakeBroker()
    store = FakeStore()
    publish_run(broker, "r1", [1, 2, 3], stamp_ms=STAMP_MS)
    first = run_consumer(FakeBronzeConsumer(broker), store, run_id="r1", timeout=5)
    assert first.complete and len(store.events) == 3
    publish_run(broker, "r1", [1, 2, 3], stamp_ms=STAMP_MS + 60_000)  # la publicación 2
    clock = ManualClock()
    consumer = FakeBronzeConsumer(broker, clock=clock)

    report = run_consumer(consumer, store, run_id="r1", timeout=5, clock=clock)

    assert report.complete and not report.timed_out
    # Un consume con la publicación 2 entera (inicio, 3 eventos y fin) y otro vacío.
    assert consumer.consumes == 2
    assert (report.saved, report.repeated) == (5, 0)
    assert len(store.events) == 6  # las dos publicaciones, con su ingest_time cada una
    assert (report.progress.published, report.progress.stored) == (3, 3)
    assert broker.committed == {(PATIENTS, 0): 6, (RUNS, 0): 4}


def test_los_mensajes_que_son_errores_se_apartan_y_un_lote_solo_de_errores_no_confirma():
    broker = FakeBroker()
    broker.publish(PATIENTS, None, kind=0, error="_TRANSPORT")
    seen = []
    consumer = FakeBronzeConsumer(broker)
    store = FakeStore()

    report = run_consumer(consumer, store, should_stop=stop_after(1), on_error=seen.append)

    assert seen == ["_TRANSPORT"]
    assert (report.errors, report.messages, report.batches) == (1, 0, 0)
    assert consumer.commits == []
    assert store.rejected == {}


def test_un_lote_vacio_no_guarda_ni_confirma():
    log = []
    consumer = FakeBronzeConsumer(FakeBroker(), log=log)

    run_consumer(consumer, FakeStore(log=log), should_stop=stop_after(2))

    assert log == [("consume", 0), ("consume", 0)]


def test_lo_ilegible_va_a_rechazados_en_la_misma_transaccion_y_se_confirma():
    broker = FakeBroker()
    broker.publish(PATIENTS, b"{roto", stamp_ms=STAMP_MS)
    consumer = FakeBronzeConsumer(broker)
    store = FakeStore()

    report = run_consumer(consumer, store, should_stop=stop_after(1))

    (rejected,) = store.rejected.values()
    assert rejected.motivo.startswith("JSON roto")
    assert (report.rejected, report.retried) == (1, 0)
    assert consumer.commits == [False]


def test_on_progress_se_llama_cada_diez_segundos():
    clock = ManualClock()
    calls = []

    run_consumer(
        FakeBronzeConsumer(FakeBroker(), clock=clock),
        FakeStore(),
        should_stop=lambda: clock.now >= 35,
        on_progress=lambda report: calls.append(report.seconds),
        clock=clock,
    )

    assert calls == [10.0, 20.0, 30.0]


def test_parar_con_run_dice_cuantos_faltan():
    broker = FakeBroker()
    publish_run(broker, "r1", [1, 2, 3, 4], stamp_ms=STAMP_MS)

    report = run_consumer(
        FakeBronzeConsumer(broker),
        FakeStore(),
        run_id="r1",
        batch_size=2,
        should_stop=stop_after(1),
    )

    # El broker falso sirve las particiones por nombre: el primer lote son dos eventos de
    # ed.patient.events, antes del inicio y del fin de ed.runs.
    assert report.stopped and not report.complete
    assert report.saved == 2
    assert report.progress.started is False
    assert report.missing is None  # sin el fin, no se sabe cuántos faltan


def test_un_bucle_que_no_para_falla_en_lugar_de_girar_sin_fin():
    """El doble corta un bucle sin parada: sin él, una versión incorrecta que la quita (V16 en
    la CLI) dejaba el test girando y llenando la memoria."""
    consumer = FakeBronzeConsumer(FakeBroker(), clock=ManualClock())  # sin esperas reales

    with pytest.raises(RunawayLoop):
        run_consumer(consumer, FakeStore())
    assert consumer.consumes == MAX_CONSUMES + 1


def test_la_configuracion_del_consumidor_de_bronce():
    assert bronze_consumer_config("localhost:9092") == {
        "bootstrap.servers": "localhost:9092",
        "group.id": "edsim-bronce",
        "client.id": "edsim-bronce",
        "enable.auto.commit": False,
        "auto.offset.reset": "earliest",
    }
    assert BRONZE_GROUP == "edsim-bronce"


def test_connect_bronze_consumer_se_suscribe_a_los_tres_topics(monkeypatch):
    kafka = install_fake_confluent_kafka(monkeypatch)
    created = []

    class Consumer:
        def __init__(self, config):
            self.config = config
            created.append(self)

        def subscribe(self, topics):
            self.topics = topics

    kafka.Consumer = Consumer

    consumer = connect_bronze_consumer("localhost:9092", group_id="edsim-bronce-test")

    assert created == [consumer]
    assert consumer.config["group.id"] == "edsim-bronce-test"
    assert consumer.topics == list(READ_TOPICS) == ["ed.patient.events", "ed.resource.events", RUNS]
