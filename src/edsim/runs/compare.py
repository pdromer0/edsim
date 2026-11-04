"""Compare persisted runs, checking common random numbers against exact draws."""

import math
from collections.abc import Mapping
from dataclasses import dataclass, fields
from types import MappingProxyType
from typing import Literal

import numpy as np

from edsim.engine.ground_truth import EpisodeTruth
from edsim.engine.report import SUMMARY_MEASURES
from edsim.runs.results import RunResults
from edsim.runs.truth import TRUTH_ABS_TOL_MINUTES
from edsim.runs.variants import CenterDifference, center_diff

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


type Number = int | float
type ChangeKind = Literal["improved", "worsened", "unchanged"]


@dataclass(frozen=True, slots=True)
class KPIComparison:
    """B minus A in the KPI's unit; relative change is a fraction, or undefined."""

    field: str
    a: Number | None
    b: Number | None
    difference: Number | None
    relative_change: float | None


@dataclass(frozen=True, slots=True)
class WaitStatistics:
    """One completed-episode measure, in minutes; missing without patients."""

    measure: str
    mean: float | None
    p90: float | None


@dataclass(frozen=True, slots=True)
class LevelRunSummary:
    """Completed patients, five measures and pooled Manchester exceedance fraction."""

    n: int
    waits: tuple[WaitStatistics, ...]
    max_wait: float
    exceeded_share: float | None


@dataclass(frozen=True, slots=True)
class LevelComparison:
    """Both sides of one triage level, including an empty level."""

    level: int
    a: LevelRunSummary
    b: LevelRunSummary


@dataclass(frozen=True, slots=True)
class RunSummaryComparison:
    """Log-derived aggregates only; contains no pairing or episode attributes.

    Time measures are minutes, census is patients, arrivals are patients/day,
    counts are integers and admission/exceedance shares are fractions.
    """

    metadata_differences: tuple[MetadataDifference, ...]
    center_differences: tuple[CenterDifference, ...]
    kpis: tuple[KPIComparison, ...]
    levels: tuple[LevelComparison, ...]
    completed_a: int
    completed_b: int
    unfinished_a: int
    unfinished_b: int


@dataclass(frozen=True, slots=True)
class ExcludedEpisodes:
    """Window arrivals completed only in A, only in B, or in neither."""

    only_a: int
    only_b: int
    neither: int


@dataclass(frozen=True, slots=True)
class EpisodeDifference:
    """Two completed histories of the same patient; all times are minutes."""

    episode_id: str
    arrival: float
    level_a: int
    level_b: int
    stay_a: float
    stay_b: float
    door_to_doctor_a: float
    door_to_doctor_b: float

    @property
    def stay_difference(self) -> float:
        """Signed B minus A stay, before rounding."""
        return self.stay_b - self.stay_a

    @property
    def door_to_doctor_difference(self) -> float:
        """Signed B minus A door-to-doctor, before rounding."""
        return self.door_to_doctor_b - self.door_to_doctor_a

    @property
    def stay_change(self) -> ChangeKind:
        """Classify the stay using the shared absolute truth tolerance."""
        return _change(self.stay_difference)

    @property
    def door_to_doctor_change(self) -> ChangeKind:
        """Classify door-to-doctor using the shared absolute truth tolerance."""
        return _change(self.door_to_doctor_difference)


@dataclass(frozen=True, slots=True)
class HistogramBin:
    """Left-closed minute interval and count; the final interval includes its right edge."""

    left: float
    right: float
    n: int


@dataclass(frozen=True, slots=True)
class DifferenceSummary:
    """Patient changes as counts and fractions; histogram excludes unchanged patients."""

    measure: Literal["stay", "door_to_doctor"]
    n: int
    improved: int
    worsened: int
    unchanged: int
    improved_share: float | None
    worsened_share: float | None
    unchanged_share: float | None
    histogram: tuple[HistogramBin, ...]


@dataclass(frozen=True, slots=True)
class RunComparison:
    """A verified paired comparison; episode collections may be empty, never None."""

    summary: RunSummaryComparison
    pairing: PairingInfo
    excluded: ExcludedEpisodes
    episodes: tuple[EpisodeDifference, ...]
    differences: tuple[DifferenceSummary, ...]
    most_affected: tuple[EpisodeDifference, ...]


def compare_run_summary(a: RunResults, b: RunResults) -> RunSummaryComparison:
    """Compare all log-derived aggregates without reading or requiring hidden truth.

    The nine displayed KPIs exclude n, which is provided as completed_a/b.
    Differences involving None are undefined. Relative changes also require
    nonzero A; an admission-share difference is a fraction (display as pp).
    """
    kpis = []
    for field in fields(a.kpis):
        if field.name == "n":
            continue
        av, bv = getattr(a.kpis, field.name), getattr(b.kpis, field.name)
        difference = None if av is None or bv is None else bv - av
        relative = None if difference is None or av == 0 else difference / av
        kpis.append(KPIComparison(field.name, av, bv, difference, relative))

    def level_summary(result: RunResults, index: int) -> LevelRunSummary:
        metrics = result.analysis.metrics.by_level[index]
        compliance = result.compliance.by_level[index]
        return LevelRunSummary(
            metrics.n,
            tuple(
                WaitStatistics(name, metrics.mean[name], metrics.p90[name])
                for name, _ in SUMMARY_MEASURES
            ),
            compliance.max_wait,
            compliance.exceeded_share,
        )

    def unfinished(result: RunResults) -> int:
        metrics = result.analysis.metrics
        return sum(
            metrics.start <= e.arrival < metrics.end and e.departure is None
            for e in result.analysis.table
        )

    return RunSummaryComparison(
        _metadata_differences(a, b),
        center_diff(a.center, b.center),
        tuple(kpis),
        tuple(LevelComparison(i + 1, level_summary(a, i), level_summary(b, i)) for i in range(5)),
        a.kpis.n,
        b.kpis.n,
        unfinished(a),
        unfinished(b),
    )


def _change(difference: float) -> ChangeKind:
    if difference < -TRUTH_ABS_TOL_MINUTES:
        return "improved"
    if difference > TRUTH_ABS_TOL_MINUTES:
        return "worsened"
    return "unchanged"


def _difference_summary(
    episodes: tuple[EpisodeDifference, ...],
    measure: Literal["stay", "door_to_doctor"],
) -> DifferenceSummary:
    values = [getattr(e, f"{measure}_difference") for e in episodes]
    improved = sum(_change(value) == "improved" for value in values)
    worsened = sum(_change(value) == "worsened" for value in values)
    unchanged = len(values) - improved - worsened
    changing = [value for value in values if _change(value) != "unchanged"]
    histogram = ()
    if changing:
        counts, edges = np.histogram(changing, bins=30)
        histogram = tuple(
            HistogramBin(float(left), float(right), int(count))
            for left, right, count in zip(edges[:-1], edges[1:], counts, strict=True)
        )
    n = len(values)
    return DifferenceSummary(
        measure,
        n,
        improved,
        worsened,
        unchanged,
        improved / n if n else None,
        worsened / n if n else None,
        unchanged / n if n else None,
        histogram,
    )


def compare_runs(
    a: RunResults,
    b: RunResults,
    truth_a: Mapping[str, EpisodeTruth],
    truth_b: Mapping[str, EpisodeTruth],
) -> RunComparison:
    """Verify and compare the same patients; never impute censored observations.

    Raises ValueError for nonpairable configurations (caller programming error),
    or PairingCheckError when hidden truth contradicts arrivals/configuration.
    Pair by identity among arrivals in [warm-up, horizon) completed in both.
    """
    pairing = _checked_pairing(a, b, truth_a, truth_b)
    start, end = a.analysis.metrics.start, a.analysis.metrics.end
    by_a = {e.episode_id: e for e in a.analysis.table if start <= e.arrival < end}
    by_b = {e.episode_id: e for e in b.analysis.table if start <= e.arrival < end}
    if by_a.keys() != by_b.keys():
        raise PairingCheckError(
            (a.info.run_id, b.info.run_id),
            "arrival_time",
            len(by_a.keys() ^ by_b.keys()),
            "la población de ventana difiere",
        )
    episodes = []
    only_a = only_b = neither = 0
    for key, av in by_a.items():
        bv = by_b[key]
        if av.departure is None or bv.departure is None:
            only_a += av.departure is not None
            only_b += bv.departure is not None
            neither += av.departure is None and bv.departure is None
            continue
        assert av.level is not None and bv.level is not None
        assert av.stay is not None and bv.stay is not None
        assert av.door_to_doctor is not None and bv.door_to_doctor is not None
        episodes.append(
            EpisodeDifference(
                key,
                av.arrival,
                av.level,
                bv.level,
                av.stay,
                bv.stay,
                av.door_to_doctor,
                bv.door_to_doctor,
            )
        )
    paired = tuple(sorted(episodes, key=lambda e: (e.arrival, e.episode_id)))
    return RunComparison(
        compare_run_summary(a, b),
        pairing,
        ExcludedEpisodes(only_a, only_b, neither),
        paired,
        tuple(_difference_summary(paired, measure) for measure in ("stay", "door_to_doctor")),
        tuple(sorted(paired, key=lambda e: (-abs(e.stay_difference), e.episode_id))[:10]),
    )
