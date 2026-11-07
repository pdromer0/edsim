"""Sala de resultados (decisión candidata 45, tarea 4.6a).

El escenario a mano de ``clinical_factory.room_log``: un box, tres niveles 4. A deja el
box en 30 al pedir un ECG, B lo recibe en 30, los resultados de A llegan en 42 y A vuelve
al box en 70 por delante de C, que espera desde 25 pero llegó después. Los valores a mano
de este fichero salen de esos instantes, no de las funciones que se prueban.
"""

import dataclasses
import itertools
from datetime import date
from pathlib import Path

import pytest
from clinical_factory import room_log

from edsim.arrivals.profile import load_profile
from edsim.engine.analysis import (
    MEASURES,
    busy_intervals,
    episode_table,
    little_laws,
    step_curves,
    utilization_identities,
)
from edsim.engine.center import load_center
from edsim.engine.engine import simulate_ed
from edsim.engine.events import MemorySink

DATA = Path(__file__).parent / "data"
HORIZON = 1440.0


@pytest.fixture(scope="module")
def room():
    return room_log()


@pytest.fixture(scope="module")
def records(room):
    return {r.episode_id: r for r in episode_table(room)}


# --- Análisis del escenario a mano --------------------------------------------------


def test_esperas_de_box_inicial_y_de_la_vuelta(records):
    a, b, c = records["EP-000000"], records["EP-000001"], records["EP-000002"]
    # A: box en cuanto acaba el triaje (10) y, tras la sala, de 42 a 70.
    assert (a.initial_box_wait, a.results_box_wait, a.box_wait) == (0.0, 28.0, 28.0)
    # B: de 11 a 30; C: de 25 a 80. No pasan por la sala.
    assert (b.initial_box_wait, b.results_box_wait, b.box_wait) == (19.0, 0.0, 19.0)
    assert (c.initial_box_wait, c.results_box_wait, c.box_wait) == (55.0, 0.0, 55.0)
    # La espera de médico no cuenta la sala: A tiene médico en cuanto vuelve al box.
    assert (a.doctor_wait, a.first_box, a.departure) == (0.0, 10.0, 80.0)


def test_los_relojes_no_cambian_con_la_sala(records):
    # Los relojes A, B y C acaban en la primera valoración: la sala viene después.
    a = records["EP-000000"]
    assert (a.door_to_doctor, a.triage_start_to_doctor, a.classified_to_doctor) == (5.0, 5.0, 0.0)


def test_las_medidas_nuevas_en_measures():
    assert MEASURES[:4] == ("triage_wait", "box_wait", "initial_box_wait", "results_box_wait")


def test_el_box_de_a_son_20_mas_10_minutos(room):
    # A ocupa el box 20 minutos de valoración y 10 de reevaluación, no la ronda.
    boxes = busy_intervals(room, HORIZON)["boxes"]
    assert boxes == [(10.0, 30.0), (30.0, 70.0), (70.0, 80.0), (80.0, 95.0)]
    a = [(10.0, 30.0), (70.0, 80.0)]
    assert sum(end - start for start, end in a) == 30.0


def test_curvas_a_mano(room):
    curves = step_curves(room, HORIZON)
    at = {t: curves.value("boxes_busy", t) for t in (9, 10, 30, 42, 70, 80, 95)}
    assert at == {9: 0, 10: 1, 30: 1, 42: 1, 70: 1, 80: 1, 95: 0}
    # La cola de box: B desde 11, C desde 25, A sale en 30... y vuelve en 42.
    queue = {t: curves.value("waiting_box", t) for t in (10, 11, 25, 30, 42, 70, 80)}
    assert queue == {10: 0, 11: 1, 25: 2, 30: 1, 42: 2, 70: 1, 80: 0}
    # El censo cuenta a A también en la sala.
    census = {t: curves.value("census", t) for t in (5, 6, 20, 35, 70, 80, 95)}
    assert census == {5: 1, 6: 2, 20: 3, 35: 3, 70: 2, 80: 1, 95: 0}


def test_little_y_utilizacion_exactas_en_el_escenario(room, records):
    # Nadie dentro en los bordes de [0, 1440]: Little es exacta. Área de la cola de box:
    # 14·1 + 5·2 + 12·1 + 28·2 + 10·1 = 102 = 28 + 19 + 55, las tres box_wait.
    curves = step_curves(room, HORIZON)
    assert curves.area("waiting_box", 0, HORIZON) == 102.0
    laws = {law.name: law for law in little_laws(tuple(records.values()), curves, 0, HORIZON)}
    assert laws["box_queue"].relative_error == pytest.approx(0, abs=1e-12)
    assert laws["system"].relative_error == pytest.approx(0, abs=1e-12)
    for identity in utilization_identities(room, curves, 0, HORIZON):
        assert identity.relative_error == pytest.approx(0, abs=1e-12), identity.pool


def test_sin_sala_la_espera_inicial_es_la_total():
    # Con el provisional (sin sala) y sin desalojos, la espera de box es toda inicial.
    sink = MemorySink()
    simulate_ed(
        load_center(DATA / "centro_ejemplo.toml"),
        load_profile(DATA / "llegadas_ejemplo.toml"),
        2,
        2026,
        sink=sink,
        warmup_days=0,
    )
    done = [r for r in episode_table(sink.events) if r.departure is not None]
    assert done
    plain = [r for r in done if r.displacements == 0]
    assert plain
    assert all(r.initial_box_wait == r.box_wait for r in plain)
    assert all(r.results_box_wait == 0.0 for r in done)
    # Los campos nuevos van al final de EpisodeRecord: runs/ y la app leen los de antes.
    names = [f.name for f in dataclasses.fields(done[0])]
    assert names[-2:] == ["initial_box_wait", "results_box_wait"]


# --- Replay y Episodios: runs/_location y episode_segments --------------------------


def states_by_time(events, episode):
    """El estado y el box de un episodio tras cada instante de sus eventos."""
    from edsim.runs._location import LocationState

    state, out = LocationState(), {}
    for e in events:
        if e.episode_id == episode:
            state = state.apply(e)
            out[e.sim_time] = (state.location(), state.box)
    return out


def test_el_paciente_de_la_sala_espera_pruebas_sin_box(room):
    a = states_by_time(room, "EP-000000")
    assert a[10.0] == ("assessment", 1)
    assert a[30.0] == ("waiting_tests", None)  # en la sala, con las pruebas pendientes
    assert a[42.0] == ("waiting_box", None)  # con los resultados, espera box
    assert a[70.0] == ("reassessment", 1)


def test_sin_box_fuera_de_la_sala_es_esperar_box(room):
    # B antes de su primer box y un desalojado con las pruebas pendientes, como hasta ahora.
    from edsim.engine.events import EventLog, MemorySink
    from edsim.runs._location import LocationState

    assert states_by_time(room, "EP-000001")[11.0] == ("waiting_box", None)
    log = EventLog("r", date(2026, 1, 5), MemorySink())
    displaced = LocationState(triage_started=True, triaged=True, box=3, tests_pending=True)
    after = displaced.apply(
        log.emit("patient_displaced", 1.0, arrival_id=0, box=3, desalojado_por="EP-000009")
    )
    assert (after.location(), after.box, after.in_results_room) == ("waiting_box", None, False)


def test_nunca_dos_pacientes_en_el_mismo_box(room):
    from edsim.runs.episodes import episode_segments

    spans = []
    for episode in ("EP-000000", "EP-000001", "EP-000002"):
        own = [e for e in room if e.episode_id == episode]
        spans += [(s.start, s.end, s.box) for s in episode_segments(own, HORIZON).segments if s.box]
    for i, (start, end, box) in enumerate(spans):
        for other_start, other_end, other_box in spans[i + 1 :]:
            assert box != other_box or end <= other_start or other_end <= start
    # Los tramos de A: box 1 de 10 a 30, la sala sin box y el box 1 otra vez de 70 a 80.
    a = episode_segments([e for e in room if e.episode_id == "EP-000000"], HORIZON)
    assert [(s.state, s.start, s.end, s.box) for s in a.segments] == [
        ("triage", 5.0, 10.0, None),
        ("assessment", 10.0, 30.0, 1),
        ("waiting_tests", 30.0, 42.0, None),
        ("waiting_box", 42.0, 70.0, None),
        ("reassessment", 70.0, 80.0, 1),
    ]


def test_los_tramos_de_a_marcan_la_sala_entre_sus_dos_boxes(room):
    # Tarea 4.8a: la sala se distingue con results_room, no con un estado nuevo. Es
    # verdadero de box_released (30) al siguiente box_assigned (70): la espera de los
    # resultados y la de box a la vuelta, no la primera espera de box de B.
    from edsim.runs.episodes import episode_segments

    a = episode_segments([e for e in room if e.episode_id == "EP-000000"], HORIZON)
    assert [(s.state, s.start, s.end, s.box, s.results_room) for s in a.segments] == [
        ("triage", 5.0, 10.0, None, False),
        ("assessment", 10.0, 30.0, 1, False),
        ("waiting_tests", 30.0, 42.0, None, True),
        ("waiting_box", 42.0, 70.0, None, True),
        ("reassessment", 70.0, 80.0, 1, False),
    ]
    b = episode_segments([e for e in room if e.episode_id == "EP-000001"], HORIZON)
    assert ("waiting_box", 11.0, 30.0, None, False) in [
        (s.state, s.start, s.end, s.box, s.results_room) for s in b.segments
    ]


def test_el_replay_marca_al_paciente_de_la_sala(room):
    from edsim.runs.replay import _empty, _fold

    def view(t):
        return {p.episode_id: p for p in _fold(_empty(), room, t).patients}

    at_35, at_50, at_75 = view(35.0), view(50.0), view(75.0)
    a = "EP-000000"
    assert (at_35[a].state, at_35[a].box, at_35[a].results_room) == ("waiting_tests", None, True)
    assert (at_50[a].state, at_50[a].box, at_50[a].results_room) == ("waiting_box", None, True)
    assert (at_75[a].state, at_75[a].box, at_75[a].results_room) == ("reassessment", 1, False)
    # B en su box y C en su primera espera de box: fuera de la sala.
    assert (at_35["EP-000001"].state, at_35["EP-000001"].results_room) == ("assessment", False)
    assert (at_35["EP-000002"].state, at_35["EP-000002"].results_room) == ("waiting_box", False)


# --- El motor -------------------------------------------------------------------------


@pytest.fixture(scope="module")
def profiles():
    from clinical_factory import example_profiles

    return example_profiles()


@pytest.fixture(scope="module")
def room_center():
    return dataclasses.replace(load_center(DATA / "centro_sala_ejemplo.toml"), boxes=1)


def run_hand(center, patients, days=1):
    """El motor con pacientes a mano, uno por instante de llegada, y su log de la versión 3."""
    from clinical_factory import clinical_log

    from edsim.arrivals.thinning import ArrivalRecord
    from edsim.engine.engine import run_engine

    log, sink = clinical_log()
    arrivals = [ArrivalRecord(k, t) for k, t in enumerate(patients)]
    draws = dict(enumerate(patients.values()))
    run_engine(center, arrivals, lambda a: draws[a.arrival_id], log, days)
    return sink.events


def test_el_motor_escribe_el_escenario_a_mano(room, room_center, profiles):
    # El log del motor es, evento a evento, el escrito a mano (hasta la salida de C).
    from clinical_factory import room_patients

    from edsim.engine.invariants import check_invariants

    events = run_hand(room_center, room_patients(profiles))

    assert events[: len(room)] == room
    assert all(e.event_type == "staffing_changed" for e in events[len(room) :])
    assert check_invariants(events, room_center) == []


def released(events):
    return [e.episode_id for e in events if e.event_type == "box_released"]


@pytest.mark.parametrize(
    ("level", "true_level", "tests", "leaves"),
    [
        (3, 3, True, False),  # nivel 3 con pruebas: se queda en el box
        (4, 3, True, True),  # infratriado: decide el asignado (4), sale
        (3, 4, True, False),  # sobretriado: decide el asignado (3), se queda
        (4, 4, False, False),  # nivel 4 sin pruebas: no hay ronda, se queda hasta salir
        (5, 5, True, True),
    ],
)
def test_quien_deja_el_box_lo_decide_el_nivel_asignado(
    room_center, profiles, level, true_level, tests, leaves
):
    from clinical_factory import hand_patient, ordered_of

    patient = hand_patient(
        profiles,
        level=level,
        true_level=true_level,
        ordered=ordered_of("ecg") if tests else (False,) * 4,
    )
    events = run_hand(room_center, {5.0: patient})
    own = [e.event_type for e in events if e.episode_id == "EP-000000"]

    assert released(events) == (["EP-000000"] if leaves else [])
    assert own.count("box_assigned") == (2 if leaves else 1)
    assert own[-1] == "patient_departed"


def test_el_provisional_ignora_la_sala(room_center):
    # Un nivel 4 con pruebas del modelo provisional, con [4, 5]: no deja el box, y el log
    # es el mismo que sin sala.
    from edsim.arrivals.thinning import ArrivalRecord
    from edsim.engine.engine import run_engine
    from edsim.engine.events import EventLog
    from edsim.engine.scenarios import hand_draws

    def run(center):
        sink = MemorySink()
        log = EventLog("p", date(2026, 1, 5), sink)
        draws = hand_draws(4, 5.0, 20.0, needs_tests=True)
        run_engine(center, [ArrivalRecord(0, 5.0)], lambda a: draws, log, 1)
        return sink.events

    with_room = run(room_center)
    assert released(with_room) == []
    assert with_room == run(dataclasses.replace(room_center, results_wait_outside=()))
    assert [e.event_type for e in with_room].count("box_assigned") == 1


def test_huella_del_provisional_con_la_sala(tmp_path):
    # La huella del log provisional de test_engine.py, también con espera_resultados_fuera:
    # el provisional no cambia ni un bit.
    import hashlib

    from test_engine import FINGERPRINT, SEED

    from edsim.engine.events import JsonlSink

    center = load_center(DATA / "centro_sala_ejemplo.toml")
    assert center.results_wait_outside == (4, 5)
    sink_path = tmp_path / "eventos.jsonl"
    with JsonlSink(sink_path) as sink:
        simulate_ed(center, load_profile(DATA / "llegadas_ejemplo.toml"), 3, SEED, sink=sink)
    assert hashlib.sha256(sink_path.read_bytes()).hexdigest() == FINGERPRINT


def simulate(center, profiles, days=3, seed=2026):
    sink = MemorySink()
    result = simulate_ed(
        center,
        load_profile(DATA / "llegadas_ejemplo.toml"),
        days,
        seed,
        sink=sink,
        profiles=profiles,
    )
    return sink.events, result


def test_numeros_comunes_con_y_sin_sala_y_con_otra_plantilla(profiles):
    # Ningún sorteo del paciente cambia: el ground truth es el mismo con la sala, sin ella
    # y con otra plantilla; el log sí cambia (el flujo).
    sala = load_center(DATA / "centro_sala_ejemplo.toml")
    events, base = simulate(sala, profiles)
    others = [
        dataclasses.replace(sala, results_wait_outside=()),
        dataclasses.replace(sala, doctors=(8, 8, 5), boxes=25),
    ]
    assert released(events)
    for other in others:
        other_events, result = simulate(other, profiles)
        assert result.ground_truth == base.ground_truth
        assert other_events != events


def test_una_copia_sin_la_clave_da_el_log_de_antes(tmp_path, profiles):
    # Reproducibilidad: el centro de la sala sin la línea de la clave (como la copia de una
    # ejecución anterior a la 4.6a) da el log de centro_ejemplo.toml, sin box_released.
    text = (DATA / "centro_sala_ejemplo.toml").read_text(encoding="utf-8")
    copy = tmp_path / "centro.toml"
    copy.write_text(text.replace("espera_resultados_fuera = [4, 5]\n", ""), encoding="utf-8")
    events, _ = simulate(load_center(copy), profiles)

    assert load_center(copy).results_wait_outside == ()
    assert events == simulate(load_center(DATA / "centro_ejemplo.toml"), profiles)[0]
    assert released(events) == []


def box_waits_by_hand(events, horizon):
    """La espera de box de cada episodio, recortada en el horizonte, por otro camino.

    Espera box desde triage_completed, desde patient_displaced y, si dejó el box por la
    sala, desde su test_resulted; hasta el box_assigned siguiente o el horizonte.
    """
    since, room, total = {}, set(), {}
    for e in events:
        ep, kind = e.episode_id, e.event_type
        if kind in ("triage_completed", "patient_displaced") or (
            kind == "test_resulted" and ep in room
        ):
            since[ep] = e.sim_time
            room.discard(ep)
        elif kind == "box_released":
            room.add(ep)
        elif kind == "box_assigned" and ep in since:
            total[ep] = total.get(ep, 0.0) + e.sim_time - since.pop(ep)
    for ep, start in since.items():
        total[ep] = total.get(ep, 0.0) + horizon - start
    return total


def test_catorce_dias_con_la_sala():
    # config/ (espera_resultados_fuera = [4, 5]), 14 días con 2 de calentamiento: cero
    # violaciones, utilización exacta y la cola de box contada por dos caminos.
    from edsim.engine.analysis import analyze_run
    from edsim.engine.invariants import check_invariants
    from edsim.profiles.config import load_profiles

    config = Path(__file__).resolve().parents[1] / "config"
    center, profiles = load_center(config / "centro.toml"), load_profiles(config / "perfiles.toml")
    sink = MemorySink()
    result = simulate_ed(
        center,
        load_profile(config / "llegadas.toml"),
        14,
        2026,
        sink=sink,
        warmup_days=2,
        profiles=profiles,
    )
    events, horizon = sink.events, 14 * 1440.0
    assert center.results_wait_outside == (4, 5)
    assert len(released(events)) > 1000
    assert (
        check_invariants(
            events,
            center,
            ground_truth=result.ground_truth,
            inside=result.inside,
            profiles=profiles,
        )
        == []
    )

    run = analyze_run(events, center, 14, 2)
    for identity in run.utilization:
        assert identity.relative_error < 1e-9, identity.pool
    by_hand = box_waits_by_hand(events, horizon)
    assert run.curves.area("waiting_box", 0, horizon) == pytest.approx(
        sum(by_hand.values()), rel=1e-12
    )
    departed = [r for r in run.table if r.departure is not None]
    assert all(
        r.box_wait == pytest.approx(by_hand.get(r.episode_id, 0.0), abs=1e-9) for r in departed
    )
    assert sum(r.results_box_wait > 0 for r in departed) > 100


def test_nunca_dos_pacientes_en_el_mismo_box_en_tres_dias(profiles):
    # Con la sala, en 3 días: los tramos con box de Episodios nunca se solapan en un box.
    from edsim.runs.episodes import episode_segments

    events, _ = simulate(load_center(DATA / "centro_sala_ejemplo.toml"), profiles)
    assert released(events)
    by_episode = {}
    for e in events:
        if e.episode_id is not None:
            by_episode.setdefault(e.episode_id, []).append(e)
    spans = {}
    for own in by_episode.values():
        for s in episode_segments(own, 3 * 1440.0).segments:
            if s.box is not None:
                spans.setdefault(s.box, []).append((s.start, s.end))
    for box, intervals in spans.items():
        intervals.sort()
        assert all(a[1] <= b[0] for a, b in itertools.pairwise(intervals)), box
