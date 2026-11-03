"""Deterministic clinical previews for a raw center editor."""

import math
from collections.abc import Mapping
from dataclasses import dataclass

from edsim.engine.center import center_from_values
from edsim.engine.clinical import lognormal_params


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
