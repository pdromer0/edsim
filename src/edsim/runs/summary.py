"""Deterministic clinical previews: a raw center editor and clinical profiles."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from edsim.arrivals.profile import ArrivalProfile
from edsim.engine.center import center_from_values
from edsim.engine.clinical import lognormal_params
from edsim.profiles.config import REASON_KEYS, TEST_TYPES, ClinicalProfiles
from edsim.profiles.durations import physician_load
from edsim.profiles.mixing import global_reason_shares
from edsim.profiles.severity import (
    assigned_shares,
    real_shares,
    severity_mixture,
    triage_error_rates,
    triage_matrix,
)
from edsim.profiles.workup import workup_model


@dataclass(frozen=True, slots=True)
class DurationSummary:
    """Mean and density points of a duration, identified by its TOML key."""

    key: str
    mean_minutes: float
    curve_minutes: tuple[float, ...]
    curve_density: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class CenterSummary:
    """Derived values; global percentages are on a scale from 0 to 100."""

    raw_share_total: float
    normalized_level_shares: tuple[float, ...]
    durations: tuple[DurationSummary, ...]
    tests_percentage: float
    admission_percentage: float


def summarize_center(values: Mapping[str, object]) -> CenterSummary:
    """Validate raw values and summarize them without changing the input.

    Raise ValueError on invalid values. Each curve contains the origin and
    121 log-spaced points over mu ± 3 sigma, including the median.
    """
    center = center_from_values(values)
    durations = []
    for key, parameters in (
        ("duraciones.triaje", center.triage_time),
        ("duraciones.valoracion", center.assessment_time),
        ("duraciones.reevaluacion", center.reassessment_time),
        ("duraciones.respuesta_pruebas", center.test_turnaround),
    ):
        mu, sigma = lognormal_params(*parameters)
        z = tuple(-3 + i / 20 for i in range(121))
        minutes = tuple(math.exp(mu + x * sigma) for x in z)
        density = tuple(
            math.exp(-x * x / 2) / (t * sigma * math.sqrt(2 * math.pi))
            for x, t in zip(z, minutes, strict=True)
        )
        durations.append(
            DurationSummary(key, math.exp(mu + sigma * sigma / 2), (0.0, *minutes), (0.0, *density))
        )
    return CenterSummary(
        raw_share_total=sum(values["triaje.reparto_niveles"]),
        normalized_level_shares=center.level_shares,
        durations=tuple(durations),
        tests_percentage=100
        * sum(s * p for s, p in zip(center.level_shares, center.test_probability, strict=True)),
        admission_percentage=100
        * sum(
            s * p for s, p in zip(center.level_shares, center.admission_probability, strict=True)
        ),
    )


@dataclass(frozen=True, slots=True)
class ProfilesSummary:
    """What a year of patients of some clinical profiles is expected to be, exactly.

    Percentages are on a scale from 0 to 100, over the patients of a year of
    the arrival profile; minutes are per patient. ``reason_percentages`` and
    ``test_percentages`` follow the order of ``REASON_KEYS`` and ``TEST_TYPES``.
    Levels are 1 to 5, assigned (what the hospital sees) and true (the ground
    truth). ``reassessment_minutes`` counts only the patients with a round of
    tests, so ``physician_minutes`` is ``assessment_minutes`` plus it.
    """

    reason_percentages: Mapping[str, float]
    assigned_level_percentages: tuple[float, ...]
    true_level_percentages: tuple[float, ...]
    undertriage_percentage: float
    overtriage_percentage: float
    any_test_percentage: float
    test_percentages: Mapping[str, float]
    assessment_minutes: float
    reassessment_minutes: float
    physician_minutes: float


def summarize_profiles(profiles: ClinicalProfiles, arrivals: ArrivalProfile) -> ProfilesSummary:
    """Summarize clinical profiles over a year of an arrival profile, without sampling.

    The same exact functions as ``perfiles validar`` and notebook 04: the
    reason mix of the year (``global_reason_shares``), the assigned and true
    levels and the under and overtriage from the mixture of G with the written
    thresholds, noise and bias, the tests from ``workup_model`` and the load
    of the doctor from ``physician_load``.
    """
    mixture = severity_mixture(profiles, arrivals)
    triage = profiles.triage
    assigned = assigned_shares(mixture, triage.thresholds, triage.noise, triage.bias)
    true = real_shares(mixture, triage.thresholds)
    under, over = triage_error_rates(
        triage_matrix(mixture, triage.thresholds, triage.noise, triage.bias)
    )
    workup = workup_model(profiles, arrivals)
    load = physician_load(profiles, arrivals)
    reasons = global_reason_shares(profiles, arrivals)
    return ProfilesSummary(
        reason_percentages=MappingProxyType(
            {key: 100 * float(share) for key, share in zip(REASON_KEYS, reasons, strict=True)}
        ),
        assigned_level_percentages=tuple(100 * float(x) for x in assigned),
        true_level_percentages=tuple(100 * float(x) for x in true),
        undertriage_percentage=100 * under,
        overtriage_percentage=100 * over,
        any_test_percentage=100 * workup.any_test_share(),
        test_percentages=MappingProxyType(
            {
                key: 100 * float(share)
                for key, share in zip(TEST_TYPES, workup.order_shares(), strict=True)
            }
        ),
        assessment_minutes=load.assessment,
        reassessment_minutes=load.reassessment_with_tests,
        physician_minutes=load.load,
    )
