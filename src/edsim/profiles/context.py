"""Context of an arrival: shift band, day type and season.

The clinical mix depends on when the patient arrives. Each arrival time ``t``
(minutes since 00:00 of the arrival profile's ``start_date``) is turned into
three features, with the same calendar as lambda(t) in ``arrivals.rate``: a
clock at +01:00 with no daylight saving time and no holidays.

- Shift band: morning, afternoon or night, from the profile's own starting
  hours (``contexto.franjas``, 8, 15 and 22 by default). The night runs past
  midnight. They are not the shifts of ``centro.toml``: moving a change of
  shift does not move the patients.
- Day type: weekday, or weekend (Saturday and Sunday). A holiday is a weekday.
- Season: by months, December to February is winter, March to May spring,
  June to August summer and September to November autumn.

The day and the calendar come from ``rate.split_days`` and
``rate.day_calendar``, so that this module and lambda(t) cannot disagree on
which day a time falls.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
from numpy.typing import ArrayLike, NDArray

from edsim.arrivals.profile import ArrivalProfile
from edsim.arrivals.rate import MINUTES_PER_DAY, cumulative_rate, day_calendar, split_days
from edsim.checks import check_count
from edsim.profiles.config import N_DAY_TYPES, N_SEASONS, N_SHIFT_BANDS

SHIFT_BANDS = ("manana", "tarde", "noche")
"""Names of the shift bands, in the order of their factors."""

DAY_TYPES = ("laborable", "fin_de_semana")
"""Names of the day types, in the order of their factors."""

SEASONS = ("invierno", "primavera", "verano", "otono")
"""Names of the seasons, in the order of their factors."""

DAYS_PER_YEAR = 365
"""Days of the year over which the global mix is weighted."""


@dataclass(frozen=True, slots=True, order=True)
class ArrivalContext:
    """The context of one arrival, as indices into the factors of the profiles.

    Attributes:
        shift_band: 0 morning, 1 afternoon, 2 night.
        day_type: 0 weekday, 1 weekend.
        season: 0 winter, 1 spring, 2 summer, 3 autumn.
    """

    shift_band: int
    day_type: int
    season: int

    def __post_init__(self) -> None:
        for name, n in (
            ("shift_band", N_SHIFT_BANDS),
            ("day_type", N_DAY_TYPES),
            ("season", N_SEASONS),
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int | np.integer)
                or not 0 <= value < n
            ):
                raise ValueError(f"{name} must be an integer in 0-{n - 1}, got {value!r}")
            object.__setattr__(self, name, int(value))

    @property
    def label(self) -> str:
        """Readable name, such as ``"manana/laborable/invierno"``."""
        return f"{SHIFT_BANDS[self.shift_band]}/{DAY_TYPES[self.day_type]}/{SEASONS[self.season]}"


def all_contexts() -> tuple[ArrivalContext, ...]:
    """The 24 contexts, in the order shift band, day type, season."""
    return tuple(
        ArrivalContext(s, d, e)
        for s in range(N_SHIFT_BANDS)
        for d in range(N_DAY_TYPES)
        for e in range(N_SEASONS)
    )


def _check_times(t: ArrayLike) -> NDArray[np.float64]:
    times = np.asarray(t, dtype=float)
    if not np.all(np.isfinite(times)) or np.any(times < 0):
        raise ValueError(
            f"t must be finite and not negative (minutes since fecha_inicio), got {t!r}"
        )
    return times


def _day_type(weekdays: NDArray[np.int64]) -> NDArray[np.int64]:
    """1 for Saturday (5) and Sunday (6), 0 for the other days."""
    return (weekdays >= 5).astype(np.int64)


def _season(months: NDArray[np.int64]) -> NDArray[np.int64]:
    """Season of each month: January (0) and February (1) → 0, March → 1, ..., December → 0."""
    return (months + 1) % 12 // 3


def context_indices(
    t: ArrayLike, start_date: date, shift_band_starts: Sequence[int]
) -> tuple[NDArray[np.int64], NDArray[np.int64], NDArray[np.int64]]:
    """Shift band, day type and season of each time, as index arrays.

    Args:
        t: Minutes since 00:00 of ``start_date``; a scalar or an array.
        start_date: Date of minute 0, the ``start_date`` of the arrival profile.
        shift_band_starts: Starting hours of the morning, afternoon and night
            (``ClinicalProfiles.shift_band_starts``).

    Returns:
        Three integer arrays with the shape of ``t``: shift band (0-2), day
        type (0-1) and season (0-3).

    Raises:
        ValueError: If any time is negative or not finite.
    """
    days, minutes = split_days(_check_times(t))
    morning, afternoon, night = (60 * h for h in shift_band_starts)
    shift = np.where(
        (minutes >= morning) & (minutes < afternoon),
        0,
        np.where((minutes >= afternoon) & (minutes < night), 1, 2),
    )
    weekdays, months = day_calendar(days, start_date)
    return shift.astype(np.int64), _day_type(weekdays), _season(months)


def arrival_context(t: float, start_date: date, shift_band_starts: Sequence[int]) -> ArrivalContext:
    """The context of one arrival at time ``t``; see ``context_indices``."""
    shift, day_type, season = context_indices(t, start_date, shift_band_starts)
    return ArrivalContext(int(shift), int(day_type), int(season))


def context_weights(
    profile: ArrivalProfile, shift_band_starts: Sequence[int], days: int = DAYS_PER_YEAR
) -> NDArray[np.float64]:
    """Expected arrivals in each context over the first ``days`` days of the profile.

    The days are cut at midnight and at the start of each shift band, and the
    expected arrivals of each piece, ``Lambda(end) - Lambda(start)``, are added
    to the context of its start. ``Lambda`` is exact, so the weights are too;
    they do not include the daily random effect Z, which has mean 1.

    Args:
        profile: The arrival profile, with its ``start_date``.
        shift_band_starts: Starting hours of the shift bands.
        days: Number of days from ``start_date``; a year by default, so that
            every season and day type weighs what it weighs in a year.

    Returns:
        Array of shape (3, 2, 4): shift band, day type, season. Its sum is
        ``cumulative_rate(days * 1440)``.

    Raises:
        ValueError: If ``days`` is not a positive integer.
    """
    days = check_count("days", days, 1)
    cuts = np.unique(np.array([0, *(60 * h for h in shift_band_starts)], dtype=float))
    edges = (np.arange(days)[:, None] * MINUTES_PER_DAY + cuts[None, :]).ravel()
    edges = np.append(edges, float(days * MINUTES_PER_DAY))
    expected = np.diff(cumulative_rate(edges, profile))
    weights = np.zeros((N_SHIFT_BANDS, N_DAY_TYPES, N_SEASONS))
    np.add.at(weights, context_indices(edges[:-1], profile.start_date, shift_band_starts), expected)
    return weights


def context_time(
    start_date: date, shift_band_starts: Sequence[int], context: ArrivalContext
) -> float:
    """A time in the first year with the given context, for validations.

    It is 30 minutes after the start of the shift band, on the first day with
    the day type and the season of the context.

    Raises:
        ValueError: If no day of the first year has the context; it cannot
            happen with a valid profile, because every season has weekdays
            and weekends.
    """
    days = np.arange(DAYS_PER_YEAR + 1)
    weekdays, months = day_calendar(days, start_date)
    matches = days[(_day_type(weekdays) == context.day_type) & (_season(months) == context.season)]
    if matches.size == 0:
        raise ValueError(f"no day of the first year is {context.label}")
    return float(matches[0] * MINUTES_PER_DAY + 60 * shift_band_starts[context.shift_band] + 30)
