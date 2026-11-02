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
"""

import csv
from collections import Counter
from collections.abc import Sequence
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
from edsim.engine.analysis import SHIFTS, LevelMetrics, RunAnalysis, StepCurves, WindowMetrics
from edsim.engine.center import CenterConfig
from edsim.engine.ground_truth import EpisodeTruth
from edsim.engine.invariants import Violation
from edsim.engine.validation import (
    HOURS,
    LITTLE_TOLERANCE,
    UTILIZATION_TOLERANCE,
    HourlyCensus,
    MG1Replicas,
)

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

EPISODE_COLUMNS = (
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
    *PARAMETER_COLUMNS,
)

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

MAX_VIOLATIONS_SHOWN = 10

_LEVEL_WIDTH = 7
_CELL_WIDTH = 16


def _level_row(label: str, m: LevelMetrics) -> str:
    cells = []
    for name, _ in SUMMARY_MEASURES:
        mean, p90 = m.mean[name], m.p90[name]
        cells.append("—" if mean is None else f"{mean:.1f} / {p90:.1f}")
    return f"{label:<{_LEVEL_WIDTH}}{m.n:>6}" + "".join(f"{c:>{_CELL_WIDTH}}" for c in cells)


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


def format_run_summary(analysis: RunAnalysis, violations: Sequence[Violation]) -> str:
    """Summarize one run: patients, waits by level, occupancy, Little and invariants.

    - Patients over the whole log: arrived, departed and still inside; and the
      arrivals in the window, also per day.
    - By level (1 to 5 and the total), over the episodes that arrive in the
      window and depart: their number and the mean / p90 of the triage, box
      and doctor waits, door to doctor and the stay, in minutes. A level
      without episodes shows ``—``.
    - Occupancy of each pool in each shift: busy over the staff in force.
    - Little's law for the system and the triage and box queues.
    - The invariants: 0 violations, or how many by check and the first ten.

    Args:
        analysis: The analysis of the run, from ``analyze_run``.
        violations: The result of ``check_invariants`` on the same log.
    """
    m = analysis.metrics
    table = analysis.table
    departed = sum(e.departure is not None for e in table)
    per_day = m.arrivals / (m.end - m.start) * MINUTES_PER_DAY
    window = f"[día {m.start / MINUTES_PER_DAY:g}, día {m.end / MINUTES_PER_DAY:g})"
    lines = [
        f"Pacientes en todo el log: {len(table)} llegados, {departed} salidos,"
        f" {len(table) - departed} dentro al final",
        f"Ventana {window}: {m.arrivals} llegadas en la ventana, {per_day:.1f} al día",
        "",
        "Esperas y estancia por nivel, en minutos (media / p90; episodios que llegan"
        " en la ventana y salen)",
        f"{'nivel':<{_LEVEL_WIDTH}}{'n':>6}"
        + "".join(f"{label:>{_CELL_WIDTH}}" for _, label in SUMMARY_MEASURES),
    ]
    lines += [_level_row(str(lv.level), lv) for lv in m.by_level]
    lines.append(_level_row("total", m.overall))

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


def write_episodes_csv(
    episodes: Sequence[EpisodeTruth], path: Path, parameters: RunParameters
) -> None:
    """Write the ground truth of the episodes as a tidy CSV, one row per episode.

    Columns: ``episodio``, ``llegada`` (``arrival_id``), ``minuto_llegada``
    (bit for bit the instant of ``iter_arrivals``), ``nivel``, the drawn
    durations ``triaje``, ``valoracion`` and ``reevaluacion``, ``pruebas``
    (``True`` or ``False``), ``respuesta_pruebas``, ``destino`` (``alta`` or
    ``ingreso``, as in the log) and the run parameters. Durations are drawn
    even when not used, such as the turnaround of a patient without tests.
    """
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(EPISODE_COLUMNS)
        for e in episodes:
            writer.writerow(
                (
                    e.episode_id,
                    e.arrival_id,
                    e.arrival_time,
                    e.level,
                    e.triage_time,
                    e.assessment_time,
                    e.reassessment_time,
                    e.needs_tests,
                    e.test_turnaround,
                    "ingreso" if e.admitted else "alta",
                    *astuple(parameters),
                )
            )


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

    fig = _figure(11, 4.2)
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
        ax.set_xticklabels([f"{lv.level}\nn = {lv.n}" for lv in levels])
        ax.set_ylim(bottom=0)
        ax.set_title(title)
        ax.set_xlabel("Nivel de triaje")
        ax.grid(axis="y", alpha=0.3)
    axes[0].set_ylabel("Minutos")
    axes[0].legend(loc="upper left")
    fig.suptitle("Esperas por nivel en la ventana: media y p90")
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
