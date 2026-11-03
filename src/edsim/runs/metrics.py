"""Window KPIs and Manchester counts for completed episodes."""

from collections.abc import Sequence
from dataclasses import dataclass

from edsim.arrivals.rate import MINUTES_PER_DAY
from edsim.engine.analysis import EpisodeRecord, WindowMetrics, completed_in_window
from edsim.engine.targets import Compliance, manchester_compliance


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
    """

    level: int
    n: int
    max_wait: float
    exceeded: int
    exceeded_share: float | None
    share_out: float | None


@dataclass(frozen=True, slots=True)
class WindowCompliance:
    """Original daily compliance and pooled counts of completed patients."""

    daily: Compliance
    by_level: tuple[LevelCompliance, ...]


def window_compliance(
    table: Sequence[EpisodeRecord], first_day: int, end_day: int
) -> WindowCompliance:
    """Use Manchester's daily targets in [first_day, end_day), pooling patients."""
    daily = manchester_compliance(table, first_day, end_day)
    done = completed_in_window(table, first_day * MINUTES_PER_DAY, end_day * MINUTES_PER_DAY)
    shares = daily.share_out
    levels = []
    for index, maximum in enumerate(daily.max_wait):
        patients = [e for e in done if e.level == index + 1]
        n = len(patients)
        exceeded = sum(e.door_to_doctor > maximum for e in patients)
        levels.append(
            LevelCompliance(
                index + 1,
                n,
                maximum,
                exceeded,
                exceeded / n if n else None,
                float(shares[index]) if n else None,
            )
        )
    return WindowCompliance(daily, tuple(levels))
