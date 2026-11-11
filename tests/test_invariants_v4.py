"""Invariantes de la versión 4: abandono, destinos, espera de cama y pasillo (tarea 5.1).

Logs a mano de la versión 4. Uno correcto, con los finales del hito 5 (alta, ingreso en
el box, ingreso desalojado al pasillo y abandonos desde los tres sitios), da cero
violaciones; cada log erróneo da la violación de la comprobación que lo busca. Los tres
que pide la especificación: un abandono después de ser visto, un `bed_assigned` sin
`bed_requested` y un ingresado desalojado que vuelve a tener box.

Lo nuevo solo mira eventos de la versión 4: los logs de las versiones 1 a 3 dan las mismas
violaciones que antes (tests de test_invariants.py y test_results_room.py).
"""

import dataclasses
from pathlib import Path

import pytest

from edsim.engine.center import load_center
from edsim.engine.events import OUTCOME_SCHEMA_VERSION, EventLog, MemorySink
from edsim.engine.invariants import CHECKS, TRANSITIONS, TRANSITIONS_V4, check_invariants
from edsim.engine.scenarios import SCENARIO_START

DATA = Path(__file__).parent / "data"

Step = tuple[float, int, str, dict]


@pytest.fixture(scope="module")
def center():
    # Dos boxes: el nivel 1 de 30 desaloja porque los dos están ocupados.
    return dataclasses.replace(load_center(DATA / "centro_ejemplo.toml"), boxes=2)


def arrive(i: int, t: float) -> list[Step]:
    return [
        (t, i, "patient_arrived", {"medio": "propios_medios"}),
        (t, i, "patient_registered", {"edad": 50, "sexo": "mujer"}),
    ]


def triage(i: int, start: float, end: float, level: int) -> list[Step]:
    circuito = "puerta" if level == 1 else "enfermeria"
    return [
        (start, i, "triage_started", {"circuito": circuito}),
        (end, i, "triage_completed", {"nivel": level, "motivo": "otros"}),
    ]


def box(i: int, t: float, number: int) -> list[Step]:
    return [(t, i, "box_assigned", {"box": number})]


def assess(i: int, start: float, end: float, number: int, tipo: str = "inicial") -> list[Step]:
    return [
        (start, i, "assessment_started", {"tipo": tipo, "pool": "medicos", "box": number}),
        (end, i, "assessment_ended", {"tipo": tipo, "interrumpida": False}),
    ]


def decide(i: int, t: float, destino: str) -> list[Step]:
    steps = [(t, i, "disposition_decided", {"destino": destino})]
    if destino == "ingreso":
        return [*steps, (t, i, "bed_requested", {"servicio": "planta"})]
    return [*steps, (t, i, "patient_departed", {"destino": destino})]


def bed(i: int, t: float) -> list[Step]:
    return [
        (t, i, "bed_assigned", {"servicio": "planta"}),
        (t, i, "patient_departed", {"destino": "ingreso"}),
    ]


def left(i: int, t: float, espera: str) -> list[Step]:
    return [(t, i, "patient_left_wbs", {"espera": espera})]


def build(*parts: list[Step]) -> list:
    """Emite los pasos en orden de tiempo (estable) con un EventLog de la versión 4."""
    sink = MemorySink()
    log = EventLog("rv4", SCENARIO_START, sink, schema_version=OUTCOME_SCHEMA_VERSION)
    log.emit("staffing_changed", 0.0, recurso="enfermeria_triaje", anterior=0, nueva=3)
    log.emit("staffing_changed", 0.0, recurso="medicos", anterior=0, nueva=7)
    steps = [step for part in parts for step in part]
    for t, i, event_type, payload in sorted(steps, key=lambda step: step[0]):
        log.emit(event_type, t, arrival_id=i, **payload)
    return sink.events


def correct_parts() -> list[list[Step]]:
    """Todos los finales del hito 5, coherentes entre sí en dos boxes.

    EP-000000: alta en 15 (box 1). EP-000001: ingreso en 16 y cama en 100, en el box 2.
    EP-000002: box 1 en 15, ingreso en 25; EP-000003 (nivel 1) lo desaloja en 30 y espera
    la cama en el pasillo hasta 120. EP-000004 se va en 51 esperando enfermera; EP-000006
    recibe el box 1 en 55 y se va en 75 desde él, esperando médico; EP-000005, triado en 57
    con los dos boxes ocupados, se va en 62 esperando box.
    """
    return [
        arrive(0, 0.0),
        triage(0, 0.0, 5.0, 3),
        box(0, 5.0, 1),
        assess(0, 5.0, 15.0, 1),
        decide(0, 15.0, "alta"),
        arrive(1, 1.0),
        triage(1, 1.0, 6.0, 3),
        box(1, 6.0, 2),
        assess(1, 6.0, 16.0, 2),
        decide(1, 16.0, "ingreso"),
        bed(1, 100.0),
        arrive(2, 2.0),
        triage(2, 2.0, 7.0, 4),
        box(2, 15.0, 1),
        assess(2, 15.0, 25.0, 1),
        decide(2, 25.0, "ingreso"),
        arrive(3, 30.0),
        triage(3, 30.0, 30.0, 1),
        [(30.0, 2, "patient_displaced", {"box": 1, "desalojado_por": "EP-000003"})],
        box(3, 30.0, 1),
        assess(3, 30.0, 40.0, 1),
        decide(3, 40.0, "alta"),
        arrive(4, 50.0),
        left(4, 51.0, "triaje"),
        arrive(6, 53.0),
        triage(6, 53.0, 55.0, 5),
        box(6, 55.0, 1),
        arrive(5, 55.0),
        triage(5, 55.0, 57.0, 5),
        left(5, 62.0, "box"),
        left(6, 75.0, "medico"),
        bed(2, 120.0),
    ]


def violations(events, center, check=None):
    found = check_invariants(events, center)
    return found if check is None else [v for v in found if v.check == check]


def test_el_log_correcto_no_tiene_violaciones(center):
    events = build(*correct_parts())
    assert violations(events, center) == []
    # Guarda: el log tiene los finales que dice.
    types = {e.event_type for e in events}
    assert {"patient_left_wbs", "bed_requested", "bed_assigned", "patient_displaced"} <= types
    assert {e.payload["espera"] for e in events if e.event_type == "patient_left_wbs"} == {
        "triaje",
        "box",
        "medico",
    }


def test_las_comprobaciones_nuevas_estan_registradas():
    assert list(CHECKS)[-2:] == ["abandonment", "outcome"]


def test_la_tabla_v4_separa_lo_visto_de_lo_no_visto():
    # El abandono solo sale de las esperas sin ver; tras la valoración inicial, nunca.
    unseen = {"registered", "triaged", "in_box", "waiting_box_unseen"}
    leaving = {state for state, edges in TRANSITIONS_V4.items() if "patient_left_wbs" in edges}
    assert leaving == unseen
    assert TRANSITIONS_V4["in_box"]["patient_displaced"] == "waiting_box_unseen"
    assert TRANSITIONS_V4["cut_initial"]["patient_displaced"] == "waiting_box_initial"
    assert TRANSITIONS_V4["waiting_box_initial"] == {"box_assigned": "in_box_seen"}
    # La tabla de las versiones 1 a 3 no cambia.
    assert not any("patient_left_wbs" in edges for edges in TRANSITIONS.values())
    assert TRANSITIONS["waiting_box_initial"] == {"box_assigned": "in_box"}


# --- Los tres logs erróneos de la especificación --------------------------------------


def test_abandono_despues_de_ser_visto(center):
    events = build(
        arrive(0, 0.0),
        triage(0, 0.0, 5.0, 3),
        box(0, 5.0, 1),
        assess(0, 5.0, 15.0, 1),
        left(0, 20.0, "medico"),
    )
    (v,) = violations(events, center, "abandonment")
    assert "left after being seen" in v.message
    assert (v.episode_id, v.sim_time) == ("EP-000000", 20.0)


def test_cama_sin_pedirla(center):
    events = build(
        arrive(0, 0.0),
        triage(0, 0.0, 5.0, 3),
        box(0, 5.0, 1),
        assess(0, 5.0, 15.0, 1),
        [(15.0, 0, "disposition_decided", {"destino": "ingreso"})],
        bed(0, 100.0),
    )
    found = [v.message for v in violations(events, center, "outcome")]
    assert "bed_assigned of EP-000000 without bed_requested" in found
    assert "disposition_decided not followed in its instant by bed_requested" in found


def test_ingresado_desalojado_que_vuelve_a_tener_box(center):
    parts = correct_parts()
    # EP-000002, en el pasillo desde 30, recibe el box 1 cuando EP-000003 sale en 40.
    events = build(*parts, box(2, 40.0, 1))
    (v,) = violations(events, center, "displacement")
    assert v.message == "EP-000002 was displaced while waiting for its bed and got box 1 again"
    assert any(
        x.check == "transitions" and x.episode_id == "EP-000002" for x in violations(events, center)
    )


# --- Más errores, uno por regla ---------------------------------------------------------


def test_espera_que_no_es_la_del_estado(center):
    events = build(arrive(0, 0.0), triage(0, 0.0, 5.0, 3), box(0, 5.0, 1), left(0, 9.0, "box"))
    (v,) = violations(events, center, "abandonment")
    assert v.message == "patient_left_wbs with espera 'box', but EP-000000 was waiting for 'medico'"


def test_un_nivel_1_no_abandona(center):
    events = build(arrive(0, 0.0), triage(0, 0.0, 0.0, 1), left(0, 3.0, "box"))
    (v,) = violations(events, center, "abandonment")
    assert "level 1" in v.message


def test_nadie_abandona_durante_el_triaje(center):
    events = build(
        arrive(0, 0.0),
        [(0.0, 0, "triage_started", {"circuito": "enfermeria"})],
        left(0, 3.0, "triaje"),
    )
    (v,) = violations(events, center, "abandonment")
    assert v.message == "EP-000000 left during its triage"


def test_nada_despues_del_abandono(center):
    events = build(arrive(0, 0.0), left(0, 3.0, "triaje"), triage(0, 4.0, 9.0, 3))
    (v,) = violations(events, center, "time")
    assert v.message == "triage_started of EP-000000 after its patient_left_wbs"


def test_un_solo_evento_terminal(center):
    events = build(
        arrive(0, 0.0), left(0, 3.0, "triaje"), [(4.0, 0, "patient_departed", {"destino": "alta"})]
    )
    found = [v.message for v in violations(events, center, "conservation")]
    # El segundo terminal deja además el censo en -1.
    assert found == [
        "patient_departed of EP-000000 after its patient_left_wbs",
        "negative census: -1",
    ]


def test_el_abandono_cuenta_como_salida_para_los_de_dentro(center):
    events = build(arrive(0, 0.0), left(0, 3.0, "triaje"), arrive(1, 4.0))
    assert violations(events, center, "conservation") == []
    assert check_invariants(events, center, inside=1) == []
    assert [v.check for v in check_invariants(events, center, inside=2)] == ["conservation"]


def test_salida_con_ingreso_sin_cama(center):
    events = build(
        arrive(0, 0.0),
        triage(0, 0.0, 5.0, 3),
        box(0, 5.0, 1),
        assess(0, 5.0, 15.0, 1),
        decide(0, 15.0, "ingreso"),
        [(15.0, 0, "patient_departed", {"destino": "ingreso"})],
    )
    found = [v.message for v in violations(events, center, "outcome")]
    assert found == ["patient_departed with 'ingreso' not right after bed_assigned"]


def test_traslado_que_no_sale_en_el_instante(center):
    events = build(
        arrive(0, 0.0),
        triage(0, 0.0, 5.0, 3),
        box(0, 5.0, 1),
        assess(0, 5.0, 15.0, 1),
        [(15.0, 0, "disposition_decided", {"destino": "traslado"})],
        [(20.0, 0, "patient_departed", {"destino": "traslado"})],
    )
    (v,) = violations(events, center, "outcome")
    assert v.message == "disposition_decided not followed in its instant by patient_departed"
    assert v.sim_time == 15.0


def test_quien_abandona_desde_el_box_lo_libera(center):
    # El box 1 queda libre con el abandono de EP-000000: EP-000001 lo recibe en 9.
    events = build(
        arrive(0, 0.0),
        triage(0, 0.0, 5.0, 3),
        box(0, 5.0, 1),
        left(0, 9.0, "medico"),
        arrive(1, 1.0),
        triage(1, 1.0, 6.0, 4),
        box(1, 6.0, 2),
        arrive(2, 2.0),
        triage(2, 2.0, 7.0, 4),
        box(2, 9.0, 1),
    )
    assert violations(events, center) == []
