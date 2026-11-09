"""KafkaSink y la configuración del productor, sin broker (tarea 6.4, pieza 7).

Con FakeProducer (tests/fake_kafka.py) se ve cada mensaje: topic, clave, valor y
cabeceras; y se programan un BufferError, un aviso de entrega con error, entregas
desordenadas y un flush que no vacía la cola. Estos tests no necesitan el extra kafka.
"""

import json
from types import MappingProxyType

import pytest
from fake_kafka import FakeProducer
from test_directo import INFO, live_hand_log

from edsim.engine import events as events_module
from edsim.engine.events import CATALOG_V3, CATALOGS, EventLog, EventSpec, MemorySink, to_json
from edsim.engine.scenarios import SCENARIO_START
from edsim.live.clock import FakeClock
from edsim.live.control import NoControl
from edsim.live.directo import LogSource, RunEnd, RunInfo, RunStart, SinkError, run_live
from edsim.live.kafka import FLUSH_TIMEOUT, KafkaSink, producer_config
from edsim.live.messages import run_end_json, run_start_json
from edsim.live.pacer import Pacer

RUN = "r2026"


def events(n: int, run_id: str = RUN) -> list:
    """n llegadas de pacientes distintos, un minuto entre cada una."""
    sink = MemorySink()
    log = EventLog(run_id, SCENARIO_START, sink, schema_version=3)
    for i in range(n):
        log.emit("patient_arrived", float(i), arrival_id=i, medio="ambulancia")
    return sink.events


def values(producer) -> list[bytes]:
    return [message.value for message, _ in producer.delivered]


def test_configuracion_del_productor():
    assert producer_config("localhost:9092", "r2026_20261106T172300") == {
        "bootstrap.servers": "localhost:9092",
        "enable.idempotence": True,
        "acks": "all",
        "partitioner": "murmur2_random",
        "client.id": "edsim-r2026_20261106T172300",
    }


def test_eventos_a_mano():
    sink_log = MemorySink()
    log = EventLog(RUN, SCENARIO_START, sink_log, schema_version=3)
    staffing = log.emit("staffing_changed", 0.0, recurso="medicos", anterior=0, nueva=7)
    triage = log.emit("triage_completed", 10.0, arrival_id=137, nivel=3, motivo="disnea")
    producer = FakeProducer()

    with KafkaSink(producer, RUN) as sink:
        sink.write(staffing)
        sink.write(triage)

    [(topic1, call1), (topic2, call2)] = producer.calls
    # Sin timestamp: la marca la pone el broker (LogAppendTime).
    assert set(call1) == set(call2) == {"key", "value", "headers"}
    assert (topic1, call1["key"]) == ("ed.resource.events", b"medicos")
    assert call1["headers"] == [("event_type", b"staffing_changed"), ("schema_version", b"3")]
    assert call1["value"] == to_json(staffing).encode("utf-8")
    assert (topic2, call2["key"]) == ("ed.patient.events", b"EP-000137")
    assert call2["headers"] == [("event_type", b"triage_completed"), ("schema_version", b"3")]
    assert call2["value"] == to_json(triage).encode("utf-8")
    # poll(0) tras cada produce, y flush(30) al salir.
    assert producer.polls == [0, 0]
    assert producer.flushes == [FLUSH_TIMEOUT]
    assert sink.delivered == 2


def test_inicio_y_fin_en_ed_runs():
    # Una ejecución sin eventos: el fin con 0 publicados coincide con lo confirmado.
    start = RunStart(INFO, 120.0, 180.0, 60.0, 0, 0)
    end = RunEnd("rcenso", "horizonte", 180.0, None, 0)
    producer = FakeProducer()

    with KafkaSink(producer, "rcenso") as sink:
        sink.start(start)
        sink.end(end)

    assert producer.calls == [
        ("ed.runs", {"key": b"rcenso", "value": run_start_json(start).encode("utf-8")}),
        ("ed.runs", {"key": b"rcenso", "value": run_end_json(end).encode("utf-8")}),
    ]
    assert sink.delivered == 0  # cuenta solo eventos


def test_reparto_con_un_catalogo_que_aun_no_existe(monkeypatch):
    # Una versión 99 de prueba: la 3 más un evento de recurso sin episodio y sin recurso. Se
    # cambia CATALOGS solo durante el test (monkeypatch); el paquete no cambia.
    catalog = {**CATALOG_V3, "ventilador_revisado": EventSpec("rrhh", False, MappingProxyType({}))}
    monkeypatch.setattr(events_module, "CATALOGS", MappingProxyType({**CATALOGS, 99: catalog}))
    monkeypatch.setattr(events_module, "SCHEMA_VERSIONS", frozenset({*CATALOGS, 99}))
    sink_log = MemorySink()
    event = EventLog(RUN, SCENARIO_START, sink_log, schema_version=99).emit(
        "ventilador_revisado", 5.0
    )
    producer = FakeProducer()

    with KafkaSink(producer, RUN) as sink:
        sink.write(event)

    [(topic, call)] = producer.calls
    assert topic == "ed.resource.events"
    assert call["key"] is None
    assert call["headers"] == [("event_type", b"ventilador_revisado"), ("schema_version", b"99")]
    assert call["value"] == to_json(event).encode("utf-8")


def test_buffer_error_reintenta_sin_perder():
    five = events(5)
    producer = FakeProducer(buffer_errors={3})

    with KafkaSink(producer, RUN) as sink:
        for event in five:
            sink.write(event)

    assert len(producer.calls) == 6  # la tercera llamada lanzó BufferError
    assert values(producer) == [to_json(e).encode("utf-8") for e in five]  # una vez, en orden
    assert [error for _, error in producer.delivered] == [None] * 5
    assert 0.1 in producer.polls
    assert sink.delivered == 5


def test_aviso_de_entrega_con_error():
    four = events(4)
    producer = FakeProducer(delivery_errors={3})
    sink = KafkaSink(producer, RUN)
    for event in four[:3]:
        sink.write(event)

    with pytest.raises(SinkError) as raised:
        sink.write(four[3])

    error = raised.value
    assert (error.delivered, error.failed) == (2, (four[2].event_id,))
    assert error.last_delivered == four[1].event_id
    assert len(producer.calls) == 3  # el cuarto no se envía
    with pytest.raises(SinkError):  # y ninguno después
        sink.write(four[3])
    # El fin se publica aunque el sumidero haya fallado.
    sink.end(RunEnd(RUN, "error", 2.0, error.last_delivered, error.delivered))
    assert producer.calls[-1][0] == "ed.runs"


def test_confirmaciones_desordenadas():
    # Las particiones confirman por separado: el aviso del evento 2 llega antes que el del 1.
    four = events(4)
    producer = FakeProducer(deliver_on_poll=False, delivery_errors={3})
    sink = KafkaSink(producer, RUN)
    for event in four[:3]:
        sink.write(event)

    producer.release(2)
    producer.release(1)
    assert sink.last_delivered == four[1].event_id  # el de mayor número, no el último aviso
    producer.release(3)
    with pytest.raises(SinkError) as raised:
        sink.write(four[3])

    assert (raised.value.delivered, raised.value.last_delivered) == (2, four[1].event_id)


def test_run_live_con_kafka_que_falla():
    # Mensajes aceptados: 1 inicio, 2 y 3 los dos staffing_changed, 4 el tercer evento del
    # censo, que falla. El cuarto write lanza SinkError en pleno censo (minuto W = 120).
    clock = FakeClock()
    producer = FakeProducer(delivery_errors={4})

    with pytest.raises(SinkError), KafkaSink(producer, "rcenso") as sink:
        run_live(
            LogSource(live_hand_log(), 180),
            Pacer(clock, 60, (0.0, 0.0)),
            NoControl(),
            sink,
            start=120,
            horizon=180,
            run_info=INFO,
        )

    topic, last = producer.calls[-1]
    assert topic == "ed.runs"
    assert json.loads(last["value"]) == {
        "tipo": "fin",
        "version": 1,
        "run_id": "rcenso",
        "motivo": "error",
        "sim_time": 120.0,
        "ultimo_event_id": "rcenso-000000001",
        "publicados": 2,
    }


def test_flush_al_salir():
    five = events(5)
    producer = FakeProducer(deliver_on_poll=False)

    with KafkaSink(producer, RUN) as sink:
        for event in five:
            sink.write(event)
        assert len(producer) == 5  # todos pendientes dentro del with

    assert len(producer) == 0
    assert values(producer) == [to_json(e).encode("utf-8") for e in five]
    assert sink.delivered == 5


def test_flush_que_no_vacia_da_error():
    producer = FakeProducer(deliver_on_poll=False, stuck=2)

    with pytest.raises(SinkError, match="2 messages still pending") as raised:
        with KafkaSink(producer, RUN) as sink:
            for event in events(5):
                sink.write(event)

    assert (raised.value.pending, raised.value.delivered) == (2, 3)


def test_error_de_entrega_durante_el_flush():
    three = events(3)
    producer = FakeProducer(deliver_on_poll=False, delivery_errors={2})

    with pytest.raises(SinkError, match="1 more messages not delivered") as raised:
        with KafkaSink(producer, RUN) as sink:
            for event in three:
                sink.write(event)

    assert raised.value.failed == (three[1].event_id,)


def test_salir_con_una_excepcion_no_la_tapa():
    producer = FakeProducer(deliver_on_poll=False, stuck=1)

    with pytest.raises(RuntimeError, match="boom") as raised:
        with KafkaSink(producer, RUN) as sink:
            sink.write(events(1)[0])
            raise RuntimeError("boom")

    assert raised.value.__notes__ == ["KafkaSink: 1 messages still pending after flush(30)"]


def test_run_id_ajeno():
    producer = FakeProducer()
    sink = KafkaSink(producer, RUN)

    with pytest.raises(ValueError, match="r2027"):
        sink.write(events(1, run_id="r2027")[0])
    with pytest.raises(ValueError, match="rcenso"):
        sink.start(RunStart(INFO, 120.0, 180.0, 60.0, 2, 6))
    with pytest.raises(ValueError, match="rcenso"):
        sink.end(RunEnd("rcenso", "horizonte", 180.0, None, 0))
    with pytest.raises(ValueError, match="run_id"):
        KafkaSink(producer, "")
    assert producer.calls == []


# --- El fin espera las confirmaciones (revisión del PR #59) ----------------------------


def one_event_log():
    sink = MemorySink()
    EventLog("runo", SCENARIO_START, sink, schema_version=3).emit(
        "patient_arrived", 1.0, arrival_id=1, medio="ambulancia"
    )
    return sink.events


ONE_INFO = RunInfo("runo", "replay", 3, 2026, SCENARIO_START, False)


def run_kafka(producer, events, *, run_id, info, start, horizon, clock=None):
    """run_live con un KafkaSink sobre `producer`, a ×60 desde 0 s; devuelve el sink."""
    clock = FakeClock() if clock is None else clock
    sink = KafkaSink(producer, run_id)
    with sink:
        run_live(
            LogSource(events, horizon),
            Pacer(clock, 60, (0.0, 0.0)),
            NoControl(),
            sink,
            start=start,
            horizon=horizon,
            run_info=info,
        )
    return sink


def last_end(producer) -> dict:
    topic, call = producer.calls[-1]
    assert topic == "ed.runs"
    return json.loads(call["value"])


def test_un_fallo_tras_el_ultimo_write_da_fin_con_error():
    # El caso de Codex: el único evento falla, pero su aviso llega después de su write, en
    # el flush. Ningún write más lo vería; el fin no puede decir «horizonte, 1 publicado».
    producer = FakeProducer(deliver_on_poll=False, delivery_errors={2})

    with pytest.raises(SinkError) as raised:
        run_kafka(producer, one_event_log(), run_id="runo", info=ONE_INFO, start=0, horizon=4)

    assert last_end(producer) == {
        "tipo": "fin",
        "version": 1,
        "run_id": "runo",
        "motivo": "error",
        "sim_time": 4.0,
        "ultimo_event_id": None,
        "publicados": 0,
    }
    assert raised.value.failed == ("runo-000000000",)
    assert raised.value.delivered == 0


def test_sin_errores_el_fin_espera_al_flush():
    # Ninguna confirmación llega antes del fin: end hace flush y después publica el fin,
    # horizonte, con los 9 confirmados.
    producer = FakeProducer(deliver_on_poll=False)

    run_kafka(producer, live_hand_log(), run_id="rcenso", info=INFO, start=120, horizon=180)

    # El flush de end, el fin y el flush del __exit__.
    assert producer.ops[-3:] == [("flush",), ("produce", "ed.runs"), ("flush",)]
    end = last_end(producer)
    assert (end["motivo"], end["publicados"]) == ("horizonte", 9)
    assert end["ultimo_event_id"] == "rcenso-000000011"


def test_ctrl_c_con_un_fallo_pendiente_da_fin_con_error():
    # Ctrl+C a los 45 s (minuto 165): se publicaron el censo y dos salidas. La segunda
    # salida (mensaje 9) falla, pero su aviso solo llega en el flush del fin: el fin dice
    # error, y sale el SinkError, con la interrupción como contexto.
    producer = FakeProducer(deliver_on_poll=False, delivery_errors={9})

    with pytest.raises(SinkError) as raised:
        run_kafka(
            producer,
            live_hand_log(),
            run_id="rcenso",
            info=INFO,
            start=120,
            horizon=180,
            clock=FakeClock(interrupt_at=45),
        )

    end = last_end(producer)
    assert (end["motivo"], end["publicados"], end["sim_time"]) == ("error", 7, 165.0)
    assert end["ultimo_event_id"] == "rcenso-000000009"
    assert isinstance(raised.value.__context__, KeyboardInterrupt)


def test_el_fin_de_error_lleva_lo_confirmado_tras_el_flush():
    # Mensajes: 1 inicio, 2 y 3 los staffing_changed, retenidos hasta el flush; 4 el tercer
    # evento, que falla en su poll. El cuarto write lanza SinkError con 0 confirmados, y el
    # flush del fin confirma los dos retenidos: el fin dice 2.
    producer = FakeProducer(hold={2, 3}, delivery_errors={4})

    with pytest.raises(SinkError) as raised:
        run_kafka(producer, live_hand_log(), run_id="rcenso", info=INFO, start=120, horizon=180)

    assert (raised.value.delivered, raised.value.last_delivered) == (0, None)
    end = last_end(producer)
    assert (end["motivo"], end["publicados"]) == ("error", 2)
    assert end["ultimo_event_id"] == "rcenso-000000001"
