"""Perfiles clínicos construidos a mano para los tests, sin TOML.

``make_profiles`` parte de los pesos del catálogo como pesos base y de todos los
factores en 1; cada test escribe solo los factores que necesita, de modo que el
valor esperado se puede calcular a mano.

La gravedad por defecto es normal estándar en todos los motivos (media 0,
desviación 1 y sin ajuste por edad), de modo que la mezcla de un año también lo
es, sean cuales sean los pesos: es el modelo de la especificación, con ruido
0,32 y sesgo −0,08. Los umbrales de ``TRIAGE`` son orientativos; los tests que los
necesitan exactos los calculan con ``thresholds_for``.

Las pruebas y las duraciones por defecto son las de la especificación (las de
``config/perfiles.toml`` para los tipos de prueba y los niveles), con un 40 % de
cada prueba en todos los motivos y sin factor de duración.
"""

from datetime import date

from edsim.profiles.config import (
    REASONS,
    ClinicalProfiles,
    DiagnosticTest,
    DurationProfile,
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
    duration=(5, 10),
)

DURATIONS = DurationProfile(
    assessment=((40, 90), (30, 70), (22, 50), (15, 35), (10, 25)),
    reassessment=((15, 30), (12, 25), (10, 20), (8, 15), (6, 12)),
)

DIAGNOSTIC_TESTS = (
    DiagnosticTest(
        key="analitica",
        turnaround=(60, 150),
        turnaround_shift_factors=(1.0, 1.1, 0.9),
        severity_or=3.3,
        older_or=2.2,
        abnormal_pct=30,
        abnormal_severity_or=2.5,
    ),
    DiagnosticTest(
        key="radiografia",
        turnaround=(30, 75),
        turnaround_shift_factors=(1.0, 1.0, 1.2),
        severity_or=1.5,
        older_or=1.8,
        abnormal_pct=25,
        abnormal_severity_or=2.0,
    ),
    DiagnosticTest(
        key="ecg",
        turnaround=(10, 25),
        severity_or=2.0,
        older_or=3.0,
        abnormal_pct=20,
        abnormal_severity_or=2.0,
    ),
    DiagnosticTest(
        key="imagen",
        turnaround=(100, 240),
        turnaround_shift_factors=(1.0, 1.1, 1.3),
        severity_or=2.0,
        older_or=1.8,
        abnormal_pct=35,
        abnormal_severity_or=2.0,
    ),
)

TEST_PCT = (40.0, 40.0, 40.0, 40.0)


def make_profiles(
    factors: dict[str, dict[str, tuple[float, ...]]] | None = None,
    *,
    base_weights: dict[str, float] | None = None,
    severity: dict[str, Severity] | None = None,
    population: Population = POPULATION,
    shift_band_starts: tuple[int, ...] = (8, 15, 22),
    triage: TriageProfile = TRIAGE,
    durations: DurationProfile = DURATIONS,
    diagnostic_tests: tuple[DiagnosticTest, ...] = DIAGNOSTIC_TESTS,
    test_pct: dict[str, tuple[float, ...]] | None = None,
) -> ClinicalProfiles:
    """Profiles with the catalog weights and only the given factors.

    ``factors`` maps a reason key to its fields, such as
    ``{"disnea": {"age_factors": (1, 1, 1, 2.4)}}`` or ``{"disnea":
    {"duration_factor": 1.2}}``; ``base_weights`` replaces some base weights,
    ``severity`` some severities (standard normal by default) and ``test_pct``
    the percentages of tests of some reasons (``TEST_PCT`` by default).
    """
    factors = factors or {}
    base_weights = base_weights or {}
    severity = severity or {}
    test_pct = test_pct or {}
    reasons = tuple(
        ReasonProfile(
            key=key,
            name=name,
            base_weight=base_weights.get(key, weight),
            severity=severity.get(key, STANDARD),
            test_pct=test_pct.get(key, TEST_PCT),
            **factors.get(key, {}),
        )
        for key, name, weight in REASONS
    )
    return ClinicalProfiles(
        shift_band_starts=shift_band_starts,
        population=population,
        reasons=reasons,
        triage=triage,
        durations=durations,
        diagnostic_tests=diagnostic_tests,
    )


def t_at(when: date, hour: int, minute: int = 0) -> float:
    """Minutes since 00:00 of ``START`` at ``hour:minute`` of ``when``."""
    return float((when - START).days * DAY + 60 * hour + minute)
