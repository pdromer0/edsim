"""Enteros enormes en las comprobaciones de «número real finito» (revisión del PR #59).

Los enteros de Python no tienen límite, y `json.loads` lee un 1 seguido de 400 ceros como
un `int`. Con él, `float`, `math.isfinite` y `math.isnan` lanzan OverflowError en vez de
responder. Cada comprobación debe rechazarlo con el ValueError y el mensaje de siempre:
el mismo que da con infinito (o con NaN, en el censo, que admite el infinito).
"""

import math

import pytest
from fake_kafka import FakeConsumer
from test_directo import INFO
from test_messages import INVALID_ORDERS

from edsim.engine.events import EventLog, JsonlSink, MemorySink, event_time, read_events
from edsim.engine.scenarios import SCENARIO_START
from edsim.live.census import census, live_events, open_episodes
from edsim.live.clock import FakeClock
from edsim.live.control import SPEED, STOP, Command, NoControl, ScriptedControl, check_speed
from edsim.live.directo import LogSource, MemoryLiveSink, run_live
from edsim.live.kafka import KafkaControl
from edsim.live.messages import control_json
from edsim.live.pacer import Pacer

HUGE = 10**400
DIGITS = "1" + "0" * 400


def emit(t):
    EventLog("r", SCENARIO_START, MemorySink()).emit("patient_arrived", t, arrival_id=1)


def run(start=120, horizon=180):
    run_live(
        LogSource([], 180),
        Pacer(FakeClock(), 60, (0.0, 0.0)),
        NoControl(),
        MemoryLiveSink(),
        start=start,
        horizon=horizon,
        run_info=INFO,
    )


CHECKS = {
    # events._check_sim_time
    "event_time": lambda x: event_time(SCENARIO_START, x),
    "emit": emit,
    # control
    "check_speed": check_speed,
    "command": lambda x: Command(SPEED, x),
    "instante-de-orden": lambda x: ScriptedControl(FakeClock(), [(x, Command(STOP))]),
    # clock
    "sleep": lambda x: FakeClock().sleep(x),
    "reloj-start": lambda x: FakeClock(start=x),
    # directo._check_minutes
    "run_live-start": lambda x: run(start=x),
    "logsource-horizon": lambda x: LogSource([], x),
    # pacer
    "pacer-velocidad": lambda x: Pacer(FakeClock(), x, (0.0, 0.0)),
    "pacer-ancla": lambda x: Pacer(FakeClock(), 60, (x, 0.0)),
    "reanchor": lambda x: Pacer(FakeClock(), 60, (0.0, 0.0)).reanchor(x),
    "wait_until": lambda x: Pacer(FakeClock(), 60, (0.0, 0.0)).wait_until(x, NoControl()),
}


def message(check, value) -> str:
    with pytest.raises(ValueError) as raised:
        check(value)
    return str(raised.value)


@pytest.mark.parametrize("check", CHECKS.values(), ids=CHECKS.keys())
def test_un_entero_enorme_da_el_valueerror_de_siempre(check):
    reference = message(check, math.inf)
    assert message(check, HUGE) == reference.replace("inf", repr(HUGE))


@pytest.mark.parametrize("check", [open_episodes, census, live_events], ids=lambda f: f.__name__)
def test_en_el_censo_tambien(check):
    # El censo admite el infinito (todo es calentamiento) y rechaza NaN.
    reference = message(lambda x: check([], x), math.nan)
    assert message(lambda x: check([], x), HUGE) == reference.replace("nan", repr(HUGE))


def test_read_events_con_un_sim_time_enorme(tmp_path):
    path = tmp_path / "eventos.jsonl"
    with JsonlSink(path) as sink:
        log = EventLog("r", SCENARIO_START, sink)
        log.emit("patient_arrived", 1.0, arrival_id=1)
        log.emit("patient_arrived", 2.0, arrival_id=2)
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace('"sim_time": 2.0', f'"sim_time": {DIGITS}'), encoding="utf-8")

    with pytest.raises(ValueError, match=rf"{path}:2: .*sim_time must be a finite number >= 0"):
        list(read_events(path))


def test_la_orden_con_una_velocidad_enorme_esta_en_las_colecciones():
    # M7 (test_messages.py) y S11 (test_schemas.py) la pasan por parse_control y el esquema.
    [text] = [t for name, t in INVALID_ORDERS if name == "velocidad-10e400"]
    assert DIGITS in text


def kafka_control(values, warnings) -> KafkaControl:
    """Un KafkaControl sin broker: el consumidor falso sustituye al real, que crea __init__."""
    control = object.__new__(KafkaControl)
    control._consumer = FakeConsumer(values)
    control.run_id = "r1"
    control._on_invalid = warnings.append
    return control


def test_kafka_control_avisa_y_sigue():
    text = '{"version": 1, "run_id": "r1", "orden": "velocidad", "valor": ' + DIGITS + "}"
    warnings = []
    control = kafka_control([text.encode(), control_json("r1", Command(STOP)).encode()], warnings)

    assert control.poll() is None
    assert control.poll() == Command(STOP)  # la ejecución sigue
    assert len(warnings) == 1
    assert "speed must be a positive finite number" in warnings[0]
