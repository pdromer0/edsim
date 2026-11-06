"""Validación estadística de la mezcla de bandas y motivos por contexto, y del triaje.

Potencia. Cada contexto sortea 25 000 pacientes (DEFAULT_MIXING_PATIENTS desde la
tarea 4.6a; antes, 20 000). Cada categoría se compara con
su probabilidad exacta con un chi² de 1 grado de libertad: 4 bandas, 17 motivos
(marginal sobre las bandas) y 68 motivos dentro de cada banda, 89 por contexto.
Con ALPHA = 0,01 y Bonferroni entre los 24 contextos y las 89 categorías, cada
prueba usa el nivel 0,01 / 2136 = 4,7e-6. Con una potencia del 80 % detecta:

- marginal, n = 25 000: un 0,5 % que pasa a 0,75 %; un 5 % que pasa a 5,76 %;
  un 8 % que pasa a 8,94 %; un 20 % que pasa a 21,38 %;
- dentro de la banda de 80-99, n = 4500 en la mañana laborable (18 % de los
  pacientes): un 5 % que pasa a 6,80 %; un 20 % que pasa a 23,26 %; la disnea
  de esa banda en invierno, 19,9 %, si pasa a 23,2 %. De noche en fin de semana
  hay menos mayores (n ≈ 3790): un 5 % que pasa a 6,97 %.

Es decir, errores relativos de alrededor del 50 % en los motivos raros y del
7-15 % en los frecuentes en la marginal, y del 16-36 % dentro de la banda de
más edad; un error más pequeño puede pasar. Con 25 000 pacientes, el menor
esperado dentro de una banda es 6,1 (la parada en 15-44, tarde laborable de
invierno), por encima de MIN_EXPECTED; con los 20 000 de antes de la tarea 4.6a
serían 4,9. Con solo 2 contextos (el test rápido) el
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
from edsim.profiles.durations import ASSESSMENT, duration_model
from edsim.profiles.mixing import band_probabilities, reason_probabilities
from edsim.profiles.severity import severity_mixture, triage_matrix
from edsim.profiles.validation import (
    MIN_EXPECTED,
    MIN_GROUP_PATIENTS,
    N_CATEGORIES,
    N_DURATION_CATEGORIES,
    N_TRIAGE_CATEGORIES,
    N_WORKUP_CATEGORIES,
    check_durations,
    check_mixing,
    check_triage,
    check_workup,
    detectable_share,
    detection_power,
    year_patients,
)
from edsim.profiles.workup import workup_model

EXAMPLE = Path(__file__).parent / "data" / "perfiles_ejemplo.toml"
ARRIVALS = Path(__file__).parent / "data" / "llegadas_ejemplo.toml"
SEED = 2026
N = 25_000  # DEFAULT_MIXING_PATIENTS
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
    for p0, p1 in [(0.005, 0.0075), (0.05, 0.0576), (0.08, 0.0894), (0.20, 0.2138)]:
        assert detectable_share(p0, N, alpha) == pytest.approx(p1, abs=1e-4)
    # Dentro de la banda de 80-99, con sus pacientes.
    for n, p0, p1 in [(4500, 0.05, 0.0680), (4500, 0.20, 0.2326), (3787, 0.05, 0.0697)]:
        assert detectable_share(p0, n, alpha) == pytest.approx(p1, abs=1e-4)


def test_potencia_contra_la_disnea_de_los_mayores(profiles):
    # La disnea en 80-99 en la mañana de invierno es el 19,9 %; con ×1,5 en esa
    # banda pasa a 1,5·p / (1 + 0,5·p) = 27,2 %. Con unos 4500 pacientes de la
    # banda, la potencia es mayor del 99,99999 % al nivel de un contexto
    # (0,01 / 89) y también al de los 24 (0,01 / 2136).
    winter = OPPOSITE[0]
    p0 = reason_probabilities(profiles, winter, OLDEST)[DISNEA]
    p1 = 1.5 * p0 / (1 + 0.5 * p0)
    n = int(N * band_probabilities(profiles.population, winter)[OLDEST])

    assert p0 == pytest.approx(0.1995, abs=1e-4)  # 0,1988 hasta la tarea 4.6a
    assert n == 4500
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
    # La parada (0,3 %) necesita al menos 5 pacientes esperados por contexto: con
    # 200 pacientes el test pasaría de forma vacía.
    with pytest.raises(ValueError, match=f"expected .* < {MIN_EXPECTED}"):
        check_mixing(profiles, START, seed=SEED, patients=200, contexts=OPPOSITE)


def test_misma_semilla_mismo_resultado(profiles):
    # 25 000 pacientes: con 2000, la parada en 15-44 tendría menos de 1 esperado.
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
#   del 12,10 % al 12,53 %; el 5, del 1,40 % al 1,56 %; la casilla real 1 →
#   asignado 2, del 0,036 % al 0,063 %; la real 3 → asignado 2, del 2,19 % al 2,38 %;
# - 20 000 pacientes (el test rápido): el nivel 1 asignado del 0,40 % al 0,61 %;
#   el 2, del 12,10 % al 13,12 %; la casilla real 1 → asignado 2, del 0,036 % al
#   0,103 %; la real 3 → asignado 2, del 2,19 % al 2,65 %.
#
# Desde la tarea 4.6a, con las paradas casi siempre de nivel 1 real y asignado, la
# casilla real 1 → asignado 2 baja del 0,117 % al 0,036 %.
#
# Las 12 casillas a dos niveles o más de la diagonal esperan menos de 5 pacientes
# y usan la binomial exacta. Diez esperan menos de 1e-5 pacientes: fallan con
# uno solo. En un año, la real 2 → asignado 4 (0,85 esperados) falla con 6 y la
# real 4 → asignado 2 (0,29), con 4.

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
    for n, level, p1 in [(year, 0, 0.00486), (year, 1, 0.12534), (year, 4, 0.01559)]:
        assert detectable_share(assigned[level], n, alpha) == pytest.approx(p1, abs=1e-5)
    for n, level, p1 in [(TRIAGE_N, 0, 0.00606), (TRIAGE_N, 1, 0.13124)]:
        assert detectable_share(assigned[level], n, alpha) == pytest.approx(p1, abs=1e-5)
    for n, cell, p1 in [
        (year, (0, 1), 0.00063),
        (year, (2, 1), 0.02383),
        (TRIAGE_N, (0, 1), 0.00103),
        (TRIAGE_N, (2, 1), 0.02652),
    ]:
        assert detectable_share(exact[cell], n, alpha) == pytest.approx(p1, abs=1e-5)
    # Casillas con menos de 5 esperados: 12 en un año.
    assert np.sum(year * exact < MIN_EXPECTED) == 12
    assert year * exact[1, 3] == pytest.approx(0.853, abs=1e-3)  # 0,747 hasta la tarea 4.6a


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
    # el perfil (0,334). La casilla real 3 → asignado 2 pasa del 2,19 % al 2,87 %:
    # potencia del 99,6 % con 20 000 pacientes.
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
    # asignado 1: 6,2e-10 esperados con 20 000): las prueba la binomial.
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


# --- Pruebas y duraciones ------------------------------------------------------
#
# Potencia. check_workup prueba 134 categorías (nivel 0,01/134) y check_durations,
# 64 (0,01/64). Con una potencia del 80 %, con 20 000 pacientes (un año: 109 542):
# - pedir analítica en el quintil central de G, 44,9 %: se ve si pasa a 48,7 %
#   (46,5 % en un año);
# - pedir analítica entre los infratriados (2020 pacientes), 59,5 %: 64,7 % (61,7 %);
# - valoración del nivel real 3 (7164 pacientes) bajo su mediana exacta, 50 %:
#   52,7 % (51,2 %).
# (Recalculados en la tarea 4.6a; antes, 45,0 → 48,8 y 46,6 %, y 59,8 → 65,0 y 62,0 %.)
# Los tests rápidos usan 20 000 pacientes (unos 2,5 s cada comprobación) y los
# slow, un año (unos 14 s): con 20 000, las versiones incorrectas V1 y V2 solo se
# ven con firmeza en una categoría o en ninguna; con un año, en varias.

WORKUP_N = 20_000


def with_test(profiles, key, **changes):
    tests = tuple(
        dataclasses.replace(t, **changes) if t.key == key else t for t in profiles.diagnostic_tests
    )
    return dataclasses.replace(profiles, diagnostic_tests=tests)


@pytest.fixture(scope="module")
def workup(profiles, arrivals):
    return workup_model(profiles, arrivals)


@pytest.fixture(scope="module")
def durations(profiles, arrivals):
    return duration_model(profiles, arrivals)


def test_potencia_de_pruebas_y_duraciones_escrita(profiles, arrivals, workup, durations):
    assert N_WORKUP_CATEGORIES == 20 + 20 + 4 + 68 + 20 + 2 == 134
    assert N_DURATION_CATEGORIES == 2 + 8 + 20 + 34 == 64
    aw, ad = 0.01 / N_WORKUP_CATEGORIES, 0.01 / N_DURATION_CATEGORIES
    year = year_patients(profiles, arrivals)
    middle = workup.order_by_severity()[2, 0]
    under = workup.order_given_undertriage()[0]
    level_3 = durations.reason_level.sum(axis=0)[2]

    assert middle == pytest.approx(0.4491, abs=5e-5)
    assert under == pytest.approx(0.5949, abs=5e-5)
    for n, p1 in [(WORKUP_N, 0.4869), (year, 0.4653)]:
        assert detectable_share(middle, n // 5, aw) == pytest.approx(p1, abs=1e-4)
    for n, p1 in [(WORKUP_N, 0.6471), (year, 0.6173)]:
        n_under = int(n * workup.undertriage_share())
        assert detectable_share(under, n_under, aw) == pytest.approx(p1, abs=1e-4)
    for n, p1 in [(WORKUP_N, 0.5273), (year, 0.5117)]:
        assert detectable_share(0.5, int(n * level_3), ad) == pytest.approx(p1, abs=1e-4)


def test_pruebas_con_20000_pacientes(profiles, arrivals):
    result = check_workup(profiles, arrivals, seed=SEED, patients=WORKUP_N)

    assert result.passed, [(d.name, d.p_value) for d in result.details if not d.passed]
    names = [d.name for d in result.details]
    assert len(names) == len(set(names)) == N_WORKUP_CATEGORIES
    assert names[0] == "pedir/analitica/quintil_1"
    assert names[20] == "alterado/analitica/quintil_1"
    assert names[40] == "pedir/analitica/infratriaje"
    assert names[44] == "pedir/analitica/traumatismo"
    assert names[-3:] == ["pedir/imagen/real_5", "ronda/mediana", "ronda/p90"]
    criteria = {d.name: d.criterion.split()[0] for d in result.details}
    # El ECG de las paradas (99 %) deja 1 paciente esperado fuera: binomial.
    assert criteria["pedir/ecg/parada"] == "binomial"
    assert criteria["pedir/analitica/quintil_3"] == "p"


def test_duraciones_con_20000_pacientes(profiles, arrivals):
    result = check_durations(profiles, arrivals, seed=SEED, patients=WORKUP_N)

    assert result.passed, [(d.name, d.p_value) for d in result.details if not d.passed]
    names = [d.name for d in result.details]
    assert len(names) == len(set(names)) == N_DURATION_CATEGORIES
    assert names[:3] == ["triaje/mediana", "triaje/p90", "respuesta/analitica/mediana"]
    assert "valoracion/real_1/p90" in names
    assert names[-1] == "reevaluacion/otros/mediana"


def test_detecta_mas_alterados(profiles, arrivals, workup):
    # El muestreador sortea la analítica alterada con base 36 y no 30; la hipótesis
    # es el perfil. En el quintil central el alterado pasa del 28,6 % al 34,5 %:
    # potencia mayor del 99,99 % con unos 4000 pacientes.
    sampled = with_test(profiles, "analitica", abnormal_pct=36)
    before = workup.abnormal_by_severity()[::-1][2, 0]
    after = workup_model(sampled, arrivals).abnormal_by_severity()[::-1][2, 0]
    assert (before, after) == pytest.approx((0.2862, 0.3446), abs=5e-5)
    assert detection_power(before, after, WORKUP_N // 5, 0.01 / N_WORKUP_CATEGORIES) > 0.9999

    result = check_workup(
        profiles, arrivals, seed=SEED, patients=WORKUP_N, sampled_profiles=sampled
    )

    assert "alterado/analitica/quintil_3" in {d.name for d in result.details if not d.passed}


def test_detecta_otro_odds_ratio_de_gravedad(profiles, arrivals, workup):
    # OR 5 y no 3,3 en la analítica: más pedidas en el quintil más grave
    # (88,6 → 92,1 %) y menos en el más leve (12,9 → 9,1 %), potencia > 99,9 %.
    # Los quintiles centrales apenas cambian: la curva gira alrededor de G ≈ 0.
    sampled = with_test(profiles, "analitica", severity_or=5.0)
    before = workup.order_by_severity()[::-1][:, 0]
    after = workup_model(sampled, arrivals).order_by_severity()[::-1][:, 0]
    alpha = 0.01 / N_WORKUP_CATEGORIES
    for q in (0, 4):
        assert detection_power(before[q], after[q], WORKUP_N // 5, alpha) > 0.999

    result = check_workup(
        profiles, arrivals, seed=SEED, patients=WORKUP_N, sampled_profiles=sampled
    )

    failed = {d.name for d in result.details if not d.passed}
    assert {"pedir/analitica/quintil_1", "pedir/analitica/quintil_5"} <= failed


def test_detecta_otro_k(profiles, arrivals, durations):
    # Traumatismo con k = 1 y no 0,85: por debajo de la mediana exacta de su
    # valoración queda el 40,5 % de sus pacientes, no el 50 %; potencia de 1,0.
    sampled = dataclasses.replace(
        profiles,
        reasons=tuple(
            dataclasses.replace(r, duration_factor=1.0) if r.key == "traumatismo" else r
            for r in profiles.reasons
        ),
    )
    m = REASON_KEYS.index("traumatismo")
    x = durations.quantile(ASSESSMENT, 0.5, reason=m)
    p1 = duration_model(sampled, arrivals).cdf(ASSESSMENT, x, reason=m)
    assert p1 == pytest.approx(0.4055, abs=5e-4)

    result = check_durations(
        profiles, arrivals, seed=SEED, patients=WORKUP_N, sampled_profiles=sampled
    )

    failed = {d.name for d in result.details if not d.passed}
    assert "valoracion/traumatismo/mediana" in failed
    assert not any(name.startswith(("triaje", "respuesta")) for name in failed)


@pytest.mark.parametrize("check", [check_workup, check_durations])
def test_pocos_pacientes_en_el_grupo_mas_pequeno_es_un_error(profiles, arrivals, check):
    # Desde la tarea 4.6a, el grupo más pequeño es la parada (0,302 %), que espera 30,2
    # pacientes con 10 000: menos de 50. Antes lo era el nivel real 1 (0,42 %, 42,3).
    assert MIN_GROUP_PATIENTS == 50
    with pytest.raises(ValueError, match=r"too few patients for parada: expected 30\.2 < 50"):
        check(profiles, arrivals, seed=SEED, patients=10_000)


def test_pruebas_misma_semilla_mismo_resultado(profiles, arrivals):
    a = check_durations(profiles, arrivals, seed=SEED, patients=WORKUP_N)
    b = check_durations(profiles, arrivals, seed=SEED, patients=WORKUP_N)

    assert a == b


@pytest.mark.slow
def test_pruebas_de_un_ano(profiles, arrivals):
    result = check_workup(profiles, arrivals, seed=SEED)

    assert result.passed, [(d.name, d.p_value) for d in result.details if not d.passed]
    assert result.criterion.startswith("all 134 categories")


@pytest.mark.slow
def test_duraciones_de_un_ano(profiles, arrivals):
    result = check_durations(profiles, arrivals, seed=SEED)

    assert result.passed, [(d.name, d.p_value) for d in result.details if not d.passed]
    assert result.criterion.startswith("all 64 categories")
