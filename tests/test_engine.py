"""simulate_ed: llegadas del hito 2, ground truth, reproducibilidad, horizonte y huella.

Se usan el centro y el perfil de ejemplo de tests/data con semilla fija y pocos días.
"""

import dataclasses
import hashlib
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
import pytest

from edsim.arrivals.profile import ArrivalProfile, load_profile
from edsim.arrivals.rate import MINUTES_PER_DAY
from edsim.arrivals.thinning import ArrivalRecord, DayRecord, iter_arrivals
from edsim.engine.center import CenterConfig, load_center
from edsim.engine.clinical import PatientDraws
from edsim.engine.engine import EDResult, default_run_id, simulate_ed
from edsim.engine.events import Event, JsonlSink, MemorySink
from edsim.engine.ground_truth import EpisodeTruth
from edsim.engine.invariants import check_invariants
from edsim.seeds import child_streams

DATA = Path(__file__).parent / "data"
SEED = 2026
DAYS = 3

# Huella SHA-256 de eventos.jsonl con el centro y el perfil de ejemplo, semilla 2026
# y 3 días. Se regenera a propósito en las tareas 3.4 (prioridad y desalojo) y 3.5
# (turnos), que cambian el orden de servicio, explicando el cambio en el commit;
# nunca para que un test pase.
FINGERPRINT = "740d77b7f0538125bb76b0019af0abc07ba6d7cf7fc85f044e4f4c1a0d4cbed1"


@pytest.fixture(scope="module")
def center() -> CenterConfig:
    return load_center(DATA / "centro_ejemplo.toml")


@pytest.fixture(scope="module")
def profile() -> ArrivalProfile:
    return load_profile(DATA / "llegadas_ejemplo.toml")


def simulate(center, profile, seed=SEED, days=DAYS, **kwargs) -> tuple[list[Event], EDResult]:
    sink = MemorySink()
    result = simulate_ed(center, profile, days, seed, sink=sink, **kwargs)
    return sink.events, result


@pytest.fixture(scope="module")
def base(center, profile) -> tuple[list[Event], EDResult]:
    return simulate(center, profile)


def by_episode(events: list[Event]) -> dict[str, list[Event]]:
    episodes: dict[str, list[Event]] = defaultdict(list)
    for e in events:
        if e.episode_id is not None:
            episodes[e.episode_id].append(e)
    return episodes


def box_waits(events: list[Event]) -> dict[str, float]:
    """Espera de box de cada episodio que lo recibió: box_assigned − triage_completed."""
    waits = {}
    for episode, evs in by_episode(events).items():
        times = {e.event_type: e.sim_time for e in evs}
        if "box_assigned" in times:
            waits[episode] = times["box_assigned"] - times["triage_completed"]
    return waits


# --- Capacidad infinita -------------------------------------------------------------


def expected_trace(truth: EpisodeTruth, t0: float) -> list[tuple[str, float]]:
    """Recorrido sin esperas: cada duración se suma a t, en el mismo orden que SimPy.

    t0 es el sim_time del patient_arrived del log (env.now), no arrival_time: con el
    ulp de arrival_source, el == fallaría en 1 de cada ~92 000 llegadas.
    """
    t = t0
    trace = [("patient_arrived", t), ("patient_registered", t), ("triage_started", t)]
    t += truth.triage_time
    trace += [("triage_completed", t), ("box_assigned", t), ("assessment_started", t)]
    t += truth.assessment_time
    trace.append(("assessment_ended", t))
    if truth.needs_tests:
        trace.append(("test_ordered", t))
        t += truth.test_turnaround
        trace += [("test_resulted", t), ("assessment_started", t)]
        t += truth.reassessment_time
        trace.append(("assessment_ended", t))
    trace += [("disposition_decided", t), ("patient_departed", t)]
    return trace


def test_capacidad_infinita_sin_esperas(center, profile):
    infinite = dataclasses.replace(
        center, triage_nurses=(10_000,) * 3, doctors=(10_000,) * 3, boxes=10_000
    )

    events, result = simulate(infinite, profile)

    episodes = by_episode(events)
    departed = 0
    for truth in result.ground_truth.episodes:
        actual = [(e.event_type, e.sim_time) for e in episodes[truth.episode_id]]
        expected = expected_trace(truth, actual[0][1])
        # Los cortados por el horizonte son un prefijo exacto del recorrido sin esperas.
        assert actual == expected[: len(actual)], truth.episode_id
        departed += actual[-1][0] == "patient_departed"
    assert departed > 0.9 * len(result.ground_truth.episodes)


# --- Reproducibilidad ----------------------------------------------------------------


def test_misma_semilla_entera(center, profile, base):
    events, result = simulate(center, profile)

    assert events == base[0]
    assert result == base[1]


def test_mismo_seed_sequence_dos_veces(center, profile):
    seed = np.random.SeedSequence(SEED).spawn(3)[1]

    first = simulate(center, profile, seed=seed)
    second = simulate(center, profile, seed=seed)

    assert first == second


def test_semillas_distintas(center, profile, base):
    events, result = simulate(center, profile, seed=SEED + 1)

    assert result.ground_truth.episodes != base[1].ground_truth.episodes
    assert [e.sim_time for e in events] != [e.sim_time for e in base[0]]


# --- Llegadas y ground truth -----------------------------------------------------------


def test_llegadas_identicas_a_iter_arrivals(profile, base):
    events, result = base
    days: list[DayRecord] = []
    arrivals = list(iter_arrivals(profile, DAYS, child_streams(SEED, 5)[0], on_day=days.append))

    # Ground truth: bit a bit.
    episodes = result.ground_truth.episodes
    assert [(t.arrival_id, t.arrival_time) for t in episodes] == [
        (a.arrival_id, a.time) for a in arrivals
    ]
    assert result.ground_truth.days == tuple(days)
    # Log: mismo episodio y sim_time = env.now, igual o a 1 ulp de la llegada.
    logged = [e for e in events if e.event_type == "patient_arrived"]
    assert [e.episode_id for e in logged] == [t.episode_id for t in episodes]
    for e, a in zip(logged, arrivals, strict=True):
        assert abs(e.sim_time - a.time) <= math.ulp(a.time)


def test_todos_los_dias_en_el_ground_truth(base):
    _, result = base
    days = result.ground_truth.days

    assert [d.day for d in days] == list(range(DAYS))
    assert sum(d.accepted for d in days) == len(result.ground_truth.episodes)


def test_nivel_y_destino_del_log_iguales_al_ground_truth(base):
    events, result = base
    truth = {t.episode_id: t for t in result.ground_truth.episodes}

    for e in events:
        if e.event_type == "triage_completed":
            assert e.payload["nivel"] == truth[e.episode_id].level
        elif e.event_type == "disposition_decided":
            admitted = truth[e.episode_id].admitted
            assert e.payload["destino"] == ("ingreso" if admitted else "alta")


def test_otra_plantilla_mismos_pacientes_otras_esperas(center, profile, base):
    narrow = dataclasses.replace(center, boxes=12, doctors=(6, 6, 4))

    events, result = simulate(narrow, profile)

    assert result.ground_truth == base[1].ground_truth
    waits, base_waits = box_waits(events), box_waits(base[0])
    # Que la comparación no pase en vacío: con 12 boxes hay colas.
    assert sum(w > 0 for w in waits.values()) > 10
    common = waits.keys() & base_waits.keys()
    assert any(waits[k] != base_waits[k] for k in common)


def test_muestreador_inyectado(center, profile):
    draws = PatientDraws(
        level=4,
        triage_time=1.0,
        assessment_time=2.0,
        reassessment_time=3.0,
        needs_tests=False,
        test_turnaround=4.0,
        admitted=False,
    )
    seen: list[ArrivalRecord] = []

    def sampler(arrival: ArrivalRecord) -> PatientDraws:
        seen.append(arrival)
        return draws

    _, result = simulate(center, profile, days=1, sampler=sampler)

    assert [(a.arrival_id, a.time) for a in seen] == [
        (t.arrival_id, t.arrival_time) for t in result.ground_truth.episodes
    ]
    assert all(t.level == 4 and t.triage_time == 1.0 for t in result.ground_truth.episodes)


# --- Horizonte ----------------------------------------------------------------------


def test_horizonte(base):
    events, result = base
    horizon = DAYS * MINUTES_PER_DAY

    assert all(e.sim_time < horizon for e in events)
    arrived = {e.episode_id for e in events if e.event_type == "patient_arrived"}
    departed = {e.episode_id for e in events if e.event_type == "patient_departed"}
    assert departed < arrived
    assert result.inside == len(arrived - departed) > 0


# --- Invariantes ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "change",
    [{}, {"boxes": 10, "doctors": (5, 5, 3), "triage_nurses": (1, 1, 1)}],
    ids=["ejemplo", "estrecho"],
)
def test_invariantes_sin_violaciones(center, profile, change):
    config = dataclasses.replace(center, **change)

    events, result = simulate(config, profile)

    assert len(events) > 5_000  # para que no pase en vacío
    violations = check_invariants(
        events, config, ground_truth=result.ground_truth, inside=result.inside
    )
    assert violations == []


# --- run_id ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "seed, expected",
    [
        (2026, "r2026"),
        (0, "r0"),
        (np.random.SeedSequence(2026), "r2026"),
        (np.random.SeedSequence(2026).spawn(3)[1], "r2026.1"),
        (np.random.SeedSequence(2026).spawn(3)[2].spawn(1)[0], "r2026.2.0"),
        (np.random.SeedSequence([1, 2]), "r1_2"),
    ],
)
def test_run_id_por_defecto(seed, expected):
    assert default_run_id(seed) == expected


def test_run_id_en_el_log(center, profile, base):
    events, result = base
    assert result.run_id == "r2026"
    assert events[0].event_id == "r2026-000000000"

    events, result = simulate(center, profile, days=1, run_id="prueba")
    assert result.run_id == "prueba"
    assert {e.run_id for e in events} == {"prueba"}


# --- Regresión ----------------------------------------------------------------------------


def test_huella_del_log(center, profile, tmp_path):
    path = tmp_path / "eventos.jsonl"
    with JsonlSink(path) as sink:
        simulate_ed(center, profile, DAYS, SEED, sink=sink)

    assert hashlib.sha256(path.read_bytes()).hexdigest() == FINGERPRINT
