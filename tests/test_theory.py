import dataclasses

import pytest

from edsim.queueing.theory import MM1Theory, mm1_theory


def test_valores_conocidos():
    # Caso de la especificación: λ = 0,5, μ = 1.
    t = mm1_theory(lam=0.5, mu=1.0)

    assert isinstance(t, MM1Theory)
    assert t.rho == pytest.approx(0.5)
    assert t.wq == pytest.approx(1.0)
    assert t.w == pytest.approx(2.0)
    assert t.lq == pytest.approx(0.5)
    assert t.l == pytest.approx(1.0)


def test_caso_de_referencia():
    # λ = 0,8, μ = 1, el escenario de referencia del hito, calculado a mano:
    # Wq = 0,8 / 0,2 = 4; W = 1 / 0,2 = 5; Lq = 0,64 / 0,2 = 3,2; L = 0,8 / 0,2 = 4.
    t = mm1_theory(lam=0.8, mu=1.0)

    assert t.rho == pytest.approx(0.8)
    assert t.wq == pytest.approx(4.0)
    assert t.w == pytest.approx(5.0)
    assert t.lq == pytest.approx(3.2)
    assert t.l == pytest.approx(4.0)


def test_mu_distinto_de_uno():
    # λ = 2, μ = 5, calculado a mano: ρ = 0,4; W = 1/3; Wq = 0,4/3 = 2/15;
    # Lq = 0,16/0,6 = 4/15; L = 0,4/0,6 = 2/3. Con μ ≠ 1 se detectan fórmulas
    # que solo aciertan por casualidad cuando μ = 1.
    t = mm1_theory(lam=2.0, mu=5.0)

    assert t.rho == pytest.approx(0.4)
    assert t.wq == pytest.approx(2 / 15)
    assert t.w == pytest.approx(1 / 3)
    assert t.lq == pytest.approx(4 / 15)
    assert t.l == pytest.approx(2 / 3)


@pytest.mark.parametrize(
    ("lam", "mu"),
    [(0.1, 1.0), (0.5, 1.0), (0.9, 1.0), (0.99, 1.0), (2.0, 5.0), (3.0, 3.5)],
)
def test_ley_de_little(lam, mu):
    t = mm1_theory(lam=lam, mu=mu)

    assert t.l == pytest.approx(lam * t.w)
    assert t.lq == pytest.approx(lam * t.wq)
    # Tiempo en el sistema = espera en cola + tiempo medio de servicio.
    assert t.w == pytest.approx(t.wq + 1 / mu)


@pytest.mark.parametrize(
    ("lam", "mu"),
    [(0.0, 1.0), (-1.0, 1.0), (0.5, 0.0), (0.5, -1.0)],
)
def test_tasas_no_positivas(lam, mu):
    with pytest.raises(ValueError, match="positive"):
        mm1_theory(lam=lam, mu=mu)


@pytest.mark.parametrize(("lam", "mu"), [(1.0, 1.0), (1.5, 1.0)])
def test_inestable(lam, mu):
    # Con ρ ≥ 1 la cola crece sin límite: no hay estado estacionario.
    with pytest.raises(ValueError, match="rho"):
        mm1_theory(lam=lam, mu=mu)


def test_inmutable():
    t = mm1_theory(lam=0.5, mu=1.0)

    with pytest.raises(dataclasses.FrozenInstanceError):
        t.rho = 0.9
