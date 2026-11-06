"""Gumbel-max frente a la CDF inversa: cuántos pacientes cambian de categoría con otros pesos.

Valores a mano con tres categorías, [2, 1, 1] → [3, 1, 1] (repartos 50/25/25 → 60/20/20 %):

- Mínimo posible (distancia de variación total): ½ (0,10 + 0,05 + 0,05) = 0,10.
- Gumbel-max: solo crece el peso de A, así que solo cambian los que pasan a A: 0,10.
  Con la fórmula cerrada, P(sigue en A) = 1 / (1 + ½ + ½) = 0,5 y P(sigue en B) =
  P(sigue en C) = 1 / (3 + 1 + 1) = 0,2; siguen 0,9 y cambian 0,10.
- CDF inversa en el orden [A, B, C]: A = [0; 0,5) → [0; 0,6), B = [0,5; 0,75) →
  [0,6; 0,8), C = [0,75; 1) → [0,8; 1). Se solapan 0,5 + 0,15 + 0,2 = 0,85: cambian
  0,15 (0,10 de B a A y 0,05 de C a B).
"""

import dataclasses
from pathlib import Path

import numpy as np
import pytest
from scipy import stats

from edsim.arrivals.profile import load_profile
from edsim.profiles.config import load_profiles
from edsim.profiles.coupling import (
    ReasonShockChanges,
    gumbel_change_share,
    inverse_cdf,
    inverse_cdf_change_share,
    reason_shock_changes,
    simulate_changes,
    simulate_reason_shock,
    total_variation,
)

CONFIG = Path(__file__).parent.parent / "config"
BEFORE, AFTER = [2.0, 1.0, 1.0], [3.0, 1.0, 1.0]
CONFIDENCE = 1 - 1e-6  # un fallo por azar, una vez en un millón


def inside_binomial(k: int, n: int, p: float) -> bool:
    low, high = stats.binom.interval(CONFIDENCE, n, p)
    return low <= k <= high


def more_dyspnoea(profiles, factor=1.5):
    """Los perfiles con el peso base de la disnea multiplicado por ``factor``: la gripe."""
    return dataclasses.replace(
        profiles,
        reasons=tuple(
            dataclasses.replace(r, base_weight=r.base_weight * factor) if r.key == "disnea" else r
            for r in profiles.reasons
        ),
    )


@pytest.fixture(scope="module")
def profiles():
    return load_profiles(CONFIG / "perfiles.toml")


@pytest.fixture(scope="module")
def arrivals():
    return load_profile(CONFIG / "llegadas.toml")


# --- Valores a mano ------------------------------------------------------------------


def test_minimo_posible_a_mano():
    assert total_variation(BEFORE, AFTER) == pytest.approx(0.10, abs=1e-12)


def test_gumbel_max_a_mano():
    assert gumbel_change_share(BEFORE, AFTER) == pytest.approx(0.10, abs=1e-12)


def test_cdf_inversa_a_mano():
    assert inverse_cdf_change_share(BEFORE, AFTER) == pytest.approx(0.15, abs=1e-12)


def test_la_cdf_inversa_depende_del_orden():
    # En el orden [B, A, C]: B = [0; 0,25) → [0; 0,2), A = [0,25; 0,75) → [0,2; 0,8),
    # C = [0,75; 1) → [0,8; 1): se solapan 0,2 + 0,5 + 0,2 = 0,9 y cambian 0,10.
    assert inverse_cdf_change_share([1, 2, 1], [1, 3, 1]) == pytest.approx(0.10, abs=1e-12)


def test_sin_cambio_nadie_cambia():
    w = [5.0, 2.0, 0.5, 9.0]
    assert gumbel_change_share(w, w) == pytest.approx(0.0, abs=1e-12)
    assert inverse_cdf_change_share(w, w) == pytest.approx(0.0, abs=1e-12)
    assert total_variation(w, w) == 0.0


def test_la_escala_no_cambia_nada():
    assert gumbel_change_share(BEFORE, [6.0, 3.0, 3.0]) == pytest.approx(0.0, abs=1e-12)
    assert gumbel_change_share([20, 10, 10], [3, 1, 1]) == pytest.approx(0.10, abs=1e-12)


def test_un_peso_cero_no_retiene_a_nadie():
    # A desaparece: sus 0,5 pasan a B y C, que no pierden a nadie.
    assert gumbel_change_share(BEFORE, [0.0, 1.0, 1.0]) == pytest.approx(0.5, abs=1e-12)
    assert total_variation(BEFORE, [0.0, 1.0, 1.0]) == pytest.approx(0.5, abs=1e-12)


def test_con_un_solo_peso_que_crece_gumbel_es_el_minimo():
    rng = np.random.default_rng(2026)
    for _ in range(200):
        w = rng.uniform(0.1, 10, size=rng.integers(2, 18))
        v = w.copy()
        v[rng.integers(w.size)] *= rng.uniform(1, 5)
        assert gumbel_change_share(w, v) == pytest.approx(total_variation(w, v), abs=1e-12)


def test_ningun_metodo_cambia_menos_que_el_minimo():
    rng = np.random.default_rng(2027)
    for _ in range(200):
        n = rng.integers(2, 18)
        w, v = rng.uniform(0.1, 10, size=n), rng.uniform(0.1, 10, size=n)
        tv = total_variation(w, v)
        assert gumbel_change_share(w, v) >= tv - 1e-12
        assert inverse_cdf_change_share(w, v) >= tv - 1e-12


def test_por_ejes_como_cada_contexto():
    w = np.array([[2.0, 1.0], [1.0, 1.0], [1.0, 1.0]])  # 3 categorías, 2 contextos
    v = np.array([[3.0, 1.0], [1.0, 1.0], [1.0, 1.0]])

    assert np.allclose(gumbel_change_share(w, v), [0.10, 0.0], atol=1e-12)
    assert np.allclose(inverse_cdf_change_share(w, v), [0.15, 0.0], atol=1e-12)
    assert np.allclose(total_variation(w, v), [0.10, 0.0], atol=1e-12)


@pytest.mark.parametrize(
    ("u", "category"), [(0.0, 0), (0.4999, 0), (0.5, 1), (0.7499, 1), (0.75, 2), (0.9999, 2)]
)
def test_cdf_inversa_en_los_bordes(u, category):
    # Cada categoría es el intervalo [acumulado anterior, acumulado): un borde es del siguiente.
    assert inverse_cdf(BEFORE, u) == category


def test_cdf_inversa_con_peso_cero():
    assert [inverse_cdf([1.0, 0.0, 1.0], u) for u in (0.2, 0.5, 0.7)] == [0, 2, 2]


def test_cdf_inversa_uniforme_fuera_de_rango():
    with pytest.raises(ValueError, match=r"u must be in \[0, 1\)"):
        inverse_cdf(BEFORE, 1.0)


@pytest.mark.parametrize(
    ("before", "after"),
    [([1.0, 2.0], [1.0, 2.0, 3.0]), ([1.0], [2.0]), ([1.0, -1.0], [1.0, 1.0]), ([0, 0], [1, 1])],
)
def test_pesos_no_validos(before, after):
    with pytest.raises(ValueError):
        gumbel_change_share(before, after)


# --- Simulados con números aleatorios comunes ------------------------------------------


def test_simulacion_dentro_de_su_binomial():
    n = 20_000
    s = simulate_changes(BEFORE, AFTER, n, 2026)

    assert s.patients == n
    assert inside_binomial(s.gumbel, n, 0.10)  # el valor a mano, no la fórmula
    assert inside_binomial(s.inverse_cdf, n, 0.15)


def test_simulacion_sin_cambio_de_pesos():
    s = simulate_changes(BEFORE, [4.0, 2.0, 2.0], 5_000, 2026)
    assert (s.gumbel, s.inverse_cdf) == (0, 0)


def test_simulacion_solo_de_una_dimension():
    with pytest.raises(ValueError, match="one-dimensional"):
        simulate_changes(np.ones((3, 2)), np.ones((3, 2)), 10, 2026)


# --- La gripe con config/ --------------------------------------------------------------


def test_la_gripe_en_un_año(profiles, arrivals):
    # Disnea ×1,5 con los pesos de config/ (tarea 4.7): cambia el 3,37 % de los pacientes
    # con Gumbel-max, exactamente el mínimo posible, frente al 15,55 % con la CDF inversa.
    # La especificación decía 3,6 %, 3,5 % y 17,3 % (la sesión conceptual, otros pesos).
    c = reason_shock_changes(profiles, more_dyspnoea(profiles), arrivals)

    assert isinstance(c, ReasonShockChanges)
    assert c.gumbel == pytest.approx(0.033696, abs=1e-6)
    assert c.minimum == pytest.approx(c.gumbel, abs=1e-12)
    assert c.inverse_cdf == pytest.approx(0.155492, abs=1e-6)


def test_la_gripe_simulada_dentro_de_su_binomial(profiles, arrivals):
    n = 20_000
    s = simulate_reason_shock(profiles, more_dyspnoea(profiles), arrivals, seed=2026, patients=n)
    exact = reason_shock_changes(profiles, more_dyspnoea(profiles), arrivals)

    assert s.patients == n
    assert s.gumbel > 0  # el caso ocurre
    assert inside_binomial(s.gumbel, n, s.expected_gumbel)
    assert inside_binomial(s.inverse_cdf, n, s.expected_inverse_cdf)
    # Lo esperado para estos pacientes está cerca de lo exacto del año.
    assert s.expected_gumbel == pytest.approx(exact.gumbel, abs=0.002)
    assert s.expected_minimum == pytest.approx(s.expected_gumbel, abs=1e-12)


def test_sin_cambio_de_perfiles_nadie_cambia(profiles, arrivals):
    s = simulate_reason_shock(profiles, profiles, arrivals, seed=2026, patients=2_000)
    assert (s.gumbel, s.inverse_cdf) == (0, 0)


def test_otra_poblacion_es_un_error(profiles, arrivals):
    population = dataclasses.replace(profiles.population, band_shares=(40.0, 22.0, 20.0, 18.0))
    other = dataclasses.replace(profiles, population=population)

    with pytest.raises(ValueError, match="same population"):
        reason_shock_changes(profiles, other, arrivals)
    with pytest.raises(ValueError, match="same population"):
        simulate_reason_shock(profiles, other, arrivals, seed=2026, patients=10)
