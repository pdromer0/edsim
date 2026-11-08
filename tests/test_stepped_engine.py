"""Motor por pasos (tarea 6.2): por trozos, paso a paso y en el horizonte.

El directo del hito 6 avanza el motor evento a evento para esperar entre uno y otro. Eso
no puede cambiar nada: avanzar por trozos arbitrarios, o paso a paso, da el mismo log, la
misma verdad y los mismos procesos vivos que de un tirón (docs/specs/hito-6.md, pieza 1).
Se prueba con los dos modelos, semilla 2026 y 3 días: el provisional con el centro de
ejemplo y el clínico con config/. Los cortes se fijaron antes de ver los resultados.
"""

import math
from pathlib import Path

import numpy as np
import pytest

from edsim.arrivals.profile import load_profile
from edsim.arrivals.rate import MINUTES_PER_DAY
from edsim.engine.center import load_center
from edsim.engine.engine import SteppedED, simulate_ed, start_ed, start_engine
from edsim.engine.events import EventLog, MemorySink, to_json
from edsim.engine.scenarios import SCENARIO_START, Scenario, hand_draws
from edsim.profiles.config import load_profiles

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data"
CONFIG = ROOT / "config"
SEED = 2026
DAYS = 3
HORIZON = DAYS * MINUTES_PER_DAY

MODELS = {
    "provisional": (DATA / "centro_ejemplo.toml", DATA / "llegadas_ejemplo.toml", None),
    "clinico": (CONFIG / "centro.toml", CONFIG / "llegadas.toml", CONFIG / "perfiles.toml"),
}

RANDOM_CUTS = sorted(float(t) for t in np.random.default_rng(62).uniform(0, HORIZON, 8))
"""Ocho cortes uniformes en (0, H), con una semilla fija."""


@pytest.fixture(scope="module", params=sorted(MODELS))
def model(request):
    center, arrivals, profiles = MODELS[request.param]
    return (
        load_center(center),
        load_profile(arrivals),
        None if profiles is None else load_profiles(profiles),
    )


def start(model) -> tuple[SteppedED, MemorySink]:
    center, profile, profiles = model
    sink = MemorySink()
    return start_ed(center, profile, DAYS, SEED, sink=sink, profiles=profiles), sink


def outcome(ed: SteppedED, sink: MemorySink):
    """Líneas del log, EDResult y vivos al final; los vivos son tantos como inside."""
    result = ed.finish()
    alive = ed.alive_episodes()
    assert len(alive) == result.inside
    return [to_json(e) for e in sink.events], result, alive


@pytest.fixture(scope="module")
def at_once(model):
    """De un tirón: start_ed y advance_until(H). Devuelve también los eventos."""
    ed, sink = start(model)
    ed.advance_until(ed.horizon)
    return sink.events, outcome(ed, sink)


def test_de_un_tiron_es_simulate_ed(model, at_once):
    center, profile, profiles = model
    sink = MemorySink()
    result = simulate_ed(center, profile, DAYS, SEED, sink=sink, profiles=profiles)

    _, (lines, expected, _) = at_once
    assert [to_json(e) for e in sink.events] == lines
    assert result == expected
    assert len(expected.ground_truth.days) == DAYS


def test_por_trozos_igual_que_de_un_tiron(model, at_once):
    events, (lines, result, alive) = at_once
    arrival = next(
        e.sim_time
        for e in events
        if e.event_type == "patient_arrived" and e.episode_id == "EP-000100"
    )
    # Guardas: hay un instante con varios eventos y un evento justo en el corte de llegada.
    assert sum(e.sim_time == 480 for e in events) >= 2
    assert any(e.sim_time == arrival for e in events)
    assert result.inside > 0

    cuts = sorted([0, 480, 900, 1320, arrival, *RANDOM_CUTS, HORIZON + 60, math.inf])
    ed, sink = start(model)
    for cut in cuts:
        ed.advance_until(cut)
        if cut > 0:
            # El log va en orden de sim_time: basta con el último.
            assert sink.events[-1].sim_time < cut, cut
        else:
            # En 0 solo están los staffing_changed que start_shifts emite al arrancar.
            assert [e.event_type for e in sink.events] == ["staffing_changed"] * 2
        assert ed.peek() >= cut, cut

    assert outcome(ed, sink) == (lines, result, alive)
    assert ed.peek() == math.inf


def test_paso_a_paso_el_primer_dia(model, at_once):
    _, expected = at_once
    ed, sink = start(model)
    steps = 0
    while ed.peek() < MINUTES_PER_DAY:
        ed.step()
        steps += 1

    assert steps > 1000
    assert sink.events[-1].sim_time < MINUTES_PER_DAY <= ed.peek()
    ed.advance_until(ed.horizon)
    assert outcome(ed, sink) == expected


# --- El horizonte -------------------------------------------------------------------


@pytest.fixture(scope="module")
def example_center():
    return load_center(DATA / "centro_ejemplo.toml")


def start_scenario(center, patients, days):
    scenario = Scenario(center, tuple(patients), days)
    sink = MemorySink()
    log = EventLog("rpasos", SCENARIO_START, sink)
    engine = start_engine(scenario.center, scenario.arrivals, scenario.sampler, log, days)
    return engine, sink


# Un nivel 3 llega en 1400; triaje de 10 min y valoración de 30, sin pruebas: su
# valoración termina exactamente en 1440, el horizonte de un día.
AT_THE_HORIZON = [(1400.0, hand_draws(3, 10, 30))]


def test_un_evento_en_el_horizonte_no_ocurre(example_center):
    engine, sink = start_scenario(example_center, AT_THE_HORIZON, days=1)
    engine.advance_until(engine.horizon)

    assert [(e.event_type, e.sim_time) for e in sink.events if e.episode_id] == [
        ("patient_arrived", 1400.0),
        ("patient_registered", 1400.0),
        ("triage_started", 1400.0),
        ("triage_completed", 1410.0),
        ("box_assigned", 1410.0),
        ("assessment_started", 1410.0),
    ]
    assert engine.peek() == math.inf
    assert engine.alive_episodes() == {"EP-000000"}
    assert engine.finish().inside == 1


def test_el_evento_del_horizonte_estaba_programado(example_center):
    # Recuento: con dos días, el mismo paciente tiene su evento pendiente justo en 1440,
    # y en ese instante salen la valoración, la decisión y la salida.
    engine, sink = start_scenario(example_center, AT_THE_HORIZON, days=2)
    engine.advance_until(MINUTES_PER_DAY)
    assert engine.peek() == 1440.0
    assert engine.alive_episodes() == {"EP-000000"}

    engine.advance_until(engine.horizon)
    assert [e.event_type for e in sink.events if e.sim_time == 1440.0] == [
        "assessment_ended",
        "disposition_decided",
        "patient_departed",
    ]
    assert engine.alive_episodes() == frozenset()
    assert engine.finish().inside == 0


def test_step_sin_eventos_antes_del_horizonte_falla(example_center):
    engine, _ = start_scenario(example_center, AT_THE_HORIZON, days=1)
    engine.advance_until(engine.horizon)

    with pytest.raises(RuntimeError, match="horizon"):
        engine.step()


def test_finish_antes_del_horizonte_falla(example_center):
    engine, _ = start_scenario(example_center, AT_THE_HORIZON, days=1)
    with pytest.raises(RuntimeError, match="advance_until"):
        engine.finish()

    engine.advance_until(1405)
    with pytest.raises(RuntimeError, match="advance_until"):
        engine.finish()

    engine.advance_until(engine.horizon)
    assert engine.finish() == engine.finish()


@pytest.mark.parametrize("t", [math.nan, "10", None, True])
def test_advance_until_rechaza_nan_y_lo_que_no_es_numero(example_center, t):
    engine, sink = start_scenario(example_center, AT_THE_HORIZON, days=1)
    with pytest.raises(ValueError, match="number"):
        engine.advance_until(t)
    assert len(sink.events) == 2  # solo los staffing_changed del arranque


def test_advance_until_hacia_atras_no_hace_nada(example_center):
    engine, sink = start_scenario(example_center, AT_THE_HORIZON, days=1)
    engine.advance_until(1405)
    before = list(sink.events)

    engine.advance_until(100)
    assert sink.events == before
    assert engine.peek() == 1410.0
