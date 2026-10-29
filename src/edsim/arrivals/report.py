"""Presentation of arrivals: validation table, tidy CSV and plots.

These functions only format records and results that ``simulate_arrivals``
and ``validate_arrivals`` already computed; they do not simulate. The CLI
calls them, and so can tests and notebooks. Labels are in Spanish here, while
the keys of the tests stay in English in ``validation.py``.

The CSV files are tidy: one row per arrival or per day, with the parameters
of the run (configuration file, its fingerprint, days and seed) repeated in
every row, so each file records how it was generated. Floats are written with
``repr``, all their digits, so reading them back gives the same value.

The plots use matplotlib's Agg canvas directly instead of ``pyplot``, as in
``edsim.queueing.report``: importing this module never changes the global
backend, and figures are not kept in pyplot's registry.
"""

import csv
import hashlib
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from scipy import stats

from edsim.arrivals.profile import ArrivalProfile
from edsim.arrivals.rate import MINUTES_PER_DAY
from edsim.arrivals.thinning import ArrivalRecord, DayRecord
from edsim.arrivals.validation import (
    ALPHA,
    ValidationResult,
    daily_residuals,
    hour_of_day,
    hourly_counts,
    rescaled_gaps,
)

TEST_LABELS = {
    "volume": "a. Volumen",
    "hourly_shape": "b. Forma horaria",
    "rescaled_gaps": "c. Huecos reescalados",
    "dispersion": "d. Dispersión diaria",
    "p_uniformity": "e. Uniformidad de los p-valores",
}

WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")

DETAIL_LABELS = {
    "total": "total",
    **dict(
        zip(
            ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"),
            WEEKDAYS,
            strict=True,
        )
    ),
    "unconditional": "sin Z",
    "conditional": "condicional",
}

PARAMETER_COLUMNS = ("config", "huella", "dias", "semilla")
ARRIVALS_COLUMNS = ("id", "minuto", "fecha_hora", "dia_semana", "hora", *PARAMETER_COLUMNS)
DAYS_COLUMNS = (
    "dia",
    "fecha",
    "efecto_diario",
    "esperadas",
    "cota",
    "candidatas",
    "aceptadas",
    *PARAMETER_COLUMNS,
)

FINGERPRINT_LENGTH = 12

# Slots 1 and 2 of the reference categorical palette (dataviz skill): what was
# observed in blue, the hypothesis in orange.
OBSERVED_COLOR = "#2a78d6"
THEORY_COLOR = "#eb6834"

_SECONDS_PER_DAY = 86_400
_RESIDUAL_BINS = 40


# --- Validation table ---------------------------------------------------------------


def _row(label: str, r: ValidationResult) -> str:
    if r.p_value is not None:
        evidence = f"p = {r.p_value:.4f}"
        target = "—"
        criterion = f"p ≥ {ALPHA:g}"
    else:
        evidence = f"[{r.ci_low:.4f}, {r.ci_high:.4f}]"
        target = f"{r.target:.4f}"
        criterion = f"objetivo ∈ IC {100 * r.confidence:g} %"
    outcome = "pasa" if r.passed else "FALLA"
    return f"{label:<34}{r.statistic:>12.4f}{evidence:>22}{target:>10}  {criterion:<24}{outcome}"


def format_validation(results: Sequence[ValidationResult]) -> str:
    """Format the five validation tests as a table, with their details below.

    One row per test: statistic, p-value or confidence interval, target,
    criterion and outcome. The intervals of a test with several (the total
    and the seven weekdays of a; the two Pearson indexes of d) follow it,
    indented. A failure is written in capitals, ``FALLA``, so it stands out,
    and the last line sums up which tests fail.
    """
    rows = [
        f"{'prueba':<34}{'estadístico':>12}{'p-valor / IC':>22}{'objetivo':>10}"
        f"  {'criterio':<24}resultado"
    ]
    for r in results:
        rows.append(_row(TEST_LABELS[r.name], r))
        rows.extend(_row(f"    {DETAIL_LABELS[d.name]}", d) for d in r.details)

    failed = [TEST_LABELS[r.name].split(".")[0] for r in results if not r.passed]
    if failed:
        rows.append(f"\nResultado: FALLAN {', '.join(failed)}")
    else:
        rows.append(f"\nResultado: pasan las {len(results)} pruebas")
    return "\n".join(rows)


# --- CSV ------------------------------------------------------------------------------


def config_fingerprint(path: str | Path) -> str:
    """The first 12 hexadecimal digits of the SHA-256 of a file's bytes.

    It identifies the exact configuration a run used: two files with the
    same name but different values have different fingerprints.
    """
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:FINGERPRINT_LENGTH]


def _clock(time: float, start_date: date) -> datetime:
    """Date and time of a minute since ``start_date``, truncated to the second.

    The day and the second of the day are computed separately and the second
    is capped at 23:59:59, so the result always falls on the same day as
    ``time // 1440``. ``timedelta(minutes=time)`` would round to the
    microsecond and could move an arrival at 23:59:59.9999999 to the next
    day.
    """
    day = int(time // MINUTES_PER_DAY)
    second = min(int((time - day * MINUTES_PER_DAY) * 60), _SECONDS_PER_DAY - 1)
    return datetime.combine(start_date, datetime.min.time()) + timedelta(days=day, seconds=second)


def write_arrivals_csv(
    arrivals: Sequence[ArrivalRecord],
    start_date: date,
    path: Path,
    *,
    config: str,
    fingerprint: str,
    days: int,
    seed: int,
) -> None:
    """Write the arrivals as a tidy CSV, one row per arrival.

    Columns: ``id``, ``minuto`` (minutes since ``start_date``),
    ``fecha_hora`` (ISO 8601, to the second, truncated), ``dia_semana`` (in
    Spanish), ``hora`` (hour of the clock, as in test b) and the run
    parameters.

    Args:
        arrivals: Arrivals of one run.
        start_date: Date of minute 0, the profile's ``start_date``.
        path: File to write.
        config: Path of the configuration file, as given.
        fingerprint: ``config_fingerprint`` of that file.
        days: Days of the run.
        seed: Seed of the run.
    """
    hours = hour_of_day([a.time for a in arrivals])
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(ARRIVALS_COLUMNS)
        for a, hour in zip(arrivals, hours, strict=True):
            moment = _clock(a.time, start_date)
            writer.writerow(
                (
                    a.arrival_id,
                    a.time,
                    moment.isoformat(),
                    WEEKDAYS[moment.weekday()],
                    int(hour),
                    config,
                    fingerprint,
                    days,
                    seed,
                )
            )


def write_days_csv(
    day_records: Sequence[DayRecord],
    path: Path,
    *,
    config: str,
    fingerprint: str,
    days: int,
    seed: int,
) -> None:
    """Write the day records (ground truth) as a tidy CSV, one row per day.

    Columns: ``dia``, ``fecha`` (ISO 8601), ``efecto_diario`` (Z),
    ``esperadas`` (Lambda of the day, with Z), ``cota``, ``candidatas``,
    ``aceptadas`` and the run parameters, as in ``write_arrivals_csv``.
    """
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(DAYS_COLUMNS)
        for d in day_records:
            writer.writerow(
                (
                    d.day,
                    d.date.isoformat(),
                    d.day_effect,
                    d.expected,
                    d.bound,
                    d.candidates,
                    d.accepted,
                    config,
                    fingerprint,
                    days,
                    seed,
                )
            )


# --- Plots ----------------------------------------------------------------------------


def _figure(width: float, height: float) -> Figure:
    fig = Figure(figsize=(width, height), layout="constrained")
    FigureCanvasAgg(fig)
    return fig


def plot_hourly_profile(
    profile: ArrivalProfile, arrivals: Sequence[ArrivalRecord], days: Sequence[DayRecord]
) -> Figure:
    """Arrivals by hour of the clock: observed bars against the expected counts.

    The counts are ``hourly_counts``, the ones test b compares: the expected
    counts are scaled to the total observed, so the plot shows the shape.

    Returns:
        The figure, attached to an Agg canvas; save it with ``savefig``.
    """
    observed, expected = hourly_counts(profile, arrivals, days)
    hours = np.arange(24)

    fig = _figure(8, 4.5)
    ax = fig.add_subplot()
    ax.bar(hours, observed, width=0.8, color=OBSERVED_COLOR, label="Observadas")
    ax.plot(hours, expected, "o-", color=THEORY_COLOR, linewidth=2, markersize=6, label="Esperadas")
    ax.set_xticks(hours[::2])
    ax.set_xlim(-0.6, 23.6)
    ax.set_xlabel("Hora del reloj")
    ax.set_ylabel("Llegadas en la hora, sumadas en todos los días")
    ax.set_title(f"Forma horaria: {len(days)} días, {len(arrivals)} llegadas")
    ax.grid(axis="y", alpha=0.3)
    ax.legend()
    return fig


def plot_rescaled_qq(
    profile: ArrivalProfile, arrivals: Sequence[ArrivalRecord], days: Sequence[DayRecord]
) -> Figure:
    """QQ plot of the rescaled gaps against an exponential of mean 1.

    Every gap is plotted: its sorted value against the Exp(1) quantile at
    the plotting position ``(i - 0.5) / n``. Under the hypothesis the points
    lie on the diagonal; the tails show first when they do not.

    Returns:
        The figure, attached to an Agg canvas; save it with ``savefig``.
    """
    gaps = np.sort(rescaled_gaps(profile, arrivals, days))
    n = gaps.size
    quantiles = stats.expon.ppf((np.arange(1, n + 1) - 0.5) / n)
    top = max(gaps.max(), quantiles.max())

    fig = _figure(5.5, 5.5)
    ax = fig.add_subplot()
    # With about 10^5 points, the markers must be small to stay readable.
    ax.plot(
        quantiles,
        gaps,
        ".",
        color=OBSERVED_COLOR,
        markersize=3,
        label=f"Huecos reescalados ({n})",
    )
    ax.plot([0, top], [0, top], color=THEORY_COLOR, linewidth=2, label="Diagonal: Exp(1)")
    ax.set_xlim(0, top)
    ax.set_ylim(0, top)
    ax.set_aspect("equal")
    ax.set_xlabel("Cuantil teórico de Exp(1)")
    ax.set_ylabel("Hueco reescalado Λ(tᵢ) − Λ(tᵢ₋₁)")
    ax.set_title("Huecos reescalados frente a Exp(1)")
    ax.grid(alpha=0.3)
    ax.legend()
    return fig


def plot_daily_residuals(profile: ArrivalProfile, runs: Sequence[Sequence[DayRecord]]) -> Figure:
    """Histograms of the standardized daily residuals against a standard normal.

    Left, given Z: ``(c - e*Z) / sqrt(e*Z)``; right, without Z:
    ``(c - e) / sqrt(e + CV**2 * e**2)`` (``daily_residuals``), over the days
    of every run, such as the replications of test d. Both histograms share
    40 bins over a symmetric range that holds every residual.

    Args:
        profile: The profile of the hypothesis, whose ``daily_cv`` enters
            the residual without Z.
        runs: Day records of each run, each from day 0.

    Returns:
        The figure, attached to an Agg canvas; save it with ``savefig``.
    """
    parts = [daily_residuals(profile, r) for r in runs]
    conditional = np.concatenate([c for c, _ in parts])
    unconditional = np.concatenate([u for _, u in parts])
    largest = max(np.abs(conditional).max(), np.abs(unconditional).max())
    limit = max(4.0, float(np.ceil(largest)))
    bins = np.linspace(-limit, limit, _RESIDUAL_BINS + 1)
    grid = np.linspace(-limit, limit, 200)

    fig = _figure(10, 4.5)
    axes = fig.subplots(1, 2, sharex=True, sharey=True)
    panels = (
        (axes[0], conditional, "Con Z: (c − e·Z) / √(e·Z)"),
        (axes[1], unconditional, f"Sin Z: (c − e) / √(e + CV²·e²), CV = {profile.daily_cv:g}"),
    )
    for ax, residuals, title in panels:
        ax.hist(
            residuals,
            bins=bins,
            density=True,
            color=OBSERVED_COLOR,
            edgecolor="white",
            linewidth=0.5,
            label=f"{residuals.size} días, DT = {np.std(residuals):.3f}",
        )
        ax.plot(grid, stats.norm.pdf(grid), color=THEORY_COLOR, linewidth=2, label="N(0, 1)")
        ax.set_title(title)
        ax.set_xlabel("Residuo estandarizado")
        ax.grid(axis="y", alpha=0.3)
        ax.legend(loc="upper right")
    axes[0].set_ylabel("Densidad")
    return fig
