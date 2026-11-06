"""Cascada de valores derivados de perfiles.toml y criterio de la gravedad de un motivo.

Los valores a mano se calculan aparte, con ``scipy.stats.norm`` y ``reason_band_mass``,
no con las funciones que se prueban (tarea 4.6a).
"""

import math
from pathlib import Path

import numpy as np
import pytest
from scipy import stats

from edsim.arrivals.profile import load_profile
from edsim.profiles.config import REASON_KEYS, REASONS, load_profiles
from edsim.profiles.derivation import (
    derive_written_values,
    reason_level1_shares,
    severity_mean_for,
    with_derived,
    with_severity,
)
from edsim.profiles.mixing import reason_band_mass

ROOT = Path(__file__).parents[1]
FILES = pytest.mark.parametrize(
    ("profiles_path", "arrivals_path"),
    [
        (ROOT / "tests/data/perfiles_ejemplo.toml", ROOT / "tests/data/llegadas_ejemplo.toml"),
        (ROOT / "config/perfiles.toml", ROOT / "config/llegadas.toml"),
    ],
    ids=["ejemplo", "real"],
)
PARADA = REASON_KEYS.index("parada")


@pytest.fixture(scope="module")
def real():
    return load_profiles(ROOT / "config/perfiles.toml"), load_profile(ROOT / "config/llegadas.toml")


@FILES
def test_la_cascada_reproduce_lo_escrito(profiles_path, arrivals_path):
    """Pesos, ruido, sesgo y umbrales escritos son la cascada redondeada a 3 decimales."""
    profiles = load_profiles(profiles_path)
    derived = derive_written_values(profiles, load_profile(arrivals_path))

    assert dict(derived.base_weights) == {r.key: r.base_weight for r in profiles.reasons}
    assert list(derived.base_weights) == list(REASON_KEYS)
    assert (derived.noise, derived.bias) == (profiles.triage.noise, profiles.triage.bias)
    assert derived.thresholds == profiles.triage.thresholds


def test_la_cascada_no_depende_de_lo_ya_derivado(real):
    """Con otros pesos, ruido, sesgo y umbrales de partida, la cascada da lo mismo."""
    profiles, arrivals = real
    derived = derive_written_values(profiles, arrivals)
    scrambled = with_derived(
        profiles,
        type(derived)(
            {k: 1.0 for k in REASON_KEYS}, 0.9, 0.3, tuple(c + 0.5 for c in derived.thresholds)
        ),
    )
    assert derive_written_values(scrambled, arrivals) == derived


def test_cuotas_de_nivel_1_de_un_motivo_sin_edad_a_mano(real):
    """La parada no depende de la edad: una sola normal, Φ a mano."""
    profiles, arrivals = real
    severity = profiles.reason("parada").severity
    t = profiles.triage
    c1 = t.thresholds[0]

    real_share, assigned = reason_level1_shares(profiles, arrivals, "parada")

    assert real_share == pytest.approx(
        stats.norm.cdf((severity.mean - c1) / severity.sd), abs=1e-12
    )
    assert assigned == pytest.approx(
        stats.norm.cdf((severity.mean + t.bias - c1) / math.hypot(severity.sd, t.noise)),
        abs=1e-12,
    )


def test_cuotas_de_nivel_1_de_un_motivo_con_edad(real):
    """La disnea mezcla sus cuatro bandas con los pesos de un año de reason_band_mass."""
    profiles, arrivals = real
    disnea = profiles.reason("disnea")
    weights = reason_band_mass(profiles, arrivals)[REASON_KEYS.index("disnea")]
    weights = weights / weights.sum()
    t = profiles.triage
    c1 = t.thresholds[0]
    means = np.array([disnea.severity.mean + a for a in disnea.severity.age_shift])
    sd = disnea.severity.sd

    real_share, assigned = reason_level1_shares(profiles, arrivals, "disnea")

    assert real_share == pytest.approx(
        sum(w * stats.norm.cdf((m - c1) / sd) for w, m in zip(weights, means, strict=True)),
        abs=1e-12,
    )
    assert assigned == pytest.approx(
        sum(
            w * stats.norm.cdf((m + t.bias - c1) / math.hypot(sd, t.noise))
            for w, m in zip(weights, means, strict=True)
        ),
        abs=1e-12,
    )


def test_motivo_desconocido(real):
    profiles, arrivals = real
    with pytest.raises(ValueError, match="reason must be one of"):
        reason_level1_shares(profiles, arrivals, "gripe")
    with pytest.raises(ValueError, match="reason must be one of"):
        with_severity(profiles, "gripe", 1.0, 1.0)


# El catálogo con la parada al 0,3 % (tarea 4.6a), escrito aquí aparte de REASONS.
CATALOG_03 = {key: (0.3 if key == "parada" else share) for key, _, share in REASONS}


def test_media_de_la_parada_por_su_criterio(real):
    """La menor media de la rejilla de 0,01 con ≥ 99 % de real 1 y ≥ 97 % de asignado 1.

    Con la desviación de 0,25 y la parada al 0,3 % sale 4,21: 4,20 da un 96,91 % de
    asignado 1, por debajo del 97 %.
    """
    profiles, arrivals = real
    mean = severity_mean_for(
        profiles,
        arrivals,
        "parada",
        0.25,
        real_min=0.99,
        assigned_min=0.97,
        start=4.0,
        targets=CATALOG_03,
    )
    assert mean == 4.21

    def shares(m):
        candidate = with_severity(profiles, "parada", m, 0.25)
        candidate = with_derived(candidate, derive_written_values(candidate, arrivals, CATALOG_03))
        return reason_level1_shares(candidate, arrivals, "parada")

    below_real, below_assigned = shares(4.20)
    assert below_real >= 0.99 and below_assigned < 0.97
    assert below_assigned == pytest.approx(0.9691, abs=5e-5)


def test_el_inicio_no_puede_cumplir_ya(real):
    """Si el primer candidato cumple, no sería la menor media: error."""
    profiles, arrivals = real
    with pytest.raises(ValueError, match="already meets the criterion"):
        severity_mean_for(
            profiles,
            arrivals,
            "parada",
            0.25,
            real_min=0.5,
            assigned_min=0.5,
            start=4.0,
            targets=CATALOG_03,
        )


def test_sin_candidato_en_la_rejilla(real):
    profiles, arrivals = real
    with pytest.raises(RuntimeError, match="no mean from"):
        severity_mean_for(
            profiles,
            arrivals,
            "parada",
            0.25,
            real_min=0.99,
            assigned_min=0.999,
            start=4.0,
            max_steps=2,
            targets=CATALOG_03,
        )


# --- Guarda del criterio de la parada (tarea 4.6a) ------------------------------------


@FILES
def test_guarda_de_la_parada_con_lo_escrito(profiles_path, arrivals_path):
    """Con los valores escritos, ≥ 99 % de las paradas de un año son nivel real 1 y ≥ 97 %,
    asignado 1 (a la puerta). La parada no depende de la edad, así que las dos cuotas son
    una Φ cada una, calculadas aquí a mano:

    - real: Φ((4,21 − 3,341) / 0,25) = Φ(3,476) = 0,99975;
    - asignado: Φ((4,21 − 0,081 − 3,341) / √(0,25² + 0,334²)) = Φ(1,8887) = 0,97054.
    """
    profiles = load_profiles(profiles_path)
    severity = profiles.reason("parada").severity
    t = profiles.triage
    assert (severity.mean, severity.sd, severity.age_shift) == (4.21, 0.25, (0.0,) * 4)
    assert (t.noise, t.bias, t.thresholds[0]) == (0.334, -0.081, 3.341)

    real_hand = stats.norm.cdf((4.21 - 3.341) / 0.25)
    assigned_hand = stats.norm.cdf((4.21 - 0.081 - 3.341) / math.sqrt(0.25**2 + 0.334**2))
    assert real_hand == pytest.approx(0.99975, abs=5e-6)
    assert assigned_hand == pytest.approx(0.97054, abs=5e-6)

    real_share, assigned = reason_level1_shares(profiles, load_profile(arrivals_path), "parada")
    assert real_share == pytest.approx(real_hand, abs=1e-12)
    assert assigned == pytest.approx(assigned_hand, abs=1e-12)
    assert real_share >= 0.99 and assigned >= 0.97


def test_la_media_escrita_es_la_del_criterio_con_el_catalogo(real):
    """Con el catálogo de REASONS (la parada al 0,3 %), la función da la media escrita."""
    profiles, arrivals = real
    assert {key: share for key, _, share in REASONS}["parada"] == 0.3
    mean = severity_mean_for(
        profiles, arrivals, "parada", 0.25, real_min=0.99, assigned_min=0.97, start=4.0
    )
    assert mean == profiles.reason("parada").severity.mean == 4.21
