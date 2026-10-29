"""Center configuration: staff, boxes and the provisional clinical model, from TOML.

The file has one table per topic (``turnos``, ``recursos``, ``triaje``,
``duraciones``, ``pruebas`` and ``destino``); see ``config/centro.toml`` and
docs/specs/hito-3.md. Keys are in Spanish (ADR 0015) and errors name them with
their table, such as ``recursos.medicos[2]``, because that is what the user
wrote.

Durations are given as the median and the 90th percentile of a lognormal, in
minutes: two numbers a clinician can estimate. ``edsim.engine.clinical`` turns
them into the parameters of the distribution.
"""

import math
import tomllib
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

N_SHIFTS = 3
"""Shifts per day: morning, afternoon and night."""

N_LEVELS = 5
"""Triage levels, 1 (most urgent) to 5."""

# "table.key" in TOML → field name, in the order of the file.
_KEYS = {
    "turnos.inicio": "shift_starts",
    "recursos.enfermeria_triaje": "triage_nurses",
    "recursos.medicos": "doctors",
    "recursos.boxes": "boxes",
    "triaje.reparto_niveles": "level_shares",
    "duraciones.triaje": "triage_time",
    "duraciones.valoracion": "assessment_time",
    "duraciones.reevaluacion": "reassessment_time",
    "duraciones.respuesta_pruebas": "test_turnaround",
    "pruebas.probabilidad": "test_probability",
    "destino.probabilidad_ingreso": "admission_probability",
}
_DURATION_FIELDS = ("triage_time", "assessment_time", "reassessment_time", "test_turnaround")
_PROBABILITY_FIELDS = ("test_probability", "admission_probability")
_TOML_KEY = {field: key for key, field in _KEYS.items()}


def _check_number(key: str, value: object) -> float:
    """Return ``value`` as a float if it is a finite real number."""
    # bool is a subclass of int in Python: `true` must not pass as 1.
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{key} must be a number, got {value!r}")
    if not math.isfinite(value):
        raise ValueError(f"{key} must be a finite number, got {value!r}")
    return float(value)


def _check_integer(key: str, value: object) -> int:
    """Return ``value`` if it is an integer; ``3.0`` and ``true`` are not."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer, got {value!r}")
    return value


def _check_list(key: str, values: object, n: int) -> list:
    """Check that ``values`` is a list (or tuple) of ``n`` values."""
    if not isinstance(values, list | tuple):
        raise ValueError(f"{key} must be a list of {n} values, got {values!r}")
    if len(values) != n:
        raise ValueError(f"{key} must have {n} values, got {len(values)}")
    return list(values)


def _check_staff(key: str, value: object) -> int:
    """A capacity: an integer of at least 1."""
    n = _check_integer(key, value)
    if n < 1:
        raise ValueError(f"{key} must be at least 1, got {value!r}")
    return n


def _check_shift_staff(key: str, values: object) -> tuple[int, ...]:
    """One capacity per shift."""
    staff = _check_list(key, values, N_SHIFTS)
    return tuple(_check_staff(f"{key}[{i}]", n) for i, n in enumerate(staff))


def _check_shift_starts(key: str, values: object) -> tuple[int, ...]:
    hours = [
        _check_integer(f"{key}[{i}]", h) for i, h in enumerate(_check_list(key, values, N_SHIFTS))
    ]
    for i, h in enumerate(hours):
        if not 0 <= h <= 23:
            raise ValueError(f"{key}[{i}] must be between 0 and 23, got {h!r}")
    if any(a >= b for a, b in pairwise(hours)):
        raise ValueError(f"{key} must be strictly increasing, got {hours!r}")
    return tuple(hours)


def _check_shares(key: str, values: object) -> tuple[float, ...]:
    """Non-negative weights with a positive sum, normalized to sum 1.

    Shares that already sum to 1 (up to 1e-12) are kept as they are. Dividing
    them again by a sum such as 0.9999999999999999 would change their last
    bit, and ``dataclasses.replace`` would not give back the same center.
    """
    shares = [
        _check_number(f"{key}[{i}]", x) for i, x in enumerate(_check_list(key, values, N_LEVELS))
    ]
    for i, x in enumerate(shares):
        if x < 0:
            raise ValueError(f"{key}[{i}] must not be negative, got {values[i]!r}")
    total = sum(shares)
    if total <= 0:
        raise ValueError(f"{key} must have a positive sum, got {list(values)!r}")
    if math.isclose(total, 1, rel_tol=0, abs_tol=1e-12):
        return tuple(shares)
    return tuple(x / total for x in shares)


def _check_duration(key: str, values: object) -> tuple[float, float]:
    """``[median, p90]`` of a lognormal: median > 0 and p90 > median."""
    median, p90 = (
        _check_number(f"{key}[{i}]", x) for i, x in enumerate(_check_list(key, values, 2))
    )
    if median <= 0:
        raise ValueError(f"{key}[0] (median) must be positive, got {values[0]!r}")
    if p90 <= median:
        raise ValueError(f"{key}: p90 must be greater than the median, got {list(values)!r}")
    return (median, p90)


def _check_probabilities(key: str, values: object) -> tuple[float, ...]:
    probabilities = [
        _check_number(f"{key}[{i}]", x) for i, x in enumerate(_check_list(key, values, N_LEVELS))
    ]
    for i, p in enumerate(probabilities):
        if not 0 <= p <= 1:
            raise ValueError(f"{key}[{i}] must be between 0 and 1, got {values[i]!r}")
    return tuple(probabilities)


@dataclass(frozen=True, slots=True)
class CenterConfig:
    """Validated and normalized configuration of the center.

    Validation and normalization happen on construction, as in
    ``ArrivalProfile``: a center can only exist valid, whether it comes from
    ``load_center`` or is built directly (also with ``dataclasses.replace``).
    Lists are stored as tuples, so the configuration cannot change after
    validation.

    Values per shift are in the order morning, afternoon, night; values per
    level, from level 1 to level 5.

    Attributes:
        shift_starts: Starting hour of each shift (``turnos.inicio``); three
            integers in 0-23, strictly increasing. The last shift runs past
            midnight into the first one.
        triage_nurses: Triage nurses on each shift (``recursos.enfermeria_triaje``).
        doctors: Doctors on each shift (``recursos.medicos``).
        boxes: Number of boxes, the same in every shift (``recursos.boxes``).
        level_shares: Share of patients in each triage level, summing to 1
            (``triaje.reparto_niveles``, which accepts any non-negative
            weights, such as percentages). A level may have share 0.
        triage_time: ``(median, p90)`` of the triage time, in minutes
            (``duraciones.triaje``).
        assessment_time: ``(median, p90)`` of the first assessment
            (``duraciones.valoracion``).
        reassessment_time: ``(median, p90)`` of the reassessment after the
            tests (``duraciones.reevaluacion``).
        test_turnaround: ``(median, p90)`` from ordering the tests to their
            results (``duraciones.respuesta_pruebas``).
        test_probability: Probability of ordering tests, per level
            (``pruebas.probabilidad``).
        admission_probability: Probability of admission, per level
            (``destino.probabilidad_ingreso``); the rest are discharged.
    """

    shift_starts: tuple[int, ...]
    triage_nurses: tuple[int, ...]
    doctors: tuple[int, ...]
    boxes: int
    level_shares: tuple[float, ...]
    triage_time: tuple[float, float]
    assessment_time: tuple[float, float]
    reassessment_time: tuple[float, float]
    test_turnaround: tuple[float, float]
    test_probability: tuple[float, ...]
    admission_probability: tuple[float, ...]

    def __post_init__(self) -> None:
        def check(field: str, function) -> None:
            # The dataclass is frozen: object.__setattr__ is the standard way to
            # set fields during construction.
            object.__setattr__(self, field, function(_TOML_KEY[field], getattr(self, field)))

        check("shift_starts", _check_shift_starts)
        for field in ("triage_nurses", "doctors"):
            check(field, _check_shift_staff)
        check("boxes", _check_staff)
        check("level_shares", _check_shares)
        for field in _DURATION_FIELDS:
            check(field, _check_duration)
        for field in _PROBABILITY_FIELDS:
            check(field, _check_probabilities)


def load_center(path: str | Path) -> CenterConfig:
    """Load the center configuration from a TOML file.

    The file must have exactly the tables and keys of ``config/centro.toml``.
    Unknown tables or keys are an error, so that a misspelt key does not go
    unnoticed.

    Args:
        path: Path of the TOML file, such as ``config/centro.toml``.

    Returns:
        The validated and normalized configuration.

    Raises:
        ValueError: If tables or keys are missing or unknown, or a value is not
            valid.
        FileNotFoundError: If the file does not exist.
        tomllib.TOMLDecodeError: If the file is not valid TOML.
    """
    path = Path(path)
    with path.open("rb") as f:
        data = tomllib.load(f)

    sections = {key.split(".")[0] for key in _KEYS}
    for section in sorted(sections & data.keys()):
        if not isinstance(data[section], dict):
            raise ValueError(f"{path}: {section} must be a table, got {data[section]!r}")

    # Flatten to "table.key"; a missing or unknown table is reported by its name.
    found = {s for s in data if s not in sections}
    found |= {f"{s}.{k}" for s in sections & data.keys() for k in data[s]}
    expected = {key for key in _KEYS if key.split(".")[0] in data}
    expected |= sections - data.keys()

    missing = sorted(expected - found)
    unknown = sorted(found - expected)
    if missing or unknown:
        problems = []
        if missing:
            problems.append(f"missing keys: {', '.join(missing)}")
        if unknown:
            problems.append(f"unknown keys: {', '.join(unknown)}")
        raise ValueError(f"{path}: {'; '.join(problems)}")

    values = {}
    for key, field in _KEYS.items():
        section, name = key.split(".")
        values[field] = data[section][name]
    return CenterConfig(**values)
