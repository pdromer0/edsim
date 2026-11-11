"""Presentation of the engine: run summary, validation table, CSV and plots.

These functions only format what ``simulate_ed``, ``analyze_run``,
``check_invariants`` and ``validate_engine`` already computed; they do not
simulate. The CLI calls them, and so can tests and notebooks. Labels are in
Spanish here, while the keys of the checks stay in English in
``validation.py``.

The CSV files of the ground truth are tidy, as those of milestone 2: one row
per episode or per day, with the parameters of the run (both configuration
files with their fingerprints, days, warm-up, seed and run identifier)
repeated in every row, so each file records how it was generated. Floats are
written with ``repr``, all their digits, so reading them back gives the same
value.

The episodes CSV of the clinical model (task 4.5b) has the columns of the
provisional one, then the clinical truth (``CLINICAL_TRUTH_COLUMNS``), then the
run parameters and the clinical profiles (``PROFILES_COLUMNS``): everything
``EpisodeTruth`` has, so ``read_episodes_csv`` gives back the same episodes,
floats bit for bit. The CSV of the provisional model does not change.
"""

import csv
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import astuple, dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from edsim.arrivals.rate import MINUTES_PER_DAY
from edsim.arrivals.report import WEEKDAYS
from edsim.arrivals.thinning import DayRecord
from edsim.arrivals.validation import ValidationResult
from edsim.engine.analysis import (
    SHIFTS,
    LevelMetrics,
    RunAnalysis,
    StepCurves,
    WindowMetrics,
)
from edsim.engine.center import CenterConfig
from edsim.engine.clinical_sampler import ClinicalTruth
from edsim.engine.events import ARRIVAL_MODES, SEXES, episode_id
from edsim.engine.ground_truth import EpisodeTruth
from edsim.engine.invariants import Violation
from edsim.engine.outcome_metrics import CensoredValue, OverThreshold, WindowOutcome
from edsim.engine.targets import (
    CLOCKS,
    COMPLIANCE_TARGET,
    PRETRIAGE_LONG_WAIT,
    PRETRIAGE_MAX_WAIT,
    PRETRIAGE_TARGET,
    clock_quantiles,
    manchester_compliance,
    pretriage,
)
from edsim.engine.validation import (
    HOURS,
    LITTLE_TOLERANCE,
    UTILIZATION_TOLERANCE,
    HourlyCensus,
    MG1Replicas,
)
from edsim.profiles.config import DESTINATIONS, N_BANDS, N_LEVELS, REASON_KEYS, TEST_TYPES
from edsim.profiles.context import DAY_TYPES, SEASONS, SHIFT_BANDS, ArrivalContext
from edsim.profiles.population import Person
from edsim.profiles.sampler import Outcome, SeverityAndTriage
from edsim.profiles.severity import CORRECT, OVER, UNDER, triage_quality
from edsim.profiles.workup import Workup

# --- Run parameters ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunParameters:
    """How a run was generated, repeated in every row of its CSV files.

    Attributes:
        center: Path of the center file, as given.
        center_fingerprint: ``config_fingerprint`` of that file.
        profile: Path of the arrival profile, as given.
        profile_fingerprint: ``config_fingerprint`` of that file.
        days: Horizon in full days, warm-up included.
        warmup_days: Full days of warm-up.
        seed: Master seed.
        run_id: Identifier of the run, as in the log.
    """

    center: str
    center_fingerprint: str
    profile: str
    profile_fingerprint: str
    days: int
    warmup_days: int
    seed: int
    run_id: str


PARAMETER_COLUMNS = (
    "centro",
    "huella_centro",
    "llegadas",
    "huella_llegadas",
    "dias",
    "calentamiento",
    "semilla",
    "run_id",
)
"""The fields of ``RunParameters``, in its order, as CSV columns."""

EPISODE_DATA_COLUMNS = (
    "episodio",
    "llegada",
    "minuto_llegada",
    "nivel",
    "triaje",
    "valoracion",
    "reevaluacion",
    "pruebas",
    "respuesta_pruebas",
    "destino",
)
"""The draws of an episode, the same with both models; ``nivel`` is the assigned level."""

EPISODE_COLUMNS = (*EPISODE_DATA_COLUMNS, *PARAMETER_COLUMNS)
"""The columns of the episodes CSV of the provisional model."""


@dataclass(frozen=True, slots=True)
class ProfilesParameters:
    """The clinical profiles of a run, in the last two columns of its clinical CSV.

    Attributes:
        profiles: Path of ``perfiles.toml``, as given.
        profiles_fingerprint: ``config_fingerprint`` of that file.
    """

    profiles: str
    profiles_fingerprint: str


PROFILES_COLUMNS = ("perfiles", "huella_perfiles")
"""The fields of ``ProfilesParameters``, in its order, as CSV columns."""

_WORKUP_DRAWS = ("pedida", "alterada", "respuesta")
"""The three standard draws of each type of test, in the order of ``Workup.draws``."""

CLINICAL_TRUTH_COLUMNS = (
    "franja",
    "tipo_dia",
    "estacion",
    "banda",
    "edad",
    "sexo",
    "medio",
    "motivo",
    "z_gravedad",
    "gravedad",
    "nivel_real",
    "calidad_triaje",
    "salto",
    *(f"pedida_{t}" for t in TEST_TYPES),
    *(f"alterada_{t}" for t in TEST_TYPES),
    *(f"respuesta_base_{t}" for t in TEST_TYPES),
    *(f"sorteo_{d}_{t}" for t in TEST_TYPES for d in _WORKUP_DRAWS),
)
"""The clinical truth of an episode, in the order of ``ClinicalTruth``: 37 columns.

The context (``franja``, ``tipo_dia`` and ``estacion``, by name), the person
(``banda`` is the index of the age band, 0 to 3; ``sexo`` and ``medio`` use the
words of the log), the reason, the triage (``z_gravedad``, ``gravedad``,
``nivel_real``, ``calidad_triaje`` and ``salto``; the assigned level is the
column ``nivel``) and the tests: whether each type is ordered, whether it is
abnormal and its base turnaround (factor 1), and then the 12 standard draws of
stream 3, three per type in the order of ``TEST_TYPES``.
"""

CLINICAL_EPISODE_COLUMNS = (
    *EPISODE_DATA_COLUMNS,
    *CLINICAL_TRUTH_COLUMNS,
    *PARAMETER_COLUMNS,
    *PROFILES_COLUMNS,
)
"""The columns of the episodes CSV of the clinical model: 10 + 37 + 8 + 2 = 57."""

OUTCOME_COLUMNS = (
    "z_paciencia",
    "paciencia",
    *(f"sorteo_destino_{d}" for d in DESTINATIONS),
    "z_cama",
    "espera_cama_base",
)
"""The outcome of an episode of milestone 5, in the order of the specification: 8 columns.

The normal of stream 8 and the patience in minutes, the 4 Gumbel draws of
stream 4 in the order of ``DESTINATIONS``, and the normal of stream 9 and the
base wait for a bed (factor 1). The destination drawn from them is the column
``destino``, also for a patient who left (H5-10).
"""

OUTCOME_EPISODE_COLUMNS = (*CLINICAL_EPISODE_COLUMNS, *OUTCOME_COLUMNS)
"""The columns of the episodes CSV of the milestone 5 model: 57 + 8 = 65."""

DAY_COLUMNS = (
    "dia",
    "fecha",
    "efecto_diario",
    "esperadas",
    "cota",
    "candidatas",
    "aceptadas",
    *PARAMETER_COLUMNS,
)
"""The columns of ``dias.csv`` of milestone 2, with the parameters of the engine."""


# --- Run summary -------------------------------------------------------------------------

SUMMARY_MEASURES = (
    ("triage_wait", "triaje"),
    ("box_wait", "box"),
    ("doctor_wait", "médico"),
    ("door_to_doctor", "puerta-médico"),
    ("stay", "estancia"),
)
"""Measures of the summary by level. ``doctor_wait`` adds up every wait for a
doctor while holding a box (first assessment, reassessment and resumptions)."""

POOL_LABELS = {
    "enfermeria_triaje": "enfermería de triaje",
    "medicos": "médicos",
    "boxes": "boxes",
}
SHIFT_LABELS = {"morning": "mañana", "afternoon": "tarde", "night": "noche"}
LITTLE_LABELS = {"system": "sistema", "triage_queue": "cola de triaje", "box_queue": "cola de box"}

CLOCK_LABELS = {
    "door_to_doctor": "A llegada",
    "triage_start_to_doctor": "B triaje",
    "classified_to_doctor": "C clasif.",
}
"""Short labels of the three clocks in the summary of the CLI. The app keeps
``SUMMARY_MEASURES`` until task 4.8b."""

MAX_VIOLATIONS_SHOWN = 10

_LEVEL_WIDTH = 7
_CELL_WIDTH = 16


def _level_row(label: str, m: LevelMetrics) -> str:
    cells = []
    for name, _ in SUMMARY_MEASURES:
        mean, p90 = m.mean[name], m.p90[name]
        cells.append("—" if mean is None else f"{mean:.1f} / {p90:.1f}")
    return f"{label:<{_LEVEL_WIDTH}}{m.n:>6}" + "".join(f"{c:>{_CELL_WIDTH}}" for c in cells)


_CLOCK_LABEL_WIDTH = 13


def _share(value: float) -> str:
    return f"{100 * value:.1f} %"


def _clock_lines(table: Sequence, first_day: int, end_day: int) -> list[str]:
    """Median / p90 of the three clocks by level, with the Manchester compliance (C)."""
    clocks = clock_quantiles(table, first_day, end_day)
    compliance = manchester_compliance(table, first_day, end_day)
    lines = [
        "Relojes hasta el médico por nivel, en minutos (mediana / p90)",
        "A desde la llegada, B desde el inicio del triaje, C desde la clasificación",
        f"Cumplimiento Manchester con C (días fuera: menos del {100 * COMPLIANCE_TARGET:.0f} %"
        " dentro del máximo); el nivel 1, solo con su tiempo",
        f"{'':<{_CLOCK_LABEL_WIDTH}}{'n':>6}"
        + "".join(f"{CLOCK_LABELS[name]:>{_CELL_WIDTH}}" for name in CLOCKS)
        + f"{'máx.':>7}{'cumple C':>11}{'días fuera C':>14}",
    ]
    for c in clocks:
        k = c.level - 1
        cells = [
            "—" if c.median[name] is None else f"{c.median[name]:.1f} / {c.p90[name]:.1f}"
            for name in CLOCKS
        ]
        if c.level == 1 or not c.n:
            within = out = "—"
        else:
            within = _share(compliance.pooled_within[k])
            out = f"{compliance.out[:, k].sum()} de {compliance.days_with_patients[k]}"
        lines.append(
            f"{f'nivel {c.level}':<{_CLOCK_LABEL_WIDTH}}{c.n:>6}"
            + "".join(f"{cell:>{_CELL_WIDTH}}" for cell in cells)
            + f"{compliance.max_wait[k]:>7.0f}{within:>11}{out:>14}"
        )
    return lines


def _pretriage_lines(table: Sequence, first_day: int, end_day: int) -> list[str]:
    """The pretriage by level, 2 to 5, and all of them, with the days out."""
    p = pretriage(table, first_day, end_day)
    lines = [
        f"Pretriaje (de la llegada al inicio del triaje), sin el nivel 1: ≤ {PRETRIAGE_MAX_WAIT:g}"
        f" min (objetivo {100 * PRETRIAGE_TARGET:.0f} %) y > {PRETRIAGE_LONG_WAIT:g} min",
        f"{'':<{_CLOCK_LABEL_WIDTH}}{'n':>6}"
        f"{f'≤ {PRETRIAGE_MAX_WAIT:g} min':>11}{f'> {PRETRIAGE_LONG_WAIT:g} min':>11}"
        f"{'días fuera':>14}",
    ]
    for g, group in enumerate(p.groups):
        label = "niveles 2-5" if group is None else f"nivel {group}"
        n = p.pooled_n[g]
        within = _share(p.pooled_within[g]) if n else "—"
        over = _share(p.pooled_over[g]) if n else "—"
        out = f"{p.out[:, g].sum()} de {p.days_with_patients[g]}" if n else "—"
        lines.append(f"{label:<{_CLOCK_LABEL_WIDTH}}{n:>6}{within:>11}{over:>11}{out:>14}")
    return lines


def _violation_lines(violations: Sequence[Violation]) -> list[str]:
    if not violations:
        return ["Invariantes: 0 violaciones"]
    by_check = Counter(v.check for v in violations)
    counts = ", ".join(f"{check} {n}" for check, n in by_check.items())
    lines = [f"Invariantes: FALLAN {len(violations)} violaciones ({counts})"]
    for v in violations[:MAX_VIOLATIONS_SHOWN]:
        where = "—" if v.sim_time is None else f"minuto {v.sim_time:.4f}"
        lines.append(f"    {v.check}  {v.event_id or '—'}  {where}  {v.message}")
    if len(violations) > MAX_VIOLATIONS_SHOWN:
        lines.append(f"    … y {len(violations) - MAX_VIOLATIONS_SHOWN} más")
    return lines


def format_run_summary(
    analysis: RunAnalysis,
    violations: Sequence[Violation],
    outcome: WindowOutcome | None = None,
) -> str:
    """Summarize one run: patients, waits by level, occupancy, Little and invariants.

    - Patients over the whole log: arrived, departed and still inside; and the
      arrivals in the window, also per day.
    - By level (1 to 5 and the total), over the episodes that arrive in the
      window and depart: their number and the mean / p90 of the triage, box
      and doctor waits, door to doctor and the stay, in minutes. A level
      without episodes shows ``—``.
    - The three clocks to the doctor by level (median / p90) and the
      Manchester compliance with clock C; the level 1 only with its times.
    - The pretriage by level, 2 to 5, against its standard.
    - Occupancy of each pool in each shift: busy over the staff in force.
    - Little's law for the system and the triage and box queues.
    - The invariants: 0 violations, or how many by check and the first ten.

    With ``outcome`` (milestone 5, task 5.4), the patients over the whole log
    tell apart those who left without being seen, and a section after the
    pretriage gives the abandonment, the censored compliance, the destinations,
    the wait for a bed, the stay by destination and the boxes blocked. Without
    it, the summary of before.

    Args:
        analysis: The analysis of the run, from ``analyze_run``.
        violations: The result of ``check_invariants`` on the same log.
        outcome: The indicators of the outcome of the same window, from
            ``window_outcome``, with a log of version 4.
    """
    m = analysis.metrics
    table = analysis.table
    departed = sum(e.departure is not None for e in table)
    left = sum(e.left is not None for e in table)
    per_day = m.arrivals / (m.end - m.start) * MINUTES_PER_DAY
    window = f"[día {m.start / MINUTES_PER_DAY:g}, día {m.end / MINUTES_PER_DAY:g})"
    # Whoever left is never counted as inside; the logs of versions 1 to 3 have none.
    gone = f" {left} se van sin ser vistos," if left or outcome is not None else ""
    lines = [
        f"Pacientes en todo el log: {len(table)} llegados, {departed} salidos,{gone}"
        f" {len(table) - departed - left} dentro al final",
        f"Ventana {window}: {m.arrivals} llegadas en la ventana, {per_day:.1f} al día",
        "",
        "Esperas y estancia por nivel, en minutos (media / p90; episodios que llegan"
        " en la ventana y salen)",
        f"{'nivel':<{_LEVEL_WIDTH}}{'n':>6}"
        + "".join(f"{label:>{_CELL_WIDTH}}" for _, label in SUMMARY_MEASURES),
    ]
    lines += [_level_row(str(lv.level), lv) for lv in m.by_level]
    lines.append(_level_row("total", m.overall))

    first_day, end_day = int(m.start // MINUTES_PER_DAY), int(m.end // MINUTES_PER_DAY)
    lines += ["", *_clock_lines(table, first_day, end_day)]
    lines += ["", *_pretriage_lines(table, first_day, end_day)]
    if outcome is not None:
        lines += ["", *_outcome_lines(outcome, table, first_day, end_day)]

    lines += [
        "",
        "Ocupación por pool y turno (ocupados / plantilla vigente)",
        f"{'pool':<22}" + "".join(f"{SHIFT_LABELS[s]:>10}" for s in SHIFTS),
    ]
    for pool, label in POOL_LABELS.items():
        ratios = {o.shift: o.ratio for o in m.occupancy if o.pool == pool}
        lines.append(f"{label:<22}" + "".join(f"{100 * ratios[s]:>8.1f} %" for s in SHIFTS))

    lines += [
        "",
        "Ley de Little en la ventana (L frente a λ·W)",
        f"{'':<16}{'L':>10}{'λ·W':>10}{'error rel.':>12}",
    ]
    for law in analysis.little:
        lines.append(
            f"{LITTLE_LABELS[law.name]:<16}{law.l:>10.4f}{law.lam * law.w:>10.4f}"
            f"{100 * law.relative_error:>10.2f} %"
        )

    lines += ["", *_violation_lines(violations)]
    return "\n".join(lines)


_WAIT_LABELS = {"triaje": "triaje", "box": "box", "medico": "médico"}


def _censored(value: CensoredValue | None) -> str:
    """A statistic with censoring: ``≥`` if it is a lower bound, ``—`` without patients."""
    if value is None:
        return "—"
    return f"{value.value:.1f}" if value.exact else f"≥ {value.value:.1f}"


def _maybe_share(value: float | None) -> str:
    return "—" if value is None else _share(value)


def _over(o: OverThreshold, label: str) -> str:
    unknown = f", {o.unknown} sin saber" if o.unknown else ""
    return f"{label} {o.over} de {o.known} ({_maybe_share(o.share)}{unknown})"


def _outcome_lines(outcome: WindowOutcome, table: Sequence, first_day: int, end_day: int) -> list:
    """The section of the outcome of milestone 5 (task 5.4): abandonment, censored
    compliance, destinations, wait for a bed, stay by destination and boxes blocked."""
    left, destinations, bed, stay = (
        outcome.left,
        outcome.destinations,
        outcome.bed_wait,
        outcome.stay,
    )
    compliance = manchester_compliance(table, first_day, end_day)
    sites = ", ".join(f"{_WAIT_LABELS[w]} {n}" for w, n in left.by_wait.items())
    lines = [
        "Desenlace de los episodios que llegan en la ventana (modelo del hito 5)",
        "Las esperas y los relojes de arriba son de los atendidos; el cumplimiento cuenta como"
        " incumplimiento a quien se va con su reloj C en el máximo o por encima, y quien se va"
        " antes queda censurado",
        f"Se van sin ser vistos: {left.left} de {left.arrivals} ({_maybe_share(left.share)}):"
        f" antes del triaje {left.before_triage} ({_maybe_share(left.before_triage_share)}),"
        f" después {left.after_triage} ({_maybe_share(left.after_triage_share)}); {sites}",
        f"Cumplimiento con C: {int(compliance.left_late.sum())} se van después de su máximo"
        f" (incumplen) y {int(compliance.censored.sum())} antes (censurados)",
        "",
        "Por nivel asignado, sobre los clasificados de cada nivel",
        f"{'':<{_CLOCK_LABEL_WIDTH}}{'n':>6}{'se van':>10}"
        + "".join(f"{d:>10}" for d in DESTINATIONS),
    ]
    for gone, level in zip(left.by_level, destinations.by_level, strict=True):
        cells = [_maybe_share(gone.share)] + [_maybe_share(level.share(d)) for d in DESTINATIONS]
        lines.append(
            f"{f'nivel {level.level}':<{_CLOCK_LABEL_WIDTH}}{level.classified:>6}"
            + "".join(f"{c:>10}" for c in cells)
        )
    totals = [_maybe_share(left.share)] + [
        _maybe_share(destinations.share(d)) for d in DESTINATIONS
    ]
    lines.append(
        f"{'llegadas':<{_CLOCK_LABEL_WIDTH}}{destinations.arrivals:>6}"
        + "".join(f"{c:>10}" for c in totals)
    )
    over = ", ".join(_over(o, f"> {o.minutes / 60:g} h") for o in bed.over)
    lines += [
        "",
        f"Espera de cama, en minutos: {bed.requests} pedidos, {bed.completed} con cama,"
        f" {bed.censored} esperando al final; mediana {_censored(bed.median)},"
        f" p90 {_censored(bed.p90)} (≥: cota con los que siguen esperando)",
        f"    {over}",
        "",
        "Estancia por destino, en minutos (media / mediana / p90; ≥: cota con los que siguen"
        " dentro)",
        f"{'':<{_CLOCK_LABEL_WIDTH}}{'n':>6}{'dentro':>8}{'media':>12}{'mediana':>12}{'p90':>12}",
    ]
    rows = [(d, stay.by_destination[d]) for d in DESTINATIONS] + [("se van", stay.left)]
    for label, s in rows:
        lines.append(
            f"{label:<{_CLOCK_LABEL_WIDTH}}{s.n:>6}{s.censored:>8}"
            + "".join(f"{_censored(v):>12}" for v in (s.mean, s.median, s.p90))
        )
    beds = outcome.beds
    lines += [
        f"Dentro sin destino al final: {stay.inside_without_destination};"
        f" {_over(stay.admitted_over, 'ingresados > 4 h:')}",
        f"Boxes con ingresados esperando cama: media {beds.boxes_mean:.2f}, máximo"
        f" {beds.boxes_max}; en el pasillo: media {beds.hallway_mean:.2f}, máximo"
        f" {beds.hallway_max}",
    ]
    return lines


# --- Validation table -------------------------------------------------------------------

CHECK_LABELS = {
    "invariants": "1. Invariantes",
    "little_system": "2. Little: sistema",
    "little_triage_queue": "2. Little: cola de triaje",
    "little_box_queue": "2. Little: cola de box",
    "utilization_enfermeria_triaje": "2. Utilización: enfermería de triaje",
    "utilization_medicos": "2. Utilización: médicos",
    "utilization_boxes": "2. Utilización: boxes",
    "mg1": "3a. M/G/1",
    "mtginf": "3b. Mₜ/G/∞",
    "infinite_capacity": "4. Capacidad infinita",
    "more_doctors": "4. Más médicos",
}
"""Labels of the checks of ``validate_engine``, with their level of the specification."""

MG1_LABELS = {"wq": "Wq", "rho": "ρ", "lq": "Lq"}

_LABEL_WIDTH = 38
_VALUE_WIDTH = 12
_BOUND_WIDTH = 24
_CRITERION_WIDTH = 44


def _percent(confidence: float) -> str:
    """A confidence level as a percentage, such as ``99.667 %``."""
    return f"{100 * confidence:.5g} %"


def _interval(r: ValidationResult, digits: int) -> str:
    return f"[{r.ci_low:.{digits}f}, {r.ci_high:.{digits}f}]"


def _cells(r: ValidationResult) -> tuple[str, str, str]:
    """Value, interval or tolerance, and criterion of a check, in Spanish."""
    name = r.name
    if name.startswith("little_"):
        return (
            f"{100 * r.statistic:.2f} %",
            f"≤ {100 * LITTLE_TOLERANCE:g} %",
            "error relativo de L = λ·W",
        )
    if name.startswith("utilization_"):
        return (
            f"{r.statistic:.1e}",
            f"≤ {UTILIZATION_TOLERANCE:g}",
            "área de ocupados = suma de atenciones",
        )
    match name:
        case "invariants":
            return f"{r.statistic:.0f}", "—", "0 violaciones (ejecución larga)"
        case "mg1":
            return (
                f"{r.statistic:.2f}",
                _interval(r, 2),
                f"Wq, ρ y Lq de P–K en sus IC al {_percent(r.confidence)}",
            )
        case "mtginf":
            return (
                f"{r.statistic:.0f}",
                f"IC al {_percent(r.confidence)}",
                f"m(t) en los IC de las {len(r.details)} horas",
            )
        case "infinite_capacity":
            return f"{r.statistic:.0f}", "—", "esperas 0 y estancias exactas"
        case "more_doctors":
            return (
                f"{r.statistic:.2f}",
                f"{_interval(r, 2)} al {_percent(r.confidence)}",
                "Δ espera de médico < 0 y mismos pacientes",
            )
    return f"{r.statistic:.4g}", "—", r.criterion


def _outcome(passed: bool) -> str:
    return "pasa" if passed else "FALLA"


def _table_row(label: str, value: str, bound: str, criterion: str, passed: bool) -> str:
    return (
        f"{label:<{_LABEL_WIDTH}}{value:>{_VALUE_WIDTH}}  {bound:<{_BOUND_WIDTH}}"
        f"{criterion:<{_CRITERION_WIDTH}}{_outcome(passed)}"
    )


def format_engine_validation(results: Sequence[ValidationResult]) -> str:
    """Format the checks of ``validate_engine`` as a table, with details below.

    One row per check: value, interval or tolerance, criterion and outcome.
    The value is the number of violations for the invariants, the relative
    error for Little (in %) and the utilization, the mean Wq in minutes for
    the M/G/1, the hours outside their interval for the Mₜ/G/∞, the inexact
    episodes for the infinite capacity and the paired difference of the doctor
    wait in minutes for more doctors.

    Below the table come the three intervals of the M/G/1 (Wq, ρ and Lq
    against Pollaczek–Khinchine) and, only if there are any, the hours of the
    Mₜ/G/∞ whose interval misses m(t). A failure is written ``FALLA``, and
    the last line sums up which checks fail.
    """
    lines = [
        f"{'comprobación':<{_LABEL_WIDTH}}{'valor':>{_VALUE_WIDTH}}  "
        f"{'IC o tolerancia':<{_BOUND_WIDTH}}{'criterio':<{_CRITERION_WIDTH}}resultado"
    ]
    for r in results:
        lines.append(_table_row(CHECK_LABELS.get(r.name, r.name), *_cells(r), r.passed))

    by_name = {r.name: r for r in results}
    if "mg1" in by_name:
        mg1 = by_name["mg1"]
        lines += ["", "M/G/1 frente a Pollaczek–Khinchine"]
        for d in mg1.details:
            lines.append(
                f"    {MG1_LABELS[d.name]:<6}{d.statistic:>10.4f}  {_interval(d, 4):<24}"
                f"P–K {d.target:.4f} en el IC al {_percent(d.confidence):<10}"
                f"{_outcome(d.passed)}"
            )
    if "mtginf" in by_name:
        outside = [d for d in by_name["mtginf"].details if not d.passed]
        if outside:
            lines += ["", "Horas de la Mₜ/G/∞ fuera de su IC (censo medio frente a m(t))"]
            for d in outside:
                lines.append(
                    f"    {d.name:<6}{d.statistic:>10.4f}  {_interval(d, 4):<24}"
                    f"m(t) {d.target:.4f}  {_outcome(d.passed)}"
                )

    failed = [CHECK_LABELS.get(r.name, r.name) for r in results if not r.passed]
    lines.append("")
    if failed:
        lines.append(f"Resultado: FALLAN {', '.join(failed)}")
    else:
        lines.append(f"Resultado: pasan las {len(results)} comprobaciones")
    return "\n".join(lines)


# --- CSV ------------------------------------------------------------------------------------


def _episode_cells(e: EpisodeTruth) -> tuple:
    return (
        e.episode_id,
        e.arrival_id,
        e.arrival_time,
        e.level,
        e.triage_time,
        e.assessment_time,
        e.reassessment_time,
        e.needs_tests,
        "" if e.test_turnaround is None else e.test_turnaround,
        _destination(e),
    )


def _destination(e: EpisodeTruth) -> str:
    """The drawn destination: one of four with milestone 5, else ``alta`` or ``ingreso``."""
    if e.outcome is None:
        return "ingreso" if e.admitted else "alta"
    return e.outcome.destination


def _outcome_cells(e: EpisodeTruth) -> tuple:
    """The 8 cells of the outcome, or ``ValueError`` if they cannot be read back."""
    outcome = e.outcome
    if outcome is None:
        raise ValueError(f"{e.episode_id} has no outcome: it is not of the milestone 5 model")
    if outcome.destination not in DESTINATIONS or len(outcome.destination_draws) != len(
        DESTINATIONS
    ):
        raise ValueError(f"{e.episode_id}: its outcome has no valid destination and draws")
    if e.admitted != (outcome.destination == "ingreso"):
        raise ValueError(
            f"{e.episode_id}: admitted={e.admitted!r} but the destination is "
            f"{outcome.destination!r}"
        )
    return (
        outcome.patience_z,
        outcome.patience,
        *outcome.destination_draws,
        outcome.bed_z,
        outcome.bed_base,
    )


def _clinical_cells(e: EpisodeTruth) -> tuple:
    """The 37 clinical cells of an episode, or ``ValueError`` if they cannot be read back."""
    truth = e.clinical
    if truth is None:
        raise ValueError(f"{e.episode_id} is of the provisional model")
    t, w = truth.triage, truth.workup
    if e.test_turnaround is not None:
        raise ValueError(f"{e.episode_id}: test_turnaround must be None with the clinical model")
    if e.level != t.level:
        raise ValueError(f"{e.episode_id}: level {e.level} is not the assigned one ({t.level})")
    if e.needs_tests != w.has_round:
        raise ValueError(f"{e.episode_id}: needs_tests does not match the ordered tests")
    c, person = truth.context, truth.person
    return (
        SHIFT_BANDS[c.shift_band],
        DAY_TYPES[c.day_type],
        SEASONS[c.season],
        person.band,
        person.age,
        truth.sex,
        truth.arrival_mode,
        truth.reason,
        t.z,
        t.severity,
        t.true_level,
        t.quality,
        t.jump,
        *w.ordered,
        *w.abnormal,
        *w.turnarounds,
        *w.draws,
    )


def write_episodes_csv(
    episodes: Sequence[EpisodeTruth],
    path: Path,
    parameters: RunParameters,
    profiles: ProfilesParameters | None = None,
    *,
    outcome: bool = False,
) -> None:
    """Write the ground truth of the episodes as a tidy CSV, one row per episode.

    Columns: ``episodio``, ``llegada`` (``arrival_id``), ``minuto_llegada``
    (bit for bit the instant of ``iter_arrivals``), ``nivel``, the drawn
    durations ``triaje``, ``valoracion`` and ``reevaluacion``, ``pruebas``
    (``True`` or ``False``), ``respuesta_pruebas``, ``destino`` (``alta`` or
    ``ingreso``, as in the log) and the run parameters. Durations are drawn
    even when not used, such as the turnaround of a patient without tests.

    With ``profiles``, the CSV of the clinical model: ``CLINICAL_EPISODE_COLUMNS``,
    with the clinical truth after ``destino``, the profiles after the run
    parameters and ``respuesta_pruebas`` empty (``None``: the turnaround of a
    round depends on the shift band of its order).

    With ``outcome`` too, the CSV of the milestone 5 model (task 5.3):
    ``OUTCOME_EPISODE_COLUMNS``, the clinical one with ``OUTCOME_COLUMNS`` at the
    end and ``destino`` one of the four drawn destinations, also the
    counterfactual one of a patient who left. The model says it, not the
    episodes, so a run of milestone 5 without episodes has its 65 columns too.

    Raises:
        ValueError: If ``profiles`` is given and some episode is provisional,
            or not given and some episode is clinical, or a clinical episode
            cannot be read back (its ``test_turnaround`` is not ``None``, or
            its level or ``needs_tests`` contradict its clinical truth); if
            ``outcome`` is given without ``profiles``, or some episode has no
            outcome with it or has one without it. It is checked before the
            file is created.
    """
    if outcome:
        if profiles is None:
            raise ValueError("the CSV of the milestone 5 model needs the profiles")
        rows = [
            (
                *_episode_cells(e),
                *_clinical_cells(e),
                *astuple(parameters),
                *astuple(profiles),
                *_outcome_cells(e),
            )
            for e in episodes
        ]
        _write_rows(path, OUTCOME_EPISODE_COLUMNS, rows)
        return
    with_outcome = [e.episode_id for e in episodes if e.outcome is not None]
    if with_outcome:
        raise ValueError(
            f"{with_outcome[0]} has an outcome: the CSV of the milestone 5 model needs outcome=True"
        )
    if profiles is None:
        clinical = [e.episode_id for e in episodes if e.clinical is not None]
        if clinical:
            raise ValueError(f"{clinical[0]} is of the clinical model: its CSV needs the profiles")
        header = EPISODE_COLUMNS
        rows = [(*_episode_cells(e), *astuple(parameters)) for e in episodes]
    else:
        header = CLINICAL_EPISODE_COLUMNS
        rows = [
            (*_episode_cells(e), *_clinical_cells(e), *astuple(parameters), *astuple(profiles))
            for e in episodes
        ]
    _write_rows(path, header, rows)


def _write_rows(path: Path, header: Sequence[str], rows: Sequence[tuple]) -> None:
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def _token(row: Mapping[str, str], column: str, choices: Sequence[str]) -> str:
    value = row[column]
    if value not in choices:
        raise ValueError(f"{column} must be one of {tuple(choices)}, got {value!r}")
    return value


def _boolean(row: Mapping[str, str], column: str) -> bool:
    return _token(row, column, ("True", "False")) == "True"


def _integer(row: Mapping[str, str], column: str, low: int, high: int) -> int:
    text = row[column]
    try:
        value = int(text)
    except ValueError:
        raise ValueError(f"{column} must be an integer, got {text!r}") from None
    if str(value) != text or not low <= value <= high:
        raise ValueError(f"{column} must be an integer in {low}-{high}, got {text!r}")
    return value


def _real(row: Mapping[str, str], column: str, *, non_negative: bool = False) -> float:
    text = row[column]
    try:
        value = float(text)
    except ValueError:
        raise ValueError(f"{column} must be a number, got {text!r}") from None
    if not math.isfinite(value) or (non_negative and value < 0):
        qualifier = "finite and non-negative" if non_negative else "finite"
        raise ValueError(f"{column} must be {qualifier}, got {text!r}")
    return value


def _clinical_truth(row: Mapping[str, str], level: int, needs_tests: bool) -> ClinicalTruth:
    true_level = _integer(row, "nivel_real", 1, N_LEVELS)
    quality = _token(row, "calidad_triaje", (CORRECT, UNDER, OVER))
    jump = _integer(row, "salto", 0, N_LEVELS - 1)
    if (quality, jump) != triage_quality(level, true_level):
        raise ValueError(
            f"calidad_triaje and salto ({quality}, {jump}) do not match "
            f"nivel {level} and nivel_real {true_level}"
        )
    ordered = tuple(_boolean(row, f"pedida_{t}") for t in TEST_TYPES)
    if any(ordered) != needs_tests:
        raise ValueError("pruebas does not match the ordered tests (pedida_*)")
    return ClinicalTruth(
        context=ArrivalContext(
            shift_band=SHIFT_BANDS.index(_token(row, "franja", SHIFT_BANDS)),
            day_type=DAY_TYPES.index(_token(row, "tipo_dia", DAY_TYPES)),
            season=SEASONS.index(_token(row, "estacion", SEASONS)),
        ),
        person=Person(
            band=_integer(row, "banda", 0, N_BANDS - 1),
            age=_integer(row, "edad", 0, 150),
            female=_token(row, "sexo", SEXES) == SEXES[0],
            ambulance=_token(row, "medio", ARRIVAL_MODES) == ARRIVAL_MODES[0],
        ),
        reason=_token(row, "motivo", REASON_KEYS),
        triage=SeverityAndTriage(
            z=_real(row, "z_gravedad"),
            severity=_real(row, "gravedad"),
            level=level,
            true_level=true_level,
            quality=quality,
            jump=jump,
        ),
        workup=Workup(
            ordered=ordered,
            abnormal=tuple(_boolean(row, f"alterada_{t}") for t in TEST_TYPES),
            turnarounds=tuple(
                _real(row, f"respuesta_base_{t}", non_negative=True) for t in TEST_TYPES
            ),
            draws=tuple(_real(row, f"sorteo_{d}_{t}") for t in TEST_TYPES for d in _WORKUP_DRAWS),
        ),
    )


def _outcome_from_row(row: Mapping[str, str]) -> Outcome:
    return Outcome(
        destination_draws=tuple(_real(row, f"sorteo_destino_{d}") for d in DESTINATIONS),
        destination=_token(row, "destino", DESTINATIONS),
        patience_z=_real(row, "z_paciencia"),
        patience=_real(row, "paciencia", non_negative=True),
        bed_z=_real(row, "z_cama"),
        bed_base=_real(row, "espera_cama_base", non_negative=True),
    )


def episode_from_row(row: Mapping[str, str]) -> EpisodeTruth:
    """The ``EpisodeTruth`` of one row of an episodes CSV, of any model.

    A row with the clinical columns (``CLINICAL_TRUTH_COLUMNS``) is of the
    clinical model: its ``respuesta_pruebas`` must be empty and is read as
    ``None``. A clinical row with the outcome columns (``OUTCOME_COLUMNS``) is
    of milestone 5: its ``destino`` is one of the four destinations, and
    ``admitted`` is whether it is ``ingreso``. Tokens are exact
    (``True``/``False``, the words of the log and of the contexts), integers
    are written as Python writes them, and floats are finite and read bit for
    bit. The run parameters are not read here.

    Raises:
        ValueError: If a value is invalid or contradicts another one.
        KeyError: If a column is missing.
    """
    arrival_id = _integer(row, "llegada", 0, 10**12)
    if row["episodio"] != episode_id(arrival_id):
        raise ValueError("episodio does not match llegada")
    level = _integer(row, "nivel", 1, N_LEVELS)
    needs_tests = _boolean(row, "pruebas")
    clinical = "franja" in row
    outcome = _outcome_from_row(row) if clinical and "z_paciencia" in row else None
    if clinical:
        if row["respuesta_pruebas"] != "":
            raise ValueError("respuesta_pruebas must be empty with the clinical model")
        turnaround = None
    else:
        turnaround = _real(row, "respuesta_pruebas", non_negative=True)
    return EpisodeTruth(
        episode_id=row["episodio"],
        arrival_id=arrival_id,
        arrival_time=_real(row, "minuto_llegada", non_negative=True),
        level=level,
        triage_time=_real(row, "triaje", non_negative=True),
        assessment_time=_real(row, "valoracion", non_negative=True),
        reassessment_time=_real(row, "reevaluacion", non_negative=True),
        needs_tests=needs_tests,
        test_turnaround=turnaround,
        admitted=(
            outcome.destination == "ingreso"
            if outcome is not None
            else _token(row, "destino", ("alta", "ingreso")) == "ingreso"
        ),
        clinical=_clinical_truth(row, level, needs_tests) if clinical else None,
        outcome=outcome,
    )


def read_episodes_csv(path: Path) -> tuple[EpisodeTruth, ...]:
    """Read an episodes CSV of either model, as ``write_episodes_csv`` wrote it.

    The header must be exactly ``EPISODE_COLUMNS``, ``CLINICAL_EPISODE_COLUMNS``
    (57 columns, milestone 4) or ``OUTCOME_EPISODE_COLUMNS`` (65, milestone 5),
    and the run parameters (and profiles) the same in every row. Each row is
    read with ``episode_from_row``.

    Raises:
        ValueError: With ``path:line``, if the header, a row or its
            parameters are invalid.
    """
    episodes = []
    with Path(path).open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source, strict=True)
        try:
            header = tuple(reader.fieldnames or ())
            if header not in (EPISODE_COLUMNS, CLINICAL_EPISODE_COLUMNS, OUTCOME_EPISODE_COLUMNS):
                raise ValueError("invalid episode ground truth header")
            # The columns of the run, the same in every row; the outcome comes after them.
            parameter_columns = tuple(
                c for c in header if c in PARAMETER_COLUMNS or c in PROFILES_COLUMNS
            )
            first = None
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError("incomplete or extra CSV fields")
                parameters = tuple(row[c] for c in parameter_columns)
                first = parameters if first is None else first
                if parameters != first:
                    raise ValueError("the run parameters change between rows")
                episodes.append(episode_from_row(row))
        except (ValueError, KeyError, csv.Error) as error:
            raise ValueError(f"{path}:{max(1, reader.line_num)}: {error}") from error
    return tuple(episodes)


def write_ground_truth_days_csv(
    days: Sequence[DayRecord], path: Path, parameters: RunParameters
) -> None:
    """Write the day records of the run as a tidy CSV, one row per day.

    The columns of ``dias.csv`` of milestone 2 (``dia``, ``fecha``,
    ``efecto_diario``, ``esperadas``, ``cota``, ``candidatas``,
    ``aceptadas``) and the run parameters.
    """
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(DAY_COLUMNS)
        for d in days:
            writer.writerow(
                (
                    d.day,
                    d.date.isoformat(),
                    d.day_effect,
                    d.expected,
                    d.bound,
                    d.candidates,
                    d.accepted,
                    *astuple(parameters),
                )
            )


# --- Plots ----------------------------------------------------------------------------------
# Figures use matplotlib's Agg canvas directly instead of pyplot, as in
# arrivals/report.py: importing this module never changes the global backend.
# Colors are slots 1 to 3 of the reference categorical palette (dataviz skill),
# which pass the colorblind checks for every pair: what was simulated in blue,
# the theory or the capacity in orange, a second simulated curve in aqua. The
# M/M/1 reference, which is not a hypothesis being tested, is the muted gray.

OBSERVED_COLOR = "#2a78d6"
THEORY_COLOR = "#eb6834"
SECOND_COLOR = "#1baf7a"
MUTED_COLOR = "#898781"

CENSUS_DAYS = 7
"""Days of the long run shown by ``plot_census``: one week."""

WAIT_PANELS = (("box_wait", "Box"), ("doctor_wait", "Médico"), ("door_to_doctor", "Puerta-médico"))


def _figure(width: float, height: float) -> Figure:
    fig = Figure(figsize=(width, height), layout="constrained")
    FigureCanvasAgg(fig)
    return fig


def _window_stairs(
    curves: StepCurves, name: str, start: float, end: float
) -> tuple[np.ndarray, np.ndarray]:
    """The steps of a curve that cover ``[start, end]``, with the edges clipped to it."""
    edges = curves.edges
    keep = (edges[1:] > start) & (edges[:-1] < end)
    values = curves[name][keep]
    kept_edges = np.append(edges[:-1][keep], edges[1:][keep][-1])
    return values, np.clip(kept_edges, start, end)


def plot_census(
    analysis: RunAnalysis, center: CenterConfig, start_date: date, days: int = CENSUS_DAYS
) -> Figure:
    """Census and busy boxes of one week of a run, against the number of boxes.

    The week starts at the end of the warm-up and is cut at the horizon if the
    run is shorter. The curves are the step functions of the log: the census
    can go above the boxes, because it counts the patients waiting for triage
    or for a box; the busy boxes never can.

    Args:
        analysis: The analysis of the run, such as ``EngineValidation.long_run``.
        center: The configuration of the run, for the number of boxes.
        start_date: Date of minute 0 (the profile's ``start_date``), for the
            names of the days.
        days: Days shown.

    Returns:
        The figure, attached to an Agg canvas; save it with ``savefig``.
    """
    start = analysis.metrics.start
    end = min(start + days * MINUTES_PER_DAY, analysis.curves.horizon)
    first_day, last_day = round(start / MINUTES_PER_DAY), round(end / MINUTES_PER_DAY)

    fig = _figure(10, 4.5)
    ax = fig.add_subplot()
    for name, label, color in (
        ("census", "Censo", OBSERVED_COLOR),
        ("boxes_busy", "Boxes ocupados", SECOND_COLOR),
    ):
        values, edges = _window_stairs(analysis.curves, name, start, end)
        ax.stairs(
            values, edges / MINUTES_PER_DAY, baseline=None, color=color, linewidth=1.5, label=label
        )
    ax.plot(
        [first_day, last_day],
        [center.boxes, center.boxes],
        "--",
        color=THEORY_COLOR,
        linewidth=2,
        label=f"Capacidad: {center.boxes} boxes",
    )
    ticks = range(first_day, last_day + 1)
    ax.set_xticks(list(ticks))
    ax.set_xticklabels(
        [
            f"{WEEKDAYS[(start_date + timedelta(days=d)).weekday()][:3]} "
            f"{(start_date + timedelta(days=d)).day}"
            for d in ticks
        ]
    )
    ax.set_xlim(first_day, last_day)
    ax.set_ylim(bottom=0)
    ax.set_xlabel("Día (las marcas son las 0 h)")
    ax.set_ylabel("Pacientes")
    ax.set_title(f"Censo y boxes ocupados: días {first_day} a {last_day} de la ejecución")
    ax.grid(alpha=0.3)
    # Outside the axes: the curves can be high at both ends of the week.
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1))
    return fig


def plot_waits_by_level(metrics: WindowMetrics) -> Figure:
    """Box, doctor and door-to-doctor waits by level: mean as bars, p90 as markers.

    One panel per wait, each with its own scale. The doctor wait is
    ``doctor_wait``, every wait for a doctor while holding a box. Levels
    without episodes in the window are left out; the label under each bar
    gives the number of episodes.

    Returns:
        The figure, attached to an Agg canvas; save it with ``savefig``.
    """
    levels = [lv for lv in metrics.by_level if lv.n > 0]
    x = np.arange(len(levels))

    fig = _figure(13, 4.5)
    axes = fig.subplots(1, len(WAIT_PANELS))
    for ax, (name, title) in zip(axes, WAIT_PANELS, strict=True):
        ax.bar(x, [lv.mean[name] for lv in levels], width=0.6, color=OBSERVED_COLOR, label="Media")
        ax.plot(
            x,
            [lv.p90[name] for lv in levels],
            "D",
            color=THEORY_COLOR,
            markersize=8,
            label="p90",
        )
        ax.set_xticks(x)
        ax.set_xticklabels([f"{lv.level}\nn = {lv.n}" for lv in levels], fontsize=9)
        ax.set_ylim(bottom=0)
        ax.set_title(title)
        ax.set_xlabel("Nivel de triaje")
        ax.grid(axis="y", alpha=0.3)
    axes[0].set_ylabel("Minutos")
    fig.suptitle("Esperas por nivel en la ventana: media y p90")
    # Outside the axes, so that it never hides a tall p90 of level 1.
    fig.legend(*axes[0].get_legend_handles_labels(), loc="outside upper right")
    return fig


def plot_mg1(replicas: MG1Replicas, wq: ValidationResult) -> Figure:
    """The Wq of each replication of the M/G/1 and its interval, against the theory.

    The band is the interval of the ``wq`` detail of the ``mg1`` result, the
    same one the table prints. Pollaczek–Khinchine is the hypothesis; the
    M/M/1 with the same mean service time, ``Wq = ρ·E[S] / (1 − ρ)``, is a
    reference: the gap between both lines is the factor ``(1 + CV²) / 2``.

    Args:
        replicas: The values of each replication and the theory.
        wq: The ``wq`` detail of the ``mg1`` result.

    Returns:
        The figure, attached to an Agg canvas; save it with ``savefig``.
    """
    theory = replicas.theory
    n = len(replicas.wq)
    x = np.arange(1, n + 1)
    mm1 = theory.rho * theory.mean_service / (1 - theory.rho)

    fig = _figure(8, 4.5)
    ax = fig.add_subplot()
    ax.axhspan(wq.ci_low, wq.ci_high, color=OBSERVED_COLOR, alpha=0.15, linewidth=0)
    ax.axhline(
        wq.statistic,
        color=OBSERVED_COLOR,
        linewidth=2,
        label=f"Media {wq.statistic:.2f} e IC al {_percent(wq.confidence)}",
    )
    ax.plot(
        x, replicas.wq, "o", color=OBSERVED_COLOR, markersize=8, label=f"Wq de cada réplica ({n})"
    )
    ax.axhline(
        theory.wq,
        color=THEORY_COLOR,
        linewidth=2,
        label=f"Pollaczek–Khinchine: {theory.wq:.2f} min",
    )
    ax.axhline(
        mm1,
        color=MUTED_COLOR,
        linewidth=2,
        linestyle="--",
        label=f"M/M/1 de la misma media: {mm1:.2f} min",
    )
    ax.set_xlim(0.5, n + 0.5)
    ax.set_xticks(x if n <= 20 else x[::5])
    ax.set_ylim(bottom=0)
    ax.set_xlabel("Réplica")
    ax.set_ylabel("Espera media de triaje Wq (min)")
    ax.set_title(f"M/G/1 del triaje: λ = {60 * theory.lam:g}/h, ρ = {theory.rho:.3f}")
    ax.grid(axis="y", alpha=0.3)
    ax.legend(loc="lower right")
    return fig


def plot_hourly_census(hourly: HourlyCensus) -> Figure:
    """Mean census by hour of the clock, with its interval, against m(t).

    Each point is the mean over the replications of the census of that hour,
    with the interval that the Mₜ/G/∞ check uses (Bonferroni among the 24
    hours) as its error bar; the line is the offered load m(t) averaged the
    same way.

    Returns:
        The figure, attached to an Agg canvas; save it with ``savefig``.
    """
    hours = np.arange(HOURS)
    mean = hourly.census.mean(axis=0)
    errors = np.array([mean - hourly.ci_low, hourly.ci_high - mean])

    fig = _figure(8, 4.5)
    ax = fig.add_subplot()
    ax.plot(hours, hourly.expected, color=THEORY_COLOR, linewidth=2, label="m(t): carga ofrecida")
    ax.errorbar(
        hours,
        mean,
        yerr=errors,
        fmt="o",
        color=OBSERVED_COLOR,
        markersize=6,
        capsize=3,
        label=f"Censo medio e IC ({hourly.census.shape[0]} réplicas)",
    )
    ax.set_xticks(hours[::2])
    ax.set_xlim(-0.6, 23.6)
    ax.set_ylim(bottom=0)
    ax.set_xlabel("Hora del reloj")
    ax.set_ylabel("Pacientes dentro (media de la hora)")
    ax.set_title("Mₜ/G/∞: censo por hora con capacidad infinita frente a m(t)")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left")
    return fig
