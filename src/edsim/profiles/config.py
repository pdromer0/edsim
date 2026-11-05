"""Clinical profiles from TOML: the context bands, the population and the reasons.

The file ``config/perfiles.toml`` has three tables (see docs/specs/hito-4.md):

- ``[contexto]``: ``franjas``, the starting hours of the morning, afternoon
  and night bands of the arrivals, independent of the shifts of the center;
- ``[poblacion]``: the age bands and, per band, its share in the reference
  context, optional factors per shift band and day type, and the
  percentages of women and of arrivals by ambulance;
- ``[motivos.<clave>]``: one table per reason for consultation, with its
  name, its base weight and optional factors per age band, shift band, day
  type and season.

Keys are in Spanish (ADR 0015) and errors name them in full, such as
``motivos.disnea.edad[1]``, because that is what the user wrote. Unknown keys
are an error, so that a misspelt factor does not silently stay at 1.

Values are stored as written, in clinical units (percentages and factors),
only checked and turned into tuples of floats. Absent factors are stored as
1. So building a profile twice, as ``dataclasses.replace`` does, gives the
same profile. The probabilities are computed by ``edsim.profiles.mixing``.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from edsim.checks import check_integer, check_list, check_number

REASONS: tuple[tuple[str, str, float], ...] = (
    ("traumatismo", "Traumatismo / musculoesquelético", 20.0),
    ("dolor_abdominal", "Dolor abdominal", 10.0),
    ("fiebre", "Fiebre / infección", 8.0),
    ("disnea", "Disnea / respiratorio", 8.0),
    ("malestar", "Malestar general / debilidad", 6.0),
    ("dolor_toracico", "Dolor torácico", 5.0),
    ("neurologico", "Neurológico", 5.0),
    ("sincope", "Síncope / mareo", 4.0),
    ("urologico", "Urológico / renal", 4.0),
    ("cutaneo", "Cutáneo / alergia", 4.0),
    ("orl", "ORL / oftalmológico", 4.0),
    ("digestivo", "Digestivo", 4.0),
    ("psiquiatrico", "Psiquiátrico", 3.0),
    ("palpitaciones", "Palpitaciones / arritmia", 2.0),
    ("intoxicacion", "Intoxicación", 2.0),
    ("parada", "Parada / crítico", 0.5),
    ("otros", "Otros", 10.0),
)
"""The catalog of docs/diseno.md: key, name and approximate share, in percent.

The share is the target of the global mix, not a base weight: «< 1 %» is
written as 0.5 and «~10 %» as 10, so the shares add up to 99.5 and are
normalized when used as targets.
"""

REASON_KEYS: tuple[str, ...] = tuple(key for key, _, _ in REASONS)
"""Keys of the 17 reasons, in the order of the catalog."""

N_BANDS = 4
"""Age bands: 15-44, 45-64, 65-79 and 80-99 by default."""

N_SHIFT_BANDS = 3
"""Shift bands of the arrivals: morning, afternoon and night."""

N_DAY_TYPES = 2
"""Day types: weekday and weekend (Saturday and Sunday); no holidays."""

N_SEASONS = 4
"""Seasons: winter, spring, summer and autumn."""

MIN_AGE = 15
"""Youngest patient: the center sees adults only (ADR candidate 35)."""

MAX_AGE = 99
"""Oldest patient: the top of the last age band."""

# Optional factors of a reason: TOML key → (field, number of values).
_REASON_FACTORS = {
    "edad": ("age_factors", N_BANDS),
    "franja": ("shift_factors", N_SHIFT_BANDS),
    "dia": ("day_factors", N_DAY_TYPES),
    "estacion": ("season_factors", N_SEASONS),
}
_REASON_REQUIRED = ("nombre", "peso_base")

# Keys of [poblacion]: TOML key → field.
_POPULATION_REQUIRED = {
    "bandas_edad": "band_starts",
    "reparto_edad": "band_shares",
    "mujeres": "female_pct",
    "ambulancia": "ambulance_pct",
}
_POPULATION_OPTIONAL = {"franja": "band_shift_factors", "dia": "band_day_factors"}

_SECTIONS = ("contexto", "poblacion", "motivos")


def _check_hours(key: str, values: object) -> tuple[int, ...]:
    """Three integer hours in 0-23, strictly increasing."""
    hours = [
        check_integer(f"{key}[{i}]", h)
        for i, h in enumerate(check_list(key, values, N_SHIFT_BANDS))
    ]
    for i, h in enumerate(hours):
        if not 0 <= h <= 23:
            raise ValueError(f"{key}[{i}] must be between 0 and 23, got {h!r}")
    if any(a >= b for a, b in pairwise(hours)):
        raise ValueError(f"{key} must be strictly increasing, got {hours!r}")
    return tuple(hours)


def _check_band_starts(key: str, values: object) -> tuple[int, ...]:
    """Lower age of each band: integers in [MIN_AGE, MAX_AGE], strictly increasing."""
    ages = [check_integer(f"{key}[{i}]", a) for i, a in enumerate(check_list(key, values, N_BANDS))]
    for i, a in enumerate(ages):
        if not MIN_AGE <= a <= MAX_AGE:
            raise ValueError(f"{key}[{i}] must be between {MIN_AGE} and {MAX_AGE}, got {a!r}")
    if any(a >= b for a, b in pairwise(ages)):
        raise ValueError(f"{key} must be strictly increasing, got {ages!r}")
    return tuple(ages)


def _check_percentages(key: str, values: object, n: int) -> tuple[float, ...]:
    """``n`` percentages in [0, 100]."""
    checked = [check_number(f"{key}[{i}]", x) for i, x in enumerate(check_list(key, values, n))]
    for i, x in enumerate(checked):
        if not 0 <= x <= 100:
            raise ValueError(f"{key}[{i}] must be between 0 and 100, got {values[i]!r}")
    return tuple(checked)


def _check_positive(key: str, value: object) -> float:
    x = check_number(key, value)
    if x <= 0:
        raise ValueError(f"{key} must be positive, got {value!r}")
    return x


def _check_factors(key: str, values: object, n: int) -> tuple[float, ...]:
    """``n`` finite, strictly positive factors."""
    return tuple(
        _check_positive(f"{key}[{i}]", x) for i, x in enumerate(check_list(key, values, n))
    )


def _check_band_factors(key: str, values: object, n: int) -> tuple[tuple[float, ...], ...]:
    """One row of ``n`` factors per age band."""
    return tuple(
        _check_factors(f"{key}[{b}]", row, n)
        for b, row in enumerate(check_list(key, values, N_BANDS))
    )


@dataclass(frozen=True, slots=True)
class ReasonProfile:
    """One reason for consultation, from its ``[motivos.<clave>]`` table.

    Its weight for a patient of band ``b`` in a context is
    ``base_weight * age_factors[b] * shift_factors[shift band] *
    day_factors[day type] * season_factors[season]``.

    Attributes:
        key: Key of the reason, one of ``REASON_KEYS``, such as ``"disnea"``.
        name: Name for people (``nombre``), such as ``"Disnea / respiratorio"``.
        base_weight: Base weight (``peso_base``), derived with
            ``base_weights_for``; positive.
        age_factors: Factor per age band (``edad``); 1 if absent.
        shift_factors: Factor per shift band: morning, afternoon, night
            (``franja``).
        day_factors: Factor per day type: weekday, weekend (``dia``).
        season_factors: Factor per season: winter, spring, summer, autumn
            (``estacion``).
    """

    key: str
    name: str
    base_weight: float
    age_factors: tuple[float, ...] = (1.0,) * N_BANDS
    shift_factors: tuple[float, ...] = (1.0,) * N_SHIFT_BANDS
    day_factors: tuple[float, ...] = (1.0,) * N_DAY_TYPES
    season_factors: tuple[float, ...] = (1.0,) * N_SEASONS

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not self.key:
            raise ValueError(f"the key of a reason must be a non-empty string, got {self.key!r}")
        prefix = f"motivos.{self.key}"
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError(f"{prefix}.nombre must be a non-empty string, got {self.name!r}")
        object.__setattr__(
            self, "base_weight", _check_positive(f"{prefix}.peso_base", self.base_weight)
        )
        for toml_key, (field, n) in _REASON_FACTORS.items():
            checked = _check_factors(f"{prefix}.{toml_key}", getattr(self, field), n)
            object.__setattr__(self, field, checked)


@dataclass(frozen=True, slots=True)
class Population:
    """The population of adults that arrive, from ``[poblacion]``.

    Values per band are in the order of ``band_starts``. The weight of band
    ``b`` in a context is ``band_shares[b] * band_shift_factors[b][shift band]
    * band_day_factors[b][day type]``; with all factors at 1 (the reference
    context), the shares are the age mix.

    Attributes:
        band_starts: Lowest age of each band (``bandas_edad``); the last band
            goes up to ``MAX_AGE``.
        band_shares: Percentage of each band in the reference context
            (``reparto_edad``); in [0, 100], with a positive sum. They do not
            need to add up to 100.
        female_pct: Percentage of women in each band (``mujeres``).
        ambulance_pct: Percentage of arrivals by ambulance in each band
            (``ambulancia``).
        band_shift_factors: Per band, a factor per shift band (``franja``).
        band_day_factors: Per band, a factor per day type (``dia``).
    """

    band_starts: tuple[int, ...]
    band_shares: tuple[float, ...]
    female_pct: tuple[float, ...]
    ambulance_pct: tuple[float, ...]
    band_shift_factors: tuple[tuple[float, ...], ...] = ((1.0,) * N_SHIFT_BANDS,) * N_BANDS
    band_day_factors: tuple[tuple[float, ...], ...] = ((1.0,) * N_DAY_TYPES,) * N_BANDS

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "band_starts", _check_band_starts("poblacion.bandas_edad", self.band_starts))
        shares = _check_percentages("poblacion.reparto_edad", self.band_shares, N_BANDS)
        if sum(shares) <= 0:
            raise ValueError(
                f"poblacion.reparto_edad must have a positive sum, got {list(shares)!r}"
            )
        set_(self, "band_shares", shares)
        set_(self, "female_pct", _check_percentages("poblacion.mujeres", self.female_pct, N_BANDS))
        set_(
            self,
            "ambulance_pct",
            _check_percentages("poblacion.ambulancia", self.ambulance_pct, N_BANDS),
        )
        set_(
            self,
            "band_shift_factors",
            _check_band_factors("poblacion.franja", self.band_shift_factors, N_SHIFT_BANDS),
        )
        set_(
            self,
            "band_day_factors",
            _check_band_factors("poblacion.dia", self.band_day_factors, N_DAY_TYPES),
        )


def _check_reasons(reasons: object) -> tuple[ReasonProfile, ...]:
    """The 17 reasons, each once, in the order of the catalog."""
    if not isinstance(reasons, Iterable) or isinstance(reasons, str | Mapping):
        raise ValueError(f"reasons must be a sequence of ReasonProfile, got {reasons!r}")
    reasons = list(reasons)
    for r in reasons:
        if not isinstance(r, ReasonProfile):
            raise ValueError(f"each reason must be a ReasonProfile, got {r!r}")
    keys = [r.key for r in reasons]
    duplicates = sorted({k for k in keys if keys.count(k) > 1})
    if duplicates:
        raise ValueError(f"duplicate keys: {', '.join(f'motivos.{k}' for k in duplicates)}")
    problems = _problems(*_missing_and_unknown("motivos", keys, REASON_KEYS))
    if problems:
        raise ValueError("; ".join(problems))
    by_key = {r.key: r for r in reasons}
    return tuple(by_key[k] for k in REASON_KEYS)


@dataclass(frozen=True, slots=True)
class ClinicalProfiles:
    """Validated clinical profiles: context bands, population and reasons.

    Validation happens on construction, as in ``CenterConfig``: profiles can
    only exist valid, whether they come from ``load_profiles`` or are built
    directly (also with ``dataclasses.replace``). The reasons are stored in
    the order of the catalog (``REASON_KEYS``), whatever their order in the
    file.

    Attributes:
        shift_band_starts: Starting hour of the morning, afternoon and night
            bands of the arrivals (``contexto.franjas``); three integers in
            0-23, strictly increasing. The night runs past midnight into the
            morning. They are independent of the shifts of ``centro.toml``:
            moving a change of shift does not move the patients.
        population: The age mix, sex and arrival mode (``[poblacion]``).
        reasons: The 17 reasons for consultation (``[motivos.<clave>]``).
    """

    shift_band_starts: tuple[int, ...]
    population: Population
    reasons: tuple[ReasonProfile, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "shift_band_starts", _check_hours("contexto.franjas", self.shift_band_starts)
        )
        if not isinstance(self.population, Population):
            raise ValueError(f"population must be a Population, got {self.population!r}")
        object.__setattr__(self, "reasons", _check_reasons(self.reasons))

    @property
    def reason_keys(self) -> tuple[str, ...]:
        """Keys of the reasons, in the order of the catalog."""
        return tuple(r.key for r in self.reasons)

    def reason(self, key: str) -> ReasonProfile:
        """The profile of one reason, by its key.

        Raises:
            KeyError: If there is no reason with that key.
        """
        for r in self.reasons:
            if r.key == key:
                return r
        raise KeyError(key)


def _missing_and_unknown(
    prefix: str, found: Iterable[str], required: Iterable[str], optional: Iterable[str] = ()
) -> tuple[list[str], list[str]]:
    """Missing and unknown keys of a table, named in full (``prefix.key``)."""
    found, required = set(found), list(required)
    full = (lambda k: f"{prefix}.{k}") if prefix else str
    missing = [full(k) for k in required if k not in found]
    unknown = [full(k) for k in sorted(found - set(required) - set(optional))]
    return missing, unknown


def _problems(missing: list[str], unknown: list[str]) -> list[str]:
    """The messages of ``load_center``: missing keys first, then unknown keys."""
    problems = []
    if missing:
        problems.append(f"missing keys: {', '.join(missing)}")
    if unknown:
        problems.append(f"unknown keys: {', '.join(sorted(unknown))}")
    return problems


def _check_table(name: str, value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a table, got {value!r}")
    return value


def _structure(data: dict) -> list[str]:
    """Every missing or unknown key of the file, reported together."""
    missing, unknown = _missing_and_unknown("", data, _SECTIONS)

    def add(found: tuple[list[str], list[str]]) -> None:
        missing.extend(found[0])
        unknown.extend(found[1])

    if "contexto" in data:
        add(
            _missing_and_unknown(
                "contexto", _check_table("contexto", data["contexto"]), ["franjas"]
            )
        )
    if "poblacion" in data:
        population = _check_table("poblacion", data["poblacion"])
        add(
            _missing_and_unknown(
                "poblacion", population, _POPULATION_REQUIRED, _POPULATION_OPTIONAL
            )
        )
    if "motivos" in data:
        reasons = _check_table("motivos", data["motivos"])
        add(_missing_and_unknown("motivos", reasons, REASON_KEYS))
        for key in REASON_KEYS:
            if key in reasons:
                table = _check_table(f"motivos.{key}", reasons[key])
                add(
                    _missing_and_unknown(f"motivos.{key}", table, _REASON_REQUIRED, _REASON_FACTORS)
                )
    return _problems(missing, unknown)


def load_profiles(path: str | Path) -> ClinicalProfiles:
    """Load the clinical profiles from a TOML file.

    The file must have the tables ``[contexto]``, ``[poblacion]`` and one
    ``[motivos.<clave>]`` for each of the 17 reasons of ``REASON_KEYS``. The
    factors are optional and worth 1 when absent; any other key is an error.

    Args:
        path: Path of the TOML file, such as ``config/perfiles.toml``.

    Returns:
        The validated profiles.

    Raises:
        ValueError: If tables or keys are missing or unknown, or a value is not
            valid. Missing and unknown keys are reported together, with their
            full name, such as ``motivos.disnea.edades``.
        FileNotFoundError: If the file does not exist.
        tomllib.TOMLDecodeError: If the file is not valid TOML.
    """
    path = Path(path)
    with path.open("rb") as file:
        data = tomllib.load(file)

    try:
        problems = _structure(data)
    except ValueError as error:
        raise ValueError(f"{path}: {error}") from None
    if problems:
        raise ValueError(f"{path}: {'; '.join(problems)}")

    population = data["poblacion"]
    reasons = data["motivos"]
    return ClinicalProfiles(
        shift_band_starts=data["contexto"]["franjas"],
        population=Population(
            **{field: population[key] for key, field in _POPULATION_REQUIRED.items()},
            **{
                field: population[key]
                for key, field in _POPULATION_OPTIONAL.items()
                if key in population
            },
        ),
        reasons=tuple(
            ReasonProfile(
                key=key,
                name=reasons[key]["nombre"],
                base_weight=reasons[key]["peso_base"],
                **{
                    field: reasons[key][toml_key]
                    for toml_key, (field, _) in _REASON_FACTORS.items()
                    if toml_key in reasons[key]
                },
            )
            for key in REASON_KEYS
        ),
    )
