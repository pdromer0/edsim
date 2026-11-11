"""JSON Schema de los eventos, de ed.runs y de ed.control (tarea 6.4, H6-10).

Tres comprobaciones:

- **Escritos = generados.** Los ficheros de schemas/ son los que genera el código: si
  alguien cambia el catálogo sin regenerar, falla.
- **Los logs validan.** Cada línea de un log de cada versión valida contra su esquema.
- **Dos fuentes comparadas.** Una colección de eventos válidos e inválidos hecha a mano
  pasa por `Event(**datos)` y por el esquema de su versión, y deben decir lo mismo salvo
  las diferencias de `KNOWN_DIFFERENCES`, probadas en los dos sentidos. Lo mismo con las
  órdenes de ed.control: `parse_control` frente a ed-control-v1.

Se valida contra el esquema generado (`event_schema`), no contra el fichero: el fichero
lo ata «escritos = generados».
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from test_directo import run_hand, write_v2_log
from test_events import SAMPLES, SAMPLES_V2, SAMPLES_V4
from test_messages import FOREIGN_ORDERS, INVALID_ORDERS, RUN, VALID_ORDERS

from edsim.arrivals.profile import load_profile
from edsim.engine.center import load_center
from edsim.engine.engine import simulate_ed
from edsim.engine.events import CATALOG_V3, CATALOGS, SCHEMA_VERSIONS, Event, EventLog, MemorySink
from edsim.engine.events import to_json as event_json
from edsim.engine.scenarios import SCENARIO_START
from edsim.live.control import MAX_SPEED, PAUSE, RESUME, SPEED, STOP, Command
from edsim.live.directo import RunEnd, RunInfo, RunStart
from edsim.live.messages import (
    KNOWN_CONTROL_DIFFERENCES,
    control_json,
    parse_control,
    run_end_json,
    run_start_json,
)
from edsim.live.schemas import (
    COMMAND,
    KNOWN_DIFFERENCES,
    MAX_DOUBLE,
    event_schema,
    schema_filename,
    schema_text,
)
from edsim.profiles.config import load_profiles

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
DATA = ROOT / "tests" / "data"
RUNS_SCHEMA = SCHEMAS / "ed-runs-v1.schema.json"
CONTROL_SCHEMA = SCHEMAS / "ed-control-v1.schema.json"
VERSIONS = sorted(SCHEMA_VERSIONS)


def validator(version: int) -> Draft202012Validator:
    return Draft202012Validator(event_schema(version))


def load(path: Path) -> Draft202012Validator:
    return Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))


# --- Escritos = generados --------------------------------------------------------------


@pytest.mark.parametrize("version", VERSIONS)
def test_escritos_iguales_a_los_generados(version):
    # Si falla: uv run python -m edsim.live.schemas, desde la raíz.
    written = (SCHEMAS / schema_filename(version)).read_text(encoding="utf-8")
    assert written == schema_text(version)
    assert COMMAND in json.loads(written)["$comment"]


def test_la_carpeta_schemas_tiene_exactamente_los_seis():
    expected = {schema_filename(v) for v in VERSIONS} | {RUNS_SCHEMA.name, CONTROL_SCHEMA.name}
    assert {p.name for p in SCHEMAS.iterdir()} == expected
    assert len(expected) == 6


@pytest.mark.parametrize("name", sorted(p.name for p in SCHEMAS.glob("*.json")))
def test_cada_esquema_es_2020_12_valido(name):
    schema = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)


def test_cada_comprobacion_describe_su_esquema():
    payload = {t: spec.payload for t, spec in CATALOG_V3.items()}
    episode = {"type": "string", "pattern": "^EP-[0-9]{6}$", "maxLength": 9}

    assert payload["triage_completed"]["nivel"].json_schema() == {
        "type": "integer",
        "minimum": 1,
        "maximum": 5,
    }
    assert payload["box_assigned"]["box"].json_schema() == {"type": "integer", "minimum": 1}
    assert payload["assessment_started"]["tipo"].json_schema() == {
        "enum": ["inicial", "reevaluacion"]
    }
    assert payload["assessment_started"]["pool"].json_schema() == {"enum": ["medicos"]}
    assert payload["assessment_ended"]["interrumpida"].json_schema() == {"type": "boolean"}
    assert payload["patient_displaced"]["desalojado_por"].json_schema() == episode
    assert payload["test_resulted"]["resultados"].json_schema() == {
        "type": "object",
        "minProperties": 1,
        "properties": {
            "analitica": {"enum": ["normal", "alterado"]},
            "radiografia": {"enum": ["normal", "alterado"]},
            "ecg": {"enum": ["normal", "alterado"]},
            "imagen": {"enum": ["normal", "alterado"]},
        },
        "additionalProperties": False,
    }


def test_pruebas_son_las_15_listas_en_orden():
    a, r, e, i = "analitica", "radiografia", "ecg", "imagen"
    expected = [
        [a], [r], [e], [i],
        [a, r], [a, e], [a, i], [r, e], [r, i], [e, i],
        [a, r, e], [a, r, i], [a, e, i], [r, e, i],
        [a, r, e, i],
    ]  # fmt: skip
    assert CATALOG_V3["test_ordered"].payload["pruebas"].json_schema() == {"enum": expected}


def test_el_sobre_de_cada_rama():
    schema = event_schema(3)
    [branch] = [b for b in schema["oneOf"] if b["title"] == "staffing_changed"]
    assert list(schema["oneOf"][i]["title"] for i in range(len(CATALOG_V3))) == list(CATALOG_V3)
    assert branch["required"] == list(Event.__dataclass_fields__)
    assert branch["additionalProperties"] is False
    assert branch["properties"]["episode_id"] == {"type": "null"}
    assert branch["properties"]["ingest_time"] == {"type": "null"}
    assert branch["properties"]["sim_time"] == {
        "type": "number",
        "minimum": 0,
        "maximum": MAX_DOUBLE,
    }
    assert branch["properties"]["payload"]["additionalProperties"] is False


# --- Los logs validan ------------------------------------------------------------------


def log_lines(center: str, clinical: bool) -> list[str]:
    sink = MemorySink()
    simulate_ed(
        load_center(DATA / center),
        load_profile(DATA / "llegadas_ejemplo.toml"),
        3,
        2026,
        sink=sink,
        profiles=load_profiles(DATA / "perfiles_ejemplo.toml") if clinical else None,
    )
    return [event_json(e) for e in sink.events]


def v4_lines() -> list[str]:
    """Un log de la versión 4 con un evento de cada tipo (tarea 5.1)."""
    log = EventLog("r2026", SCENARIO_START, MemorySink(), schema_version=4)
    events = []
    for i, (event_type, payload) in enumerate(SAMPLES_V4.items()):
        kwargs = {"arrival_id": 137} if CATALOGS[4][event_type].patient else {}
        events.append(log.emit(event_type, float(i), **kwargs, **payload))
    return [event_json(e) for e in events]


@pytest.fixture(scope="module")
def logs(tmp_path_factory):
    """Los tres logs de «directo = batch» de la 6.3 (provisional, versión 2 y clínico con
    sala) y uno de la versión 4."""
    v2 = write_v2_log(tmp_path_factory.mktemp("v2") / "eventos.jsonl")
    return {
        1: log_lines("centro_ejemplo.toml", clinical=False),
        2: v2.read_text(encoding="utf-8").splitlines(),
        3: log_lines("centro_sala_ejemplo.toml", clinical=True),
        4: v4_lines(),
    }


@pytest.mark.slow  # unos 7 s por log: jsonschema prueba cada rama del oneOf en cada línea
@pytest.mark.parametrize("version", VERSIONS)
def test_cada_linea_de_cada_log_valida(logs, version):
    check = validator(version)
    lines = logs[version]

    failing = [line for line in lines if not check.is_valid(json.loads(line))]

    assert not failing, failing[:3]
    # Guardas: el log es de esa versión y tiene todos los tipos que el modelo emite.
    types = {json.loads(line)["event_type"] for line in lines}
    assert {json.loads(line)["schema_version"] for line in lines} == {version}
    assert len(types) >= 12
    if version >= 3:
        assert "box_released" in types
    if version == 4:
        assert {"patient_left_wbs", "bed_requested", "bed_assigned"} <= types


# --- Event y el esquema dicen lo mismo -------------------------------------------------

DELETE = object()


def sample(version: int, event_type: str) -> dict:
    """Un evento válido del tipo, como lo lee un consumidor: el resultado de json.loads."""
    if event_type == "box_released":
        payload = {"box": 7, "espera": "resultados"}
    elif version == 4:
        payload = SAMPLES_V4[event_type]
    else:
        payload = (SAMPLES if version == 1 else SAMPLES_V2)[event_type]
    log = EventLog("r2026", SCENARIO_START, MemorySink(), schema_version=version)
    kwargs = {"arrival_id": 137} if CATALOGS[version][event_type].patient else {}
    return json.loads(event_json(log.emit(event_type, 10.0, **kwargs, **payload)))


def changed(version: int, event_type: str, /, **fields) -> dict:
    """La muestra con campos del sobre cambiados (o quitados con DELETE)."""
    data = sample(version, event_type)
    for key, value in fields.items():
        if value is DELETE:
            del data[key]
        else:
            data[key] = value
    return data


def with_payload(version: int, event_type: str, /, **fields) -> dict:
    """La muestra con claves del payload cambiadas (o quitadas con DELETE)."""
    data = sample(version, event_type)
    for key, value in fields.items():
        if value is DELETE:
            del data["payload"][key]
        else:
            data["payload"][key] = value
    return data


VALID = [(f"valido-v{v}-{t}", v, sample(v, t), None) for v in VERSIONS for t in CATALOGS[v]]
"""Cada tipo de cada versión: 13 + 13 + 14 + 17 = 57 eventos válidos."""

INVALID = [
    # Sobre: campos de más y de menos, y no objetos.
    ("sobre-campo-de-mas", 3, changed(3, "triage_completed", origen="x"), None),
    ("sobre-falta-campo", 3, changed(3, "triage_completed", ingest_time=DELETE), None),
    ("no-objeto", 3, [], None),
    ("payload-no-objeto", 3, changed(3, "test_ordered", payload=[]), None),
    # Payload: campos de más y de menos.
    ("payload-campo-de-mas", 3, with_payload(3, "triage_completed", prioridad=1), None),
    ("payload-falta-campo", 3, with_payload(3, "triage_completed", motivo=DELETE), None),
    ("v1-con-payload-de-v2", 1, with_payload(1, "patient_arrived", medio="ambulancia"), None),
    # Tipo de evento y versión.
    ("tipo-desconocido", 3, changed(3, "test_ordered", event_type="patient_teleported"), None),
    ("box-released-en-v2", 2, changed(3, "box_released", schema_version=2), None),
    ("version-desconocida", 3, changed(3, "test_ordered", schema_version=5), None),
    ("left-wbs-en-v3", 3, changed(4, "patient_left_wbs", schema_version=3), None),
    ("traslado-en-v3", 3, with_payload(3, "patient_departed", destino="traslado"), None),
    ("servicio-uci", 4, with_payload(4, "bed_requested", servicio="uci"), None),
    ("espera-desconocida", 4, with_payload(4, "patient_left_wbs", espera="pasillo"), None),
    ("bed-assigned-de-his", 4, changed(4, "bed_assigned", source_system="his"), None),
    ("version-booleana", 1, changed(1, "test_ordered", schema_version=True), None),
    ("version-de-otra-rama", 3, changed(2, "test_ordered"), None),
    ("source-system-cambiado", 3, changed(3, "triage_completed", source_system="his"), None),
    # Tipos cambiados.
    ("nivel-texto", 3, with_payload(3, "triage_completed", nivel="3"), None),
    ("nivel-booleano", 3, with_payload(3, "triage_completed", nivel=True), None),
    ("interrumpida-entero", 3, with_payload(3, "assessment_ended", interrumpida=0), None),
    ("sim-time-texto", 3, changed(3, "test_ordered", sim_time="10"), None),
    ("sim-time-booleano", 3, changed(3, "test_ordered", sim_time=True), None),
    ("event-id-no-texto", 3, changed(3, "test_ordered", event_id=5), None),
    ("event-time-nulo", 3, changed(3, "test_ordered", event_time=None), None),
    # Fuera de rango.
    ("nivel-fuera", 3, with_payload(3, "triage_completed", nivel=6), None),
    ("nivel-cero", 3, with_payload(3, "triage_completed", nivel=0), None),
    ("box-cero", 3, with_payload(3, "box_assigned", box=0), None),
    ("anterior-negativa", 3, with_payload(3, "staffing_changed", anterior=-1), None),
    ("sim-time-negativo", 3, changed(3, "test_ordered", sim_time=-1), None),
    ("sim-time-desborda", 3, changed(3, "test_ordered", sim_time=json.loads("1e400")), None),
    ("sim-time-entero-enorme", 3, changed(3, "test_ordered", sim_time=10**400), None),
    # Valores cerrados.
    ("motivo-fuera", 3, with_payload(3, "triage_completed", motivo="dolor"), None),
    ("circuito-fuera", 1, with_payload(1, "triage_started", circuito="box"), None),
    ("espera-fuera", 3, with_payload(3, "box_released", espera="pruebas"), None),
    # Cadenas del sobre.
    ("event-id-vacio", 3, changed(3, "test_ordered", event_id=""), None),
    ("run-id-vacio", 3, changed(3, "test_ordered", run_id=""), None),
    ("ingest-time-relleno", 3, changed(3, "test_ordered", ingest_time="2026-01-05T00:10:00.000+01:00"), None),  # noqa: E501
    # Identificadores.
    ("episodio-en-recurso", 3, changed(3, "staffing_changed", episode_id="EP-000137", patient_id="PT-000137"), None),  # noqa: E501
    ("paciente-sin-episodio", 3, changed(3, "test_ordered", episode_id=None, patient_id=None), None),  # noqa: E501
    ("episode-id-mal", 3, changed(3, "test_ordered", episode_id="EP-137"), None),
    ("episode-id-salto-final", 3, changed(3, "test_ordered", episode_id="EP-000137\n"), None),
    ("patient-id-salto-final", 3, changed(3, "test_ordered", patient_id="PT-000137\n"), None),
    ("desalojado-por-salto-final", 3, with_payload(3, "patient_displaced", desalojado_por="EP-000140\n"), None),  # noqa: E501
    ("desalojado-por-mal", 3, with_payload(3, "patient_displaced", desalojado_por="PT-000140"), None),  # noqa: E501
    # Pruebas y resultados.
    ("pruebas-desordenadas", 3, with_payload(3, "test_ordered", pruebas=["ecg", "analitica"]), None),  # noqa: E501
    ("pruebas-repetidas", 3, with_payload(3, "test_ordered", pruebas=["ecg", "ecg"]), None),
    ("pruebas-vacia", 3, with_payload(3, "test_ordered", pruebas=[]), None),
    ("pruebas-texto", 3, with_payload(3, "test_ordered", pruebas="ecg"), None),
    ("pruebas-desconocida", 3, with_payload(3, "test_ordered", pruebas=["orina"]), None),
    ("resultados-clave-de-mas", 3, with_payload(3, "test_resulted", resultados={"ecg": "normal", "orina": "normal"}), None),  # noqa: E501
    ("resultados-vacio", 3, with_payload(3, "test_resulted", resultados={}), None),
    ("resultados-valor-fuera", 3, with_payload(3, "test_resulted", resultados={"ecg": "raro"}), None),  # noqa: E501
    # Las diferencias de la lista: el esquema acepta y Event rechaza.
    ("patient-id-de-otro-episodio", 3, changed(3, "test_ordered", patient_id="PT-000138"), "patient-id"),  # noqa: E501
    ("nivel-3.0", 3, with_payload(3, "triage_completed", nivel=3.0), "entero-con-decimales"),
    ("schema-version-3.0", 3, changed(3, "test_ordered", schema_version=3.0), "entero-con-decimales"),  # noqa: E501
    ("anterior-12.0", 3, with_payload(3, "staffing_changed", anterior=12.0), "entero-con-decimales"),  # noqa: E501
]  # fmt: skip
"""Eventos inválidos hechos a mano, cada uno con la diferencia que lo explica (o None)."""

CASES = VALID + INVALID


def event_accepts(data, version: int) -> bool:
    """Si Event(**datos) acepta el evento como uno de la versión del esquema.

    El esquema de la versión N describe los eventos de la versión N: un evento válido de
    otra versión no es de este esquema, aunque Event lo acepte.

    «Event rechaza» es que lance ValueError o TypeError, y solo esas dos: con un campo
    de más o de menos en el sobre, la dataclass lanza TypeError (argumento inesperado o
    que falta), y con un documento que no es un objeto, ** lanza TypeError. Cualquier
    otra excepción no se captura y hace fallar el test.
    """
    try:
        event = Event(**data)
    except (ValueError, TypeError):
        return False
    return event.schema_version == version


@pytest.mark.parametrize(
    ("version", "data", "difference"), [c[1:] for c in CASES], ids=[c[0] for c in CASES]
)
def test_event_y_esquema_coinciden(version, data, difference):
    by_event = event_accepts(data, version)
    by_schema = validator(version).is_valid(data)

    if difference is None:
        assert by_event == by_schema
    else:
        assert difference in KNOWN_DIFFERENCES
        assert by_schema and not by_event


def test_cada_diferencia_de_la_lista_ocurre():
    # Los dos sentidos: cada diferencia de la lista tiene un caso que la muestra, y no hay
    # casos con una diferencia que no esté en la lista (los demás deben coincidir).
    used = {c[3] for c in CASES} - {None}
    assert used == set(KNOWN_DIFFERENCES)
    assert len(VALID) == 57
    assert len(INVALID) > 40


# --- ed.runs ---------------------------------------------------------------------------

INFO = RunInfo("r2026", "directo", 3, 2026, SCENARIO_START, True)


def runs_messages() -> dict[str, str]:
    _, sink = run_hand()
    return {
        "inicio": run_start_json(sink.run_start),
        "fin": run_end_json(sink.run_end),
        "inicio-max": run_start_json(RunStart(INFO, 3510.0, 4320.0, MAX_SPEED, 113, 520)),
        "fin-sin-eventos": run_end_json(RunEnd("r2026", "parar", 2880.0, None, 0)),
        "fin-error": run_end_json(RunEnd("r2026", "error", 3000.5, "r2026-000000041", 41)),
    }


def control_messages() -> dict[str, str]:
    commands = [Command(SPEED, 10), Command(SPEED, MAX_SPEED), Command(PAUSE)]
    commands += [Command(RESUME), Command(STOP)]
    return {f"{c.order}-{c.value}": control_json(RUN, c) for c in commands}


def test_los_mensajes_de_messages_validan():
    runs, control = load(RUNS_SCHEMA), load(CONTROL_SCHEMA)

    for name, text in runs_messages().items():
        assert runs.is_valid(json.loads(text)), name
        assert not control.is_valid(json.loads(text)), name
    for name, text in control_messages().items():
        assert control.is_valid(json.loads(text)), name
        assert not runs.is_valid(json.loads(text)), name


def edit(text: str, **fields) -> dict:
    data = json.loads(text)
    for key, value in fields.items():
        if value is DELETE:
            del data[key]
        else:
            data[key] = value
    return data


def invalid_runs() -> list[tuple[str, dict]]:
    m = runs_messages()
    start, end = m["inicio"], m["fin"]
    census = json.loads(start)["censo"]
    return [
        ("tipo-otro", edit(start, tipo="comienzo")),
        ("version-2", edit(start, version=2)),
        ("inicio-campo-de-mas", edit(start, origen="cli")),
        ("inicio-falta-censo", edit(start, censo=DELETE)),
        ("modo-batch", edit(start, modo="batch")),
        ("velocidad-0", edit(start, velocidad=0)),
        ("velocidad-texto", edit(start, velocidad="rápido")),
        ("velocidad-1e400", edit(start, velocidad=json.loads("1e400"))),
        ("horizonte-1e400", edit(start, horizonte=json.loads("1e400"))),
        ("inicio-directo-1e400", edit(start, inicio_directo=json.loads("1e400"))),
        ("horizonte-0", edit(start, horizonte=0)),
        ("semilla-negativa", edit(start, semilla=-1)),
        ("anclado-texto", edit(start, anclado="no")),
        ("fecha-corta", edit(start, fecha_inicio="2026-1-5")),
        ("fecha-salto-final", edit(start, fecha_inicio="2026-01-05\n")),
        ("censo-campo-de-mas", edit(start, censo={**census, "recursos": 14})),
        ("fin-sim-time-1e400", edit(end, sim_time=json.loads("1e400"))),
        ("motivo-otro", edit(end, motivo="cansancio")),
        ("publicados-negativo", edit(end, publicados=-1)),
        ("ultimo-event-id-vacio", edit(end, ultimo_event_id="")),
        ("fin-falta-campo", edit(end, ultimo_event_id=DELETE)),
        ("fin-con-censo", edit(end, censo=census)),
    ]


def test_mensajes_de_ed_runs_invalidos_no_validan():
    runs = load(RUNS_SCHEMA)
    cases = invalid_runs()

    accepted = [name for name, data in cases if runs.is_valid(data)]

    assert not accepted
    assert len(cases) == 22


# --- ed.control: parse_control y el esquema dicen lo mismo -----------------------------

CONTROL_CASES = [
    *[(name, text, None) for name, text, _ in VALID_ORDERS],
    *[(name, text, "run-id-ajeno") for name, text in FOREIGN_ORDERS],
    *[(name, text, None) for name, text in INVALID_ORDERS],
    # Más, válidos.
    ("reanudar", '{"version": 1, "run_id": "r1", "orden": "reanudar"}', None),
    ("parar", '{"version": 1, "run_id": "r1", "orden": "parar"}', None),
    ("valor-decimal", '{"version": 1, "run_id": "r1", "orden": "velocidad", "valor": 2.5}', None),
    ("version-1.0", '{"version": 1.0, "run_id": "r1", "orden": "parar"}', None),
    # Más, inválidos.
    ("valor-max-mayusculas", '{"version": 1, "run_id": "r1", "orden": "velocidad", "valor": "MAX"}', None),  # noqa: E501
    ("valor-diminuto", '{"version": 1, "run_id": "r1", "orden": "velocidad", "valor": 1e-400}', None),  # noqa: E501
    ("velocidad-con-valor-nulo", '{"version": 1, "run_id": "r1", "orden": "velocidad", "valor": null}', None),  # noqa: E501
    ("ajeno-e-invalido", '{"version": 7, "run_id": "r2", "orden": "acelerar"}', "run-id-ajeno"),
]  # fmt: skip
"""Las órdenes de test_messages.py y algunas más, con la diferencia que las explica."""


def schema_accepts(control: Draft202012Validator, text: str | bytes) -> bool:
    """Si el esquema acepta el mensaje; un texto que no es UTF-8 ni JSON no lo acepta."""
    try:
        data = json.loads(text.decode("utf-8") if isinstance(text, bytes) else text)
    except ValueError:
        return False
    return control.is_valid(data)


@pytest.mark.parametrize(
    ("text", "difference"), [c[1:] for c in CONTROL_CASES], ids=[c[0] for c in CONTROL_CASES]
)
def test_parse_control_y_esquema_coinciden(text, difference):
    warnings = []
    command = parse_control(text, RUN, warnings.append)
    by_schema = schema_accepts(load(CONTROL_SCHEMA), text)

    if difference is None:
        # Acepta = da una orden sin aviso; rechaza = None con un aviso.
        assert (command is not None) == by_schema
        assert len(warnings) == (0 if by_schema else 1)
    else:
        # Otro run_id: se ignora sin aviso, sea válida o no.
        assert difference in KNOWN_CONTROL_DIFFERENCES
        assert (command, warnings) == (None, [])


def test_cada_diferencia_de_las_ordenes_ocurre():
    used = {c[2] for c in CONTROL_CASES} - {None}
    assert used == set(KNOWN_CONTROL_DIFFERENCES)
    # La diferencia existe de verdad: una orden ajena que el esquema acepta.
    control = load(CONTROL_SCHEMA)
    foreign = [text for _, text, label in CONTROL_CASES if label == "run-id-ajeno"]
    assert any(schema_accepts(control, text) for text in foreign)
