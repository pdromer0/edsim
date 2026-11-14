"""`edsim registro validar` y `generar` (tarea 7.2).

Cada test dice qué error pilla. La CLI es fina: aquí se prueban sus códigos de salida, lo que
imprime y que no escribe nada cuando falla; la lógica está en el paquete y tiene sus tests
(`test_record_run.py`, `test_registro_perfiles.py`). Las ejecuciones son copias de `clinical_store`.
"""

import hashlib
import json
import re
import shutil

import pytest
from registro_factory import PROFILES_FILE
from runaway import check_calls
from runs_factory import copy_run

from edsim import cli
from edsim.runs import RunStore, read_recorded_records, read_recorded_run, record_run
from edsim.store.migrations import MigrationError
from edsim.store.postgres import (
    DEFAULT_URL,
    BronzeReadError,
    DatabaseUnavailableError,
    MissingPostgresExtraError,
)


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


# --- comparar -----------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def recorded_root(clinical_store, tmp_path_factory):
    """Una copia de `clinica` con el registro limpio, el realista y el realista de semilla 5."""
    root = tmp_path_factory.mktemp("comparar")
    store, _ = copy_run(clinical_store, "clinica", root)
    record_run(store, "clinica", "limpio", profiles_file=PROFILES_FILE)
    record_run(store, "clinica", "realista", profiles_file=PROFILES_FILE)
    record_run(store, "clinica", "realista", 5, profiles_file=PROFILES_FILE)
    return store.root


@pytest.fixture
def copy_of_recorded(recorded_root, tmp_path):
    """Una copia que el test puede estropear: la carpeta de las ejecuciones y la de `clinica`."""
    shutil.copytree(recorded_root, tmp_path / "ejecuciones", symlinks=True)
    return tmp_path / "ejecuciones", tmp_path / "ejecuciones" / "clinica"


def compare_argv(root, *extra, profile="realista", run_id="clinica"):
    return ["registro", "comparar", run_id, "--perfil", profile, "--ejecuciones", str(root), *extra]


def seed_of(root) -> int:
    return RunStore(root).open("clinica").seed


def prints(directory):
    return {
        p.relative_to(directory).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }


@pytest.fixture
def no_postgres(monkeypatch):
    """Un `read_bronze_records` que falla el test si algo lo llama (con tope de llamadas)."""
    calls = []

    def fail(url, run_id):
        calls.append(url)
        check_calls(len(calls), 3, "read_bronze_records")
        pytest.fail("conectó con Postgres")

    monkeypatch.setattr(cli, "read_bronze_records", fail)


def test_comparar_con_ficheros_imprime_la_conciliacion_y_la_tabla(
    recorded_root, no_postgres, capsys
):
    """Pilla un `comparar` que no dice de qué ejecución y de dónde sale lo registrado, que no
    imprime la cuenta o la tabla, o que sale con otro código."""
    assert cli.main(compare_argv(recorded_root)) == 0
    out = capsys.readouterr().out

    seed = seed_of(recorded_root)
    assert f"Comparación de clinica · perfil realista · semilla {seed}" in out
    assert f"Ejecución derivada: clinica_realista_s{seed} · lo registrado sale de ficheros" in out
    assert "Conciliación (la cuenta cuadra):" in out
    assert "Retraso por sistema" in out
    assert "Indicador" in out and "Nivel 5 en el triaje (%)" in out


def test_comparar_no_escribe_nada(recorded_root, no_postgres, capsys):
    """La comparación es una lectura: ningún fichero de la ejecución cambia ni se crea."""
    before = prints(recorded_root)

    assert cli.main(compare_argv(recorded_root)) == 0

    assert prints(recorded_root) == before


def test_comparar_con_el_perfil_limpio_no_tiene_diferencias(recorded_root, no_postgres, capsys):
    """Con el limpio, cada fila de la tabla acaba en una diferencia de 0 (y la tabla no está
    vacía: tiene las nueve filas)."""
    assert cli.main(compare_argv(recorded_root, profile="limpio")) == 0
    out = capsys.readouterr().out

    table = out.split("  Indicador ", 1)[1].splitlines()[1:]
    assert len(table) == 9
    assert all(line.split()[-1] == "0" for line in table), table


def test_comparar_con_una_semilla_elige_ese_registro(recorded_root, no_postgres, capsys):
    """`--semilla 5` compara el registro de la semilla 5, no el de la ejecución."""
    assert cli.main(compare_argv(recorded_root, "--semilla", "5")) == 0

    assert "semilla 5" in capsys.readouterr().out


def fake_bronze(monkeypatch, root, *, drop=0, calls=None):
    """Un `read_bronze_records` que da lo que hay en ficheros, sin los últimos `drop`."""
    run = read_recorded_run(RunStore(root), "clinica", "realista")
    records = list(read_recorded_records(run))

    def read(url, run_id):
        if calls is not None:
            calls.append((url, run_id))
            check_calls(len(calls), 3, "read_bronze_records")
        return records[: len(records) - drop]

    monkeypatch.setattr(cli, "read_bronze_records", read)
    return run


def test_comparar_con_postgres_da_la_misma_conciliacion_que_con_ficheros(
    recorded_root, monkeypatch, capsys
):
    """Con los mismos registros, el informe es el mismo salvo la línea del origen. La URL sin
    valor es la de compose.yaml, y se pide la ejecución derivada, no la verdad."""
    assert cli.main(compare_argv(recorded_root)) == 0
    files = capsys.readouterr().out
    calls = []
    run = fake_bronze(monkeypatch, recorded_root, calls=calls)

    assert cli.main(compare_argv(recorded_root, "--postgres")) == 0
    postgres = capsys.readouterr().out

    assert calls == [(DEFAULT_URL, run.derived_run_id)]
    assert files.replace("ficheros", "X") == postgres.replace(
        f"Postgres ({DEFAULT_URL.replace('edsim:edsim', 'edsim:***')})", "X"
    )


def test_comparar_con_postgres_imprime_la_url_sin_la_contrasena(recorded_root, monkeypatch, capsys):
    """La URL de `--postgres URL` se usa tal cual y se imprime sin la contraseña."""
    calls = []
    fake_bronze(monkeypatch, recorded_root, calls=calls)
    url = "postgresql://yo:secreta@otro:5432/base"

    assert cli.main(compare_argv(recorded_root, "--postgres", url)) == 0
    out = capsys.readouterr().out

    assert calls[0][0] == url
    assert "Postgres (postgresql://yo:***@otro:5432/base)" in out
    assert "secreta" not in out


def test_comparar_con_postgres_antes_de_otra_opcion_usa_la_url_por_defecto(
    recorded_root, monkeypatch, capsys
):
    """`--postgres --perfil realista`: la opción sin valor no se come la siguiente."""
    calls = []
    fake_bronze(monkeypatch, recorded_root, calls=calls)

    argv = ["registro", "comparar", "clinica", "--postgres", "--perfil", "realista"]
    assert cli.main([*argv, "--ejecuciones", str(recorded_root)]) == 0
    capsys.readouterr()

    assert calls[0][0] == DEFAULT_URL


def test_comparar_con_un_bronce_incompleto_sale_con_1_y_dice_que_consumir(
    recorded_root, monkeypatch, capsys
):
    """Bronce al que le faltan registros: la cuenta no cuadra, código 1, nada en stdout (ningún
    número) y la pista del comando que lo llena (`almacen consumir --run <derivada>`)."""
    run = fake_bronze(monkeypatch, recorded_root, drop=2)

    assert cli.main(compare_argv(recorded_root, "--postgres")) == 1
    captured = capsys.readouterr()

    assert captured.out == ""
    assert "la cuenta no cuadra" in captured.err
    assert f"edsim almacen consumir --run {run.derived_run_id}" in captured.err


@pytest.mark.parametrize(
    ("error", "text"),
    [
        (DatabaseUnavailableError("postgresql://h/db", "rechazada"), "no se puede conectar"),
        (MissingPostgresExtraError("Falta el extra postgres: uv sync"), "Falta el extra postgres"),
        (MigrationError("relation does not exist"), "Error en las migraciones"),
        (BronzeReadError("el valor 3 de bronce no es un registro"), "valor 3 de bronce"),
    ],
)
def test_comparar_con_postgres_que_falla_sale_con_1_sin_traza(
    recorded_root, monkeypatch, capsys, error, text
):
    """Postgres que no responde, el extra que falta, las tablas que faltan o un valor que no es un
    registro: código 1 con su frase, no una traza ni un error de uso (2)."""

    def fail(url, run_id):
        raise error

    monkeypatch.setattr(cli, "read_bronze_records", fail)

    assert cli.main(compare_argv(recorded_root, "--postgres")) == 1
    captured = capsys.readouterr()

    assert text in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""


def test_comparar_con_una_cuenta_que_no_cuadra_en_ficheros_sale_con_1(
    copy_of_recorded, no_postgres, capsys
):
    """Un `registrado.jsonl` al que le falta una línea: código 1, la cuenta que no cuadra y sin
    la pista de bronce (no se leyó de bronce)."""
    root, run_dir = copy_of_recorded
    path = run_dir / "registros" / f"realista-s{seed_of(root)}" / "registrado.jsonl"
    lines = path.read_text(encoding="utf-8").split("\n")
    del lines[3]
    path.write_text("\n".join(lines), encoding="utf-8")

    assert cli.main(compare_argv(root)) == 1
    err = capsys.readouterr().err

    assert "la cuenta no cuadra" in err and "almacen consumir" not in err


def test_comparar_con_una_libreta_rota_sale_con_1_y_dice_la_linea(
    copy_of_recorded, no_postgres, capsys
):
    """Un fallo de los datos (`defectos.csv`), con su línea: código 1, no 2."""
    root, run_dir = copy_of_recorded
    path = run_dir / "registros" / f"realista-s{seed_of(root)}" / "defectos.csv"
    path.write_text(path.read_text(encoding="utf-8").replace("clase", "otra", 1), encoding="utf-8")

    assert cli.main(compare_argv(root)) == 1
    assert "defectos.csv:1" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("extra", "profile", "run_id", "text"),
    [
        (("--semilla", "99"), "realista", "clinica", "there is no recording realista-s99"),
        ((), "hostil", "clinica", "there is no recording hostil"),
        ((), "realista", "no-existe", "no-existe"),
        (("--postgres", "http://x"), "realista", "clinica", "no es una URL de Postgres"),
        (("--semilla", "-1"), "realista", "clinica", "seed"),
    ],
)
def test_comparar_con_un_uso_malo_sale_con_2_antes_de_conectar(
    recorded_root, no_postgres, capsys, extra, profile, run_id, text
):
    """Un registro que no existe, una ejecución que no existe, una URL que no lo es o una semilla
    negativa son errores de uso (2) y no llegan a conectar con Postgres (`no_postgres` falla el
    test si algo lo llama)."""
    err = usage_error(compare_argv(recorded_root, *extra, profile=profile, run_id=run_id), capsys)

    assert text in err


@pytest.mark.parametrize(
    "argv",
    [
        ["registro", "comparar", "clinica"],
        ["registro", "comparar", "clinica", "--perfil", "feroz"],
        ["registro", "comparar"],
    ],
    ids=["sin_perfil", "perfil_desconocido", "sin_ejecucion"],
)
def test_comparar_sin_lo_obligatorio_es_un_error_de_uso(argv, no_postgres, capsys):
    """El perfil y la ejecución son obligatorios, y el perfil es uno de los tres."""
    assert re.search(r"perfil|RUN_ID|invalid choice", usage_error(argv, capsys))
