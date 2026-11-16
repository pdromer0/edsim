"""`edsim almacen cargar-verdad` sin Docker (tarea 8.4): los códigos de salida y los textos.

La CLI solo lee la ejecución, llama a la carga e imprime. Lo que se sustituye es `load_truth`, tal
como lo importa `edsim.cli`: la carga con `COPY` se prueba contra un Postgres real en
`tests_integracion/test_verdad.py`. Las filas y sus errores, en `test_store_truth.py`.
"""

from pathlib import Path

import pytest
from runs_factory import copy_run

from edsim import cli
from edsim.runs import RunStore, simulate_run
from edsim.store.migrations import MigrationError
from edsim.store.postgres import DatabaseUnavailableError
from edsim.store.truth import TruthLoad

DATA = Path(__file__).parent / "data"
URL = "postgresql://edsim:secreta@localhost:5432/edsim"
COUNTS = {"eventos": 55054, "episodios": 4439, "dias": 14, "libreta": 55397}


@pytest.fixture
def loads(monkeypatch):
    """Sustituye `load_truth`: apunta cada llamada y devuelve la carga de `h8demo` de ejemplo."""
    calls = []

    def fake(url, run):
        calls.append((url, run.run_id, [t.qualified_name for t in run.tables]))
        return TruthLoad(run.run_id, COUNTS, ("realista-s2026",), 3.14)

    monkeypatch.setattr(cli, "load_truth", fake)
    return calls


@pytest.fixture(scope="module")
def base_run(tmp_path_factory):
    """Una ejecución del hito 5 (esquema 4) de 2 días: solo hace falta que sea de ese modelo."""
    root = tmp_path_factory.mktemp("cargar-verdad")
    simulate_run(
        DATA / "centro_h5_ejemplo.toml",
        DATA / "llegadas_ejemplo.toml",
        2,
        7,
        output_dir=root / "hito5",
        run_id="hito5",
        warmup_days=1,
        origin="cli",
        profiles=DATA / "perfiles_h5_ejemplo.toml",
    )
    return RunStore(root)


@pytest.fixture
def runs(base_run, tmp_path):
    """La carpeta de las ejecuciones con una copia de la del hito 5, `hito5`."""
    store, _ = copy_run(base_run, "hito5", tmp_path)
    return store.root


def test_cargar_verdad_imprime_los_recuentos_y_la_libreta(runs, loads, capsys):
    """Pilla un comando que no diga cuánto escribió en cada tabla ni de qué perfiles es la
    libreta, o que enseñe la contraseña de la URL."""
    code = cli.main(
        ["almacen", "cargar-verdad", "hito5", "--ejecuciones", str(runs), "--postgres", URL]
    )

    assert code == 0
    assert capsys.readouterr().out == (
        "Postgres postgresql://edsim:***@localhost:5432/edsim\n"
        "hito5: verdad cargada en 3.1 s: 55054 eventos · 4439 episodios · 14 días · "
        "55397 filas de libreta\n"
        "Libreta de: realista-s2026\n"
    )
    assert loads == [
        (URL, "hito5", ["verdad.eventos", "verdad.episodios", "verdad.dias", "verdad.libreta"])
    ]


def test_cargar_verdad_sin_libreta_lo_dice_y_sale_con_0(runs, monkeypatch, capsys):
    """Pilla un error donde la especificación dice que una ejecución sin `registros/` se carga con
    la libreta vacía: el comando lo dice y cómo escribirla."""
    monkeypatch.setattr(
        cli,
        "load_truth",
        lambda url, run: TruthLoad(run.run_id, {**COUNTS, "libreta": 0}, (), 1.0),
    )

    assert cli.main(["almacen", "cargar-verdad", "hito5", "--ejecuciones", str(runs)]) == 0
    out = capsys.readouterr().out
    assert "0 filas de libreta" in out
    assert "Sin libreta: hito5 no tiene registros/" in out
    assert "edsim registro generar hito5 --perfil PERFIL" in out


def test_cargar_verdad_usa_la_postgres_de_compose_por_defecto(runs, loads):
    """Pilla un valor por defecto que no sea el de `compose.yaml`, como el de los demás comandos."""
    assert cli.main(["almacen", "cargar-verdad", "hito5", "--ejecuciones", str(runs)]) == 0

    assert loads[0][0] == "postgresql://edsim:edsim@localhost:5432/edsim"


@pytest.mark.parametrize(
    ("run_id", "schema"), [("clinica", 3), ("provisional", 1)], ids=["hito-4", "provisional"]
)
def test_una_ejecucion_de_otro_esquema_sale_con_1_sin_tocar_la_base(
    clinical_store, loads, capsys, run_id, schema
):
    """D1: pilla una carga que llegue a conectar con una ejecución de otro esquema. Código 1 (como
    los demás errores de datos de `almacen`) y el mensaje dice cómo regenerarla."""
    code = cli.main(["almacen", "cargar-verdad", run_id, "--ejecuciones", str(clinical_store.root)])

    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith(f"Error: {run_id} es del esquema {schema}")
    assert "edsim motor simular" in err
    assert loads == []


def test_una_ejecucion_que_no_existe_es_un_error_de_uso(runs, loads, capsys):
    """Como `registro generar`: código 2 y nada de conectar."""
    with pytest.raises(SystemExit) as caught:
        cli.main(["almacen", "cargar-verdad", "no-existe", "--ejecuciones", str(runs)])

    assert caught.value.code == 2
    assert "no-existe" in capsys.readouterr().err
    assert loads == []


@pytest.mark.parametrize(
    ("error", "text"),
    [
        (DatabaseUnavailableError(URL, "connection refused"), "docker compose up --wait"),
        (MigrationError("falta verdad.eventos"), "Error en las migraciones"),
    ],
)
def test_cargar_verdad_sale_con_1_si_postgres_falla(runs, monkeypatch, capsys, error, text):
    """Pilla un fallo de Postgres que acabe en un traceback y no en el mensaje en español."""

    def fail(url, run):
        raise error

    monkeypatch.setattr(cli, "load_truth", fail)

    assert cli.main(["almacen", "cargar-verdad", "hito5", "--ejecuciones", str(runs)]) == 1
    err = capsys.readouterr().err
    assert text in err
    assert "secreta" not in err


def test_un_fichero_que_falla_al_leerse_durante_la_carga_sale_con_1(runs, monkeypatch, capsys):
    """Pilla un error de lectura con la conexión ya abierta que acabe como error de uso (código 2):
    antes de conectar es un error de uso; después, un problema de los datos."""

    def fail(url, run):
        raise PermissionError(13, "Permission denied", "defectos.csv")

    monkeypatch.setattr(cli, "load_truth", fail)

    assert cli.main(["almacen", "cargar-verdad", "hito5", "--ejecuciones", str(runs)]) == 1
    err = capsys.readouterr().err
    assert err.startswith("Error: ") and "defectos.csv" in err
