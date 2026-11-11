"""Presentation of ``edsim perfiles validar``: the table and the four plots.

These functions only format what ``validate_profiles`` already computed; they
do not draw patients. Labels are in Spanish here, while the keys of the checks
stay in English in ``validation.py``. Each plot shows the exact value of the
profiles and the observed one with its 95 % interval: with many categories,
about one interval in twenty misses the exact value by chance, so the verdict
is that of the table, with Bonferroni.
"""

from collections.abc import Sequence

import numpy as np
from matplotlib.axes import Axes
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from edsim.profiles.validation import (
    ALPHA,
    CHECK_NAMES,
    CONFIDENCE,
    CheckOutcome,
    ProfilesFigures,
    ProfilesValidation,
    QuantileComparison,
    ShareComparison,
)

CHECK_LABELS = {
    "mixing": "Mezcla de motivos",
    "triage": "Triaje",
    "workup": "Pruebas",
    "durations": "Duraciones",
    "patience": "Paciencia",
    "destinations": "Destinos",
}
"""The rows of the table, in Spanish."""

MAX_FAILURES_SHOWN = 10
"""Failing categories listed under the table for each check."""


def false_alarm(checks: int) -> str:
    """The joint false alarm rate of ``checks`` checks, by Boole's inequality."""
    return (
        f"Cada comprobación usa α = {ALPHA:g} con Bonferroni dentro de ella; con las "
        f"{checks}, un muestreador correcto falla alguna hasta un "
        f"{100 * checks * ALPHA:g} % de las veces (desigualdad de Boole)."
    )


FALSE_ALARM = false_alarm(len(CHECK_NAMES))
"""The joint false alarm rate of the four checks, under the table and in the help."""

WITHOUT_OUTCOME = (
    "Paciencia y destinos: no se comprueban; los perfiles no tienen el bloque del hito 5 "
    "([abandono], [destinos] e ingreso en los motivos)."
)
"""What the table says with profiles of milestone 4 (task 5.3)."""

PLOT_NOTE = (
    f"Exacto (perfiles) y observado con su IC al {100 * CONFIDENCE:g} %. Con muchas categorías, "
    "uno de cada veinte IC deja fuera lo exacto por azar: el veredicto es de la tabla."
)


def _percent(p: float) -> str:
    return f"{100 * p:.2f} %" if p < 0.01 else f"{100 * p:.1f} %"


def _detectable(c: CheckOutcome) -> str:
    d = c.detectable
    return f"{d.category}: {_percent(d.p0)} → {_percent(d.p1)}"


def _failing(c: CheckOutcome) -> list[str]:
    leaves = [
        (f"{d.name}/{x.name}" if d.details else x.name, x)
        for d in c.result.details
        for x in (d.details or (d,))
    ]
    failing = [(name, x) for name, x in leaves if not x.passed]
    lines = [
        f"    {name}: p = {x.p_value:.3g}, exacto {_percent(x.target)}"
        for name, x in failing[:MAX_FAILURES_SHOWN]
    ]
    if len(failing) > MAX_FAILURES_SHOWN:
        lines.append(f"    … y {len(failing) - MAX_FAILURES_SHOWN} más")
    return lines


def format_profiles_validation(validation: ProfilesValidation) -> str:
    """Format the four checks (six with the milestone 5 block) as a table, with the
    failing categories below.

    One row per check: patients drawn, categories, failures, the smallest
    p-value against the level of each category (Bonferroni), the error of a
    reference category it sees with a power of 80 % and its time. Below, the
    draw of the year, the joint false alarm rate and the result.
    """
    rows = [
        f"{'comprobación':<19}{'pacientes':>10}{'categorías':>12}{'fallos':>8}"
        f"{'p mínimo':>11}{'α (Bonferroni)':>16}  {'error detectable (80 %)':<56}"
        f"{'tiempo':>8}  resultado"
    ]
    for c in validation.checks:
        rows.append(
            f"{CHECK_LABELS[c.name]:<19}{c.patients:>10}{c.categories:>12}{c.failures:>8}"
            f"{c.min_p:>11.3g}{c.alpha:>16.3g}  {_detectable(c):<56}"
            f"{c.seconds:>6.1f} s  {'pasa' if c.passed else 'FALLA'}"
        )
    rows.append("")
    rows.append(
        f"Muestra del año: {validation.year_patients} pacientes, sorteados una vez en "
        f"{validation.year_seconds:.1f} s para el triaje, las pruebas y las duraciones."
    )
    if not validation.has_outcome:
        rows.append(WITHOUT_OUTCOME)
    rows.append(false_alarm(len(validation.checks)))
    failed = [c for c in validation.checks if not c.passed]
    for c in failed:
        rows.append(f"\n{CHECK_LABELS[c.name]}: fallan {c.failures} categorías")
        rows.extend(_failing(c))
    if failed:
        names = ", ".join(CHECK_LABELS[c.name].lower() for c in failed)
        rows.append(f"\nResultado: FALLAN {names}")
    else:
        rows.append(f"\nResultado: pasan las {len(validation.checks)} comprobaciones")
    return "\n".join(rows)


# --- Plots ------------------------------------------------------------------------------
# Built with Figure, not pyplot, as in arrivals/report.py: importing this module
# never changes the global backend.


def _figure(width: float, height: float) -> Figure:
    fig = Figure(figsize=(width, height), layout="constrained")
    FigureCanvasAgg(fig)
    return fig


def _errorbars(
    ax: Axes,
    x: np.ndarray,
    c: ShareComparison | QuantileComparison,
    scale: float,
    color: str = "C1",
    label: str | None = "observado",
) -> None:
    observed = np.array(c.observed) * scale
    below = observed - np.array(c.low) * scale
    above = np.array(c.high) * scale - observed
    ax.errorbar(
        x, observed, yerr=[below, above], fmt="o", color=color, ms=4, capsize=2, label=label
    )


def plot_reasons(figures: ProfilesFigures) -> Figure:
    """The 17 reasons of the sample of the year: exact bars and observed points with IC."""
    c = figures.reasons
    fig = _figure(10, 4.5)
    ax = fig.add_subplot()
    x = np.arange(len(c.labels))
    ax.bar(x, np.array(c.exact) * 100, color="C0", alpha=0.5, label="exacto")
    _errorbars(ax, x, c, 100)
    ax.set_xticks(x, c.labels, rotation=60, ha="right")
    ax.set_ylabel("pacientes (%)")
    ax.set_title(f"Motivos de consulta en la muestra del año ({c.counts[0]} pacientes)")
    ax.legend()
    fig.supxlabel(PLOT_NOTE, fontsize=8)
    return fig


def plot_triage(figures: ProfilesFigures) -> Figure:
    """P(assigned | true) for each true level: one panel per true level."""
    fig = _figure(14, 3.6)
    axes = fig.subplots(1, len(figures.triage), sharey=True)
    for ax, c in zip(axes, figures.triage, strict=True):
        x = np.arange(1, len(c.labels) + 1)
        ax.bar(x, np.array(c.exact) * 100, color="C0", alpha=0.5, label="exacto")
        _errorbars(ax, x, c, 100)
        ax.set_xticks(x)
        ax.set_xlabel("nivel asignado")
        ax.set_title(f"{c.title} ({c.counts[0]} pacientes)", fontsize=10)
    axes[0].set_ylabel("P(asignado | real) (%)")
    axes[0].legend()
    fig.suptitle("Triaje: nivel asignado según el nivel real")
    fig.supxlabel(PLOT_NOTE, fontsize=8)
    return fig


def plot_workup(figures: ProfilesFigures) -> Figure:
    """Ordering each type of test by fifth of G: exact line and observed points with IC."""
    fig = _figure(10, 4.5)
    ax = fig.add_subplot()
    for i, c in enumerate(figures.workup):
        x = np.arange(1, len(c.labels) + 1) + (i - 1.5) * 0.06
        ax.plot(x, np.array(c.exact) * 100, color=f"C{i}", label=f"{c.title} (exacto)")
        _errorbars(ax, x, c, 100, color=f"C{i}", label=None)
    ax.set_xticks(range(1, len(figures.workup[0].labels) + 1))
    ax.set_xlabel("quintil de G (1, el menos grave)")
    ax.set_ylabel("se pide la prueba (%)")
    ax.set_title("Pruebas por quintil de gravedad (puntos: observado con su IC)")
    ax.legend(fontsize=8)
    fig.supxlabel(PLOT_NOTE, fontsize=8)
    return fig


def plot_durations(figures: ProfilesFigures) -> Figure:
    """Median and p90 of the assessment and the reassessment by true level."""
    fig = _figure(10, 4.5)
    axes = fig.subplots(1, 2, sharex=True)
    for ax, which, title in zip(
        axes, ("valoracion", "reevaluacion"), ("Valoración", "Reevaluación"), strict=True
    ):
        comparisons: Sequence[QuantileComparison] = [
            c for c in figures.durations if c.title.startswith(f"{which}/")
        ]
        for i, c in enumerate(comparisons):
            x = np.arange(1, len(c.labels) + 1)
            name = c.title.split("/")[1]
            ax.plot(x, c.exact, color=f"C{i}", label=f"{name} (exacto)")
            _errorbars(ax, x + 0.05, c, 1, color=f"C{i}", label=f"{name} (observado)")
        ax.set_xticks(range(1, len(comparisons[0].labels) + 1))
        ax.set_xlabel("nivel real")
        ax.set_ylabel("minutos")
        ax.set_title(title)
        ax.legend(fontsize=8)
    fig.suptitle("Duraciones por nivel real: mediana y p90")
    fig.supxlabel(PLOT_NOTE, fontsize=8)
    return fig


PLOTS = (
    ("motivos.png", plot_reasons),
    ("triaje.png", plot_triage),
    ("pruebas_por_gravedad.png", plot_workup),
    ("duraciones_por_nivel.png", plot_durations),
)
"""The four plots of ``edsim perfiles validar``: file name and function."""
