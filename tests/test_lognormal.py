"""El módulo neutro de la lognormal y su reexportación desde el motor."""

import numpy as np
import pytest
from scipy import integrate, stats

import edsim.engine.clinical as clinical
import edsim.lognormal as lognormal


def test_el_motor_reexporta_los_mismos_objetos():
    # Los imports antiguos (engine/validation.py, runs/summary.py y los tests)
    # siguen funcionando y dan exactamente lo mismo.
    assert clinical.lognormal_params is lognormal.lognormal_params
    assert clinical.Z90 is lognormal.Z90


def test_lognormal_no_importa_el_motor():
    import subprocess
    import sys

    script = (
        "import sys, edsim.lognormal\n"
        "bad = sorted(n for n in sys.modules if n.startswith('edsim.engine'))\n"
        "assert not bad, bad\n"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr


def test_densidad_frente_a_scipy():
    mu, sigma = lognormal.lognormal_params(20, 45)
    x = np.array([0.5, 5.0, 20.0, 45.0, 300.0])

    assert lognormal.lognormal_pdf(x, mu, sigma) == pytest.approx(
        stats.lognorm.pdf(x, sigma, scale=np.exp(mu)), rel=1e-12
    )
    # Media 24,43 de la especificación (base 20 y 45 minutos), integrando x · f(x).
    mean, _ = integrate.quad(lambda t: t * float(lognormal.lognormal_pdf(t, mu, sigma)), 0, np.inf)
    assert mean == pytest.approx(24.43, abs=0.005)


def test_densidad_cero_fuera_de_los_positivos():
    mu, sigma = lognormal.lognormal_params(20, 45)
    assert lognormal.lognormal_pdf([-1.0, 0.0], mu, sigma).tolist() == [0.0, 0.0]
    with pytest.raises(ValueError, match="sigma must be positive"):
        lognormal.lognormal_pdf(1.0, mu, 0.0)
