"""engine/report.py: resumen de una ejecución, tabla de validación, CSV y gráficas.

Se usan el centro y el perfil de ejemplo con pocos días: aquí se prueba la
presentación, no el motor. La tabla y las gráficas de la validación usan el
``EngineValidation`` pequeño de ``conftest.py``.
"""

import csv
import dataclasses
import io
from pathlib import Path
from types import MappingProxyType

import numpy as np
import pytest

from edsim.arrivals.profile import load_profile
from edsim.engine.analysis import MEASURES, LevelMetrics, analyze_run
from edsim.engine.center import load_center
from edsim.engine.engine import simulate_ed
from edsim.engine.events import MemorySink
from edsim.engine.invariants import Violation
from edsim.engine.report import (
    DAY_COLUMNS,
    EPISODE_COLUMNS,
    PARAMETER_COLUMNS,
    RunParameters,
    format_engine_validation,
    format_run_summary,
    plot_census,
    plot_hourly_census,
    plot_mg1,
    plot_waits_by_level,
    write_episodes_csv,
    write_ground_truth_days_csv,
)

DATA = Path(__file__).parent / "data"
EXAMPLE_CENTER = DATA / "centro_ejemplo.toml"
EXAMPLE_PROFILE = DATA / "llegadas_ejemplo.toml"
DAYS = 3
WARMUP = 1
SEED = 7

PARAMETERS = RunParameters(
    center="centro.toml",
    center_fingerprint="aaaaaaaaaaaa",
    profile="llegadas.toml",
    profile_fingerprint="bbbbbbbbbbbb",
    days=DAYS,
    warmup_days=WARMUP,
    seed=SEED,
    run_id="r7",
)


@pytest.fixture(scope="module")
def center():
    return load_center(EXAMPLE_CENTER)


@pytest.fixture(scope="module")
def run(center):
    sink = MemorySink()
    result = simulate_ed(
        center, load_profile(EXAMPLE_PROFILE), DAYS, SEED, sink=sink, warmup_days=WARMUP
    )
    return result, analyze_run(sink.events, center, DAYS, WARMUP)


def lines_starting(text, start):
    return [line for line in text.splitlines() if line.startswith(start)]


# --- Resumen de una ejecución ---------------------------------------------------------


def test_resumen_pacientes(run):
    _, analysis = run
    table = analysis.table
    departed = sum(e.departure is not None for e in table)

    text = format_run_summary(analysis, [])

    assert f"{len(table)} llegados, {departed} salidos, {len(table) - departed} dentro" in text
    m = analysis.metrics
    per_day = m.arrivals / (m.end - m.start) * 1440
    assert f"{m.arrivals} llegadas en la ventana, {per_day:.1f} al día" in text


def test_resumen_por_nivel(run):
    _, analysis = run
    text = format_run_summary(analysis, [])

    for metrics, label in (
        *((lv, str(lv.level)) for lv in analysis.metrics.by_level),
        (
            analysis.metrics.overall,
            "total",
        ),
    ):
        (row,) = lines_starting(text, f"{label:<7}")
        assert row.split()[1] == str(metrics.n)
        if metrics.n == 0:
            continue
        for name in ("triage_wait", "box_wait", "doctor_wait", "door_to_doctor", "stay"):
            assert f"{metrics.mean[name]:.1f} / {metrics.p90[name]:.1f}" in row, name


def test_resumen_nivel_sin_episodios(run):
    _, analysis = run
    empty = LevelMetrics(
        1, 0, MappingProxyType(dict.fromkeys(MEASURES)), MappingProxyType(dict.fromkeys(MEASURES))
    )
    metrics = dataclasses.replace(
        analysis.metrics, by_level=(empty, *analysis.metrics.by_level[1:])
    )

    text = format_run_summary(dataclasses.replace(analysis, metrics=metrics), [])

    (row,) = lines_starting(text, "1      ")
    assert row.split()[1] == "0"
    assert row.count("—") == 5


def test_resumen_ocupacion_y_little(run):
    _, analysis = run
    text = format_run_summary(analysis, [])

    labels = {"enfermeria_triaje": "enfermería de triaje", "medicos": "médicos", "boxes": "boxes"}
    for pool, label in labels.items():
        (row,) = lines_starting(text, label)
        ratios = [o.ratio for o in analysis.metrics.occupancy if o.pool == pool]
        assert row.split()[-6:] == [x for r in ratios for x in (f"{100 * r:.1f}", "%")]
    little = {"system": "sistema", "triage_queue": "cola de triaje", "box_queue": "cola de box"}
    for law in analysis.little:
        (row,) = lines_starting(text, little[law.name])
        assert f"{law.l:.4f}" in row
        assert f"{law.lam * law.w:.4f}" in row
        assert row.endswith(f"{100 * law.relative_error:.2f} %")


def test_resumen_sin_violaciones(run):
    _, analysis = run
    assert format_run_summary(analysis, []).endswith("Invariantes: 0 violaciones")


def test_resumen_con_violaciones(run):
    _, analysis = run
    violations = [
        Violation("capacity", f"box {i} ocupado dos veces", f"r7-{i:09d}", "EP-000001", 10.0 + i)
        for i in range(11)
    ] + [Violation("conservation", "falta un episodio")]

    text = format_run_summary(analysis, violations)

    assert "Invariantes: FALLAN 12 violaciones (capacity 11, conservation 1)" in text
    shown = lines_starting(text, "    capacity")
    assert len(shown) == 10
    assert "r7-000000000" in shown[0] and "10.0000" in shown[0]
    assert "box 0 ocupado dos veces" in shown[0]
    assert text.endswith("    … y 2 más")


# --- Tabla de validación -----------------------------------------------------------------

LABELS = (
    "1. Invariantes",
    "2. Little: sistema",
    "2. Little: cola de triaje",
    "2. Little: cola de box",
    "2. Utilización: enfermería de triaje",
    "2. Utilización: médicos",
    "2. Utilización: boxes",
    "3a. M/G/1",
    "3b. Mₜ/G/∞",
    "4. Capacidad infinita",
    "4. Más médicos",
)


def test_tabla_todas_pasan(engine_validation_pequena):
    v = engine_validation_pequena
    lines = format_engine_validation(v.results).splitlines()

    assert lines[0].split()[:4] == ["comprobación", "valor", "IC", "o"]
    rows = [line for line in lines if line.startswith(LABELS)]
    assert len(rows) == len(LABELS) == len(v.results)
    for label, row in zip(LABELS, rows, strict=True):
        assert row.startswith(label)
        assert row.endswith("pasa")
    assert lines[-1] == "Resultado: pasan las 11 comprobaciones"
    # Los tres IC de la M/G/1, debajo de su fila; ninguna hora fuera de su IC.
    mg1 = v.result("mg1")
    for label, detail in zip(("Wq", "ρ", "Lq"), mg1.details, strict=True):
        (row,) = lines_starting("\n".join(lines), f"    {label} ")
        assert f"[{detail.ci_low:.4f}, {detail.ci_high:.4f}]" in row
        assert f"{detail.target:.4f}" in row
    assert "fuera de su IC" not in "\n".join(lines)


def test_tabla_valores(engine_validation_pequena):
    v = engine_validation_pequena
    text = format_engine_validation(v.results)

    (little,) = lines_starting(text, "2. Little: sistema")
    assert f"{100 * v.result('little_system').statistic:.2f} %" in little
    assert "≤ 2 %" in little
    (mg1,) = lines_starting(text, "3a. M/G/1")
    r = v.result("mg1")
    assert f"{r.statistic:.2f}" in mg1
    assert f"[{r.ci_low:.2f}, {r.ci_high:.2f}]" in mg1
    assert "99.667 %" in mg1
    (more,) = lines_starting(text, "4. Más médicos")
    assert "-3.70" in more and "[-4.50, -2.90]" in more and "99 %" in more


def test_tabla_marca_los_fallos(engine_validation_pequena):
    v = engine_validation_pequena
    results = list(v.results)
    results[1] = dataclasses.replace(results[1], passed=False)
    results[7] = dataclasses.replace(results[7], passed=False)

    text = format_engine_validation(results)

    (little,) = lines_starting(text, "2. Little: sistema")
    assert little.endswith("FALLA")
    assert text.splitlines()[-1] == "Resultado: FALLAN 2. Little: sistema, 3a. M/G/1"


def test_tabla_horas_fuera_de_la_mtginf(engine_validation_pequena):
    v = engine_validation_pequena
    mtginf = v.result("mtginf")
    details = list(mtginf.details)
    details[5] = dataclasses.replace(details[5], passed=False)
    failing = dataclasses.replace(mtginf, statistic=1.0, passed=False, details=tuple(details))
    results = [failing if r.name == "mtginf" else r for r in v.results]

    text = format_engine_validation(results)

    assert "Horas de la Mₜ/G/∞ fuera de su IC" in text
    hours = lines_starting(text, "    ")
    hour_rows = [line for line in hours if line.lstrip()[:3].endswith("h")]
    assert len(hour_rows) == 1
    assert hour_rows[0].lstrip().startswith("05h")
    assert f"{details[5].target:.4f}" in hour_rows[0]


# --- CSV del ground truth -------------------------------------------------------------------


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def check_parameters(row):
    assert tuple(row[c] for c in PARAMETER_COLUMNS) == (
        "centro.toml",
        "aaaaaaaaaaaa",
        "llegadas.toml",
        "bbbbbbbbbbbb",
        str(DAYS),
        str(WARMUP),
        str(SEED),
        "r7",
    )


def test_csv_de_episodios(run, tmp_path):
    result, _ = run
    path = tmp_path / "ground_truth_episodios.csv"

    write_episodes_csv(result.ground_truth.episodes, path, PARAMETERS)
    header, rows = read_csv(path)

    assert tuple(header) == EPISODE_COLUMNS
    assert len(rows) == len(result.ground_truth.episodes)
    for row, e in zip(rows, result.ground_truth.episodes, strict=True):
        assert row["episodio"] == e.episode_id
        assert int(row["llegada"]) == e.arrival_id
        # Todas las cifras: la lectura devuelve el mismo float, bit a bit.
        assert float(row["minuto_llegada"]) == e.arrival_time
        assert int(row["nivel"]) == e.level
        assert float(row["triaje"]) == e.triage_time
        assert float(row["valoracion"]) == e.assessment_time
        assert float(row["reevaluacion"]) == e.reassessment_time
        assert row["pruebas"] == str(e.needs_tests)
        assert float(row["respuesta_pruebas"]) == e.test_turnaround
        assert row["destino"] == ("ingreso" if e.admitted else "alta")
        check_parameters(row)


def test_csv_de_dias(run, tmp_path):
    result, _ = run
    path = tmp_path / "ground_truth_dias.csv"

    write_ground_truth_days_csv(result.ground_truth.days, path, PARAMETERS)
    header, rows = read_csv(path)

    assert tuple(header) == DAY_COLUMNS
    assert len(rows) == DAYS
    for row, d in zip(rows, result.ground_truth.days, strict=True):
        assert int(row["dia"]) == d.day
        assert row["fecha"] == d.date.isoformat()
        assert float(row["efecto_diario"]) == d.day_effect
        assert float(row["esperadas"]) == d.expected
        assert float(row["cota"]) == d.bound
        assert int(row["candidatas"]) == d.candidates
        assert int(row["aceptadas"]) == d.accepted
        check_parameters(row)


# --- Gráficas ------------------------------------------------------------------------------


def line(ax, label):
    (found,) = [li for li in ax.get_lines() if li.get_label() == label]
    return found


def png_bytes(fig):
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png")
    return buffer.getvalue()


def test_grafica_censo(run, center):
    _, analysis = run
    start_date = load_profile(EXAMPLE_PROFILE).start_date

    fig = plot_census(analysis, center, start_date)
    (ax,) = fig.axes

    # Una semana desde el fin del calentamiento, recortada al horizonte (2 días aquí).
    assert ax.get_xlim() == (WARMUP, DAYS)
    stairs = {p.get_label(): p for p in ax.patches}
    assert set(stairs) == {"Censo", "Boxes ocupados"}
    for label, name in (("Censo", "census"), ("Boxes ocupados", "boxes_busy")):
        values, edges, _ = stairs[label].get_data()
        assert edges[0] == WARMUP and edges[-1] == DAYS
        # Cada escalón es el valor de la curva en ese instante.
        middle = (edges[:-1] + edges[1:]) / 2 * 1440
        expected = [analysis.curves.value(name, t) for t in middle]
        np.testing.assert_array_equal(values, expected)
    capacity = line(ax, f"Capacidad: {center.boxes} boxes")
    assert set(capacity.get_ydata()) == {center.boxes}
    assert png_bytes(fig).startswith(b"\x89PNG")


def test_grafica_censo_semana_completa(center):
    # Con un horizonte largo se dibujan 7 días exactos desde el fin del calentamiento.
    sink = MemorySink()
    simulate_ed(center, load_profile(EXAMPLE_PROFILE), 10, SEED, sink=sink, warmup_days=2)
    analysis = analyze_run(sink.events, center, 10, 2)

    fig = plot_census(analysis, center, load_profile(EXAMPLE_PROFILE).start_date)

    assert fig.axes[0].get_xlim() == (2, 9)


def test_grafica_esperas_por_nivel(run):
    _, analysis = run
    m = analysis.metrics
    empty = LevelMetrics(
        5, 0, MappingProxyType(dict.fromkeys(MEASURES)), MappingProxyType(dict.fromkeys(MEASURES))
    )
    m = dataclasses.replace(m, by_level=(*m.by_level[:4], empty))

    fig = plot_waits_by_level(m)

    assert [ax.get_title() for ax in fig.axes] == ["Box", "Médico", "Puerta-médico"]
    for ax, name in zip(fig.axes, ("box_wait", "doctor_wait", "door_to_doctor"), strict=True):
        levels = m.by_level[:4]  # el nivel 5 no tiene episodios: no se dibuja
        heights = [bar.get_height() for bar in ax.containers[0]]
        np.testing.assert_allclose(heights, [lv.mean[name] for lv in levels])
        p90 = line(ax, "p90")
        np.testing.assert_allclose(p90.get_ydata(), [lv.p90[name] for lv in levels])
        labels = [t.get_text() for t in ax.get_xticklabels()]
        assert labels == [f"{lv.level}\nn = {lv.n}" for lv in levels]
    assert png_bytes(fig).startswith(b"\x89PNG")


def test_grafica_mg1(engine_validation_pequena):
    v = engine_validation_pequena
    replicas, wq = v.mg1, v.result("mg1").details[0]
    theory = replicas.theory

    fig = plot_mg1(replicas, wq)
    (ax,) = fig.axes

    points = line(ax, f"Wq de cada réplica ({len(replicas.wq)})")
    np.testing.assert_array_equal(points.get_xdata(), np.arange(1, len(replicas.wq) + 1))
    np.testing.assert_array_equal(points.get_ydata(), replicas.wq)
    pk = line(ax, f"Pollaczek–Khinchine: {theory.wq:.2f} min")
    assert set(pk.get_ydata()) == {theory.wq}
    # La M/M/1 es Pollaczek–Khinchine con el segundo momento de una exponencial,
    # E[S²] = 2·E[S]²; debe quedar por encima de la lognormal, de CV menor que 1.
    mm1 = theory.lam * 2 * theory.mean_service**2 / (2 * (1 - theory.rho))
    reference = line(ax, f"M/M/1 de la misma media: {mm1:.2f} min")
    assert list(reference.get_ydata()) == pytest.approx([mm1, mm1])
    assert mm1 > theory.wq
    mean = line(ax, f"Media {wq.statistic:.2f} e IC al 99.667 %")
    assert set(mean.get_ydata()) == {wq.statistic}
    # La banda del IC es la del detalle wq, el mismo de la tabla.
    (band,) = ax.patches
    assert (band.get_y(), band.get_y() + band.get_height()) == pytest.approx(
        (wq.ci_low, wq.ci_high)
    )
    assert png_bytes(fig).startswith(b"\x89PNG")


def test_grafica_censo_por_hora(engine_validation_pequena):
    hourly = engine_validation_pequena.hourly

    fig = plot_hourly_census(hourly)
    (ax,) = fig.axes

    expected = line(ax, "m(t): carga ofrecida")
    np.testing.assert_array_equal(expected.get_ydata(), hourly.expected)
    (container,) = ax.containers
    data = container.lines[0]
    mean = hourly.census.mean(axis=0)
    np.testing.assert_array_equal(data.get_xdata(), np.arange(24))
    np.testing.assert_allclose(data.get_ydata(), mean)
    # Las barras de error van del límite inferior al superior de cada IC.
    (bars,) = container.lines[2]
    segments = bars.get_segments()
    np.testing.assert_allclose([s[0][1] for s in segments], hourly.ci_low)
    np.testing.assert_allclose([s[1][1] for s in segments], hourly.ci_high)
    assert png_bytes(fig).startswith(b"\x89PNG")
