"""Perfiles clínicos construidos a mano para los tests, sin TOML.

``make_profiles`` parte de los pesos del catálogo como pesos base y de todos los
factores en 1; cada test escribe solo los factores que necesita, de modo que el
valor esperado se puede calcular a mano.
"""

from datetime import date

from edsim.profiles.config import REASONS, ClinicalProfiles, Population, ReasonProfile

START = date(2026, 1, 5)  # fecha_inicio de los perfiles de llegadas: un lunes
DAY = 1440

POPULATION = Population(
    band_starts=(15, 45, 65, 80),
    band_shares=(38, 22, 22, 18),
    female_pct=(50, 50, 55, 62),
    ambulance_pct=(6, 10, 21, 34),
    band_shift_factors=((1, 1, 1.3), (1, 1, 1), (1, 1, 1), (1, 1, 1)),
    band_day_factors=((1, 1.15), (1, 1), (1, 1), (1, 1)),
)


def make_profiles(
    factors: dict[str, dict[str, tuple[float, ...]]] | None = None,
    *,
    base_weights: dict[str, float] | None = None,
    population: Population = POPULATION,
    shift_band_starts: tuple[int, ...] = (8, 15, 22),
) -> ClinicalProfiles:
    """Profiles with the catalog weights and only the given factors.

    ``factors`` maps a reason key to its fields, such as
    ``{"disnea": {"age_factors": (1, 1, 1, 2.4)}}``; ``base_weights`` replaces
    some base weights.
    """
    factors = factors or {}
    base_weights = base_weights or {}
    reasons = tuple(
        ReasonProfile(
            key=key, name=name, base_weight=base_weights.get(key, weight), **factors.get(key, {})
        )
        for key, name, weight in REASONS
    )
    return ClinicalProfiles(
        shift_band_starts=shift_band_starts, population=population, reasons=reasons
    )


def t_at(when: date, hour: int, minute: int = 0) -> float:
    """Minutes since 00:00 of ``START`` at ``hour:minute`` of ``when``."""
    return float((when - START).days * DAY + 60 * hour + minute)
