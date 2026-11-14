"""`edsim registro validar` y `generar` (tarea 7.2).

Cada test dice qué error pilla. La CLI es fina: aquí se prueban sus códigos de salida, lo que
imprime y que no escribe nada cuando falla; la lógica está en el paquete y tiene sus tests
(`test_record_run.py`, `test_registro_perfiles.py`). Las ejecuciones son copias de `clinical_store`.
"""

import hashlib
import json

import pytest
from registro_factory import PROFILES_FILE
from runs_factory import copy_run

from edsim import cli


def usage_error(argv, capsys) -> str:
    """Ejecuta la CLI, exige el error de uso (código 2) y devuelve lo que dijo por stderr."""
    with pytest.raises(SystemExit) as stop:
        cli.main(argv)
    assert stop.value.code == 2
    return capsys.readouterr().err


def generate_argv(root, profile="realista", *extra, run_id="clinica"):
    return [
        "registro",
        "generar",
        run_id,
        "--perfil",
        profile,
        "--registros",
        str(PROFILES_FILE),
        "--ejecuciones",
        str(root),
        *extra,
    ]


@pytest.fixture
def runs(clinical_store, tmp_path):
    """Una copia de la ejecución `clinica` en `tmp_path`: la carpeta de las ejecuciones."""
    store, run_dir = copy_run(clinical_store, "clinica", tmp_path)
    return store.root, run_dir


# --- validar ------------------------------------------------------------------------------


def test_validar_imprime_el_fichero_y_los_tres_perfiles(capsys):
    """Pilla un `validar` que no dice qué fichero ni qué huella, o que no enseña los perfiles."""
    assert cli.main(["registro", "validar", "--registros", str(PROFILES_FILE)]) == 0
    out = capsys.readouterr().out
    fingerprint = hashlib.sha256(PROFILES_FILE.read_bytes()).hexdigest()[:12]
    assert f"(huella {fingerprint})" in out
    assert "3 perfiles: limpio, realista, hostil" in out
    for text in ("olvido 0.005 · campo vacío 0.01", "olvido 0.05 · campo vacío 0.07"):
        assert text in out
    assert "triaje +7" in out


def test_validar_sin_opciones_usa_el_fichero_del_repositorio(capsys):
    """Pilla un valor por defecto que no es `config/registro_clinico.toml` (desde la raíz)."""
    assert cli.main(["registro", "validar"]) == 0
    assert "config/registro_clinico.toml" in capsys.readouterr().out


def test_validar_con_un_fichero_malo_sale_con_2_y_da_todos_los_errores(tmp_path, capsys):
    """Pilla un `validar` que sale con 0 o que enseña un solo error."""
    bad = tmp_path / "malo.toml"
    bad.write_text("[limpio]\nolvido = 3\n", encoding="utf-8")
    err = usage_error(["registro", "validar", "--registros", str(bad)], capsys)
    assert "--registros" in err and "limpio.olvido" in err
    assert "realista: missing profile" in err and "hostil: missing profile" in err


def test_validar_con_un_fichero_que_no_existe_sale_con_2(tmp_path, capsys):
    """Pilla un fichero ausente que escapa como traza en vez de error de uso."""
    err = usage_error(["registro", "validar", "--registros", str(tmp_path / "no.toml")], capsys)
    assert "--registros" in err


# --- generar ------------------------------------------------------------------------------


def test_generar_escribe_e_imprime_la_cuenta(runs, capsys):
    """Pilla un `generar` que no escribe o que imprime una cuenta distinta de `registro.json`."""
    root, run_dir = runs
    assert cli.main(generate_argv(root, "hostil", "--semilla", "5")) == 0
    out = capsys.readouterr().out
    folder = run_dir / "registros" / "hostil-s5"
    info = json.loads((folder / "registro.json").read_text(encoding="utf-8"))
    cuenta = info["cuenta"]
    assert "Ejecución derivada: clinica_hostil_s5" in out
    assert f"Carpeta: {folder}" in out
    assert "La cuenta cuadra:" in out
    assert (
        f"hechos de pacientes {cuenta['hechos_pacientes']} = {cuenta['bien']} bien + "
        f"{cuenta['con_despistes']} con despistes + {cuenta['perdido']} perdidos"
    ) in out
    assert f"registros escritos {cuenta['registros']} =" in out
    assert info["huella"] in out


def test_generar_sin_semilla_usa_la_de_la_ejecucion(runs, capsys):
    """Pilla un valor por defecto de `--semilla` que no sea el de `run.json` (2026)."""
    root, run_dir = runs
    assert cli.main(generate_argv(root)) == 0
    assert (run_dir / "registros" / "realista-s2026").is_dir()
    assert "semilla 2026" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (["--perfil", "caotico"], "invalid choice: 'caotico'"),
        (["--semilla", "no"], "invalid int value"),
    ],
    ids=["perfil_que_no_existe", "semilla_que_no_es_un_numero"],
)
def test_generar_con_opciones_no_validas_sale_con_2(runs, capsys, extra, message):
    """Pilla una opción mal escrita que llega a escribir algo: `argparse` la para antes."""
    root, run_dir = runs
    argv = ["registro", "generar", "clinica", "--ejecuciones", str(root)] + extra
    if "--perfil" not in extra:
        argv += ["--perfil", "realista"]
    assert message in usage_error(argv, capsys)
    assert not (run_dir / "registros").exists()


def test_generar_sin_perfil_sale_con_2(runs, capsys):
    """Pilla un perfil por defecto: la especificación lo hace obligatorio."""
    root, _ = runs
    err = usage_error(["registro", "generar", "clinica", "--ejecuciones", str(root)], capsys)
    assert "--perfil" in err


@pytest.mark.parametrize(
    ("argv_change", "message"),
    [
        ({"run_id": "no-existe"}, "no-existe"),
        ({"extra": ("--semilla", "-3")}, "seed must be an integer >= 0"),
    ],
    ids=["ejecucion_que_no_existe", "semilla_negativa"],
)
def test_generar_con_un_error_de_uso_sale_con_2_y_no_deja_nada(runs, capsys, argv_change, message):
    """Pilla un error de uso que se convierte en traza o en código 1."""
    root, run_dir = runs
    argv = generate_argv(
        root, "realista", *argv_change.get("extra", ()), run_id=argv_change.get("run_id", "clinica")
    )
    assert message in usage_error(argv, capsys)
    assert not (run_dir / "registros").exists()


def test_generar_con_un_registro_que_ya_existe_sale_con_2_y_no_lo_pisa(runs, capsys):
    """Pilla un segundo `generar` que sobrescribe el primero."""
    root, run_dir = runs
    assert cli.main(generate_argv(root, "realista", "--semilla", "4")) == 0
    capsys.readouterr()
    folder = run_dir / "registros" / "realista-s4"
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    assert "already exists" in usage_error(
        generate_argv(root, "realista", "--semilla", "4"), capsys
    )
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before


def test_generar_con_un_fichero_de_perfiles_malo_sale_con_2(runs, tmp_path, capsys):
    """Pilla un perfil inválido que llega a escribir: el error es de uso y no deja nada."""
    root, run_dir = runs
    bad = tmp_path / "malo.toml"
    bad.write_text("[limpio]\nolvido = 3\n", encoding="utf-8")
    argv = generate_argv(root)
    argv[argv.index("--registros") + 1] = str(bad)
    assert "limpio.olvido" in usage_error(argv, capsys)
    assert not (run_dir / "registros").exists()


def test_generar_con_el_log_de_otra_ejecucion_sale_con_1_y_no_deja_nada(
    clinical_store, tmp_path, capsys
):
    """Pilla un fallo de los datos que sale como error de uso: el log no es el de la ejecución.

    La copia se llama `otra` (con su `run.json` cambiado) y lleva los eventos de `clinica`.
    """
    store, run_dir = copy_run(clinical_store, "clinica", tmp_path, "otra")
    info = (run_dir / "run.json").read_text(encoding="utf-8")
    (run_dir / "run.json").write_text(info.replace('"run_id": "clinica"', '"run_id": "otra"'))
    assert cli.main(generate_argv(store.root, run_id="otra")) == 1
    err = capsys.readouterr().err
    assert "Error en los datos de otra" in err and "not of run" in err
    assert not (run_dir / "registros").exists()


def test_generar_con_una_linea_rota_del_log_sale_con_1(runs, capsys):
    """Pilla un log con una línea que no es un evento: código 1 y el número de la línea."""
    root, run_dir = runs
    events = run_dir / "eventos.jsonl"
    lines = events.read_text(encoding="utf-8").split("\n")
    lines[1] = "{no es json"
    events.write_text("\n".join(lines), encoding="utf-8")
    assert cli.main(generate_argv(root)) == 1
    assert "eventos.jsonl:2" in capsys.readouterr().err
    assert not (run_dir / "registros").exists()
