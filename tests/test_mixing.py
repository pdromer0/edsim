import math
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from profiles_factory import POPULATION, START, make_profiles, t_at

from edsim.arrivals.profile import load_profile
from edsim.profiles.config import REASON_KEYS, REASONS
from edsim.profiles.context import ArrivalContext, all_contexts, arrival_context
from edsim.profiles.mixing import (
    band_probabilities,
    band_weights,
    base_weights_for,
    catalog_shares,
    global_reason_shares,
    gumbel_max,
    probabilities,
    reason_probabilities,
    reason_weights,
)

ARRIVALS = Path(__file__).parent / "data" / "llegadas_ejemplo.toml"
DISNEA = REASON_KEYS.index("disnea")
OLDEST = 3  # banda 80-99

# Perfil del ejemplo a mano: pesos del catálogo (suma 99,5) y solo estos factores
# en la banda de 80-99 años:
#   disnea:   8 × 2,4 (edad) × 1,5 (invierno) = 28,8   (+20,8)
#   malestar: 6 × 1,74                        = 10,44  (+4,44)
#   síncope:  4 × 1,5                         = 6      (+2)
# Suma: 99,5 + 20,8 + 4,44 + 2 = 126,74; disnea = 28,8 / 126,74 = 22,72 %.
HAND = {
    "disnea": {"age_factors": (1, 1, 1, 2.4), "season_factors": (1.5, 1, 1, 1)},
    "malestar": {"age_factors": (1, 1, 1, 1.74)},
    "sincope": {"age_factors": (1, 1, 1, 1.5)},
}

# Factores de intoxicación de config/perfiles.toml, para un reparto global que
# se aleja del catálogo si los pesos base no se derivan.
INTOXICATION = {
    "intoxicacion": {
        "age_factors": (2.0, 0.8, 0.3, 0.2),
        "shift_factors": (1, 1, 1.8),
        "day_factors": (1, 1.7),
    },
    "disnea": {"age_factors": (0.4, 0.8, 1.8, 2.4), "season_factors": (1.5, 1, 0.7, 1)},
}


@pytest.fixture(scope="module")
def arrivals():
    return load_profile(ARRIVALS)


@pytest.fixture(scope="module")
def tuesday_winter_morning() -> ArrivalContext:
    ctx = arrival_context(t_at(date(2026, 1, 6), 10), START, (8, 15, 22))
    assert ctx == ArrivalContext(0, 0, 0)  # martes 6 de enero a las 10:00
    return ctx


# --- Ejemplo a mano ------------------------------------------------------------


def test_disnea_en_mayores_un_martes_de_invierno(tuesday_winter_morning):
    profiles = make_profiles(HAND)

    w = reason_weights(profiles, tuesday_winter_morning, OLDEST)
    p = reason_probabilities(profiles, tuesday_winter_morning, OLDEST)

    assert w[DISNEA] == pytest.approx(28.8, rel=1e-12)
    assert w.sum() == pytest.approx(126.74, rel=1e-12)
    assert p[DISNEA] == pytest.approx(0.22724, abs=5e-6)


def test_los_factores_se_multiplican():
    profiles = make_profiles(HAND)

    summer = reason_weights(profiles, ArrivalContext(0, 0, 2), OLDEST)
    young_winter = reason_weights(profiles, ArrivalContext(0, 0, 0), 0)

    assert summer[DISNEA] == pytest.approx(8 * 2.4, rel=1e-12)  # sin el factor de invierno
    assert young_winter[DISNEA] == pytest.approx(8 * 1.5, rel=1e-12)  # sin el de edad


def test_cuatro_factores_a_la_vez():
    # 8 × 2 × 1,5 × 1,2 × 0,5 = 14,4: con cuatro factores el producto y la suma difieren.
    profiles = make_profiles(
        {
            "disnea": {
                "age_factors": (2, 1, 1, 1),
                "shift_factors": (1, 1, 1.5),
                "day_factors": (1, 1.2),
                "season_factors": (1, 1, 1, 0.5),
            }
        }
    )

    w = reason_weights(profiles, ArrivalContext(2, 1, 3), 0)

    assert w[DISNEA] == pytest.approx(14.4, rel=1e-12)


def test_factores_neutros_dan_el_catalogo():
    profiles = make_profiles()

    for ctx in all_contexts():
        p = reason_probabilities(profiles, ctx, 2)
        np.testing.assert_allclose(p, [w / 99.5 for _, _, w in REASONS], rtol=1e-12)


def test_probabilidades_suman_uno():
    profiles = make_profiles(INTOXICATION)

    for ctx in all_contexts():
        assert band_probabilities(profiles.population, ctx).sum() == pytest.approx(1, rel=1e-12)
        for band in range(4):
            assert reason_probabilities(profiles, ctx, band).sum() == pytest.approx(1, rel=1e-12)


def test_probabilities_a_mano():
    np.testing.assert_allclose(probabilities([1, 2, 7]), [0.1, 0.2, 0.7], rtol=1e-15)


# --- Bandas de edad ------------------------------------------------------------


def test_bandas_en_el_contexto_de_referencia():
    # Mañana laborable: todos los factores valen 1 y el reparto es el escrito.
    p = band_probabilities(POPULATION, ArrivalContext(0, 0, 1))

    np.testing.assert_allclose(p, [0.38, 0.22, 0.22, 0.18], rtol=1e-12)


def test_bandas_de_noche_en_fin_de_semana():
    # Jóvenes: 38 × 1,3 × 1,15 = 56,81; suma 56,81 + 62 = 118,81.
    w = band_weights(POPULATION, ArrivalContext(2, 1, 0))
    p = band_probabilities(POPULATION, ArrivalContext(2, 1, 0))

    assert w[0] == pytest.approx(56.81, rel=1e-12)
    assert p[0] == pytest.approx(56.81 / 118.81, rel=1e-12)  # 47,8 %
    assert p[3] == pytest.approx(18 / 118.81, rel=1e-12)


def test_la_estacion_no_cambia_las_bandas():
    for season in range(4):
        np.testing.assert_array_equal(
            band_weights(POPULATION, ArrivalContext(2, 1, season)),
            band_weights(POPULATION, ArrivalContext(2, 1, 0)),
        )


# --- Gumbel-max a mano ---------------------------------------------------------


@pytest.mark.parametrize(
    ("g", "winner"),
    [
        # log w = [0; 0,693; 1,946]. Con g = [2, 0, 0], log w + g = [2; 0,69; 1,95]:
        # gana 0, mientras que w + g = [3, 2, 7] haría ganar a 2.
        ([2.0, 0.0, 0.0], 0),
        # log w + g = [0; 1,993; 1,946]: gana 1 por poco; w + g = [1; 3,3; 7] daría 2.
        ([0.0, 1.3, 0.0], 1),
        ([0.0, 0.0, 0.0], 2),
        ([1.9, 0.0, 0.0], 2),  # 1,9 < 1,946
    ],
)
def test_gumbel_max_a_mano(g, winner):
    assert gumbel_max([1.0, 2.0, 7.0], g) == winner


@pytest.mark.parametrize("scale", [10.0, 1e-3, 1 / 3])
def test_gumbel_max_no_depende_de_la_escala(scale):
    rng = np.random.default_rng(3)
    w = np.array([1.0, 2.0, 7.0, 0.5])
    for _ in range(200):
        g = rng.gumbel(size=4)
        assert gumbel_max(w * scale, g) == gumbel_max(w, g)


def test_gumbel_max_con_peso_cero():
    # Una banda con reparto 0 no sale nunca, aunque su Gumbel sea enorme.
    assert gumbel_max([1.0, 2.0, 0.0], [0.0, 0.0, 50.0]) != 2


def test_gumbel_max_devuelve_int():
    assert type(gumbel_max([1.0, 2.0], [0.0, 0.0])) is int


def test_gumbel_max_longitudes_distintas():
    with pytest.raises(ValueError, match="same length"):
        gumbel_max([1.0, 2.0], [0.0, 0.0, 0.0])


# --- base_weights_for ----------------------------------------------------------


def test_catalogo_normalizado():
    shares = catalog_shares()

    assert shares.sum() == pytest.approx(1, rel=1e-15)
    assert shares[REASON_KEYS.index("parada")] == pytest.approx(0.5 / 99.5, rel=1e-15)


def test_sin_factores_los_pesos_base_son_el_catalogo(arrivals):
    weights = base_weights_for(make_profiles(), arrivals)

    assert tuple(weights) == REASON_KEYS
    assert sum(weights.values()) == pytest.approx(100, rel=1e-12)
    for key, _, catalog in REASONS:
        assert weights[key] == pytest.approx(100 * catalog / 99.5, rel=1e-10)


def test_sin_derivar_el_reparto_global_se_aleja(arrivals):
    # Comprueba que el test siguiente no pasa de forma vacía: con los pesos del
    # catálogo como base, la intoxicación sale más de 0,5 puntos lejos del 2,01 %.
    shares = global_reason_shares(make_profiles(INTOXICATION), arrivals)
    i = REASON_KEYS.index("intoxicacion")

    assert abs(shares[i] - catalog_shares()[i]) > 0.005


def test_pesos_derivados_dan_el_catalogo(arrivals):
    profiles = make_profiles(INTOXICATION)

    weights = base_weights_for(profiles, arrivals)
    derived = make_profiles(INTOXICATION, base_weights=weights)

    np.testing.assert_allclose(global_reason_shares(derived, arrivals), catalog_shares(), atol=1e-9)


def test_pesos_derivados_no_dependen_de_los_pesos_base_del_perfil(arrivals):
    a = base_weights_for(make_profiles(INTOXICATION), arrivals)
    b = base_weights_for(
        make_profiles(INTOXICATION, base_weights=dict.fromkeys(REASON_KEYS, 1.0)), arrivals
    )

    for key in REASON_KEYS:
        assert a[key] == pytest.approx(b[key], rel=1e-12)


def test_el_reparto_global_suma_uno(arrivals):
    assert global_reason_shares(make_profiles(INTOXICATION), arrivals).sum() == pytest.approx(
        1, rel=1e-12
    )


def test_objetivos_propios(arrivals):
    targets = dict.fromkeys(REASON_KEYS, 1.0)  # todos iguales

    weights = base_weights_for(make_profiles(INTOXICATION), arrivals, targets)
    derived = make_profiles(INTOXICATION, base_weights=weights)

    np.testing.assert_allclose(global_reason_shares(derived, arrivals), 1 / 17, atol=1e-9)


def test_sin_converger_es_un_error(arrivals):
    with pytest.raises(RuntimeError, match="did not converge after 1 iteration"):
        base_weights_for(make_profiles(INTOXICATION), arrivals, max_iterations=1)


@pytest.mark.parametrize(
    ("targets", "message"),
    [
        ({k: 1.0 for k in REASON_KEYS if k != "otros"}, "missing keys: motivos.otros"),
        ({**dict.fromkeys(REASON_KEYS, 1.0), "gripe": 1.0}, "unknown keys: motivos.gripe"),
        ({**dict.fromkeys(REASON_KEYS, 1.0), "otros": 0.0}, r"targets\[otros\] must be positive"),
        ({**dict.fromkeys(REASON_KEYS, 1.0), "otros": math.nan}, r"targets\[otros\]"),
    ],
)
def test_objetivos_no_validos(arrivals, targets, message):
    with pytest.raises(ValueError, match=message):
        base_weights_for(make_profiles(), arrivals, targets)
