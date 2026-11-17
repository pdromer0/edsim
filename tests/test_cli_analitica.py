"""La CLI de `edsim analitica refrescar` (tarea 8.7): fina, sin lógica.

La lógica del bucle se prueba en `test_refrescar.py`. Aquí, solo lo que pone la CLI: sus
opciones, los errores de uso y que el bucle recibe la carpeta y el intervalo pedidos.
"""

from pathlib import Path

import pytest

from edsim import cli
from edsim.analytics import RefreshSummary


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / "analitica"
    folder.mkdir()
    (folder / "dbt_project.yml").write_text("name: prueba\n")
    return folder


def test_refrescar_lanza_el_bucle_con_la_carpeta_y_el_intervalo(project, monkeypatch, capsys):
    """El bucle recibe el intervalo de --cada y una construcción en la carpeta de --analitica;
    Ctrl+C acaba con código 0."""
    seen = {}

    def fake_builder(uv, folder):
        seen["folder"] = folder
        return lambda: pytest.fail("la CLI no construye: lo hace el bucle")

    def fake_refresh(build, clock, every, emit):
        seen["every"] = every
        emit("Parado con Ctrl+C antes de acabar la primera vuelta")
        return RefreshSummary(0, 0, None)

    monkeypatch.setattr(cli, "dbt_builder", fake_builder)
    monkeypatch.setattr(cli, "refresh", fake_refresh)

    code = cli.main(["analitica", "refrescar", "--cada", "30", "--analitica", str(project)])

    assert code == 0
    assert seen == {"folder": project.resolve(), "every": 30.0}
    out = capsys.readouterr().out
    assert "cada 30 s" in out
    assert out.endswith("Parado con Ctrl+C antes de acabar la primera vuelta\n")


def test_refrescar_sin_proyecto_dbt_es_un_error_de_uso(tmp_path, monkeypatch, capsys):
    """Una carpeta sin `dbt_project.yml` sale con código 2 antes de lanzar nada."""
    monkeypatch.setattr(cli, "refresh", lambda *a, **k: pytest.fail("lanzó el bucle"))

    with pytest.raises(SystemExit) as caught:
        cli.main(["analitica", "refrescar", "--analitica", str(tmp_path)])

    assert caught.value.code == 2
    assert "le falta dbt_project.yml" in capsys.readouterr().err


@pytest.mark.parametrize("cada", ["0", "-5", "nan", "inf", "uno"])
def test_refrescar_con_un_intervalo_que_no_es_positivo_es_un_error_de_uso(cada, capsys):
    with pytest.raises(SystemExit) as caught:
        cli.main(["analitica", "refrescar", "--cada", cada])

    assert caught.value.code == 2
    assert "los segundos deben ser un número positivo" in capsys.readouterr().err


def test_refrescar_por_defecto_cada_60_s_en_analitica():
    args = cli.build_parser().parse_args(["analitica", "refrescar"])

    assert (args.cada, Path(args.analitica)) == (60.0, Path("analitica"))
