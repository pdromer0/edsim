"""Pure episode filters, exclusive cohorts and right-censored lower bounds."""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from edsim.engine.analysis import EpisodeRecord

EpisodePeriod = Literal["warmup", "window", "unfinished"]


@dataclass(frozen=True, slots=True)
class EpisodeFilters:
    """Optional AND filters; thresholds are strict, non-negative minutes."""

    level: int | None = None
    destination: Literal["alta", "ingreso"] | None = None
    displaced: bool | None = None
    arrival_day: int | None = None
    period: EpisodePeriod | None = None
    door_to_doctor_gt: float | None = None
    stay_gt: float | None = None

    def __post_init__(self) -> None:
        if self.level is not None and (type(self.level) is not int or not 1 <= self.level <= 5):
            raise ValueError("level must be 1 to 5 or None")
        if self.destination not in (None, "alta", "ingreso"):
            raise ValueError("unknown destination")
        if self.displaced is not None and type(self.displaced) is not bool:
            raise ValueError("displaced must be a bool or None")
        if self.arrival_day is not None and (
            type(self.arrival_day) is not int or self.arrival_day < 0
        ):
            raise ValueError("arrival_day must be a non-negative integer or None")
        if self.period not in (None, "warmup", "window", "unfinished"):
            raise ValueError("unknown period")
        for name in ("door_to_doctor_gt", "stay_gt"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not math.isfinite(value) or value < 0
            ):
                raise ValueError(f"{name} must be finite and non-negative or None")


def episode_period(episode: EpisodeRecord, warmup_end: float) -> EpisodePeriod:
    """Classify unfinished episodes first, then arrivals relative to warm-up."""
    if episode.departure is None:
        return "unfinished"
    return "warmup" if episode.arrival < warmup_end else "window"


def episode_observed_time(episode: EpisodeRecord, horizon: float) -> float:
    """Observed stay in minutes; a lower bound when departure is unknown."""
    return (horizon if episode.departure is None else episode.departure) - episode.arrival


def filter_episodes(
    table: Sequence[EpisodeRecord], filters: EpisodeFilters, *, warmup_end: float, horizon: float
) -> tuple[EpisodeRecord, ...]:
    """Keep arrival order and use lower bounds for unknown stay/door-to-doctor.

    Exactly on a threshold does not pass. A known door-to-doctor value is final
    even when the patient has not departed. Arrival days start at zero.
    """
    if not math.isfinite(horizon) or not 0 <= warmup_end < horizon:
        raise ValueError("need 0 <= warmup_end < finite horizon")

    def passes(episode: EpisodeRecord) -> bool:
        if filters.level is not None and episode.level != filters.level:
            return False
        if filters.destination is not None and episode.destination != filters.destination:
            return False
        if filters.displaced is not None and (episode.displacements > 0) != filters.displaced:
            return False
        if (
            filters.arrival_day is not None
            and math.floor(episode.arrival / 1440) != filters.arrival_day
        ):
            return False
        if filters.period is not None and episode_period(episode, warmup_end) != filters.period:
            return False
        if (
            filters.stay_gt is not None
            and episode_observed_time(episode, horizon) <= filters.stay_gt
        ):
            return False
        door = episode.door_to_doctor
        if door is None:
            door = horizon - episode.arrival
        return filters.door_to_doctor_gt is None or door > filters.door_to_doctor_gt

    return tuple(episode for episode in table if passes(episode))
