"""Load and validate ``config/registro_clinico.toml``: how much the hospital gets wrong.

One table per profile, with the same keys in the three (docs/specs/hito-7.md,
«Especificación: perfiles»). The keys are Spanish, as in every configuration
file; ``load_record_profiles`` turns each profile into a ``RecordProfile``.

The rules, each error naming its profile and its key (``realista.retraso.triaje.minutos``):

- exactly the profiles ``limpio``, ``realista`` and ``hostil``, each with exactly the keys of
  the specification: a missing or an unknown key is an error;
- the systems of ``retraso`` and ``reloj`` are exactly those of the catalog;
- rates in [0, 1]; ``minutos`` is ``[median, p90]`` with 0 < median < p90 (the lognormal of
  ``edsim.lognormal``); offsets are any finite number, of any sign;
- ``limpio`` has every rate and every offset at 0: "clean" has to mean clean.

All the problems of a file are reported together, as ``load_profiles`` does.
"""

import math
import tomllib
from collections.abc import Iterator, Mapping
from pathlib import Path
from types import MappingProxyType

from edsim.clinical_record.record import SYSTEMS, RecordProfile, Timed
from edsim.lognormal import lognormal_params

PROFILE_NAMES: tuple[str, ...] = ("limpio", "realista", "hostil")
"""The three profiles of the file, from no slips to exaggerated ones."""

CLEAN = "limpio"
"""The profile whose rates and offsets must all be 0."""

DEFAULT_PROFILES_FILE = "config/registro_clinico.toml"


def _number(value: object) -> float:
    """A TOML number as a finite float: not a bool, a string or a date."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"must be a number, got {value!r}")
    try:
        number = float(value)
    except OverflowError:  # an integer of 10**400: float() fails before isfinite can
        raise ValueError("is too large to be a finite number") from None
    if not math.isfinite(number):
        raise ValueError(f"must be finite, got {value!r}")
    return number


def _rate(value: object) -> float:
    number = _number(value)
    if not 0 <= number <= 1:
        raise ValueError(f"must be in [0, 1], got {value!r}")
    return number


def _offset(value: object) -> float:
    return _number(value)


def _minutes(value: object) -> tuple[float, float]:
    """``[median, p90]`` of a lognormal: two numbers, 0 < median < p90."""
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"must be [median, p90], got {value!r}")
    median, p90 = _number(value[0]), _number(value[1])
    try:
        lognormal_params(median, p90)
    except ValueError as error:
        raise ValueError(f"[median, p90] = {value!r}: {error}") from None
    return median, p90


_TIMED = {"tasa": _rate, "minutos": _minutes}
_SHAPE: dict[str, object] = {
    "olvido": _rate,
    "vacio": _rate,
    "erroneo": _rate,
    "duplicado": _TIMED,
    "correccion": _TIMED,
    "retraso": {system: _TIMED for system in SYSTEMS},
    "reloj": {system: _offset for system in SYSTEMS},
}
"""The keys of a profile: a table is a dict, a value is the function that checks it."""


def _walk(
    prefix: str, value: object, shape: object, problems: list[str]
) -> dict[str, object] | object:
    """Check ``value`` against ``shape``; the parsed tree, or ``None`` where it has a problem."""
    if callable(shape):
        try:
            return shape(value)
        except ValueError as error:
            problems.append(f"{prefix}: {error}")
            return None
    if not isinstance(value, Mapping):
        problems.append(f"{prefix}: must be a table, got {value!r}")
        return None
    for key in shape:
        if key not in value:
            problems.append(f"{prefix}.{key}: missing key")
    for key in value:
        if key not in shape:
            problems.append(f"{prefix}.{key}: unknown key")
    return {
        key: _walk(f"{prefix}.{key}", value[key], shape[key], problems)
        for key in shape
        if key in value
    }


def _zeros(prefix: str, tree: object) -> Iterator[tuple[str, float]]:
    """The rates and offsets of a parsed profile, with their keys: what ``limpio`` keeps at 0."""
    if isinstance(tree, dict):
        for key, child in tree.items():
            if key != "minutos":
                yield from _zeros(f"{prefix}.{key}", child)
    elif tree is not None:
        yield prefix, tree


class RecordProfiles(Mapping[str, RecordProfile]):
    """The profiles of a file by name, in the order of ``PROFILE_NAMES``."""

    def __init__(self, profiles: Mapping[str, RecordProfile]) -> None:
        self._profiles = MappingProxyType({name: profiles[name] for name in PROFILE_NAMES})

    def __getitem__(self, name: str) -> RecordProfile:
        try:
            return self._profiles[name]
        except KeyError:
            raise KeyError(
                f"unknown profile {name!r}: the profiles are {PROFILE_NAMES!r}"
            ) from None

    def __iter__(self) -> Iterator[str]:
        return iter(self._profiles)

    def __len__(self) -> int:
        return len(self._profiles)

    def __repr__(self) -> str:
        return f"RecordProfiles({list(self._profiles)!r})"


def _timed(tree: dict[str, object]) -> Timed:
    return Timed(tree["tasa"], tree["minutos"])


def _profile(name: str, tree: dict[str, object]) -> RecordProfile:
    return RecordProfile(
        name=name,
        forget=tree["olvido"],
        empty=tree["vacio"],
        wrong=tree["erroneo"],
        duplicate=_timed(tree["duplicado"]),
        correction=_timed(tree["correccion"]),
        delay={system: _timed(tree["retraso"][system]) for system in SYSTEMS},
        clock=dict(tree["reloj"]),
    )


def load_record_profiles(path: str | Path) -> RecordProfiles:
    """Load the three profiles of the clinical record from a TOML file.

    Args:
        path: Path of the file, such as ``config/registro_clinico.toml``.

    Returns:
        The validated profiles: ``limpio``, ``realista`` and ``hostil``.

    Raises:
        ValueError: If a profile or a key is missing or unknown, a value is not valid, or
            ``limpio`` has a rate or an offset other than 0. All the problems are reported
            together, each with its profile and key. A file that is not valid TOML raises
            ``tomllib.TOMLDecodeError``, which is a ``ValueError``.
        OSError: If the file cannot be read.
    """
    path = Path(path)
    with path.open("rb") as file:
        data = tomllib.load(file)

    problems: list[str] = []
    for name in PROFILE_NAMES:
        if name not in data:
            problems.append(f"{name}: missing profile")
    for name in data:
        if name not in PROFILE_NAMES:
            problems.append(f"{name}: unknown profile (the profiles are {PROFILE_NAMES!r})")
    trees = {
        name: _walk(name, data[name], _SHAPE, problems) for name in PROFILE_NAMES if name in data
    }
    clean = trees.get(CLEAN)
    if clean:
        for key, value in _zeros(CLEAN, clean):
            if value is not None and value != 0:
                problems.append(f"{key}: must be 0 in the clean profile, got {value!r}")
    if problems:
        raise ValueError(f"{path}: {'; '.join(problems)}")
    return RecordProfiles({name: _profile(name, trees[name]) for name in PROFILE_NAMES})

