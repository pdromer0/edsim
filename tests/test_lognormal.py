"""El módulo neutro de la lognormal y su reexportación desde el motor."""

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
