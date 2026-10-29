"""Replicated M/M/1 experiments compared with the steady-state theory.

One experiment runs ``R`` independent replications, each with its own
warm-up, computes the metrics of every replication and builds a confidence
interval per metric. The theoretical value should fall inside the interval;
with 95 % intervals, about one correct comparison in twenty falls outside by
chance.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from edsim.queueing.mm1 import MM1Metrics, mm1_metrics, simulate_mm1
from edsim.queueing.theory import mm1_theory
from edsim.stats import Summary, summarize

METRIC_NAMES = ("wq", "w", "lq", "l", "rho")


@dataclass(frozen=True, slots=True)
class MetricComparison:
    """Simulated metric versus its theoretical value.

    Attributes:
        name: Metric name, one of ``METRIC_NAMES``.
        theory: Steady-state value from the M/M/1 formulas.
        summary: Statistics of the metric across replications.
        rel_error: ``|mean - theory| / theory``.
        theory_in_ci: Whether the theoretical value lies inside the
            confidence interval.
    """

    name: str
    theory: float
    summary: Summary
    rel_error: float
    theory_in_ci: bool


@dataclass(frozen=True, slots=True)
class MM1Comparison:
    """Result of a replicated M/M/1 experiment.

    Attributes:
        replications: Metrics of each replication, in replication order.
        metrics: One comparison per metric, in the order of ``METRIC_NAMES``.
    """

    replications: tuple[MM1Metrics, ...]
    metrics: tuple[MetricComparison, ...]

    def metric(self, name: str) -> MetricComparison:
        """Return the comparison of the metric called ``name``."""
        for m in self.metrics:
            if m.name == name:
                return m
        raise KeyError(name)


def compare_mm1(
    lam: float,
    mu: float,
    duration: float,
    warmup: float,
    replicas: int = 20,
    seed: int = 2026,
    confidence: float = 0.95,
) -> MM1Comparison:
    """Run replications of an M/M/1 queue and compare them with the theory.

    Each replication simulates ``warmup + duration`` time units from an empty
    system and measures only ``[warmup, warmup + duration]``. Replication
    ``i`` uses child ``i`` of ``SeedSequence(seed).spawn(replicas)``, so it
    depends only on the master seed and its index: the same seed reproduces
    the experiment, and adding replications keeps the earlier ones.

    Args:
        lam: Arrival rate.
        mu: Service rate.
        duration: Observed time per replication, after the warm-up.
        warmup: Initial time discarded in every replication.
        replicas: Number of independent replications, at least 2.
        seed: Master seed of the experiment.
        confidence: Confidence level of the intervals.

    Returns:
        The per-replication metrics and one comparison per metric.

    Raises:
        ValueError: If the parameters are invalid, for example an unstable
            queue, a non-positive duration or fewer than 2 replications.
    """
    theory = mm1_theory(lam, mu)
    if duration <= 0:
        raise ValueError(f"duration must be positive, got {duration}")
    if replicas < 2:
        raise ValueError(f"at least 2 replications are needed, got {replicas}")

    horizon = warmup + duration
    children = np.random.SeedSequence(seed).spawn(replicas)
    replications = tuple(
        mm1_metrics(simulate_mm1(lam, mu, horizon, child), warmup, horizon) for child in children
    )

    metrics = []
    for name in METRIC_NAMES:
        summary = summarize((getattr(r, name) for r in replications), confidence)
        value = getattr(theory, name)
        metrics.append(
            MetricComparison(
                name=name,
                theory=value,
                summary=summary,
                rel_error=abs(summary.mean - value) / value,
                theory_in_ci=summary.ci_low <= value <= summary.ci_high,
            )
        )

    return MM1Comparison(replications=replications, metrics=tuple(metrics))


@dataclass(frozen=True, slots=True)
class Coverage:
    """Result of repeating a whole experiment with different master seeds.

    With 95 % intervals, about 95 % of the experiments should contain the
    theoretical value. Misses should fall on both sides; if they all fall on
    one side, the simulated metric is biased.

    Attributes:
        metric: Name of the metric, one of ``METRIC_NAMES``.
        seeds: Master seed of each experiment.
        intervals: Comparison of the metric in each experiment, in seed order.
    """

    metric: str
    seeds: tuple[int, ...]
    intervals: tuple[MetricComparison, ...]

    @property
    def hits(self) -> int:
        """Number of experiments whose interval contains the theory."""
        return sum(m.theory_in_ci for m in self.intervals)

    @property
    def rate(self) -> float:
        """Fraction of experiments whose interval contains the theory."""
        return self.hits / len(self.intervals)

    @property
    def below(self) -> tuple[int, ...]:
        """Seeds whose whole interval lies below the theory."""
        return tuple(
            s
            for s, m in zip(self.seeds, self.intervals, strict=True)
            if m.summary.ci_high < m.theory
        )

    @property
    def above(self) -> tuple[int, ...]:
        """Seeds whose whole interval lies above the theory."""
        return tuple(
            s
            for s, m in zip(self.seeds, self.intervals, strict=True)
            if m.summary.ci_low > m.theory
        )


def coverage_mm1(
    lam: float,
    mu: float,
    duration: float,
    warmup: float,
    replicas: int,
    seeds: Sequence[int],
    metric: str = "wq",
    confidence: float = 0.95,
) -> Coverage:
    """Run one ``compare_mm1`` experiment per master seed and keep one metric.

    Raises:
        ValueError: If there are no seeds, the metric is unknown or the
            experiment parameters are invalid.
    """
    if not seeds:
        raise ValueError("at least one seed is needed")
    if metric not in METRIC_NAMES:
        raise ValueError(f"unknown metric {metric!r}, expected one of {METRIC_NAMES}")
    intervals = tuple(
        compare_mm1(lam, mu, duration, warmup, replicas, seed, confidence).metric(metric)
        for seed in seeds
    )
    return Coverage(metric=metric, seeds=tuple(seeds), intervals=intervals)
