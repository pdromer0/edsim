"""The arrival rate lambda(t) and its cumulative intensity Lambda(t).

Time ``t`` is in minutes since 00:00 of the profile's ``start_date``. The rate
is in arrivals per minute::

    lambda(t) = day_scale(day) * shape(minute of the day)
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
a per-day random effect (the daily Z of a later task) enter as one more factor
of ``day_scale``, without changing the rest.

Both functions are vectorized: they take a scalar or an array of any shape,
because the validation computes Lambda at hundreds of thousands of arrivals.
"""

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


def _shape_knots(profile: ArrivalProfile) -> tuple[NDArray, NDArray, NDArray]:
    """Knots of the hourly shape within one day and the cumulative area at each.

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
    return x, y, np.concatenate([[0.0], np.cumsum(trapezoids)])


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


def rate(t: ArrayLike, profile: ArrivalProfile) -> float | NDArray[np.float64]:
    """Arrival rate lambda(t), in arrivals per minute.

    Args:
        t: Minutes since 00:00 of ``profile.start_date``; a scalar or an array.
        profile: The arrival profile.

    Returns:
        The rate at each time: a float for a scalar ``t``, otherwise an array
        with the shape of ``t``.

    Raises:
        ValueError: If any time is negative or not finite.
    """
    times = _check_times(t)
    days, minutes = _split(times)
    # np.interp with period=24 joins 23:30 with 0:30 across midnight.
    shape = np.interp(minutes / 60, _HOUR_CENTRES, profile.hour_factors, period=24)
    return _as_output(_day_scale(days, profile) * shape)


def cumulative_rate(t: ArrayLike, profile: ArrivalProfile) -> float | NDArray[np.float64]:
    """Cumulative intensity Lambda(t): expected number of arrivals in ``[0, t]``.

    The arrivals between ``a`` and ``b`` follow a Poisson distribution with
    mean ``Lambda(b) - Lambda(a)``. The value is exact: it adds the areas of
    the full days before ``t`` and the trapezoids of the current day.

    Args:
        t: Minutes since 00:00 of ``profile.start_date``; a scalar or an array.
        profile: The arrival profile.

    Returns:
        Lambda at each time: a float for a scalar ``t``, otherwise an array
        with the shape of ``t``.

    Raises:
        ValueError: If any time is negative or not finite.
    """
    times = _check_times(t)
    if times.size == 0:
        return times
    days, minutes = _split(times)

    # Scale of every day up to the last one asked for, and the area of the
    # full days before each day (cumulative sum shifted by one day).
    scales = _day_scale(np.arange(days.max() + 1), profile)
    day_area = _shape_knots(profile)[2][-1]  # 1440 up to rounding
    before = np.concatenate([[0.0], np.cumsum(scales * day_area)])

    return _as_output(before[days] + scales[days] * _shape_area(minutes, profile))
