"""Real numbers that do not fit in a float (task 6.4, review of PR #59).

Python's integers have no limit: ``json.loads`` reads ``1`` followed by 400 zeros as
an ``int``, and ``float``, ``math.isfinite`` and ``math.isnan`` raise ``OverflowError``
with it instead of answering. Every check of "a finite real number" in the package
converts with ``to_float`` first, so that such a number is refused with the same
``ValueError`` and message as infinity.

Standard library only: the clock, the orders and the pacer use it without loading the
engine.
"""


def to_float(value: object) -> float | None:
    """``float(value)``, or ``None`` if it does not fit in a float (such as ``10**400``).

    The caller has already checked that ``value`` is a real number; a finite float is
    then the same as before, and the caller decides about NaN and infinity.
    """
    try:
        return float(value)
    except OverflowError:
        return None
