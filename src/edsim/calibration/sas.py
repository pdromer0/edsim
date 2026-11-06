"""Observed figures of the SAS, Andalusian Health Service, used apart from the targets.

The calibration targets live in ``config/objetivos.toml``. These are the other
figures of the same source that the notebooks and the variants of the
profiles use: the triage mix by level and the time to the doctor (TPAM) by
level, from the report of the minimum basic data set of emergencies of 2013
(CMBD 2013; the link of ``config/objetivos.toml``).

The SAS counts include patients under 15 years old, and EDsim simulates only
adults (ADR candidate 35). ``adult_level_counts`` removes the under-15s of
each level with the share of minors that the report gives for that level, and
``level_pct`` turns any counts into percentages: a target is always converted
to the population that is simulated before using it.
"""

from collections.abc import Sequence

from edsim.checks import check_number

SOURCE = "SAS, Urgencias hospitalarias en el Servicio Andaluz de Salud, CMBD 2013"
"""The report the figures come from."""

LINK = (
    "https://www.sspa.juntadeandalucia.es/servicioandaluzdesalud/sites/default/files/"
    "sincfiles/wsas-media-pdf_publicacion/2020/"
    "UrgenciasHospitalariasenelServicioAndaluzdeSalud.CMBD2013_0.pdf"
)
"""The link of ``config/objetivos.toml``."""

LEVEL_COUNTS: tuple[int, ...] = (30_457, 208_635, 989_622, 1_312_906, 731_808)
"""Emergencies of 2013 by triage level, 1 to 5, of all ages (page 30)."""

MINOR_PCT: tuple[float, ...] = (2.65, 9.60, 10.38, 23.78, 35.90)
"""Percentage of each level's emergencies that are under 15 years old (page 30)."""

TPAM_BY_LEVEL: tuple[float, ...] = (31.7, 35.6, 59.0, 59.8, 68.5)
"""Mean minutes from the arrival to the first doctor (TPAM, clock A) by assigned
triage level, 1 to 5, of all ages."""

TPAM_TOTAL = 59.7
"""Mean TPAM of all the levels, of all ages, in minutes."""


def _check_levels(name: str, values: Sequence[float]) -> tuple[float, ...]:
    values = tuple(check_number(f"{name}[{i}]", x) for i, x in enumerate(values))
    if len(values) != len(LEVEL_COUNTS):
        raise ValueError(f"{name} must have {len(LEVEL_COUNTS)} values, got {len(values)}")
    return values


def adult_level_counts(
    counts: Sequence[float] = LEVEL_COUNTS, minor_pct: Sequence[float] = MINOR_PCT
) -> tuple[float, ...]:
    """The emergencies of adults of each level: the count times ``1 - minors / 100``.

    The share of minors differs by level (2.65 % in level 1, 35.90 % in level
    5), so the adult mix is not the mix of all ages minus a constant.

    Raises:
        ValueError: If a count is negative or a percentage is outside [0, 100].
    """
    counts = _check_levels("counts", counts)
    minor_pct = _check_levels("minor_pct", minor_pct)
    if any(c < 0 for c in counts):
        raise ValueError(f"counts must be non-negative, got {counts}")
    if any(not 0 <= m <= 100 for m in minor_pct):
        raise ValueError(f"minor_pct must be in [0, 100], got {minor_pct}")
    return tuple(c * (1 - m / 100) for c, m in zip(counts, minor_pct, strict=True))


def level_pct(counts: Sequence[float]) -> tuple[float, ...]:
    """Percentage of each level over the total of ``counts``; they add up to 100.

    Raises:
        ValueError: If a count is negative or the total is not positive.
    """
    counts = _check_levels("counts", counts)
    total = sum(counts)
    if any(c < 0 for c in counts) or not total > 0:
        raise ValueError(f"counts must be non-negative with a positive total, got {counts}")
    return tuple(100 * c / total for c in counts)
