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


# --- El modelo clínico ignora el bloque -------------------------------------------------


@pytest.mark.slow
def test_el_clinico_ignora_el_bloque_y_las_dos_se_emparejan_como_plantilla(tmp_path):
    from edsim.runs import (
        RunStore,
        compare_run_summary,
        compare_runs,
        read_run_episode_truth,
        read_run_results,
    )
    from edsim.runs.compare import pairing_category

    config = Path(__file__).parents[1] / "config"
    # La plantilla del centro base del hito 4 (config/centro.toml hasta la tarea 5.6,
    # congelado en centro_h4.toml) más el bloque de centro_ejemplo.toml: el provisional
    # necesita [destino], que el centro del hito 5 no tiene.
    base = DATA / "centro_h4.toml"
    example = (DATA / "centro_ejemplo.toml").read_text(encoding="utf-8")
    block = example[example.index("[triaje]") : example.index("[destino]")]
    with_block = tmp_path / "con_bloque.toml"
    with_block.write_text(base.read_text(encoding="utf-8") + "\n" + block)
    assert load_center(with_block).has_provisional
    assert not load_center(base).has_provisional

    # Un catálogo por centro, con el mismo run_id: el log lo lleva en cada evento.
    stores = {}
    for name, center in (("sin", base), ("con", with_block)):
        stores[name] = RunStore(tmp_path / name)
        simulate_run(
            center,
            config / "llegadas.toml",
            3,
            2026,
            output_dir=stores[name].root / "r2026",
            warmup_days=1,
            origin="cli",
            profiles=DATA / "perfiles_h4.toml",
        )

    # El mismo log byte a byte: con el modelo clínico, el bloque no cambia nada.
    logs = [(s.root / "r2026" / "eventos.jsonl").read_bytes() for s in stores.values()]
    assert logs[0] == logs[1]

    a, b = (read_run_results(s, "r2026") for s in stores.values())
    assert pairing_category(a, b) == "template"
    summary = compare_run_summary(a, b)
    assert len(summary.center_differences) == 6
    assert all(d.before is None and d.after is not None for d in summary.center_differences)
    truth_a, truth_b = (read_run_episode_truth(s, "r2026") for s in stores.values())
    comparison = compare_runs(a, b, truth_a, truth_b)
    assert comparison.pairing.kind == "same_draws"
    assert all(d.changed == 0 for d in comparison.pairing.draw_differences)


# --- La CLI con config/centro.toml, que no tiene el bloque ---------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["motor", "simular", "--provisional", "--dias", "1", "--calentamiento", "0"],
        ["motor", "validar", "--centro", "config/centro.toml"],
    ],
    ids=["simular", "validar"],
)
def test_la_cli_con_el_provisional_y_config_centro_es_un_error_de_uso(
    argv, monkeypatch, tmp_path, capsys
):
    from edsim.cli import main

    monkeypatch.chdir(Path(__file__).parents[1])
    monkeypatch.setattr("edsim.runs.service.simulate_ed", lambda *a, **k: pytest.fail("simuló"))
    monkeypatch.setattr("edsim.cli.validate_engine", lambda *a, **k: pytest.fail("validó"))
    out_dir = tmp_path / "salida"

    with pytest.raises(SystemExit) as exit_info:
        main([*argv, "--salida", str(out_dir)])
    captured = capsys.readouterr()

    assert exit_info.value.code == 2
    assert (
        "--centro config/centro.toml: el modelo provisional necesita las tablas [triaje], "
        "[duraciones] y [pruebas] del centro, y este no las tiene; su centro es "
        "tests/data/centro_ejemplo.toml"
    ) in captured.err
    assert captured.out == ""
    assert not out_dir.exists()
