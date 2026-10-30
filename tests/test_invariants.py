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
    assert list(CHECKS) == [
        "conservation",
        "time",
        "transitions",
        "capacity",
        "nobody_jumps_the_queue",
        "displacement",
    ]


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
    # Cortar la valoración es válido, pero solo si le sigue patient_displaced: aquí le
    # sigue test_ordered, y la violación está en ese evento.
    rows = replace_payload(journey(0, 0.0), 6, interrumpida=True)
    assert rows[6][2] == "assessment_ended"

    (v,) = violations(build(rows), center, "transitions")

    assert v.event_id == build(rows)[7].event_id
    assert "test_ordered" in v.message
    assert "cut_initial" in v.message


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


# --- Desalojo en el autómata y en la capacidad --------------------------------------
#
# A (llegada 0, nivel 3) entra en el box 1 en el minuto 5. En td, L (llegada 9, nivel 1,
# triaje td-5 a td) lo desaloja y recibe el box 1 en ese instante; L se valora 20
# minutos sin pruebas y sale en td+20, y A recupera el box 1 justo después. Centro de
# un box, un médico y una enfermera: nadie se solapa.

A, L = 0, 9


def _start(t: float, tipo: str) -> tuple:
    return (t, "assessment_started", {"tipo": tipo, "pool": "medicos", "box": 1})


def _end(t: float, tipo: str, cut: bool = False) -> tuple:
    return (t, "assessment_ended", {"tipo": tipo, "interrumpida": cut})


def _displaced(t: float, by: int = L) -> tuple:
    return (t, "patient_displaced", {"box": 1, "desalojado_por": f"EP-{by:06d}"})


def _box(t: float) -> tuple:
    return (t, "box_assigned", {"box": 1})


def _out(t: float) -> list[tuple]:
    return [
        (t, "disposition_decided", {"destino": "alta"}),
        (t, "patient_departed", {"destino": "alta"}),
    ]


_PREFIX = [
    (0.0, "patient_arrived", {}),
    (0.0, "patient_registered", {}),
    (0.0, "triage_started", {}),
    (5.0, "triage_completed", {"nivel": 3}),
    _box(5.0),
]

# Recorrido de A con un desalojo en cada estado con box: (td, filas de A).
DISPLACED_STAYS = {
    "valoracion": (
        12.0,
        [_start(5, "inicial"), _end(12, "inicial", cut=True), _displaced(12), _box(32)]
        + [_start(32, "inicial"), _end(45, "inicial"), (45, "test_ordered", {})]
        + [(105, "test_resulted", {}), _start(105, "reevaluacion"), _end(115, "reevaluacion")]
        + _out(115),
    ),
    "espera_de_medico": (
        12.0,
        [_displaced(12), _box(32), _start(32, "inicial"), _end(52, "inicial")] + _out(52),
    ),
    "pruebas": (
        30.0,
        [_start(5, "inicial"), _end(25, "inicial"), (25, "test_ordered", {}), _displaced(30)]
        + [_box(50), (85, "test_resulted", {}), _start(85, "reevaluacion")]
        + [_end(95, "reevaluacion")]
        + _out(95),
    ),
    "resultado_esperando_box": (
        30.0,
        [_start(5, "inicial"), _end(25, "inicial"), (25, "test_ordered", {}), _displaced(30)]
        + [(40, "test_resulted", {}), _box(50), _start(50, "reevaluacion")]
        + [_end(60, "reevaluacion")]
        + _out(60),
    ),
    "espera_de_reevaluacion": (
        88.0,
        [_start(5, "inicial"), _end(25, "inicial"), (25, "test_ordered", {})]
        + [(85, "test_resulted", {}), _displaced(88), _box(108), _start(108, "reevaluacion")]
        + [_end(118, "reevaluacion")]
        + _out(118),
    ),
    "reevaluacion": (
        90.0,
        [_start(5, "inicial"), _end(25, "inicial"), (25, "test_ordered", {})]
        + [(85, "test_resulted", {}), _start(85, "reevaluacion")]
        + [_end(90, "reevaluacion", cut=True), _displaced(90), _box(110)]
        + [_start(110, "reevaluacion"), _end(115, "reevaluacion")]
        + _out(115),
    ),
}


def displacer(td: float, arrival_id: int = L) -> list[Row]:
    """El nivel 1: triaje de td-5 a td, box 1 en td, valoración de 20 y salida."""
    t0 = td - 5
    rows = [
        (t0, "patient_arrived", {}),
        (t0, "patient_registered", {}),
        (t0, "triage_started", {}),
        (td, "triage_completed", {"nivel": 1}),
        _box(td),
        _start(td, "inicial"),
        _end(td + 20, "inicial"),
        (td + 20, "disposition_decided", {"destino": "ingreso"}),
        (td + 20, "patient_departed", {"destino": "ingreso"}),
    ]
    return [(t, arrival_id, event_type, payload) for t, event_type, payload in rows]


def displaced_stay(stage: str) -> list[Row]:
    """Filas de A y de L ordenadas como las emitiría el motor.

    Antes de que L salga (td+20), en un mismo instante van primero las de A (el
    desalojado se procesa antes que la concesión); desde td+20, primero las de L (su
    salida libera el box que recibe A).
    """
    td, rows = DISPLACED_STAYS[stage]
    a_rows = [(t, A, event_type, payload) for t, event_type, payload in _PREFIX + rows]
    back = td + 20

    def order(row: Row) -> tuple[float, int]:
        time, arrival_id = row[0], row[1]
        first = (arrival_id == A) == (time < back)
        return (time, 0 if first else 1)

    return sorted(a_rows + displacer(td), key=order)


@pytest.fixture(scope="module")
def one_box(center) -> CenterConfig:
    return dataclasses.replace(center, boxes=1)


@pytest.mark.parametrize("stage", DISPLACED_STAYS)
def test_desalojo_en_cada_estado_con_box_es_valido(one_box, stage):
    events = build(displaced_stay(stage))
    td, _ = DISPLACED_STAYS[stage]

    displaced = [e for e in events if e.event_type == "patient_displaced"]
    assert [(e.episode_id, e.sim_time) for e in displaced] == [("EP-000000", td)]
    assert (
        check_invariants(events, one_box, ground_truth=truth((A, 0.0), (L, td - 5)), inside=0) == []
    )


@pytest.mark.parametrize("stage", DISPLACED_STAYS)
def test_desalojo_cortado_por_el_horizonte_es_valido(one_box, stage):
    rows = displaced_stay(stage)
    for k in range(1, len(rows) + 1):
        events = build(rows[:k])
        found = [
            v for v in check_invariants(events, one_box) if v.check in ("transitions", "capacity")
        ]
        assert found == [], k


def test_dos_desalojos_del_mismo_paciente(one_box):
    # A valorándose desde 5; L9 lo desaloja en 12 (le faltan 13) y sale en 32; A vuelve
    # en 32 y L8 lo desaloja en 40 (le faltan 5); L8 sale en 60 y A termina en 65.
    l9 = displacer(12.0, 9)
    l8 = displacer(40.0, 8)
    a = [(t, A, event_type, payload) for t, event_type, payload in _PREFIX]
    a += [
        (5.0, A, *_start(5, "inicial")[1:]),
        (12.0, A, *_end(12, "inicial", cut=True)[1:]),
        (12.0, A, *_displaced(12, by=9)[1:]),
    ]
    a2 = [
        (32.0, A, *_box(32)[1:]),
        (32.0, A, *_start(32, "inicial")[1:]),
        (40.0, A, *_end(40, "inicial", cut=True)[1:]),
        (40.0, A, *_displaced(40, by=8)[1:]),
    ]
    a3 = [
        (60.0, A, *_box(60)[1:]),
        (60.0, A, *_start(60, "inicial")[1:]),
        (65.0, A, *_end(65, "inicial")[1:]),
    ] + [(65.0, A, event_type, payload) for _, event_type, payload in _out(65)]
    # build ordena por instante de forma estable: en 12 y 40 van antes las filas de A
    # (el desalojado antes que la concesión); en 32 y 60, la salida del nivel 1 antes
    # que el box de A.
    events = build(a + l9 + a2 + l8 + a3)

    displaced = [e.payload["desalojado_por"] for e in events if e.event_type == "patient_displaced"]
    assert displaced == ["EP-000009", "EP-000008"]
    assert check_invariants(events, one_box) == []


def _a_rows(*rows: tuple) -> list[Row]:
    return [(t, A, event_type, payload) for t, event_type, payload in _PREFIX + list(rows)]


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        # Entre assessment_ended y test_ordered no hay yield: no cabe un desalojo.
        ((_start(5, "inicial"), _end(25, "inicial"), _displaced(25)), "'assessed'"),
        # Vuelve al box tras cortar la valoración inicial y hace la reevaluación.
        (
            (_start(5, "inicial"), _end(12, "inicial", cut=True), _displaced(12), _box(32))
            + (_start(32, "reevaluacion"),),
            "'in_box'",
        ),
        # Sin pruebas pedidas, no llega un resultado mientras espera box.
        ((_displaced(12), (20, "test_resulted", {})), "'waiting_box_initial'"),
        # Desalojado otra vez sin haber recuperado el box.
        ((_displaced(12), _displaced(20)), "'waiting_box_initial'"),
        # Reevaluación cortada que no sigue con patient_displaced.
        (
            (_start(5, "inicial"), _end(25, "inicial"), (25, "test_ordered", {}))
            + ((85, "test_resulted", {}), _start(85, "reevaluacion"))
            + (_end(90, "reevaluacion", cut=True), _box(90)),
            "'cut_reassessment'",
        ),
        # Valoración en curso sin box: tras el desalojo, assessment_started directo.
        ((_displaced(12), _start(20, "inicial")), "'waiting_box_initial'"),
    ],
    ids=[
        "sin_yield",
        "etapa_cambiada",
        "resultado_sin_pruebas",
        "doble",
        "corte_sin_desalojo",
        "sin_box",
    ],
)
def test_desalojo_fuera_del_automata(center, rows, expected):
    (v,) = violations(build(_a_rows(*rows)), center, "transitions")

    assert expected in v.message


def test_el_desalojo_libera_el_box(one_box):
    events = build(displaced_stay("valoracion"))

    assert violations(events, one_box, "capacity") == []


def test_desalojado_de_un_box_que_no_era_el_suyo(one_box):
    rows = displaced_stay("valoracion")
    index = next(i for i, r in enumerate(rows) if r[2] == "patient_displaced")
    rows = replace_payload(rows, index, box=2)
    wider = dataclasses.replace(one_box, boxes=2)

    messages = [v.message for v in violations(build(rows), wider, "capacity")]

    assert any("displaced from box 2" in m and "box 1" in m for m in messages)


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


# --- Nadie se cuela ----------------------------------------------------------------------


def stay_in_box(
    arrival_id: int, t0: float, level: int, box_time: float, box: int, start: float | None = None
) -> list[Row]:
    """Recorrido sin pruebas: triaje de t0 a t0+5, box en box_time y valoración de 20
    minutos desde start (box_time si no se da)."""
    start = box_time if start is None else start
    rows = [
        (t0, "patient_arrived", {}),
        (t0, "patient_registered", {}),
        (t0, "triage_started", {}),
        (t0 + 5, "triage_completed", {"nivel": level}),
        (box_time, "box_assigned", {"box": box}),
        (start, "assessment_started", {"tipo": "inicial", "pool": "medicos", "box": box}),
        (start + 20, "assessment_ended", {"tipo": "inicial", "interrumpida": False}),
        (start + 20, "disposition_decided", {"destino": "alta"}),
        (start + 20, "patient_departed", {"destino": "alta"}),
    ]
    return [(t, arrival_id, event_type, payload) for t, event_type, payload in rows]


@pytest.fixture(scope="module")
def roomy(center) -> CenterConfig:
    """Enfermeras y médicos de sobra: solo cuentan los boxes."""
    return dataclasses.replace(center, triage_nurses=(5, 5, 5), doctors=(5, 5, 5))


@pytest.mark.parametrize(("first", "expected"), [(1, ["EP-000001"]), (2, [])])
def test_box_para_quien_tiene_la_clave_menor(roomy, first, expected):
    # Un box, ocupado por A de 5 a 95. B (nivel 4) espera desde 15 y C (nivel 2) desde
    # 25. En 95 el box debe ir a C; si va a B, B se ha colado.
    one_box = dataclasses.replace(roomy, boxes=1)
    events = build(
        journey(0, 0.0),
        stay_in_box(1, 10.0, 4, 95.0 if first == 1 else 115.0, 1),
        stay_in_box(2, 20.0, 2, 95.0 if first == 2 else 115.0, 1),
    )

    found = violations(events, one_box, "nobody_jumps_the_queue")

    assert [v.episode_id for v in found] == expected
    if found:
        assert "box" in found[0].message and "EP-000002" in found[0].message
        assert found[0].sim_time == 95.0


def test_medico_para_quien_tiene_la_clave_menor(center):
    # Un médico, ocupado por A de 5 a 25. B (nivel 4) espera médico en el box 2 desde 6 y
    # C (nivel 2) en el box 3 desde 7. En 25 el médico va a B: se ha colado.
    small = dataclasses.replace(center, boxes=3, triage_nurses=(5, 5, 5))
    events = build(
        journey(0, 0.0, tests=False),
        stay_in_box(1, 1.0, 4, 6.0, 2, start=25.0),
        stay_in_box(2, 2.0, 2, 7.0, 3, start=45.0),
    )

    (v,) = violations(events, small, "nobody_jumps_the_queue")

    assert v.episode_id == "EP-000001"
    assert v.sim_time == 25.0
    assert "doctor" in v.message and "EP-000002" in v.message


def test_espera_que_empieza_en_el_mismo_instante_no_cuenta(center):
    # El caso del desalojo con médicos escasos: en 25 A suelta el médico y SimPy se lo da
    # a B (nivel 4, esperando desde 6). En ese mismo instante C (nivel 2) recibe un box y
    # empieza a esperar médico, y su box_assigned sale antes que el assessment_started de
    # B. B no se ha colado: el médico era suyo antes de que C lo pidiera.
    small = dataclasses.replace(center, boxes=3, triage_nurses=(5, 5, 5))
    c = stay_in_box(2, 20.0, 2, 25.0, 3, start=45.0)
    # Hasta su box_assigned, C va antes que B en el fichero; después, detrás.
    events = build(
        journey(0, 0.0, tests=False), c[:5], stay_in_box(1, 1.0, 4, 6.0, 2, start=25.0), c[5:]
    )
    order = [(e.episode_id, e.event_type) for e in events if e.sim_time == 25.0]
    assert order.index(("EP-000002", "box_assigned")) < order.index(
        ("EP-000001", "assessment_started")
    )

    assert violations(events, small, "nobody_jumps_the_queue") == []


def test_quien_vuelve_tras_un_desalojo_espera_con_su_clave(roomy):
    # A (nivel 3, llegada 0) es desalojado en 12 y espera box desde ahí. B (nivel 3,
    # llegada 20) termina el triaje en 25. Cuando L sale en 32, el box es de A, que llegó
    # antes aunque pidiera de nuevo después; aquí va a B (32-52) y A vuelve en 53.
    one_box = dataclasses.replace(roomy, boxes=1)
    rows = [
        (r[0] + 21, *r[1:]) if r[1] == A and r[0] >= 32 else r
        for r in displaced_stay("espera_de_medico")
    ]
    events = build(rows, stay_in_box(1, 20.0, 3, 32.0, 1))

    (v,) = violations(events, one_box, "nobody_jumps_the_queue")

    assert v.episode_id == "EP-000001"
    assert v.sim_time == 32.0
    assert "EP-000000" in v.message


# --- Desalojo ------------------------------------------------------------------------------


def _set(rows: list[Row], arrival_id: int, event_type: str, **payload: object) -> list[Row]:
    index = next(i for i, r in enumerate(rows) if r[1] == arrival_id and r[2] == event_type)
    return replace_payload(rows, index, **payload)


def test_desalojo_valido(one_box):
    assert violations(build(displaced_stay("valoracion")), one_box, "displacement") == []


def test_desaloja_quien_no_es_nivel_1(one_box):
    rows = _set(displaced_stay("valoracion"), L, "triage_completed", nivel=2)

    messages = [v.message for v in violations(build(rows), one_box, "displacement")]

    assert any("EP-000009" in m and "level 2" in m for m in messages)


def test_desalojado_de_nivel_1(one_box):
    rows = _set(displaced_stay("valoracion"), A, "triage_completed", nivel=1)

    messages = [v.message for v in violations(build(rows), one_box, "displacement")]

    assert any("EP-000000" in m and "level 1" in m for m in messages)


def test_desalojado_de_otro_box(one_box):
    rows = _set(displaced_stay("valoracion"), A, "patient_displaced", box=2)
    two_boxes = dataclasses.replace(one_box, boxes=2)

    messages = [v.message for v in violations(build(rows), two_boxes, "displacement")]

    assert any("box 2" in m and "box 1" in m for m in messages)


def test_el_nivel_1_recibe_otro_box(one_box):
    rows = displaced_stay("valoracion")
    index = next(i for i, r in enumerate(rows) if r[1] == L and r[2] == "box_assigned")
    rows = replace_payload(rows, index, box=2)
    rows = _set(rows, L, "assessment_started", box=2)
    two_boxes = dataclasses.replace(one_box, boxes=2)

    (v,) = violations(build(rows), two_boxes, "displacement")

    assert v.episode_id == "EP-000009"
    assert "box 2" in v.message and "box 1" in v.message


def test_el_nivel_1_recibe_el_box_en_otro_instante(one_box):
    rows = [
        (r[0] + 1, *r[1:]) if r[1] == L and r[2] in ("box_assigned", "assessment_started") else r
        for r in displaced_stay("valoracion")
    ]

    found = violations(build(rows), one_box, "displacement")

    # Además, en 12 L espera con el box libre.
    (late,) = [v for v in found if v.sim_time == 13.0]
    assert late.episode_id == "EP-000009"
    assert "12" in late.message


def test_el_nivel_1_no_recibe_el_box(one_box):
    rows = [
        r
        for r in displaced_stay("valoracion")
        if not (r[1] == L and r[0] >= 12 and r[2] != "triage_completed")
    ]

    found = violations(build(rows), one_box, "displacement")

    assert any(v.event_id is None and "EP-000009" in v.message for v in found)


def test_nivel_1_esperando_con_un_nivel_mayor_en_un_box(roomy):
    # Un box con A (nivel 3) de 5 a 95; L (nivel 1) termina el triaje en 10 y espera sin
    # desalojar a nadie hasta 95.
    one_box = dataclasses.replace(roomy, boxes=1)
    events = build(journey(0, 0.0), stay_in_box(9, 5.0, 1, 95.0, 1))

    found = violations(events, one_box, "displacement")

    assert [v.sim_time for v in found] == [10.0]
    assert "EP-000009" in found[0].message and "level 3" in found[0].message


def test_nivel_1_esperando_con_un_box_libre(roomy):
    # Dos boxes: A (nivel 1) en el 1; L (nivel 1) espera de 10 a 25 con el 2 libre.
    two_boxes = dataclasses.replace(roomy, boxes=2)
    events = build(stay_in_box(0, 0.0, 1, 5.0, 1), stay_in_box(9, 5.0, 1, 25.0, 2))

    found = violations(events, two_boxes, "displacement")

    assert [v.sim_time for v in found] == [10.0]
    assert "free" in found[0].message


def test_nivel_1_esperando_con_todos_los_boxes_de_nivel_1(roomy):
    one_box = dataclasses.replace(roomy, boxes=1)
    events = build(stay_in_box(0, 0.0, 1, 5.0, 1), stay_in_box(9, 5.0, 1, 25.0, 1))

    assert violations(events, one_box, "displacement") == []
