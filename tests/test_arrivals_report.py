import csv
import dataclasses
import hashlib
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from scipy import stats

from edsim.arrivals.profile import load_profile
from edsim.arrivals.report import (
    ARRIVALS_COLUMNS,
    DAYS_COLUMNS,
    config_fingerprint,
    format_validation,
    plot_daily_residuals,
    plot_hourly_profile,
    plot_rescaled_qq,
    write_arrivals_csv,
    write_days_csv,
)
from edsim.arrivals.thinning import ArrivalRecord, simulate_arrivals
from edsim.arrivals.validation import (
    daily_residuals,
    hourly_counts,
    rescaled_gaps,
    validate_arrivals,
)

EXAMPLE = Path(__file__).parent / "data" / "llegadas_ejemplo.toml"
PARAMS = {"config": "config/llegadas.toml", "fingerprint": "0123456789ab", "days": 14, "seed": 7}


@pytest.fixture(scope="module")
def example():
    return load_profile(EXAMPLE)


@pytest.fixture(scope="module")
def run(example):
    return simulate_arrivals(example, 14, 5)


@pytest.fixture(scope="module")
def validation(example):
    # Corrida mínima: aquí se prueba la presentación, no la estadística.
    return validate_arrivals(example, 14, 2, 7, short_runs=2, short_days=2)


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


# --- Huella del fichero de configuración ----------------------------------------


def test_huella_son_los_12_primeros_caracteres_del_sha256(tmp_path):
    path = tmp_path / "perfil.toml"
    path.write_bytes(b"abc")

    # SHA-256 de "abc", el vector de prueba de FIPS 180-2: ba7816bf8f01cfea…
    assert config_fingerprint(path) == "ba7816bf8f01"
    assert config_fingerprint(EXAMPLE) == hashlib.sha256(EXAMPLE.read_bytes()).hexdigest()[:12]


# --- llegadas.csv -----------------------------------------------------------------


def test_csv_de_llegadas_fechas_a_mano(example, tmp_path):
    # El minuto 0 es el lunes 5 de enero de 2026 a las 0:00.
    times = [0.0, 1439.9999999, 1500.5, 6 * 1440 + 1439.75]
    arrivals = tuple(ArrivalRecord(arrival_id=i, time=t) for i, t in enumerate(times))
    path = tmp_path / "llegadas.csv"

    write_arrivals_csv(arrivals, example.start_date, path, **PARAMS)
    header, rows = read_csv(path)

    assert header == list(ARRIVALS_COLUMNS)
    assert header == [
        "id",
        "minuto",
        "fecha_hora",
        "dia_semana",
        "hora",
        "config",
        "huella",
        "dias",
        "semilla",
    ]
    assert [(r["fecha_hora"], r["dia_semana"], r["hora"]) for r in rows] == [
        ("2026-01-05T00:00:00", "lunes", "0"),
        # Se trunca a segundos: el instante sigue en el día 0 y en la hora 23.
        ("2026-01-05T23:59:59", "lunes", "23"),
        # 1500,5 min = 1 día + 60,5 min: martes a la 1:00:30.
        ("2026-01-06T01:00:30", "martes", "1"),
        ("2026-01-11T23:59:45", "domingo", "23"),
    ]
    assert [int(r["id"]) for r in rows] == [0, 1, 2, 3]
    # El minuto se escribe con todas sus cifras: la lectura es exacta.
    assert [float(r["minuto"]) for r in rows] == times
    for r in rows:
        assert (r["config"], r["huella"], r["dias"], r["semilla"]) == (
            "config/llegadas.toml",
            "0123456789ab",
            "14",
            "7",
        )


def test_csv_de_llegadas_una_fila_por_llegada(example, run, tmp_path):
    arrivals, _ = run
    path = tmp_path / "llegadas.csv"

    write_arrivals_csv(arrivals, example.start_date, path, **PARAMS)
    _, rows = read_csv(path)

    assert len(rows) == len(arrivals)
    assert [float(r["minuto"]) for r in rows] == [a.time for a in arrivals]


# --- dias.csv -----------------------------------------------------------------------


def test_csv_de_dias(run, tmp_path):
    _, days = run
    path = tmp_path / "dias.csv"

    write_days_csv(days, path, **PARAMS)
    header, rows = read_csv(path)

    assert header == list(DAYS_COLUMNS)
    assert header == [
        "dia",
        "fecha",
        "efecto_diario",
        "esperadas",
        "cota",
        "candidatas",
        "aceptadas",
        "config",
        "huella",
        "dias",
        "semilla",
    ]
    assert len(rows) == 14
    assert rows[0]["fecha"] == "2026-01-05"
    assert rows[13]["fecha"] == "2026-01-18"
    for row, d in zip(rows, days, strict=True):
        assert int(row["dia"]) == d.day
        assert date.fromisoformat(row["fecha"]) == d.date
        assert float(row["efecto_diario"]) == d.day_effect
        assert float(row["esperadas"]) == d.expected
        assert float(row["cota"]) == d.bound
        assert int(row["candidatas"]) == d.candidates
        assert int(row["aceptadas"]) == d.accepted
        assert row["huella"] == "0123456789ab"


# --- Tabla de validación ------------------------------------------------------------

LABELS = [
    "a. Volumen",
    "b. Forma horaria",
    "c. Huecos reescalados",
    "d. Dispersión diaria",
    "e. Uniformidad de los p-valores",
]
DETAILS_A = ["total", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def test_tabla_cinco_pruebas_y_sus_detalles(validation):
    lines = format_validation(validation.results).splitlines()

    assert lines[0].split()[:2] == ["prueba", "estadístico"]
    starts = [next(i for i, line in enumerate(lines) if line.startswith(lab)) for lab in LABELS]
    assert starts == sorted(starts)

    # Debajo de a, sus 8 intervalos, indentados; debajo de d, los dos Pearson.
    a, b, c, d, e = starts
    assert [line.split()[0] for line in lines[a + 1 : b]] == DETAILS_A
    assert all(line.startswith("    ") for line in lines[a + 1 : b])
    assert [line[4:15].strip() for line in lines[d + 1 : e]] == ["sin Z", "condicional"]
    assert b + 1 == c and c + 1 == d


def test_tabla_valores_de_cada_fila(validation):
    lines = format_validation(validation.results).splitlines()
    volume, shape, *_ = validation.results

    row_a = next(line for line in lines if line.startswith("a. Volumen"))
    assert f"{volume.statistic:.4f}" in row_a
    assert f"[{volume.ci_low:.4f}, {volume.ci_high:.4f}]" in row_a
    assert "objetivo ∈ IC 99.875 %" in row_a

    row_b = next(line for line in lines if line.startswith("b. Forma horaria"))
    assert f"{shape.statistic:.4f}" in row_b
    assert f"p = {shape.p_value:.4f}" in row_b
    assert "p ≥ 0.01" in row_b

    row_d = next(line for line in lines if line.strip().startswith("sin Z"))
    assert f"{validation.results[3].details[0].target:.4f}" in row_d
    assert "objetivo ∈ IC 99.5 %" in row_d


def passed(result, value=True):
    """The result with ``passed`` set to ``value``, and its details passing."""
    details = tuple(dataclasses.replace(x, passed=True) for x in result.details)
    return dataclasses.replace(result, passed=value, details=details)


def test_tabla_marca_los_fallos(validation):
    passing = [passed(r) for r in validation.results]
    # Falla el lunes, y con él la prueba a; falla también d.
    volume = passed(validation.results[0], False)
    monday = dataclasses.replace(volume.details[1], passed=False)
    volume = dataclasses.replace(volume, details=(volume.details[0], monday, *volume.details[2:]))
    failing = [volume, *passing[1:3], passed(validation.results[3], False), passing[4]]

    ok = format_validation(passing).splitlines()
    bad = format_validation(failing).splitlines()

    assert all(not line.endswith("FALLA") for line in ok)
    assert ok[-1] == "Resultado: pasan las 5 pruebas"
    row_a = next(line for line in bad if line.startswith("a. Volumen"))
    row_monday = next(line for line in bad if line.strip().startswith("lunes"))
    row_total = next(line for line in bad if line.strip().startswith("total"))
    assert row_a.endswith("FALLA")
    assert row_monday.endswith("FALLA")
    assert row_total.endswith("pasa")
    assert bad[-1] == "Resultado: FALLAN a, d"


# --- Gráficas ---------------------------------------------------------------------


def test_grafica_perfil_horario(example, run):
    arrivals, days = run
    observed, expected = hourly_counts(example, arrivals, days)

    fig = plot_hourly_profile(example, arrivals, days)
    (ax,) = fig.axes

    assert len(ax.patches) == 24
    assert [p.get_height() for p in ax.patches] == observed.tolist()
    (line,) = ax.get_lines()
    np.testing.assert_allclose(line.get_ydata(), expected)
    assert ax.get_xlabel() and ax.get_ylabel()
    assert ax.get_legend() is not None


def test_grafica_qq_reescalado(example, run):
    arrivals, days = run
    gaps = np.sort(rescaled_gaps(example, arrivals, days))
    n = len(arrivals)

    fig = plot_rescaled_qq(example, arrivals, days)
    (ax,) = fig.axes
    points, diagonal = ax.get_lines()

    assert len(points.get_xdata()) == n
    np.testing.assert_allclose(points.get_ydata(), gaps)
    np.testing.assert_allclose(points.get_xdata(), stats.expon.ppf((np.arange(1, n + 1) - 0.5) / n))
    np.testing.assert_allclose(diagonal.get_xdata(), diagonal.get_ydata())
    assert ax.get_xlabel() and ax.get_ylabel()


def test_grafica_residuos_diarios(example, validation):
    runs = validation.replications
    conditional = np.concatenate([daily_residuals(example, r)[0] for r in runs])
    unconditional = np.concatenate([daily_residuals(example, r)[1] for r in runs])

    fig = plot_daily_residuals(example, runs)
    axes = fig.axes

    assert len(axes) == 2
    for ax, residuals in zip(axes, (conditional, unconditional), strict=True):
        assert len(ax.patches) == 40
        # Histograma de densidad: las barras suman área 1 y cubren todos los residuos.
        widths = np.array([p.get_width() for p in ax.patches])
        heights = np.array([p.get_height() for p in ax.patches])
        assert np.sum(widths * heights) == pytest.approx(1)
        assert ax.patches[0].get_x() <= residuals.min()
        (curve,) = ax.get_lines()
        np.testing.assert_allclose(curve.get_ydata(), stats.norm.pdf(curve.get_xdata()))
        assert ax.get_xlabel()
    assert "Z" in axes[0].get_title() and "Z" in axes[1].get_title()
