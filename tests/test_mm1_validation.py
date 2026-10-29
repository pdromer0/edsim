"""Validación estadística: la teoría de la M/M/1 cae dentro del IC al 95 %.

Con intervalos al 95 %, alrededor de una de cada veinte comparaciones correctas
cae fuera por azar. Se usa la semilla fija de la especificación y los
resultados se interpretan en conjunto.
"""

import pytest

from edsim.queueing.replications import compare_mm1
from edsim.queueing.report import format_comparison

pytestmark = pytest.mark.slow


@pytest.mark.parametrize("rho", [0.5, 0.8])
def test_teoria_dentro_del_ic(rho):
    c = compare_mm1(lam=rho, mu=1.0, duration=10_000.0, warmup=1_000.0, replicas=20, seed=2026)

    assert all(m.theory_in_ci for m in c.metrics), f"\nρ = {rho}\n{format_comparison(c)}"
