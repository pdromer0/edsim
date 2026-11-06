"""La variante de perfiles con otro reparto objetivo y sus umbrales rederivados en memoria.

Los umbrales se derivan una vez y se escriben en el TOML, y no se recalculan al cargar
(decisión 38). Una variante con otro reparto objetivo, como el del SAS en adultos, es
otra cosa: un perfil distinto, cuyos umbrales salen de ``thresholds_for`` con su
reparto. El ruido y el sesgo se quedan como están, así que su infra y sobretriaje
cambian. Nada se escribe en config/.
"""

from pathlib import Path

import numpy as np
import pytest

from edsim.arrivals.profile import load_profile
from edsim.calibration import sas
from edsim.profiles.config import load_profiles
from edsim.profiles.derivation import with_target_mix
from edsim.profiles.severity import assigned_shares, severity_mixture, thresholds_for

CONFIG = Path(__file__).parent.parent / "config"
PROFILES = CONFIG / "perfiles.toml"
SAS_ADULTS = sas.level_pct(sas.adult_level_counts())


@pytest.fixture(scope="module")
def base():
    return load_profiles(PROFILES)


@pytest.fixture(scope="module")
def arrivals():
    return load_profile(CONFIG / "llegadas.toml")


@pytest.fixture(scope="module")
def variant(base, arrivals):
    return with_target_mix(base, arrivals, SAS_ADULTS)


def test_los_umbrales_salen_de_thresholds_for(base, variant, arrivals):
    assert variant.triage.thresholds == thresholds_for(variant, arrivals)
    assert variant.triage.thresholds != base.triage.thresholds


def test_el_reparto_asignado_exacto_es_el_objetivo(variant, arrivals):
    t = variant.triage
    shares = assigned_shares(severity_mixture(variant, arrivals), t.thresholds, t.noise, t.bias)

    assert np.allclose(shares, np.array(SAS_ADULTS) / sum(SAS_ADULTS), rtol=0, atol=1e-10)
    assert 100 * shares[4] == pytest.approx(18.22, abs=0.005)  # muchos más niveles 5


def test_el_reparto_objetivo_es_el_nuevo(variant):
    assert variant.triage.target_pct == pytest.approx(SAS_ADULTS, abs=1e-12)


def test_ruido_sesgo_y_lo_demas_no_cambian(base, variant):
    assert (variant.triage.noise, variant.triage.bias) == (base.triage.noise, base.triage.bias)
    assert variant.reasons == base.reasons
    assert variant.population == base.population


def test_con_el_reparto_base_salen_los_umbrales_escritos(base, arrivals):
    same = with_target_mix(base, arrivals, base.triage.target_pct)
    assert same.triage.thresholds == pytest.approx(base.triage.thresholds, abs=5e-4)


def test_no_toca_los_ficheros(arrivals):
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(CONFIG.iterdir())}

    with_target_mix(load_profiles(PROFILES), arrivals, SAS_ADULTS)

    after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(CONFIG.iterdir())}
    assert after == before


def test_un_reparto_no_valido_es_un_error(base, arrivals):
    with pytest.raises(ValueError, match="reparto_objetivo"):
        with_target_mix(base, arrivals, (10, 10, 10, 10, 10))
