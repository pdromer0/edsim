"""Window KPIs, Manchester counts, the three clocks and the pretriage of completed episodes."""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from edsim.arrivals.rate import MINUTES_PER_DAY
from edsim.engine.analysis import EpisodeRecord, WindowMetrics, completed_in_window
from edsim.engine.targets import (
    CLOCKS,
    MANCHESTER_MAX_WAIT,
    Compliance,
    ComplianceCase,
    LevelClocks,
    Pretriage,
    clock_quantiles,
    compliance_cases,
    compliance_from_cases,
    pretriage,
)


@dataclass(frozen=True, slots=True)
class WindowKPIs:
    """Time-based arrivals/day and census, and completed-episode statistics.

    Waits and stays are in minutes; admission_share is a fraction. Without
    completed episodes, counts are zero and statistics are None. Time-based
    values remain defined, including patients still inside at the horizon.
    """

    n: int
    arrivals_per_day: float
    census_mean: float
    stay_mean: float | None
    stay_p90: float | None
    door_to_doctor_mean: float | None
    door_to_doctor_p90: float | None
    displaced_episodes: int
    total_displacements: int
    admission_share: float | None


def window_kpis(table: Sequence[EpisodeRecord], metrics: WindowMetrics) -> WindowKPIs:
    """Summarize a table and its matching window metrics, without rounding."""
    done = completed_in_window(table, metrics.start, metrics.end)
    return WindowKPIs(
        n=len(done),
        arrivals_per_day=metrics.arrivals * MINUTES_PER_DAY / (metrics.end - metrics.start),
        census_mean=metrics.time_averages["census"],
        stay_mean=metrics.overall.mean["stay"],
        stay_p90=metrics.overall.p90["stay"],
        door_to_doctor_mean=metrics.overall.mean["door_to_doctor"],
        door_to_doctor_p90=metrics.overall.p90["door_to_doctor"],
        displaced_episodes=sum(e.displacements > 0 for e in done),
        total_displacements=sum(e.displacements for e in done),
        admission_share=sum(e.destination == "ingreso" for e in done) / len(done) if done else None,
    )


@dataclass(frozen=True, slots=True)
class LevelCompliance:
    """Integer exceedances of a level's maximum (minutes), and patient/day shares.

    Exactly at the maximum complies. Both shares are None without patients;
    share_out counts only days with completed patients of this level.

    With the abandonment (task 5.4, H5-8), ``n`` and ``exceeded`` include
    whoever left without being seen once its clock reached the maximum (a sure
    miss), and ``censored`` counts whoever left before it, out of ``n``.
    """

    level: int
    n: int
    max_wait: float
    exceeded: int
    exceeded_share: float | None
    share_out: float | None
    censored: int = 0


@dataclass(frozen=True, slots=True)
class WindowCompliance:
    """Original daily compliance and pooled counts of completed patients."""

    daily: Compliance
    by_level: tuple[LevelCompliance, ...]


APP_COMPLIANCE_MEASURE = "classified_to_doctor"
"""Default clock of ``window_compliance``: C, from the classification (decision 40).

Clock A until task 4.9, so that the app did not change before it passed C itself
(task 4.8b); the name stays because it is public. ``RunResults.compliance`` uses it.
"""


def window_compliance(
    table: Sequence[EpisodeRecord],
    first_day: int,
    end_day: int,
    *,
    measure: str = APP_COMPLIANCE_MEASURE,
) -> WindowCompliance:
    """Use Manchester's daily targets in [first_day, end_day), pooling patients.

    ``measure`` is the clock, a name of ``CLOCKS``. Its default is
    ``APP_COMPLIANCE_MEASURE``, clock C since task 4.9, as in
    ``manchester_compliance``; ``door_to_doctor`` gives clock A, as before.
    """
    cases = compliance_cases(table, first_day, end_day, MANCHESTER_MAX_WAIT, measure=measure)
    daily = compliance_from_cases(cases, first_day, end_day, measure=measure)
    return WindowCompliance(daily, _pooled_levels(daily, cases))


def _pooled_levels(
    daily: Compliance, cases: Sequence[ComplianceCase]
) -> tuple[LevelCompliance, ...]:
    """Pool the patients of each level against its maximum, with the censoring.

    ``cases`` are those of ``compliance_cases`` for the same stretch and clock
    as ``daily``, with the level that groups them: the assigned one or, with
    its ``level_of``, such as the true level.
    """
    shares = daily.share_out
    levels = []
    for index, maximum in enumerate(daily.max_wait):
        patients = [c for c in cases if c.level == index + 1]
        counted = [c for c in patients if c.status != "censored"]
        n = len(counted)
        exceeded = sum(c.status == "exceeded" for c in counted)
        levels.append(
            LevelCompliance(
                index + 1,
                n,
                maximum,
                exceeded,
                exceeded / n if n else None,
                float(shares[index]) if n else None,
                len(patients) - n,
            )
        )
    return tuple(levels)


# --- The three clocks, the level 1 and the pretriage (task 4.8a) -------------------------


@dataclass(frozen=True, slots=True)
class ClockStatistics:
    """Mean, median and 90th percentile of one clock, in minutes; None without patients."""

    measure: str
    mean: float | None
    median: float | None
    p90: float | None


@dataclass(frozen=True, slots=True)
class LevelClockSummary:
    """The clocks A, B and C of one level, in the order of ``CLOCKS``."""

    level: int
    n: int
    clocks: tuple[ClockStatistics, ...]


def window_clocks(
    table: Sequence[EpisodeRecord], first_day: int, end_day: int
) -> tuple[LevelClockSummary, ...]:
    """The three clocks to the doctor of levels 1 to 5, in days ``[first_day, end_day)``.

    Median and p90 are those of ``clock_quantiles`` (linear interpolation); the
    mean is over the same patients, those who arrived in the stretch and
    departed. For the level 1, whose maximum is 0, show only the median and the
    p90 (``level_one_clocks``): a share of compliance would always be 0 %.
    """
    quantiles = clock_quantiles(table, first_day, end_day)
    done = completed_in_window(table, first_day * MINUTES_PER_DAY, end_day * MINUTES_PER_DAY)
    out = []
    for q in quantiles:
        episodes = [e for e in done if e.level == q.level]
        clocks = []
        for name in CLOCKS:
            values = [getattr(e, name) for e in episodes]
            mean = float(np.mean(values)) if values else None
            clocks.append(ClockStatistics(name, mean, q.median[name], q.p90[name]))
        out.append(LevelClockSummary(q.level, q.n, tuple(clocks)))
    return tuple(out)


def level_one_clocks(table: Sequence[EpisodeRecord], first_day: int, end_day: int) -> LevelClocks:
    """The level 1 with its time alone: median and p90 of the three clocks, no share."""
    return clock_quantiles(table, first_day, end_day)[0]


@dataclass(frozen=True, slots=True)
class PretriageGroup:
    """The pretriage of a group of levels over the stretch.

    ``group`` is a level, 2 to 5, or None for the four together. Shares are
    fractions of the patients of the stretch (None without patients):
    ``within_share`` started the triage within the maximum (10 minutes,
    exactly at it complies) and ``over_share`` waited more than 5 minutes (the
    TECLA of the SAS). ``days_out`` counts the days below the 85 % target among
    the ``days_with_patients``.
    """

    group: int | None
    n: int
    within_share: float | None
    over_share: float | None
    days_out: int
    days_with_patients: int


@dataclass(frozen=True, slots=True)
class WindowPretriage:
    """Daily pretriage of ``engine.targets.pretriage`` and its pooled groups."""

    daily: Pretriage
    by_group: tuple[PretriageGroup, ...]


def window_pretriage(
    table: Sequence[EpisodeRecord], first_day: int, end_day: int
) -> WindowPretriage:
    """The pretriage indicator in days ``[first_day, end_day)``, without the level 1.

    The level 1 is classified at the door and does not count. Groups are those
    of ``PRETRIAGE_GROUPS``: levels 2, 3, 4 and 5, and the four together.
    """
    daily = pretriage(table, first_day, end_day)
    groups = []
    for g, group in enumerate(daily.groups):
        n = int(daily.pooled_n[g])
        groups.append(
            PretriageGroup(
                group,
                n,
                float(daily.pooled_within[g]) if n else None,
                float(daily.pooled_over[g]) if n else None,
                int(daily.out[:, g].sum()),
                int(daily.days_with_patients[g]),
            )
        )
    return WindowPretriage(daily, tuple(groups))
