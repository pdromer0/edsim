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

from __future__ import annotations

import json
import math
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from edsim.checks import check_integer, check_list, check_number

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
_SECTIONS = {key.split(".")[0] for key in _KEYS}


def _check_staff(key: str, value: object) -> int:
    """A capacity: an integer of at least 1."""
    n = check_integer(key, value)
    if n < 1:
        raise ValueError(f"{key} must be at least 1, got {value!r}")
    return n


def _check_shift_staff(key: str, values: object) -> tuple[int, ...]:
    """One capacity per shift."""
    staff = check_list(key, values, N_SHIFTS)
    return tuple(_check_staff(f"{key}[{i}]", n) for i, n in enumerate(staff))


def _check_shift_starts(key: str, values: object) -> tuple[int, ...]:
    hours = [
        check_integer(f"{key}[{i}]", h) for i, h in enumerate(check_list(key, values, N_SHIFTS))
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
        check_number(f"{key}[{i}]", x) for i, x in enumerate(check_list(key, values, N_LEVELS))
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
    median, p90 = (check_number(f"{key}[{i}]", x) for i, x in enumerate(check_list(key, values, 2)))
    if median <= 0:
        raise ValueError(f"{key}[0] (median) must be positive, got {values[0]!r}")
    if p90 <= median:
        raise ValueError(f"{key}: p90 must be greater than the median, got {list(values)!r}")
    return (median, p90)


def _check_probabilities(key: str, values: object) -> tuple[float, ...]:
    probabilities = [
        check_number(f"{key}[{i}]", x) for i, x in enumerate(check_list(key, values, N_LEVELS))
    ]
    for i, p in enumerate(probabilities):
        if not 0 <= p <= 1:
            raise ValueError(f"{key}[{i}] must be between 0 and 1, got {values[i]!r}")
    return tuple(probabilities)


_VALIDATORS = dict(
    zip(
        _KEYS,
        (
            _check_shift_starts,
            _check_shift_staff,
            _check_shift_staff,
            _check_staff,
            _check_shares,
            _check_duration,
            _check_duration,
            _check_duration,
            _check_duration,
            _check_probabilities,
            _check_probabilities,
        ),
        strict=True,
    )
)


def _read_center_data(path: str | Path) -> dict:
    with Path(path).open("rb") as file:
        return tomllib.load(file)


def _flatten_center_data(data: Mapping[str, object]) -> dict[str, object]:
    """Keep unknown sections and malformed tables available for diagnostics."""
    values = {}
    for section, contents in data.items():
        if section in _SECTIONS and isinstance(contents, dict):
            values.update((f"{section}.{name}", value) for name, value in contents.items())
        else:
            # A literal root key "recursos.medicos" is not medicos in [recursos].
            key = json.dumps(section, ensure_ascii=False) if "." in section else section
            values[key] = contents
    return values


def read_center_values(path: str | Path) -> dict[str, object]:
    """Read raw TOML values without normalization or semantic validation.

    Known tables are flattened to full keys, such as ``recursos.medicos``.
    Unknown sections and malformed tables retain their section name so that
    ``validate_center_values`` can report them. Literal dotted root keys are
    quoted to distinguish them from flattened table keys. Syntax and read
    errors propagate.
    """
    return _flatten_center_data(_read_center_data(path))


def _structure_errors(values: Mapping[str, object]) -> tuple[list[str], list[str], list[str]]:
    malformed = sorted(_SECTIONS & values.keys())
    missing = [key for key in _KEYS if key not in values]
    unknown = sorted(values.keys() - _KEYS.keys() - _SECTIONS)
    return malformed, missing, unknown


def validate_center_values(values: Mapping[str, object]) -> dict[str, str]:
    """Return every field error, keyed by full TOML key, without changing values.

    Each field reports its first error, using the same checks and messages as
    ``CenterConfig``. Unknown sections use their section name as the error key.
    """
    malformed, missing, unknown = _structure_errors(values)
    errors = {}
    for key, validator in _VALIDATORS.items():
        section = key.split(".")[0]
        if section in malformed:
            errors[key] = f"{section} must be a table, got {values[section]!r}"
        elif key in missing:
            errors[key] = f"missing keys: {key}"
        else:
            try:
                validator(key, values[key])
            except ValueError as error:
                errors[key] = str(error)
    errors.update((key, f"unknown keys: {key}") for key in unknown)
    return errors


def center_from_values(values: Mapping[str, object]) -> CenterConfig:
    """Validate raw values and construct an immutable, normalized center.

    Invalid input raises ``ValueError`` containing all field errors. Use
    ``validate_center_values`` when the individual error keys are needed.
    """
    errors = validate_center_values(values)
    if errors:
        raise ValueError("; ".join(errors.values()))
    return CenterConfig(**{field: values[key] for key, field in _KEYS.items()})


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
        for key, field in _KEYS.items():
            object.__setattr__(self, field, _VALIDATORS[key](key, getattr(self, field)))


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
    data = _read_center_data(path)
    values = _flatten_center_data(data)
    malformed, missing, unknown = _structure_errors(values)
    if malformed:
        section = malformed[0]
        raise ValueError(f"{path}: {section} must be a table, got {values[section]!r}")

    # Preserve the loader's historical grouped diagnostics; field validation
    # still reports every missing full key for an editor.
    missing = sorted({key if key.split(".")[0] in data else key.split(".")[0] for key in missing})
    root_labels = {json.dumps(key, ensure_ascii=False): key for key in data if "." in key}
    unknown = sorted({root_labels.get(key, key) for key in unknown})
    if missing or unknown:
        problems = []
        if missing:
            problems.append(f"missing keys: {', '.join(missing)}")
        if unknown:
            problems.append(f"unknown keys: {', '.join(unknown)}")
        raise ValueError(f"{path}: {'; '.join(problems)}")

    errors = validate_center_values(values)
    if errors:
        raise ValueError(next(iter(errors.values())))
    return center_from_values(values)
