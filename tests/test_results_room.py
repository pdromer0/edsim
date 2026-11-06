"""Sala de resultados (decisión candidata 45, tarea 4.6a).

El escenario a mano de ``clinical_factory.room_log``: un box, tres niveles 4. A deja el
box en 30 al pedir un ECG, B lo recibe en 30, los resultados de A llegan en 42 y A vuelve
al box en 70 por delante de C, que espera desde 25 pero llegó después. Los valores a mano
de este fichero salen de esos instantes, no de las funciones que se prueban.
"""

import dataclasses
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
