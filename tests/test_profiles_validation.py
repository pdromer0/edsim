"""Validación estadística de la mezcla de bandas y motivos por contexto, y del triaje.

Potencia. Cada contexto sortea 20 000 pacientes. Cada categoría se compara con
su probabilidad exacta con un chi² de 1 grado de libertad: 4 bandas, 17 motivos
(marginal sobre las bandas) y 68 motivos dentro de cada banda, 89 por contexto.
Con ALPHA = 0,01 y Bonferroni entre los 24 contextos y las 89 categorías, cada
prueba usa el nivel 0,01 / 2136 = 4,7e-6. Con una potencia del 80 % detecta:

- marginal, n = 20 000: un 0,5 % que pasa a 0,78 %; un 5 % que pasa a 5,85 %;
  un 8 % que pasa a 9,05 %; un 20 % que pasa a 21,54 %;
- dentro de la banda de 80-99, n ≈ 3600 en la mañana laborable (18 % de los
  pacientes): un 5 % que pasa a 7,02 %; un 20 % que pasa a 23,65 %; la disnea
  de esa banda en invierno, 19,9 %, si pasa a 23,5 %. De noche en fin de semana
  hay menos mayores (n ≈ 3030): un 5 % que pasa a 7,21 %.

Es decir, errores relativos de alrededor del 55 % en los motivos raros y del
10-15 % en los frecuentes en la marginal, y del 20-40 % dentro de la banda de
más edad; un error más pequeño puede pasar. Con 20 000 pacientes, el menor
esperado dentro de una banda es 7,1 (intoxicación en 80-99, tarde laborable de
invierno), por encima de MIN_EXPECTED. Con solo 2 contextos (el test rápido) el
nivel es 0,01 / 178 y la potencia, algo mayor.
"""

import dataclasses
from pathlib import Path

import numpy as np
import pytest
from profiles_factory import START

from edsim.arrivals.profile import load_profile
from edsim.profiles.config import REASON_KEYS, load_profiles
from edsim.profiles.context import ArrivalContext, all_contexts
from edsim.profiles.mixing import band_probabilities, reason_probabilities
from edsim.profiles.severity import severity_mixture, triage_matrix
from edsim.profiles.validation import (
    MIN_EXPECTED,
    N_CATEGORIES,
    N_TRIAGE_CATEGORIES,
    check_mixing,
    check_triage,
    detectable_share,
    detection_power,
    year_patients,
)

EXAMPLE = Path(__file__).parent / "data" / "perfiles_ejemplo.toml"
ARRIVALS = Path(__file__).parent / "data" / "llegadas_ejemplo.toml"
SEED = 2026
N = 20_000
OPPOSITE = (ArrivalContext(0, 0, 0), ArrivalContext(2, 1, 2))  # mañana laborable de invierno
# frente a noche de fin de semana de verano
OLDEST = 3  # banda 80-99
DISNEA = REASON_KEYS.index("disnea")


@pytest.fixture(scope="module")
def profiles():
    return load_profiles(EXAMPLE)


def test_potencia_escrita_en_el_test():
    alpha = 0.01 / (24 * N_CATEGORIES)

    assert N_CATEGORIES == 4 + 17 + 4 * 17 == 89
    for p0, p1 in [(0.005, 0.0078), (0.05, 0.0585), (0.08, 0.0905), (0.20, 0.2154)]:
        assert detectable_share(p0, N, alpha) == pytest.approx(p1, abs=1e-4)
    # Dentro de la banda de 80-99, con sus pacientes.
    for n, p0, p1 in [(3600, 0.05, 0.0702), (3600, 0.20, 0.2365), (3030, 0.05, 0.0721)]:
        assert detectable_share(p0, n, alpha) == pytest.approx(p1, abs=1e-4)


def test_potencia_contra_la_disnea_de_los_mayores(profiles):
    # La disnea en 80-99 en la mañana de invierno es el 19,9 %; con ×1,5 en esa
    # banda pasa a 1,5·p / (1 + 0,5·p) = 27,1 %. Con unos 3600 pacientes de la
    # banda, la potencia es mayor del 99,99999 % al nivel de un contexto
    # (0,01 / 89) y también al de los 24 (0,01 / 2136).
    winter = OPPOSITE[0]
    p0 = reason_probabilities(profiles, winter, OLDEST)[DISNEA]
    p1 = 1.5 * p0 / (1 + 0.5 * p0)
    n = int(N * band_probabilities(profiles.population, winter)[OLDEST])

    assert p0 == pytest.approx(0.1988, abs=1e-4)
    assert n == 3600
    for alpha in (0.01 / N_CATEGORIES, 0.01 / (24 * N_CATEGORIES)):
        assert detection_power(p0, p1, n, alpha) >= 0.99


def test_dos_contextos_opuestos(profiles):
    result = check_mixing(profiles, START, seed=SEED, patients=N, contexts=OPPOSITE)

    assert result.passed, [(d.name, d.p_value) for d in result.details]
    assert [d.name for d in result.details] == [
        "manana/laborable/invierno",
        "noche/fin_de_semana/verano",
    ]
    assert all(len(d.details) == N_CATEGORIES for d in result.details)
    names = [c.name for c in result.details[0].details]
    assert names[:5] == ["banda_15_44", "banda_45_64", "banda_65_79", "banda_80_99", "traumatismo"]
    assert names[-1] == "banda_80_99/otros"
    assert result.criterion.startswith("all 2 contexts")


def test_detecta_mas_disnea_en_invierno(profiles):
    # El muestreador sortea con la disnea ×1,2 y la hipótesis es el perfil: en la
    # mañana de invierno la disnea pasa de alrededor del 11 % al 13 %, muy por
    # encima de lo que detecta la prueba (8 % → 9 %).
    sampled = dataclasses.replace(
        profiles,
        reasons=tuple(
            dataclasses.replace(r, base_weight=1.2 * r.base_weight) if r.key == "disnea" else r
            for r in profiles.reasons
        ),
    )

    result = check_mixing(
        profiles, START, seed=SEED, patients=N, contexts=OPPOSITE[:1], sampled_profiles=sampled
    )

    assert not result.passed
    failed = [d.name for d in result.details[0].details if not d.passed]
    assert "disnea" in failed


def test_detecta_la_disnea_de_los_mayores_solo_en_su_banda(profiles):
    # El muestreador sortea con la disnea ×1,5 solo en 80-99 (factor de edad); la
    # hipótesis es el perfil. Falla la categoría condicionada de la disnea en esa
    # banda, con la potencia del test anterior.
    sampled = dataclasses.replace(
        profiles,
        reasons=tuple(
            dataclasses.replace(r, age_factors=(*r.age_factors[:3], 1.5 * r.age_factors[3]))
            if r.key == "disnea"
            else r
            for r in profiles.reasons
        ),
    )

    result = check_mixing(
        profiles, START, seed=SEED, patients=N, contexts=OPPOSITE[:1], sampled_profiles=sampled
    )

    assert not result.passed
    failed = {d.name for d in result.details[0].details if not d.passed}
    assert "banda_80_99/disnea" in failed
    # La disnea de las otras bandas no cambia.
    assert not failed & {"banda_15_44/disnea", "banda_45_64/disnea", "banda_65_79/disnea"}


def test_pocos_pacientes_es_un_error(profiles):
    # La parada (0,5 %) necesita al menos 5 pacientes esperados por contexto: con
    # 200 pacientes el test pasaría de forma vacía.
    with pytest.raises(ValueError, match=f"expected .* < {MIN_EXPECTED}"):
        check_mixing(profiles, START, seed=SEED, patients=200, contexts=OPPOSITE)


def test_misma_semilla_mismo_resultado(profiles):
    # 20 000 pacientes: con 2000, la parada en 15-44 tendría 0,8 esperados.
    a = check_mixing(profiles, START, seed=SEED, patients=N, contexts=OPPOSITE[:1])
    b = check_mixing(profiles, START, seed=SEED, patients=N, contexts=OPPOSITE[:1])

    assert a == b


@pytest.mark.slow
def test_los_24_contextos(profiles):
    result = check_mixing(profiles, START, seed=SEED, patients=N)

    assert len(result.details) == 24
    assert [d.name for d in result.details] == [c.label for c in all_contexts()]
    assert result.passed, [(d.name, d.p_value) for d in result.details if not d.passed]
    assert result.p_value == min(d.p_value for d in result.details)


def test_detectable_share_crece_con_menos_pacientes():
    assert detectable_share(0.05, 2000, 2e-5) > detectable_share(0.05, 20_000, 2e-5)
    assert np.isclose(detectable_share(0.05, 10**9, 2e-5), 0.05, atol=1e-4)


# --- Triaje ----------------------------------------------------------------------
#
# Potencia de check_triage. Se prueban 30 categorías (5 niveles asignados y las 25
# casillas de la matriz real × asignado), cada una al nivel 0,01 / 30 = 3,3e-4.
# Con los perfiles de ejemplo y una potencia del 80 %, el χ² detecta:
#
# - un año (109 542 pacientes): el nivel 1 asignado del 0,40 % al 0,49 %; el 2,
#   del 12,09 % al 12,53 %; el 5, del 1,40 % al 1,56 %; la casilla real 1 →
#   asignado 2, del 0,113 % al 0,160 %; la real 3 → asignado 2, del 2,14 % al 2,34 %;
# - 20 000 pacientes (el test rápido): el nivel 1 asignado del 0,40 % al 0,61 %;
#   el 2, del 12,09 % al 13,12 %; la casilla real 1 → asignado 2, del 0,113 % al
#   0,227 %; la real 3 → asignado 2, del 2,14 % al 2,60 %.
#
# Las 12 casillas a dos niveles o más de la diagonal esperan menos de 5 pacientes
# y usan la binomial exacta. Diez esperan menos de 1e-5 pacientes: fallan con
# uno solo. En un año, la real 2 → asignado 4 (0,73 esperados) falla con 6 y la
# real 4 → asignado 2 (0,25), con 4.

TRIAGE_N = 20_000


def with_noise(profiles, noise):
    return dataclasses.replace(profiles, triage=dataclasses.replace(profiles.triage, noise=noise))


@pytest.fixture(scope="module")
def arrivals():
    return load_profile(ARRIVALS)


@pytest.fixture(scope="module")
def exact(profiles, arrivals):
    t = profiles.triage
    return triage_matrix(severity_mixture(profiles, arrivals), t.thresholds, t.noise, t.bias)


def test_potencia_del_triaje_escrita_en_el_test(profiles, arrivals, exact):
    alpha = 0.01 / N_TRIAGE_CATEGORIES
    year = year_patients(profiles, arrivals)

    assert N_TRIAGE_CATEGORIES == 30
    assert year == 109_542
    assigned = exact.sum(axis=0)
    for n, level, p1 in [(year, 0, 0.00486), (year, 1, 0.12532), (year, 4, 0.01559)]:
        assert detectable_share(assigned[level], n, alpha) == pytest.approx(p1, abs=1e-5)
    for n, level, p1 in [(TRIAGE_N, 0, 0.00606), (TRIAGE_N, 1, 0.13123)]:
        assert detectable_share(assigned[level], n, alpha) == pytest.approx(p1, abs=1e-5)
    for n, cell, p1 in [
        (year, (0, 1), 0.00160),
        (year, (2, 1), 0.02337),
        (TRIAGE_N, (0, 1), 0.00227),
        (TRIAGE_N, (2, 1), 0.02604),
    ]:
        assert detectable_share(exact[cell], n, alpha) == pytest.approx(p1, abs=1e-5)
    # Casillas con menos de 5 esperados: 12 en un año.
    assert np.sum(year * exact < MIN_EXPECTED) == 12
    assert year * exact[1, 3] == pytest.approx(0.735, abs=1e-3)


def test_triaje_con_20000_pacientes(profiles, arrivals):
    result = check_triage(profiles, arrivals, seed=SEED, patients=TRIAGE_N)

    assert result.passed, [(d.name, d.p_value) for d in result.details if not d.passed]
    names = [d.name for d in result.details]
    assert len(names) == N_TRIAGE_CATEGORIES
    assert names[:6] == [*(f"asignado_{j}" for j in range(1, 6)), "real_1/asignado_1"]
    assert names[-1] == "real_5/asignado_5"
    criteria = {d.name: d.criterion.split()[0] for d in result.details}
    assert criteria["real_1/asignado_2"] == "p"  # χ²
    assert criteria["real_1/asignado_3"] == "binomial"


def test_detecta_mas_ruido_de_triaje(profiles, arrivals, exact):
    # El muestreador sortea con ruido 0,40 y los mismos umbrales; la hipótesis es
    # el perfil (0,335). La casilla real 3 → asignado 2 pasa del 2,14 % al 2,80 %:
    # potencia del 99,4 % con 20 000 pacientes.
    sampled = with_noise(profiles, 0.40)
    t = profiles.triage
    wrong = triage_matrix(severity_mixture(profiles, arrivals), t.thresholds, 0.40, t.bias)
    alpha = 0.01 / N_TRIAGE_CATEGORIES
    assert detection_power(exact[2, 1], wrong[2, 1], TRIAGE_N, alpha) >= 0.99

    result = check_triage(
        profiles, arrivals, seed=SEED, patients=TRIAGE_N, sampled_profiles=sampled
    )

    assert not result.passed
    assert "real_3/asignado_2" in {d.name for d in result.details if not d.passed}


def test_detecta_un_salto_imposible(profiles, arrivals):
    # Con ruido 1,5 en el muestreador, aparecen pacientes a dos niveles de la
    # diagonal, en casillas que la hipótesis da por casi vacías (real 3 →
    # asignado 1: 1,6e-7 esperados con 20 000): las prueba la binomial.
    t = profiles.triage
    sampled = dataclasses.replace(profiles, triage=dataclasses.replace(t, noise=1.5))

    result = check_triage(
        profiles, arrivals, seed=SEED, patients=TRIAGE_N, sampled_profiles=sampled
    )

    failed = {d.name: d for d in result.details if not d.passed}
    assert "real_3/asignado_1" in failed
    assert failed["real_3/asignado_1"].criterion.startswith("binomial")


def test_triaje_con_pocos_pacientes_es_un_error(profiles, arrivals):
    # El nivel 1 asignado (0,4 %) necesita al menos 5 esperados.
    with pytest.raises(ValueError, match=f"expected .* < {MIN_EXPECTED}"):
        check_triage(profiles, arrivals, seed=SEED, patients=1000)


def test_triaje_misma_semilla_mismo_resultado(profiles, arrivals):
    a = check_triage(profiles, arrivals, seed=SEED, patients=TRIAGE_N)
    b = check_triage(profiles, arrivals, seed=SEED, patients=TRIAGE_N)

    assert a == b


@pytest.mark.slow
def test_triaje_de_un_ano(profiles, arrivals):
    result = check_triage(profiles, arrivals, seed=SEED)

    assert result.passed, [(d.name, d.p_value) for d in result.details if not d.passed]
    assert result.criterion.startswith("all 30 categories")
