"""Pacientes clínicos hechos a mano y la respuesta esperada de la ronda, para los tests.

``expected_turnaround`` es el cálculo independiente de la respuesta de la ronda: la
franja del instante del pedido con ``context_indices`` y los factores
``respuesta_franja`` de los perfiles, sin pasar por ``ClinicalDraws``. Así un test
que lo usa no comparte un error de ``ClinicalDraws.round_turnaround`` (versiones
incorrectas V7 y V10 de la tarea 4.5a).
"""

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
