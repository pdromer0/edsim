"""Calibration targets from ``config/objetivos.toml``.

Each target is one table ``[objetivos.<name>]`` with the observed value it is
calibrated against, its band and its source, so that the CLI, the notebook and
the tests read the same numbers (docs/specs/hito-4.md, "Calibración"):

- ``medida``: a per-episode measure of ``EpisodeRecord``, such as
  ``triage_wait`` (the pretriage) or ``door_to_doctor`` (clock A);
- ``niveles``: the assigned levels whose patients count, such as ``[2, 3, 4, 5]``;
- ``estadistico``: ``"media"`` (mean per patient, in minutes) or
  ``"porcentaje_sobre_umbral"`` (percentage of patients above ``umbral``);
- ``umbral``: only with the percentage, in minutes or ``"manchester"`` (the
  Manchester maximum of each patient's assigned level); above means strictly
  above, so a patient exactly at the threshold is not counted;
- ``referencia``: the observed value, optional (some sources give only a
  range), and inside the band when present;
- ``horquilla``: ``[min, max]`` with min < max; a percentage within [0, 100];
- ``uso``: ``"ajuste"`` (fits a knob) or ``"comprobacion"`` (reserved check);
- ``fuente`` and ``enlace``: where the number comes from; ``nota``, optional.

Unknown keys are an error, and every error names the full key, such as
``objetivos.pretriaje_medio.horquilla``.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from edsim.checks import check_integer, check_list, check_number
from edsim.engine.analysis import MEASURES
from edsim.engine.center import N_LEVELS
from edsim.engine.targets import MANCHESTER_MAX_WAIT

MEAN = "media"
"""Statistic: mean of the measure per patient, in minutes."""

PERCENTAGE = "porcentaje_sobre_umbral"
"""Statistic: percentage of the patients whose measure is above the threshold."""

STATISTICS = (MEAN, PERCENTAGE)

FIT = "ajuste"
"""Use of a target that fits a knob."""

CHECK = "comprobacion"
"""Use of a target reserved to check the fit, never to choose it."""

USES = (FIT, CHECK)

MANCHESTER = "manchester"
"""Threshold of a percentage: the Manchester maximum of the assigned level."""

_REQUIRED = ("medida", "niveles", "estadistico", "horquilla", "uso", "fuente", "enlace")
_OPTIONAL = ("referencia", "umbral", "nota")


def _check_text(key: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string, got {value!r}")
    return value


def _check_levels(key: str, values: object) -> tuple[int, ...]:
    if not isinstance(values, list | tuple) or not values:
        raise ValueError(f"{key} must be a non-empty list of levels from 1 to 5, got {values!r}")
    levels = [check_integer(f"{key}[{i}]", x) for i, x in enumerate(values)]
    for i, level in enumerate(levels):
        if not 1 <= level <= N_LEVELS:
            raise ValueError(f"{key}[{i}] must be a level from 1 to {N_LEVELS}, got {level!r}")
    if any(a >= b for a, b in pairwise(levels)):
        raise ValueError(f"{key} must be increasing, without repeats, got {levels!r}")
    return tuple(levels)


@dataclass(frozen=True, slots=True)
class Target:
    """One calibration target, validated on construction.

    Attributes:
        name: The name of its table, such as ``pretriaje_medio``.
        measure: A name of ``MEASURES`` (``medida``).
        levels: Assigned levels that count, increasing (``niveles``).
        statistic: ``MEAN`` or ``PERCENTAGE`` (``estadistico``).
        threshold: With ``PERCENTAGE``, minutes or ``MANCHESTER``; ``None``
            with ``MEAN`` (``umbral``).
        band: ``(min, max)`` of the band (``horquilla``).
        use: ``FIT`` or ``CHECK`` (``uso``).
        source: Where the reference comes from (``fuente``).
        link: Address of the source (``enlace``).
        reference: The observed value, inside the band, or ``None``
            (``referencia``).
        note: A remark on the source, or ``None`` (``nota``).
    """

    name: str
    measure: str
    levels: tuple[int, ...]
    statistic: str
    threshold: float | str | None
    band: tuple[float, float]
    use: str
    source: str
    link: str
    reference: float | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        name = _check_text("target name", self.name)
        key = f"objetivos.{name}"
        if self.measure not in MEASURES:
            raise ValueError(f"{key}.medida must be one of {MEASURES}, got {self.measure!r}")
        set_(self, "levels", _check_levels(f"{key}.niveles", self.levels))
        if self.statistic not in STATISTICS:
            raise ValueError(
                f"{key}.estadistico must be one of {STATISTICS}, got {self.statistic!r}"
            )
        set_(self, "threshold", self._checked_threshold(key))
        low, high = (
            check_number(f"{key}.horquilla[{i}]", x)
            for i, x in enumerate(check_list(f"{key}.horquilla", self.band, 2))
        )
        if not low < high:
            raise ValueError(f"{key}.horquilla must have min < max, got {[low, high]!r}")
        if self.statistic == PERCENTAGE and not 0 <= low < high <= 100:
            raise ValueError(f"{key}.horquilla of a percentage must be within [0, 100]")
        set_(self, "band", (low, high))
        if self.use not in USES:
            raise ValueError(f"{key}.uso must be one of {USES}, got {self.use!r}")
        set_(self, "source", _check_text(f"{key}.fuente", self.source))
        set_(self, "link", _check_text(f"{key}.enlace", self.link))
        if self.reference is not None:
            reference = check_number(f"{key}.referencia", self.reference)
            if not low <= reference <= high:
                raise ValueError(
                    f"{key}.referencia must be inside the band {[low, high]!r}, got {reference!r}"
                )
            set_(self, "reference", reference)
        if self.note is not None:
            set_(self, "note", _check_text(f"{key}.nota", self.note))

    def _checked_threshold(self, key: str) -> float | str | None:
        threshold = self.threshold
        if self.statistic == MEAN:
            if threshold is not None:
                raise ValueError(f"{key}.umbral is only for {PERCENTAGE!r}, not for {MEAN!r}")
            return None
        if threshold is None:
            raise ValueError(f"{key}.umbral is required with {PERCENTAGE!r}")
        if threshold == MANCHESTER:
            return MANCHESTER
        minutes = check_number(f"{key}.umbral", threshold) if not isinstance(threshold, str) else -1
        if not minutes > 0:
            raise ValueError(
                f"{key}.umbral must be minutes > 0 or {MANCHESTER!r}, got {threshold!r}"
            )
        return minutes

    @property
    def is_percentage(self) -> bool:
        """Whether the statistic is a percentage of patients."""
        return self.statistic == PERCENTAGE

    def threshold_for(self, level: int) -> float:
        """The threshold of a patient of assigned ``level``, in minutes."""
        if self.threshold is None:
            raise ValueError(f"objetivos.{self.name} is a mean: it has no threshold")
        if self.threshold == MANCHESTER:
            return MANCHESTER_MAX_WAIT[level - 1]
        return float(self.threshold)


def _target(name: str, table: object) -> Target:
    key = f"objetivos.{name}"
    if not isinstance(table, dict):
        raise ValueError(f"{key} must be a table, got {table!r}")
    missing = [f"{key}.{k}" for k in _REQUIRED if k not in table]
    unknown = [f"{key}.{k}" for k in sorted(table.keys() - {*_REQUIRED, *_OPTIONAL})]
    problems = []
    if missing:
        problems.append(f"missing keys: {', '.join(missing)}")
    if unknown:
        problems.append(f"unknown keys: {', '.join(unknown)}")
    if problems:
        raise ValueError("; ".join(problems))
    return Target(
        name=name,
        measure=table["medida"],
        levels=table["niveles"],
        statistic=table["estadistico"],
        threshold=table.get("umbral"),
        band=table["horquilla"],
        use=table["uso"],
        source=table["fuente"],
        link=table["enlace"],
        reference=table.get("referencia"),
        note=table.get("nota"),
    )


def targets_from_data(data: dict) -> tuple[Target, ...]:
    """The targets of the parsed TOML ``data``, in the order of the file.

    Raises:
        ValueError: If a table or key is missing or unknown, or a value is not
            valid; the message names the full key.
    """
    unknown = sorted(data.keys() - {"objetivos"})
    if unknown:
        raise ValueError(f"unknown keys: {', '.join(unknown)}")
    if "objetivos" not in data:
        raise ValueError("missing keys: objetivos")
    tables = data["objetivos"]
    if not isinstance(tables, dict) or not tables:
        raise ValueError(f"objetivos must be a non-empty table of targets, got {tables!r}")
    return tuple(_target(name, table) for name, table in tables.items())


def load_targets(path: str | Path) -> tuple[Target, ...]:
    """Load the calibration targets of a TOML file, such as ``config/objetivos.toml``.

    Raises:
        ValueError: If the file has missing or unknown keys or invalid values
            (``tomllib.TOMLDecodeError`` for invalid TOML is a ``ValueError``).
        FileNotFoundError: If the file does not exist.
    """
    with Path(path).open("rb") as file:
        return targets_from_data(tomllib.load(file))
