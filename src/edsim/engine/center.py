"""Center configuration: shifts, staff, boxes and destination, from TOML.

The file has one table per topic (``turnos``, ``recursos`` and ``destino``);
see ``config/centro.toml`` and docs/specs/hito-3.md. Keys are in Spanish (ADR
0015) and errors name them with their table, such as ``recursos.medicos[2]``,
because that is what the user wrote.

The provisional model of milestone 3 also reads ``triaje``, ``duraciones`` and
``pruebas``: the provisional block (task 4.9). The three tables come together
or not at all. Without them, their six fields are ``None`` and only the
clinical model can use the center, which takes those values from the profiles;
``tests/data/centro_ejemplo.toml`` is the center of the provisional model, and
copies of ``centro.toml`` saved with older runs still read as they did.

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
from edsim.profiles.config import N_SEASONS

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
    "recursos.espera_resultados_fuera": "results_wait_outside",
    "triaje.reparto_niveles": "level_shares",
    "duraciones.triaje": "triage_time",
    "duraciones.valoracion": "assessment_time",
    "duraciones.reevaluacion": "reassessment_time",
    "duraciones.respuesta_pruebas": "test_turnaround",
    "pruebas.probabilidad": "test_probability",
    "destino.probabilidad_ingreso": "admission_probability",
    "camas.espera": "bed_wait",
    "camas.factor_turno": "bed_shift_factors",
    "camas.factor_estacion": "bed_season_factors",
}
_SECTIONS = {key.split(".")[0] for key in _KEYS}

DESTINATION_KEY = "destino.probabilidad_ingreso"
"""The only key of ``[destino]``: the provisional and milestone 4 models need it."""

BED_TABLE = "camas"
"""The table of the wait for a bed, of the milestone 5 model (task 5.2)."""

_BED_KEYS = tuple(key for key in _KEYS if key.split(".")[0] == BED_TABLE)
_BED_FIELDS = tuple(_KEYS[key] for key in _BED_KEYS)
_BED_OPTIONAL = {"camas.factor_estacion": (1.0,) * N_SEASONS}
"""Keys of ``[camas]`` that may be missing, with the value they mean then."""

MISSING_DESTINATION = (
    "missing keys: destino.probabilidad_ingreso (provisional and milestone 4 models) "
    "or camas.espera and camas.factor_turno (milestone 5 model)"
)
BOTH_DESTINATION_AND_BEDS = (
    "a center has [destino] (provisional and milestone 4 models) or [camas] "
    "(milestone 5 model), not both"
)
_MISSING_DESTINATION_TABLES = (
    "destino (provisional and milestone 4 models) or camas (milestone 5 model)"
)

# Keys that may be missing, with the value they mean then. Only one: a center
# written before task 4.6a (such as the copy kept in a saved run) has no
# espera_resultados_fuera, and it means what it meant then, nobody waits
# outside. That is why the default is () and not the (4, 5) of config/.
_OPTIONAL: dict[str, object] = {"recursos.espera_resultados_fuera": ()}

PROVISIONAL_TABLES = ("triaje", "duraciones", "pruebas")
"""Tables of the provisional block: all three or none (task 4.9)."""

# The six keys of the provisional block, in the order of the file. Without the
# block they are all None; there is no hidden default for the provisional model.
_PROVISIONAL_KEYS = tuple(key for key in _KEYS if key.split(".")[0] in PROVISIONAL_TABLES)
_PROVISIONAL_FIELDS = tuple(_KEYS[key] for key in _PROVISIONAL_KEYS)


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


def _check_wait_outside(key: str, values: object) -> tuple[int, ...]:
    """Assigned levels that wait for their results outside the box: 2 to 5, increasing.

    Level 1 is classified at the door and keeps its box; a list may be empty.
    """
    if not isinstance(values, list | tuple):
        raise ValueError(f"{key} must be a list of levels from 2 to {N_LEVELS}, got {values!r}")
    levels = [check_integer(f"{key}[{i}]", x) for i, x in enumerate(values)]
    for i, level in enumerate(levels):
        if level == 1:
            raise ValueError(
                f"{key}[{i}] cannot be 1: level 1 is classified at the door and never "
                "waits outside the box"
            )
        if not 2 <= level <= N_LEVELS:
            raise ValueError(f"{key}[{i}] must be a level from 2 to {N_LEVELS}, got {level!r}")
    if any(a >= b for a, b in pairwise(levels)):
        raise ValueError(f"{key} must be increasing, without repeats, got {levels!r}")
    return tuple(levels)


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


def _check_factors(key: str, values: object, n: int) -> tuple[float, ...]:
    """``n`` finite, strictly positive factors."""
    factors = [check_number(f"{key}[{i}]", x) for i, x in enumerate(check_list(key, values, n))]
    for i, x in enumerate(factors):
        if x <= 0:
            raise ValueError(f"{key}[{i}] must be positive, got {values[i]!r}")
    return tuple(factors)


def _check_shift_factors(key: str, values: object) -> tuple[float, ...]:
    """One factor per shift: morning, afternoon and night."""
    return _check_factors(key, values, N_SHIFTS)


def _check_season_factors(key: str, values: object) -> tuple[float, ...]:
    """One factor per season: winter, spring, summer and autumn."""
    return _check_factors(key, values, N_SEASONS)


_VALIDATORS = dict(
    zip(
        _KEYS,
        (
            _check_shift_starts,
            _check_shift_staff,
            _check_shift_staff,
            _check_staff,
            _check_wait_outside,
            _check_shares,
            _check_duration,
            _check_duration,
            _check_duration,
            _check_duration,
            _check_probabilities,
            _check_probabilities,
            _check_duration,
            _check_shift_factors,
            _check_season_factors,
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


def _has_provisional_block(values: Mapping[str, object]) -> bool:
    """Whether any table of the provisional block is there.

    A table is there if it brings a key, known or unknown, or if it is
    malformed (not a table). An empty table brings no key and counts as missing.
    """
    return _has_tables(values, PROVISIONAL_TABLES)


def _has_tables(values: Mapping[str, object], tables: tuple[str, ...]) -> bool:
    """Whether any of ``tables`` brings a key, known or unknown, or is malformed."""
    return any(key in tables or key.split(".")[0] in tables for key in values)


def _destination_conflict(values: Mapping[str, object]) -> str | None:
    """The error of [destino] and [camas]: exactly one of the two, never both (task 5.2).

    ``None`` if the center has one of them. Without either, the missing key
    is ``destino.probabilidad_ingreso``, with a message that names both tables.
    """
    has_destination = _has_tables(values, ("destino",))
    has_beds = _has_tables(values, (BED_TABLE,))
    if has_destination and has_beds:
        return BOTH_DESTINATION_AND_BEDS
    if not has_destination and not has_beds:
        return MISSING_DESTINATION
    return None


def _structure_errors(values: Mapping[str, object]) -> tuple[list[str], list[str], list[str]]:
    malformed = sorted(_SECTIONS & values.keys())
    optional = _OPTIONAL.keys() | _BED_OPTIONAL.keys()
    if not _has_provisional_block(values):
        optional = optional | set(_PROVISIONAL_KEYS)
    if _has_tables(values, (BED_TABLE,)):
        optional = optional | {DESTINATION_KEY}
    else:
        optional = optional | set(_BED_KEYS)
    missing = [key for key in _KEYS if key not in values and key not in optional]
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
        elif key not in values:
            continue  # an optional key, or the provisional block is missing
        else:
            try:
                validator(key, values[key])
            except ValueError as error:
                errors[key] = str(error)
    conflict = _destination_conflict(values)
    if conflict is not None and "destino" not in malformed:
        # Under the key the app edits, so that it shows next to its field.
        errors[DESTINATION_KEY] = conflict
    errors.update((key, f"unknown keys: {key}") for key in unknown)
    return errors


def center_from_values(values: Mapping[str, object]) -> CenterConfig:
    """Validate raw values and construct an immutable, normalized center.

    Invalid input raises ``ValueError`` containing all field errors. Use
    ``validate_center_values`` when the individual error keys are needed.
    Without the provisional block, its six fields are ``None``.
    """
    errors = validate_center_values(values)
    if errors:
        raise ValueError("; ".join(errors.values()))
    return CenterConfig(
        **{field: values.get(key, _OPTIONAL.get(key)) for key, field in _KEYS.items()}
    )


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
        results_wait_outside: Assigned levels whose patients leave the box when
            they order tests and wait for the results outside, in a room without
            a capacity limit (``recursos.espera_resultados_fuera``; ADR
            candidate 45). Levels 2 to 5, increasing; ``()`` if the key is
            missing, as in a center written before task 4.6a. Only the clinical
            model uses it: the provisional model ignores it.
        level_shares: Share of patients in each triage level, summing to 1
            (``triaje.reparto_niveles``, which accepts any non-negative
            weights, such as percentages). A level may have share 0. This
            and the next five fields are the provisional block: all of them
            or none are ``None`` (task 4.9).
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
            (``destino.probabilidad_ingreso``); the rest are discharged. The
            provisional and milestone 4 models need it; ``None`` in a center
            of milestone 5, which has ``[camas]`` instead (task 5.2). A center
            has one of the two, never both.
        bed_wait: ``(median, p90)`` of the wait for a bed of the admitted
            patients, in their box, with factor 1, in minutes
            (``camas.espera``; H5-6). This and the next two fields are
            ``[camas]``: ``None`` without it.
        bed_shift_factors: Factor of the wait by the shift of the request:
            morning, afternoon, night (``camas.factor_turno``).
        bed_season_factors: Factor by the season of the request: winter,
            spring, summer, autumn (``camas.factor_estacion``); 1 if missing.
    """

    shift_starts: tuple[int, ...]
    triage_nurses: tuple[int, ...]
    doctors: tuple[int, ...]
    boxes: int
    results_wait_outside: tuple[int, ...]
    level_shares: tuple[float, ...] | None
    triage_time: tuple[float, float] | None
    assessment_time: tuple[float, float] | None
    reassessment_time: tuple[float, float] | None
    test_turnaround: tuple[float, float] | None
    test_probability: tuple[float, ...] | None
    admission_probability: tuple[float, ...] | None
    bed_wait: tuple[float, float] | None = None
    bed_shift_factors: tuple[float, ...] | None = None
    bed_season_factors: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        has_beds = any(getattr(self, field) is not None for field in _BED_FIELDS)
        if has_beds and self.admission_probability is not None:
            raise ValueError(BOTH_DESTINATION_AND_BEDS)
        if not has_beds and self.admission_probability is None:
            raise ValueError(MISSING_DESTINATION)
        if has_beds:
            if self.bed_season_factors is None:
                object.__setattr__(
                    self, "bed_season_factors", _BED_OPTIONAL["camas.factor_estacion"]
                )
            lacking = [
                key
                for key, field in zip(_BED_KEYS, _BED_FIELDS, strict=True)
                if getattr(self, field) is None
            ]
            if lacking:
                raise ValueError(f"missing keys: {', '.join(lacking)}")
        missing = [
            key
            for key, field in zip(_PROVISIONAL_KEYS, _PROVISIONAL_FIELDS, strict=True)
            if getattr(self, field) is None
        ]
        if missing and len(missing) < len(_PROVISIONAL_KEYS):
            raise ValueError(
                "the provisional tables [triaje], [duraciones] and [pruebas] come together "
                f"or not at all: missing keys: {', '.join(missing)}"
            )
        for key, field in _KEYS.items():
            if missing and key in _PROVISIONAL_KEYS:
                continue
            if getattr(self, field) is None and (key == DESTINATION_KEY or key in _BED_KEYS):
                continue  # the table this center does not have
            object.__setattr__(self, field, _VALIDATORS[key](key, getattr(self, field)))

    @property
    def has_beds(self) -> bool:
        """Whether the center has ``[camas]`` (milestone 5 model) instead of ``[destino]``."""
        return self.bed_wait is not None

    @property
    def has_provisional(self) -> bool:
        """Whether the center has the provisional block, which the provisional model needs."""
        return self.level_shares is not None


def require_destination(center: CenterConfig) -> None:
    """Fail early if the provisional or milestone 4 model gets a center without ``[destino]``.

    Both draw the destination with ``destino.probabilidad_ingreso`` of the
    assigned level. A center of milestone 5 has ``[camas]`` instead (task 5.2).

    Raises:
        ValueError: If ``center`` has no ``[destino]``; the message names it.
    """
    if center.admission_probability is None:
        raise ValueError(
            "the provisional and milestone 4 models need [destino] of the center "
            "(destino.probabilidad_ingreso); this one has [camas], of the milestone 5 model"
        )


def require_provisional(center: CenterConfig) -> None:
    """Fail early if the provisional model is asked for a center without its block.

    Raises:
        ValueError: If ``center`` has no ``[triaje]``, ``[duraciones]`` and
            ``[pruebas]``; the message names the three tables.
    """
    if not center.has_provisional:
        raise ValueError(
            "the provisional model needs the tables [triaje], [duraciones] and [pruebas] "
            "of the center, and this one has none of them"
        )


def load_center(path: str | Path) -> CenterConfig:
    """Load the center configuration from a TOML file.

    The file has the tables and keys of ``config/centro.toml`` and, for the
    provisional model, the provisional block (``triaje``, ``duraciones`` and
    ``pruebas``, all three or none), as ``tests/data/centro_ejemplo.toml``.
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
    conflict = _destination_conflict(values)
    labels = {}
    if conflict == MISSING_DESTINATION:
        # Neither [destino] nor [camas]: say which one each model needs.
        labels = {
            "destino": _MISSING_DESTINATION_TABLES,
            DESTINATION_KEY: _MISSING_DESTINATION_TABLES,
        }
    missing = sorted(
        {
            labels.get(name, name)
            for name in (key if key.split(".")[0] in data else key.split(".")[0] for key in missing)
        }
    )
    root_labels = {json.dumps(key, ensure_ascii=False): key for key in data if "." in key}
    unknown = sorted({root_labels.get(key, key) for key in unknown})
    if missing or unknown:
        problems = []
        if missing:
            problems.append(f"missing keys: {', '.join(missing)}")
        if unknown:
            problems.append(f"unknown keys: {', '.join(unknown)}")
        raise ValueError(f"{path}: {'; '.join(problems)}")
    if conflict is not None:
        raise ValueError(f"{path}: {conflict}")

    errors = validate_center_values(values)
    if errors:
        raise ValueError(next(iter(errors.values())))
    return center_from_values(values)
