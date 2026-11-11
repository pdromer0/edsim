"""Censo inicial del directo (tarea 6.2): episodios abiertos, censo y eventos en directo.

El censo son eventos del log, no una foto del estado (H6-11): los del calentamiento de
los episodios abiertos en W y todos los de recursos, en su orden. Primero, con un log a
mano en las tres versiones del catálogo; después, contra la verdad del motor por pasos:
los episodios abiertos son exactamente los procesos de paciente vivos en W, y censo más
directo es el log filtrado de la pieza 7.
"""

import math
from pathlib import Path

import pytest

from edsim.arrivals.profile import load_profile
from edsim.engine.center import load_center
from edsim.engine.engine import start_ed
from edsim.engine.events import EventLog, MemorySink, to_json
from edsim.engine.scenarios import SCENARIO_START
from edsim.live.census import census, live_events, open_episodes
from edsim.profiles.config import load_profiles

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data"
CONFIG = ROOT / "config"

# --- Un log a mano -------------------------------------------------------------------

W_HAND = 120


def emit_hand_log(log: EventLog) -> None:
    """Emite el log a mano con ``log``, de cualquier versión.

    staffing_changed de enfermería y de médicos en 0; EP-000001 llega en 10 y sale en 100;
    EP-000002 llega en 50 y sigue dentro; EP-000003 llega en 60 y sale justo en 120 = W.
    El directo de la tarea 6.3 sigue emitiendo con el mismo log.
    """
    clinical = log.schema_version >= 2
    arrived = {"medio": "propios_medios"} if clinical else {}
    registered = {"edad": 40, "sexo": "mujer"} if clinical else {}

    log.emit("staffing_changed", 0.0, recurso="enfermeria_triaje", anterior=0, nueva=2)
    log.emit("staffing_changed", 0.0, recurso="medicos", anterior=0, nueva=3)
    for arrival_id, t in ((1, 10.0), (2, 50.0), (3, 60.0)):
        log.emit("patient_arrived", t, arrival_id=arrival_id, **arrived)
        log.emit("patient_registered", t, arrival_id=arrival_id, **registered)
    log.emit("patient_departed", 100.0, arrival_id=1, destino="alta")
    log.emit("patient_departed", 120.0, arrival_id=3, destino="ingreso")


def hand_log(version: int) -> list:
    """El log a mano, emitido con un EventLog de la versión dada."""
    sink = MemorySink()
    emit_hand_log(EventLog("rcenso", SCENARIO_START, sink, schema_version=version))
    return sink.events


@pytest.mark.parametrize("version", [1, 2, 3])
def test_censo_a_mano(version):
    events = hand_log(version)
    assert {e.schema_version for e in events} == {version}

    assert open_episodes(events, W_HAND) == {"EP-000002", "EP-000003"}

    got = census(events, W_HAND)
    assert [(e.event_type, e.episode_id, e.sim_time) for e in got] == [
        ("staffing_changed", None, 0.0),
        ("staffing_changed", None, 0.0),
        ("patient_arrived", "EP-000002", 50.0),
        ("patient_registered", "EP-000002", 50.0),
        ("patient_arrived", "EP-000003", 60.0),
        ("patient_registered", "EP-000003", 60.0),
    ]
    assert all(e.episode_id != "EP-000001" for e in got)

    # La salida justo en W es del directo, no del censo.
    live = live_events(events, W_HAND)
    assert [(e.event_type, e.episode_id, e.sim_time) for e in live] == [
        ("patient_departed", "EP-000003", 120.0)
    ]
    assert got == [e for e in events if e in got]  # en el orden original


def hand_log_v4() -> list:
    """El log a mano de la 6.2 en la versión 4 (tarea 5.1), en orden de tiempo, más dos episodios.

    EP-000004 llega en 70 y se va sin ser visto en 110; EP-000005 llega en 80, se decide
    su ingreso y pide cama en 100 y la recibe en 150. Como el de la 6.2, no es un
    recorrido completo: solo lleva lo que el censo mira.
    """
    sink = MemorySink()
    log = EventLog("rcenso", SCENARIO_START, sink, schema_version=4)
    arrived = {"medio": "propios_medios"}
    registered = {"edad": 40, "sexo": "mujer"}
    log.emit("staffing_changed", 0.0, recurso="enfermeria_triaje", anterior=0, nueva=2)
    log.emit("staffing_changed", 0.0, recurso="medicos", anterior=0, nueva=3)
    for arrival_id, t in ((1, 10.0), (2, 50.0), (3, 60.0), (4, 70.0), (5, 80.0)):
        log.emit("patient_arrived", t, arrival_id=arrival_id, **arrived)
        log.emit("patient_registered", t, arrival_id=arrival_id, **registered)
    log.emit("patient_departed", 100.0, arrival_id=1, destino="alta")
    log.emit("disposition_decided", 100.0, arrival_id=5, destino="ingreso")
    log.emit("bed_requested", 100.0, arrival_id=5, servicio="planta")
    log.emit("patient_left_wbs", 110.0, arrival_id=4, espera="triaje")
    log.emit("patient_departed", 120.0, arrival_id=3, destino="ingreso")
    log.emit("bed_assigned", 150.0, arrival_id=5, servicio="planta")
    log.emit("patient_departed", 150.0, arrival_id=5, destino="ingreso")
    return sink.events


def test_censo_a_mano_version_4():
    # W = 120: EP-000002 sigue dentro, EP-000003 sale justo en W (no antes) y EP-000005
    # espera cama hasta 150. EP-000004 se fue en 110 < 120: el abandono lo cierra.
    events = hand_log_v4()
    assert open_episodes(events, W_HAND) == {"EP-000002", "EP-000003", "EP-000005"}

    got = census(events, W_HAND)
    assert [(e.event_type, e.episode_id, e.sim_time) for e in got] == [
        ("staffing_changed", None, 0.0),
        ("staffing_changed", None, 0.0),
        ("patient_arrived", "EP-000002", 50.0),
        ("patient_registered", "EP-000002", 50.0),
        ("patient_arrived", "EP-000003", 60.0),
        ("patient_registered", "EP-000003", 60.0),
        ("patient_arrived", "EP-000005", 80.0),
        ("patient_registered", "EP-000005", 80.0),
        ("disposition_decided", "EP-000005", 100.0),
        ("bed_requested", "EP-000005", 100.0),
    ]
    assert all(e.episode_id != "EP-000004" for e in got)
    live = live_events(events, W_HAND)
    assert [(e.event_type, e.episode_id, e.sim_time) for e in live] == [
        ("patient_departed", "EP-000003", 120.0),
        ("bed_assigned", "EP-000005", 150.0),
        ("patient_departed", "EP-000005", 150.0),
    ]


def test_censo_de_un_log_vacio():
    assert open_episodes([], W_HAND) == frozenset()
    assert census([], W_HAND) == []
    assert live_events([], W_HAND) == []


def test_en_el_instante_0_todo_es_directo():
    events = hand_log(3)
    assert open_episodes(events, 0) == frozenset()
    assert census(events, 0) == []
    assert live_events(events, 0) == events


def test_censo_acepta_un_iterador():
    # census recorre los eventos dos veces: con un generador no puede perder ninguno.
    events = hand_log(3)
    assert census(iter(events), W_HAND) == census(events, W_HAND)


@pytest.mark.parametrize("start", [math.nan, "120", None, True])
@pytest.mark.parametrize("function", [open_episodes, census, live_events])
def test_inicio_no_valido(function, start):
    with pytest.raises(ValueError, match="start"):
        function(hand_log(3), start)


# --- Contra el motor por pasos -------------------------------------------------------

SEED = 2026
DAYS = 3
W = 2 * 1440

MODELS = {
    "provisional": (DATA / "centro_ejemplo.toml", DATA / "llegadas_ejemplo.toml", None),
    "clinico": (CONFIG / "centro.toml", CONFIG / "llegadas.toml", CONFIG / "perfiles.toml"),
}


@pytest.fixture(scope="module", params=sorted(MODELS))
def run(request):
    """Eventos hasta W, vivos en W según el motor y el log completo hasta el horizonte."""
    center, arrivals, profiles = MODELS[request.param]
    sink = MemorySink()
    ed = start_ed(
        load_center(center),
        load_profile(arrivals),
        DAYS,
        SEED,
        sink=sink,
        profiles=None if profiles is None else load_profiles(profiles),
    )
    ed.advance_until(W)
    warmup, alive = list(sink.events), ed.alive_episodes()
    ed.advance_until(ed.horizon)
    return warmup, alive, sink.events


def test_abiertos_igual_a_vivos(run):
    warmup, alive, _ = run
    arrived = {e.episode_id for e in warmup if e.event_type == "patient_arrived"}
    departed = {e.episode_id for e in warmup if e.event_type == "patient_departed"}
    # Guardas: hay pacientes dentro y alguno de los que llegaron antes de W ya salió.
    assert len(alive) > 10
    assert departed and departed < arrived

    assert open_episodes(warmup, W) == alive


def test_censo_mas_directo_es_el_log_filtrado(run):
    warmup, alive, events = run
    # La fórmula de la pieza 7, con los vivos del motor y no con open_episodes.
    expected = [
        e for e in events if e.sim_time >= W or e.episode_id is None or e.episode_id in alive
    ]

    got = census(events, W) + live_events(events, W)
    assert [to_json(e) for e in got] == [to_json(e) for e in expected]
    # Guardas: el censo deja fuera parte del calentamiento, y lleva recursos y pacientes.
    initial = census(events, W)
    assert len(initial) < len(warmup)
    assert any(e.episode_id is None for e in initial)
    assert any(e.episode_id is not None for e in initial)
    assert census(warmup, W) == initial
