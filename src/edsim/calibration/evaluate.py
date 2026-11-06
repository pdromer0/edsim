"""Replications, comparison with the bands, sensitivity and choice of a staffing.

Simulating and evaluating are separate (docs/specs/hito-4.md, "Calibración"):

- **Simulate.** ``simulate_replicas`` runs R replications with common random
  numbers: child ``i`` of the seed (``child_streams``) is replication ``i`` for
  every candidate, so two staffings see the same patients and their difference
  is not noise. Each replication is reduced to a ``ReplicaValues`` at once and
  its events are dropped.
- **Evaluate.** ``replica_values`` (one replication) and ``summarize_targets``
  (all of them) are pure functions of the episodes.

**Drain day.** ``completed_in_window`` counts only the episodes that have
departed, and those who arrive in the last hours of the window and are still
inside at its end are mostly the ones who wait longest: cutting them biases
the waits down, precisely in the tight staffings. So each replication runs
``DRAIN_DAYS`` more day, with its arrivals, and only the patients who arrive in
the window ``[warmup_days, days)`` are measured. Those still inside at the end
of the horizon are counted as censored, per replication.

**Rule 4 of the calibration.** A target passes if the mean between
replications falls inside its band and the width of its 95 % confidence
interval (Student's t) is not larger than the width of the band.

**Days out.** Each replication gives the value of the target on each day of
the window (with the patients who arrived that day); a day is out if that
value is outside the band. The share of days out is the mean between
replications of each replication's share.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from edsim.arrivals.profile import ArrivalProfile
from edsim.arrivals.rate import MINUTES_PER_DAY
from edsim.calibration.targets import Target
from edsim.checks import check_count
from edsim.engine.analysis import EpisodeRecord, completed_in_window, episode_table
from edsim.engine.center import N_LEVELS, CenterConfig
from edsim.engine.engine import check_horizon, simulate_ed
from edsim.engine.events import Event, MemorySink
from edsim.engine.targets import manchester_compliance
from edsim.profiles.config import ClinicalProfiles
from edsim.seeds import child_streams
from edsim.stats import Summary, summarize

DRAIN_DAYS = 1
"""Days simulated after the window, with arrivals, so that its patients can leave."""

FIT_SEED = 2026
"""Seed of the fit (rule 3: different seeds to fit and to check)."""

CHECK_SEED = 2027
"""Seed of the check of the fitted staffing; never used to choose it."""

CONFIDENCE = 0.95
"""Confidence of the interval of rule 4."""

CENSORED_WARNING = 0.001
"""Share of censored patients of a replication above which the CLI warns."""

COMPLIANCE_SHARE_OUT = 0.10
"""Largest mean share of days out of Manchester (clock C) of the compliant center."""

COMPLIANCE_LEVELS = (2, 3, 4, 5)
"""Levels whose compliance the compliant center needs; level 1 has no share."""


# --- One replication ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TargetValues:
    """What one replication gives for one target.

    Attributes:
        value: The statistic over the patients of the window: the mean, or the
            percentage above the threshold; ``nan`` without patients.
        daily: The same on each day of the window, with the patients who
            arrived that day; ``nan`` on a day without them.
        n_by_level: Patients of the window of each level of the target.
        over_by_level: With a percentage, how many of them are above the
            threshold; empty with a mean.
    """

    value: float
    daily: tuple[float, ...]
    n_by_level: tuple[int, ...]
    over_by_level: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ReplicaValues:
    """One replication reduced to what the calibration needs.

    Attributes:
        targets: The values of each target, by its name.
        arrivals: Episodes that arrived in the window.
        censored: Of them, those without a departure at the end of the horizon.
        compliance_out: Share of the days of the window out of the Manchester
            compliance with clock C, per level 1 to 5; ``nan`` for a level
            without patients.
    """

    targets: Mapping[str, TargetValues]
    arrivals: int
    censored: int
    compliance_out: tuple[float, ...]

    @property
    def censored_share(self) -> float:
        """Censored over the arrivals of the window; 0 without arrivals."""
        return self.censored / self.arrivals if self.arrivals else 0.0


def _statistic(target: Target, episodes: Sequence[EpisodeRecord]) -> float:
    if not episodes:
        return math.nan
    values = np.array([_measure(target, e) for e in episodes], dtype=float)
    if not target.is_percentage:
        return float(values.mean())
    thresholds = np.array([target.threshold_for(e.level) for e in episodes], dtype=float)
    return float(100 * np.mean(values > thresholds))


def _measure(target: Target, e: EpisodeRecord) -> float:
    value = getattr(e, target.measure)
    if value is None:
        raise ValueError(f"{e.episode_id} departed without a {target.measure}")
    return value


def _target_values(
    target: Target, done: Sequence[EpisodeRecord], first_day: int, end_day: int
) -> TargetValues:
    episodes = [e for e in done if e.level in target.levels]
    by_day: list[list[EpisodeRecord]] = [[] for _ in range(first_day, end_day)]
    for e in episodes:
        by_day[math.floor(e.arrival / MINUTES_PER_DAY) - first_day].append(e)
    n_by_level = tuple(sum(e.level == level for e in episodes) for level in target.levels)
    over_by_level: tuple[int, ...] = ()
    if target.is_percentage:
        over_by_level = tuple(
            sum(
                _measure(target, e) > target.threshold_for(level)
                for e in episodes
                if e.level == level
            )
            for level in target.levels
        )
    return TargetValues(
        value=_statistic(target, episodes),
        daily=tuple(_statistic(target, day) for day in by_day),
        n_by_level=n_by_level,
        over_by_level=over_by_level,
    )


def replica_values(
    table: Sequence[EpisodeRecord], targets: Sequence[Target], first_day: int, end_day: int
) -> ReplicaValues:
    """Reduce the episodes of one replication: a pure function.

    Only the episodes that arrive in days ``[first_day, end_day)`` count, as in
    ``completed_in_window``; the day of an episode is the day of its arrival.

    Args:
        table: The episodes of the replication, from ``episode_table``; its
            horizon should go beyond ``end_day`` (``DRAIN_DAYS``).
        targets: The targets to evaluate.
        first_day: First day of the window, the warm-up.
        end_day: Day after the last of the window.

    Raises:
        ValueError: If the days are not valid, or a departed episode lacks the
            measure of a target.
    """
    if not 0 <= first_day < end_day:
        raise ValueError(f"need 0 <= first_day < end_day, got {first_day} and {end_day}")
    start, end = first_day * MINUTES_PER_DAY, end_day * MINUTES_PER_DAY
    arrived = [e for e in table if start <= e.arrival < end]
    done = completed_in_window(table, start, end)
    compliance = manchester_compliance(table, first_day, end_day)
    return ReplicaValues(
        targets=MappingProxyType(
            {t.name: _target_values(t, done, first_day, end_day) for t in targets}
        ),
        arrivals=len(arrived),
        censored=sum(e.departure is None for e in arrived),
        compliance_out=tuple(float(x) for x in compliance.share_out),
    )


# --- All the replications -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TargetResult:
    """One target against its band, over the replications.

    Attributes:
        target: The target.
        values: Its value in each replication.
        summary: Mean between replications and its confidence interval.
        days_out: Share of the days of each replication out of the band.
        within: Whether the mean is inside the band (the borders count).
        narrow: Whether the interval is not wider than the band.
    """

    target: Target
    values: tuple[float, ...]
    summary: Summary
    days_out: tuple[float, ...]
    within: bool
    narrow: bool

    @property
    def mean(self) -> float:
        return self.summary.mean

    @property
    def ci_width(self) -> float:
        return self.summary.ci_high - self.summary.ci_low

    @property
    def share_days_out(self) -> float:
        """Mean between replications of the share of days out of the band."""
        return float(np.mean(self.days_out))

    @property
    def passed(self) -> bool:
        """Rule 4: the mean inside the band and the interval not wider than it."""
        return self.within and self.narrow


def _days_out(daily: Sequence[float], band: tuple[float, float]) -> float:
    days = np.array(daily, dtype=float)
    days = days[~np.isnan(days)]
    if not days.size:
        return math.nan
    return float(np.mean((days < band[0]) | (days > band[1])))


def summarize_targets(
    replicas: Sequence[ReplicaValues],
    targets: Sequence[Target],
    confidence: float = CONFIDENCE,
) -> tuple[TargetResult, ...]:
    """Compare each target with its band over the replications: a pure function.

    Raises:
        ValueError: With fewer than 2 replications, or a target without
            patients in some replication.
    """
    check_count("replications", len(replicas), 2)
    out = []
    for target in targets:
        values = tuple(r.targets[target.name].value for r in replicas)
        if any(math.isnan(v) for v in values):
            raise ValueError(f"objetivos.{target.name}: some replication has no patients")
        summary = summarize(values, confidence)
        low, high = target.band
        out.append(
            TargetResult(
                target=target,
                values=values,
                summary=summary,
                days_out=tuple(
                    _days_out(r.targets[target.name].daily, target.band) for r in replicas
                ),
                within=bool(low <= summary.mean <= high),
                narrow=bool(summary.ci_high - summary.ci_low <= high - low),
            )
        )
    return tuple(out)


def evaluate_targets(
    tables: Sequence[Sequence[EpisodeRecord]],
    targets: Sequence[Target],
    first_day: int,
    end_day: int,
    confidence: float = CONFIDENCE,
) -> tuple[TargetResult, ...]:
    """``summarize_targets`` of the ``replica_values`` of each table: a pure function."""
    return summarize_targets(
        [replica_values(t, targets, first_day, end_day) for t in tables], targets, confidence
    )


@dataclass(frozen=True, slots=True)
class LevelShare:
    """One level of a percentage target, over the replications.

    Attributes:
        level: The assigned level.
        percentage: Mean between replications of the percentage of the
            patients of the level above the threshold.
        contribution: Mean between replications of the points it adds to the
            percentage of the target: its patients above the threshold over
            the patients of all the levels of the target, × 100. The
            contributions add up to the mean of the target.
    """

    level: int
    percentage: float
    contribution: float


def level_breakdown(replicas: Sequence[ReplicaValues], target: Target) -> tuple[LevelShare, ...]:
    """The percentage of a target split by level: a pure function.

    With clock A, level 2 (10 minutes) is above its Manchester maximum almost
    always, because the pretriage and the triage already take longer; the
    breakdown shows how much of the overall figure comes from each level.

    Raises:
        ValueError: If the target is a mean.
    """
    if not target.is_percentage:
        raise ValueError(f"objetivos.{target.name} is a mean: it has no breakdown by level")
    out = []
    for i, level in enumerate(target.levels):
        percentages, contributions = [], []
        for r in replicas:
            v = r.targets[target.name]
            total = sum(v.n_by_level)
            n, over = v.n_by_level[i], v.over_by_level[i]
            percentages.append(100 * over / n if n else math.nan)
            contributions.append(100 * over / total if total else math.nan)
        out.append(LevelShare(level, float(np.mean(percentages)), float(np.mean(contributions))))
    return tuple(out)


def mean_compliance_out(replicas: Sequence[ReplicaValues]) -> tuple[float, ...]:
    """Mean between replications of the share of days out of Manchester (clock C), by level."""
    return tuple(float(np.mean([r.compliance_out[k] for r in replicas])) for k in range(N_LEVELS))


# --- Simulating -----------------------------------------------------------------------------

Run = Callable[[int], Sequence[Event]]
"""A run of the engine: horizon in full days → its events, in file order."""


def replica_table(run: Run, days: int, warmup_days: int) -> tuple[EpisodeRecord, ...]:
    """The episodes of one replication, simulated with the drain day.

    ``run`` is called with ``days + DRAIN_DAYS``: the window ``[warmup_days,
    days)`` keeps its arrivals and the patients who arrive near its end can
    still leave.

    Raises:
        ValueError: If ``days`` or ``warmup_days`` are not valid.
    """
    days, warmup_days = check_horizon(days, warmup_days)
    return episode_table(run(days + DRAIN_DAYS))


def clinical_run(
    center: CenterConfig,
    arrival_profile: ArrivalProfile,
    profiles: ClinicalProfiles,
    seed: int | np.random.SeedSequence,
    warmup_days: int,
) -> Run:
    """The clinical model in memory with this seed, as a ``Run``."""

    def run(horizon_days: int) -> list[Event]:
        sink = MemorySink()
        simulate_ed(
            center,
            arrival_profile,
            horizon_days,
            seed,
            sink=sink,
            warmup_days=warmup_days,
            profiles=profiles,
        )
        return sink.events

    return run


def simulate_replicas(
    center: CenterConfig,
    arrival_profile: ArrivalProfile,
    profiles: ClinicalProfiles,
    targets: Sequence[Target],
    *,
    replicas: int,
    days: int,
    warmup_days: int,
    seed: int | np.random.SeedSequence,
) -> tuple[ReplicaValues, ...]:
    """Simulate ``replicas`` replications and reduce each one at once.

    Replication ``i`` uses child ``i`` of ``seed`` (``child_streams``): the same
    patients for every center, the common random numbers that make the
    comparison of two staffings paired.

    Raises:
        ValueError: If ``replicas`` is below 2 or the days are not valid.
    """
    replicas = check_count("replicas", replicas, 2)
    days, warmup_days = check_horizon(days, warmup_days)
    out = []
    for child in child_streams(seed, replicas):
        run = clinical_run(center, arrival_profile, profiles, child, warmup_days)
        out.append(
            replica_values(replica_table(run, days, warmup_days), targets, warmup_days, days)
        )
    return tuple(out)
