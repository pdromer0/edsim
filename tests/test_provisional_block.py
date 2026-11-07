"""El modelo provisional exige el bloque provisional del centro (tarea 4.9).

Sin ``[triaje]``, ``[duraciones]`` y ``[pruebas]``, cada punto de entrada del modelo
provisional falla pronto, antes de simular o de escribir nada, con un mensaje que
nombra las tres tablas.
"""

from pathlib import Path

import pytest

from edsim.arrivals.profile import load_profile
from edsim.engine.center import load_center, read_center_values
from edsim.engine.clinical import ProvisionalSampler
from edsim.engine.engine import simulate_ed
from edsim.engine.events import MemorySink
from edsim.engine.validation import validate_engine
from edsim.runs import RunConfigurationError, offered_load, simulate_run, summarize_center
from edsim.seeds import child_streams

DATA = Path(__file__).parent / "data"
TABLES = r"\[triaje\], \[duraciones\] and \[pruebas\]"


def without_block(text: str) -> str:
    """El centro de ejemplo sin las tres tablas del bloque: lo de antes de [triaje] y [destino]."""
    return text[: text.index("[triaje]")] + text[text.index("[destino]") :]


@pytest.fixture
def center_path(tmp_path):
    path = tmp_path / "centro.toml"
    path.write_text(without_block((DATA / "centro_ejemplo.toml").read_text(encoding="utf-8")))
    return path


@pytest.fixture
def center(center_path):
    c = load_center(center_path)
    assert not c.has_provisional  # guarda: el fichero de verdad no tiene el bloque
    return c


@pytest.fixture
def profile():
    return load_profile(DATA / "llegadas_ejemplo.toml")


def test_el_muestreador_provisional(center):
    with pytest.raises(ValueError, match=TABLES):
        ProvisionalSampler(center, child_streams(1, 5)[1:])


def test_simulate_ed_sin_perfiles_falla_antes_del_primer_evento(center, profile):
    sink = MemorySink()
    with pytest.raises(ValueError, match=TABLES):
        simulate_ed(center, profile, 1, 7, sink=sink, warmup_days=0)
    assert sink.events == []


def test_simulate_run_sin_perfiles_no_crea_nada(center_path, tmp_path):
    parent = tmp_path / "resultados"
    output = parent / "r7"
    with pytest.raises(RunConfigurationError, match=TABLES) as caught:
        simulate_run(
            center_path,
            DATA / "llegadas_ejemplo.toml",
            1,
            7,
            output_dir=output,
            warmup_days=0,
            origin="cli",
        )
    assert str(caught.value).startswith(f"{center_path}: ")
    # Ni la carpeta de salida ni su padre: falla antes de crear nada.
    assert not output.exists()
    assert not parent.exists()


def test_simulate_run_con_perfiles_no_necesita_el_bloque(center_path, tmp_path):
    result = simulate_run(
        center_path,
        DATA / "llegadas_ejemplo.toml",
        1,
        7,
        output_dir=tmp_path / "r7",
        warmup_days=0,
        origin="cli",
        profiles=DATA / "perfiles_ejemplo.toml",
    )
    assert result.info.is_clinical
    assert result.violations == ()


def test_offered_load_sin_perfiles(center, profile):
    with pytest.raises(ValueError, match=TABLES):
        offered_load(center, profile, 1, sample_size=10)


def test_summarize_center(center_path):
    values = read_center_values(center_path)
    with pytest.raises(ValueError, match=TABLES):
        summarize_center(values)


def test_validate_engine_falla_antes_de_simular(center, profile):
    with pytest.raises(ValueError, match=TABLES):
        validate_engine(center, profile, replicas=2)
