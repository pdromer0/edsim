"""Validación estadística de la mezcla de bandas y motivos por contexto.

Potencia. Cada contexto sortea 20 000 pacientes y cada categoría (4 bandas y 17
motivos) se compara con su probabilidad exacta con un chi² de 1 grado de libertad.
Con ALPHA = 0,01 y Bonferroni entre los 24 contextos y las 21 categorías, cada
prueba usa el nivel 0,01 / 504 = 2,0e-5. Con una potencia del 80 % detecta:

    un 0,5 % que pasa a 0,76 %; un 5 % que pasa a 5,80 %;
    un 8 % que pasa a 8,99 %;   un 20 % que pasa a 21,45 %.

Es decir, errores relativos del 50 % en los motivos raros (parada) y del 12-16 %
en los frecuentes; un error más pequeño puede pasar. Con solo 2 contextos (el test
rápido) el nivel es 0,01 / 42 y la potencia, algo mayor.
"""

import dataclasses
from pathlib import Path

import numpy as np
import pytest
from profiles_factory import START

from edsim.profiles.config import load_profiles
from edsim.profiles.context import ArrivalContext, all_contexts
from edsim.profiles.validation import (
    MIN_EXPECTED,
    N_CATEGORIES,
    check_mixing,
    detectable_share,
)

EXAMPLE = Path(__file__).parent / "data" / "perfiles_ejemplo.toml"
SEED = 2026
N = 20_000
OPPOSITE = (ArrivalContext(0, 0, 0), ArrivalContext(2, 1, 2))  # mañana laborable de invierno
# frente a noche de fin de semana de verano


@pytest.fixture(scope="module")
def profiles():
    return load_profiles(EXAMPLE)


def test_potencia_escrita_en_el_test():
    alpha = 0.01 / (24 * N_CATEGORIES)

    assert N_CATEGORIES == 21
    for p0, p1 in [(0.005, 0.0076), (0.05, 0.0580), (0.08, 0.0899), (0.20, 0.2145)]:
        assert detectable_share(p0, N, alpha) == pytest.approx(p1, abs=1e-4)


def test_dos_contextos_opuestos(profiles):
    result = check_mixing(profiles, START, seed=SEED, patients=N, contexts=OPPOSITE)

    assert result.passed, [(d.name, d.p_value) for d in result.details]
    assert [d.name for d in result.details] == [
        "manana/laborable/invierno",
        "noche/fin_de_semana/verano",
    ]
    assert all(len(d.details) == N_CATEGORIES for d in result.details)
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


def test_pocos_pacientes_es_un_error(profiles):
    # La parada (0,5 %) necesita al menos 5 pacientes esperados por contexto: con
    # 200 pacientes el test pasaría de forma vacía.
    with pytest.raises(ValueError, match=f"expected .* < {MIN_EXPECTED}"):
        check_mixing(profiles, START, seed=SEED, patients=200, contexts=OPPOSITE)


def test_misma_semilla_mismo_resultado(profiles):
    a = check_mixing(profiles, START, seed=SEED, patients=2000, contexts=OPPOSITE[:1])
    b = check_mixing(profiles, START, seed=SEED, patients=2000, contexts=OPPOSITE[:1])

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
