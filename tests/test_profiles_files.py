"""Los ficheros de perfiles: config/perfiles.toml y su copia fija de ejemplo."""

import dataclasses
from pathlib import Path

import numpy as np
import pytest

from edsim.arrivals.profile import load_profile
from edsim.profiles.config import REASON_KEYS, REASONS, ClinicalProfiles, load_profiles
from edsim.profiles.mixing import base_weights_for, catalog_shares, global_reason_shares
from edsim.profiles.population import global_band_shares, share_65_plus

ROOT = Path(__file__).parents[1]
EXAMPLE = Path(__file__).parent / "data" / "perfiles_ejemplo.toml"
REAL = ROOT / "config" / "perfiles.toml"
ARRIVALS = {
    EXAMPLE: Path(__file__).parent / "data" / "llegadas_ejemplo.toml",
    REAL: ROOT / "config" / "llegadas.toml",
}
FILES = pytest.mark.parametrize("path", [EXAMPLE, REAL], ids=["ejemplo", "real"])


@pytest.fixture(scope="module")
def example() -> ClinicalProfiles:
    return load_profiles(EXAMPLE)


@FILES
def test_carga(path):
    profiles = load_profiles(path)

    assert profiles.reason_keys == REASON_KEYS
    assert profiles.shift_band_starts == (8, 15, 22)


def test_valores_del_ejemplo(example):
    assert example.population.band_shares == (38.0, 22.0, 22.0, 18.0)
    assert example.population.ambulance_pct == (6.0, 10.0, 21.0, 34.0)
    assert example.reason("disnea").base_weight == 7.327
    assert example.reason("disnea").age_factors == (0.4, 0.8, 1.8, 2.4)
    # Motivos sin factores: todos valen 1.
    for key in ("dolor_abdominal", "digestivo", "otros"):
        r = example.reason(key)
        assert r.age_factors + r.shift_factors + r.day_factors + r.season_factors == (1.0,) * 13


@FILES
def test_reparto_global_dentro_de_medio_punto(path):
    # Con los pesos base escritos (redondeados a 3 decimales), el reparto de un año
    # queda a menos de 0,5 puntos del catálogo; en la tarea 4.2, a 0,0006.
    shares = global_reason_shares(load_profiles(path), load_profile(ARRIVALS[path]))
    deviation = 100 * np.abs(shares - catalog_shares())

    assert deviation.max() < 0.5, dict(zip(REASON_KEYS, deviation.round(3), strict=True))


@FILES
def test_pesos_escritos_iguales_a_los_derivados(path):
    # Si se cambia un factor sin volver a ejecutar base_weights_for, falla.
    profiles = load_profiles(path)
    derived = base_weights_for(profiles, load_profile(ARRIVALS[path]))

    for r in profiles.reasons:
        assert r.base_weight == pytest.approx(derived[r.key], abs=5e-4), r.key


@FILES
def test_sin_derivar_se_saldria_del_catalogo(path):
    # Comprueba que el test del reparto global no pasa de forma vacía: con el
    # catálogo como peso base, los factores alejan la intoxicación más de 0,5 puntos.
    profiles = load_profiles(path)
    catalog = {key: weight for key, _, weight in REASONS}
    naive = dataclasses.replace(
        profiles,
        reasons=tuple(dataclasses.replace(r, base_weight=catalog[r.key]) for r in profiles.reasons),
    )
    shares = global_reason_shares(naive, load_profile(ARRIVALS[path]))
    i = REASON_KEYS.index("intoxicacion")

    assert 100 * abs(shares[i] - catalog_shares()[i]) > 0.5


@FILES
def test_mayores_de_65_en_la_horquilla(path):
    # 34-44 % de mayores de 65 años sobre adultos (Gaceta Sanitaria 2018: 27-35 %
    # sobre todas las edades, dividido por 0,79).
    share = share_65_plus(load_profiles(path), load_profile(ARRIVALS[path]))

    assert 0.34 <= share <= 0.44
    assert share == pytest.approx(0.3855, abs=5e-4)


@FILES
def test_ambulancia_en_mayores_de_65(path):
    # 27 % de los mayores de 65 años llega en ambulancia (cohorte EDEN).
    profiles = load_profiles(path)
    shares = global_band_shares(profiles, load_profile(ARRIVALS[path]))
    pct = np.asarray(profiles.population.ambulance_pct)

    older = (shares[2:] * pct[2:]).sum() / shares[2:].sum()

    assert older == pytest.approx(27, abs=0.5)
