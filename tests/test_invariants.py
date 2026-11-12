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
        (t, "triage_started", {"circuito": "enfermeria"}),
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


STAFF = (1, 1)
"""Plantilla del centro pequeño: (enfermeras, médicos)."""


def staffing_rows(staff: tuple[int, int]) -> list[Row]:
    """Los dos staffing_changed del minuto 0, como los emite el motor."""
    nurses, doctors = staff
    return [
        (
            0.0,
            None,
            "staffing_changed",
            {"recurso": "enfermeria_triaje", "anterior": 0, "nueva": nurses},
        ),
        (0.0, None, "staffing_changed", {"recurso": "medicos", "anterior": 0, "nueva": doctors}),
    ]


def build(*journeys: list[Row], staff: tuple[int, int] | None = STAFF) -> list[Event]:
    """Emite las filas ordenadas por instante; a igualdad, en el orden en que se dan.

    Antes van los staffing_changed del minuto 0 con la plantilla ``staff``
    (enfermeras, médicos), salvo con ``staff=None``.
    """
    first = [] if staff is None else staffing_rows(staff)
    rows = sorted((row for j in [first, *journeys] for row in j), key=lambda row: row[0])
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
        "door",
        "schema_version",
        "clinical",
        "results_wait",
        "abandonment",
        "outcome",
    ]


def test_ground_truth_desde_los_sorteos():
    episode = EpisodeTruth.from_draws(ArrivalRecord(137, 739.02), DRAWS)

    assert episode.episode_id == "EP-000137"
    assert episode.arrival_id == 137
    assert episode.arrival_time == 739.02
    # Un paciente provisional: sin desenlace en los sorteos ni en la verdad. Con el hito 5,
    # la verdad guarda lo sorteado (OutcomeDraws.truth), no lo que lee el motor (5.3).
    assert DRAWS.outcome is None and episode.outcome is None
    for field in dataclasses.fields(PatientDraws):
        if field.name != "outcome":
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

    assert len(events) == 2 + 13 + 9  # staffing_changed y dos recorridos
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
    assert events[7].event_type == "assessment_started" and events[7].sim_time == 5.0
    events[7] = dataclasses.replace(events[7], sim_time=1.0)

    (v,) = violations(events, center, "time")

    assert v.event_id == events[7].event_id
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
    assert events[3].event_type == "patient_registered"
    events[3] = dataclasses.replace(events[3], sim_time=9.0)

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

    assert v.event_id == build(rows)[9].event_id  # 2 staffing_changed delante
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
    (0.0, "triage_started", {"circuito": "enfermeria"}),
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
    """El nivel 1: llega en td y se clasifica en la puerta, box 1 en td, valoración de 20
    y salida. Desde la tarea 4.1 un nivel 1 no pasa por la enfermera (invariante door)."""
    rows = [
        (td, "patient_arrived", {}),
        (td, "patient_registered", {}),
        (td, "triage_started", {"circuito": "puerta"}),
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


def test_medicos_por_encima_de_la_plantilla(center):
    # Un médico de plantilla: A con médico de 5 a 25; B empieza valoración en el 15.
    events = build(journey(0, 0.0, box=1), journey(1, 10.0, box=2, tests=False))

    (v,) = violations(events, center, "capacity")

    assert v.episode_id == "EP-000001"
    assert v.sim_time == 15.0
    assert "1 doctors busy" in v.message and "staff in force 1" in v.message


def test_enfermeras_por_encima_de_la_plantilla(center):
    # A en triaje de 0 a 5; B empieza su triaje en el 2.
    events = build(journey(0, 0.0, box=1), journey(1, 2.0, box=2, tests=False))

    nurses = [v for v in violations(events, center, "capacity") if "nurses" in v.message]

    assert len(nurses) == 1
    assert nurses[0].sim_time == 2.0


def door_journey(arrival_id: int, t0: float, *, box: int) -> list[Row]:
    """Un nivel 1 clasificado en la puerta en t0: box y médico al llegar, 20 minutos."""
    rows = [
        (t0, "patient_arrived", {}),
        (t0, "patient_registered", {}),
        (t0, "triage_started", {"circuito": "puerta"}),
        (t0, "triage_completed", {"nivel": 1}),
        (t0, "box_assigned", {"box": box}),
        (t0, "assessment_started", {"tipo": "inicial", "pool": "medicos", "box": box}),
        (t0 + 20, "assessment_ended", {"tipo": "inicial", "interrumpida": False}),
        (t0 + 20, "disposition_decided", {"destino": "ingreso"}),
        (t0 + 20, "patient_departed", {"destino": "ingreso"}),
    ]
    return [(time, arrival_id, event_type, payload) for time, event_type, payload in rows]


def test_el_triaje_de_puerta_no_ocupa_enfermera(center):
    # Una enfermera, triando a A de 0 a 5. L (nivel 1) se clasifica en la puerta en 2:
    # no cuenta como enfermera. Dos médicos: L 2-22 y A 5-25.
    wider = dataclasses.replace(center, doctors=(2, 2, 2))
    events = build(journey(0, 0.0, box=1, tests=False), door_journey(1, 2.0, box=2), staff=(1, 2))

    assert check_invariants(events, wider) == []


def test_el_triaje_de_puerta_antes_de_la_plantilla_no_cuenta(center):
    # Sin staffing_changed de enfermería: un triaje de enfermería lo señala, uno de puerta no.
    events = build(door_journey(0, 2.0, box=1), staff=None)
    messages = [v.message for v in violations(events, center, "capacity")]
    assert not any("enfermeria_triaje" in m for m in messages)


def test_dos_valoraciones_caben_con_plantilla_2(center):
    wider = dataclasses.replace(center, doctors=(2, 1, 1))
    events = build(journey(0, 0.0, box=1), journey(1, 10.0, box=2, tests=False), staff=(1, 2))

    assert violations(events, wider, "capacity") == []


def staffing(time: float, recurso: str, anterior: int, nueva: int) -> list[Row]:
    return [
        (time, None, "staffing_changed", {"recurso": recurso, "anterior": anterior, "nueva": nueva})
    ]


def test_empieza_con_el_pool_a_la_plantilla_vigente_tras_una_bajada(center):
    # Dos médicos hasta el 10 y uno después. A valora de 5 a 25; B empieza en el 15 con
    # A ocupado y la plantilla ya en 1: violación. Seguir con A tras la bajada no lo es.
    wider = dataclasses.replace(center, doctors=(2, 1, 1))
    events = build(
        journey(0, 0.0, box=1),
        journey(1, 10.0, box=2, tests=False),
        staffing(10.0, "medicos", 2, 1),
        staff=(1, 2),
    )

    (v,) = violations(events, wider, "capacity")

    assert (v.episode_id, v.sim_time) == ("EP-000001", 15.0)
    assert "staff in force 1" in v.message


def test_por_encima_de_la_plantilla_maxima(center):
    # Un log que anuncia 2 médicos con una plantilla máxima de 1: la segunda valoración
    # cabe en la plantilla anunciada, pero no en la máxima.
    events = build(journey(0, 0.0, box=1), journey(1, 10.0, box=2, tests=False), staff=(1, 2))

    (v,) = violations(events, center, "capacity")

    assert (v.episode_id, v.sim_time) == ("EP-000001", 15.0)
    assert "above the largest staff 1" in v.message


def test_atencion_antes_del_primer_staffing_changed(center):
    # Sin staffing_changed: el primer triaje y la primera valoración son violaciones,
    # una por pool (como en las transiciones, un error no da una cascada).
    events = build(journey(0, 0.0, box=1), staff=None)

    messages = [(v.sim_time, v.message) for v in violations(events, center, "capacity")]

    assert messages == [
        (0.0, "triage_started before the first staffing_changed of enfermeria_triaje"),
        (5.0, "assessment_started before the first staffing_changed of medicos"),
    ]


def test_por_encima_de_la_maxima_sin_plantilla(center):
    # Sin staffing_changed la plantilla no limita, pero la máxima sí: dos valoraciones a
    # la vez con un médico como máximo.
    events = build(journey(0, 0.0, box=1), journey(1, 10.0, box=2, tests=False), staff=None)

    messages = [v.message for v in violations(events, center, "capacity")]

    assert "2 doctors busy, above the largest staff 1" in messages


def test_plantilla_de_un_solo_pool(center):
    # Solo el de médicos: el triaje es una violación, las valoraciones no.
    events = build(journey(0, 0.0, box=1), staffing(0.0, "medicos", 0, 1), staff=None)

    (v,) = violations(events, center, "capacity")

    assert v.message == "triage_started before the first staffing_changed of enfermeria_triaje"


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        (staffing(10.0, "medicos", 2, 1), "anterior 2, but the staff in force was 1"),
        (
            [(0.0, None, "staffing_changed", {"recurso": "medicos", "anterior": 3, "nueva": 1})],
            "anterior 3, but the staff in force was 0",
        ),
    ],
)
def test_staffing_changed_con_anterior_incoherente(center, rows, expected):
    staff = None if rows[0][0] == 0.0 else STAFF
    first = staffing(0.0, "enfermeria_triaje", 0, 1) if staff is None else []
    events = build(first, rows, journey(0, 0.0, box=1), staff=staff)

    messages = [v.message for v in violations(events, center, "capacity")]

    assert len(messages) == 1
    assert messages[0].startswith("staffing_changed of medicos with ")
    assert expected in messages[0]


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
        (t0, "triage_started", {"circuito": "enfermeria"}),
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


def test_dos_concesiones_del_mismo_instante_no_son_un_salto(center):
    # Dos médicos, ocupados por A hasta 25 y libres de golpe (un cambio de turno). B
    # (nivel 4) espera desde 6 y C (nivel 2) desde 7; en 25 los dos reciben médico. SimPy
    # los concede por la clave, pero en la versión 4 quien espera con su paciencia se
    # reanuda un paso después que una reevaluación, y su assessment_started puede salir
    # detrás en el fichero (tarea 5.6). Nadie esperó por el otro.
    small = dataclasses.replace(center, boxes=3, triage_nurses=(5, 5, 5), doctors=(2, 2, 2))
    events = build(
        journey(0, 0.0, tests=False),
        stay_in_box(1, 1.0, 4, 6.0, 2, start=25.0),
        stay_in_box(2, 2.0, 2, 7.0, 3, start=25.0),
    )
    order = [(e.episode_id, e.event_type) for e in events if e.sim_time == 25.0]
    assert order.index(("EP-000001", "assessment_started")) < order.index(
        ("EP-000002", "assessment_started")
    )

    assert violations(events, small, "nobody_jumps_the_queue") == []


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


def queued(arrival_id: int, arrival: float, start: float, circuito: str = "enfermeria"):
    """Un episodio que llega en ``arrival`` y empieza el triaje en ``start``, cortado
    por el horizonte al terminar el triaje (5 minutos de enfermería o 0 en la puerta)."""
    end = start if circuito == "puerta" else start + 5
    level = 1 if circuito == "puerta" else 3
    rows = [
        (arrival, "patient_arrived", {}),
        (arrival, "patient_registered", {}),
        (start, "triage_started", {"circuito": circuito}),
        (end, "triage_completed", {"nivel": level}),
    ]
    return [(time, arrival_id, event_type, payload) for time, event_type, payload in rows]


@pytest.mark.parametrize(
    ("b_start", "c_start", "expected"),
    [
        (5.0, 10.0, []),  # FIFO: B (llega en 1) antes que C (llega en 2)
        (10.0, 5.0, ["EP-000002"]),  # C empieza en 5 con B esperando desde 1
    ],
)
def test_triaje_por_orden_de_llegada(center, b_start, c_start, expected):
    # Una enfermera, ocupada por A de 0 a 5. B y C esperan desde 1 y 2.
    events = build(queued(0, 0.0, 0.0), queued(1, 1.0, b_start), queued(2, 2.0, c_start))

    found = violations(events, center, "nobody_jumps_the_queue")

    assert [v.episode_id for v in found] == expected
    if found:
        assert "triage" in found[0].message and "EP-000001" in found[0].message
        assert found[0].sim_time == 5.0


def test_triaje_con_llegadas_del_mismo_instante(center):
    # B y C llegan en 1: cualquiera de los dos puede empezar primero.
    events = build(queued(0, 0.0, 0.0), queued(1, 1.0, 10.0), queued(2, 1.0, 5.0))
    assert violations(events, center, "nobody_jumps_the_queue") == []


def test_el_nivel_1_en_la_puerta_no_se_cuela(center):
    # B espera enfermera desde 1; L (nivel 1) llega en 3 y se clasifica en la puerta:
    # no ocupa enfermera ni hace cola, así que no adelanta a B en la cola de triaje.
    events = build(queued(0, 0.0, 0.0), queued(1, 1.0, 5.0), queued(2, 3.0, 3.0, "puerta"))
    assert violations(events, center, "nobody_jumps_the_queue") == []
    # Y quien empieza tras él no se cuela respecto a él: L ya no espera.
    events = build(queued(0, 0.0, 0.0), queued(2, 1.0, 1.0, "puerta"), queued(1, 2.0, 5.0))
    assert violations(events, center, "nobody_jumps_the_queue") == []


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


_ARRIVAL_AND_TRIAGE = (
    "patient_arrived",
    "patient_registered",
    "triage_started",
    "triage_completed",
)


def test_el_nivel_1_no_recibe_el_box(one_box):
    rows = [
        r
        for r in displaced_stay("valoracion")
        # L se queda en su llegada y su triaje de puerta (en 12): nunca recibe el box.
        if not (r[1] == L and r[0] >= 12 and r[2] not in _ARRIVAL_AND_TRIAGE)
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


# --- Puerta, versión única y verdad clínica (tarea 4.5a) ------------------------------


def door_triage(arrival_id: int, t0: float, *, level: int = 1, delay: float = 0.0) -> list[Row]:
    """Llegada y triaje de puerta (sin enfermera), con el nivel y el retraso dados."""
    rows = [
        (t0, "patient_arrived", {}),
        (t0, "patient_registered", {}),
        (t0 + delay, "triage_started", {"circuito": "puerta"}),
        (t0 + delay, "triage_completed", {"nivel": level}),
    ]
    return [(time, arrival_id, event_type, payload) for time, event_type, payload in rows]


def with_level(rows: list[Row], level: int) -> list[Row]:
    return [
        (t, a, name, {"nivel": level} if name == "triage_completed" else payload)
        for t, a, name, payload in rows
    ]


def test_puerta_valida(center):
    assert violations(build(door_triage(0, 10.0)), center, "door") == []


def test_puerta_con_nivel_2(center):
    (v,) = violations(build(door_triage(0, 10.0, level=2)), center, "door")
    assert "at the door with nivel 2" in v.message and v.episode_id == "EP-000000"


def test_nivel_1_por_enfermeria(center):
    (v,) = violations(build(with_level(journey(0, 0.0), 1)), center, "door")
    assert "level 1 triaged by a nurse" in v.message


def test_puerta_en_otro_instante_que_la_llegada(center):
    found = violations(build(door_triage(0, 10.0, delay=2.0)), center, "door")
    assert [v.message.split(" at the door")[0] for v in found] == [
        "triage_started",
        "triage_completed",
    ]


def test_enfermeria_que_empieza_en_la_llegada_es_valida(center):
    # Con una enfermera libre, el triaje de enfermería empieza en el instante de la
    # llegada: no es un triaje de puerta y no es una violación.
    events = build(journey(0, 0.0))
    arrived, _, started = events[2:5]
    assert started.payload["circuito"] == "enfermeria" and started.sim_time == arrived.sim_time
    assert violations(events, center, "door") == []


def test_versiones_mezcladas(center):
    events = two_patients()
    last = events[-1]
    mixed = [*events[:-1], dataclasses.replace(last, schema_version=2)]

    assert violations(events, center, "schema_version") == []
    (v,) = violations(mixed, center, "schema_version")
    assert v.event_id == last.event_id
    assert "schema_version 2 in a log of version 1" in v.message


def test_log_vacio_sin_version(center):
    assert violations([], center, "schema_version") == []


# La verdad clínica: un log de la versión 2 del motor con dos pacientes a mano, uno con
# analítica y radiografía de mañana (la radiografía alterada) y otro sin ronda.


@pytest.fixture(scope="module")
def clinical_run():
    from clinical_factory import clinical_log, example_profiles, hand_patient, ordered_of

    from edsim.arrivals.thinning import DayRecord
    from edsim.engine.engine import run_engine

    profiles = example_profiles()
    patients = [
        hand_patient(
            profiles,
            level=3,
            reason="dolor_abdominal",
            age=70,
            ambulance=True,
            ordered=ordered_of("analitica", "radiografia"),
            abnormal=(False, True, False, False),
        ),
        hand_patient(profiles, level=1, reason="parada", age=88, female=False),
    ]
    arrivals = [ArrivalRecord(0, 600.0), ArrivalRecord(1, 610.0)]
    log, sink = clinical_log()
    run = run_engine(load_center(EXAMPLE), arrivals, lambda a: patients[a.arrival_id], log, 1)
    day = DayRecord(
        day=0, date=START, day_effect=1.0, expected=2.0, bound=1.0, candidates=2, accepted=2
    )
    return sink.events, GroundTruth(episodes=run.episodes, days=(day,)), profiles


def clinical_violations(events, ground_truth=None, profiles=None):
    return violations(
        events, load_center(EXAMPLE), "clinical", ground_truth=ground_truth, profiles=profiles
    )


def replaced(events, event_type, episode="EP-000000", **changes):
    """El log con un evento cambiado: el primero de ese tipo y episodio."""
    i = next(
        k for k, e in enumerate(events) if e.event_type == event_type and e.episode_id == episode
    )
    return [*events[:i], dataclasses.replace(events[i], **changes), *events[i + 1 :]]


def test_log_clinico_valido(clinical_run):
    events, ground_truth, profiles = clinical_run
    assert {e.schema_version for e in events} == {3}
    assert [e.event_type for e in events].count("test_resulted") == 1
    assert (
        check_invariants(events, load_center(EXAMPLE), ground_truth=ground_truth, profiles=profiles)
        == []
    )


@pytest.mark.parametrize(
    ("event_type", "payload", "key"),
    [
        ("patient_arrived", {"medio": "propios_medios"}, "medio"),
        ("patient_registered", {"edad": 71, "sexo": "mujer"}, "edad"),
        ("patient_registered", {"edad": 70, "sexo": "hombre"}, "sexo"),
        ("triage_completed", {"nivel": 2, "motivo": "dolor_abdominal"}, "nivel"),
        ("triage_completed", {"nivel": 3, "motivo": "digestivo"}, "motivo"),
        ("test_ordered", {"pruebas": ["analitica"]}, "pruebas"),
    ],
)
def test_cada_campo_clinico_contra_la_verdad(clinical_run, event_type, payload, key):
    events, ground_truth, profiles = clinical_run
    broken = replaced(events, event_type, payload=payload)

    found = clinical_violations(broken, ground_truth, profiles)
    assert any(v.message.startswith(f"{key} ") for v in found), found
    assert clinical_violations(events, ground_truth, profiles) == []


def test_resultados_contra_la_verdad(clinical_run):
    events, ground_truth, profiles = clinical_run
    broken = replaced(
        events,
        "test_resulted",
        payload={"resultados": {"analitica": "normal", "radiografia": "normal"}},
    )

    (v,) = clinical_violations(broken, ground_truth, profiles)
    assert v.message.startswith("resultados ") and "in the truth" in v.message


def test_resultados_distintos_de_las_pruebas_sin_verdad(clinical_run):
    # Del log solo: el resultado lleva los tipos del pedido del episodio.
    events, _, _ = clinical_run
    broken = replaced(events, "test_resulted", payload={"resultados": {"analitica": "normal"}})

    assert clinical_violations(events) == []
    (v,) = clinical_violations(broken)
    assert "but the tests ordered were ['analitica', 'radiografia']" in v.message


@pytest.mark.parametrize(("shift", "fails"), [(1e-6, True), (1e-10, False)])
def test_respuesta_con_tolerancia(clinical_run, shift, fails):
    # Pedido a las 10:20 (mañana): la ronda dura la radiografía o la analítica con
    # factor 1, la más lenta; un desvío de 1e-6 min es una violación, uno de 1e-10 no.
    events, ground_truth, profiles = clinical_run
    resulted = next(e for e in events if e.event_type == "test_resulted")
    broken = replaced(events, "test_resulted", sim_time=resulted.sim_time + shift)

    found = clinical_violations(broken, ground_truth, profiles)
    assert bool(found) is fails
    if fails:
        assert "with the shift band of the order" in found[0].message


def test_sin_perfiles_no_se_comprueba_la_respuesta(clinical_run):
    events, ground_truth, profiles = clinical_run
    resulted = next(e for e in events if e.event_type == "test_resulted")
    broken = replaced(events, "test_resulted", sim_time=resulted.sim_time + 1.0)

    assert clinical_violations(broken, ground_truth) == []
    assert clinical_violations(broken, ground_truth, profiles) != []


def test_log_clinico_con_verdad_provisional(clinical_run):
    events, ground_truth, _ = clinical_run
    provisional = GroundTruth(
        episodes=tuple(
            dataclasses.replace(e, clinical=None, test_turnaround=60.0)
            for e in ground_truth.episodes
        ),
        days=ground_truth.days,
    )

    (v,) = clinical_violations(events, provisional)
    assert v.message == "a clinical log with a provisional ground truth"


def test_log_provisional_con_verdad_clinica(clinical_run):
    _, ground_truth, _ = clinical_run
    events = build(journey(0, 600.0), journey(1, 610.0, box=2, tests=False))

    (v,) = clinical_violations(events, ground_truth)
    assert v.message == "a log of version 1 with a clinical ground truth"


def test_un_log_provisional_no_tiene_comprobacion_clinica(center):
    assert clinical_violations(two_patients(), truth((0, 0.0), (1, 30.0))) == []


# --- Sala de resultados (tarea 4.6a) --------------------------------------------------
#
# El escenario a mano de clinical_factory: A (nivel 4) deja el box 1 en 30 al pedir un
# ECG, B lo recibe en 30, los resultados de A llegan en 42 y A vuelve al box en 70 por
# delante de C, que espera desde 25 pero llegó después.

SALA = Path(__file__).parent / "data" / "centro_sala_ejemplo.toml"


@pytest.fixture(scope="module")
def room_center():
    return dataclasses.replace(load_center(SALA), boxes=1)


@pytest.fixture(scope="module")
def room():
    from clinical_factory import room_log

    return room_log()


def all_violations(events, center):
    return [(v.check, v.message) for v in check_invariants(events, center)]


def moved(events, i, j):
    """El log con el evento i llevado a la posición j (sin cambiar su sim_time)."""
    events = list(events)
    events.insert(j, events.pop(i))
    return events


def index_of(events, event_type, episode="EP-000000", nth=0):
    return [
        k for k, e in enumerate(events) if e.event_type == event_type and e.episode_id == episode
    ][nth]


def test_el_escenario_de_la_sala_es_valido(room, room_center):
    assert all_violations(room, room_center) == []


def test_la_transicion_de_la_sala():
    assert TRANSITIONS["awaiting_tests"]["box_released"] == "results_room"
    assert TRANSITIONS["results_room"] == {"test_resulted": "waiting_box_reassessment"}


def test_soltar_el_box_antes_del_pedido(room, room_center):
    # box_released antes de test_ordered: no es una transición válida desde «assessed».
    i = index_of(room, "box_released")
    bad = moved(room, i, i - 1)
    found = violations(bad, room_center, "transitions")
    assert [v.message for v in found] == ["'box_released' is not valid in state 'assessed'"]


def test_volver_al_box_antes_de_los_resultados(room, room_center):
    # El test_resulted de A, después de su vuelta al box: la vuelta llega en la sala.
    i = index_of(room, "test_resulted")
    bad = moved(room, i, index_of(room, "box_assigned", nth=1))
    bad = [
        dataclasses.replace(e, sim_time=70.0) if k == index_of(bad, "test_resulted") else e
        for k, e in enumerate(bad)
    ]
    found = violations(bad, room_center, "transitions")
    assert [v.message for v in found] == ["'box_assigned' is not valid in state 'results_room'"]


def test_reevaluacion_sin_box(room, room_center):
    # Sin el box_assigned de la vuelta, A se reevalúa sin box.
    i = index_of(room, "box_assigned", nth=1)
    bad = room[:i] + room[i + 1 :]
    assert [v.message for v in violations(bad, room_center, "transitions")] == [
        "('assessment_started', 'reevaluacion') is not valid in state 'waiting_box_reassessment'"
    ]
    assert [v.message for v in violations(bad, room_center, "capacity")] == [
        "assessment in box 1, but the patient is in box None"
    ]


def test_box_released_con_otro_box(room, room_center):
    # A dice dejar el box 2, pero tenía el 1: se señala, y el 1 queda libre igualmente
    # (como en un desalojo), así que B lo recibe sin otra violación.
    bad = [
        dataclasses.replace(e, payload={**e.payload, "box": 2})
        if e.event_type == "box_released"
        else e
        for e in room
    ]
    assert [v.message for v in violations(bad, room_center, "capacity")] == [
        "released box 2, but the patient is in box 1"
    ]


def test_un_box_ocupado_dos_veces_si_la_sala_no_lo_libera(room, room_center):
    # Sin el box_released de A, A sigue en el box 1 cuando B lo recibe en 30, y sigue en él
    # cuando vuelve en 70 (B ya ha salido y el box está libre, pero A no lo dejó).
    i = index_of(room, "box_released")
    bad = room[:i] + room[i + 1 :]
    assert [v.message for v in violations(bad, room_center, "capacity")] == [
        "box 1 already taken by EP-000000",
        "EP-000000 already in box 1",
    ]


def test_un_nivel_3_no_deja_el_box(room, room_center):
    i = index_of(room, "triage_completed")
    bad = [
        dataclasses.replace(e, payload={**e.payload, "nivel": 3}) if k == i else e
        for k, e in enumerate(room)
    ]
    assert [v.message for v in violations(bad, room_center, "results_wait")] == [
        "box_released of a level 3 patient not right after its test_ordered "
        "(espera_resultados_fuera [4, 5])"
    ]


def test_un_nivel_4_con_pruebas_deja_el_box(room_center):
    # El motor sin sala (centro de ejemplo): el nivel 4 con pruebas se queda en el box. Con
    # el centro de la sala, eso es una violación.
    from clinical_factory import clinical_log, example_profiles, hand_patient, ordered_of

    from edsim.engine.engine import run_engine

    patient = hand_patient(example_profiles(), level=4, ordered=ordered_of("ecg"))
    log, sink = clinical_log()
    run_engine(load_center(EXAMPLE), [ArrivalRecord(0, 5.0)], lambda a: patient, log, 1)

    assert check_invariants(sink.events, load_center(EXAMPLE)) == []
    assert [v.message for v in violations(sink.events, room_center, "results_wait")] == [
        "a level 4 patient ordered tests and did not leave its box (espera_resultados_fuera [4, 5])"
    ]


def test_box_released_en_otro_instante(room, room_center):
    i = index_of(room, "box_released")
    bad = [dataclasses.replace(e, sim_time=30.5) if k == i else e for k, e in enumerate(room)]
    assert [v.message for v in violations(bad, room_center, "results_wait")] == [
        "box_released at 30.5, not in the instant of its test_ordered 30.0"
    ]


def test_la_vuelta_con_su_clave_de_llegada(room_center):
    # Si C recibe el box en 70 (como con una clave nueva para A, la hora de vuelta), C se
    # cuela: A espera desde 42 con la clave (4, 5) y C tiene (4, 20).
    from clinical_factory import room_log

    bad = room_log(c_first=True)
    assert [v.message for v in violations(bad, room_center, "nobody_jumps_the_queue")] == [
        "EP-000002 (4, 20.0) got a box while EP-000000 (4, 5.0) waited for one since 42.0"
    ]
    assert [c for c, _ in all_violations(bad, room_center)] == ["nobody_jumps_the_queue"]


def test_solo_en_logs_de_la_version_3(room_center):
    # results_wait no mira los logs de las versiones 1 y 2, donde no hay sala: el mismo
    # nivel 4 con pruebas que no deja el box, en un log de la versión 2, no se señala.
    from clinical_factory import example_profiles, hand_patient, ordered_of

    from edsim.engine.engine import run_engine

    patient = hand_patient(example_profiles(), level=4, ordered=ordered_of("ecg"))
    log = EventLog("v2", date(2026, 1, 5), MemorySink(), schema_version=2)
    run_engine(load_center(EXAMPLE), [ArrivalRecord(0, 5.0)], lambda a: patient, log, 1)
    assert violations(log.sink.events, room_center, "results_wait") == []
