"""Auxiliares de los tests del registro clínico de la tarea 7.2.

Un log verdadero sintético, un perfil escandaloso en código (para que cada despiste ocurra de
verdad) y un dado contador con tope: ningún doble de prueba se llama en bucle sin un tope que
lance un error (lección de la 7.5), para que una versión incorrecta que gire sin fin falle en
vez de colgar el test.
"""

from datetime import date
from pathlib import Path

from edsim.clinical_record import RecordProfile, Timed
from edsim.engine.events import EventLog, MemorySink

START = date(2026, 1, 5)
RUN = "r2026"
PROFILES_FILE = Path(__file__).resolve().parent.parent / "config" / "registro_clinico.toml"
"""Los tres perfiles reales del repositorio."""

SYSTEMS = ("admision", "triaje", "his", "lab")
MOTIVES = ("traumatismo", "fiebre", "disnea", "dolor_toracico", "otros", "sincope")
DESTINATIONS = ("alta", "ingreso", "traslado", "exitus")


class RunawayLoop(AssertionError):
    """Un doble se llamó más veces de las que el test admite: el código bajo prueba gira sin fin."""


class CountingDice:
    """Envuelve un dado, cuenta las tiradas y lanza `RunawayLoop` al pasar de `limit`."""

    def __init__(self, inner, limit: int = 1_000_000):
        self.inner = inner
        self.limit = limit
        self.calls = 0

    def roll(self):
        self.calls += 1
        if self.calls > self.limit:
            raise RunawayLoop(f"roll() was called more than {self.limit} times")
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
