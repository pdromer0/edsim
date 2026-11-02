"""engine/report.py: resumen de una ejecución, tabla de validación, CSV y gráficas.

Se usan el centro y el perfil de ejemplo con pocos días: aquí se prueba la
presentación, no el motor. La tabla y las gráficas de la validación usan el
``EngineValidation`` pequeño de ``conftest.py``.
"""

import csv
import dataclasses
from pathlib import Path
from types import MappingProxyType

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
