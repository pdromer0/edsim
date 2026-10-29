"""Invariantes del log: cero violaciones en logs válidos y cada una detecta su log roto.

Los logs se construyen a mano con EventLog y MemorySink. Un recorrido completo con
pruebas tiene 13 eventos; los instantes son los del escenario a mano de la tarea 3.3
(triaje 5, valoración 20, pruebas 60 y reevaluación 10 minutos).
"""

import dataclasses
from datetime import date
from pathlib import Path

import pytest

from edsim.arrivals.thinning import ArrivalRecord
from edsim.engine.center import CenterConfig, load_center
from edsim.engine.clinical import PatientDraws
from edsim.engine.events import Event, EventLog, MemorySink
from edsim.engine.ground_truth import EpisodeTruth, GroundTruth
from edsim.engine.invariants import CHECKS, TRANSITIONS, Violation, check_invariants

EXAMPLE = Path(__file__).parent / "data" / "centro_ejemplo.toml"
START = date(2026, 1, 5)

DRAWS = PatientDraws(
    level=3,
    triage_time=5.0,
    assessment_time=20.0,
    reassessment_time=10.0,
    needs_tests=True,
    test_turnaround=60.0,
    admitted=False,
)

Row = tuple[float, int, str, dict]


@pytest.fixture(scope="module")
def center() -> CenterConfig:
    """Centro pequeño: dos boxes, un médico y una enfermera, para provocar los fallos."""
    return dataclasses.replace(
        load_center(EXAMPLE), boxes=2, doctors=(1, 1, 1), triage_nurses=(1, 1, 1)
    )


def journey(
    arrival_id: int, t0: float, *, box: int = 1, tests: bool = True, destino: str = "alta"
) -> list[Row]:
    """Filas (instante, llegada, tipo, payload) de un recorrido completo y válido."""
    t = t0
    rows = [
        (t, "patient_arrived", {}),
        (t, "patient_registered", {}),
        (t, "triage_started", {}),
    ]
    t += 5
    rows += [
        (t, "triage_completed", {"nivel": 3}),
        (t, "box_assigned", {"box": box}),
        (t, "assessment_started", {"tipo": "inicial", "pool": "medicos", "box": box}),
    ]
    t += 20
    rows.append((t, "assessment_ended", {"tipo": "inicial", "interrumpida": False}))
    if tests:
        rows.append((t, "test_ordered", {}))
        t += 60
        rows += [
            (t, "test_resulted", {}),
            (t, "assessment_started", {"tipo": "reevaluacion", "pool": "medicos", "box": box}),
        ]
        t += 10
        rows.append((t, "assessment_ended", {"tipo": "reevaluacion", "interrumpida": False}))
    rows += [
        (t, "disposition_decided", {"destino": destino}),
        (t, "patient_departed", {"destino": destino}),
    ]
    return [(time, arrival_id, event_type, payload) for time, event_type, payload in rows]


def build(*journeys: list[Row]) -> list[Event]:
    """Emite las filas ordenadas por instante; a igualdad, en el orden en que se dan."""
    rows = sorted((row for j in journeys for row in j), key=lambda row: row[0])
    sink = MemorySink()
    log = EventLog("rtest", START, sink)
    for time, arrival_id, event_type, payload in rows:
        log.emit(event_type, time, arrival_id=arrival_id, **payload)
    return sink.events


def truth(*arrivals: tuple[int, float]) -> GroundTruth:
    episodes = tuple(
        EpisodeTruth.from_draws(ArrivalRecord(arrival_id, time), DRAWS)
        for arrival_id, time in arrivals
    )
    return GroundTruth(episodes=episodes, days=())


def violations(events: list[Event], center: CenterConfig, check: str, **kwargs) -> list[Violation]:
    return [v for v in check_invariants(events, center, **kwargs) if v.check == check]


def two_patients() -> list[Event]:
    """A con pruebas en el box 1 y B sin pruebas en el box 2, sin solaparse en médico
    ni en enfermera: A triaje 0-5, médico 5-25 y 85-95; B triaje 30-35, médico 35-55."""
    return build(journey(0, 0.0, box=1), journey(1, 30.0, box=2, tests=False))


# --- API -----------------------------------------------------------------------


def test_comprobaciones_registradas():
    assert list(CHECKS) == ["conservation", "time", "transitions", "capacity"]


def test_ground_truth_desde_los_sorteos():
    episode = EpisodeTruth.from_draws(ArrivalRecord(137, 739.02), DRAWS)

    assert episode.episode_id == "EP-000137"
    assert episode.arrival_id == 137
    assert episode.arrival_time == 739.02
    for field in dataclasses.fields(PatientDraws):
        assert getattr(episode, field.name) == getattr(DRAWS, field.name)


def test_violacion_apunta_al_evento(center):
    events = build(journey(0, 0.0), [(200.0, 0, "patient_arrived", {})])

    (v,) = violations(events, center, "conservation")

    assert v.event_id == events[-1].event_id
    assert v.episode_id == "EP-000000"
    assert v.sim_time == 200.0


# --- Logs válidos ----------------------------------------------------------------


def test_log_valido_sin_violaciones(center):
    events = two_patients()

    assert len(events) == 13 + 9
    assert check_invariants(events, center, ground_truth=truth((0, 0.0), (1, 30.0)), inside=0) == []


def test_admite_un_iterador(center):
    assert check_invariants(iter(two_patients()), center) == []


@pytest.mark.parametrize("tests", [True, False])
def test_recorrido_cortado_por_el_horizonte_es_valido(center, tests):
    full = journey(0, 0.0, tests=tests)
    for k in range(1, len(full) + 1):
        inside = 1 if k < len(full) else 0
        events = build(full[:k])
        assert (
            check_invariants(events, center, ground_truth=truth((0, 0.0)), inside=inside) == []
        ), k


def test_automata_sin_estados_inalcanzables():
    # Cada estado destino es también un estado de la tabla, y todos salvo el
    # inicial son destino de alguna transición.
    targets = {state for edges in TRANSITIONS.values() for state in edges.values()}
    assert targets <= TRANSITIONS.keys()
    assert TRANSITIONS.keys() - targets == {"start"}


# --- Conservación ----------------------------------------------------------------


def test_salida_sin_llegada(center):
    events = build([(0.0, 0, "patient_departed", {"destino": "alta"})])

    messages = [v.message for v in violations(events, center, "conservation")]

    assert any("without patient_arrived" in m for m in messages)
    assert any("census" in m for m in messages)


def test_llegada_repetida(center):
    events = build(journey(0, 0.0), [(200.0, 0, "patient_arrived", {})])

    (v,) = violations(events, center, "conservation")

    assert "repeated patient_arrived" in v.message


def test_salida_repetida(center):
    events = build(journey(0, 0.0), [(200.0, 0, "patient_departed", {"destino": "alta"})])

    messages = [v.message for v in violations(events, center, "conservation")]

    assert any("repeated patient_departed" in m for m in messages)


def test_episodio_del_ground_truth_sin_llegada_en_el_log(center):
    events = build(journey(0, 0.0))

    (v,) = violations(events, center, "conservation", ground_truth=truth((0, 0.0), (1, 30.0)))

    assert v.episode_id == "EP-000001"
    assert "0 patient_arrived" in v.message


def test_llegada_que_no_esta_en_el_ground_truth(center):
    events = two_patients()

    (v,) = violations(events, center, "conservation", ground_truth=truth((0, 0.0)))

    assert v.episode_id == "EP-000001"
    assert "not in the ground truth" in v.message


def test_llegada_repetida_frente_al_ground_truth(center):
    events = build(journey(0, 0.0), [(200.0, 0, "patient_arrived", {})])

    messages = [
        v.message for v in violations(events, center, "conservation", ground_truth=truth((0, 0.0)))
    ]

    assert any("2 patient_arrived" in m for m in messages)


@pytest.mark.parametrize("inside", [1, 2])
def test_dentro_distinto_de_los_procesos_vivos(center, inside):
    events = two_patients()  # los dos han salido

    (v,) = violations(events, center, "conservation", inside=inside)

    assert "0 patients inside" in v.message
    assert f"{inside} patient processes" in v.message


def test_dentro_al_final_cuenta_los_cortados(center):
    events = build(journey(0, 0.0), journey(1, 30.0, box=2, tests=False)[:5])

    assert violations(events, center, "conservation", inside=1) == []
    assert len(violations(events, center, "conservation", inside=0)) == 1


# --- Tiempo ----------------------------------------------------------------------


def test_tiempo_que_decrece(center):
    events = build(journey(0, 0.0))
    # EventLog no deja emitir hacia atrás: se rompe el log después.
    assert events[5].event_type == "assessment_started" and events[5].sim_time == 5.0
    events[5] = dataclasses.replace(events[5], sim_time=1.0)

    (v,) = violations(events, center, "time")

    assert v.event_id == events[5].event_id
    assert "decreased" in v.message


def test_evento_antes_de_la_llegada(center):
    rows = journey(1, 10.0, box=2, tests=False)
    # El registro del paciente 1 aparece en el minuto 3, antes de su llegada en el 10.
    rows[1] = (3.0, *rows[1][1:])
    events = build(journey(0, 0.0), rows)

    (v,) = violations(events, center, "time")

    assert v.episode_id == "EP-000001"
    assert v.sim_time == 3.0
    assert "before its patient_arrived" in v.message


def test_evento_con_tiempo_anterior_a_la_llegada(center):
    events = build(journey(0, 10.0))
    # El registro va detrás de la llegada en el fichero, pero en el minuto 9.
    events[1] = dataclasses.replace(events[1], sim_time=9.0)

    messages = [v.message for v in violations(events, center, "time")]

    assert len(messages) == 2
    assert any("decreased" in m for m in messages)
    assert any("before the arrival" in m for m in messages)


# --- Transiciones ------------------------------------------------------------------


def replace_payload(rows: list[Row], index: int, **payload: object) -> list[Row]:
    time, arrival_id, event_type, old = rows[index]
    rows = list(rows)
    rows[index] = (time, arrival_id, event_type, {**old, **payload})
    return rows


def test_box_antes_del_triaje(center):
    # Tras la primera transición inválida, el episodio deja de comprobarse:
    # una violación, no una cascada.
    rows = [r for r in journey(0, 0.0) if not r[2].startswith("triage")]

    (v,) = violations(build(rows), center, "transitions")

    assert "box_assigned" in v.message
    assert "registered" in v.message


def test_valoracion_interrumpida_sin_desalojo(center):
    rows = replace_payload(journey(0, 0.0), 6, interrumpida=True)
    assert rows[6][2] == "assessment_ended"

    (v,) = violations(build(rows), center, "transitions")

    assert v.sim_time == 25.0
    assert "True" in v.message


def test_reevaluacion_sin_pruebas(center):
    rows = journey(0, 0.0)
    del rows[7:9]  # sin test_ordered ni test_resulted

    (v,) = violations(build(rows), center, "transitions")

    assert "reevaluacion" in v.message


def test_evento_despues_de_la_salida(center):
    events = build(journey(0, 0.0), [(200.0, 0, "test_ordered", {})])

    (v,) = violations(events, center, "transitions")

    assert "departed" in v.message


def test_destino_de_la_salida_distinto_de_la_decision(center):
    rows = replace_payload(journey(0, 0.0), 12, destino="ingreso")
    assert rows[12][2] == "patient_departed"

    (v,) = violations(build(rows), center, "transitions")

    assert "ingreso" in v.message and "alta" in v.message


# --- Capacidad ---------------------------------------------------------------------


def test_box_ocupado_por_dos_pacientes(center):
    # B recibe el box 1 en el minuto 35, con A dentro hasta el 95.
    events = build(journey(0, 0.0, box=1), journey(1, 30.0, box=1, tests=False))

    (v,) = violations(events, center, "capacity")

    assert v.episode_id == "EP-000001"
    assert "box 1" in v.message and "EP-000000" in v.message


def test_box_reutilizado_tras_la_salida(center):
    events = build(journey(0, 0.0, box=1), journey(1, 100.0, box=1))

    assert violations(events, center, "capacity") == []


def test_box_fuera_de_rango(center):
    events = build(journey(0, 0.0, box=3))

    messages = [v.message for v in violations(events, center, "capacity")]

    assert any("out of range" in m for m in messages)


def test_dos_boxes_para_el_mismo_paciente(center):
    rows = journey(0, 0.0, box=1)
    rows.insert(5, (5.0, 0, "box_assigned", {"box": 2}))

    messages = [v.message for v in violations(build(rows), center, "capacity")]

    assert any("already in box 1" in m for m in messages)


def test_valoracion_en_otro_box(center):
    rows = replace_payload(journey(0, 0.0, box=1), 5, box=2)

    (v,) = violations(build(rows), center, "capacity")

    assert "box 2" in v.message and "box 1" in v.message


def test_medicos_por_encima_de_la_capacidad(center):
    # A con médico de 5 a 25; B llega en el 10 y empieza valoración en el 15.
    events = build(journey(0, 0.0, box=1), journey(1, 10.0, box=2, tests=False))

    (v,) = violations(events, center, "capacity")

    assert v.episode_id == "EP-000001"
    assert v.sim_time == 15.0
    assert "doctors" in v.message


def test_enfermeras_por_encima_de_la_capacidad(center):
    # A en triaje de 0 a 5; B empieza su triaje en el 2.
    events = build(journey(0, 0.0, box=1), journey(1, 2.0, box=2, tests=False))

    nurses = [v for v in violations(events, center, "capacity") if "nurses" in v.message]

    assert len(nurses) == 1
    assert nurses[0].sim_time == 2.0


def test_capacidad_maxima_de_la_plantilla(center):
    # Con dos médicos en algún turno, dos valoraciones a la vez caben.
    wider = dataclasses.replace(center, doctors=(2, 1, 1))
    events = build(journey(0, 0.0, box=1), journey(1, 10.0, box=2, tests=False))

    assert violations(events, wider, "capacity") == []
