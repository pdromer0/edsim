"""La comparación con la verdad: conciliación e indicadores ingenuos (tarea 7.3).

Cada test dice qué error pilla. El escenario L (el de la 7.1, con sus horas calculadas a mano en el
PR de la 7.3 con código independiente de `compare`) fija los números de la especificación; los
casos a mano fijan cada regla de los indicadores ingenuos y cada error de la cuenta, con registros
que `record` no puede producir (un duplicado con otra hora, una salida antes que la llegada) y que
por eso se construyen aquí, copiando eventos de la verdad.
"""

import dataclasses
import math
import re

import pytest
from registro_factory import (
    DERIVED,
    HORIZON,
    RUN,
    START,
    clean_record_profile,
    eid,
    loud_profile,
    patient_log,
    run_l,
    scenario_l,
)

from edsim.clinical_record import (
    CORRECTION,
    DUPLICATE,
    GOOD,
    LOST,
    PENDING,
    RECORD_CORRECTED,
    WITH_SLIPS,
    Comparison,
    DelayStats,
    NotebookRow,
    ReconciliationError,
    Record,
    SlipCounts,
    compare,
    record,
)
from edsim.clinical_record.compare import MAX_HOURS
from edsim.engine.events import EventLog, MemorySink

# --- El escenario L ----------------------------------------------------------------------------


def compare_l(**options) -> Comparison:
    recording = run_l()
    return compare(scenario_l(), recording.records, recording.notebook, horizon=HORIZON, **options)


def test_conciliacion_del_escenario_l():
    """6 hechos (4 bien, 1 con despistes, 1 perdido) y 7 registros (4 bien, 1 con despistes,
    1 duplicado, 1 corrección): la cuenta de la especificación. Pilla un duplicado contado como
    hecho (V9: serían 7 hechos y la cuenta no cuadraría)."""
    reconciliation = compare_l().reconciliation

    assert reconciliation.facts == 6
    assert reconciliation.records == 7
    assert dict(reconciliation.by_kind) == {
        "bien": 4,
        "con_despistes": 1,
        "duplicado": 1,
        "correccion": 1,
        "perdido": 1,
        "pendiente": 0,
        "correccion_pendiente": 0,
    }
    assert list(reconciliation.by_kind) == [
        "bien",
        "con_despistes",
        "duplicado",
        "correccion",
        "perdido",
        "pendiente",
        "correccion_pendiente",
    ]


def test_retraso_por_sistema_del_escenario_l():
    """Admisión [0, 0, 0], triaje [7] y HIS [0]: el duplicado (retraso de 0,5 min) y la
    corrección no entran en la distribución de su sistema (V28: el HIS saldría con mediana
    0,25), y un sistema sin registros da recuento 0, sin números."""
    delay = compare_l().reconciliation.delay

    assert list(delay) == ["admision", "triaje", "his", "lab"]
    assert delay["admision"] == DelayStats(3, 0.0, 0.0)
    assert delay["triaje"] == DelayStats(1, 7.0, 7.0)
    assert delay["his"] == DelayStats(1, 0.0, 0.0)
    assert delay["lab"] == DelayStats(0, None, None)


def test_desglose_de_con_despistes_del_escenario_l():
    """La única fila `con_despistes` (el triaje) tiene reloj, retraso y valor erróneo y ningún
    campo vacío; no es «solo reloj»."""
    assert compare_l().reconciliation.slips == SlipCounts(
        rows=1, clock=1, delay=1, wrong=1, empty=0, only_clock=0
    )


def test_indicadores_del_escenario_l_la_tabla_de_la_especificacion():
    """4,2 frente a 6,2 min; 1 frente a 2 pacientes a las 20:00; nivel 3 frente a nivel 4.

    Pilla el reloj que no llega al tiempo hasta el triaje, un censo que no cuenta al fantasma
    (la salida de Lucía se perdió) y una corrección aplicada (V10: nivel 3 en vez de 4)."""
    comparison = compare_l()
    truth, recorded = comparison.truth, comparison.recorded

    assert truth.time_to_triage == pytest.approx(4.2)
    assert recorded.time_to_triage == pytest.approx(6.2)
    assert truth.in_department[20] == 1
    assert recorded.in_department[20] == 2
    assert truth.level_shares == {1: 0.0, 2: 0.0, 3: 100.0, 4: 0.0, 5: 0.0}
    assert recorded.level_shares == {1: 0.0, 2: 0.0, 3: 0.0, 4: 100.0, 5: 0.0}


def test_otros_indicadores_del_escenario_l():
    """Tiempo hasta el médico igual (el HIS no tiene desfase), 2 llegadas y el censo hora a hora
    de las 17 a las 23, calculado a mano: [1, 2, 1, 1, 1, 1, 1] frente a [1, 2, 2, 2, 2, 2, 2];
    las horas anteriores a la primera llegada, a 0. Las medias, 8/24 y 13/24."""
    comparison = compare_l()
    truth, recorded = comparison.truth, comparison.recorded

    assert truth.time_to_doctor == recorded.time_to_doctor == pytest.approx(40.0)
    assert truth.arrivals == recorded.arrivals == 2
    assert [truth.in_department[k] for k in range(17, 24)] == [1, 2, 1, 1, 1, 1, 1]
    assert [recorded.in_department[k] for k in range(17, 24)] == [1, 2, 2, 2, 2, 2, 2]
    assert set(truth.in_department) == set(range(24))
    assert not any(truth.in_department[k] for k in range(17))
    assert truth.mean_in_department == pytest.approx(8 / 24)
    assert recorded.mean_in_department == pytest.approx(13 / 24)


def test_la_tabla_de_indicadores_del_escenario_l():
    """La tabla «indicador, verdad, registrado, diferencia»: una fila por indicador y una por
    nivel; la diferencia es registrado menos verdad."""
    rows = {row.key: row for row in compare_l().rows()}

    assert list(rows) == [
        "time_to_triage",
        "time_to_doctor",
        "mean_in_department",
        "arrivals",
        "level_1",
        "level_2",
        "level_3",
        "level_4",
        "level_5",
    ]
    assert rows["time_to_triage"].difference == pytest.approx(2.0)
    assert rows["mean_in_department"].difference == pytest.approx(5 / 24)
    assert rows["arrivals"].difference == 0
    assert rows["level_3"].difference == -100.0
    assert rows["level_4"].difference == 100.0


def test_la_comparacion_no_cambia_lo_que_recibe():
    """Pilla una comparación que reordena o consume las listas: son las mismas dos veces."""
    recording = run_l()
    truth = scenario_l()

    first = compare(truth, recording.records, recording.notebook, horizon=HORIZON)
    second = compare(truth, list(recording.records), list(recording.notebook), horizon=HORIZON)

    assert first == second


# --- Con el perfil limpio, todos iguales ------------------------------------------------------


def test_con_el_perfil_limpio_todos_los_indicadores_son_los_de_la_verdad():
    """120 pacientes (y un evento de recursos) con el perfil limpio: cada indicador, igual en la
    verdad y en lo registrado, y la conciliación sin despistes. Pilla un indicador que sesga por
    sí mismo, no por los despistes."""
    truth = patient_log(120)
    recording = record(truth, clean_record_profile(), 3, horizon=1440.0, run_id=RUN)

    comparison = compare(truth, recording.records, recording.notebook, horizon=1440.0)

    assert comparison.truth == comparison.recorded
    assert all(row.difference == 0 for row in comparison.rows())
    reconciliation = comparison.reconciliation
    assert reconciliation.by_kind["bien"] == reconciliation.facts == len(truth)
    assert reconciliation.slips.rows == 0
    # Que no sea un test vacío: hay de qué medir.
    assert comparison.truth.arrivals == 120
    assert comparison.truth.time_to_triage is not None
    assert comparison.truth.time_to_doctor is not None
    assert max(comparison.truth.in_department.values()) > 1
    assert sum(1 for s in comparison.truth.level_shares.values() if s) == 5


def test_con_un_perfil_ruidoso_los_indicadores_se_desvian():
    """La contraprueba del anterior: con despistes la tabla no es de ceros. Sin ella, el test del
    perfil limpio pasaría también con una comparación que devuelve siempre lo mismo."""
    truth = patient_log(120)
    recording = record(truth, loud_profile(), 3, horizon=1440.0, run_id=RUN)

    comparison = compare(truth, recording.records, recording.notebook, horizon=1440.0)

    assert comparison.truth != comparison.recorded
    assert comparison.reconciliation.by_kind[WITH_SLIPS] > 0
    assert comparison.reconciliation.by_kind[LOST] > 0
    assert comparison.reconciliation.by_kind[DUPLICATE] > 0
    assert comparison.reconciliation.slips.rows == comparison.reconciliation.by_kind[WITH_SLIPS]


# --- Casos a mano: copiar eventos de la verdad ---------------------------------------------------


def hand_truth(*steps, version: int = 4) -> list:
    """El log verdadero de unos pasos `(minuto, tipo, llegada, payload)`, en orden."""
    sink = MemorySink()
    log = EventLog(RUN, START, sink, schema_version=version)
    for minute, event_type, arrival, payload in steps:
        log.emit(event_type, minute, arrival_id=arrival, **payload)
    return sink.events


def as_record(event, number: int, **changes) -> Record:
    """El registro de un evento tal cual, con sus cambios (`event_time`, `payload`…)."""
    values = {
        "event_id": eid(number),
        "event_type": event.event_type,
        "schema_version": event.schema_version,
        "run_id": DERIVED,
        "episode_id": event.episode_id,
        "patient_id": event.patient_id,
        "source_system": event.source_system,
        "sim_time": event.sim_time,
        "event_time": event.event_time,
        "recorded_time": event.event_time,
        "ingest_time": None,
        "payload": dict(event.payload),
    }
    values.update(changes)
    return Record(**values)


def faithful(truth):
    """Cada evento escrito tal cual, de clase `bien`: la base de los casos a mano."""
    records = [as_record(e, n) for n, e in enumerate(truth, start=1)]
    notebook = [
        NotebookRow(r.event_id, e.event_id, GOOD, 0.0, 0.0)
        for r, e in zip(records, truth, strict=True)
    ]
    return records, notebook


def at(minute: float) -> str:
    """La hora del minuto `minute` del día 5 de enero de 2026, como la escribe `event_time`."""
    total = round(minute * 60_000)
    hours, rest = divmod(total, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    day, hour = 5 + hours // 24, hours % 24
    return f"2026-01-{day:02d}T{hour:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}+01:00"


TRIAGED = {"nivel": 3, "motivo": "otros"}
ARRIVED = {"medio": "propios_medios"}
SEEN = {"tipo": "inicial", "pool": "medicos", "box": 1}


def test_el_primer_registro_de_cada_tipo_es_el_que_cuenta():
    """Con la llegada duplicada 30 s más tarde (un reloj distinto), el tiempo hasta el triaje se
    mide desde la primera, no desde la última (V26: 4,5 en vez de 5)."""
    truth = hand_truth((600, "patient_arrived", 1, ARRIVED), (605, "triage_completed", 1, TRIAGED))
    records, notebook = faithful(truth)
    records.append(as_record(truth[0], 3, event_time=at(600.5)))
    notebook.append(
        NotebookRow(eid(3), truth[0].event_id, DUPLICATE, 0.0, 0.0, duplicate_of=eid(1))
    )
    records.sort(key=lambda r: r.sim_time)

    comparison = compare(truth, records, notebook, horizon=1440.0)

    assert comparison.recorded.time_to_triage == pytest.approx(5.0)
    assert comparison.recorded.arrivals == 2  # el duplicado es otra llegada para quien cuenta filas


def test_el_medico_solo_cuenta_la_valoracion_inicial_con_su_tipo():
    """Una reevaluación no es «hasta el médico», y un `tipo` a null (campo vacío) no cuenta: el
    episodio sin valoración inicial legible no entra, en vez de caer en un error."""
    truth = hand_truth(
        (0, "patient_arrived", 1, ARRIVED),
        (10, "assessment_started", 1, {**SEEN, "tipo": "reevaluacion"}),
        (20, "assessment_started", 1, SEEN),
        (30, "patient_arrived", 2, ARRIVED),
        (45, "assessment_started", 2, SEEN),
    )
    records, notebook = faithful(truth)
    nulled = dataclasses.replace(records[4], payload={**records[4].payload, "tipo": None})
    records[4] = nulled

    comparison = compare(truth, records, notebook, horizon=1440.0)

    assert comparison.truth.time_to_doctor == pytest.approx(17.5)  # mediana de 20 y 15
    assert comparison.recorded.time_to_doctor == pytest.approx(20.0)  # solo el episodio 1


def test_el_reparto_por_nivel_ignora_lo_que_no_se_lee_y_las_correcciones():
    """Entran los `triage_completed` con un nivel entero de 1 a 5 (los duplicados cuentan);
    un `null`, un 9, un `True` y un «3» no entran en el denominador, y un `record_corrected` no
    es un triaje ni cambia nada (V10)."""
    truth = hand_truth(
        *[
            step
            for i in range(1, 7)
            for step in (
                (i, "patient_arrived", i, ARRIVED),
                (i + 0.5, "triage_completed", i, {"nivel": 1 + i % 5, "motivo": "otros"}),
            )
        ]
    )
    records, notebook = faithful(truth)
    triages = [i for i, r in enumerate(records) if r.event_type == "triage_completed"]
    for index, level in zip(triages[:4], (None, 9, True, "3"), strict=True):
        records[index] = dataclasses.replace(
            records[index], payload={**records[index].payload, "nivel": level}
        )
    number = len(records) + 1
    records.append(
        as_record(
            truth[1],
            number,
            event_type=RECORD_CORRECTED,
            sim_time=700.0,
            payload={"corrige": records[triages[4]].event_id, "campos": {"nivel": 1}},
        )
    )
    notebook.append(
        NotebookRow(eid(number), truth[1].event_id, CORRECTION, 0.0, 0.0, corrects=eid(1))
    )

    shares = compare(truth, records, notebook, horizon=1440.0).recorded.level_shares

    # Quedan los triajes 5 y 6 (niveles 1 + 5 % 5 = 1 y 1 + 6 % 5 = 2): mitad y mitad.
    assert shares == {1: 50.0, 2: 50.0, 3: 0.0, 4: 0.0, 5: 0.0}


def test_sin_triajes_legibles_el_reparto_no_tiene_valores():
    """Tolerante a los vacíos: sin ningún nivel legible el reparto es `None`, no 0 % ni un error
    de división por cero."""
    truth = hand_truth((0, "patient_arrived", 1, ARRIVED))
    records, notebook = faithful(truth)

    comparison = compare(truth, records, notebook, horizon=1440.0)

    assert comparison.truth.level_shares == dict.fromkeys(range(1, 6))
    assert comparison.recorded.time_to_triage is None
    assert all(row.difference is None for row in comparison.rows() if row.key.startswith("level_"))


def test_el_censo_en_la_hora_en_punto_cuenta_la_llegada_y_no_la_salida():
    """Una llegada justo a la 1:00 está dentro a la 1:00; una salida justo a las 2:00 ya no
    está dentro a las 2:00 (V29: con los comparadores al revés, el censo sería [0, 0, 1])."""
    truth = hand_truth(
        (60, "patient_arrived", 1, ARRIVED),
        (120, "patient_departed", 1, {"destino": "alta"}),
    )
    records, notebook = faithful(truth)

    census = compare(truth, records, notebook, horizon=240.0).recorded.in_department

    assert dict(census) == {0: 0, 1: 1, 2: 0, 3: 0}


def test_el_censo_cierra_con_las_dos_salidas_y_ignora_lo_que_no_tiene_llegada():
    """`patient_left_wbs` cierra el episodio como `patient_departed`; una salida sin llegada no
    resta a nadie; una segunda salida del mismo episodio no cambia nada."""
    truth = hand_truth(
        (10, "patient_arrived", 1, ARRIVED),
        (20, "patient_arrived", 2, ARRIVED),
        (30, "patient_departed", 3, {"destino": "alta"}),
        (80, "patient_left_wbs", 1, {"espera": "triaje"}),
    )
    records, notebook = faithful(truth)
    # Una segunda salida (duplicada) del episodio 1, más tarde.
    records.append(as_record(truth[3], 5, event_time=at(200)))
    notebook.append(
        NotebookRow(eid(5), truth[3].event_id, DUPLICATE, 0.0, 0.0, duplicate_of=eid(4))
    )

    census = compare(truth, records, notebook, horizon=180.0).recorded.in_department

    assert dict(census) == {0: 0, 1: 2, 2: 1}  # a la 1:00 los episodios 1 y 2; a las 2:00, el 2


def test_una_salida_anterior_a_la_llegada_por_los_relojes_no_deja_a_nadie_dentro():
    """Con la llegada en un reloj adelantado y la salida en otro retrasado, la salida cae antes
    que la llegada: el episodio no está nunca, ni de negativo (un −1 en la hora de en medio)."""
    truth = hand_truth(
        (118, "patient_arrived", 1, ARRIVED), (119, "patient_departed", 1, {"destino": "alta"})
    )
    records, notebook = faithful(truth)
    records[0] = dataclasses.replace(records[0], event_time=at(121))  # llega a las 2:01
    records[1] = dataclasses.replace(records[1], event_time=at(119))  # sale a las 1:59

    census = compare(truth, records, notebook, horizon=240.0).recorded.in_department

    assert dict(census) == {0: 0, 1: 0, 2: 0, 3: 0}


@pytest.mark.parametrize(
    ("warmup", "horizon", "hours"),
    [
        (0, 240, [0, 1, 2, 3]),
        (
            120,
            300,
            [2, 3, 4],
        ),  # la hora 2 (el calentamiento) entra; la 5 (300 = 5 h) no cabe: 60 k < 300
        (120, 301, [2, 3, 4, 5]),
        (61, 240, [2, 3]),  # la hora 1 (60 min) queda antes del calentamiento
        (61, 119, []),  # ninguna hora en punto: sin media
    ],
)
def test_las_horas_de_la_ventana_empiezan_en_el_calentamiento_y_acaban_antes_del_horizonte(
    warmup, horizon, hours
):
    """La media es la de las horas en punto de `[calentamiento, horizonte)`: el calentamiento
    entra, el horizonte no, y sin ninguna hora no hay media (V30: con el calentamiento dentro,
    la media y las horas serían otras)."""
    truth = hand_truth((0, "patient_arrived", 1, ARRIVED))
    records, notebook = faithful(truth)

    comparison = compare(truth, records, notebook, horizon=horizon, warmup=warmup)

    assert list(comparison.recorded.in_department) == hours
    assert comparison.recorded.mean_in_department == (1.0 if hours else None)


def test_la_media_del_censo_deja_fuera_el_calentamiento():
    """Un paciente de 0:00 a 0:30 y dos que llegan a las 2:00 y se quedan: el censo de las horas
    0 a 3 es [1, 0, 2, 2] (media 5/4); con calentamiento de 2 h, solo cuentan las horas 2 y 3
    (media 2). Pilla una media que no deja fuera el calentamiento (V30: saldría 5/4)."""
    truth = hand_truth(
        (0, "patient_arrived", 1, ARRIVED),
        (30, "patient_departed", 1, {"destino": "alta"}),
        (120, "patient_arrived", 2, ARRIVED),
        (120, "patient_arrived", 3, ARRIVED),
    )
    records, notebook = faithful(truth)

    whole = compare(truth, records, notebook, horizon=240.0).recorded
    window = compare(truth, records, notebook, horizon=240.0, warmup=120.0).recorded

    assert dict(whole.in_department) == {0: 1, 1: 0, 2: 2, 3: 2}
    assert whole.mean_in_department == pytest.approx(5 / 4)
    assert dict(window.in_department) == {2: 2, 3: 2}
    assert window.mean_in_department == 2.0


def test_todo_vacio_es_una_comparacion_vacia_no_un_error():
    """Sin hechos ni registros: recuentos a 0, indicadores sin valor, el censo en ceros."""
    comparison = compare([], [], [], horizon=120.0)

    assert comparison.reconciliation.facts == comparison.reconciliation.records == 0
    assert set(comparison.reconciliation.by_kind.values()) == {0}
    assert comparison.truth == comparison.recorded
    assert comparison.truth.time_to_triage is None
    assert dict(comparison.truth.in_department) == {0: 0, 1: 0}
    assert comparison.truth.arrivals == 0


def test_p90_y_mediana_del_retraso_por_interpolacion_lineal():
    """Retrasos de 1 a 10 min en un sistema: mediana 5,5 y p90 9,1 (1 + 0,9 · 9 = posición 8,1);
    el valor calculado a mano con código aparte, en el PR."""
    truth = hand_truth(*[(i * 10, "patient_arrived", i, ARRIVED) for i in range(1, 11)])
    records, notebook = faithful(truth)
    records = [
        dataclasses.replace(r, recorded_time=at(i * 10 + i)) for i, r in enumerate(records, start=1)
    ]

    stats = compare(truth, records, notebook, horizon=1440.0).reconciliation.delay["admision"]

    assert stats.count == 10
    assert stats.median == pytest.approx(5.5)
    assert stats.p90 == pytest.approx(9.1)


def test_el_desglose_cuenta_cada_despiste_y_cuanto_es_solo_reloj():
    """Cinco filas `con_despistes`: dos solo con reloj, una con reloj y retraso, una con un valor
    erróneo y una con un campo vacío. Los despistes se solapan: 3 con reloj, 1 con retraso."""
    truth = hand_truth(*[(i, "patient_arrived", i, ARRIVED) for i in range(1, 6)])
    records, _ = faithful(truth)
    ids = [r.event_id for r in records]
    fact = [e.event_id for e in truth]
    rows = [
        NotebookRow(ids[0], fact[0], WITH_SLIPS, 0.0, 2.0),
        NotebookRow(ids[1], fact[1], WITH_SLIPS, 0.0, -1.0),
        NotebookRow(ids[2], fact[2], WITH_SLIPS, 3.0, 2.0),
        NotebookRow(ids[3], fact[3], WITH_SLIPS, 0.0, 0.0, wrong_field="nivel",
                    true_value=3, recorded_value=4),
        NotebookRow(ids[4], fact[4], WITH_SLIPS, 0.0, 0.0, empty_field="medio"),
    ]  # fmt: skip

    slips = compare(truth, records, rows, horizon=1440.0).reconciliation.slips

    assert slips == SlipCounts(rows=5, clock=3, delay=1, wrong=1, empty=1, only_clock=2)


# --- La cuenta ---------------------------------------------------------------------------------


def l_inputs():
    recording = run_l()
    return scenario_l(), list(recording.records), list(recording.notebook)


def replace_row(notebook, index, **changes):
    notebook[index] = dataclasses.replace(notebook[index], **changes)


def case_missing_record():
    truth, records, notebook = l_inputs()
    del records[5]  # el duplicado que bronce no tiene
    return truth, records, notebook, "filas de la libreta sin su registro: 1"


def case_extra_record():
    truth, records, notebook = l_inputs()
    records.append(dataclasses.replace(records[0], event_id=eid(99)))
    return truth, records, notebook, "registros que la libreta no tiene: 1"


def case_repeated_record_id():
    truth, records, notebook = l_inputs()
    records[1] = dataclasses.replace(records[1], event_id=records[0].event_id)
    return truth, records, notebook, "registros con el mismo event_id: 1"


def case_unknown_fact():
    truth, records, notebook = l_inputs()
    replace_row(notebook, 0, fact_id="otro-hecho")
    return truth, records, notebook, "hechos de la libreta que no están en la verdad: 1"


def case_row_without_record():
    truth, records, notebook = l_inputs()
    replace_row(notebook, 0, record_id=eid(77))
    return truth, records, notebook, "filas de la libreta sin su registro: 1"


def case_missing_fact():
    truth, records, notebook = l_inputs()
    del notebook[-1]  # la fila del hecho perdido
    return truth, records, notebook, "hechos de la verdad sin fila en la libreta: 1"


def case_double_fact_row():
    truth, records, notebook = l_inputs()
    replace_row(notebook, 1, fact_id=notebook[0].fact_id)
    return truth, records, notebook, "hechos con más de una fila de hecho: 1"


def case_wrong_kind_count():
    truth, records, notebook = l_inputs()
    replace_row(notebook, 5, kind=GOOD, duplicate_of=None)  # un duplicado contado como hecho
    return truth, records, notebook, "hechos de la verdad = bien + con_despistes"


@pytest.mark.parametrize(
    "case",
    [
        case_missing_record,
        case_extra_record,
        case_repeated_record_id,
        case_unknown_fact,
        case_row_without_record,
        case_missing_fact,
        case_double_fact_row,
        case_wrong_kind_count,
    ],
)
def test_si_la_cuenta_no_cuadra_es_un_error_no_un_numero(case):
    """Registros de menos (un bronce incompleto), de más, repetidos, un hecho desconocido, una
    fila sin registro, un hecho sin fila, con dos filas o un duplicado contado como hecho: cada
    uno es `ReconciliationError`, con su frase (V27: sin el error, la comparación daría números)."""
    truth, records, notebook, message = case()

    with pytest.raises(ReconciliationError, match=re.escape(message)) as error:
        compare(truth, records, notebook, horizon=HORIZON)

    assert isinstance(error.value, ValueError)
    assert error.value.problems


def test_el_error_de_la_cuenta_da_todos_los_problemas_a_la_vez():
    """Un bronce al que le faltan dos registros se ve entero de una vez, no de uno en uno."""
    truth, records, notebook = l_inputs()
    del records[5]
    del records[0]

    with pytest.raises(ReconciliationError) as error:
        compare(truth, records, notebook, horizon=HORIZON)

    texts = " | ".join(error.value.problems)
    assert (
        "registros que la libreta no tiene" not in texts
    )  # lo que sobra en la libreta es otro problema
    assert "filas de la libreta sin su registro: 2" in texts
    assert "registros = bien + con_despistes + duplicado + correccion: 5 != 7" in texts
    assert len(error.value.problems) == 2


# --- Entradas malas ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("horizon", "warmup"),
    [
        (math.inf, 0),
        (math.nan, 0),
        (-math.inf, 0),
        (10**400, 0),
        (True, 0),
        ("1440", 0),
        (None, 0),
        (1440, math.nan),
        (1440, -1),
        (1440, 1440),
        (1440, 2000),
        (1440, True),
        (0, 0),
        (MAX_HOURS * 60 + 60, 0),
    ],
)
def test_una_ventana_imposible_es_un_error(horizon, warmup):
    """Infinitos, NaN, un entero de 400 cifras (sin float), un booleano, un horizonte que no
    sobrepasa al calentamiento o una ventana de más de diez años: `ValueError`, y nunca un bucle
    de millones de horas."""
    with pytest.raises(ValueError):
        compare([], [], [], horizon=horizon, warmup=warmup)


@pytest.mark.parametrize(
    "bad",
    ["2026-01-05T17:00:00", "2026-01-05", "ayer", ""],
    ids=["sin_zona", "solo_fecha", "texto", "vacio"],
)
def test_una_hora_sin_zona_o_ilegible_es_un_error_que_dice_el_registro(bad):
    """Un `date` o un `datetime` sin zona no se comparan con uno con zona (`TypeError`): se
    rechazan, con el `event_id` del registro."""
    truth = hand_truth((0, "patient_arrived", 1, ARRIVED))
    records, notebook = faithful(truth)
    records[0] = dataclasses.replace(records[0], event_time=bad)

    with pytest.raises(ValueError, match=eid(1)):
        compare(truth, records, notebook, horizon=1440.0)


def test_un_hecho_pendiente_o_perdido_no_rompe_el_retraso():
    """Las filas sin `registro` (perdido, pendiente) no tienen registro que medir: el retraso se
    calcula solo con lo escrito."""
    truth = hand_truth((0, "patient_arrived", 1, ARRIVED), (5, "triage_completed", 1, TRIAGED))
    records, _ = faithful(truth)
    notebook = [
        NotebookRow(records[0].event_id, truth[0].event_id, GOOD, 0.0, 0.0),
        NotebookRow(None, truth[1].event_id, PENDING),
    ]

    comparison = compare(truth, records[:1], notebook, horizon=1440.0)

    assert comparison.reconciliation.by_kind[PENDING] == 1
    assert comparison.reconciliation.delay["triaje"] == DelayStats(0, None, None)
