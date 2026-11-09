"""Mensajes de ed.runs y ed.control (tarea 6.4).

El inicio y el fin del directo a mano de la 6.3 se comparan con su texto literal, en el
orden de claves de la especificación. Las órdenes se prueban con los mensajes a mano del
prompt; las colecciones de órdenes válidas, ajenas e inválidas son datos del módulo,
porque test_schemas.py pasa las mismas por el esquema ed-control-v1 (control cruzado).
"""

import json

import pytest
from test_directo import run_hand

from edsim.engine.scenarios import SCENARIO_START
from edsim.live.control import MAX_SPEED, PAUSE, RESUME, SPEED, STOP, Command
from edsim.live.directo import RunEnd, RunInfo, RunStart
from edsim.live.messages import control_json, parse_control, run_end_json, run_start_json

# --- ed.runs ---------------------------------------------------------------------------

HAND_START = {
    "tipo": "inicio",
    "version": 1,
    "run_id": "rcenso",
    "modo": "replay",
    "schema_version": 3,
    "semilla": 2026,
    "fecha_inicio": "2026-01-05",
    "inicio_directo": 120.0,
    "horizonte": 180.0,
    "velocidad": 60.0,
    "anclado": False,
    "censo": {"episodios": 2, "eventos": 6},
}
HAND_END = {
    "tipo": "fin",
    "version": 1,
    "run_id": "rcenso",
    "motivo": "horizonte",
    "sim_time": 180.0,
    "ultimo_event_id": "rcenso-000000011",  # la llegada de EP-000004
    "publicados": 9,
}


def test_inicio_y_fin_del_directo_a_mano():
    _, sink = run_hand()

    assert SCENARIO_START.isoformat() == HAND_START["fecha_inicio"]
    # El texto exacto: mismas claves, mismo orden y los minutos escritos como 120.0.
    assert run_start_json(sink.run_start) == json.dumps(HAND_START, ensure_ascii=False)
    assert run_end_json(sink.run_end) == json.dumps(HAND_END, ensure_ascii=False)


def test_inicio_con_velocidad_maxima():
    info = RunInfo("r2026", "directo", 3, 2026, SCENARIO_START, True)
    start = RunStart(info, 3510.0, 4320.0, MAX_SPEED, 113, 520)

    data = json.loads(run_start_json(start))

    assert data["velocidad"] == "max"
    assert data["modo"] == "directo"
    assert data["anclado"] is True


def test_fin_sin_eventos():
    end = RunEnd("r2026", "parar", 2880.0, None, 0)

    assert run_end_json(end) == (
        '{"tipo": "fin", "version": 1, "run_id": "r2026", "motivo": "parar", '
        '"sim_time": 2880.0, "ultimo_event_id": null, "publicados": 0}'
    )


# --- ed.control ------------------------------------------------------------------------

RUN = "r1"

VALID_ORDERS = [
    # Los tres del prompt, a mano.
    ("velocidad-10", '{"version": 1, "run_id": "r1", "orden": "velocidad", "valor": 10}',
     Command(SPEED, 10.0)),
    ("velocidad-max", '{"version": 1, "run_id": "r1", "orden": "velocidad", "valor": "max"}',
     Command(SPEED, MAX_SPEED)),
    ("pausar", '{"version": 1, "run_id": "r1", "orden": "pausar"}', Command(PAUSE)),
]  # fmt: skip
"""Órdenes válidas para r1: (id, texto, la orden que dan)."""

FOREIGN_ORDERS = [
    ("run-id-ajeno", '{"version": 1, "run_id": "r2", "orden": "pausar"}'),
]
"""Órdenes válidas de otra ejecución: parse_control las ignora sin aviso."""

INVALID_ORDERS = [
    # Los del prompt.
    ("valor-0", '{"version": 1, "run_id": "r1", "orden": "velocidad", "valor": 0}'),
    ("valor-rapido", '{"version": 1, "run_id": "r1", "orden": "velocidad", "valor": "rápido"}'),
    ("version-2", '{"version": 2, "run_id": "r1", "orden": "pausar"}'),
    ("orden-acelerar", '{"version": 1, "run_id": "r1", "orden": "acelerar"}'),
    ("pausar-con-valor", '{"version": 1, "run_id": "r1", "orden": "pausar", "valor": 10}'),
    ("json-roto", '{"version": 1, "run_id": "r1", "orden": '),
    # Más.
    ("velocidad-sin-valor", '{"version": 1, "run_id": "r1", "orden": "velocidad"}'),
    ("velocidad-1e400", '{"version": 1, "run_id": "r1", "orden": "velocidad", "valor": 1e400}'),
    ("valor-negativo", '{"version": 1, "run_id": "r1", "orden": "velocidad", "valor": -10}'),
    ("valor-booleano", '{"version": 1, "run_id": "r1", "orden": "velocidad", "valor": true}'),
    ("campo-de-mas", '{"version": 1, "run_id": "r1", "orden": "parar", "motivo": "fin"}'),
    ("sin-version", '{"run_id": "r1", "orden": "parar"}'),
    ("version-texto", '{"version": "1", "run_id": "r1", "orden": "parar"}'),
    ("version-booleana", '{"version": true, "run_id": "r1", "orden": "parar"}'),
    ("orden-no-texto", '{"version": 1, "run_id": "r1", "orden": 3}'),
    ("sin-run-id", '{"version": 1, "orden": "parar"}'),
    ("run-id-vacio", '{"version": 1, "run_id": "", "orden": "parar"}'),
    ("run-id-no-texto", '{"version": 1, "run_id": 1, "orden": "parar"}'),
    ("no-objeto", '["parar"]'),
    ("utf8-roto", b'{"version": 1, "run_id": "r1", "orden": "parar\xff"}'),
]
"""Mensajes inválidos de r1 (o sin dueño claro): parse_control avisa y da None."""


def parse(text):
    warnings = []
    return parse_control(text, RUN, warnings.append), warnings


ROUND_TRIP = {
    "velocidad-10": Command(SPEED, 10),
    "velocidad-max": Command(SPEED, MAX_SPEED),
    "pausar": Command(PAUSE),
    "reanudar": Command(RESUME),
    "parar": Command(STOP),
}


@pytest.mark.parametrize("command", ROUND_TRIP.values(), ids=ROUND_TRIP.keys())
def test_orden_ida_y_vuelta(command):
    text = control_json(RUN, command)

    assert json.loads(text)["version"] == 1
    assert ("valor" in json.loads(text)) == (command.order == SPEED)
    assert parse(text) == (command, [])


def test_orden_a_mano():
    assert control_json(RUN, Command(SPEED, 10)) == (
        '{"version": 1, "run_id": "r1", "orden": "velocidad", "valor": 10.0}'
    )


@pytest.mark.parametrize(
    ("text", "expected"), [c[1:] for c in VALID_ORDERS], ids=[c[0] for c in VALID_ORDERS]
)
def test_orden_valida(text, expected):
    assert parse(text) == (expected, [])
    assert parse(text.encode("utf-8")) == (expected, [])  # el valor de Kafka son bytes


def test_orden_de_otro_run_id_se_ignora_sin_aviso():
    [(_, text)] = FOREIGN_ORDERS
    assert parse(text) == (None, [])
    # Es una orden válida: para r2 sí vale.
    assert parse_control(text, "r2", pytest.fail) == Command(PAUSE)


@pytest.mark.parametrize("text", [c[1] for c in INVALID_ORDERS], ids=[c[0] for c in INVALID_ORDERS])
def test_orden_invalida_avisa(text):
    command, warnings = parse(text)

    assert command is None
    assert len(warnings) == 1
    assert warnings[0].startswith("invalid message in ed.control: ")
