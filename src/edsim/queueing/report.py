"""Presentation of M/M/1 experiments: text table, tidy CSV and Wq plot.

These functions only format results that ``compare_mm1`` already computed;
they do not simulate. The CLI calls them, and so can tests and notebooks.

The plot uses matplotlib's Agg canvas directly instead of ``pyplot``, so
importing this module never changes the global backend (for example inside a
notebook) and figures are not kept in pyplot's registry of open figures.
"""

import csv
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from edsim.queueing.replications import MM1Comparison
from edsim.queueing.theory import mm1_theory

METRIC_LABELS = {"wq": "Wq", "w": "W", "lq": "Lq", "l": "L", "rho": "ρ"}

CSV_COLUMNS = (
    "rho",
    "metrica",
    "teoria",
    "media",
    "desv_tipica",
    "ic_inf",
    "ic_sup",
    "error_rel",
    "dentro_ic",
    "replicas",
    "duracion",
    "warmup",
    "semilla",
)

# One point of a sweep: the utilization and the experiment run at it (mu = 1).
SweepPoint = tuple[float, MM1Comparison]


def format_comparison(c: MM1Comparison) -> str:
    """Format a comparison as a table, one row per metric.

    Columns: metric, theory, simulated mean, confidence interval, relative
    error and whether the theory falls inside the interval. A miss is written
    in capitals, ``NO``, so it stands out.
    """
    level = c.metrics[0].summary.confidence * 100
    ci_title = f"IC {level:g} %"
    rows = [f"{'métrica':<8}{'teoría':>10}{'media':>10}{ci_title:>24}{'error rel.':>12}  dentro"]
    for m in c.metrics:
        s = m.summary
        rows.append(
            f"{METRIC_LABELS[m.name]:<8}{m.theory:>10.4f}{s.mean:>10.4f}"
            f"  [{s.ci_low:>9.4f}, {s.ci_high:>9.4f}]"
            f"{m.rel_error * 100:>10.2f} %  {'sí' if m.theory_in_ci else 'NO'}"
        )
    return "\n".join(rows)


def write_sweep_csv(
    points: Sequence[SweepPoint], path: Path, *, duration: float, warmup: float, seed: int
) -> None:
    """Write a sweep as a tidy CSV: one row per utilization and metric.

    The run parameters are repeated in every row, so each file records how it
    was generated and several sweeps can be stacked into one table. Floats are
    written with all their digits, so reading them back gives the same value.
    """
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_COLUMNS)
        for rho, c in points:
            for m in c.metrics:
                s = m.summary
                writer.writerow(
                    (
                        rho,
                        m.name,
                        m.theory,
                        s.mean,
                        s.std,
                        s.ci_low,
                        s.ci_high,
                        m.rel_error,
                        m.theory_in_ci,
                        s.n,
                        duration,
                        warmup,
                        seed,
                    )
                )


def plot_sweep(points: Sequence[SweepPoint]) -> Figure:
    """Plot the theoretical Wq against rho and the simulated points.

    The theoretical curve, ``Wq = rho / (1 - rho)`` with ``mu = 1``, is
    evaluated on 200 points up to the largest simulated rho. Each simulated
    point is the mean of the replications with its confidence interval as an
    error bar. The axis is linear so the blow-up near ``rho = 1`` is visible.

    Returns:
        The figure, attached to an Agg canvas; save it with ``savefig``.
    """
    rhos = np.array([rho for rho, _ in points])
    summaries = [c.metric("wq").summary for _, c in points]
    means = np.array([s.mean for s in summaries])
    errors = np.array(
        [[s.mean - s.ci_low for s in summaries], [s.ci_high - s.mean for s in summaries]]
    )
    level = summaries[0].confidence * 100

    grid = np.linspace(0.005, rhos.max(), 200)
    theory = [mm1_theory(r, 1.0).wq for r in grid]

    fig = Figure(figsize=(7, 4.5), layout="constrained")
    FigureCanvasAgg(fig)
    ax = fig.add_subplot()
    ax.plot(grid, theory, label="Teoría")
    ax.errorbar(
        rhos, means, yerr=errors, fmt="o", capsize=3, label=f"Simulación (media e IC {level:g} %)"
    )
    ax.set_xlim(0, 1)
    ax.set_ylim(bottom=0)
    ax.set_xlabel("Utilización ρ")
    ax.set_ylabel("Espera media en cola Wq")
    ax.set_title("M/M/1 con μ = 1: Wq frente a ρ")
    ax.grid(alpha=0.3)
    ax.legend()
    return fig
