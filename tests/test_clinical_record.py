"""El simulador del registro clínico: `record` con el dado forzado a mano (tarea 7.1).

Cada test dice qué error pilla. El escenario L y sus dos variantes llevan sus horas
calculadas a mano con código independiente de `record` (el cálculo, en el PR de la 7.1);
aquí van escritas como texto.

El perfil `prueba` son las tasas realistas de «Valores orientativos de partida», con tres
medianas cambiadas para que z = 0 dé los minutos del escenario: retraso de triaje [7, 15],
corrección [135, 720] y duplicado [0,5, 2]. La regla de los dados: todas las u (y la de
reserva) a 0,99, por encima de toda tasa, y todas las z a 0, salvo lo que diga cada test.
"""

import dataclasses
import math
from datetime import date

import pytest

from edsim.clinical_record import (
    CORRECTION,
    CORRECTION_PENDING,
    DUPLICATE,
    GOOD,
    LOST,
    NOTEBOOK_COLUMNS,
    PENDING,
    RECORD_CORRECTED,
    WITH_SLIPS,
    NotebookRow,
    Record,
    RecordProfile,
    Roll,
    Timed,
    notebook_csv,
    record,
    record_json,
)
from edsim.engine.events import (
    PROVISIONAL_SCHEMA_VERSION,
    EventLog,
    MemorySink,
    to_json,
)
from edsim.lognormal import Z90

START = date(2026, 1, 5)
RUN = "r2026"
SEED = 7
DERIVED = "r2026_prueba_s7"
HORIZON = 1440.0
QUIET = 0.99
"""Un uniforme por encima de todas las tasas del perfil `prueba`: ningún despiste."""


def iso(clock: str) -> str:
    """La hora del día 5 de enero de 2026, como la escribe `event_time`."""
    return f"2026-01-05T{clock}.000+01:00"


def eid(number: int) -> str:
    return f"{DERIVED}-{number:09d}"


def make_roll(**changes: float) -> Roll:
    """Una tirada con la regla por defecto (u = 0,99, z = 0) y los cambios dados."""
    values = {f.name: (0.0 if f.name.startswith("z_") else QUIET) for f in dataclasses.fields(Roll)}
    values.update(changes)
    return Roll(**values)


class HandDice:
    """Un dado que devuelve las tiradas dadas, en orden, y cuenta cuántas se pidieron."""

    def __init__(self, rolls=(), default=None):
        self.rolls = list(rolls)
        self.default = default
        self.calls = 0

    def roll(self) -> Roll:
        self.calls += 1
        if self.rolls:
            return self.rolls.pop(0)
        if self.default is None:
            raise AssertionError("the test gave fewer rolls than patient events")
        return self.default


def make_profile(name="prueba", **changes) -> RecordProfile:
    values = {
        "name": name,
        "forget": 0.005,
        "empty": 0.01,
        "wrong": 0.01,
        "duplicate": Timed(0.005, (0.5, 2.0)),
        "correction": Timed(0.5, (135.0, 720.0)),
        "delay": {
            "admision": Timed(0.10, (1.0, 5.0)),
            "triaje": Timed(0.60, (7.0, 15.0)),
            "his": Timed(0.70, (10.0, 45.0)),
            "lab": Timed(0.05, (1.0, 3.0)),
        },
        "clock": {"admision": 0.0, "triaje": 2.0, "his": 0.0, "lab": -1.0},
    }
    values.update(changes)
    return RecordProfile(**values)


def clean_profile() -> RecordProfile:
    zero = Timed(0.0, (1.0, 2.0))
    return make_profile(
        name="limpio",
        forget=0.0,
        empty=0.0,
        wrong=0.0,
        duplicate=zero,
        correction=zero,
        delay=dict.fromkeys(("admision", "triaje", "his", "lab"), zero),
        clock=dict.fromkeys(("admision", "triaje", "his", "lab"), 0.0),
    )


def scenario_l():
    """El log verdadero del escenario L, en la versión 4, con el minuto 0 a las 0:00."""
    sink = MemorySink()
    log = EventLog(RUN, START, sink, schema_version=4)
    log.emit("patient_arrived", 1020.0, arrival_id=1, medio="propios_medios")
    log.emit("patient_registered", 1022.5, arrival_id=1, edad=54, sexo="mujer")
    log.emit("triage_completed", 1024.2, arrival_id=1, nivel=3, motivo="dolor_toracico")
    log.emit("patient_arrived", 1028.0, arrival_id=2, medio="ambulancia")
    log.emit("assessment_started", 1060.0, arrival_id=1, tipo="inicial", pool="medicos", box=1)
    log.emit("patient_departed", 1135.0, arrival_id=1, destino="alta")
    return sink.events


def scenario_l_dice(u_wrong_l3=0.005) -> HandDice:
    return HandDice(
        [
            make_roll(),  # L1
            make_roll(),  # L2
            make_roll(  # L3
                u_delay=0.0,
                u_wrong=u_wrong_l3,
                u_wrong_field=0.0,
                u_wrong_value=0.9,
                u_correction=0.0,
            ),
            make_roll(),  # L4
            make_roll(u_duplicate=0.0),  # L5
            make_roll(u_forget=0.0),  # L6
        ]
    )


def run_l(profile=None, u_wrong_l3=0.005):
    return record(
        scenario_l(),
        profile or make_profile(),
        SEED,
        horizon=HORIZON,
        run_id=RUN,
        dice=scenario_l_dice(u_wrong_l3),
    )


def table(recording):
    return [
        (r.event_type, r.episode_id, r.sim_time, r.event_time, r.recorded_time, dict(r.payload))
        for r in recording.records
    ]


L_ROWS = [
    ("patient_arrived", "EP-000001", 1020.0, iso("17:00:00"), iso("17:00:00"),
     {"medio": "propios_medios"}),
    ("patient_registered", "EP-000001", 1022.5, iso("17:02:30"), iso("17:02:30"),
     {"edad": 54, "sexo": "mujer"}),
    ("patient_arrived", "EP-000002", 1028.0, iso("17:08:00"), iso("17:08:00"),
     {"medio": "ambulancia"}),
    ("triage_completed", "EP-000001", 1031.2, iso("17:06:12"), iso("17:13:12"),
     {"nivel": 4, "motivo": "dolor_toracico"}),
    ("assessment_started", "EP-000001", 1060.0, iso("17:40:00"), iso("17:40:00"),
     {"tipo": "inicial", "pool": "medicos", "box": 1}),
    ("assessment_started", "EP-000001", 1060.5, iso("17:40:00"), iso("17:40:30"),
     {"tipo": "inicial", "pool": "medicos", "box": 1}),
]  # fmt: skip
L_CORRECTION = (
    RECORD_CORRECTED, "EP-000001", 1166.2, iso("19:28:12"), iso("19:28:12"),
    {"corrige": eid(4), "campos": {"nivel": 3}},
)  # fmt: skip


# --- Escenario L --------------------------------------------------------------------


def test_escenario_l_registros():
    """Las siete filas de la especificación: orden, sim_time, las dos horas y el payload.

    Pilla el reloj metido en sim_time (V3), la emisión por event_time (V2) y una
    corrección que apunta a la verdad (V5).
    """
    recording = run_l()

    assert table(recording) == [*L_ROWS, L_CORRECTION]
    triage = recording.records[3]
    assert triage.source_system == "triaje"
    correction = recording.records[6]
    assert (correction.source_system, correction.schema_version) == ("triaje", 4)
    assert all(r.ingest_time is None for r in recording.records)


def test_escenario_l_identificadores():
    """El run_id derivado y los event_id renumerados desde 1, sin huecos (V1)."""
    recording = run_l()

    assert recording.run_id == DERIVED
    assert [r.event_id for r in recording.records] == [eid(n) for n in range(1, 8)]
    assert {r.run_id for r in recording.records} == {DERIVED}


def test_escenario_l_libreta():
    """Una fila por registro y una por el olvidado; retraso_min con una sola definición."""
    events = scenario_l()
    truth = [e.event_id for e in events]
    recording = run_l()

    assert list(recording.notebook) == [
        NotebookRow(eid(1), truth[0], GOOD, 0.0, 0.0),
        NotebookRow(eid(2), truth[1], GOOD, 0.0, 0.0),
        NotebookRow(eid(3), truth[3], GOOD, 0.0, 0.0),
        NotebookRow(eid(4), truth[2], WITH_SLIPS, 7.0, 2.0, wrong_field="nivel",
                    true_value=3, recorded_value=4),
        NotebookRow(eid(5), truth[4], GOOD, 0.0, 0.0),
        NotebookRow(eid(6), truth[4], DUPLICATE, 0.5, 0.0, duplicate_of=eid(5)),
        NotebookRow(eid(7), truth[2], CORRECTION, 142.0, 2.0, wrong_field="nivel",
                    true_value=3, corrects=eid(4)),
        NotebookRow(None, truth[5], LOST),
    ]  # fmt: skip


def test_escenario_l_cuenta():
    """6 hechos = 4 + 1 + 1 + 0; 7 registros = 4 + 1 + 1 + 1; 1 corrección escrita."""
    info = run_l().info

    assert info["cuenta"] == {
        "hechos_pacientes": 6, "bien": 4, "con_despistes": 1, "perdido": 1, "pendiente": 0,
        "hechos_recursos": 0, "recursos_bien": 0, "recursos_pendiente": 0,
        "registros": 7, "duplicado": 1, "correccion": 1, "correccion_pendiente": 0,
        "erroneos_con_correccion": 1,
    }  # fmt: skip
    assert {k: info[k] for k in ("run_id", "run_id_origen", "perfil", "semilla", "horizonte")} == {
        "run_id": DERIVED,
        "run_id_origen": RUN,
        "perfil": "prueba",
        "semilla": SEED,
        "horizonte": HORIZON,
    }


def test_variante_corte():
    """Con la corrección a los 500 min, 1.531,2 ≥ 1.440: no se escribe (V6)."""
    profile = make_profile(correction=Timed(0.5, (500.0, 720.0)))
    truth = [e.event_id for e in scenario_l()]
    recording = run_l(profile)

    assert table(recording) == L_ROWS
    assert recording.notebook[-2:] == (
        NotebookRow(None, truth[2], CORRECTION_PENDING, wrong_field="nivel", true_value=3,
                    corrects=eid(4)),
        NotebookRow(None, truth[5], LOST),
    )  # fmt: skip
    cuenta = recording.info["cuenta"]
    assert (cuenta["registros"], cuenta["correccion"], cuenta["correccion_pendiente"]) == (6, 0, 1)
    assert cuenta["bien"] + cuenta["con_despistes"] + cuenta["perdido"] + cuenta["pendiente"] == 6


def test_variante_dado():
    """El mismo 0,03 en L3: el realista (0,01) no altera el nivel; el hostil (0,07), sí."""
    realista = run_l(make_profile(name="realista", wrong=0.01), u_wrong_l3=0.03)
    hostil = run_l(make_profile(name="hostil", wrong=0.07), u_wrong_l3=0.03)

    unchanged = L_ROWS[3][:5] + ({"nivel": 3, "motivo": "dolor_toracico"},)
    assert table(realista) == [*L_ROWS[:3], unchanged, *L_ROWS[4:]]
    assert realista.notebook[3].kind == WITH_SLIPS  # el retraso y el reloj siguen
    assert realista.notebook[3].wrong_field is None
    assert realista.info["cuenta"]["correccion"] == 0
    assert table(hostil) == [*L_ROWS, L_CORRECTION[:5] + ({"corrige": "r2026_hostil_s7-000000004",
                                                           "campos": {"nivel": 3}},)]  # fmt: skip


# --- Cada despiste por separado --------------------------------------------------------


def one_patient(schema_version=4):
    """Un paciente con un evento de cada sistema con campos, en la versión dada."""
    sink = MemorySink()
    log = EventLog(RUN, START, sink, schema_version=schema_version)
    if schema_version == PROVISIONAL_SCHEMA_VERSION:
        log.emit("patient_arrived", 100.0, arrival_id=1)
        log.emit("triage_completed", 110.0, arrival_id=1, nivel=3)
        log.emit("patient_departed", 300.0, arrival_id=1, destino="alta")
    else:
        log.emit("patient_arrived", 100.0, arrival_id=1, medio="ambulancia")
        log.emit("patient_registered", 102.0, arrival_id=1, edad=67, sexo="hombre")
        log.emit("triage_completed", 110.0, arrival_id=1, nivel=3, motivo="disnea")
        log.emit("patient_departed", 300.0, arrival_id=1, destino="alta")
    return sink.events


def run_one(events, rolls, profile=None, horizon=HORIZON):
    dice = HandDice(rolls, default=make_roll())
    return record(events, profile or make_profile(), SEED, horizon=horizon, run_id=RUN, dice=dice)


def test_despiste_olvido_sin_retraso_duplicado_ni_correccion():
    """Un olvidado no deja nada, aunque sus otros números pidan todos los despistes."""
    everything = make_roll(
        u_forget=0.0, u_delay=0.0, u_wrong=0.0, u_empty=0.0, u_correction=0.0, u_duplicate=0.0
    )
    events = one_patient()
    recording = run_one(events, [make_roll(), make_roll(), everything])

    assert [r.event_type for r in recording.records] == [
        "patient_arrived",
        "patient_registered",
        "patient_departed",
    ]
    assert recording.notebook[-1] == NotebookRow(None, events[2].event_id, LOST)
    assert recording.info["cuenta"]["perdido"] == 1


def test_despiste_retraso_por_sistema_y_umbral_estricto():
    """El retraso es el cuantil de su sistema; con u igual a la tasa no hay retraso."""
    events = one_patient()
    rolls = [
        make_roll(u_delay=0.0, z_delay=Z90),  # admisión: el p90, 5 min
        make_roll(u_delay=0.10),  # admisión, u = tasa: sin retraso
    ]
    recording = run_one(events, rolls, profile=make_profile(clock=dict.fromkeys(
        ("admision", "triaje", "his", "lab"), 0.0)))  # fmt: skip

    arrived = next(r for r in recording.records if r.event_type == "patient_arrived")
    registered = next(r for r in recording.records if r.event_type == "patient_registered")
    assert arrived.sim_time == pytest.approx(105.0, rel=1e-12)
    assert arrived.event_time == iso("01:40:00")
    assert arrived.recorded_time == iso("01:45:00")
    assert registered.sim_time == 102.0
    # El desorden sale del retraso: la llegada (105) se anota después del registro (102).
    assert [r.event_type for r in recording.records[:2]] == [
        "patient_registered",
        "patient_arrived",
    ]
    assert [(row.kind, row.delay_min) for row in recording.notebook[:2]] == [
        (GOOD, 0.0),
        (WITH_SLIPS, pytest.approx(5.0, rel=1e-12)),
    ]


def test_despiste_reloj_mueve_las_horas_y_nunca_sim_time():
    """Un desfase de −1,5 min mueve event_time y recorded_time; sim_time queda (V3)."""
    profile = make_profile(clock={"admision": -1.5, "triaje": 0.0, "his": 0.0, "lab": 0.0})
    recording = run_one(one_patient(), [], profile=profile)

    arrived = recording.records[0]
    assert arrived.sim_time == 100.0
    assert (arrived.event_time, arrived.recorded_time) == (
        "2026-01-05T01:38:30.000+01:00",
        "2026-01-05T01:38:30.000+01:00",
    )
    assert (recording.notebook[0].kind, recording.notebook[0].clock_min) == (WITH_SLIPS, -1.5)
    assert recording.records[2].event_time == iso("01:50:00")  # triaje, sin desfase


@pytest.mark.parametrize(
    ("true_level", "u", "expected"), [(1, 0.9, 2), (5, 0.1, 4), (3, 0.1, 2), (3, 0.5, 4)]
)
def test_valor_erroneo_nivel_mas_menos_uno_y_hacia_dentro_en_los_bordes(true_level, u, expected):
    sink = MemorySink()
    log = EventLog(RUN, START, sink, schema_version=4)
    log.emit("triage_completed", 10.0, arrival_id=1, nivel=true_level, motivo="disnea")
    recording = run_one(sink.events, [make_roll(u_wrong=0.0, u_wrong_field=0.0, u_wrong_value=u)])

    assert recording.records[0].payload["nivel"] == expected
    row = recording.notebook[0]
    assert (row.wrong_field, row.true_value, row.recorded_value) == ("nivel", true_level, expected)


@pytest.mark.parametrize(
    ("age", "expected"), [(67, 76), (54, 45), (20, 2), (99, 100), (55, 56), (7, 8), (101, 102)]
)
def test_valor_erroneo_edad_con_las_cifras_invertidas(age, expected):
    """Literal: 20 pasa a 2 y 99 a 100, errores inverosímiles a propósito."""
    sink = MemorySink()
    EventLog(RUN, START, sink, schema_version=4).emit(
        "patient_registered", 10.0, arrival_id=1, edad=age, sexo="mujer"
    )
    recording = run_one(sink.events, [make_roll(u_wrong=0.0)])

    assert recording.records[0].payload["edad"] == expected


def test_valor_erroneo_motivo_es_otro_del_catalogo():
    from edsim.profiles.config import REASON_KEYS

    sink = MemorySink()
    EventLog(RUN, START, sink, schema_version=4).emit(
        "triage_completed", 10.0, arrival_id=1, nivel=3, motivo="disnea"
    )
    others = [k for k in REASON_KEYS if k != "disnea"]
    for i, expected in enumerate(others):
        u = (i + 0.5) / len(others)
        recording = run_one(
            sink.events, [make_roll(u_wrong=0.0, u_wrong_field=0.75, u_wrong_value=u)]
        )
        assert recording.records[0].payload["motivo"] == expected
    assert len(others) == 16


@pytest.mark.parametrize(
    ("version", "u", "expected"),
    [(1, 0.0, "ingreso"), (1, 0.99, "ingreso"), (4, 0.0, "ingreso"), (4, 0.5, "traslado"),
     (4, 0.99, "exitus")],
)  # fmt: skip
def test_valor_erroneo_destino_de_su_version(version, u, expected):
    """En las versiones 1 a 3 solo hay otro destino; en la 4, tres."""
    sink = MemorySink()
    EventLog(RUN, START, sink, schema_version=version).emit(
        "patient_departed", 10.0, arrival_id=1, destino="alta"
    )
    recording = run_one(sink.events, [make_roll(u_wrong=0.0, u_wrong_value=u)])

    assert recording.records[0].payload["destino"] == expected


def test_campo_vacio_elige_entre_los_no_alterados():
    """Con nivel alterado, el vacío solo puede caer en motivo, sea cual sea u_campo_vacio."""
    sink = MemorySink()
    EventLog(RUN, START, sink, schema_version=4).emit(
        "triage_completed", 10.0, arrival_id=1, nivel=3, motivo="disnea"
    )
    for u_field in (0.0, 0.99):
        roll = make_roll(u_wrong=0.0, u_wrong_field=0.0, u_empty=0.0, u_empty_field=u_field)
        recording = run_one(sink.events, [roll])
        assert dict(recording.records[0].payload) == {"nivel": 4, "motivo": None}
        assert recording.notebook[0].empty_field == "motivo"


def test_campo_vacio_sin_campos_elegibles():
    """v1: patient_arrived no tiene payload; triage_completed solo tiene el nivel alterado."""
    everything = make_roll(u_wrong=0.0, u_empty=0.0)
    recording = run_one(one_patient(PROVISIONAL_SCHEMA_VERSION), [everything, everything])

    assert dict(recording.records[0].payload) == {}
    assert dict(recording.records[1].payload) == {"nivel": 4}
    assert [row.empty_field for row in recording.notebook] == [None, None, None]
    assert recording.notebook[0].kind == GOOD


def test_campo_vacio_en_cualquier_campo_del_payload():
    """El vacío no se limita a los cuatro campos del valor erróneo: sexo también vale."""
    events = one_patient()
    recording = run_one(events, [make_roll(), make_roll(u_empty=0.0, u_empty_field=0.9)])

    assert dict(recording.records[1].payload) == {"edad": 67, "sexo": None}


def test_correccion_solo_si_hubo_valor_erroneo():
    recording = run_one(one_patient(), [make_roll(u_correction=0.0)] * 4)

    assert RECORD_CORRECTED not in {r.event_type for r in recording.records}


def test_duplicado_copia_el_registro_ya_alterado():
    """La copia lleva el valor erróneo y el vacío, su propio número y la hora del original."""
    sink = MemorySink()
    EventLog(RUN, START, sink, schema_version=4).emit(
        "triage_completed", 10.0, arrival_id=1, nivel=3, motivo="disnea"
    )
    roll = make_roll(u_wrong=0.0, u_wrong_field=0.0, u_empty=0.0, u_duplicate=0.0, z_duplicate=Z90)
    original, copy = run_one(sink.events, [roll]).records

    assert dict(copy.payload) == dict(original.payload) == {"nivel": 4, "motivo": None}
    assert (original.event_id, copy.event_id) == (eid(1), eid(2))
    assert copy.event_time == original.event_time == iso("00:12:00")  # reloj de triaje +2
    assert copy.sim_time == pytest.approx(12.0, rel=1e-12)  # 10 + el p90 del duplicado, 2
    assert copy.recorded_time == iso("00:14:00")


def test_orden_de_emision_en_el_empate():
    """Mismo sim_time registrado: primero el evento verdadero anterior, después el original
    antes que su duplicado y que su corrección."""
    sink = MemorySink()
    log = EventLog(RUN, START, sink, schema_version=4)
    log.emit("assessment_started", 1000.0, arrival_id=1, tipo="inicial", pool="medicos", box=1)
    log.emit("assessment_started", 1010.0, arrival_id=2, tipo="inicial", pool="medicos", box=2)
    log.emit("assessment_started", 1010.0, arrival_id=3, tipo="inicial", pool="medicos", box=3)
    rolls = [make_roll(u_delay=0.0), make_roll(), make_roll()]  # his [10, 45]: 1000 + 10 = 1010
    recording = run_one(sink.events, rolls)

    assert [r.episode_id for r in recording.records] == ["EP-000001", "EP-000002", "EP-000003"]
    assert {r.sim_time for r in recording.records} == {1010.0}


def test_corte_hecho_pendiente():
    """Un hecho retrasado hasta el horizonte no se escribe; su duplicado no tiene fila."""
    sink = MemorySink()
    EventLog(RUN, START, sink, schema_version=4).emit(
        "assessment_started", 1430.0, arrival_id=1, tipo="inicial", pool="medicos", box=1
    )
    roll = make_roll(u_delay=0.0, u_duplicate=0.0)  # his: 1430 + 10 = 1440
    recording = run_one(sink.events, [roll])

    assert recording.records == ()
    assert recording.notebook == (NotebookRow(None, sink.events[0].event_id, PENDING),)
    assert recording.info["cuenta"]["pendiente"] == 1


@pytest.mark.parametrize("field", ["z_delay", "z_duplicate", "z_correction"])
def test_una_z_enorme_cae_tras_el_horizonte_sin_romper_las_horas(field):
    """Lo que no se escribe no necesita hora: z = 40 lo lleva más allá de cualquier fecha."""
    sink = MemorySink()
    EventLog(RUN, START, sink, schema_version=4).emit(
        "triage_completed", 1430.0, arrival_id=1, nivel=3, motivo="disnea"
    )
    draws = {
        "z_delay": {"u_delay": 0.0},
        "z_duplicate": {"u_duplicate": 0.0},
        "z_correction": {"u_wrong": 0.0, "u_wrong_field": 0.0, "u_correction": 0.0},
    }[field]
    recording = run_one(sink.events, [make_roll(**draws, **{field: 40.0})])

    # Con el retraso, ni el hecho se escribe; con el duplicado o la corrección, solo el hecho.
    assert len(recording.records) == (0 if field == "z_delay" else 1)
    assert recording.info["cuenta"]["pendiente"] == (1 if field == "z_delay" else 0)


def test_la_clase_sale_de_lo_escrito_no_de_lo_sorteado():
    """Un desfase que redondea a 0 ms y un retraso que no mueve sim_time no son despistes."""
    profile = make_profile(clock={"admision": 1e-6, "triaje": 0.0, "his": 0.0, "lab": 0.0})
    roll = make_roll(u_delay=0.0, z_delay=-1000.0)  # admisión: 1 · exp(-1000·sigma) ≈ 0
    recording = run_one(scenario_l()[:1], [roll], profile=profile)

    arrived = recording.records[0]
    first = scenario_l()[0]
    assert (arrived.sim_time, arrived.event_time, arrived.recorded_time) == (
        first.sim_time,
        first.event_time,
        first.event_time,
    )
    assert (recording.notebook[0].kind, recording.notebook[0].delay_min) == (GOOD, 0.0)


@pytest.mark.parametrize(("horizon", "written"), [(1020.0 + 1e-9, 1), (1020.0, 0)])
def test_el_horizonte_es_exclusivo(horizon, written):
    recording = run_one(scenario_l()[:1], [], horizon=horizon)

    assert len(recording.records) == written


# --- Identidad, consumo, recursos y pureza -------------------------------------------


@pytest.mark.parametrize("seed", [10**60, -1, True, 1.0])
def test_run_id_derivado_invalido_es_error_antes_de_tirar(seed):
    dice = HandDice(default=make_roll())
    with pytest.raises(ValueError, match="seed|derived run_id"):
        record(scenario_l(), make_profile(), seed, horizon=HORIZON, run_id=RUN, dice=dice)
    assert dice.calls == 0


def test_run_id_derivado_que_no_cabe_es_error():
    dice = HandDice(default=make_roll())
    long_run = "r" * 60  # r…r_prueba_s7 tiene 70 caracteres
    with pytest.raises(ValueError, match="derived run_id"):
        record([], make_profile(), SEED, horizon=HORIZON, run_id=long_run, dice=dice)
    assert dice.calls == 0


def test_un_log_de_otra_ejecucion_es_error_antes_de_tirar():
    """registro.json nombraría un origen equivocado: el log debe ser del run_id dado."""
    dice = HandDice(default=make_roll())
    with pytest.raises(ValueError, match="not of run 'r7'"):
        record(scenario_l(), make_profile(), SEED, horizon=HORIZON, run_id="r7", dice=dice)
    assert dice.calls == 0


def mixed_log():
    """Dos pacientes y dos cambios de plantilla (eventos de recursos)."""
    sink = MemorySink()
    log = EventLog(RUN, START, sink, schema_version=4)
    log.emit("staffing_changed", 0.0, recurso="medicos", anterior=0, nueva=3)
    log.emit("patient_arrived", 5.0, arrival_id=1, medio="ambulancia")
    log.emit("patient_arrived", 6.0, arrival_id=2, medio="propios_medios")
    log.emit("staffing_changed", 480.0, recurso="medicos", anterior=3, nueva=4)
    log.emit("patient_departed", 500.0, arrival_id=1, destino="ingreso")
    return sink.events


@pytest.mark.parametrize("profile", [clean_profile(), make_profile(forget=1.0, wrong=1.0)])
def test_consumo_fijo_una_tirada_por_evento_de_paciente(profile):
    """Tres eventos de pacientes, tres tiradas, con el perfil limpio y con todo olvidado."""
    dice = HandDice(default=make_roll(u_forget=0.5, u_wrong=0.5))
    record(mixed_log(), profile, SEED, horizon=HORIZON, run_id=RUN, dice=dice)

    assert dice.calls == 3


def test_los_recursos_pasan_tal_cual_renumerados():
    events = mixed_log()
    hostile = make_profile(forget=1.0)  # todos los pacientes olvidados
    recording = record(
        events, hostile, SEED, horizon=HORIZON, run_id=RUN, dice=HandDice(default=make_roll())
    )

    staffing = [e for e in events if e.event_type == "staffing_changed"]
    assert [(r.event_id, r.sim_time, r.event_time, r.recorded_time, dict(r.payload))
            for r in recording.records] == [
        (eid(1), 0.0, staffing[0].event_time, staffing[0].event_time, dict(staffing[0].payload)),
        (eid(2), 480.0, staffing[1].event_time, staffing[1].event_time, dict(staffing[1].payload)),
    ]  # fmt: skip
    assert [r.kind for r in recording.notebook] == [GOOD, GOOD, LOST, LOST, LOST]
    cuenta = recording.info["cuenta"]
    assert (cuenta["hechos_recursos"], cuenta["recursos_bien"], cuenta["hechos_pacientes"]) == (
        2,
        2,
        3,
    )


def test_el_json_de_record_es_el_de_to_json():
    """Mismas claves y en el mismo orden que el log de eventos."""
    event = scenario_l()[2]
    values = {f.name: getattr(event, f.name) for f in dataclasses.fields(event)}

    assert record_json(Record(**values)) == to_json(event)
    assert [f.name for f in dataclasses.fields(Record)] == [
        f.name for f in dataclasses.fields(event)
    ]


def test_un_campo_vacio_se_escribe_como_null():
    sink = MemorySink()
    EventLog(RUN, START, sink, schema_version=4).emit(
        "test_resulted", 10.0, arrival_id=1, resultados={"analitica": "normal"}
    )
    recording = run_one(sink.events, [make_roll(u_empty=0.0)])

    assert '"payload": {"resultados": null}' in record_json(recording.records[0])


def test_es_pura_los_mismos_bytes():
    first, second = run_l(), run_l()

    assert [record_json(r) for r in first.records] == [record_json(r) for r in second.records]
    assert notebook_csv(first.notebook) == notebook_csv(second.notebook)
    assert first.info == second.info


def test_log_vacio():
    recording = record([], make_profile(), SEED, horizon=HORIZON, run_id=RUN, dice=HandDice())

    assert (recording.records, recording.notebook) == ((), ())
    assert recording.info["cuenta"]["registros"] == 0


def test_un_log_que_no_sale_de_eventlog_es_error():
    events = list(scenario_l())
    events[3] = dataclasses.replace(events[3], event_time=iso("17:08:01"))
    with pytest.raises(ValueError, match="is not the one of sim_time"):
        record(events, make_profile(), SEED, horizon=HORIZON, run_id=RUN, dice=scenario_l_dice())


@pytest.mark.parametrize(
    "horizon", [0.0, -1.0, math.nan, math.inf, True], ids=["cero", "neg", "nan", "inf", "bool"]
)
def test_horizonte_invalido(horizon):
    with pytest.raises(ValueError, match="horizon"):
        record(scenario_l(), make_profile(), SEED, horizon=horizon, run_id=RUN, dice=HandDice())


# --- La tirada, el perfil y la libreta --------------------------------------------


def test_la_tirada_tiene_13_numeros_en_su_orden():
    names = [f.name for f in dataclasses.fields(Roll)]
    assert names == [
        "u_forget", "u_delay", "z_delay", "u_wrong", "u_wrong_field", "u_wrong_value",
        "u_empty", "u_empty_field", "u_correction", "z_correction", "u_duplicate",
        "z_duplicate", "spare",
    ]  # fmt: skip
    assert Roll.from_numbers([0.0] * 13).spare == 0.0
    for numbers in ([0.5] * 12, [0.5] * 14):
        with pytest.raises(ValueError, match="13 numbers"):
            Roll.from_numbers(numbers)


@pytest.mark.parametrize(
    "changes",
    [{"u_forget": 1.0}, {"u_delay": -0.1}, {"u_wrong": math.nan}, {"z_delay": math.inf},
     {"spare": math.nan}, {"u_empty": True}],
)  # fmt: skip
def test_tirada_invalida(changes):
    with pytest.raises(ValueError):
        make_roll(**changes)


def test_el_cuantil_en_z_cero_es_la_mediana_exacta():
    assert Timed(0.6, (7.0, 15.0)).quantile(0.0) == 7.0
    assert Timed(0.6, (7.0, 15.0)).quantile(Z90) == pytest.approx(15.0, rel=1e-12)
    assert math.exp(math.log(7.0)) != 7.0  # por qué no se escribe exp(mu + sigma·z)


@pytest.mark.parametrize(
    "changes",
    [{"forget": 1.5}, {"wrong": math.nan}, {"clock": {"admision": 0.0}},
     {"delay": {"admision": Timed(0.1, (1.0, 5.0))}}, {"name": ""}],
)  # fmt: skip
def test_perfil_invalido(changes):
    with pytest.raises(ValueError):
        make_profile(**changes)
    with pytest.raises(ValueError):
        Timed(0.1, (5.0, 5.0))


def test_la_libreta_en_csv():
    text = notebook_csv(run_l().notebook)
    lines = text.splitlines()

    assert lines[0] == ",".join(NOTEBOOK_COLUMNS)
    assert lines[4] == f"{eid(4)},r2026-000000002,con_despistes,7.0,2.0,,nivel,3,4,,"
    assert lines[-1] == ",r2026-000000005,perdido,,,,,,,,"
    assert text.endswith("\n") and len(lines) == 9
