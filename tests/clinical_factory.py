"""Pacientes clínicos hechos a mano y la respuesta esperada de la ronda, para los tests.

``expected_turnaround`` es el cálculo independiente de la respuesta de la ronda: la
franja del instante del pedido con ``context_indices`` y los factores
``respuesta_franja`` de los perfiles, sin pasar por ``ClinicalDraws``. Así un test
que lo usa no comparte un error de ``ClinicalDraws.round_turnaround`` (versiones
incorrectas V7 y V10 de la tarea 4.5a).
"""

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from edsim.engine.clinical import PatientDraws
from edsim.engine.clinical_sampler import ClinicalDraws, ClinicalTruth, TurnaroundShifts
from edsim.engine.events import CURRENT_CLINICAL_SCHEMA_VERSION, EventLog, MemorySink
from edsim.profiles.config import TEST_TYPES, ClinicalProfiles, load_profiles
from edsim.profiles.context import ArrivalContext, context_indices
from edsim.profiles.population import Person
from edsim.profiles.sampler import SeverityAndTriage
from edsim.profiles.severity import triage_quality
from edsim.profiles.workup import Workup

DATA = Path(__file__).parent / "data"
START = date(2026, 1, 5)  # fecha_inicio de llegadas_ejemplo.toml
BASES = (75.0, 70.0, 12.0, 200.0)  # respuesta base de analítica, radiografía, ECG e imagen


PLAIN = (float, int, bool, str, type(None))
"""Los tipos exactos de las hojas de una verdad clínica: ningún escalar de NumPy."""


def leaves(value, path=()):
    """Todas las hojas de un asdict, con su camino, recorriendo dicts y tuplas."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield from leaves(item, (*path, key))
    elif isinstance(value, tuple | list):
        for i, item in enumerate(value):
            yield from leaves(item, (*path, i))
    else:
        yield path, value


def example_profiles() -> ClinicalProfiles:
    return load_profiles(DATA / "perfiles_ejemplo.toml")


def ordered_of(*types: str) -> tuple[bool, ...]:
    """Pedida o no cada prueba, en el orden de TEST_TYPES."""
    unknown = set(types) - set(TEST_TYPES)
    assert not unknown, unknown
    return tuple(t in types for t in TEST_TYPES)


def hand_truth(
    *,
    level: int = 3,
    true_level: int | None = None,
    ordered: tuple[bool, ...] = (False,) * 4,
    abnormal: tuple[bool, ...] = (False,) * 4,
    turnarounds: tuple[float, ...] = BASES,
    reason: str = "otros",
    age: int = 50,
    female: bool = True,
    ambulance: bool = False,
) -> ClinicalTruth:
    """Una verdad clínica a mano; el nivel real es el asignado si no se da."""
    true_level = level if true_level is None else true_level
    quality, jump = triage_quality(level, true_level)
    band = 0 if age < 45 else 1 if age < 65 else 2 if age < 80 else 3
    return ClinicalTruth(
        context=ArrivalContext(0, 0, 0),
        person=Person(band=band, age=age, female=female, ambulance=ambulance),
        reason=reason,
        triage=SeverityAndTriage(
            z=0.25, severity=0.5, level=level, true_level=true_level, quality=quality, jump=jump
        ),
        workup=Workup(
            ordered=tuple(ordered),
            abnormal=tuple(abnormal),
            turnarounds=tuple(turnarounds),
            draws=(0.0,) * 12,
        ),
    )


def hand_patient(
    profiles: ClinicalProfiles,
    *,
    triage: float = 5.0,
    assessment: float = 20.0,
    reassessment: float = 10.0,
    admitted: bool = False,
    start: date = START,
    **truth: object,
) -> PatientDraws:
    """Los sorteos de un paciente clínico a mano, con los factores de ``profiles``."""
    clinical = ClinicalDraws(
        truth=hand_truth(**truth), shifts=TurnaroundShifts.from_profiles(profiles, start)
    )
    return PatientDraws(
        level=clinical.truth.triage.level,
        triage_time=triage,
        assessment_time=assessment,
        reassessment_time=reassessment,
        needs_tests=clinical.truth.workup.has_round,
        test_turnaround=None,
        admitted=admitted,
        clinical=clinical,
    )


def clinical_log(run_id: str = "clinico", start: date = START) -> tuple[EventLog, MemorySink]:
    sink = MemorySink()
    return EventLog(run_id, start, sink, schema_version=CURRENT_CLINICAL_SCHEMA_VERSION), sink


def expected_turnaround(
    profiles: ClinicalProfiles, start: date, workup: Workup, ordered_at: float
) -> float:
    """``max(factor_t(franja del pedido) × base_t)`` sobre las pruebas pedidas, aparte."""
    (band,), _, _ = context_indices([ordered_at], start, profiles.shift_band_starts)
    return max(
        test.turnaround_shift_factors[int(band)] * base
        for test, base, ordered in zip(
            profiles.diagnostic_tests, workup.turnarounds, workup.ordered, strict=True
        )
        if ordered
    )


# --- Escenario a mano de la sala de resultados (tarea 4.6a) ------------------------------
#
# Un solo box, de noche (2 enfermeras y 7 médicos), tres niveles 4 de «otros», mujeres de
# 50 años en medios propios:
#
# - A llega en 5, triaje de 5, box 1 en 10, valoración de 20; en 30 pide un ECG (base 12,
#   sin factor de franja) y deja el box (box_released). Los resultados llegan en 42.
# - B llega en 6 y espera box desde 11; lo recibe en 30, justo después de que A lo deje.
#   Valoración de 40, sin pruebas: sale en 70.
# - C llega en 20 y espera box desde 25, antes de que A vuelva (42). En 70 se libera el
#   box y lo recibe A, por su clave (4, 5) frente a (4, 20) de C: reevaluación de 10 y
#   salida en 80. C recibe el box en 80, valoración de 15 y sale en 95.
#
# A ocupa el box 20 + 10 = 30 minutos, no los 60 de su estancia en el box con la ronda.

ROOM_ARRIVALS = {"A": 5.0, "B": 6.0, "C": 20.0}


def room_patients(profiles: ClinicalProfiles) -> dict[float, PatientDraws]:
    """Los sorteos de A, B y C, por instante de llegada."""
    return {
        5.0: hand_patient(profiles, level=4, assessment=20.0, ordered=ordered_of("ecg")),
        6.0: hand_patient(profiles, level=4, assessment=40.0),
        20.0: hand_patient(profiles, level=4, assessment=15.0),
    }


def room_log(run_id: str = "clinico", *, c_first: bool = False) -> list:
    """El log del escenario de la sala hasta la última salida (minuto 95), escrito a mano.

    Con ``c_first``, el box que se libera en 70 va a C (valoración de 70 a 85) y A vuelve
    en 85: lo que haría la vuelta con una clave nueva (la hora de vuelta, 42), que C
    (llegada en 20) adelantaría. Es un log que nadie debe escribir.
    """
    log, sink = clinical_log(run_id)
    log.emit("staffing_changed", 0.0, recurso="enfermeria_triaje", anterior=0, nueva=2)
    log.emit("staffing_changed", 0.0, recurso="medicos", anterior=0, nueva=7)
    a, b, c = 0, 1, 2
    person = {"edad": 50, "sexo": "mujer"}

    def arrive(who, t):
        log.emit("patient_arrived", t, arrival_id=who, medio="propios_medios")
        log.emit("patient_registered", t, arrival_id=who, **person)
        log.emit("triage_started", t, arrival_id=who, circuito="enfermeria")

    def assess(who, t, tipo, box=1):
        log.emit("assessment_started", t, arrival_id=who, tipo=tipo, pool="medicos", box=box)

    def end(who, t, tipo):
        log.emit("assessment_ended", t, arrival_id=who, tipo=tipo, interrumpida=False)

    def leave(who, t):
        log.emit("disposition_decided", t, arrival_id=who, destino="alta")
        log.emit("patient_departed", t, arrival_id=who, destino="alta")

    arrive(a, 5.0)
    arrive(b, 6.0)
    log.emit("triage_completed", 10.0, arrival_id=a, nivel=4, motivo="otros")
    log.emit("box_assigned", 10.0, arrival_id=a, box=1)
    assess(a, 10.0, "inicial")
    log.emit("triage_completed", 11.0, arrival_id=b, nivel=4, motivo="otros")
    arrive(c, 20.0)
    log.emit("triage_completed", 25.0, arrival_id=c, nivel=4, motivo="otros")
    end(a, 30.0, "inicial")
    log.emit("test_ordered", 30.0, arrival_id=a, pruebas=["ecg"])
    log.emit("box_released", 30.0, arrival_id=a, box=1, espera="resultados")
    log.emit("box_assigned", 30.0, arrival_id=b, box=1)
    assess(b, 30.0, "inicial")
    log.emit("test_resulted", 42.0, arrival_id=a, resultados={"ecg": "normal"})
    end(b, 70.0, "inicial")
    leave(b, 70.0)
    first, second = ((c, "inicial", 15.0), (a, "reevaluacion", 10.0))
    if not c_first:
        first, second = second, first
    t = 70.0
    for who, tipo, minutes in (first, second):
        log.emit("box_assigned", t, arrival_id=who, box=1)
        assess(who, t, tipo)
        end(who, t + minutes, tipo)
        leave(who, t + minutes)
        t += minutes
    return sink.events


def truth_lines(episodes) -> str:
    """El EpisodeTruth entero de cada episodio, en el orden de sus campos, una línea JSON.

    La tarea 5.3 añadió al final el campo ``outcome``, que vale ``None`` con los modelos
    provisional y del hito 4. Se omite solo esa clave y solo cuando vale ``None``: así la
    representación de un episodio del hito 4 es la de antes, byte a byte, y la huella
    sigue probando que ningún campo antiguo cambió. Los demás ``None``
    (``test_turnaround``, ``clinical``) se quedan, porque ya formaban parte de la huella.
    """
    lines = []
    for e in episodes:
        data = asdict(e)
        if data["outcome"] is None:
            del data["outcome"]
        lines.append(
            json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
        )
    return "".join(lines)
