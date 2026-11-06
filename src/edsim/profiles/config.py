"""Clinical profiles from TOML: the context bands, the population and the reasons.

The file ``config/perfiles.toml`` has four tables (see docs/specs/hito-4.md):

- ``[contexto]``: ``franjas``, the starting hours of the morning, afternoon
  and night bands of the arrivals, independent of the shifts of the center;
- ``[poblacion]``: the age bands and, per band, its share in the reference
  context, optional factors per shift band and day type, and the
  percentages of women and of arrivals by ambulance;
- ``[motivos.<clave>]``: one table per reason for consultation, with its
  name, its base weight, optional factors per age band, shift band, day
  type and season, and its latent severity (``gravedad``);
- ``[triaje]``: the target mix of assigned levels, the targets of under- and
  overtriage, the noise and bias of the nurse's error, the four thresholds
  and the duration of the triage;
- ``[duraciones]``: the assessment and the reassessment of the doctor, per
  true level;
- ``[pruebas.<tipo>]``: one table per type of test (``TEST_TYPES``), with its
  turnaround, its odds ratios and the share of abnormal results.

Each reason also gives, in ``pruebas``, the percentage of each type of test
for an adult with G = 0, and an optional factor on its durations
(``duracion``).

The thresholds, the noise and the bias are written in the file, not computed
on loading: ``edsim.profiles.severity`` derives them once and a test checks
that the written values are still the derived ones. So a scenario with more
severity gives more urgent levels instead of being renormalized back to the
target.

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
    ("parada", "Parada / crítico", 0.3),
    ("otros", "Otros", 10.0),
)
"""The catalog of docs/diseno.md: key, name and approximate share, in percent.

The share is the target of the global mix, not a base weight: «< 1 %» is
written as 0.3 and «~10 %» as 10, so the shares add up to 99.3 and are
normalized when used as targets. The cardiac arrest was 0.5 until task 4.6a:
with 0.3 and a high, narrow severity almost all of them fit in the 0.4 % of
assigned level 1 (ADR candidate 46).
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

N_LEVELS = 5
"""Triage levels, from 1 (most urgent) to 5."""

N_THRESHOLDS = N_LEVELS - 1
"""Thresholds between the triage levels."""

TEST_TYPES: tuple[str, ...] = ("analitica", "radiografia", "ecg", "imagen")
"""Types of test, in the order of every per-type value: blood tests, X-ray,
ECG and imaging (ultrasound or CT). Fixed in the code: the log and the
ground truth name them."""

N_TEST_TYPES = len(TEST_TYPES)
"""Types of test: 4."""

TARGET_SUM_TOLERANCE = 0.5
"""Largest distance from 100 of the sum of ``reparto_objetivo``, in points.

Published shares are rounded: the adult mix of Emergencias 2013 adds up to
100.1. Within the tolerance the shares are normalized; beyond it, the file
has an error.
"""

# Optional factors of a reason: TOML key → (field, number of values).
_REASON_FACTORS = {
    "edad": ("age_factors", N_BANDS),
    "franja": ("shift_factors", N_SHIFT_BANDS),
    "dia": ("day_factors", N_DAY_TYPES),
    "estacion": ("season_factors", N_SEASONS),
}
_REASON_REQUIRED = ("nombre", "peso_base", "gravedad", "pruebas")
_REASON_OPTIONAL = ("duracion",)

# Keys of the severity of a reason: TOML key → field.
_SEVERITY_REQUIRED = {"media": "mean", "desviacion": "sd"}
_SEVERITY_OPTIONAL = {"por_edad": "age_shift"}

# Keys of [triaje]: TOML key → field. All are required.
_TRIAGE_KEYS = {
    "reparto_objetivo": "target_pct",
    "infratriaje": "under_pct",
    "sobretriaje": "over_pct",
    "ruido": "noise",
    "sesgo": "bias",
    "umbrales": "thresholds",
    "duracion": "duration",
}

# Keys of [duraciones]: TOML key → field. Both are required.
_DURATION_KEYS = {"valoracion": "assessment", "reevaluacion": "reassessment"}

# Keys of [pruebas.<tipo>]: TOML key → field.
_TEST_REQUIRED = {"respuesta": "turnaround", "or_gravedad": "severity_or", "alterado": None}
_TEST_OPTIONAL = {"respuesta_franja": "turnaround_shift_factors", "or_mayor": "older_or"}
# Keys of alterado = { base, or_gravedad }: TOML key → field. Both are required.
_ABNORMAL_KEYS = {"base": "abnormal_pct", "or_gravedad": "abnormal_severity_or"}

# Keys of [poblacion]: TOML key → field.
_POPULATION_REQUIRED = {
    "bandas_edad": "band_starts",
    "reparto_edad": "band_shares",
    "mujeres": "female_pct",
    "ambulancia": "ambulance_pct",
}
_POPULATION_OPTIONAL = {"franja": "band_shift_factors", "dia": "band_day_factors"}

_SECTIONS = ("contexto", "poblacion", "motivos", "triaje", "duraciones", "pruebas")


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


def _check_open_percentage(key: str, value: object) -> float:
    """A percentage in (0, 100), both ends excluded: its logit must exist."""
    x = check_number(key, value)
    if not 0 < x < 100:
        raise ValueError(f"{key} must be between 0 and 100 (excluded), got {value!r}")
    return x


def _check_median_p90(key: str, values: object) -> tuple[float, float]:
    """``[mediana, p90]`` of a lognormal, in minutes: median > 0 and p90 > median."""
    median, p90 = (check_number(f"{key}[{i}]", x) for i, x in enumerate(check_list(key, values, 2)))
    if median <= 0:
        raise ValueError(f"{key}[0] (the median) must be positive, got {values[0]!r}")
    if p90 <= median:
        raise ValueError(
            f"{key}[1] (the p90) must be greater than the median, got {values[1]!r} <= "
            f"{values[0]!r}"
        )
    return median, p90


def _check_numbers(key: str, values: object, n: int) -> tuple[float, ...]:
    """``n`` finite numbers."""
    return tuple(check_number(f"{key}[{i}]", x) for i, x in enumerate(check_list(key, values, n)))


@dataclass(frozen=True, slots=True)
class Severity:
    """Latent severity of the patients of one reason, from its ``gravedad`` table.

    A patient of band ``b`` with a standard normal draw ``z`` has severity
    ``G = mean + age_shift[b] + sd * z``, in standard deviations of the
    reference population: 0 is the mean adult and more is more severe.

    Attributes:
        mean: Mean severity of the reason (``media``), in band 45-64 if the
            shifts are written that way; any finite number.
        sd: Standard deviation (``desviacion``); positive.
        age_shift: Shift of the mean per age band (``por_edad``); 0 if absent.
    """

    mean: float
    sd: float
    age_shift: tuple[float, ...] = (0.0,) * N_BANDS

    def __post_init__(self) -> None:
        object.__setattr__(self, "mean", check_number("gravedad.media", self.mean))
        object.__setattr__(self, "sd", _check_positive("gravedad.desviacion", self.sd))
        object.__setattr__(
            self, "age_shift", _check_numbers("gravedad.por_edad", self.age_shift, N_BANDS)
        )


@dataclass(frozen=True, slots=True)
class TriageProfile:
    """The triage of the nurse, from ``[triaje]``.

    The assigned level cuts ``G + bias + noise * z`` with the thresholds and
    the true level cuts ``G``; see ``edsim.profiles.severity``.

    Attributes:
        target_pct: Target percentage of each assigned level, 1 to 5
            (``reparto_objetivo``), as written; they add up to 100 within
            ``TARGET_SUM_TOLERANCE``. Calibrated.
        under_pct: Target percentage of undertriage (``infratriaje``), in
            (0, 100). Calibrated.
        over_pct: Target percentage of overtriage (``sobretriaje``).
        noise: Standard deviation of the nurse's error (``ruido``), in units
            of G; positive. Calibrated with ``triage_error_for``.
        bias: Mean of the error (``sesgo``); negative tends to undertriage.
            Calibrated with ``triage_error_for``.
        thresholds: The four thresholds c1 > c2 > c3 > c4 (``umbrales``),
            stored as written. Derived with ``thresholds_for``.
        duration: ``[mediana, p90]`` of the triage in minutes (``duracion``),
            one lognormal for levels 2 to 5. Drawn for every patient; a level
            1, classified at the door, does not use it. Orientative.
    """

    target_pct: tuple[float, ...]
    under_pct: float
    over_pct: float
    noise: float
    bias: float
    thresholds: tuple[float, ...]
    duration: tuple[float, float]

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        target = _check_percentages("triaje.reparto_objetivo", self.target_pct, N_LEVELS)
        if abs(sum(target) - 100) > TARGET_SUM_TOLERANCE:
            raise ValueError(
                f"triaje.reparto_objetivo must add up to 100 (within "
                f"{TARGET_SUM_TOLERANCE}), got {sum(target):g}"
            )
        set_(self, "target_pct", target)
        for key, field in (("infratriaje", "under_pct"), ("sobretriaje", "over_pct")):
            x = check_number(f"triaje.{key}", getattr(self, field))
            if not 0 < x < 100:
                raise ValueError(f"triaje.{key} must be between 0 and 100 (excluded), got {x!r}")
            set_(self, field, x)
        set_(self, "noise", _check_positive("triaje.ruido", self.noise))
        set_(self, "bias", check_number("triaje.sesgo", self.bias))
        thresholds = _check_numbers("triaje.umbrales", self.thresholds, N_THRESHOLDS)
        if any(a <= b for a, b in pairwise(thresholds)):
            raise ValueError(
                f"triaje.umbrales must be strictly decreasing, got {list(thresholds)!r}"
            )
        set_(self, "thresholds", thresholds)
        set_(self, "duration", _check_median_p90("triaje.duracion", self.duration))

    @property
    def target_shares(self) -> tuple[float, ...]:
        """The target mix of assigned levels, normalized to add up to 1."""
        total = sum(self.target_pct)
        return tuple(x / total for x in self.target_pct)


@dataclass(frozen=True, slots=True)
class DurationProfile:
    """The durations of the doctor, from ``[duraciones]``.

    Each is a lognormal per true level, given by ``[mediana, p90]`` in
    minutes; the reason multiplies the median by its ``duracion`` factor (see
    ``edsim.profiles.durations``). Orientative, and fixed during the
    calibration of milestone 4 (ADR candidate 41).

    Attributes:
        assessment: ``[mediana, p90]`` of the first assessment for true levels
            1 to 5 (``valoracion``).
        reassessment: Same for the reassessment after the tests
            (``reevaluacion``).
    """

    assessment: tuple[tuple[float, float], ...]
    reassessment: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        for toml_key, field in _DURATION_KEYS.items():
            key = f"duraciones.{toml_key}"
            pairs = tuple(
                _check_median_p90(f"{key}[{i}]", pair)
                for i, pair in enumerate(check_list(key, getattr(self, field), N_LEVELS))
            )
            object.__setattr__(self, field, pairs)


@dataclass(frozen=True, slots=True)
class DiagnosticTest:
    """One type of test, from its ``[pruebas.<tipo>]`` table.

    Named ``DiagnosticTest`` and not ``Test...``: pytest tries to collect every
    class called ``Test*`` that a test module imports.

    The probability of ordering it for a patient of reason m is a logistic of
    ``logit(p_m) + ln(severity_or) * G + ln(older_or) * older``, and the
    probability of an abnormal result, ``logit(abnormal_pct) +
    ln(abnormal_severity_or) * G`` (see ``edsim.profiles.workup``).

    Attributes:
        key: The type, one of ``TEST_TYPES``.
        turnaround: ``[mediana, p90]`` in minutes from ordering to the result
            (``respuesta``).
        severity_or: Odds ratio of ordering it per unit of G (``or_gravedad``);
            positive.
        abnormal_pct: Percentage of abnormal results at G = 0
            (``alterado.base``), in (0, 100).
        abnormal_severity_or: Odds ratio of an abnormal result per unit of G
            (``alterado.or_gravedad``); positive.
        turnaround_shift_factors: Factor on the median of the turnaround in
            the morning, afternoon and night bands of the order
            (``respuesta_franja``); 1 if absent.
        older_or: Odds ratio of ordering it for a patient of 65 or more
            (``or_mayor``); 1 if absent.
    """

    key: str
    turnaround: tuple[float, float]
    severity_or: float
    abnormal_pct: float
    abnormal_severity_or: float
    turnaround_shift_factors: tuple[float, ...] = (1.0,) * N_SHIFT_BANDS
    older_or: float = 1.0

    def __post_init__(self) -> None:
        if self.key not in TEST_TYPES:
            raise ValueError(f"the type of a test must be one of {TEST_TYPES}, got {self.key!r}")
        prefix = f"pruebas.{self.key}"
        set_ = object.__setattr__
        set_(self, "turnaround", _check_median_p90(f"{prefix}.respuesta", self.turnaround))
        set_(self, "severity_or", _check_positive(f"{prefix}.or_gravedad", self.severity_or))
        set_(
            self,
            "abnormal_pct",
            _check_open_percentage(f"{prefix}.alterado.base", self.abnormal_pct),
        )
        set_(
            self,
            "abnormal_severity_or",
            _check_positive(f"{prefix}.alterado.or_gravedad", self.abnormal_severity_or),
        )
        set_(
            self,
            "turnaround_shift_factors",
            _check_factors(
                f"{prefix}.respuesta_franja", self.turnaround_shift_factors, N_SHIFT_BANDS
            ),
        )
        set_(self, "older_or", _check_positive(f"{prefix}.or_mayor", self.older_or))


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
        severity: Latent severity of its patients (``gravedad``).
        test_pct: Percentage of each type of test, in the order of
            ``TEST_TYPES``, for an adult under 65 with G = 0 (``pruebas``); each
            in (0, 100). Not the share of the reason's typical patient: that is
            higher when the reason is more severe than the mean adult.
        age_factors: Factor per age band (``edad``); 1 if absent.
        shift_factors: Factor per shift band: morning, afternoon, night
            (``franja``).
        day_factors: Factor per day type: weekday, weekend (``dia``).
        season_factors: Factor per season: winter, spring, summer, autumn
            (``estacion``).
        duration_factor: Factor on the median of the assessment and the
            reassessment of its patients (``duracion``); positive, 1 if absent.
    """

    key: str
    name: str
    base_weight: float
    severity: Severity
    test_pct: tuple[float, ...]
    age_factors: tuple[float, ...] = (1.0,) * N_BANDS
    shift_factors: tuple[float, ...] = (1.0,) * N_SHIFT_BANDS
    day_factors: tuple[float, ...] = (1.0,) * N_DAY_TYPES
    season_factors: tuple[float, ...] = (1.0,) * N_SEASONS
    duration_factor: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not self.key:
            raise ValueError(f"the key of a reason must be a non-empty string, got {self.key!r}")
        prefix = f"motivos.{self.key}"
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError(f"{prefix}.nombre must be a non-empty string, got {self.name!r}")
        object.__setattr__(
            self, "base_weight", _check_positive(f"{prefix}.peso_base", self.base_weight)
        )
        if not isinstance(self.severity, Severity):
            raise ValueError(f"{prefix}.gravedad must be a Severity, got {self.severity!r}")
        for toml_key, (field, n) in _REASON_FACTORS.items():
            checked = _check_factors(f"{prefix}.{toml_key}", getattr(self, field), n)
            object.__setattr__(self, field, checked)
        pct = check_list(f"{prefix}.pruebas", self.test_pct, N_TEST_TYPES)
        object.__setattr__(
            self,
            "test_pct",
            tuple(
                _check_open_percentage(f"{prefix}.pruebas.{t}", x)
                for t, x in zip(TEST_TYPES, pct, strict=True)
            ),
        )
        object.__setattr__(
            self, "duration_factor", _check_positive(f"{prefix}.duracion", self.duration_factor)
        )


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


def _check_tests(tests: object) -> tuple[DiagnosticTest, ...]:
    """The 4 types of test, each once, in the order of ``TEST_TYPES``."""
    if not isinstance(tests, Iterable) or isinstance(tests, str | Mapping):
        raise ValueError(f"diagnostic_tests must be a sequence of DiagnosticTest, got {tests!r}")
    tests = list(tests)
    for t in tests:
        if not isinstance(t, DiagnosticTest):
            raise ValueError(f"each test must be a DiagnosticTest, got {t!r}")
    keys = [t.key for t in tests]
    duplicates = sorted({k for k in keys if keys.count(k) > 1})
    if duplicates:
        raise ValueError(f"duplicate keys: {', '.join(f'pruebas.{k}' for k in duplicates)}")
    problems = _problems(*_missing_and_unknown("pruebas", keys, TEST_TYPES))
    if problems:
        raise ValueError("; ".join(problems))
    by_key = {t.key: t for t in tests}
    return tuple(by_key[k] for k in TEST_TYPES)


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
        triage: The triage of the nurse (``[triaje]``).
        durations: The assessment and reassessment per true level
            (``[duraciones]``).
        diagnostic_tests: The 4 types of test (``[pruebas.<tipo>]``), in the
            order of ``TEST_TYPES``, whatever their order in the file.
    """

    shift_band_starts: tuple[int, ...]
    population: Population
    reasons: tuple[ReasonProfile, ...]
    triage: TriageProfile
    durations: DurationProfile
    diagnostic_tests: tuple[DiagnosticTest, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "shift_band_starts", _check_hours("contexto.franjas", self.shift_band_starts)
        )
        if not isinstance(self.population, Population):
            raise ValueError(f"population must be a Population, got {self.population!r}")
        object.__setattr__(self, "reasons", _check_reasons(self.reasons))
        if not isinstance(self.triage, TriageProfile):
            raise ValueError(f"triage must be a TriageProfile, got {self.triage!r}")
        if not isinstance(self.durations, DurationProfile):
            raise ValueError(f"durations must be a DurationProfile, got {self.durations!r}")
        object.__setattr__(self, "diagnostic_tests", _check_tests(self.diagnostic_tests))

    @property
    def reason_keys(self) -> tuple[str, ...]:
        """Keys of the reasons, in the order of the catalog."""
        return tuple(r.key for r in self.reasons)

    def diagnostic_test(self, key: str) -> DiagnosticTest:
        """The parameters of one type of test, by its key, one of ``TEST_TYPES``.

        Raises:
            KeyError: If there is no type of test with that key.
        """
        for t in self.diagnostic_tests:
            if t.key == key:
                return t
        raise KeyError(key)

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
                    _missing_and_unknown(
                        f"motivos.{key}",
                        table,
                        _REASON_REQUIRED,
                        (*_REASON_FACTORS, *_REASON_OPTIONAL),
                    )
                )
                if "gravedad" in table:
                    prefix = f"motivos.{key}.gravedad"
                    severity = _check_table(prefix, table["gravedad"])
                    add(
                        _missing_and_unknown(
                            prefix, severity, _SEVERITY_REQUIRED, _SEVERITY_OPTIONAL
                        )
                    )
                if "pruebas" in table:
                    prefix = f"motivos.{key}.pruebas"
                    add(
                        _missing_and_unknown(
                            prefix, _check_table(prefix, table["pruebas"]), TEST_TYPES
                        )
                    )
    if "triaje" in data:
        add(_missing_and_unknown("triaje", _check_table("triaje", data["triaje"]), _TRIAGE_KEYS))
    if "duraciones" in data:
        add(
            _missing_and_unknown(
                "duraciones", _check_table("duraciones", data["duraciones"]), _DURATION_KEYS
            )
        )
    if "pruebas" in data:
        tests = _check_table("pruebas", data["pruebas"])
        add(_missing_and_unknown("pruebas", tests, TEST_TYPES))
        for key in TEST_TYPES:
            if key in tests:
                prefix = f"pruebas.{key}"
                table = _check_table(prefix, tests[key])
                add(_missing_and_unknown(prefix, table, _TEST_REQUIRED, _TEST_OPTIONAL))
                if "alterado" in table:
                    sub = f"{prefix}.alterado"
                    add(
                        _missing_and_unknown(
                            sub, _check_table(sub, table["alterado"]), _ABNORMAL_KEYS
                        )
                    )
    return _problems(missing, unknown)


def load_profiles(path: str | Path) -> ClinicalProfiles:
    """Load the clinical profiles from a TOML file.

    The file must have the tables ``[contexto]``, ``[poblacion]``,
    ``[triaje]``, ``[duraciones]``, one ``[pruebas.<tipo>]`` for each of
    ``TEST_TYPES`` and one ``[motivos.<clave>]`` for each of the 17 reasons of
    ``REASON_KEYS``, each with its ``gravedad`` and its ``pruebas``. The
    factors are optional and worth 1 when absent, as ``por_edad`` is worth 0;
    any other key is an error. The thresholds are read as written, never
    recomputed.

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

    def severity(key: str) -> Severity:
        table = reasons[key]["gravedad"]
        fields = {**_SEVERITY_REQUIRED, **_SEVERITY_OPTIONAL}
        try:
            return Severity(**{field: table[k] for k, field in fields.items() if k in table})
        except ValueError as error:
            raise ValueError(f"{path}: motivos.{key}.{error}") from None

    def diagnostic_test(key: str) -> DiagnosticTest:
        table = data["pruebas"][key]
        abnormal = table["alterado"]
        try:
            return DiagnosticTest(
                key=key,
                **{field: table[k] for k, field in _TEST_REQUIRED.items() if field},
                **{field: abnormal[k] for k, field in _ABNORMAL_KEYS.items()},
                **{field: table[k] for k, field in _TEST_OPTIONAL.items() if k in table},
            )
        except ValueError as error:
            raise ValueError(f"{path}: {error}") from None

    def reason(key: str) -> ReasonProfile:
        table = reasons[key]
        try:
            return ReasonProfile(
                key=key,
                name=table["nombre"],
                base_weight=table["peso_base"],
                severity=severity(key),
                test_pct=tuple(table["pruebas"][t] for t in TEST_TYPES),
                **{
                    field: table[toml_key]
                    for toml_key, (field, _) in _REASON_FACTORS.items()
                    if toml_key in table
                },
                **({"duration_factor": table["duracion"]} if "duracion" in table else {}),
            )
        except ValueError as error:
            if str(error).startswith(str(path)):
                raise
            raise ValueError(f"{path}: {error}") from None

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
        reasons=tuple(reason(key) for key in REASON_KEYS),
        triage=TriageProfile(**{field: data["triaje"][k] for k, field in _TRIAGE_KEYS.items()}),
        durations=DurationProfile(
            **{field: data["duraciones"][k] for k, field in _DURATION_KEYS.items()}
        ),
        diagnostic_tests=tuple(diagnostic_test(key) for key in TEST_TYPES),
    )
