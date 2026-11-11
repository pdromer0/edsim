"""Compare persisted runs, checking common random numbers against exact draws."""

import dataclasses
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

type PairingKind = Literal["same_draws", "different_draws", "clinical_profiles"]
type PairingCategory = Literal["template", "clinical", "unpaired"]
type ClinicalField = Literal["reason", "level", "true_level", "age", "sex", "arrival_mode", "tests"]
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
        # The results room changes the flow, never a draw (task 4.6a).
        "recursos.espera_resultados_fuera": frozenset(),
        "triaje.reparto_niveles": frozenset({"level", "needs_tests", "admitted"}),
        "duraciones.triaje": frozenset({"triage_time"}),
        "duraciones.valoracion": frozenset({"assessment_time"}),
        "duraciones.reevaluacion": frozenset({"reassessment_time"}),
        "duraciones.respuesta_pruebas": frozenset({"test_turnaround"}),
        "pruebas.probabilidad": frozenset({"needs_tests"}),
        "destino.probabilidad_ingreso": frozenset({"admitted"}),
        # [camas] of the milestone 5 model (task 5.3): the base wait for a bed is in the
        # truth of the outcome, not in these draws; the factors apply when the bed is asked.
        "camas.espera": frozenset(),
        "camas.factor_turno": frozenset(),
        "camas.factor_estacion": frozenset(),
    }
)
"""TOML key to draws it can affect; an immutable, exhaustive clinical contract."""

CLINICAL_DRAW_EFFECTS: Mapping[str, frozenset[DrawField]] = MappingProxyType(
    {key: frozenset() for key in DRAW_EFFECTS}
    | {"destino.probabilidad_ingreso": frozenset({"admitted"})}
)
"""The same contract with the clinical model (task 4.8a).

The clinical sampler takes the level, the durations and the tests from the
profiles, so of the center only the admission probability changes a draw (the
provisional destination, with the assigned level).
"""

_DRAW_FIELDS: tuple[DrawField, ...] = (
    "level",
    "triage_time",
    "assessment_time",
    "reassessment_time",
    "needs_tests",
    "test_turnaround",
    "admitted",
)
_PAIRING_FIELDS = (
    "seed",
    "profile_fingerprint",
    "days",
    "warmup_days",
    "model",
    "catalog_version",
    "clinical_profiles_fingerprint",
)
"""Fields that must match for the same patients: the model and its profiles last (task 4.5b)."""


@dataclass(frozen=True, slots=True)
class MetadataDifference:
    """One changed RunInfo field, without formatting or normalization.

    ``None`` is the value of a clinical field (``clinical_profiles_path`` and
    ``clinical_profiles_fingerprint``) in a run of the provisional model.
    """

    field: str
    a: int | float | str | None
    b: int | float | str | None


@dataclass(frozen=True, slots=True)
class DrawDifference:
    """Exact changed draws among all arrivals, including warm-up and censored ones."""

    field: DrawField
    changed: int
    total: int


@dataclass(frozen=True, slots=True)
class ClinicalDifference:
    """Patients whose clinical truth changes in one field, among all arrivals."""

    field: ClinicalField
    changed: int
    total: int


@dataclass(frozen=True, slots=True)
class PairingInfo:
    """Configuration category checked against arrivals and all seven draws.

    ``clinical_differences`` counts, for two clinical runs, the patients whose
    reason, assigned or true level, age, sex, arrival mode or tests change:
    all zero with the same profiles; empty with the provisional model.
    """

    kind: PairingKind
    draw_differences: tuple[DrawDifference, ...]
    clinical_differences: tuple[ClinicalDifference, ...] = ()


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
    """Return changed seed, profile fingerprint, days, warm-up, model or clinical profiles.

    In that order. Two runs of different models are never the same patients:
    the clinical model draws other streams. Two clinical runs with profiles of
    different fingerprints are (task 4.8a): the same standard draws with other
    values, the clinical pairing of ``compare_runs``. The profiles block only a
    provisional run against a clinical one, together with the model. A run of
    milestone 4 and one of milestone 5, both clinical, are not either (task
    5.3): the version of the catalog (``catalog_version``) blocks them; with
    different models it is the model that blocks, alone. An empty tuple is
    configuration compatibility, not verified pairing.
    """
    both_clinical = a.info.is_clinical and b.info.is_clinical
    same_model = a.info.model == b.info.model
    return tuple(
        MetadataDifference(name, getattr(a.info, name), getattr(b.info, name))
        for name in _PAIRING_FIELDS
        if getattr(a.info, name) != getattr(b.info, name)
        and not (both_clinical and name == "clinical_profiles_fingerprint")
        and not (not same_model and name == "catalog_version")
    )


def pairing_category(a: RunResults, b: RunResults) -> PairingCategory:
    """The pairing that the metadata allow, before reading any ground truth.

    ``unpaired`` with some blocker (only the summary compares), ``clinical``
    for two clinical runs with profiles of different fingerprints, and
    ``template`` otherwise: the same patients, with another center or none.
    """
    if pairing_blockers(a, b):
        return "unpaired"
    if a.info.is_clinical and a.info.clinical_profiles_fingerprint != (
        b.info.clinical_profiles_fingerprint
    ):
        return "clinical"
    return "template"


def _clinical_values(truth: EpisodeTruth) -> tuple:
    """The fields of ``ClinicalField``, in its order, of a clinical truth."""
    clinical = truth.clinical
    assert clinical is not None
    return (
        clinical.reason,
        clinical.triage.level,
        clinical.triage.true_level,
        clinical.person.age,
        clinical.person.female,
        clinical.person.ambulance,
        clinical.workup.ordered,
    )


_CLINICAL_FIELDS: tuple[ClinicalField, ...] = (
    "reason",
    "level",
    "true_level",
    "age",
    "sex",
    "arrival_mode",
    "tests",
)


def _clinical_differences(
    truth_a: Mapping[str, EpisodeTruth], truth_b: Mapping[str, EpisodeTruth]
) -> tuple[ClinicalDifference, ...]:
    changed = [0] * len(_CLINICAL_FIELDS)
    for key, t in truth_a.items():
        for i, (x, y) in enumerate(
            zip(_clinical_values(t), _clinical_values(truth_b[key]), strict=True)
        ):
            changed[i] += x != y
    return tuple(
        ClinicalDifference(field, n, len(truth_a))
        for field, n in zip(_CLINICAL_FIELDS, changed, strict=True)
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
    changes = tuple(
        DrawDifference(
            field,
            sum(getattr(t, field) != getattr(truth_b[key], field) for key, t in truth_a.items()),
            len(truth_a),
        )
        for field in _DRAW_FIELDS
    )
    if not a.info.is_clinical:
        return _template_pairing(run_ids, a, b, changes, DRAW_EFFECTS)
    for result, truth in ((a, truth_a), (b, truth_b)):
        missing = sum(t.clinical is None for t in truth.values())
        if missing:
            raise PairingCheckError(
                run_ids, "clinical", missing, f"la verdad de {result.info.run_id} no es clínica"
            )
    differences = _clinical_differences(truth_a, truth_b)
    if a.info.clinical_profiles_fingerprint == b.info.clinical_profiles_fingerprint:
        pairing = _template_pairing(run_ids, a, b, changes, CLINICAL_DRAW_EFFECTS)
        changed = sum(t.clinical != truth_b[key].clinical for key, t in truth_a.items())
        if changed:
            raise PairingCheckError(
                run_ids,
                "clinical",
                changed,
                "con los mismos perfiles, la verdad clínica no puede cambiar",
            )
        _check_same_outcome(run_ids, a, b, truth_a, truth_b)
        return PairingInfo(pairing.kind, pairing.draw_differences, differences)
    # Other profiles: the same standard draws with other values. The truth keeps the z
    # of the severity, the 12 draws of the tests and, with milestone 5, the 4 Gumbel and
    # the two normals of the outcome; the others follow from the seed.
    for field, value in (
        ("severity_z", lambda t: t.clinical.triage.z),
        ("workup_draws", lambda t: t.clinical.workup.draws),
        ("outcome_draws", _outcome_draws),
    ):
        count = sum(value(t) != value(truth_b[key]) for key, t in truth_a.items())
        if count:
            raise PairingCheckError(
                run_ids, field, count, "los sorteos estándar guardados difieren"
            )
    return PairingInfo("clinical_profiles", changes, differences)


def _outcome_draws(truth: EpisodeTruth) -> tuple | None:
    """The standard draws of the outcome (milestone 5), or ``None`` without it."""
    o = truth.outcome
    return None if o is None else (o.destination_draws, o.patience_z, o.bed_z)


def _check_same_outcome(
    run_ids: tuple[str, str],
    a: RunResults,
    b: RunResults,
    truth_a: Mapping[str, EpisodeTruth],
    truth_b: Mapping[str, EpisodeTruth],
) -> None:
    """With the same profiles, the outcome of milestone 5 is the same (task 5.3).

    Only its base wait for a bed may change, and only if ``camas.espera`` of
    the center changes: it is drawn with the center, not with the profiles.
    """

    def drawn(t: EpisodeTruth) -> object:
        return None if t.outcome is None else dataclasses.replace(t.outcome, bed_base=0.0)

    changed = sum(drawn(t) != drawn(truth_b[key]) for key, t in truth_a.items())
    if changed:
        raise PairingCheckError(
            run_ids, "outcome", changed, "con los mismos perfiles, el desenlace no puede cambiar"
        )
    beds = sum(
        t.outcome is not None and t.outcome.bed_base != truth_b[key].outcome.bed_base
        for key, t in truth_a.items()
    )
    if beds and "camas.espera" not in {d.key for d in center_diff(a.center, b.center)}:
        raise PairingCheckError(
            run_ids, "bed_base", beds, "la espera base de cama solo cambia con camas.espera"
        )


def _template_pairing(
    run_ids: tuple[str, str],
    a: RunResults,
    b: RunResults,
    changes: tuple[DrawDifference, ...],
    effects: Mapping[str, frozenset[DrawField]],
) -> PairingInfo:
    """The same patients with another center: only its draws may change."""
    allowed = frozenset().union(*(effects[d.key] for d in center_diff(a.center, b.center)))
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
    """Counts and fractions; up to 30 equal-width bins excluding unchanged patients.

    Zero is an exact edge: no bin mixes improvements and worsenings.
    """

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
        if improved and worsened:
            # A symmetric range keeps equal widths on both sides of zero.
            extent = max(abs(value) for value in changing)
            edges = np.linspace(-extent, extent, 31)
            edges[15] = 0.0
        else:
            edges = np.linspace(min(0.0, min(changing)), max(0.0, max(changing)), 31)
        counts, edges = np.histogram(changing, bins=edges)
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
