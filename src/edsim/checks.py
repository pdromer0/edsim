"""Helpers shared by the validations of several milestones.

Two kinds of helper live here because more than one subpackage needs them:

- checks of inputs: ``check_number``, ``check_integer`` and ``check_list``
  for the values of the TOML files (``arrivals.profile``, ``engine.center``
  and ``profiles.config``) and ``check_count`` for the sizes of a validation;
- ``ValidationResult`` and the functions that build one from a confidence
  interval, a list of intervals or a tolerance, so that ``edsim llegadas
  validar`` and ``edsim motor validar`` print their tables alike.

``ValidationResult`` was defined in ``arrivals.validation``; it moved here so
that this module does not import from it (``arrivals.validation`` imports
this one). ``arrivals.validation`` still exposes it under the same name.
"""

import math
from dataclasses import dataclass

from edsim.finite import to_float
from edsim.stats import Summary


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Outcome of one validation test.

    Named ``ValidationResult`` and not ``TestResult``: pytest tries to collect
    every class called ``Test*`` that a test module imports.

    Attributes:
        name: Key of the test, such as ``"volume"``, or of a part of it, such
            as ``"monday"``.
        statistic: The test statistic: a mean ratio, a chi-square value, a
            Kolmogorov–Smirnov distance or a dispersion index.
        p_value: P-value, for the tests decided by one (``None`` otherwise).
        ci_low: Lower bound of the confidence interval, for the tests decided
            by one (``None`` otherwise).
        ci_high: Upper bound of the confidence interval.
        target: Value that must fall inside the interval (``None`` for the
            tests decided by a p-value).
        criterion: The pass condition, such as ``"p >= 0.01"`` or
            ``"1 in 99.875% CI"``.
        passed: Whether the test passes; with ``details``, whether all of
            them pass.
        details: Parts of the test, when it has several intervals.
        confidence: Level of the confidence interval, such as ``0.99875``,
            for the tests decided by one (``None`` otherwise).
    """

    name: str
    statistic: float
    p_value: float | None
    ci_low: float | None
    ci_high: float | None
    target: float | None
    criterion: str
    passed: bool
    details: tuple["ValidationResult", ...] = ()
    confidence: float | None = None


def check_number(key: str, value: object) -> float:
    """Return ``value`` as a float if it is a finite real number."""
    # bool is a subclass of int in Python: `true` must not pass as 1.
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{key} must be a number, got {value!r}")
    # to_float turns an int too large for a float, such as 10**400, into None:
    # math.isfinite would raise OverflowError instead of answering.
    if (number := to_float(value)) is None or not math.isfinite(number):
        raise ValueError(f"{key} must be a finite number, got {value!r}")
    return number


def check_integer(key: str, value: object) -> int:
    """Return ``value`` if it is an integer; ``3.0`` and ``true`` are not."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer, got {value!r}")
    return value


def check_list(key: str, values: object, n: int) -> list:
    """Check that ``values`` is a list (or tuple) of ``n`` values."""
    if not isinstance(values, list | tuple):
        raise ValueError(f"{key} must be a list of {n} values, got {values!r}")
    if len(values) != n:
        raise ValueError(f"{key} must have {n} values, got {len(values)}")
    return list(values)


def check_count(name: str, value: object, minimum: int) -> int:
    """Return ``value`` if it is an integer of at least ``minimum``, such as a size."""
    # bool is a subclass of int in Python: True must not pass as 1.
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}, got {value!r}")
    return value


def interval_result(name: str, summary: Summary, target: float) -> ValidationResult:
    """A check that passes if ``target`` falls inside the confidence interval of ``summary``."""
    return ValidationResult(
        name=name,
        statistic=summary.mean,
        p_value=None,
        ci_low=summary.ci_low,
        ci_high=summary.ci_high,
        target=target,
        criterion=f"{target:g} in {100 * summary.confidence:g}% CI",
        passed=summary.ci_low <= target <= summary.ci_high,
        confidence=summary.confidence,
    )


def all_of(name: str, details: tuple[ValidationResult, ...]) -> ValidationResult:
    """A check made of several intervals: it passes if all of them do.

    The statistic is the number of intervals that miss their target.
    """
    misses = sum(not d.passed for d in details)
    return ValidationResult(
        name=name,
        statistic=float(misses),
        p_value=None,
        ci_low=None,
        ci_high=None,
        target=None,
        criterion=f"all {len(details)} targets in their {100 * details[0].confidence:g}% CI",
        passed=misses == 0,
        details=details,
        confidence=details[0].confidence,
    )


def tolerance_result(name: str, error: float, tolerance: float) -> ValidationResult:
    """A check that passes if a relative ``error`` is at most ``tolerance``."""
    return ValidationResult(
        name=name,
        statistic=float(error),
        p_value=None,
        ci_low=None,
        ci_high=None,
        target=None,
        criterion=f"relative error <= {tolerance:g}",
        passed=bool(error <= tolerance),
    )
