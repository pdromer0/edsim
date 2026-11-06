"""CLI de la calibración: calibracion evaluar y calibracion sensibilidad (tarea 4.6b)."""

import csv
from pathlib import Path

import pytest

from edsim.cli import main

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "tests" / "data"
EXAMPLE = [
    "--centro",
    str(DATA / "centro_sala_ejemplo.toml"),
    "--llegadas",
    str(DATA / "llegadas_ejemplo.toml"),
    "--perfiles",
    str(DATA / "perfiles_ejemplo.toml"),
]
SHORT = ["--replicas", "2", "--dias", "2", "--calentamiento", "1", "--semilla", "7"]


def targets_file(path: Path, *, pretriage_band="[0, 100]", check_band="[0, 100]") -> Path:
    """Objetivos con horquillas que el ejemplo cumple, salvo las que se pidan."""
    source = 'fuente = "a mano"\nenlace = "https://example.org"\n'
    path.write_text(
        f"""
[objetivos.pretriaje_medio]
medida = "triage_wait"
niveles = [2, 3, 4, 5]
estadistico = "media"
referencia = 1.0
horquilla = {pretriage_band}
uso = "ajuste"
{source}
[objetivos.tiempo_medico_niveles_2_5]
medida = "door_to_doctor"
niveles = [2, 3, 4, 5]
estadistico = "media"
horquilla = [0, 100000]
uso = "ajuste"
{source}
[objetivos.tiempo_medico_nivel_3]
medida = "door_to_doctor"
niveles = [3]
estadistico = "media"
referencia = 10.0
horquilla = [0, 100000]
uso = "ajuste"
{source}
[objetivos.porcentaje_sobre_manchester]
medida = "door_to_doctor"
niveles = [2, 3, 4, 5]
estadistico = "porcentaje_sobre_umbral"
umbral = "manchester"
horquilla = {check_band}
uso = "comprobacion"
{source}"""
    )
    return path


def read_rows(path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# --- evaluar ------------------------------------------------------------------------------


def test_evaluar_codigo_0_tabla_y_ficheros(tmp_path, capsys):
    targets = targets_file(tmp_path / "objetivos.toml", check_band="[99, 100]")
    out_dir = tmp_path / "salida"

    code = main(
        ["calibracion", "evaluar", *EXAMPLE, "--objetivos", str(targets), *SHORT]
        + ["--salida", str(out_dir)]
    )
    out = capsys.readouterr().out

    # La comprobación falla, pero solo se informa: el código sigue siendo 0.
    assert code == 0
    assert "2 réplicas de 2 días (1 de calentamiento y 1 de vaciado) · semilla 7" in out
    assert "Resultado: todos los objetivos de ajuste pasan" in out
    assert (
        "Comprobación (se informa, no cambia el resultado): fallan porcentaje_sobre_manchester"
        in out
    )
    assert "Censurados" in out and "Desglose por nivel de porcentaje_sobre_manchester" in out

    rows = read_rows(out_dir / "evaluacion.csv")
    assert [r["objetivo"] for r in rows] == [
        "pretriaje_medio",
        "tiempo_medico_niveles_2_5",
        "tiempo_medico_nivel_3",
        "porcentaje_sobre_manchester",
    ]
    assert [r["resultado"] for r in rows] == ["pasa", "pasa", "pasa", "falla"]
    assert rows[0]["niveles"] == "2 3 4 5" and rows[0]["referencia"] == "1.0"
    assert (rows[0]["replicas"], rows[0]["dias"], rows[0]["calentamiento"], rows[0]["semilla"]) == (
        "2",
        "2",
        "1",
        "7",
    )
    assert rows[0]["objetivos"] == str(targets) and len(rows[0]["huella_objetivos"]) == 12
    replicas = read_rows(out_dir / "evaluacion_replicas.csv")
    assert len(replicas) == 2 * 4
    assert all(int(r["llegados_ventana"]) > 0 for r in replicas)
    levels = read_rows(out_dir / "evaluacion_niveles.csv")
    assert [(r["objetivo"], r["nivel"]) for r in levels] == [
        ("porcentaje_sobre_manchester", str(level)) for level in (2, 3, 4, 5)
    ]


def test_evaluar_codigo_1_si_falla_un_objetivo_de_ajuste(tmp_path, capsys):
    targets = targets_file(tmp_path / "objetivos.toml", pretriage_band="[500, 600]")
    targets.write_text(targets.read_text().replace("referencia = 1.0", "referencia = 550.0"))
    out_dir = tmp_path / "salida"

    code = main(
        ["calibracion", "evaluar", *EXAMPLE, "--objetivos", str(targets), *SHORT]
        + ["--salida", str(out_dir)]
    )

    assert code == 1
    assert "Resultado: FALLAN objetivos de ajuste: pretriaje_medio" in capsys.readouterr().out
    assert (out_dir / "evaluacion.csv").is_file()  # los ficheros se escriben igualmente


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (["--objetivos", "no-existe.toml"], "--objetivos no-existe.toml"),
        (["--objetivos", "{bad}"], "objetivos.x.uso"),
        (["--perfiles", "no-existe.toml"], "--perfiles no-existe.toml"),
        (["--centro", "no-existe.toml"], "--centro no-existe.toml"),
        (["--replicas", "1"], "replicas must be an integer >= 2"),
        (["--dias", "2", "--calentamiento", "2"], "warmup_days"),
    ],
)
@pytest.mark.parametrize("command", [["evaluar"], ["sensibilidad", "--mando", "medicos"]])
def test_errores_de_uso_sin_ficheros(command, extra, message, tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(REPO)
    monkeypatch.setattr("edsim.cli.simulate_replicas", lambda *a, **k: pytest.fail("simuló"))
    monkeypatch.setattr("edsim.cli.sensitivity", lambda *a, **k: pytest.fail("simuló"))
    bad = tmp_path / "malo.toml"
    bad.write_text(
        '[objetivos.x]\nmedida = "triage_wait"\nniveles = [2]\nestadistico = "media"\n'
        'horquilla = [6, 15]\nuso = "otro"\nfuente = "a"\nenlace = "b"\n'
    )
    extra = [str(bad) if x == "{bad}" else x for x in extra]
    out_dir = tmp_path / "salida"

    with pytest.raises(SystemExit) as exit_info:
        main(["calibracion", *command, *extra, "--salida", str(out_dir)])
    captured = capsys.readouterr()

    assert exit_info.value.code == 2
    assert message in captured.err
    assert captured.out == ""
    assert not out_dir.exists()


@pytest.mark.parametrize("command", [["evaluar"], ["sensibilidad", "--mando", "medicos"]])
def test_salida_que_es_un_fichero(command, tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(REPO)
    monkeypatch.setattr("edsim.cli.simulate_replicas", lambda *a, **k: pytest.fail("simuló"))
    monkeypatch.setattr("edsim.cli.sensitivity", lambda *a, **k: pytest.fail("simuló"))
    path = tmp_path / "fichero"
    path.write_text("no tocar")

    with pytest.raises(SystemExit) as exit_info:
        main(["calibracion", *command, "--salida", str(path)])

    assert exit_info.value.code == 2
    assert "no es un directorio" in capsys.readouterr().err
    assert path.read_text() == "no tocar"


# --- sensibilidad -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (["--mando", "boxes"], "invalid choice: 'boxes'"),
        (["--mando", "medicos", "--u-min", "0.9", "--u-max", "0.8"], "need u_min <= u_max"),
        (["--mando", "medicos", "--paso", "0"], "step must be a number > 0"),
        (
            ["--mando", "medicos", "--objetivos", "{incomplete}"],
            "objetivos.tiempo_medico_niveles_2_5",
        ),
    ],
)
def test_sensibilidad_errores_de_uso(extra, message, tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(REPO)
    monkeypatch.setattr("edsim.cli.sensitivity", lambda *a, **k: pytest.fail("simuló"))
    incomplete = targets_file(tmp_path / "objetivos.toml")
    text = incomplete.read_text()
    incomplete.write_text(text[: text.index("[objetivos.tiempo_medico_niveles_2_5]")])
    extra = [str(incomplete) if x == "{incomplete}" else x for x in extra]
    out_dir = tmp_path / "salida"

    with pytest.raises(SystemExit) as exit_info:
        main(["calibracion", "sensibilidad", *extra, "--salida", str(out_dir)])

    assert exit_info.value.code == 2
    assert message in capsys.readouterr().err
    assert not out_dir.exists()


def test_sensibilidad_de_la_enfermeria_elige_y_escribe_el_csv(tmp_path, capsys):
    targets = targets_file(tmp_path / "objetivos.toml")
    out_dir = tmp_path / "salida"

    code = main(
        ["calibracion", "sensibilidad", "--mando", "enfermeria_triaje", *EXAMPLE]
        + ["--objetivos", str(targets), *SHORT, "--u-min", "0.6", "--u-max", "0.9"]
        + ["--salida", str(out_dir)]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert "Sensibilidad del mando enfermeria_triaje con u de 0.6 a 0.9" in out
    assert "Elección (entre las que pasan pretriaje_medio" in out
    assert "Cumplidor" not in out
    rows = read_rows(out_dir / "sensibilidad_enfermeria_triaje.csv")
    staffings = {(r["manana"], r["tarde"], r["noche"]) for r in rows}
    assert len(staffings) >= 2
    assert len(rows) == 4 * len(staffings)
    chosen = {(r["manana"], r["tarde"], r["noche"]) for r in rows if r["elegida"] == "True"}
    assert len(chosen) == 1


def test_sensibilidad_codigo_1_si_ninguna_pasa(tmp_path, capsys):
    targets = targets_file(tmp_path / "objetivos.toml")
    targets.write_text(
        targets.read_text().replace(
            'estadistico = "media"\nhorquilla = [0, 100000]',
            'estadistico = "media"\nhorquilla = [0, 0.001]',
        )
    )
    out_dir = tmp_path / "salida"

    code = main(
        ["calibracion", "sensibilidad", "--mando", "medicos", *EXAMPLE]
        + ["--objetivos", str(targets), *SHORT, "--u-min", "0.9", "--u-max", "0.95"]
        + ["--salida", str(out_dir)]
    )
    out = capsys.readouterr().out

    assert code == 1
    assert "Elección: ninguna plantilla de la regla pasa" in out
    assert "Cumplidor" in out
    assert (out_dir / "sensibilidad_medicos.csv").is_file()
