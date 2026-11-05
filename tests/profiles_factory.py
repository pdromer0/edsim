"""Perfiles clínicos construidos a mano para los tests, sin TOML.

``make_profiles`` parte de los pesos del catálogo como pesos base y de todos los
factores en 1; cada test escribe solo los factores que necesita, de modo que el
valor esperado se puede calcular a mano.

La gravedad por defecto es normal estándar en todos los motivos (media 0,
desviación 1 y sin ajuste por edad), de modo que la mezcla de un año también lo
es, sean cuales sean los pesos: es el modelo de la especificación, con ruido
0,32 y sesgo −0,08. Los umbrales de ``TRIAGE`` son orientativos; los tests que los
necesitan exactos los calculan con ``thresholds_for``.
"""

from datetime import date

from edsim.profiles.config import (
    REASONS,
    ClinicalProfiles,
    Population,
    ReasonProfile,
    Severity,
    TriageProfile,
)

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


STANDARD = Severity(mean=0.0, sd=1.0)

TRIAGE = TriageProfile(
    target_pct=(0.4, 12.1, 33.6, 52.6, 1.4),  # adultos de Emergencias 2013 (suma 100,1)
    under_pct=10.1,
    over_pct=6.3,
    noise=0.32,
    bias=-0.08,
    thresholds=(2.70, 1.13, 0.02, -2.42),  # orientativos, cerca de los exactos
)


def make_profiles(
    factors: dict[str, dict[str, tuple[float, ...]]] | None = None,
    *,
    base_weights: dict[str, float] | None = None,
    severity: dict[str, Severity] | None = None,
    population: Population = POPULATION,
    shift_band_starts: tuple[int, ...] = (8, 15, 22),
    triage: TriageProfile = TRIAGE,
) -> ClinicalProfiles:
    """Profiles with the catalog weights and only the given factors.

    ``factors`` maps a reason key to its fields, such as
    ``{"disnea": {"age_factors": (1, 1, 1, 2.4)}}``; ``base_weights`` replaces
    some base weights and ``severity`` some severities (standard normal by
    default).
    """
    factors = factors or {}
    base_weights = base_weights or {}
    severity = severity or {}
    reasons = tuple(
        ReasonProfile(
            key=key,
            name=name,
            base_weight=base_weights.get(key, weight),
            severity=severity.get(key, STANDARD),
            **factors.get(key, {}),
        )
        for key, name, weight in REASONS
    )
    return ClinicalProfiles(
        shift_band_starts=shift_band_starts,
        population=population,
        reasons=reasons,
        triage=triage,
    )


def t_at(when: date, hour: int, minute: int = 0) -> float:
    """Minutes since 00:00 of ``START`` at ``hour:minute`` of ``when``."""
    return float((when - START).days * DAY + 60 * hour + minute)
