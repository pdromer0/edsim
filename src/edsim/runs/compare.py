"""Compare persisted runs, checking common random numbers against exact draws."""

import math
from collections.abc import Mapping
from dataclasses import dataclass, fields
from types import MappingProxyType
from typing import Literal

from edsim.engine.ground_truth import EpisodeTruth
from edsim.runs.results import RunResults
from edsim.runs.truth import TRUTH_ABS_TOL_MINUTES
from edsim.runs.variants import center_diff

type PairingKind = Literal["same_draws", "different_draws"]
type DrawField = Literal[
    "level",
    "triage_time",
    "assessment_time",
    "reassessment_time",
    "needs_tests",
    "test_turnaround",
    "admitted",
]

DRAW_EFFECTS: Mapping[str, frozenset[DrawField]] = MappingProxyType(
    {
        "turnos.inicio": frozenset(),
        "recursos.enfermeria_triaje": frozenset(),
        "recursos.medicos": frozenset(),
        "recursos.boxes": frozenset(),
        "triaje.reparto_niveles": frozenset({"level", "needs_tests", "admitted"}),
        "duraciones.triaje": frozenset({"triage_time"}),
        "duraciones.valoracion": frozenset({"assessment_time"}),
        "duraciones.reevaluacion": frozenset({"reassessment_time"}),
        "duraciones.respuesta_pruebas": frozenset({"test_turnaround"}),
        "pruebas.probabilidad": frozenset({"needs_tests"}),
        "destino.probabilidad_ingreso": frozenset({"admitted"}),
    }
)
"""TOML key to draws it can affect; an immutable, exhaustive clinical contract."""

_DRAW_FIELDS: tuple[DrawField, ...] = (
    "level",
    "triage_time",
    "assessment_time",
    "reassessment_time",
    "needs_tests",
    "test_turnaround",
    "admitted",
)
_PAIRING_FIELDS = ("seed", "profile_fingerprint", "days", "warmup_days")


@dataclass(frozen=True, slots=True)
class MetadataDifference:
    """One changed RunInfo field, without formatting or normalization."""

    field: str
    a: int | float | str
    b: int | float | str


@dataclass(frozen=True, slots=True)
class DrawDifference:
    """Exact changed draws among all arrivals, including warm-up and censored ones."""

    field: DrawField
    changed: int
    total: int


@dataclass(frozen=True, slots=True)
class PairingInfo:
    """Configuration category checked against arrivals and all seven draws."""

    kind: PairingKind
    draw_differences: tuple[DrawDifference, ...]


class PairingCheckError(ValueError):
    """Saved truth contradicts the patients or the configured common random numbers."""

    def __init__(self, run_ids: tuple[str, str], field: str, affected: int, reason: str):
        self.run_ids = run_ids
        self.field = field
        self.affected = affected
        super().__init__(
            f"ground_truth_episodios.csv ({run_ids[0]} / {run_ids[1]}): "
            f"{field}, {affected} pacientes: {reason}"
        )


def _metadata_differences(a: RunResults, b: RunResults) -> tuple[MetadataDifference, ...]:
    return tuple(
        MetadataDifference(field.name, getattr(a.info, field.name), getattr(b.info, field.name))
        for field in fields(a.info)
        if getattr(a.info, field.name) != getattr(b.info, field.name)
    )


def pairing_blockers(a: RunResults, b: RunResults) -> tuple[MetadataDifference, ...]:
    """Return changed seed, profile fingerprint, days or warm-up, in that order.

    An empty tuple is configuration compatibility, not verified pairing.
    """
    return tuple(
        MetadataDifference(name, getattr(a.info, name), getattr(b.info, name))
        for name in _PAIRING_FIELDS
        if getattr(a.info, name) != getattr(b.info, name)
    )


def _checked_pairing(
    a: RunResults,
    b: RunResults,
    truth_a: Mapping[str, EpisodeTruth],
    truth_b: Mapping[str, EpisodeTruth],
) -> PairingInfo:
    if pairing_blockers(a, b):
        raise ValueError("compare_runs requires pairable configurations")
    run_ids = a.info.run_id, b.info.run_id
    for result, truth in ((a, truth_a), (b, truth_b)):
        table = {e.episode_id: e for e in result.analysis.table}
        if len(table) != len(result.analysis.table):
            raise PairingCheckError(run_ids, "episode_id", 1, "identificadores repetidos en el log")
        missing = table.keys() ^ truth.keys()
        if missing:
            raise PairingCheckError(
                run_ids,
                "episode_id",
                len(missing),
                f"la verdad y el log de {result.info.run_id} contienen pacientes distintos",
            )
        for field, count in (
            ("episode_id", sum(key != t.episode_id for key, t in truth.items())),
            (
                "arrival_time",
                sum(
                    not math.isclose(
                        table[key].arrival, t.arrival_time, abs_tol=TRUTH_ABS_TOL_MINUTES, rel_tol=0
                    )
                    for key, t in truth.items()
                ),
            ),
        ):
            if count:
                raise PairingCheckError(
                    run_ids, field, count, f"la verdad contradice el log de {result.info.run_id}"
                )
    missing = truth_a.keys() ^ truth_b.keys()
    if missing:
        raise PairingCheckError(run_ids, "episode_id", len(missing), "las llegadas no coinciden")
    arrivals = sum(t.arrival_time != truth_b[key].arrival_time for key, t in truth_a.items())
    if arrivals:
        raise PairingCheckError(
            run_ids, "arrival_time", arrivals, "los minutos de llegada difieren"
        )
    allowed = frozenset().union(*(DRAW_EFFECTS[d.key] for d in center_diff(a.center, b.center)))
    changes = tuple(
        DrawDifference(
            field,
            sum(getattr(t, field) != getattr(truth_b[key], field) for key, t in truth_a.items()),
            len(truth_a),
        )
        for field in _DRAW_FIELDS
    )
    for change in changes:
        if change.changed and change.field not in allowed:
            raise PairingCheckError(
                run_ids,
                change.field,
                change.changed,
                "ningún parámetro modificado puede cambiar este sorteo",
            )
    return PairingInfo("different_draws" if allowed else "same_draws", changes)
