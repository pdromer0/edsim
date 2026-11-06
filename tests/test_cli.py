import csv
import dataclasses
from functools import partial
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pytest

from edsim.arrivals.profile import load_profile
from edsim.arrivals.report import config_fingerprint, format_validation
from edsim.arrivals.thinning import simulate_arrivals
from edsim.arrivals.validation import validate_arrivals
from edsim.cli import main
from edsim.engine.analysis import analyze_run
from edsim.engine.center import load_center
from edsim.engine.engine import simulate_ed
from edsim.engine.events import MemorySink, read_events
from edsim.engine.invariants import Violation
from edsim.engine.report import format_engine_validation, format_run_summary
from edsim.profiles.config import load_profiles
from edsim.profiles.context import ArrivalContext
from edsim.queueing.replications import METRIC_NAMES, compare_mm1
from edsim.queueing.report import format_comparison, plot_sweep

# Corridas pequeñas: aquí se prueba la CLI, no la precisión estadística.
SMALL = {"duration": 200.0, "warmup": 20.0, "replicas": 3, "seed": 7}
SMALL_ARGS = ["--duracion", "200", "--warmup", "20", "--replicas", "3", "--semilla", "7"]
RHOS = (0.3, 0.6)

CSV_HEADER = [
    "rho",
    "metrica",
    "teoria",
    "media",
    "desv_tipica",
    "ic_inf",
    "ic_sup",
    "error_rel",
    "dentro_ic",
    "replicas",
    "duracion",
    "warmup",
    "semilla",
]


def small_comparison(lam=0.5, mu=1.0):
    return compare_mm1(lam, mu, **SMALL)


# --- --version y estructura de subcomandos ---------------------------------


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])

    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"edsim {version('edsim')}"


@pytest.mark.parametrize("argv", [[], ["mm1"], ["llegadas"], ["motor"]])
def test_subcomando_obligatorio(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        main(argv)

    assert exc.value.code == 2
    assert "required" in capsys.readouterr().err


# --- comparar ----------------------------------------------------------------


def test_comparar_imprime_cabecera_y_tabla(capsys):
    main(["mm1", "comparar", "--lam", "0.5", "--mu", "1", *SMALL_ARGS])
    out = capsys.readouterr().out

    assert "λ = 0.5, μ = 1, ρ = 0.5" in out
    assert "3 réplicas" in out
    assert "semilla 7" in out
    # La tabla impresa es exactamente la del experimento con esos parámetros.
    assert format_comparison(small_comparison()) in out


def test_comparar_parametros_invalidos(capsys):
    # λ = μ: cola inestable. Error de uso limpio, sin traza de Python.
    with pytest.raises(SystemExit) as exc:
        main(["mm1", "comparar", "--lam", "1", "--mu", "1", *SMALL_ARGS])

    err = capsys.readouterr().err
    assert exc.value.code == 2
    assert "unstable" in err
    assert "Traceback" not in err


# --- format_comparison ---------------------------------------------------------


def test_format_comparison_filas():
    c = small_comparison()
    lines = format_comparison(c).splitlines()

    assert lines[0].split() == [
        "métrica",
        "teoría",
        "media",
        "IC",
        "95",
        "%",
        "error",
        "rel.",
        "dentro",
    ]
    assert len(lines) == 1 + len(METRIC_NAMES)
    labels = ["Wq", "W", "Lq", "L", "ρ"]
    for label, m, line in zip(labels, c.metrics, lines[1:], strict=True):
        s = m.summary
        assert line.split()[0] == label
        for value in (m.theory, s.mean, s.ci_low, s.ci_high):
            assert f"{value:.4f}" in line
        assert f"{m.rel_error * 100:.2f} %" in line
        assert line.endswith("sí" if m.theory_in_ci else "NO")


def test_format_comparison_marca_fuera_del_ic():
    c = small_comparison()
    outside = dataclasses.replace(c.metrics[0], theory_in_ci=False)
    inside = dataclasses.replace(c.metrics[1], theory_in_ci=True)
    c = dataclasses.replace(c, metrics=(outside, inside, *c.metrics[2:]))

    lines = format_comparison(c).splitlines()

    assert lines[1].endswith("NO")
    assert lines[2].endswith("sí")


# --- barrido -----------------------------------------------------------------


def run_sweep(out_dir):
    main(["mm1", "barrido", "--rhos", "0.3,0.6", "--salida", str(out_dir), *SMALL_ARGS])


def test_barrido_crea_csv_y_png(tmp_path, capsys):
    out_dir = tmp_path / "a" / "b"  # no existe: la CLI debe crearlo

    run_sweep(out_dir)
    out = capsys.readouterr().out

    csv_path = out_dir / "barrido.csv"
    png_path = out_dir / "barrido_wq.png"
    assert csv_path.is_file()
    assert png_path.read_bytes().startswith(b"\x89PNG")
    assert str(csv_path) in out
    assert str(png_path) in out


def test_barrido_contenido_del_csv(tmp_path):
    run_sweep(tmp_path)

    with (tmp_path / "barrido.csv").open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames
        rows = list(reader)

    assert header == CSV_HEADER
    assert len(rows) == len(RHOS) * len(METRIC_NAMES)

    expected = [(rho, m) for rho in RHOS for m in small_comparison(lam=rho).metrics]
    for row, (rho, m) in zip(rows, expected, strict=True):
        s = m.summary
        assert float(row["rho"]) == rho
        assert row["metrica"] == m.name
        # Los floats se escriben con todas sus cifras: la lectura es exacta.
        assert float(row["teoria"]) == m.theory
        assert float(row["media"]) == s.mean
        assert float(row["desv_tipica"]) == s.std
        assert float(row["ic_inf"]) == s.ci_low
        assert float(row["ic_sup"]) == s.ci_high
        assert float(row["error_rel"]) == m.rel_error
        assert row["dentro_ic"] == str(m.theory_in_ci)
        # Cómo se generó, repetido en cada fila.
        assert int(row["replicas"]) == 3
        assert float(row["duracion"]) == 200.0
        assert float(row["warmup"]) == 20.0
        assert int(row["semilla"]) == 7


@pytest.mark.parametrize("rhos", ["0.5,1", "0,0.5", "-0.1", "1.2", "abc", "", "0.5,,0.7"])
def test_barrido_rhos_invalidos(rhos, tmp_path, capsys):
    out_dir = tmp_path / "salida"

    with pytest.raises(SystemExit) as exc:
        main(["mm1", "barrido", "--rhos", rhos, "--salida", str(out_dir), *SMALL_ARGS])

    err = capsys.readouterr().err
    assert exc.value.code == 2
    assert "--rhos" in err
    assert "entre 0 y 1" in err or "no es un número" in err
    assert not out_dir.exists()


# --- plot_sweep ------------------------------------------------------------------


def test_plot_sweep_curva_y_puntos():
    points = [(rho, small_comparison(lam=rho)) for rho in RHOS]

    fig = plot_sweep(points)
    ax = fig.axes[0]

    theory = next(line for line in ax.get_lines() if line.get_label() == "Teoría")
    x, y = theory.get_xdata(), theory.get_ydata()
    assert len(x) == 200
    assert x.max() == pytest.approx(max(RHOS))
    np.testing.assert_allclose(y, x / (1 - x))  # Wq con μ = 1

    (container,) = ax.containers
    data_line = container.lines[0]
    np.testing.assert_allclose(data_line.get_xdata(), RHOS)
    np.testing.assert_allclose(
        data_line.get_ydata(), [c.metric("wq").summary.mean for _, c in points]
    )


# --- llegadas ------------------------------------------------------------------------

EXAMPLE = Path(__file__).parent / "data" / "llegadas_ejemplo.toml"
# Corridas mínimas: aquí se prueba la CLI, no la estadística.
GENERATE_ARGS = ["--dias", "14", "--semilla", "7"]
VALIDATE_ARGS = ["--dias", "14", "--replicas", "2", "--ejecuciones-cortas", "2", "--semilla", "7"]
PLOTS = ("perfil_horario.png", "qq_reescalado.png", "recuentos_diarios.png")


def small_validation():
    return validate_arrivals(load_profile(EXAMPLE), 14, 2, 7, short_runs=2)


def test_generar_escribe_los_dos_csv(tmp_path, capsys):
    out_dir = tmp_path / "a" / "b"  # no existe: la CLI debe crearlo

    code = main(
        ["llegadas", "generar", "--config", str(EXAMPLE), *GENERATE_ARGS, "--salida", str(out_dir)]
    )
    out = capsys.readouterr().out

    assert code == 0
    arrivals, days = simulate_arrivals(load_profile(EXAMPLE), 14, 7)
    with (out_dir / "llegadas.csv").open(newline="", encoding="utf-8") as f:
        arrival_rows = list(csv.DictReader(f))
    with (out_dir / "dias.csv").open(newline="", encoding="utf-8") as f:
        day_rows = list(csv.DictReader(f))
    assert [float(r["minuto"]) for r in arrival_rows] == [a.time for a in arrivals]
    assert [int(r["aceptadas"]) for r in day_rows] == [d.accepted for d in days]
    for row in (arrival_rows[0], day_rows[-1]):
        assert row["config"] == str(EXAMPLE)
        assert row["huella"] == config_fingerprint(EXAMPLE)
        assert (row["dias"], row["semilla"]) == ("14", "7")
    assert str(out_dir / "llegadas.csv") in out
    assert str(out_dir / "dias.csv") in out
    assert f"{len(arrivals)} llegadas" in out


def test_validar_imprime_cabecera_y_tabla_y_guarda_las_graficas(tmp_path, capsys):
    validation = small_validation()

    code = main(
        ["llegadas", "validar", "--config", str(EXAMPLE), *VALIDATE_ARGS, "--salida", str(tmp_path)]
    )
    out = capsys.readouterr().out

    assert code == (0 if validation.passed else 1)
    for text in (
        str(EXAMPLE),
        f"huella {config_fingerprint(EXAMPLE)}",
        "CV 0.06",
        "14 días",
        "2 réplicas",
        "2 ejecuciones cortas de 14 días",
        "semilla 7",
    ):
        assert text in out
    # La tabla impresa es exactamente la de la validación con esos parámetros.
    assert format_validation(validation.results) in out
    for name in PLOTS:
        assert (tmp_path / name).read_bytes().startswith(b"\x89PNG")
        assert str(tmp_path / name) in out


def test_validar_devuelve_1_si_falla_y_guarda_las_graficas(tmp_path, monkeypatch, capsys):
    validation = small_validation()
    failed = dataclasses.replace(validation.results[1], passed=False)
    failing = dataclasses.replace(
        validation, results=(validation.results[0], failed, *validation.results[2:])
    )
    monkeypatch.setattr("edsim.cli.validate_arrivals", lambda *args, **kwargs: failing)
    out_dir = tmp_path / "salida"

    code = main(
        ["llegadas", "validar", "--config", str(EXAMPLE), *VALIDATE_ARGS, "--salida", str(out_dir)]
    )

    assert code == 1
    assert "FALLAN b" in capsys.readouterr().out
    for name in PLOTS:
        assert (out_dir / name).is_file()


def test_validar_devuelve_0_si_pasa(tmp_path, monkeypatch):
    validation = small_validation()
    passing = dataclasses.replace(
        validation, results=tuple(dataclasses.replace(r, passed=True) for r in validation.results)
    )
    monkeypatch.setattr("edsim.cli.validate_arrivals", lambda *args, **kwargs: passing)

    code = main(
        ["llegadas", "validar", "--config", str(EXAMPLE), *VALIDATE_ARGS, "--salida", str(tmp_path)]
    )

    assert code == 0


def write_config(tmp_path, text):
    path = tmp_path / "perfil.toml"
    path.write_text(text, encoding="utf-8")
    return str(path)


@pytest.mark.parametrize(
    ("comando", "config", "extra", "message"),
    [
        ("generar", "no_existe.toml", [], "no_existe.toml"),
        ("validar", "no_existe.toml", [], "no_existe.toml"),
        ("generar", "toml_invalido", [], "perfil.toml"),
        ("validar", "toml_invalido", [], "perfil.toml"),
        ("validar", "clave_desconocida", [], "unknown keys: extra"),
        ("generar", "ejemplo", ["--dias", "0"], "days"),
        ("validar", "ejemplo", ["--dias", "13"], "days"),
        ("validar", "ejemplo", ["--replicas", "1"], "replicas"),
        ("validar", "ejemplo", ["--ejecuciones-cortas", "1"], "short_runs"),
        ("validar", "ejemplo", ["--dias", "catorce"], "--dias"),
    ],
)
def test_llegadas_errores_de_uso(comando, config, extra, message, tmp_path, capsys):
    configs = {
        "no_existe.toml": str(tmp_path / "no_existe.toml"),
        "toml_invalido": write_config(tmp_path, "base_diaria = \n"),
        "clave_desconocida": write_config(tmp_path, EXAMPLE.read_text() + "extra = 1\n"),
        "ejemplo": str(EXAMPLE),
    }
    out_dir = tmp_path / "salida"
    base = GENERATE_ARGS if comando == "generar" else VALIDATE_ARGS

    with pytest.raises(SystemExit) as exc:
        main(
            [
                "llegadas",
                comando,
                "--config",
                configs[config],
                *base,
                *extra,
                "--salida",
                str(out_dir),
            ]
        )

    captured = capsys.readouterr()
    assert exc.value.code == 2
    assert message in captured.err
    assert "Traceback" not in captured.err
    # Nada en la salida estándar: ni la cabecera de validar ni resultados.
    assert captured.out == ""
    assert not out_dir.exists()


SALIDA_COMMANDS = {
    "generar": ["llegadas", "generar", "--config", str(EXAMPLE), *GENERATE_ARGS],
    "validar": ["llegadas", "validar", "--config", str(EXAMPLE), *VALIDATE_ARGS],
    "barrido": ["mm1", "barrido", "--rhos", "0.3,0.6", *SMALL_ARGS],
    "motor simular": [
        "motor",
        "simular",
        "--centro",
        str(Path(__file__).parent / "data" / "centro_ejemplo.toml"),
        "--llegadas",
        str(EXAMPLE),
        "--dias",
        "2",
    ],
    "motor validar": [
        "motor",
        "validar",
        "--centro",
        str(Path(__file__).parent / "data" / "centro_ejemplo.toml"),
        "--llegadas",
        str(EXAMPLE),
    ],
}


@pytest.mark.parametrize("comando", SALIDA_COMMANDS)
@pytest.mark.parametrize("dentro", [False, True], ids=["fichero", "dentro_de_un_fichero"])
def test_salida_que_no_es_un_directorio(comando, dentro, tmp_path, capsys):
    # --salida es un fichero, o está dentro de uno: código 2 antes de calcular nada.
    blocker = tmp_path / "ocupado.txt"
    blocker.write_text("no tocar\n")
    out_dir = blocker / "sub" if dentro else blocker

    with pytest.raises(SystemExit) as exc:
        main([*SALIDA_COMMANDS[comando], "--salida", str(out_dir)])

    captured = capsys.readouterr()
    assert exc.value.code == 2
    assert "--salida" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""
    assert blocker.read_text() == "no tocar\n"


def test_config_por_defecto_es_config_llegadas(monkeypatch, tmp_path):
    # Desde la raíz del repositorio, --config se puede omitir.
    monkeypatch.chdir(Path(__file__).parent.parent)
    out_dir = tmp_path / "salida"

    assert main(["llegadas", "generar", "--dias", "1", "--salida", str(out_dir)]) == 0
    with (out_dir / "dias.csv").open(newline="", encoding="utf-8") as f:
        (row,) = csv.DictReader(f)
    assert row["config"] == "config/llegadas.toml"


# --- motor ------------------------------------------------------------------------------

ENGINE_CENTER = Path(__file__).parent / "data" / "centro_ejemplo.toml"
ENGINE_FILES = ("eventos.jsonl", "ground_truth_episodios.csv", "ground_truth_dias.csv")
ENGINE_PLOTS = ("censo.png", "esperas_por_nivel.png", "mg1.png", "censo_por_hora.png")
# Corridas mínimas: aquí se prueba la CLI, no el motor.
SIMULATE_ARGS = [
    "--centro",
    str(ENGINE_CENTER),
    "--llegadas",
    str(EXAMPLE),
    "--dias",
    "2",
    "--calentamiento",
    "1",
    "--semilla",
    "7",
]
ENGINE_VALIDATE_ARGS = ["--centro", str(ENGINE_CENTER), "--llegadas", str(EXAMPLE)]


def simulate_in_memory():
    sink = MemorySink()
    center = load_center(ENGINE_CENTER)
    result = simulate_ed(center, load_profile(EXAMPLE), 2, 7, sink=sink, warmup_days=1)
    return center, sink.events, result


def read_rows(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_simular_escribe_log_y_ground_truth(tmp_path, capsys):
    out_dir = tmp_path / "a" / "b"  # no existe: la CLI debe crearlo

    code = main(["motor", "simular", *SIMULATE_ARGS, "--salida", str(out_dir)])
    out = capsys.readouterr().out

    assert code == 0
    center, events, result = simulate_in_memory()
    # El log del fichero es, evento a evento, el de la misma ejecución en memoria.
    assert list(read_events(out_dir / "eventos.jsonl")) == events
    episodes = read_rows(out_dir / "ground_truth_episodios.csv")
    days = read_rows(out_dir / "ground_truth_dias.csv")
    assert [float(r["minuto_llegada"]) for r in episodes] == [
        e.arrival_time for e in result.ground_truth.episodes
    ]
    assert [int(r["aceptadas"]) for r in days] == [d.accepted for d in result.ground_truth.days]
    for row in (episodes[0], episodes[-1], days[0], days[-1]):
        assert row["centro"] == str(ENGINE_CENTER)
        assert row["huella_centro"] == config_fingerprint(ENGINE_CENTER)
        assert row["llegadas"] == str(EXAMPLE)
        assert row["huella_llegadas"] == config_fingerprint(EXAMPLE)
        assert (row["dias"], row["calentamiento"], row["semilla"]) == ("2", "1", "7")
        assert row["run_id"] == "r7"
    for text in (
        f"huella {config_fingerprint(ENGINE_CENTER)}",
        f"huella {config_fingerprint(EXAMPLE)}",
        "2 días (1 de calentamiento)",
        "semilla 7",
        "run_id r7",
    ):
        assert text in out
    # El resumen impreso es exactamente el de esa ejecución.
    summary = format_run_summary(analyze_run(events, center, 2, 1), [])
    assert summary in out
    assert summary.endswith("Invariantes: 0 violaciones")
    for name in ENGINE_FILES:
        assert str(out_dir / name) in out


def test_simular_con_run_id(tmp_path):
    code = main(
        [
            "motor",
            "simular",
            *SIMULATE_ARGS,
            "--run-id",
            "prueba",
            "--salida",
            str(tmp_path / "salida"),
        ]
    )

    assert code == 0
    first = next(read_events(tmp_path / "salida" / "eventos.jsonl"))
    assert first.run_id == "prueba"
    assert first.event_id == "prueba-000000000"
    (row, *_) = read_rows(tmp_path / "salida" / "ground_truth_dias.csv")
    assert row["run_id"] == "prueba"


def test_simular_devuelve_1_si_falla_una_invariante(tmp_path, monkeypatch, capsys):
    broken = Violation("capacity", "box 3 ocupado dos veces", "r7-000000042", "EP-000007", 99.5)
    monkeypatch.setattr("edsim.runs.service.check_invariants", lambda *args, **kwargs: [broken])

    code = main(["motor", "simular", *SIMULATE_ARGS, "--salida", str(tmp_path / "salida")])
    out = capsys.readouterr().out

    assert code == 1
    assert "Invariantes: FALLAN 1 violaciones (capacity 1)" in out
    assert "box 3 ocupado dos veces" in out
    # Los ficheros se escriben igualmente, para diagnosticar.
    for name in ENGINE_FILES:
        assert (tmp_path / "salida" / name).is_file()


def test_simular_comprueba_las_invariantes_con_el_ground_truth(tmp_path, monkeypatch):
    calls = []

    def spy(events, center, **kwargs):
        calls.append((list(events), center, kwargs))
        return []

    monkeypatch.setattr("edsim.runs.service.check_invariants", spy)

    main(["motor", "simular", *SIMULATE_ARGS, "--salida", str(tmp_path / "salida")])

    center, events, result = simulate_in_memory()
    ((checked, checked_center, kwargs),) = calls
    assert checked == events
    assert checked_center == center
    assert kwargs == {
        "ground_truth": result.ground_truth,
        "inside": result.inside,
        "profiles": None,
    }


def small_engine_validation_with(validation, passed):
    results = tuple(dataclasses.replace(r, passed=passed(r)) for r in validation.results)
    return dataclasses.replace(validation, results=results)


def test_validar_motor_imprime_tabla_y_guarda_las_graficas(
    tmp_path, monkeypatch, capsys, engine_validation_pequena
):
    calls = []

    def fake(*args, **kwargs):
        calls.append((args, kwargs))
        return engine_validation_pequena

    monkeypatch.setattr("edsim.cli.validate_engine", fake)
    out_dir = tmp_path / "salida"

    code = main(
        ["motor", "validar", *ENGINE_VALIDATE_ARGS, "--replicas", "5", "--salida", str(out_dir)]
    )
    out = capsys.readouterr().out

    assert code == 0
    ((args, kwargs),) = calls
    assert args == (load_center(ENGINE_CENTER), load_profile(EXAMPLE))
    assert kwargs == {"seed": 2026, "replicas": 5}
    for text in ("5 réplicas", "semilla 2026", "unos 2 minutos"):
        assert text in out
    # El aviso va antes de la tabla, y la tabla es la del resultado.
    table = format_engine_validation(engine_validation_pequena.results)
    assert out.index("unos 2 minutos") < out.index(table)
    for name in ENGINE_PLOTS:
        assert (out_dir / name).read_bytes().startswith(b"\x89PNG")
        assert str(out_dir / name) in out


def test_validar_motor_devuelve_1_si_falla_y_guarda_las_graficas(
    tmp_path, monkeypatch, capsys, engine_validation_pequena
):
    failing = small_engine_validation_with(
        engine_validation_pequena, lambda r: r.name != "more_doctors"
    )
    monkeypatch.setattr("edsim.cli.validate_engine", lambda *args, **kwargs: failing)

    code = main(["motor", "validar", *ENGINE_VALIDATE_ARGS, "--salida", str(tmp_path)])

    assert code == 1
    assert "FALLAN 4. Más médicos" in capsys.readouterr().out
    for name in ENGINE_PLOTS:
        assert (tmp_path / name).is_file()


@pytest.mark.parametrize(
    ("accion", "extra", "message"),
    [
        ("simular", ["--centro", "no_existe.toml"], "--centro"),
        ("simular", ["--llegadas", "no_existe.toml"], "--llegadas"),
        ("simular", ["--centro", "toml_invalido"], "--centro"),
        ("simular", ["--centro", "centro_invalido"], "recursos.boxes"),
        ("simular", ["--dias", "0"], "days"),
        ("simular", ["--dias", "2", "--calentamiento", "2"], "warmup_days"),
        ("simular", ["--calentamiento", "-1"], "warmup_days"),
        ("simular", ["--dias", "catorce"], "--dias"),
        ("simular", ["--run-id", ""], "--run-id"),
        ("validar", ["--centro", "no_existe.toml"], "--centro"),
        ("validar", ["--llegadas", "toml_invalido"], "--llegadas"),
        ("validar", ["--replicas", "1"], "replicas"),
        ("validar", ["--replicas", "dos"], "--replicas"),
    ],
)
def test_motor_errores_de_uso(accion, extra, message, tmp_path, monkeypatch, capsys):
    # Si algo llegara a simular o validar, el test lo vería.
    monkeypatch.setattr("edsim.cli.validate_engine", lambda *a, **k: pytest.fail("validó"))
    files = {
        "no_existe.toml": str(tmp_path / "no_existe.toml"),
        "toml_invalido": write_config(tmp_path, "boxes = \n"),
        "centro_invalido": write_config(
            tmp_path, ENGINE_CENTER.read_text().replace("boxes = 30", "boxes = 0")
        ),
    }
    extra = [files.get(x, x) for x in extra]
    base = SIMULATE_ARGS if accion == "simular" else ENGINE_VALIDATE_ARGS
    out_dir = tmp_path / "salida"

    with pytest.raises(SystemExit) as exc:
        main(["motor", accion, *base, *extra, "--salida", str(out_dir)])

    captured = capsys.readouterr()
    assert exc.value.code == 2
    assert message in captured.err
    assert "Traceback" not in captured.err
    # Nada en la salida estándar: ni la cabecera ni el aviso de los 2 minutos.
    assert captured.out == ""
    assert not out_dir.exists()


def test_motor_ficheros_por_defecto(monkeypatch, tmp_path):
    # Desde la raíz del repositorio, --centro y --llegadas se pueden omitir.
    monkeypatch.chdir(Path(__file__).parent.parent)
    out_dir = tmp_path / "salida"

    assert (
        main(["motor", "simular", "--dias", "1", "--calentamiento", "0", "--salida", str(out_dir)])
        == 0
    )
    (row,) = read_rows(out_dir / "ground_truth_dias.csv")
    assert (row["centro"], row["llegadas"]) == ("config/centro.toml", "config/llegadas.toml")


@pytest.mark.slow
def test_validar_motor_de_verdad(tmp_path, monkeypatch, capsys, engine_validation_real):
    # La validación completa con los valores por defecto, la misma que el fixture de
    # sesión: la CLI la recibe en lugar de repetirla, y se comprueba que la pide igual.
    root = Path(__file__).parent.parent
    center, profile = root / "config" / "centro.toml", root / "config" / "llegadas.toml"
    calls = []

    def same_validation(*args, **kwargs):
        calls.append((args, kwargs))
        return engine_validation_real

    monkeypatch.setattr("edsim.cli.validate_engine", same_validation)
    code = main(
        [
            "motor",
            "validar",
            "--centro",
            str(center),
            "--llegadas",
            str(profile),
            "--salida",
            str(tmp_path),
        ]
    )
    out = capsys.readouterr().out

    ((args, kwargs),) = calls
    assert args == (load_center(center), load_profile(profile))
    assert kwargs == {"seed": 2026, "replicas": 20}
    assert code == 0, out
    assert "Resultado: pasan las 11 comprobaciones" in out
    for name in ENGINE_PLOTS:
        assert (tmp_path / name).read_bytes().startswith(b"\x89PNG")


def test_simulate_default_output_is_catalog(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["motor", "simular", *SIMULATE_ARGS]) == 0
    output = tmp_path / "resultados" / "ejecuciones" / "r7"
    assert (output / "run.json").is_file()
    assert "resultados/ejecuciones/r7/eventos.jsonl" in capsys.readouterr().out


@pytest.mark.parametrize("kind", ["valid", "incomplete"])
def test_simulate_occupied_output_is_usage_error(tmp_path, monkeypatch, capsys, kind):
    output = tmp_path / "salida"
    if kind == "valid":
        assert main(["motor", "simular", *SIMULATE_ARGS, "--salida", str(output)]) == 0
        capsys.readouterr()
    else:
        output.mkdir()
    original = {p.name: p.read_bytes() for p in output.iterdir()}
    monkeypatch.setattr("edsim.runs.service.simulate_ed", lambda *a, **kw: pytest.fail("simulated"))
    with pytest.raises(SystemExit) as error:
        main(["motor", "simular", *SIMULATE_ARGS, "--salida", str(output)])
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert "--run-id" in captured.err
    assert "ya existe" in captured.err
    assert captured.out == ""
    assert {p.name: p.read_bytes() for p in output.iterdir()} == original


@pytest.mark.parametrize(
    "run_id", [".", "..", "../x", "a/b", "a\\b", "-x", ".x", "a" * 65, "ñ", "a b"]
)
def test_cli_rejects_invalid_directory_run_id(run_id, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("edsim.runs.service.simulate_ed", lambda *a, **kw: pytest.fail("simulated"))
    with pytest.raises(SystemExit) as error:
        main(
            [
                "motor",
                "simular",
                *SIMULATE_ARGS,
                f"--run-id={run_id}",
                "--salida",
                str(tmp_path / "salida"),
            ]
        )
    assert error.value.code == 2
    assert "--run-id" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_cli_rejects_long_automatic_run_id(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("edsim.runs.service.simulate_ed", lambda *a, **kw: pytest.fail("simulated"))
    with pytest.raises(SystemExit) as error:
        main(["motor", "simular", *SIMULATE_ARGS, "--semilla", str(10**70)])
    assert error.value.code == 2
    assert "--run-id explícito" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_simulate_analysis_value_error_propagates(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("injected analysis failure")

    monkeypatch.setattr("edsim.runs.service.analyze_run", fail)
    with pytest.raises(ValueError, match="injected analysis failure"):
        main(["motor", "simular", *SIMULATE_ARGS, "--salida", str(tmp_path / "salida")])
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("option", ["--centro", "--llegadas"])
def test_simulate_invalid_config_names_exact_option(option, tmp_path, capsys):
    invalid = tmp_path / "invalid.toml"
    invalid.write_text("invalid = [\n")
    with pytest.raises(SystemExit) as error:
        main(
            [
                "motor",
                "simular",
                *SIMULATE_ARGS,
                option,
                str(invalid),
                "--salida",
                str(tmp_path / "salida"),
            ]
        )
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert f"{option} {invalid}: " in captured.err
    assert captured.out == ""


def test_simulate_prints_validated_header_before_service(tmp_path, monkeypatch, capsys):
    from edsim.runs import simulate_run

    calls = []

    def simulate_after_header(*args, **kwargs):
        captured = capsys.readouterr()
        assert (
            f"centro {ENGINE_CENTER} (huella {config_fingerprint(ENGINE_CENTER)})" in captured.out
        )
        assert f"llegadas {EXAMPLE} (huella {config_fingerprint(EXAMPLE)})" in captured.out
        assert "2 días (1 de calentamiento) · semilla 7 · run_id r7" in captured.out
        calls.append(True)
        return simulate_run(*args, **kwargs)

    monkeypatch.setattr("edsim.cli.simulate_run", simulate_after_header)
    assert main(["motor", "simular", *SIMULATE_ARGS, "--salida", str(tmp_path / "salida")]) == 0
    assert calls == [True]


def test_simulate_destination_race_is_usage_error(tmp_path, monkeypatch, capsys):
    def race(*args, **kwargs):
        raise FileExistsError("destination occupied after validation")

    monkeypatch.setattr("edsim.cli.simulate_run", race)
    with pytest.raises(SystemExit) as error:
        main(["motor", "simular", *SIMULATE_ARGS, "--salida", str(tmp_path / "salida")])
    assert error.value.code == 2
    assert "ya existe" in capsys.readouterr().err


# --- motor simular --perfiles (tarea 4.5b) ------------------------------------------------

PROFILES = Path(__file__).parent / "data" / "perfiles_ejemplo.toml"


def test_simular_con_perfiles_dice_el_modelo_y_la_huella(tmp_path, capsys):
    out_dir = tmp_path / "salida"

    code = main(
        ["motor", "simular", *SIMULATE_ARGS, "--perfiles", str(PROFILES), "--salida", str(out_dir)]
    )
    out = capsys.readouterr().out

    assert code == 0
    header = out.splitlines()[:3]
    assert (
        header[1] == f"Modelo clínico · perfiles {PROFILES} (huella {config_fingerprint(PROFILES)})"
    )
    assert header[2] == "2 días (1 de calentamiento) · semilla 7 · run_id r7"
    assert out.rstrip().endswith(str(out_dir / "ground_truth_dias.csv"))
    assert (out_dir / "perfiles.toml").read_bytes() == PROFILES.read_bytes()


def test_simular_sin_perfiles_dice_el_modelo_provisional(tmp_path, capsys):
    code = main(["motor", "simular", *SIMULATE_ARGS, "--salida", str(tmp_path / "salida")])

    assert code == 0
    assert capsys.readouterr().out.splitlines()[1] == "Modelo provisional"
    assert not (tmp_path / "salida" / "perfiles.toml").exists()


@pytest.mark.parametrize("kind", ["missing", "directory", "toml", "validation"])
def test_simular_con_perfiles_invalidos_es_un_error_de_uso(kind, tmp_path, capsys, monkeypatch):
    profiles = tmp_path / "perfiles.toml"
    if kind == "directory":
        profiles.mkdir()
    elif kind == "toml":
        profiles.write_text("[roto")
    elif kind == "validation":
        profiles.write_text("desconocida = 1\n")
    monkeypatch.setattr("edsim.runs.service.simulate_ed", lambda *a, **k: pytest.fail("simuló"))
    out_dir = tmp_path / "salida"

    with pytest.raises(SystemExit) as exit_info:
        main(
            [
                "motor",
                "simular",
                *SIMULATE_ARGS,
                "--perfiles",
                str(profiles),
                "--salida",
                str(out_dir),
            ]
        )
    captured = capsys.readouterr()

    assert exit_info.value.code == 2
    assert f"--perfiles {profiles}" in captured.err
    assert captured.out == ""
    assert not out_dir.exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == (
        [] if kind == "missing" else ["perfiles.toml"]
    )


# --- perfiles validar (tarea 4.5b) ----------------------------------------------------------

REPO = Path(__file__).resolve().parents[1]
PROFILE_PLOTS = (
    "motivos.png",
    "triaje.png",
    "pruebas_por_gravedad.png",
    "duraciones_por_nivel.png",
)
# Las comprobaciones rápidas usan un solo contexto en la mezcla (mañana laborable de
# invierno) con validate_profiles sustituida en la CLI; --pacientes es el mínimo con
# margen de los 24 contextos (21 379 con config/ desde la tarea 4.6a), que es el que
# exige la CLI y basta también para ese contexto (20 898). Con menos, la CLI responde
# con el código 2.
MORNING = (ArrivalContext(0, 0, 0),)


@pytest.fixture
def one_context(monkeypatch):
    """La CLI con validate_profiles de un solo contexto y el mínimo de pacientes con margen."""
    from edsim.profiles import validation

    monkeypatch.chdir(REPO)
    patients = validation.mixing_minimum(load_profiles(REPO / "config" / "perfiles.toml"))

    def use(**overrides):
        monkeypatch.setattr(
            "edsim.cli.validate_profiles",
            partial(validation.validate_profiles, contexts=MORNING, **overrides),
        )
        return ["--pacientes", str(patients)]

    return use, patients


def test_perfiles_validar_imprime_la_tabla_y_guarda_las_graficas(one_context, tmp_path, capsys):
    use, patients = one_context
    out_dir = tmp_path / "a" / "b"  # no existe: la CLI debe crearlo

    code = main(["perfiles", "validar", *use(), "--salida", str(out_dir)])
    out = capsys.readouterr().out

    assert code == 0
    huella = config_fingerprint("config/perfiles.toml")
    assert out.startswith(f"Perfiles · config/perfiles.toml (huella {huella})")
    assert f"{patients} pacientes por contexto en la mezcla · {patients} en la muestra" in out
    for label in ("Mezcla de motivos", "Triaje", "Pruebas", "Duraciones"):
        assert any(line.startswith(label) and line.endswith("pasa") for line in out.splitlines())
    assert "hasta un 4 % de las veces" in out
    assert "Resultado: pasan las 4 comprobaciones" in out
    for name in PROFILE_PLOTS:
        assert (out_dir / name).read_bytes().startswith(b"\x89PNG")
        assert f"Gráfica: {out_dir / name}" in out


def test_perfiles_validar_devuelve_1_si_falla_y_guarda_las_graficas(one_context, tmp_path, capsys):
    # Un error grande en el muestreador, con el paquete intacto: los pacientes se sortean
    # con el sesgo del triaje desplazado +1 y la hipótesis es la de los perfiles (el
    # mecanismo de los tests de potencia, sampled_profiles).
    use, _ = one_context
    profiles = load_profiles(REPO / "config" / "perfiles.toml")
    sampled = dataclasses.replace(
        profiles, triage=dataclasses.replace(profiles.triage, bias=profiles.triage.bias + 1.0)
    )

    code = main(["perfiles", "validar", *use(sampled_profiles=sampled), "--salida", str(tmp_path)])
    out = capsys.readouterr().out

    assert code == 1
    assert "Resultado: FALLAN triaje" in out
    (row,) = [line for line in out.splitlines() if line.startswith("Triaje ")]
    assert row.endswith("FALLA")
    for name in PROFILE_PLOTS:
        assert (tmp_path / name).is_file()


@pytest.mark.parametrize(
    "extra, message",
    [
        (["--perfiles", "no-existe.toml"], "--perfiles no-existe.toml"),
        (["--perfiles", "{bad}"], "--perfiles"),
        (["--llegadas", "no-existe.toml"], "--llegadas no-existe.toml"),
        (["--pacientes", "0"], "--pacientes"),
        (["--pacientes", "21378"], "21378 < 21379"),
        (["--semilla", "-1"], "--semilla"),
    ],
)
def test_perfiles_validar_errores_de_uso(extra, message, tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(REPO)
    monkeypatch.setattr("edsim.cli.validate_profiles", lambda *a, **k: pytest.fail("validó"))
    bad = tmp_path / "malo.toml"
    bad.write_text("desconocida = 1\n")
    extra = [str(bad) if x == "{bad}" else x for x in extra]
    out_dir = tmp_path / "salida"

    with pytest.raises(SystemExit) as exit_info:
        main(["perfiles", "validar", *extra, "--salida", str(out_dir)])
    captured = capsys.readouterr()

    assert exit_info.value.code == 2
    assert message in captured.err
    assert captured.out == ""
    assert not out_dir.exists()


def test_perfiles_validar_con_una_salida_que_es_un_fichero(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(REPO)
    monkeypatch.setattr("edsim.cli.validate_profiles", lambda *a, **k: pytest.fail("validó"))
    path = tmp_path / "fichero"
    path.write_text("no tocar")

    with pytest.raises(SystemExit) as exit_info:
        main(["perfiles", "validar", "--salida", str(path)])

    assert exit_info.value.code == 2
    assert "no es un directorio" in capsys.readouterr().err
    assert path.read_text() == "no tocar"


@pytest.mark.slow
def test_perfiles_validar_con_los_valores_por_defecto(tmp_path, capsys, monkeypatch):
    # Criterio de aceptación del hito: perfiles validar pasa con los perfiles reales.
    monkeypatch.chdir(REPO)

    code = main(["perfiles", "validar", "--salida", str(tmp_path)])
    out = capsys.readouterr().out

    assert code == 0, out
    # 25 000 por contexto desde la tarea 4.6a (20 000 antes): 24 × 25 000 = 600 000.
    assert "25000 pacientes por contexto en la mezcla · 109542 en la muestra del año" in out
    (mixing,) = [line for line in out.splitlines() if line.startswith("Mezcla de motivos")]
    assert "600000" in mixing and "2136" in mixing
    for name in PROFILE_PLOTS:
        assert (tmp_path / name).is_file()
