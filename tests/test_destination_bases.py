"""Los derivados del destino (decisión 75, H5-9): calculados una vez, escritos y no recalculados.

``destination_bases_for`` resuelve a la vez el factor común del ingreso y las bases del
traslado y el exitus, que comparten el alta, para que el año dé 9,90 / 0,75 / 0,11 %. Lo
escrito en ``tests/data/perfiles_h5_ejemplo.toml`` es eso con 4 cifras significativas. Los
valores esperados son los del prototipo del plan de la tarea 5.2, independiente de
``profiles/outcome.py``.
"""

import tomllib
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from edsim.arrivals.profile import load_profile
from edsim.profiles.config import ADMISSION_CATALOG, REASON_KEYS, load_profiles
from edsim.profiles.derivation import (
    derive_written_values,
    round_significant,
    with_base_weights,
    with_derived,
)
from edsim.profiles.outcome import (
    DestinationBases,
    admission_from_factor,
    destination_bases_for,
    outcome_model,
    with_destination_bases,
)

DATA = Path(__file__).parent / "data"
H5 = DATA / "perfiles_h5_ejemplo.toml"
LEVELS = ("muy_bajo", "bajo", "medio", "alto", "muy_alto")


@pytest.fixture(scope="module")
def arrivals():
    return load_profile(DATA / "llegadas_ejemplo.toml")


@pytest.fixture(scope="module")
def profiles():
    return load_profiles(H5)


def test_lo_escrito_a_mano(profiles):
    # El prototipo: factor común 1,32664 sobre las odds de partida 1 / 2 / 5 / 10 / 25 %.
    written = {r.key: r.admission_pct for r in profiles.reasons}
    expected = {"muy_bajo": 1.322, "bajo": 2.636, "medio": 6.527, "alto": 12.85, "muy_alto": 30.66}
    assert written == {k: expected[ADMISSION_CATALOG[k]] for k in REASON_KEYS}
    assert profiles.outcome.transfer.base == 0.7639
    assert profiles.outcome.death.base == 0.001937


def test_escritos_iguales_a_recalculados(profiles, arrivals):
    bases = destination_bases_for(profiles, arrivals)
    assert {k: round_significant(v) for k, v in bases.admission.items()} == {
        r.key: r.admission_pct for r in profiles.reasons
    }
    assert round_significant(bases.transfer) == profiles.outcome.transfer.base
    assert round_significant(bases.death) == profiles.outcome.death.base


def test_la_derivacion_no_depende_de_lo_ya_derivado(profiles, arrivals):
    scrambled = with_destination_bases(
        profiles, DestinationBases(dict.fromkeys(REASON_KEYS, 40.0), 3.0, 1.0)
    )
    assert destination_bases_for(scrambled, arrivals) == destination_bases_for(profiles, arrivals)
    derived = derive_written_values(profiles, arrivals)
    assert derive_written_values(with_derived(scrambled, derived), arrivals) == derived


def test_el_ano_con_lo_escrito(profiles, arrivals):
    # 89,2393 / 9,9007 / 0,7500 / 0,1100: el redondeo a 4 cifras mueve el ingreso 0,0007.
    year = 100 * outcome_model(profiles, arrivals).year_shares()
    assert year == pytest.approx((89.2393, 9.9007, 0.7500, 0.1100), abs=1e-4)


def test_la_disnea_por_1_5_da_mas_ingreso(profiles, arrivals):
    # peso_base 7,397 → 11,0955 con lo escrito: 88,4533 / 10,6800 / 0,7541 / 0,1126. Si los
    # derivados se recalcularan al cargar, el ingreso seguiría en el 9,90 (V12).
    disnea = profiles.reason("disnea")
    assert disnea.base_weight == 7.397
    weights = {r.key: r.base_weight for r in profiles.reasons} | {"disnea": 7.397 * 1.5}
    shocked = with_base_weights(profiles, weights)
    year = 100 * outcome_model(shocked, arrivals).year_shares()
    assert year == pytest.approx((88.4533, 10.6800, 0.7541, 0.1126), abs=1e-4)


def test_las_marginales_respetan_el_orden_del_catalogo(profiles, arrivals):
    admission = outcome_model(profiles, arrivals).by_reason()[:, 1]
    by_level = {
        level: [admission[i] for i, k in enumerate(REASON_KEYS) if ADMISSION_CATALOG[k] == level]
        for level in LEVELS
    }
    for lower, upper in zip(LEVELS, LEVELS[1:], strict=False):
        assert max(by_level[lower]) < min(by_level[upper])


def test_las_comprobaciones_clinicas_del_prototipo(profiles, arrivals):
    model = outcome_model(profiles, arrivals)
    # Ingreso por nivel asignado (SAS: 46,5 / 25,1 / 11,0 / 3,9 / 7,4) y por k.
    assert 100 * model.by_assigned_level()[:, 1] == pytest.approx(
        (68.05, 28.06, 11.78, 4.29, 1.86), abs=0.005
    )
    assert 100 * model.by_abnormal_count()[:, 1] == pytest.approx(
        (4.91, 14.02, 29.02, 47.82, 69.06), abs=0.005
    )
    # La parada: 6,88 / 74,21 / 0,41 / 18,50, y la mitad de los exitus del año.
    parada = REASON_KEYS.index("parada")
    assert 100 * model.by_reason()[parada] == pytest.approx((6.88, 74.21, 0.41, 18.50), abs=0.005)
    deaths = model.reason_shares() * model.by_reason()[:, 3]
    assert deaths[parada] / deaths.sum() == pytest.approx(0.508, abs=5e-4)


def test_sin_bloque_no_hay_derivados_del_destino(arrivals):
    hito4 = load_profiles(DATA / "perfiles_ejemplo.toml")
    assert derive_written_values(hito4, arrivals).destinations is None
    with pytest.raises(ValueError, match=r"needs the block \[abandono\]"):
        destination_bases_for(hito4, arrivals)


def test_unos_objetivos_imposibles_no_convergen(profiles, arrivals):
    # Un traslado del 95 % con un 9,90 % de ingreso no cabe en el 100 %.
    outcome = profiles.outcome
    impossible = replace(
        profiles, outcome=replace(outcome, transfer=replace(outcome.transfer, target=95.0))
    )
    with pytest.raises(RuntimeError, match="destination_bases_for did not converge"):
        destination_bases_for(impossible, arrivals)


def test_el_factor_comun_conserva_el_orden():
    pct = admission_from_factor(0.5)
    assert pct["orl"] < pct["traumatismo"] < pct["fiebre"] < pct["disnea"] < pct["parada"]
    assert admission_from_factor(0.0)["parada"] == pytest.approx(25.0)


@pytest.mark.parametrize(
    ("x", "expected"),
    [(0.0019369194, 0.001937), (12.84681, 12.85), (30.662202, 30.66), (0.76393, 0.7639), (0, 0)],
)
def test_cuatro_cifras_significativas(x, expected):
    assert round_significant(x) == expected


def test_el_fichero_sin_el_bloque_es_el_de_ejemplo():
    with H5.open("rb") as f:
        h5 = tomllib.load(f)
    with (DATA / "perfiles_ejemplo.toml").open("rb") as f:
        base = tomllib.load(f)
    assert {"abandono", "destinos"} <= h5.keys()
    del h5["abandono"], h5["destinos"]
    for table in h5["motivos"].values():
        del table["ingreso"]
    assert h5 == base


def test_la_mayor_suma_queda_lejos_de_100(profiles):
    # La parada: 30,66 + 0,7639 + 0,001937 = 31,43.
    sums = [r.admission_pct + 0.7639 + 0.001937 for r in profiles.reasons]
    assert max(sums) == pytest.approx(31.425837)
    assert np.argmax(sums) == REASON_KEYS.index("parada")
