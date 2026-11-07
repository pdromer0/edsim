"""Pure episode filters, exclusive cohorts and right-censored lower bounds."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from edsim.engine.analysis import EpisodeRecord
from edsim.engine.events import ARRIVAL_MODES, SEXES
from edsim.profiles.config import N_BANDS, REASON_KEYS, TEST_TYPES
from edsim.runs.episodes import ObservedProfile

EpisodePeriod = Literal["warmup", "window", "unfinished"]


@dataclass(frozen=True, slots=True)
class EpisodeFilters:
    """Optional AND filters; thresholds are strict, non-negative minutes.

    The last five (task 4.8a) use the observable profile of a clinical run:
    the age band (0 to 3, the bands of its profiles), ``sex`` and
    ``arrival_mode`` with the words of the log, a ``reason`` key and a ``test``
    type that the episode had ordered.
    """

    level: int | None = None
    destination: Literal["alta", "ingreso"] | None = None
    displaced: bool | None = None
    arrival_day: int | None = None
    period: EpisodePeriod | None = None
    door_to_doctor_gt: float | None = None
    stay_gt: float | None = None
    age_band: int | None = None
    sex: Literal["mujer", "hombre"] | None = None
    arrival_mode: Literal["ambulancia", "propios_medios"] | None = None
    reason: str | None = None
    test: str | None = None

    @property
    def uses_profile(self) -> bool:
        """Whether some filter needs the observable profile."""
        return any(
            value is not None
            for value in (self.age_band, self.sex, self.arrival_mode, self.reason, self.test)
        )

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
        if self.age_band is not None and (
            type(self.age_band) is not int or not 0 <= self.age_band < N_BANDS
        ):
            raise ValueError(f"age_band must be 0 to {N_BANDS - 1} or None")
        for name, choices in (
            ("sex", SEXES),
            ("arrival_mode", ARRIVAL_MODES),
            ("reason", REASON_KEYS),
            ("test", TEST_TYPES),
        ):
            if getattr(self, name) not in (None, *choices):
                raise ValueError(f"unknown {name}")


def episode_period(episode: EpisodeRecord, warmup_end: float) -> EpisodePeriod:
    """Classify unfinished episodes first, then arrivals relative to warm-up."""
    if episode.departure is None:
        return "unfinished"
    return "warmup" if episode.arrival < warmup_end else "window"


def episode_observed_time(episode: EpisodeRecord, horizon: float) -> float:
    """Observed stay in minutes; a lower bound when departure is unknown."""
    return (horizon if episode.departure is None else episode.departure) - episode.arrival


def filter_episodes(
    table: Sequence[EpisodeRecord],
    filters: EpisodeFilters,
    *,
    warmup_end: float,
    horizon: float,
    observed: Mapping[str, ObservedProfile] | None = None,
) -> tuple[EpisodeRecord, ...]:
    """Keep arrival order and use lower bounds for unknown stay/door-to-doctor.

    Exactly on a threshold does not pass. A known door-to-doctor value is final
    even when the patient has not departed. Arrival days start at zero.

    The profile filters need ``observed``, the observable profiles of the run
    (``RunResults.observed``); an episode whose value is not in the log yet
    (such as the reason before its triage) does not pass them.
    """
    if not math.isfinite(horizon) or not 0 <= warmup_end < horizon:
        raise ValueError("need 0 <= warmup_end < finite horizon")
    if filters.uses_profile and observed is None:
        raise ValueError("profile filters need the observed profiles of a clinical run")

    def profile_passes(episode: EpisodeRecord) -> bool:
        profile = observed[episode.episode_id]
        for name in ("age_band", "sex", "arrival_mode", "reason"):
            wanted = getattr(filters, name)
            if wanted is not None and getattr(profile, name) != wanted:
                return False
        return filters.test is None or filters.test in profile.tests

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
        if filters.uses_profile and not profile_passes(episode):
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
