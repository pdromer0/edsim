import csv
import dataclasses
from importlib.metadata import version

import numpy as np
import pytest

from edsim.cli import main
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


@pytest.mark.parametrize("argv", [[], ["mm1"]])
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
