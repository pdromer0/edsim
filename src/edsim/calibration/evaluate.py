"""Replications, comparison with the bands, sensitivity and choice of a staffing.

Simulating and evaluating are separate (docs/specs/hito-4.md, "Calibración"):

- **Simulate.** ``simulate_replicas`` runs R replications with common random
  numbers: child ``i`` of the seed (``child_streams``) is replication ``i`` for
  every candidate, so two staffings see the same patients and their difference
  is not noise. Each replication may start on its own date (the annual window
  of ``calibration.window``: one per month); the same date for every candidate.
  Each replication is reduced to a ``ReplicaValues`` at once and its events are
  dropped.
- **Evaluate.** ``replica_values`` (one replication) and ``summarize_targets``
  (all of them) are pure functions of the episodes.

**Drain day.** ``completed_in_window`` counts only the episodes that have
departed, and those who arrive in the last hours of the window and are still
inside at its end are mostly the ones who wait longest: cutting them biases
the waits down, precisely in the tight staffings. So each replication runs
``DRAIN_DAYS`` more day, with its arrivals, and only the patients who arrive in
the window ``[warmup_days, days)`` are measured. Those still inside at the end
of the horizon are counted as censored, per replication: inside, not merely
without a departure, since whoever leaves without being seen has none either
(milestone 5).

**Who counts, with the abandonment** (the rules of task 5.4, H5-8; without it,
every rule gives the values of before bit for bit):

- the pretriage (``triage_wait``), of the triaged patients that end in the
  window, also those who leave after the triage (``triaged_in_window``);
- the means of the clocks to the doctor and of the other waits, of the patients
  who depart (the attended, ``completed_in_window``);
- the percentage of a clock above its threshold, with the censoring of the
  Manchester compliance (``compliance_cases``): whoever leaves with its clock at
  or above the threshold is above it for sure, and whoever leaves before is
  censored and does not count;
- the stay, of those who depart (to the ``destino`` of the target) and of those
  still inside at the horizon who would count (the admitted waiting for a bed,
  or every patient already seen without a ``destino``), at their lower bound
  ``horizon - arrival``: the mean is then a bound (``TargetValues.bounded``),
  and above a threshold a bound counts only once past it, as
  ``over_threshold`` of ``engine.outcome_metrics``;
- a percentage of the arrivals (``porcentaje_de_llegadas``), over every patient
  who arrives in the window, classified or not.

**Rule 4 of the calibration.** A target passes if the mean between
replications falls inside its band and the width of its 95 % confidence
interval (Student's t) is not larger than the width of the band. With the
annual window the spread between replications includes the variation between
months, so the interval is conservative. ``pooled_value``, the mean per patient
of all the replications (the yearly mean, which weighs each month by its
arrivals), is reported but never chooses.

**Days out.** Each replication gives the value of the target on each day of
the window (with the patients who arrived that day); a day is out if that
value is outside the band. The share of days out is the mean between
replications of each replication's share.

**The check seed may veto, never choose** (decision 41, revised in task 4.6c).
``choose_staffing`` takes the staffings that pass the fit targets with the fit
seed in the order of the choice; with ``check`` it skips each one whose fit
targets fail with the check seed, and chooses the first that passes with both.
Once the check seed has vetoed, the independent check of the staffing chosen is
``CONFIRMATION_SEED``.

**The compliant center** is decided with whole days (task 4.6c): the days out
of Manchester with clock C summed over the replications against the days with
patients summed over them, ``out ≤ share · days`` with an exact fraction. It is
not the mean of each replication's share when the replications have different
days with patients of a level, and it does not depend on rounding.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from types import MappingProxyType

import numpy as np

from edsim.arrivals.profile import ArrivalProfile
from edsim.arrivals.rate import MINUTES_PER_DAY
from edsim.calibration.staffing import (
    DOCTORS,
    KNOBS,
    NURSES,
    U_MAX,
    U_MIN,
    U_STEP,
    RuleStaffing,
    knob_loads,
    rule_staffings,
)
from edsim.calibration.targets import (
    ARRIVALS_PERCENTAGE,
    DEPARTURE,
    FIT,
    LEFT,
    STAY,
    Target,
)
from edsim.calibration.window import with_start_date
from edsim.checks import check_count
from edsim.engine.analysis import (
    EpisodeRecord,
    completed_in_window,
    episode_table,
    triaged_in_window,
)
from edsim.engine.center import N_LEVELS, CenterConfig
from edsim.engine.clinical_sampler import PatientModel, choose_model
from edsim.engine.engine import check_horizon, simulate_ed
from edsim.engine.events import Event, MemorySink
from edsim.engine.outcome_metrics import ADMISSION
from edsim.engine.targets import CLOCKS, compliance_cases, manchester_compliance
from edsim.profiles.config import ClinicalProfiles
from edsim.seeds import child_streams
from edsim.stats import Summary, summarize

DRAIN_DAYS = 1
"""Days simulated after the window, with arrivals, so that its patients can leave."""

FIT_SEED = 2026
"""Seed of the fit (rule 3: different seeds to fit and to check)."""

CHECK_SEED = 2027
"""Seed of the check of the fitted staffing: it may veto the choice, never make it
(decision 41, revised in task 4.6c; ``choose_staffing`` with ``check``)."""

CONFIRMATION_SEED = 2028
"""Seed of the independent check once the check seed has taken part in the choice
(task 4.6c: it vetoed the nurses chosen with the fit seed)."""

CONFIDENCE = 0.95
"""Confidence of the interval of rule 4."""

CENSORED_WARNING = 0.001
"""Share of censored patients of a replication above which the CLI warns."""

ADMITTED_CENSORED_WARNING = 0.01
"""Share of the admitted patients of a replication still waiting for a bed at the end of
the drain day above which the CLI warns (task 5.6): their stay enters the means at its
lower bound."""

BOTTLENECK_LEVELS = (2, 3, 4, 5)
"""Levels of the bottleneck line: the wait for a box against the wait for a doctor."""

COMPLIANCE_SHARE_OUT = Fraction(1, 10)
"""Largest share of days out of Manchester (clock C) of the compliant center: the
days out summed over the replications over the days with patients summed over
them, compared exactly."""

COMPLIANCE_LEVELS = (2, 3, 4, 5)
"""Levels whose compliance the compliant center needs; level 1 has no share."""


# --- One replication ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TargetValues:
    """What one replication gives for one target.

    Attributes:
        value: The statistic over the patients of the window: the mean, or the
            percentage above the threshold or of the arrivals; ``nan`` without
            patients.
        daily: The same on each day of the window, with the patients who
            arrived that day; ``nan`` on a day without them.
        n_by_level: Patients of the window of each level of the target; with a
            percentage of the arrivals, one number, the arrivals.
        over_by_level: With a percentage, how many of them are above the
            threshold (or had the event); empty with a mean.
        bounded: Patients that enter a mean at a lower bound (still inside at
            the horizon): with any, the mean is a bound (``≥``).
    """

    value: float
    daily: tuple[float, ...]
    n_by_level: tuple[int, ...]
    over_by_level: tuple[int, ...]
    bounded: int = 0


@dataclass(frozen=True, slots=True)
class ReplicaValues:
    """One replication reduced to what the calibration needs.

    Attributes:
        targets: The values of each target, by its name.
        arrivals: Episodes that arrived in the window.
        censored: Of them, those still inside at the end of the horizon.
        compliance_days_out: Days of the window out of the Manchester
            compliance with clock C, per level 1 to 5.
        compliance_days: Days of the window with patients of each level 1 to 5.
        left: Of the arrivals, those who left without being seen.
        censored_seen: Of the censored, those already seen by a doctor: out of
            the clocks and of the compliance, inside the stays at their bound.
        admitted: Of the arrivals, those who asked for a bed.
        censored_admitted: Of them, those still waiting for it at the end.
        box_wait: Mean of ``initial_box_wait`` of the patients of levels 2 to 5
            who depart; ``nan`` without them.
        doctor_wait: Mean of ``initial_doctor_wait`` of the same patients.
    """

    targets: Mapping[str, TargetValues]
    arrivals: int
    censored: int
    compliance_days_out: tuple[int, ...]
    compliance_days: tuple[int, ...]
    left: int = 0
    censored_seen: int = 0
    admitted: int = 0
    censored_admitted: int = 0
    box_wait: float = math.nan
    doctor_wait: float = math.nan

    @property
    def censored_share(self) -> float:
        """Censored over the arrivals of the window; 0 without arrivals."""
        return self.censored / self.arrivals if self.arrivals else 0.0

    @property
    def censored_admitted_share(self) -> float:
        """Admitted still waiting for a bed over the admitted; 0 without them."""
        return self.censored_admitted / self.admitted if self.admitted else 0.0

    @property
    def compliance_out(self) -> tuple[float, ...]:
        """Share of the days with patients out of Manchester (clock C), per level 1
        to 5; ``nan`` for a level without patients."""
        return tuple(
            out / days if days else math.nan
            for out, days in zip(self.compliance_days_out, self.compliance_days, strict=True)
        )


@dataclass(frozen=True, slots=True)
class _Case:
    """One patient of a target: its day and level, and its value or whether it is above.

    ``value`` is the measure (a lower bound if ``bounded``) for a mean, and 1 or 0
    (above the threshold, or with the event) for a percentage.
    """

    day: int
    level: int | None
    value: float
    bounded: bool = False


def _day(e: EpisodeRecord, first_day: int) -> int:
    return math.floor(e.arrival / MINUTES_PER_DAY) - first_day


def _in_levels(target: Target, e: EpisodeRecord) -> bool:
    return e.level in target.levels


def _known(target: Target, e: EpisodeRecord) -> float:
    value = getattr(e, target.measure)
    if value is None:
        raise ValueError(f"{e.episode_id} departed without a {target.measure}")
    return value


def _arrival_cases(target: Target, arrived: Sequence[EpisodeRecord], first_day: int) -> list[_Case]:
    def happened(e: EpisodeRecord) -> bool:
        if target.measure == LEFT:
            return e.left is not None
        if target.measure == DEPARTURE:
            return e.departure is not None and target.destination in (None, e.destination)
        raise ValueError(f"objetivos.{target.name}: unknown event {target.measure!r}")

    return [_Case(_day(e, first_day), None, float(happened(e))) for e in arrived]


def _stay_cases(
    target: Target, arrived: Sequence[EpisodeRecord], first_day: int, horizon: float
) -> list[_Case]:
    """The stays of those who depart, and the bounds of those still inside who count."""
    out = []
    for e in arrived:
        if not _in_levels(target, e):
            continue
        if e.departure is not None:
            if target.destination in (None, e.destination):
                out.append(_Case(_day(e, first_day), e.level, e.stay))
        elif e.end is None:
            # Still inside at the horizon: an admitted patient waiting for a bed counts in
            # the stay of the admitted; with no destino, any patient already seen.
            waiting_bed = e.bed_requested is not None
            counts = (
                waiting_bed
                if target.destination == ADMISSION
                else target.destination is None and e.first_assessment is not None
            )
            if counts:
                out.append(_Case(_day(e, first_day), e.level, horizon - e.arrival, True))
    return out


def _cases(
    target: Target,
    table: Sequence[EpisodeRecord],
    first_day: int,
    end_day: int,
    horizon: float,
) -> list[_Case]:
    """The patients of ``target`` in the window, with the rules of the module docstring."""
    start, end = first_day * MINUTES_PER_DAY, end_day * MINUTES_PER_DAY
    arrived = [e for e in table if start <= e.arrival < end]
    if target.statistic == ARRIVALS_PERCENTAGE:
        return _arrival_cases(target, arrived, first_day)
    if target.measure == STAY:
        cases = _stay_cases(target, arrived, first_day, horizon)
        if not target.is_percentage:
            return cases
        # Above the threshold, a bound counts only once past it; at or below it, it may
        # still pass it and is left out (as over_threshold of engine.outcome_metrics).
        return [
            _Case(c.day, c.level, float(c.value > target.threshold_for(c.level)))
            for c in cases
            if not c.bounded or c.value > target.threshold_for(c.level)
        ]
    if target.measure == "triage_wait":
        episodes = [e for e in triaged_in_window(table, start, end) if _in_levels(target, e)]
    elif target.is_percentage and target.measure in CLOCKS:
        # The censoring of the Manchester compliance, with the threshold of each level as
        # its maximum: "exceeded" is above it, and the censored do not count.
        maxima = [target.threshold_for(level) for level in range(1, N_LEVELS + 1)]
        return [
            _Case(c.day, c.level, float(c.status == "exceeded"))
            for c in compliance_cases(table, first_day, end_day, maxima, measure=target.measure)
            if c.status != "censored" and c.level in target.levels
        ]
    else:
        episodes = [e for e in completed_in_window(table, start, end) if _in_levels(target, e)]
        if target.is_percentage and any(
            e.left is not None and _in_levels(target, e) for e in arrived
        ):
            raise ValueError(
                f"objetivos.{target.name}: the measure {target.measure!r} has no clock for"
                " the patients who leave without being seen, so its percentage is not defined"
            )
    if not target.is_percentage:
        return [_Case(_day(e, first_day), e.level, _known(target, e)) for e in episodes]
    return [
        _Case(_day(e, first_day), e.level, float(_known(target, e) > target.threshold_for(e.level)))
        for e in episodes
    ]


def _statistic(target: Target, cases: Sequence[_Case]) -> float:
    if not cases:
        return math.nan
    mean = float(np.mean([c.value for c in cases]))
    return 100 * mean if target.is_percentage else mean


def _target_values(
    target: Target,
    table: Sequence[EpisodeRecord],
    first_day: int,
    end_day: int,
    horizon: float,
) -> TargetValues:
    cases = _cases(target, table, first_day, end_day, horizon)
    by_day: list[list[_Case]] = [[] for _ in range(first_day, end_day)]
    for c in cases:
        by_day[c.day].append(c)
    if target.statistic == ARRIVALS_PERCENTAGE:
        n_by_level: tuple[int, ...] = (len(cases),)
        over_by_level: tuple[int, ...] = (int(sum(c.value for c in cases)),)
    else:
        n_by_level = tuple(sum(c.level == level for c in cases) for level in target.levels)
        over_by_level = (
            tuple(int(sum(c.value for c in cases if c.level == level)) for level in target.levels)
            if target.is_percentage
            else ()
        )
    return TargetValues(
        value=_statistic(target, cases),
        daily=tuple(_statistic(target, day) for day in by_day),
        n_by_level=n_by_level,
        over_by_level=over_by_level,
        bounded=sum(c.bounded for c in cases),
    )


def _mean_or_nan(values: Sequence[float]) -> float:
    return float(np.mean(values)) if values else math.nan


def replica_values(
    table: Sequence[EpisodeRecord],
    targets: Sequence[Target],
    first_day: int,
    end_day: int,
    *,
    horizon: float | None = None,
) -> ReplicaValues:
    """Reduce the episodes of one replication: a pure function.

    Only the episodes that arrive in days ``[first_day, end_day)`` count, as in
    ``completed_in_window``; the day of an episode is the day of its arrival.
    Who counts in each target, with the abandonment, is in the module docstring.

    Args:
        table: The episodes of the replication, from ``episode_table``; its
            horizon should go beyond ``end_day`` (``DRAIN_DAYS``).
        targets: The targets to evaluate.
        first_day: First day of the window, the warm-up.
        end_day: Day after the last of the window.
        horizon: End of the log, in minutes: the bound of who is still inside.
            ``None`` is the one of ``replica_table``, ``end_day + DRAIN_DAYS`` days.

    Raises:
        ValueError: If the days are not valid, a departed episode lacks the
            measure of a target, or a percentage of a measure without a clock
            for who leaves meets one who left.
    """
    if not 0 <= first_day < end_day:
        raise ValueError(f"need 0 <= first_day < end_day, got {first_day} and {end_day}")
    if horizon is None:
        horizon = float((end_day + DRAIN_DAYS) * MINUTES_PER_DAY)
    start, end = first_day * MINUTES_PER_DAY, end_day * MINUTES_PER_DAY
    arrived = [e for e in table if start <= e.arrival < end]
    inside = [e for e in arrived if e.end is None]
    attended = [e for e in completed_in_window(table, start, end) if e.level in BOTTLENECK_LEVELS]
    compliance = manchester_compliance(table, first_day, end_day)
    return ReplicaValues(
        targets=MappingProxyType(
            {t.name: _target_values(t, table, first_day, end_day, horizon) for t in targets}
        ),
        arrivals=len(arrived),
        censored=len(inside),
        compliance_days_out=tuple(int(x) for x in compliance.out.sum(axis=0)),
        compliance_days=tuple(int(x) for x in compliance.days_with_patients),
        left=sum(e.left is not None for e in arrived),
        censored_seen=sum(e.first_assessment is not None for e in inside),
        admitted=sum(e.bed_requested is not None for e in arrived),
        censored_admitted=sum(e.bed_requested is not None for e in inside),
        box_wait=_mean_or_nan([e.initial_box_wait for e in attended]),
        doctor_wait=_mean_or_nan([e.initial_doctor_wait for e in attended]),
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


def pooled_value(replicas: Sequence[ReplicaValues], target: Target) -> float:
    """The statistic of ``target`` over the patients of all the replications: a pure function.

    The weight of each replication is the number of patients its value is
    computed on: those of the window that departed, of the levels of the target
    (``n_by_level``). A mean is Σ value · (n / N); a percentage counts the
    patients above the threshold of all of them, 100 · (Σ over / N), as each
    replication does. With one replication it is its value, bit for bit. With
    the annual window it is the mean of the year, which weighs each month by
    its patients, while rule 4 uses the mean of the replications. ``nan``
    without patients.
    """
    values = [r.targets[target.name] for r in replicas]
    counts = [sum(v.n_by_level) for v in values]
    total = sum(counts)
    if not total:
        return math.nan
    if target.is_percentage:
        return 100 * (sum(sum(v.over_by_level) for v in values) / total)
    return sum(v.value * (n / total) for v, n in zip(values, counts, strict=True) if n)


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


def compliance_days(replicas: Sequence[ReplicaValues]) -> tuple[tuple[int, int], ...]:
    """Days out of Manchester (clock C) and days with patients, each summed over the
    replications, per level 1 to 5."""
    return tuple(
        (
            sum(r.compliance_days_out[k] for r in replicas),
            sum(r.compliance_days[k] for r in replicas),
        )
        for k in range(N_LEVELS)
    )


# --- Which targets apply ---------------------------------------------------------------------


def target_applies(target: Target, model: PatientModel) -> bool:
    """Whether ``target`` can be measured with ``model``: the abandonment and the
    destinations (``Target.needs_outcome``) only exist in the milestone 5 model."""
    return model is PatientModel.MILESTONE_5 or not target.needs_outcome


def split_targets(
    targets: Sequence[Target], center: CenterConfig, profiles: ClinicalProfiles
) -> tuple[tuple[Target, ...], tuple[Target, ...]]:
    """The targets that apply to the model of ``center`` and ``profiles``, and those that
    do not, each in their order (task 5.6). Those that do not apply are listed as such,
    never measured as a 0 %.

    Raises:
        ModelChoiceError: If the two files do not choose one model.
    """
    model = choose_model(center, profiles)
    return (
        tuple(t for t in targets if target_applies(t, model)),
        tuple(t for t in targets if not target_applies(t, model)),
    )


def _check_targets_apply(
    targets: Sequence[Target], center: CenterConfig, profiles: ClinicalProfiles
) -> None:
    _, out = split_targets(targets, center, profiles)
    if out:
        names = ", ".join(f"objetivos.{t.name}" for t in out)
        raise ValueError(
            f"{names}: only the milestone 5 model has abandonment and its destinations;"
            " leave them out with split_targets"
        )


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
    start_dates: Sequence[date] | None = None,
) -> tuple[ReplicaValues, ...]:
    """Simulate ``replicas`` replications and reduce each one at once.

    Replication ``i`` uses child ``i`` of ``seed`` (``child_streams``): the same
    patients for every center, the common random numbers that make the
    comparison of two staffings paired.

    Args:
        start_dates: The date on which each replication starts, such as the
            annual window (``calibration.window``): replication ``i`` uses
            ``arrival_profile`` with ``start_date = start_dates[i]`` and its
            factors bit for bit (``with_start_date``), and so the
            monthly factor, the weekdays and the clinical context of that date.
            ``None`` starts all of them on the profile's ``start_date``.

    Raises:
        ValueError: If ``replicas`` is below 2, the days are not valid, there is
            not one start date per replication or a target does not apply to the
            model (``split_targets``).
    """
    replicas = check_count("replicas", replicas, 2)
    days, warmup_days = check_horizon(days, warmup_days)
    _check_targets_apply(targets, center, profiles)
    if start_dates is None:
        profiles_by_replica = [arrival_profile] * replicas
    else:
        start_dates = tuple(start_dates)
        if len(start_dates) != replicas:
            raise ValueError(
                f"need one start date per replica: {replicas} replicas and {len(start_dates)} dates"
            )
        profiles_by_replica = [with_start_date(arrival_profile, d) for d in start_dates]
    out = []
    for child, profile in zip(child_streams(seed, replicas), profiles_by_replica, strict=True):
        run = clinical_run(center, profile, profiles, child, warmup_days)
        out.append(
            replica_values(replica_table(run, days, warmup_days), targets, warmup_days, days)
        )
    return tuple(out)


# --- Sensitivity and choice -------------------------------------------------------------------

KNOB_TARGETS: Mapping[str, tuple[tuple[str, ...], str]] = MappingProxyType(
    {
        NURSES: (("pretriaje_medio",), "pretriaje_medio"),
        DOCTORS: (("tiempo_medico_niveles_2_5",), "tiempo_medico_niveles_2_5"),
    }
)
"""The fit targets of each knob, and the one whose aim (its reference or, without
one, the centre of its band) chooses among the staffings that pass (ADR candidate
41, revised).

The doctors were to be fitted also to clock A of level 3 (59.0 minutes, band
45-75), but the sensitivity showed that no staffing of the rule takes it above
23 minutes: with a strict priority in one pool of doctors, level 3 hardly waits
and the waits fall on levels 4 and 5. ``tiempo_medico_nivel_3`` became a check
target after measuring it (rule 5), and a check never chooses (task 4.6b)."""

_CENTER_FIELD = {NURSES: "triage_nurses", DOCTORS: "doctors"}


def candidate_center(center: CenterConfig, knob: str, staff: Sequence[int]) -> CenterConfig:
    """``center`` with the staff of ``knob`` replaced; the other knob as it is."""
    if knob not in KNOBS:
        raise ValueError(f"knob must be one of {KNOBS}, got {knob!r}")
    return dataclasses.replace(center, **{_CENTER_FIELD[knob]: tuple(staff)})


def check_knob_targets(targets: Sequence[Target], knob: str) -> None:
    """Check that the targets have the fit targets of ``knob`` before simulating anything.

    Raises:
        ValueError: If a target is missing or is not of fit.
    """
    if knob not in KNOBS:
        raise ValueError(f"knob must be one of {KNOBS}, got {knob!r}")
    by_name = {t.name: t for t in targets}
    names, _ = KNOB_TARGETS[knob]
    for name in names:
        if name not in by_name:
            raise ValueError(f"the knob {knob} needs the target objetivos.{name}")
        if by_name[name].use != FIT:
            raise ValueError(f"objetivos.{name} must be of use {FIT!r} to fit {knob}")


@dataclass(frozen=True, slots=True)
class SensitivityRow:
    """One staffing of the rule, evaluated.

    Attributes:
        staffing: The staff and its interval of u.
        center: The center simulated, with that staff.
        results: One result per target.
        replicas: The reduced replications.
    """

    staffing: RuleStaffing
    center: CenterConfig
    results: tuple[TargetResult, ...]
    replicas: tuple[ReplicaValues, ...]

    def result(self, name: str) -> TargetResult:
        for r in self.results:
            if r.target.name == name:
                return r
        raise KeyError(name)

    @property
    def compliance_out(self) -> tuple[float, ...]:
        """Mean between replications of the share of days out of Manchester (C), by level."""
        return mean_compliance_out(self.replicas)

    @property
    def compliance_days(self) -> tuple[tuple[int, int], ...]:
        """Days out of Manchester (C) and days with patients, summed, by level."""
        return compliance_days(self.replicas)

    @property
    def max_censored_share(self) -> float:
        return max(r.censored_share for r in self.replicas)


def evaluate_staffings(
    center: CenterConfig,
    arrival_profile: ArrivalProfile,
    profiles: ClinicalProfiles,
    targets: Sequence[Target],
    knob: str,
    staffings: Sequence[RuleStaffing],
    *,
    replicas: int,
    days: int,
    warmup_days: int,
    seed: int | np.random.SeedSequence,
    start_dates: Sequence[date] | None = None,
    on_row: Callable[[SensitivityRow], None] | None = None,
) -> tuple[SensitivityRow, ...]:
    """Evaluate the given staffings of ``knob``, in their order, the other knob fixed.

    Each one is simulated with the same replications (the same seed and the
    same ``start_dates``, as in ``simulate_replicas``), so the rows differ only
    in the staff. ``sensitivity`` gives it every staffing of
    the rule; a subset, such as the staffings around the chosen one, costs
    less.

    Args:
        staffings: The staffings to evaluate, such as some of ``rule_staffings``.
        on_row: Called with each row as soon as it is evaluated, such as a
            progress line of the CLI.

    Raises:
        ValueError: If ``knob`` is unknown.
    """
    if knob not in KNOBS:
        raise ValueError(f"knob must be one of {KNOBS}, got {knob!r}")
    rows = []
    for staffing in staffings:
        candidate = candidate_center(center, knob, staffing.staff)
        reduced = simulate_replicas(
            candidate,
            arrival_profile,
            profiles,
            targets,
            replicas=replicas,
            days=days,
            warmup_days=warmup_days,
            seed=seed,
            start_dates=start_dates,
        )
        row = SensitivityRow(staffing, candidate, summarize_targets(reduced, targets), reduced)
        rows.append(row)
        if on_row is not None:
            on_row(row)
    return tuple(rows)


def sensitivity(
    center: CenterConfig,
    arrival_profile: ArrivalProfile,
    profiles: ClinicalProfiles,
    targets: Sequence[Target],
    knob: str,
    *,
    replicas: int,
    days: int,
    warmup_days: int,
    seed: int | np.random.SeedSequence,
    u_min: float = U_MIN,
    u_max: float = U_MAX,
    step: float = U_STEP,
    start_dates: Sequence[date] | None = None,
    on_row: Callable[[SensitivityRow], None] | None = None,
) -> tuple[SensitivityRow, ...]:
    """Evaluate every staffing of the rule for ``knob``, the other knob fixed.

    The staffings come from ``rule_staffings`` with the loads of the knob and
    the shifts of ``center``, and ``evaluate_staffings`` simulates each one
    with the same replications (the same seed and ``start_dates``), so the
    rows differ only in the staff. The loads are those of the mean day of the
    profile, which do not depend on its ``start_date``.

    Args:
        on_row: Called with each row as soon as it is evaluated, such as a
            progress line of the CLI.
    """
    loads = knob_loads(knob, profiles, arrival_profile, center.shift_starts)
    return evaluate_staffings(
        center,
        arrival_profile,
        profiles,
        targets,
        knob,
        rule_staffings(loads, u_min, u_max, step),
        replicas=replicas,
        days=days,
        warmup_days=warmup_days,
        seed=seed,
        start_dates=start_dates,
        on_row=on_row,
    )


def passes_fit(row: SensitivityRow, knob: str) -> bool:
    """Whether ``row`` passes every fit target of ``knob`` (rule 4)."""
    if knob not in KNOBS:
        raise ValueError(f"knob must be one of {KNOBS}, got {knob!r}")
    names, _ = KNOB_TARGETS[knob]
    return all(row.result(name).passed for name in names)


def choice_order(rows: Sequence[SensitivityRow], knob: str) -> tuple[SensitivityRow, ...]:
    """The rows that pass every fit target of ``knob``, in the order of the choice:
    the mean of the choosing target closest to its aim (``Target.aim``: the
    reference, or the centre of the band without one) first; on a tie, the smaller
    staff first.
    """
    if knob not in KNOBS:
        raise ValueError(f"knob must be one of {KNOBS}, got {knob!r}")
    _, chooser = KNOB_TARGETS[knob]

    def distance(row: SensitivityRow) -> tuple[float, int]:
        r = row.result(chooser)
        return abs(r.mean - r.target.aim), sum(row.staffing.staff)

    return tuple(sorted((row for row in rows if passes_fit(row, knob)), key=distance))


def choose_staffing(
    rows: Sequence[SensitivityRow],
    knob: str,
    *,
    check: Callable[[SensitivityRow], SensitivityRow] | None = None,
) -> SensitivityRow | None:
    """Among the rows that pass every fit target of ``knob``, the one whose mean
    of the choosing target is closest to its aim (``choice_order``). ``None`` if
    none passes: the choice is never forced.

    With ``check``, the check seed may veto (decision 41, revised in task 4.6c):
    the candidates are taken in the order of the choice, and the first whose
    check also passes every fit target is chosen. The check never chooses: a row
    that fails with the fit seed is not a candidate, whatever its check.

    Args:
        rows: The staffings evaluated with the fit seed.
        check: The same staffing as the given row evaluated with the check seed,
            such as ``evaluate_staffings`` with ``CHECK_SEED``. It is called only
            until a candidate passes, in the order of the choice.

    Raises:
        ValueError: If ``knob`` is unknown, or ``check`` returns another staff.
    """
    for row in choice_order(rows, knob):
        if check is None:
            return row
        checked = check(row)
        if checked.staffing.staff != row.staffing.staff:
            raise ValueError(f"the check of {row.staffing.staff} is of {checked.staffing.staff}")
        if passes_fit(checked, knob):
            return row
    return None


def complies(
    days: Sequence[tuple[int, int]],
    levels: Sequence[int] = COMPLIANCE_LEVELS,
    max_share_out: Fraction = COMPLIANCE_SHARE_OUT,
) -> bool:
    """Whether each level has days with patients and at most ``max_share_out`` of
    them out: ``out ≤ max_share_out · days``, with whole days and an exact fraction.

    Args:
        days: Days out and days with patients of each level 1 to 5, such as
            ``compliance_days`` of some replications.
    """
    share = Fraction(max_share_out)
    return all(
        days[level - 1][1] > 0 and days[level - 1][0] <= share * days[level - 1][1]
        for level in levels
    )


def compliant_staffing(
    rows: Sequence[SensitivityRow],
    *,
    levels: Sequence[int] = COMPLIANCE_LEVELS,
    max_share_out: Fraction = COMPLIANCE_SHARE_OUT,
) -> SensitivityRow | None:
    """The row of highest u (the smallest staff) whose levels all have at most
    ``max_share_out`` of days out of Manchester with clock C: the days out summed
    over the replications against the days with patients summed over them
    (``complies``). ``None`` if none.
    """
    passing = [row for row in rows if complies(row.compliance_days, levels, max_share_out)]
    return max(passing, key=lambda row: row.staffing.u_high, default=None)
