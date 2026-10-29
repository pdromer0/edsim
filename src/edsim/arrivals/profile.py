"""Arrival profiles: the parameters of the arrival rate, loaded from TOML.

The rate of arrivals is a daily base multiplied by one factor per time scale::

    lambda(t) = daily_base / 1440 * h(hour) * d(weekday) * m(month)

The TOML file states the factors in terms a clinician knows: the share of a
day's arrivals in each hour, the share of a week's arrivals in each weekday,
and a relative daily rate per month. This module turns them into factors with
mean 1, so that ``daily_base`` keeps its meaning (mean arrivals per day over a
year) even if the written values do not add up exactly.

The months are weighted by their number of days (a 365-day year): a factor of
1.10 in a 31-day month weighs more in the annual mean than 1.05 in February.
"""

import math
import tomllib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

DAYS_PER_MONTH = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
"""Days of each month, January to December, in a 365-day year."""

# TOML key → field name. Keys are in Spanish (ADR 0015); errors name the key,
# because the key is what the user wrote.
_KEYS = {
    "base_diaria": "daily_base",
    "reparto_horario": "hour_factors",
    "reparto_semanal": "weekday_factors",
    "factor_mensual": "month_factors",
    "cv_diario": "daily_cv",
    "fecha_inicio": "start_date",
}


def _check_number(key: str, value: object) -> float:
    """Return ``value`` as a float if it is a finite real number."""
    # bool is a subclass of int in Python: `true` must not pass as 1.
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{key} must be a number, got {value!r}")
    if not math.isfinite(value):
        raise ValueError(f"{key} must be a finite number, got {value!r}")
    return float(value)


def _check_values(key: str, values: object, n: int) -> tuple[float, ...]:
    """Check that ``values`` has ``n`` finite, strictly positive numbers."""
    if not isinstance(values, list | tuple):
        raise ValueError(f"{key} must be a list of {n} values, got {values!r}")
    if len(values) != n:
        raise ValueError(f"{key} must have {n} values, got {len(values)}")
    checked = []
    for i, value in enumerate(values):
        x = _check_number(f"{key}[{i}]", value)
        if x <= 0:
            raise ValueError(f"{key}[{i}] must be positive, got {value!r}")
        checked.append(x)
    return tuple(checked)


@dataclass(frozen=True, slots=True)
class ArrivalProfile:
    """Validated and normalized parameters of the arrival rate.

    Validation and normalization happen on construction, so a profile can only
    exist valid and normalized, whether it comes from ``load_profile`` or is
    built directly. Normalizing an already normalized profile leaves it as it
    is, which makes ``dataclasses.replace`` safe.

    The factors are stored as tuples: a NumPy array inside a frozen dataclass
    could still be modified in place, and arrays do not compare with ``==``.

    Attributes:
        daily_base: Mean arrivals per day over a year (``base_diaria``).
        hour_factors: 24 factors ``h``, from 0 h to 23 h, with mean 1. Each one
            is the rate at the centre of its hour (h:30), relative to the
            day's mean. Built from ``reparto_horario`` as ``24 * x / sum(x)``.
        weekday_factors: 7 factors ``d``, Monday to Sunday, with mean 1. Built
            from ``reparto_semanal`` as ``7 * x / sum(x)``.
        month_factors: 12 factors ``m``, January to December, whose mean
            weighted by ``DAYS_PER_MONTH`` is 1 (``factor_mensual``).
        daily_cv: Coefficient of variation of the daily random effect
            (``cv_diario``); 0 turns it off.
        start_date: Date of minute 0, at 00:00 (``fecha_inicio``).
    """

    daily_base: float
    hour_factors: tuple[float, ...]
    weekday_factors: tuple[float, ...]
    month_factors: tuple[float, ...]
    daily_cv: float
    start_date: date

    def __post_init__(self) -> None:
        base = _check_number("base_diaria", self.daily_base)
        if base <= 0:
            raise ValueError(f"base_diaria must be positive, got {self.daily_base!r}")

        hours = _check_values("reparto_horario", self.hour_factors, 24)
        weekdays = _check_values("reparto_semanal", self.weekday_factors, 7)
        months = _check_values("factor_mensual", self.month_factors, 12)

        cv = _check_number("cv_diario", self.daily_cv)
        if cv < 0:
            raise ValueError(f"cv_diario must not be negative, got {self.daily_cv!r}")

        # datetime is a subclass of date: a TOML date-time must not pass as a date.
        if not isinstance(self.start_date, date) or isinstance(self.start_date, datetime):
            raise ValueError(
                f"fecha_inicio must be a date without time, such as 2026-01-05, "
                f"got {self.start_date!r}"
            )

        hours_sum = sum(hours)
        weekdays_sum = sum(weekdays)
        months_mean = sum(m * n for m, n in zip(months, DAYS_PER_MONTH, strict=True)) / 365

        # The dataclass is frozen: object.__setattr__ is the standard way to
        # set fields during construction.
        object.__setattr__(self, "daily_base", base)
        object.__setattr__(self, "hour_factors", tuple(24 * x / hours_sum for x in hours))
        object.__setattr__(self, "weekday_factors", tuple(7 * x / weekdays_sum for x in weekdays))
        object.__setattr__(self, "month_factors", tuple(m / months_mean for m in months))
        object.__setattr__(self, "daily_cv", cv)


def load_profile(path: str | Path) -> ArrivalProfile:
    """Load an arrival profile from a TOML file.

    The file must have exactly the keys ``base_diaria``, ``reparto_horario``,
    ``reparto_semanal``, ``factor_mensual``, ``cv_diario`` and
    ``fecha_inicio``. Unknown keys are an error, so that a misspelt key does
    not go unnoticed.

    Args:
        path: Path of the TOML file, such as ``config/llegadas.toml``.

    Returns:
        The validated and normalized profile.

    Raises:
        ValueError: If keys are missing or unknown, or a value is not valid.
        FileNotFoundError: If the file does not exist.
        tomllib.TOMLDecodeError: If the file is not valid TOML.
    """
    path = Path(path)
    with path.open("rb") as f:
        data = tomllib.load(f)

    missing = sorted(_KEYS.keys() - data.keys())
    unknown = sorted(data.keys() - _KEYS.keys())
    if missing or unknown:
        problems = []
        if missing:
            problems.append(f"missing keys: {', '.join(missing)}")
        if unknown:
            problems.append(f"unknown keys: {', '.join(unknown)}")
        raise ValueError(f"{path}: {'; '.join(problems)}")

    return ArrivalProfile(**{field: data[key] for key, field in _KEYS.items()})
