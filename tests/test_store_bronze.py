"""De un mensaje de Kafka a una fila de bronce (tarea 7.5, H7-7), sin conectar a nada.

Los mensajes se escriben a mano: un evento de la verdad, un registro con un campo vacío, un
`record_corrected`, los dos mensajes de `ed.runs` y todo lo que va a `rechazados`. Las horas
esperadas salen del cálculo del plan (python3 independiente, con aritmética de enteros desde la
época): la marca 1.767.225.600.123 ms es 2026-01-01T00:00:00.123+00:00.
"""

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest

from edsim.store.bronze import (
    LOG_APPEND_TIME,
    MAX_INTEGER,
    EventRow,
    KafkaMessage,
    RejectedRow,
    RunRow,
    TimestampTypeError,
    to_row,
)

STAMP_MS = 1_767_225_600_123
INGEST = datetime(2026, 1, 1, 0, 0, 0, 123_000, tzinfo=UTC)
CET = timezone(timedelta(hours=1))

EVENT = {
    "event_id": "r2026-000000001",
    "event_type": "patient_arrived",
    "schema_version": 4,
    "run_id": "r2026",
    "episode_id": "EP-000001",
    "patient_id": "PT-000001",
    "source_system": "admision",
    "sim_time": 739.02,
    "event_time": "2026-01-05T12:19:01.200+01:00",
    "recorded_time": "2026-01-05T12:19:01.200+01:00",
    "ingest_time": None,
    "payload": {"medio": "propio"},
}


def message(value, *, topic="ed.patient.events", offset=7, kind=LOG_APPEND_TIME, ms=STAMP_MS):
    if isinstance(value, dict):
        value = json.dumps(value, ensure_ascii=False)
    if isinstance(value, str):
        value = value.encode("utf-8")
    return KafkaMessage(topic, 3, offset, kind, ms, value)


def with_(**changes):
    return {**EVENT, **changes}


def test_un_evento_de_la_verdad_da_su_fila_con_la_marca_del_broker():
    value = json.dumps(EVENT, ensure_ascii=False)

    row = to_row(message(value, offset=2**40))

    assert row == EventRow(
        event_id="r2026-000000001",
        event_type="patient_arrived",
        schema_version=4,
        run_id="r2026",
        episode_id="EP-000001",
        patient_id="PT-000001",
        source_system="admision",
        sim_time=739.02,
        event_time=datetime(2026, 1, 5, 12, 19, 1, 200_000, tzinfo=CET),
        recorded_time=datetime(2026, 1, 5, 12, 19, 1, 200_000, tzinfo=CET),
        ingest_time=INGEST,
        payload='{"medio": "propio"}',
        kafka_topic="ed.patient.events",
        kafka_particion=3,
        kafka_offset=2**40,  # cabe en bigint
        valor=value,
    )
    # La misma hora que 11:19:01.200 en UTC (cálculo del plan).
    assert row.event_time == datetime(2026, 1, 5, 11, 19, 1, 200_000, tzinfo=UTC)
    assert row.ingest_time.isoformat() == "2026-01-01T00:00:00.123000+00:00"


def test_el_ingest_time_del_mensaje_se_ignora():
    row = to_row(message(with_(ingest_time="2030-01-01T00:00:00+00:00")))

    assert row.ingest_time == INGEST


def test_un_registro_con_un_campo_vacio_y_una_clave_de_mas_pasa_tal_cual():
    value = with_(payload={"nivel": None, "motivo": "dolor torácico"}, nueva="clave")

    row = to_row(message(value))

    assert isinstance(row, EventRow)
    assert json.loads(row.payload) == {"nivel": None, "motivo": "dolor torácico"}
    assert "dolor torácico" in row.payload  # sin escapar los acentos
    assert json.loads(row.valor)["nueva"] == "clave"  # la clave de más sigue en valor


def test_un_record_corrected_no_se_valida_con_el_catalogo():
    value = with_(
        event_id="r2026_realista_s2026-000000007",
        event_type="record_corrected",
        payload={"corrige": "r2026_realista_s2026-000000004", "campos": {"nivel": 3}},
    )

    row = to_row(message(value))

    assert isinstance(row, EventRow)
    assert row.event_type == "record_corrected"
    assert json.loads(row.payload)["campos"] == {"nivel": 3}


def test_un_evento_de_recursos_sin_episodio_ni_paciente():
    row = to_row(message(with_(episode_id=None, patient_id=None), topic="ed.resource.events"))

    assert isinstance(row, EventRow)
    assert (row.episode_id, row.patient_id) == (None, None)


def test_el_inicio_y_el_fin_de_ed_runs_van_a_ejecuciones():
    start = {"tipo": "inicio", "version": 1, "run_id": "r2026", "registro": {"perfil": "x"}}
    end = {"tipo": "fin", "version": 1, "run_id": "r2026", "publicados": 0}

    rows = [to_row(message(m, topic="ed.runs", offset=i)) for i, m in enumerate([start, end])]

    assert rows == [
        RunRow("r2026", "inicio", json.dumps(start, ensure_ascii=False), INGEST, 0),
        RunRow("r2026", "fin", json.dumps(end, ensure_ascii=False), INGEST, 1),
    ]


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ({"tipo": "pausa", "run_id": "r"}, "tipo inicio o fin"),
        ({"tipo": "inicio", "run_id": ""}, "run_id debe ser"),
        ({"tipo": "fin", "run_id": "r"}, "publicados"),
        ({"tipo": "fin", "run_id": "r", "publicados": True}, "publicados"),
        ({"tipo": "fin", "run_id": "r", "publicados": -1}, "publicados"),
        ({"tipo": "fin", "run_id": "r", "publicados": 2**63}, "publicados"),
        ("[1, 2]", "no es un objeto JSON"),
    ],
)
def test_un_mensaje_de_ed_runs_que_no_se_lee_va_a_rechazados(value, reason):
    row = to_row(message(value, topic="ed.runs"))

    assert isinstance(row, RejectedRow)
    assert reason in row.motivo
    assert row.kafka_topic == "ed.runs"


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        (None, "sin valor"),
        ("", "JSON roto"),
        ('{"event_id": ', "JSON roto"),
        ("[1, 2]", "no es un objeto JSON, sino list"),
        ({k: v for k, v in EVENT.items() if k not in ("sim_time", "payload")}, "faltan sim_time"),
        (with_(event_id=""), "event_id debe ser un texto no vacío"),
        (with_(run_id=7), "run_id debe ser"),
        (with_(episode_id={"a": 1}), "episode_id debe ser un texto o null"),
        (with_(patient_id=["PT"]), "patient_id debe ser"),
        (with_(schema_version=True), "schema_version"),
        (with_(schema_version=MAX_INTEGER + 1), "schema_version"),
        (with_(schema_version=0), "schema_version"),
        (with_(schema_version=4.0), "schema_version"),
        (with_(sim_time=True), "sim_time debe ser un número"),
        (with_(sim_time="739"), "sim_time debe ser un número"),
        (with_(sim_time=10**400), "no cabe en un double"),
        (json.dumps(EVENT).replace("739.02", "NaN"), "NaN no es JSON"),
        (json.dumps(EVENT).replace("739.02", "-Infinity"), "-Infinity no es JSON"),
        (json.dumps(EVENT).replace("739.02", "1e400"), "no es finito"),
        (with_(payload={"x": float("nan")}), "NaN no es JSON"),
        (with_(event_time="2026-01-05T12:19:01.200"), "event_time no lleva zona horaria"),
        (with_(recorded_time="2026-01-05"), "recorded_time no lleva zona horaria"),
        (with_(event_time="ayer"), "no se interpreta como hora"),
        (with_(event_time=1736079541), "debe ser una hora"),
        (with_(payload=[1]), "payload debe ser un objeto"),
        (with_(payload={"x": "a\x00b"}), "NUL"),
        (with_(payload={"a\x00": 1}), "NUL"),
        (with_(event_type="x\x00"), "NUL"),
        (json.dumps(EVENT).replace("propio", "\\ud800"), "sustituto"),
        (b'{"event_id": "\xff"}', "no es UTF-8"),
    ],
)
def test_lo_que_no_se_puede_guardar_va_a_rechazados_con_su_motivo(value, reason):
    row = to_row(message(value, offset=9))

    assert isinstance(row, RejectedRow), row
    assert reason in row.motivo
    assert (row.kafka_topic, row.kafka_particion, row.kafka_offset) == ("ed.patient.events", 3, 9)
    assert row.ingest_time == INGEST
    assert "\x00" not in row.valor


@pytest.mark.parametrize(
    "depth",
    [
        1_100,  # json.loads lo lee; falla el recorrido de _check_strings
        100_000,  # falla ya json.loads
    ],
)
def test_un_json_demasiado_anidado_va_a_rechazados(depth):
    """RecursionError no es ValueError: sin capturarlo, el mensaje tumbaría el consumidor y lo
    volvería a encontrar en cada arranque (profundidades del cálculo del PR, con python3)."""
    value = '{"payload": ' + "[" * depth + "]" * depth + "}"

    row = to_row(message(value, offset=9))

    assert isinstance(row, RejectedRow), row
    assert row.motivo == "JSON demasiado anidado"
    assert row.valor == value


def test_el_valor_rechazado_se_guarda_con_lo_que_text_no_admite_escapado():
    nul = to_row(message(b'\x00{"a"'))
    broken = to_row(message(b'{"a": "\xff"}'))
    empty = to_row(message(None))

    assert nul.valor == '\\x00{"a"'
    assert broken.valor == '{"a": "\\xff"}'
    assert empty.valor == ""


@pytest.mark.parametrize(("kind", "name"), [(1, "CreateTime"), (0, "sin marca")])
def test_una_marca_que_no_es_log_append_time_es_un_error_de_configuracion(kind, name):
    with pytest.raises(TimestampTypeError, match="mal configurado") as caught:
        to_row(message(EVENT, kind=kind))

    assert "edsim directo preparar" in str(caught.value)
    assert f"tipo {kind}" in str(caught.value), name


def test_la_marca_se_comprueba_tambien_en_lo_que_se_rechazaria():
    with pytest.raises(TimestampTypeError):
        to_row(message(None, kind=1))
