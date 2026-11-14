"""Auxiliares de los tests del registro clínico (tareas 7.1 a 7.3).

Un log verdadero sintético, un perfil escandaloso en código (para que cada despiste ocurra de
verdad), un dado contador con tope (`check_calls` de `runaway.py`: ningún doble de prueba se
llama en bucle sin un tope que lance un error, lección de la 7.5) y el escenario L de la 7.1
con su dado forzado a mano, que usan los tests de `record` y los de la comparación.
"""

import dataclasses
from datetime import date
from pathlib import Path

from runaway import check_calls

from edsim.clinical_record import RecordProfile, Roll, Timed, record
from edsim.engine.events import EventLog, MemorySink

START = date(2026, 1, 5)
RUN = "r2026"
PROFILES_FILE = Path(__file__).resolve().parent.parent / "config" / "registro_clinico.toml"
"""Los tres perfiles reales del repositorio."""

SYSTEMS = ("admision", "triaje", "his", "lab")
MOTIVES = ("traumatismo", "fiebre", "disnea", "dolor_toracico", "otros", "sincope")
DESTINATIONS = ("alta", "ingreso", "traslado", "exitus")


class CountingDice:
    """Envuelve un dado, cuenta las tiradas y lanza `RunawayLoop` al pasar de `limit`."""

    def __init__(self, inner, limit: int = 1_000_000):
        self.inner = inner
        self.limit = limit
        self.calls = 0

    def roll(self):
        self.calls += 1
        check_calls(self.calls, self.limit, "CountingDice.roll")
        return self.inner.roll()


def patient_log(patients: int, *, spacing: float = 1.5, schema_version: int = 4) -> list:
    """El log verdadero de `patients` pacientes en la versión 4, más un evento de recursos cada 100.

    Cada paciente tiene siete hechos (llegada, registro con edad y sexo, inicio de triaje,
    triaje con nivel y motivo, valoración, decisión de destino y salida), repartidos en 80
    minutos; `spacing` minutos entre llegadas. Los cuatro tipos con campo elegible para un valor
    erróneo (registro, triaje, decisión y salida) están en cada paciente, dos de ellos con un
    solo campo (`destino`).
    """
    steps = []
    for i in range(1, patients + 1):
        t = i * spacing
        medium = "ambulancia" if i % 5 == 0 else "propios_medios"
        registered = {"edad": 20 + i % 70, "sexo": "mujer" if i % 2 else "hombre"}
        circuit = "puerta" if i % 3 else "enfermeria"
        triaged = {"nivel": 1 + i % 5, "motivo": MOTIVES[i % len(MOTIVES)]}
        assessed = {"tipo": "inicial", "pool": "medicos", "box": 1 + i % 4}
        destination = {"destino": DESTINATIONS[i % 4]}
        steps += [
            (t, "patient_arrived", i, {"medio": medium}),
            (t + 0.5, "patient_registered", i, registered),
            (t + 2, "triage_started", i, {"circuito": circuit}),
            (t + 3, "triage_completed", i, triaged),
            (t + 10, "assessment_started", i, assessed),
            (t + 60, "disposition_decided", i, destination),
            (t + 80, "patient_departed", i, destination),
        ]
        if i % 100 == 0:
            steps.append(
                (t + 1, "staffing_changed", None, {"recurso": "medicos", "anterior": 3, "nueva": 4})
            )
    sink = MemorySink()
    log = EventLog(RUN, START, sink, schema_version=schema_version)
    for when, event_type, arrival, payload in sorted(steps, key=lambda s: s[0]):
        log.emit(event_type, when, arrival_id=arrival, **payload)
    return sink.events


def loud_profile(name: str = "ruidoso") -> RecordProfile:
    """Un perfil en código con todas las tasas altas: cada despiste ocurre en un log pequeño."""
    return RecordProfile(
        name=name,
        forget=0.1,
        empty=0.2,
        wrong=0.3,
        duplicate=Timed(0.2, (0.5, 2.0)),
        correction=Timed(0.5, (120.0, 720.0)),
        delay=dict.fromkeys(SYSTEMS, Timed(0.5, (2.0, 8.0))),
        clock={"admision": 1.0, "triaje": 2.0, "his": -1.0, "lab": 0.5},
    )


def clean_record_profile() -> RecordProfile:
    """Un perfil en código sin ningún despiste."""
    zero = Timed(0.0, (1.0, 2.0))
    return RecordProfile(
        name="limpio",
        forget=0.0,
        empty=0.0,
        wrong=0.0,
        duplicate=zero,
        correction=zero,
        delay=dict.fromkeys(SYSTEMS, zero),
        clock=dict.fromkeys(SYSTEMS, 0.0),
    )


# --- El escenario L de la 7.1, con el dado forzado a mano ------------------------------------

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
