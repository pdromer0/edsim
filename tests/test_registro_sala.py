"""La sala de espera del directo con lo registrado: `RecordStream` (tarea 7.4).

`record` ve el log entero y ordena todos los borradores de una vez; el directo ve los hechos
de uno en uno, y un registro retrasado tiene que esperar a que el motor pase su `sim_time`
registrado. Aquí el «motor falso» es el escenario L de la 7.1, dado hecho a hecho, con
`peek()` = el instante del hecho siguiente (∞ tras el último), como `LogSource`.

Cada test dice qué error pilla:

- la tabla del escenario L: cuándo sale cada registro (V11: soltar por la hora verdadera);
- la sala = `record` en L y sus variantes: los mismos bytes, con el corte y con el dado;
- el empate con `peek()`: un registro retrasado justo hasta el instante del hecho siguiente
  sale entonces y delante de él;
- el empate dentro de la sala: duplicado y corrección con la misma hora salen por la clave de
  emisión (duplicado antes que corrección), no por el orden en que entraron (V36);
- los errores: otra ejecución, un log que no empieza a medianoche, que retrocede o que llega
  detrás de lo ya soltado, y una cota NaN.
"""

import math
from dataclasses import replace

import pytest
from registro_factory import (
    HORIZON,
    RUN,
    SEED,
    START,
    HandDice,
    make_profile,
    make_roll,
    run_l,
    scenario_l,
    scenario_l_dice,
)

from edsim.clinical_record import RecordStream, Timed, record, record_json
from edsim.engine.events import EventLog, MemorySink


def feed_one_by_one(events, stream):
    """Da los hechos de uno en uno y, tras cada uno, suelta hasta el `peek()` siguiente.

    Devuelve, por hecho, la cota y lo soltado: lo que vería el directo con un motor que da un
    evento por paso.
    """
    steps = []
    for i, event in enumerate(events):
        stream.add([event])
        peek = events[i + 1].sim_time if i + 1 < len(events) else math.inf
        steps.append((peek, stream.ready(peek)))
    return steps


def l_stream(profile=None, u_wrong_l3=0.005):
    return RecordStream(
        profile or make_profile(),
        SEED,
        horizon=HORIZON,
        run_id=RUN,
        dice=scenario_l_dice(u_wrong_l3),
    )


def test_la_sala_suelta_cada_registro_del_escenario_l_cuando_el_motor_pasa_su_hora():
    """El triaje de L3, retrasado hasta 1.031,2, espera a L4 (1.028,0) y sale detrás (V11)."""
    steps = feed_one_by_one(scenario_l(), l_stream())

    released = [
        (peek, [(r.event_id[-1], r.event_type, r.episode_id, round(r.sim_time, 6)) for r in out])
        for peek, out in steps
    ]
    assert released == [
        (1022.5, [("1", "patient_arrived", "EP-000001", 1020.0)]),
        (1024.2, [("2", "patient_registered", "EP-000001", 1022.5)]),
        (1028.0, []),  # L3 registrado en 1.031,2: espera
        (
            1060.0,
            [
                ("3", "patient_arrived", "EP-000002", 1028.0),
                ("4", "triage_completed", "EP-000001", 1031.2),
            ],
        ),
        (
            1135.0,
            [
                ("5", "assessment_started", "EP-000001", 1060.0),
                ("6", "assessment_started", "EP-000001", 1060.5),  # el duplicado
            ],
        ),
        (math.inf, [("7", "record_corrected", "EP-000001", 1166.2)]),  # L6, olvidado
    ]


@pytest.mark.parametrize(
    "case",
    ["L", "corte", "dado-realista", "dado-hostil"],
)
def test_la_sala_da_los_mismos_bytes_que_record(case):
    """Escenario L y sus dos variantes de la 7.1: lo soltado, en orden, es `record`."""
    profile, u_wrong_l3 = {
        "L": (make_profile(), 0.005),
        "corte": (make_profile(correction=Timed(0.5, (500.0, 720.0))), 0.005),
        "dado-realista": (make_profile(name="realista", wrong=0.01), 0.03),
        "dado-hostil": (make_profile(name="hostil", wrong=0.07), 0.03),
    }[case]
    batch = run_l(profile, u_wrong_l3=u_wrong_l3)

    stream = l_stream(profile, u_wrong_l3)
    live = [r for _, out in feed_one_by_one(scenario_l(), stream) for r in out]

    assert [record_json(r) for r in live] == [record_json(r) for r in batch.records]
    assert stream.run_id == batch.run_id
    assert len(stream) == 0
    # Guardas: el caso ocurre (7 registros en L; 6 con el corte, sin la corrección; 6 con el
    # realista, que no altera el nivel; 7 con el hostil, que sí).
    assert len(live) == {"L": 7, "corte": 6, "dado-realista": 6, "dado-hostil": 7}[case]


def two_patients(triage_at: float, arrival_at: float) -> list:
    """Un triaje de EP-000001 y, después, la llegada de EP-000002."""
    sink = MemorySink()
    log = EventLog(RUN, START, sink, schema_version=4)
    log.emit("triage_completed", triage_at, arrival_id=1, nivel=3, motivo="fiebre")
    log.emit("patient_arrived", arrival_at, arrival_id=2, medio="propios_medios")
    return sink.events


def test_un_registro_que_empata_con_peek_sale_entonces_y_delante_del_hecho_de_ese_instante():
    """Triaje en 15,0 con 5,0 de retraso (mediana 5 y z = 0): registrado en 20,0, el instante
    de la llegada siguiente. Con `peek()` = 20,0 ya sale: nada futuro puede ir antes."""
    events = two_patients(15.0, 20.0)
    profile = make_profile(delay={**make_profile().delay, "triaje": Timed(0.6, (5.0, 15.0))})
    rolls = [make_roll(u_delay=0.0), make_roll()]
    stream = RecordStream(profile, SEED, horizon=HORIZON, run_id=RUN, dice=HandDice(list(rolls)))

    steps = feed_one_by_one(events, stream)

    assert [(peek, [(r.event_type, r.sim_time) for r in out]) for peek, out in steps] == [
        (20.0, [("triage_completed", 20.0)]),
        (math.inf, [("patient_arrived", 20.0)]),
    ]
    batch = record(events, profile, SEED, horizon=HORIZON, run_id=RUN, dice=HandDice(rolls))
    assert [record_json(r) for _, out in steps for r in out] == [
        record_json(r) for r in batch.records
    ]


def test_duplicado_y_correccion_a_la_misma_hora_salen_por_la_clave_no_por_la_llegada():
    """Nivel erróneo con corrección y duplicado, los dos 135 min después (z = 0): misma
    `sim_time`. La corrección entra antes en la sala, pero el duplicado (orden 1) sale antes
    que la corrección (orden 2), como en `record` (V36)."""
    events = two_patients(15.0, 300.0)[:1]
    profile = make_profile(
        duplicate=Timed(0.5, (135.0, 720.0)), correction=Timed(0.5, (135.0, 720.0))
    )
    roll = make_roll(
        u_wrong=0.0, u_wrong_field=0.0, u_wrong_value=0.9, u_correction=0.0, u_duplicate=0.0
    )
    stream = RecordStream(profile, SEED, horizon=HORIZON, run_id=RUN, dice=HandDice([roll]))
    stream.add(events)

    live = stream.ready(math.inf)

    assert [(r.event_type, r.sim_time) for r in live] == [
        ("triage_completed", 15.0),
        ("triage_completed", 150.0),  # el duplicado
        ("record_corrected", 150.0),
    ]
    batch = record(events, profile, SEED, horizon=HORIZON, run_id=RUN, dice=HandDice([roll]))
    assert [record_json(r) for r in live] == [record_json(r) for r in batch.records]


def test_lo_que_cae_en_el_horizonte_no_se_numera():
    """La llegada en 1.440,0 = horizonte: no se escribe, como en `record`."""
    events = two_patients(15.0, HORIZON)
    stream = RecordStream(
        make_profile(), SEED, horizon=HORIZON, run_id=RUN, dice=HandDice(default=make_roll())
    )
    stream.add(events)

    assert [r.event_id for r in stream.ready(math.inf)] == ["r2026_prueba_s7-000000001"]
    assert len(stream) == 0


def quiet_stream():
    return RecordStream(
        make_profile(), SEED, horizon=HORIZON, run_id=RUN, dice=HandDice(default=make_roll())
    )


def test_un_evento_de_otra_ejecucion_es_un_error():
    sink = MemorySink()
    EventLog("otra", START, sink, schema_version=4).emit(
        "patient_arrived", 1.0, arrival_id=1, medio="propios_medios"
    )
    with pytest.raises(ValueError, match="event of run 'otra', not 'r2026'"):
        quiet_stream().add(sink.events)


def test_un_log_que_no_empieza_a_medianoche_es_un_error():
    [first] = two_patients(15.0, 20.0)[:1]
    moved = replace(first, event_time=first.event_time.replace("T00:15", "T00:16"))
    with pytest.raises(ValueError, match="does not start a log at midnight"):
        quiet_stream().add([moved])


def test_un_evento_que_retrocede_es_un_error():
    triage, arrival = two_patients(15.0, 20.0)
    stream = quiet_stream()
    stream.add([arrival])
    with pytest.raises(ValueError, match="goes back"):
        stream.add([triage])


def test_un_evento_detras_de_lo_ya_soltado_es_un_error():
    """La cota de `ready` tiene que ser `peek()`: si llega un hecho anterior, la cota mentía."""
    triage, arrival = two_patients(15.0, 20.0)
    stream = quiet_stream()
    stream.ready(16.0)
    with pytest.raises(ValueError, match="already released"):
        stream.add([triage])
    stream.add([arrival])  # 20,0 ≥ 16,0: vale


def test_una_cota_nan_es_un_error():
    with pytest.raises(ValueError, match="bound must be a number"):
        quiet_stream().ready(math.nan)
