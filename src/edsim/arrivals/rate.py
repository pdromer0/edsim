"""The arrival rate lambda(t) and its cumulative intensity Lambda(t).

Time ``t`` is in minutes since 00:00 of the profile's ``start_date``. The rate
is in arrivals per minute::

    lambda(t) = Z(day) * day_scale(day) * shape(minute of the day)
    day_scale = daily_base / 1440 * d(weekday) * m(month)

``shape`` is the hourly profile made continuous: each hour factor is the value
at the centre of its hour (h:30), and consecutive centres are joined by
straight lines, periodically (23:30 links with 0:30 across midnight). The
weekday and the month change at midnight, so lambda may jump there and only
there. Every day lasts 1440 minutes: the clock has no daylight saving time.

Because the shape is piecewise linear, its area is a sum of trapezoids, so
Lambda(t), the expected number of arrivals in ``[0, t]``, is exact with no
numerical integration::

    Lambda(t) = sum of 1440 * day_scale over the full days before t
                + day_scale(current day) * area of the shape up to the minute

Splitting lambda into a per-day scale and a shape within the day is what lets
the daily random effect Z enter as one more factor of the day: both functions
take an optional ``day_effects``, the Z of each day from day 0, such as the
``day_effect`` of the ``DayRecord`` of a run. Without it, every Z is 1.

Both functions are vectorized: they take a scalar or an array of any shape,
because the validation computes Lambda at hundreds of thousands of arrivals.
"""

from functools import lru_cache

import numpy as np
from numpy.typing import ArrayLike, NDArray

from edsim.arrivals.profile import ArrivalProfile

MINUTES_PER_DAY = 1440

_HOUR_CENTRES = np.arange(24) + 0.5  # in hours: 0.5, 1.5, ..., 23.5


def _check_times(t: ArrayLike) -> NDArray[np.float64]:
    """Return ``t`` as a float array, or raise if any time is negative or not finite."""
    times = np.asarray(t, dtype=float)
    if not np.all(np.isfinite(times)):
        raise ValueError(f"t must be finite (minutes since fecha_inicio), got {t!r}")
    if np.any(times < 0):
        raise ValueError(
            f"t must not be negative (minutes since fecha_inicio), got minimum {times.min()}"
        )
    return times


def _check_day_effects(day_effects: ArrayLike, needed: int) -> NDArray[np.float64]:
    """Return the daily effects as a float array, or raise if they are not valid.

    ``needed`` is the number of days the caller uses, from day 0.
    """
    effects = np.asarray(day_effects, dtype=float)
    if effects.ndim != 1:
        raise ValueError(
            f"day_effects must be a 1-D sequence with the Z of each day, "
            f"got {effects.ndim} dimensions"
        )
    if not np.all(np.isfinite(effects)) or np.any(effects <= 0):
        raise ValueError(f"day_effects must be finite and positive, got {day_effects!r}")
    if effects.size < needed:
        raise ValueError(
            f"day_effects must cover day {needed - 1}: needs at least {needed} values, "
            f"got {effects.size}"
        )
    return effects


def _split(times: NDArray[np.float64]) -> tuple[NDArray[np.int64], NDArray[np.float64]]:
    """Split times into the day index and the minute within the day, in [0, 1440)."""
    days = np.floor(times / MINUTES_PER_DAY).astype(np.int64)
    return days, times - days * MINUTES_PER_DAY


def _day_scale(days: NDArray[np.int64], profile: ArrivalProfile) -> NDArray[np.float64]:
    """Rate scale ``daily_base / 1440 * d * m`` of each day index.

    The weekday and the month come from the calendar date of each day, so
    month lengths and the change of year are handled by NumPy's dates.
    """
    dates = np.datetime64(profile.start_date, "D") + days.astype("timedelta64[D]")
    weekdays = (days + profile.start_date.weekday()) % 7
    # Months since 1970-01; modulo 12 gives 0 for January.
    months = dates.astype("datetime64[M]").astype(np.int64) % 12
    return (
        profile.daily_base
        / MINUTES_PER_DAY
        * np.asarray(profile.weekday_factors)[weekdays]
        * np.asarray(profile.month_factors)[months]
    )


def day_scale(day: ArrayLike, profile: ArrivalProfile) -> float | NDArray[np.float64]:
    """Rate scale of a day: ``daily_base / 1440 * d(weekday) * m(month)``.

    It is the factor that multiplies the hourly shape on that day, so
    ``rate(t) = day_scale(day of t) * shape(minute of t)``. The thinning
    generator uses it for the bound of each day, ``day_scale * max(h)``.

    Args:
        day: Day index, 0 for ``profile.start_date``; an integer or an array
            of integers.
        profile: The arrival profile.

    Returns:
        The scale in arrivals per minute: a float for a scalar ``day``,
        otherwise an array with the shape of ``day``.

    Raises:
        ValueError: If any day is not an integer or is negative.
    """
    days = np.asarray(day)
    # NumPy's bool is not an integer type, so True does not pass as day 1.
    if not np.issubdtype(days.dtype, np.integer):
        raise ValueError(f"day must be an integer day index, got {day!r}")
    if np.any(days < 0):
        raise ValueError(f"day must not be negative, got minimum {days.min()}")
    return _as_output(_day_scale(days.astype(np.int64), profile))


def _shape(minutes: ArrayLike, profile: ArrivalProfile) -> NDArray[np.float64]:
    """Hourly shape at each minute of the day, as an array."""
    # The knots at 0 and 1440 carry the midnight value, so a plain np.interp
    # joins 23:30 with 0:30 across midnight. It is the same interpolation as
    # in _shape_area, and much cheaper per call than np.interp(period=...),
    # which sorts the knots every time.
    x, y, _ = _shape_knots(profile)
    return np.interp(minutes, x, y)


def shape(minutes: ArrayLike, profile: ArrivalProfile) -> float | NDArray[np.float64]:
    """Hourly shape of the rate: the hour factors joined by straight lines.

    It is the factor that varies within a day, so that
    ``rate(t) = day_scale(day of t) * shape(minute of t)``, with exactly the
    same arithmetic as ``rate``. The thinning generator computes the scale
    once per day and the shape at every candidate, which is much cheaper than
    calling ``rate`` with a scalar.

    No check is made on ``minutes``, to keep the per-candidate cost low:
    outside ``[0, 1440]`` the value is clamped to the midnight value.

    Args:
        minutes: Minutes since 00:00 of the day, in ``[0, 1440)``; a scalar or
            an array.
        profile: The arrival profile.

    Returns:
        The shape, with mean 1 over a day: a float for a scalar ``minutes``,
        otherwise an array with the shape of ``minutes``.
    """
    return _as_output(_shape(minutes, profile))


@lru_cache(maxsize=8)
def _shape_knots(profile: ArrivalProfile) -> tuple[NDArray, NDArray, NDArray]:
    """Knots of the hourly shape within one day and the cumulative area at each.

    Cached per profile, which is frozen and hashable: the thinning generator
    needs the knots at every candidate. The cache keeps the last few
    profiles, enough for a validation that compares several of them. The
    arrays are read-only, because every caller shares them.

    The knots are 0, 30, 90, ..., 1410 and 1440 minutes. At 0 and 1440 the
    shape is halfway between the 23 h and 0 h factors, by periodicity. The
    area of the full day is 1440, because the factors have mean 1.

    Returns:
        Knot positions in minutes (26), shape values at the knots, and the
        exact area of the shape from 0 to each knot.
    """
    h = np.asarray(profile.hour_factors)
    midnight = (h[-1] + h[0]) / 2
    x = np.concatenate([[0.0], 60 * _HOUR_CENTRES, [MINUTES_PER_DAY]])
    y = np.concatenate([[midnight], h, [midnight]])
    trapezoids = np.diff(x) * (y[:-1] + y[1:]) / 2
    area = np.concatenate([[0.0], np.cumsum(trapezoids)])
    for array in (x, y, area):
        array.flags.writeable = False
    return x, y, area


def day_shape_area(profile: ArrivalProfile) -> float:
    """Area of the hourly shape over a full day: 1440, up to rounding.

    The expected arrivals of a day are ``Z * day_scale(day) * day_shape_area``,
    the same product that ``cumulative_rate`` adds up day by day. The thinning
    generator uses it to fill ``DayRecord.expected`` without computing Lambda.

    Args:
        profile: The arrival profile.

    Returns:
        The exact area of the shape from 0:00 to 24:00, in minutes.
    """
    return float(_shape_knots(profile)[2][-1])


def _shape_area(minutes: NDArray[np.float64], profile: ArrivalProfile) -> NDArray[np.float64]:
    """Exact area of the hourly shape from 0:00 to each minute of the day."""
    x, y, area = _shape_knots(profile)
    # Index of the knot at or before each minute: area up to it plus a partial trapezoid.
    k = np.clip(np.searchsorted(x, minutes, side="right") - 1, 0, len(x) - 2)
    y_at = np.interp(minutes, x, y)
    return area[k] + (minutes - x[k]) * (y[k] + y_at) / 2


def _as_output(values: NDArray[np.float64]) -> float | NDArray[np.float64]:
    """A plain float for a scalar input, the array otherwise."""
    return float(values) if values.ndim == 0 else values


def rate(
    t: ArrayLike, profile: ArrivalProfile, *, day_effects: ArrayLike | None = None
) -> float | NDArray[np.float64]:
    """Arrival rate lambda(t), in arrivals per minute.

    Args:
        t: Minutes since 00:00 of ``profile.start_date``; a scalar or an array.
        profile: The arrival profile.
        day_effects: Daily random effect Z of each day, from day 0. It must
            cover the day of every time. Without it, every Z is 1.

    Returns:
        The rate at each time: a float for a scalar ``t``, otherwise an array
        with the shape of ``t``.

    Raises:
        ValueError: If any time is negative or not finite, or ``day_effects``
            is not a 1-D sequence of finite positive numbers covering the
            days of ``t``.
    """
    times = _check_times(t)
    days, minutes = _split(times)
    scale = _day_scale(days, profile)
    if day_effects is not None:
        needed = int(days.max()) + 1 if days.size else 0
        # (scale * Z) * shape: the same order of products as the thinning.
        scale = scale * _check_day_effects(day_effects, needed)[days]
    return _as_output(scale * _shape(minutes, profile))


def cumulative_rate(
    t: ArrayLike, profile: ArrivalProfile, *, day_effects: ArrayLike | None = None
) -> float | NDArray[np.float64]:
    """Cumulative intensity Lambda(t): expected number of arrivals in ``[0, t]``.

    The arrivals between ``a`` and ``b`` follow a Poisson distribution with
    mean ``Lambda(b) - Lambda(a)``. The value is exact: it adds the areas of
    the full days before ``t`` and the trapezoids of the current day.

    Args:
        t: Minutes since 00:00 of ``profile.start_date``; a scalar or an array.
        profile: The arrival profile.
        day_effects: Daily random effect Z of each day, from day 0. It must
            cover every day that ``[0, t]`` goes through: ``Lambda(n * 1440)``,
            at the end of ``n`` days, needs only their ``n`` values. Without
            it, every Z is 1.

    Returns:
        Lambda at each time: a float for a scalar ``t``, otherwise an array
        with the shape of ``t``.

    Raises:
        ValueError: If any time is negative or not finite, or ``day_effects``
            is not a 1-D sequence of finite positive numbers covering the
            days of ``t``.
    """
    times = _check_times(t)
    effects = None
    if day_effects is not None:
        needed = int(np.ceil(times.max() / MINUTES_PER_DAY)) if times.size else 0
        effects = _check_day_effects(day_effects, needed)
    if times.size == 0:
        return times
    days, minutes = _split(times)

    # Scale of every day up to the last one asked for, and the area of the
    # full days before each day (cumulative sum shifted by one day).
    n_days = int(days.max()) + 1
    scales = _day_scale(np.arange(n_days), profile)
    if effects is not None:
        # A time at the midnight that ends the effects falls on the next day
        # with minute 0: its Z multiplies an area of 0, so 1 is as good as any.
        z = np.ones(n_days)
        covered = min(n_days, effects.size)
        z[:covered] = effects[:covered]
        scales = scales * z
    day_area = day_shape_area(profile)
    before = np.concatenate([[0.0], np.cumsum(scales * day_area)])

    return _as_output(before[days] + scales[days] * _shape_area(minutes, profile))
