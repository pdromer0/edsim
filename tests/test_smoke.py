import subprocess
import sys
import tomllib
from importlib.metadata import version
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_importa_paquete():
    import edsim
    import edsim.cli

    assert edsim.cli.main is not None


def test_version_coincide_con_metadatos():
    with PYPROJECT.open("rb") as f:
        version_pyproject = tomllib.load(f)["project"]["version"]

    assert version("edsim") == version_pyproject


def test_cli_version():
    # El script instalado está junto al intérprete del venv.
    script = Path(sys.executable).parent / "edsim"

    resultado = subprocess.run(
        [str(script), "--version"], capture_output=True, text=True, check=False
    )

    assert resultado.returncode == 0
    assert resultado.stdout.strip() == f"edsim {version('edsim')}"
