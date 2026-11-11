"""EDsim contra un Kafka real (tarea 6.4): topics, directo de un día y órdenes.

`ensure_topics` se prueba con nombres únicos. KafkaSink y KafkaControl usan los nombres
reales de la tabla, que no se pueden pasar: cada test usa un `run_id` único y lee desde
los offsets altos anotados antes de publicar, así que no depende de lo que haya dejado
otra ejecución en el broker.
"""

import json
import time
import uuid
from pathlib import Path

import pytest
from confluent_kafka import (
    TIMESTAMP_LOG_APPEND_TIME,
    Consumer,
    KafkaError,
    Producer,
    TopicPartition,
)
from confluent_kafka.admin import ConfigResource, ResourceType
from jsonschema import Draft202012Validator
from kafka_testing import TIMEOUT, deadline

from edsim.arrivals.profile import load_profile
from edsim.engine.center import load_center
from edsim.engine.engine import simulate_ed, start_ed
from edsim.engine.events import MemorySink, to_json
from edsim.live.clock import SystemClock
from edsim.live.control import MAX_SPEED, PAUSE, RESUME, SPEED, STOP, Command, NoControl
from edsim.live.directo import EngineSource, RunInfo, run_live
from edsim.live.kafka import (
    KafkaControl,
    KafkaSink,
    TopicMismatchError,
    connect_producer,
    ensure_topics,
    producer_config,
)
from edsim.live.messages import control_json
from edsim.live.pacer import Pacer
from edsim.live.schemas import event_schema
from edsim.live.topics import (
    CONTROL,
    PATIENT_EVENTS,
    RESOURCE_EVENTS,
    RUNS,
    TOPIC_CONFIG,
    TOPICS,
    Topic,
)
from edsim.profiles.config import load_profiles

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data"


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def describe(admin, names: list[str]) -> dict[str, tuple[int, str, str]]:
    """Particiones, marca de tiempo y política de borrado de cada topic, leídas del broker."""
    metadata = admin.list_topics(timeout=TIMEOUT)
    resources = [ConfigResource(ResourceType.TOPIC, name) for name in names]
    futures = admin.describe_configs(resources, request_timeout=TIMEOUT)
    result = {}
    for name, resource in zip(names, resources, strict=True):
        configs = futures[resource].result(timeout=TIMEOUT)
        result[name] = (
            len(metadata.topics[name].partitions),
            configs["message.timestamp.type"].value,
            configs["cleanup.policy"].value,
        )
    return result


# --- ensure_topics ---------------------------------------------------------------------


def test_ensure_topics_crea_y_no_repite(bootstrap, admin):
    prefix = f"test.{unique('ensure')}"
    topics = [Topic(f"{prefix}.{t.name}", t.partitions, t.key, t.config) for t in TOPICS]
    names = [t.name for t in topics]
    try:
        first = ensure_topics(bootstrap, topics)
        second = ensure_topics(bootstrap, topics)
        described = describe(admin, names)
    finally:
        for future in admin.delete_topics(names, request_timeout=TIMEOUT).values():
            try:
                future.result(timeout=TIMEOUT)
            except Exception as exc:  # un topic que no llegó a crearse no se borra
                if exc.args[0].code() != KafkaError.UNKNOWN_TOPIC_OR_PART:
                    raise

    assert (first.created, first.existing) == (tuple(names), ())
    assert (second.created, second.existing) == ((), tuple(names))
    assert [described[n] for n in names] == [
        (3, "LogAppendTime", "delete"),
        (1, "LogAppendTime", "delete"),
        (1, "LogAppendTime", "delete"),
        (1, "LogAppendTime", "delete"),
    ]


@pytest.mark.parametrize(
    ("partitions", "config", "difference"),
    [
        (2, {}, "2 partitions, expected 3"),
        (3, {"message.timestamp.type": "CreateTime"}, "message.timestamp.type is CreateTime, expected LogAppendTime"),  # noqa: E501
    ],
    ids=["particiones", "marca"],
)  # fmt: skip
def test_ensure_topics_detecta_un_topic_distinto(
    bootstrap, admin, make_topic, request, partitions, config, difference
):
    wrong = make_topic(f"detecta-{request.node.callspec.id}", partitions, config)
    missing = f"test.{unique('no-se-crea')}"

    with pytest.raises(TopicMismatchError, match=f"{wrong}: {difference}"):
        ensure_topics(
            bootstrap,
            [Topic(missing, 1, "test", TOPIC_CONFIG), Topic(wrong, 3, "test", TOPIC_CONFIG)],
        )

    # Comprueba antes de crear nada: el que faltaba sigue sin existir.
    assert missing not in admin.list_topics(timeout=TIMEOUT).topics


# --- Directo de un día -----------------------------------------------------------------


def filtered_batch(batch: list, start: float) -> list:
    """La fórmula de la pieza 7, como en tests/test_directo.py: sim_time >= W, sin
    episodio, o episodio abierto en W (llegó antes de W y no salió antes de W). Con la
    versión 4, también se sale yéndose sin ser visto (patient_left_wbs, tarea 5.4)."""
    before = [e for e in batch if e.sim_time < start]
    departed = {
        e.episode_id for e in before if e.event_type in ("patient_departed", "patient_left_wbs")
    }
    still_open = {e.episode_id for e in before if e.episode_id is not None} - departed
    return [
        e
        for e in batch
        if e.sim_time >= start or e.episode_id is None or e.episode_id in still_open
    ]


def watermarks(consumer: Consumer) -> dict[tuple[str, int], int]:
    """El offset alto de cada partición de los cuatro topics."""
    metadata = consumer.list_topics(timeout=TIMEOUT)
    marks = {}
    for topic in TOPICS:
        for partition in metadata.topics[topic.name].partitions:
            _, high = consumer.get_watermark_offsets(
                TopicPartition(topic.name, partition), timeout=TIMEOUT, cached=False
            )
            marks[topic.name, partition] = high
    return marks


def read_range(consumer: Consumer, start: dict, end: dict) -> list:
    """Todos los mensajes entre los offsets de `start` y los de `end`, de cada partición."""
    consumer.assign([TopicPartition(t, p, offset) for (t, p), offset in start.items()])
    position = dict(start)
    messages, errors = [], []
    limit = deadline()
    while any(position[k] < end[k] for k in end) and time.monotonic() < limit:
        message = consumer.poll(1.0)
        if message is None:
            continue
        if message.error():
            errors.append(message.error())
            continue
        messages.append(message)
        position[message.topic(), message.partition()] = message.offset() + 1
    missing = {k: end[k] - position[k] for k in end if position[k] < end[k]}
    assert not missing, f"Faltan mensajes en {TIMEOUT:.0f} s: {missing} (errores: {errors})"
    return messages


def number(event_id: str) -> int:
    return int(event_id.rsplit("-", 1)[1])


def test_directo_de_un_dia_en_kafka(bootstrap, edsim_topics):
    run_id = unique("test")
    center = load_center(DATA / "centro_sala_ejemplo.toml")
    profile = load_profile(DATA / "llegadas_ejemplo.toml")
    profiles = load_profiles(DATA / "perfiles_ejemplo.toml")
    start, horizon = 1440, 2880
    batch = MemorySink()
    simulate_ed(
        center, profile, 2, 2026, sink=batch, run_id=run_id, profiles=profiles, warmup_days=1
    )  # noqa: E501
    expected = filtered_batch(batch.events, start)

    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": unique("test-directo"),
            "enable.auto.commit": False,
        }  # noqa: E501
    )
    try:
        before = watermarks(consumer)
        buffer = MemorySink()
        ed = start_ed(
            center, profile, 2, 2026, sink=buffer, run_id=run_id, profiles=profiles, warmup_days=1
        )  # noqa: E501
        info = RunInfo(run_id, "directo", 3, 2026, profile.start_date, False)
        with KafkaSink(connect_producer(bootstrap, run_id), run_id) as sink:
            end = run_live(
                EngineSource(ed, buffer),
                Pacer(SystemClock(), MAX_SPEED, (0.0, 0.0)),
                NoControl(),
                sink,
                start=start,
                horizon=horizon,
                run_info=info,
            )
        after = watermarks(consumer)
        messages = read_range(consumer, before, after)
    finally:
        consumer.close()

    ours = [m for m in messages if m.topic() in (PATIENT_EVENTS, RESOURCE_EVENTS)
            and json.loads(m.value())["run_id"] == run_id]  # fmt: skip
    runs = [m for m in messages if m.topic() == RUNS and m.key() == run_id.encode()]
    orders = [m for m in messages if m.topic() == CONTROL and m.key() == run_id.encode()]
    ids = [json.loads(m.value())["event_id"] for m in ours]

    # Lo leído, ordenado por el número de event_id, es el batch filtrado byte a byte.
    by_number = sorted(ours, key=lambda m: number(json.loads(m.value())["event_id"]))
    assert [m.value() for m in by_number] == [to_json(e).encode("utf-8") for e in expected]
    assert len(set(ids)) == len(ids) == len(expected)  # ni falta ni se repite ninguno
    # Dentro de cada partición, en orden de emisión (y así cada episodio en su orden).
    partitions = {}
    for message, event_id in zip(ours, ids, strict=True):
        partitions.setdefault((message.topic(), message.partition()), []).append(number(event_id))
    assert all(numbers == sorted(numbers) for numbers in partitions.values())
    assert len(partitions) == 4  # las 3 de pacientes y la de recursos
    # Clave, cabeceras y marca de cada mensaje.
    schema = Draft202012Validator(event_schema(3))
    for message in ours:
        event = json.loads(message.value())
        key = event["episode_id"] or event["payload"].get("recurso")
        assert message.key() == key.encode()
        assert message.headers() == [
            ("event_type", event["event_type"].encode()),
            ("schema_version", b"3"),
        ]
        assert schema.is_valid(event)
    assert all(m.timestamp()[0] == TIMESTAMP_LOG_APPEND_TIME for m in ours + runs)

    # ed.runs: el inicio y el fin de este run_id, y nada en ed.control.
    runs_schema = Draft202012Validator(
        json.loads((ROOT / "schemas" / "ed-runs-v1.schema.json").read_text())
    )  # noqa: E501
    start_message, end_message = [json.loads(m.value()) for m in runs]
    assert all(runs_schema.is_valid(json.loads(m.value())) for m in runs)
    assert (start_message["tipo"], start_message["inicio_directo"]) == ("inicio", 1440.0)
    census = start_message["censo"]["eventos"]
    assert 0 < census < sum(e.sim_time < start for e in batch.events)  # guarda: hay censo
    assert end_message == {
        "tipo": "fin",
        "version": 1,
        "run_id": run_id,
        "motivo": "horizonte",
        "sim_time": 2880.0,
        "ultimo_event_id": expected[-1].event_id,
        "publicados": len(ours),
    }
    assert end.published == len(ours)
    assert orders == []


# --- Órdenes ---------------------------------------------------------------------------


class Orders:
    """Publica órdenes en ed.control con el productor de EDsim, una a una."""

    def __init__(self, bootstrap: str) -> None:
        self.producer = Producer(producer_config(bootstrap, unique("test-ordenes")))

    def send(self, run_id: str, value: str) -> int:
        """Publica y espera la confirmación; devuelve el offset."""
        reports = []
        self.producer.produce(
            CONTROL,
            key=run_id.encode(),
            value=value.encode(),
            on_delivery=lambda e, m: reports.append((e, m)),  # noqa: E501
        )
        assert self.producer.flush(TIMEOUT) == 0, "La orden no se entregó en 30 s"
        [(error, message)] = reports
        assert error is None, error
        return message.offset()


def first_order(control: KafkaControl) -> Command:
    """La primera orden que da poll(), con un límite de TIMEOUT."""
    limit = deadline()
    while time.monotonic() < limit:
        command = control.poll()
        if command is not None:
            return command
        time.sleep(0.05)
    pytest.fail(f"KafkaControl no dio ninguna orden en {TIMEOUT:.0f} s")


def test_control_solo_lee_lo_publicado_despues(bootstrap, edsim_topics):
    run_id = unique("test")
    orders = Orders(bootstrap)
    old = orders.send(run_id, control_json(run_id, Command(SPEED, 10)))
    warnings = []
    control = KafkaControl(bootstrap, run_id, warnings.append)
    try:
        assert control.start_offset > old
        orders.send(run_id, control_json(run_id, Command(PAUSE)))
        # La de antes iría primero en la partición: si se leyera, saldría ella.
        assert first_order(control) == Command(PAUSE)
    finally:
        control.close()
    assert warnings == []


def test_control_ignora_otro_run_id(bootstrap, edsim_topics):
    run_id, other = unique("test"), unique("test-otro")
    orders = Orders(bootstrap)
    warnings = []
    control = KafkaControl(bootstrap, run_id, warnings.append)
    try:
        orders.send(other, control_json(other, Command(STOP)))
        orders.send(run_id, control_json(run_id, Command(RESUME)))
        assert first_order(control) == Command(RESUME)
    finally:
        control.close()
    assert warnings == []


def test_control_avisa_de_una_orden_invalida(bootstrap, edsim_topics):
    run_id = unique("test")
    orders = Orders(bootstrap)
    warnings = []
    control = KafkaControl(bootstrap, run_id, warnings.append)
    try:
        orders.send(run_id, json.dumps({"version": 1, "run_id": run_id, "orden": "acelerar"}))
        orders.send(run_id, control_json(run_id, Command(STOP)))
        assert first_order(control) == Command(STOP)
    finally:
        control.close()
    assert len(warnings) == 1
    assert "acelerar" in warnings[0]
