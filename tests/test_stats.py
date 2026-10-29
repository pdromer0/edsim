import dataclasses
import math

import pytest

from edsim.stats import Summary, summarize, t_critical

# Caso a mano con los valores 1, 2, 3, 4, 5:
#   media = 3
#   varianza muestral = (4 + 1 + 0 + 1 + 4) / (5 − 1) = 2,5  →  s = √2,5 ≈ 1,581139
#   error estándar = s / √5 = √0,5 ≈ 0,707107
#   95 %: t(0,975; 4) = 2,776445 (tablas)  →  semiamplitud ≈ 1,963243  →  IC = [1,036757; 4,963243]
#   90 %: t(0,95; 4)  = 2,131847 (tablas)  →  semiamplitud ≈ 1,507443  →  IC = [1,492557; 4,507443]
VALUES = [1.0, 2.0, 3.0, 4.0, 5.0]


def test_caso_a_mano_95():
    s = summarize(VALUES)

    assert isinstance(s, Summary)
    assert s.n == 5
    assert s.confidence == 0.95
    assert s.mean == pytest.approx(3.0)
    assert s.std == pytest.approx(math.sqrt(2.5))
    assert s.sem == pytest.approx(math.sqrt(0.5))
    assert s.ci_low == pytest.approx(1.036757, rel=1e-5)
    assert s.ci_high == pytest.approx(4.963243, rel=1e-5)


def test_caso_a_mano_90():
    s = summarize(VALUES, confidence=0.90)

    assert s.ci_low == pytest.approx(1.492557, rel=1e-5)
    assert s.ci_high == pytest.approx(4.507443, rel=1e-5)


def test_t_critical_tablas():
    # Los mismos valores de tablas del caso a mano: n = 5 → 4 grados de libertad.
    assert t_critical(5, 0.95) == pytest.approx(2.776445, rel=1e-6)
    assert t_critical(5, 0.90) == pytest.approx(2.131847, rel=1e-6)


def test_t_critical_tiende_a_la_normal():
    # Con muchos valores, la t de Student se acerca al 1,96 de la normal.
    assert t_critical(10_000, 0.95) == pytest.approx(1.96, abs=1e-3)


@pytest.mark.parametrize(("n", "confidence"), [(1, 0.95), (5, 0.0), (5, 1.0)])
def test_t_critical_invalido(n, confidence):
    with pytest.raises(ValueError):
        t_critical(n, confidence)


def test_valores_constantes():
    s = summarize([2.0, 2.0, 2.0])

    assert s.std == 0
    assert s.ci_low == s.ci_high == 2.0


@pytest.mark.parametrize("values", [[], [1.0]])
def test_pocos_valores(values):
    # Con un solo valor no hay desviación típica muestral (n − 1 = 0).
    with pytest.raises(ValueError, match="at least 2"):
        summarize(values)


@pytest.mark.parametrize("confidence", [0.0, 1.0, 1.5, -0.1])
def test_confianza_invalida(confidence):
    with pytest.raises(ValueError, match="confidence"):
        summarize(VALUES, confidence=confidence)


def test_inmutable():
    s = summarize(VALUES)

    with pytest.raises(dataclasses.FrozenInstanceError):
        s.mean = 0.0
