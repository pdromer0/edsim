"""CLI de la calibración: calibracion evaluar y calibracion sensibilidad (tarea 4.6b)."""

import csv
import dataclasses
from pathlib import Path

import pytest

from edsim.arrivals.profile import load_profile
from edsim.calibration import evaluate
from edsim.calibration.evaluate import pooled_value, simulate_replicas, summarize_targets
from edsim.calibration.targets import load_targets
from edsim.calibration.window import first_mondays
from edsim.cli import main
from edsim.engine.center import load_center
from edsim.profiles.config import load_profiles

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
# La ventana de la 4.6b con 2 réplicas; la anual siempre tiene 12.
SHORT = ["--ventana", "inicio", "--replicas", "2", "--dias", "2", "--calentamiento", "1"]
SHORT += ["--semilla", "7"]
ANNUAL_SHORT = ["--dias", "2", "--calentamiento", "1", "--semilla", "7"]
MONDAYS_2026 = [d.isoformat() for d in first_mondays(2026)]


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
    assert (
        "2 réplicas de 2 días (1 de calentamiento y 1 de vaciado) · ventana inicio (todas"
        " desde 2026-01-05) · semilla 7" in out
    )
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
        (["--ventana", "inicio", "--replicas", "1"], "replicas must be an integer >= 2"),
        (["--replicas", "10"], "la ventana anual tiene 12 réplicas, una por mes"),
        (["--ventana", "anual", "--replicas", "2"], "la ventana anual tiene 12 réplicas"),
        (["--ventana", "mensual"], "invalid choice: 'mensual'"),
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
        (
            ["--mando", "medicos", "--comprobacion", "2026"],
            "la semilla de comprobación (2026) tiene que ser distinta de la de ajuste (2026)",
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
    assert (
        "con la semilla de ajuste; la de comprobación puede vetarla (--comprobacion, decisión 41)"
        in out
    )
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


# --- La ventana (tarea 4.6c) -----------------------------------------------------------------


def example_inputs(targets_path):
    return (
        load_center(DATA / "centro_sala_ejemplo.toml"),
        load_profile(DATA / "llegadas_ejemplo.toml"),
        load_profiles(DATA / "perfiles_ejemplo.toml"),
        load_targets(targets_path),
    )


class Simulated(Exception):
    """Para la CLI en cuanto pide simular, con los argumentos que le pasa."""


@pytest.mark.parametrize(
    ("extra", "replicas", "dates"),
    [
        ([], 12, tuple(first_mondays(2026))),
        (["--replicas", "12"], 12, tuple(first_mondays(2026))),
        (["--ventana", "anual", "--replicas", "12"], 12, tuple(first_mondays(2026))),
        (["--ventana", "inicio"], 10, None),
        (["--ventana", "inicio", "--replicas", "4"], 4, None),
    ],
)
@pytest.mark.parametrize("command", [["evaluar"], ["sensibilidad", "--mando", "medicos"]])
def test_replicas_y_fechas_de_cada_ventana(command, extra, replicas, dates, tmp_path, monkeypatch):
    def stop(*args, **kwargs):
        raise Simulated(kwargs["replicas"], kwargs["start_dates"])

    monkeypatch.chdir(REPO)
    monkeypatch.setattr("edsim.cli.simulate_replicas", stop)
    monkeypatch.setattr("edsim.cli.sensitivity", stop)
    with pytest.raises(Simulated) as info:
        main(["calibracion", *command, *extra, "--salida", str(tmp_path / "salida")])
    assert info.value.args == (replicas, dates)


def test_evaluar_con_la_ventana_anual_una_replica_por_mes(tmp_path, capsys):
    targets = targets_file(tmp_path / "objetivos.toml")
    out_dir = tmp_path / "salida"

    code = main(
        ["calibracion", "evaluar", *EXAMPLE, "--objetivos", str(targets), *ANNUAL_SHORT]
        + ["--salida", str(out_dir)]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert (
        "12 réplicas de 2 días (1 de calentamiento y 1 de vaciado) · ventana anual (una"
        " réplica por mes, desde el primer lunes de cada mes de 2026) · semilla 7" in out
    )
    assert "Por réplica (ventana anual: una por mes" in out
    assert all(f"{m} {d}" in out for m, d in (("ene", 5), ("jul", 6), ("dic", 7)))
    assert "Media por paciente de todas las réplicas" in out

    rows = read_rows(out_dir / "evaluacion_replicas.csv")
    assert len(rows) == 12 * 4
    assert [r["fecha_inicio"] for r in rows[::4]] == MONDAYS_2026
    assert len({r["fecha_inicio"] for r in rows}) == 12
    assert [r["replica"] for r in rows[::4]] == [str(i) for i in range(12)]
    assert {r["ventana"] for r in rows} == {"anual"} and {r["replicas"] for r in rows} == {"12"}

    # La media por paciente del CSV es pooled_value de las mismas réplicas.
    inputs = example_inputs(targets)
    reduced = simulate_replicas(
        *inputs, replicas=12, days=2, warmup_days=1, seed=7, start_dates=first_mondays(2026)
    )
    evaluation = read_rows(out_dir / "evaluacion.csv")
    assert [float(r["media_por_paciente"]) for r in evaluation] == [
        pooled_value(reduced, t) for t in inputs[3]
    ]
    assert {r["ventana"] for r in evaluation} == {"anual"}


def test_evaluar_con_la_ventana_de_inicio_reproduce_la_4_6b(tmp_path, capsys):
    # Todas desde fecha_inicio y con los mismos valores que simulate_replicas sin fechas
    # (las 10 réplicas por defecto, en test_replicas_y_fechas_de_cada_ventana).
    targets = targets_file(tmp_path / "objetivos.toml")
    out_dir = tmp_path / "salida"

    code = main(
        ["calibracion", "evaluar", *EXAMPLE, "--objetivos", str(targets), "--ventana", "inicio"]
        + ["--replicas", "3", *ANNUAL_SHORT, "--salida", str(out_dir)]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert "3 réplicas de 2 días" in out and "ventana inicio (todas desde 2026-01-05)" in out
    rows = read_rows(out_dir / "evaluacion_replicas.csv")
    assert len(rows) == 3 * 4
    assert {r["fecha_inicio"] for r in rows} == {"2026-01-05"}
    assert {r["ventana"] for r in rows} == {"inicio"}

    inputs = example_inputs(targets)
    results = summarize_targets(
        simulate_replicas(*inputs, replicas=3, days=2, warmup_days=1, seed=7), inputs[3]
    )
    evaluation = read_rows(out_dir / "evaluacion.csv")
    assert [float(r["media"]) for r in evaluation] == [r.mean for r in results]


def test_sensibilidad_de_los_medicos_con_la_ventana_anual(tmp_path, capsys):
    targets = targets_file(tmp_path / "objetivos.toml")
    out_dir = tmp_path / "salida"

    code = main(
        ["calibracion", "sensibilidad", "--mando", "medicos", *EXAMPLE]
        + ["--objetivos", str(targets), *ANNUAL_SHORT, "--u-min", "0.95", "--u-max", "0.95"]
        + ["--salida", str(out_dir)]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert "12 réplicas de 2 días" in out and "ventana anual" in out
    assert "días fuera de Manchester (C) / días medidos, sumados" in out
    rows = read_rows(out_dir / "sensibilidad_medicos.csv")
    assert {r["ventana"] for r in rows} == {"anual"} and {r["replicas"] for r in rows} == {"12"}
    # Un día medido por réplica: 12 días medidos por nivel, sumados en las 12 réplicas.
    assert {r[f"dias_medidos_c_nivel_{k}"] for r in rows for k in (2, 3, 4)} == {"12"}
    assert all(0 <= int(r["dias_fuera_c_nivel_4"]) <= 12 for r in rows)


# --- El veto de la semilla de comprobación (revisión del PR #50) -----------------------------

NURSE_SHORT = ["--mando", "enfermeria_triaje", "--u-min", "0.6", "--u-max", "0.9"]


def check_spy(monkeypatch, verdicts):
    """Espía de la comprobación: evaluate_staffings real con lo que pide la CLI, y cada
    candidata pasa o falla según ``verdicts`` en el orden en que se piden (las que faltan,
    fallan). Devuelve la lista de llamadas: (semilla, plantillas, réplicas, días, fechas)."""
    calls = []

    def spy(center, profile, profiles, targets, knob, staffings, **kwargs):
        calls.append(
            (
                kwargs["seed"],
                [s.staff for s in staffings],
                kwargs["replicas"],
                kwargs["days"],
                kwargs["start_dates"],
            )
        )
        rows = evaluate.evaluate_staffings(
            center, profile, profiles, targets, knob, staffings, **kwargs
        )
        passed = verdicts[len(calls) - 1] if len(calls) <= len(verdicts) else False
        return tuple(
            dataclasses.replace(
                row,
                results=tuple(
                    dataclasses.replace(r, within=passed, narrow=passed) for r in row.results
                ),
            )
            for row in rows
        )

    monkeypatch.setattr("edsim.cli.evaluate_staffings", spy)
    return calls


def chosen_in_csv(out_dir):
    rows = read_rows(out_dir / "sensibilidad_enfermeria_triaje.csv")
    return {(r["manana"], r["tarde"], r["noche"]) for r in rows if r["elegida"] == "True"}


def test_la_comprobacion_veta_una_candidata_y_elige_la_siguiente(tmp_path, capsys, monkeypatch):
    calls = check_spy(monkeypatch, [False, True])
    targets = targets_file(tmp_path / "objetivos.toml")
    out_dir = tmp_path / "salida"

    code = main(
        ["calibracion", "sensibilidad", *NURSE_SHORT, *EXAMPLE, "--objetivos", str(targets)]
        + [*SHORT, "--comprobacion", "8", "--salida", str(out_dir)]
    )
    out = capsys.readouterr().out

    assert code == 0
    # Dos llamadas, una plantilla en cada una, con la semilla de comprobación y el resto
    # de opciones de la de ajuste.
    assert [(c[0], len(c[1]), c[2], c[3], c[4]) for c in calls] == [(8, 1, 2, 2, None)] * 2
    vetoed, chosen = calls[0][1][0], calls[1][1][0]
    assert vetoed != chosen
    assert "Comprobación con la semilla 8" in out
    assert f"{list(vetoed)}".replace(" ", "") in out.replace(" ", "")
    assert "vetada" in out and "elegida" in out
    assert "Elección (entre las que pasan pretriaje_medio con las semillas 7 y 8" in out
    assert f"): {list(chosen)} con u" in out
    assert chosen_in_csv(out_dir) == {tuple(str(x) for x in chosen)}


def test_la_comprobacion_se_pide_solo_hasta_la_primera_que_pasa(tmp_path, capsys, monkeypatch):
    calls = check_spy(monkeypatch, [True])
    targets = targets_file(tmp_path / "objetivos.toml")
    out_dir = tmp_path / "salida"

    code = main(
        ["calibracion", "sensibilidad", *NURSE_SHORT, *EXAMPLE, "--objetivos", str(targets)]
        + [*SHORT, "--comprobacion", "8", "--salida", str(out_dir)]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert len(calls) == 1
    assert "vetada" not in out
    assert chosen_in_csv(out_dir) == {tuple(str(x) for x in calls[0][1][0])}


def test_si_ninguna_pasa_con_las_dos_semillas_codigo_1(tmp_path, capsys, monkeypatch):
    calls = check_spy(monkeypatch, [])
    targets = targets_file(tmp_path / "objetivos.toml")
    out_dir = tmp_path / "salida"

    code = main(
        ["calibracion", "sensibilidad", *NURSE_SHORT, *EXAMPLE, "--objetivos", str(targets)]
        + [*SHORT, "--comprobacion", "8", "--salida", str(out_dir)]
    )
    out = capsys.readouterr().out
    rows = read_rows(out_dir / "sensibilidad_enfermeria_triaje.csv")
    passing = {
        (r["manana"], r["tarde"], r["noche"])
        for r in rows
        if r["objetivo"] == "pretriaje_medio" and r["resultado"] == "pasa"
    }

    assert code == 1
    assert len(passing) >= 2  # el caso ocurre: hay más de una candidata que vetar
    # Se piden todas las que pasan con la de ajuste, y solo esas.
    assert {tuple(str(x) for x in c[1][0]) for c in calls} == passing
    assert len(calls) == len(passing)
    assert "ninguna plantilla de la regla pasa pretriaje_medio con las semillas 7 y 8" in out
    assert chosen_in_csv(out_dir) == set()


def test_la_comprobacion_con_la_ventana_anual_usa_sus_fechas(tmp_path, capsys, monkeypatch):
    calls = check_spy(monkeypatch, [True])
    targets = targets_file(tmp_path / "objetivos.toml")

    code = main(
        ["calibracion", "sensibilidad", "--mando", "enfermeria_triaje", *EXAMPLE]
        + ["--objetivos", str(targets), *ANNUAL_SHORT, "--u-min", "0.85", "--u-max", "0.9"]
        + ["--comprobacion", "8", "--salida", str(tmp_path / "salida")]
    )
    capsys.readouterr()

    assert code == 0
    ((seed, _, replicas, days, dates),) = calls
    assert (seed, replicas, days) == (8, 12, 2)
    assert [d.isoformat() for d in dates] == MONDAYS_2026


# --- evaluar con el modelo del hito 5 (tarea 5.6) -----------------------------------------

H5 = [
    "--centro",
    str(DATA / "centro_h5_ejemplo.toml"),
    "--llegadas",
    str(DATA / "llegadas_ejemplo.toml"),
    "--perfiles",
    str(DATA / "perfiles_h5_ejemplo.toml"),
]


def h5_targets_file(path: Path) -> Path:
    """Los objetivos de targets_file más los del hito 5, con horquillas anchas."""
    targets_file(path)
    source = 'fuente = "a mano"\nenlace = "https://example.org"\n'
    with path.open("a", encoding="utf-8") as f:
        f.write(
            f"""
[objetivos.abandono]
medida = "left"
estadistico = "porcentaje_de_llegadas"
horquilla = [0, 100]
uso = "ajuste"
{source}
[objetivos.estancia_ingresados]
medida = "stay"
destino = "ingreso"
niveles = [1, 2, 3, 4, 5]
estadistico = "media"
horquilla = [0, 100000]
uso = "ajuste"
{source}
[objetivos.estancia_atendidos]
medida = "stay"
niveles = [1, 2, 3, 4, 5]
estadistico = "media"
horquilla = [0, 100000]
uso = "comprobacion"
{source}"""
        )
    return path


def test_evaluar_el_hito_5_con_cotas_recuentos_y_cuello_de_botella(tmp_path, capsys):
    out_dir = tmp_path / "salida"
    targets = h5_targets_file(tmp_path / "objetivos.toml")
    code = main(
        ["calibracion", "evaluar", *H5, "--objetivos", str(targets), *SHORT]
        + ["--salida", str(out_dir)]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert "No aplican" not in out
    assert "Se van sin ser vistos: " in out
    assert "Ingresados esperando cama al final del vaciado" in out
    assert "Cuello de botella (atendidos de los niveles 2 a 5, media entre réplicas)" in out
    rows = {r["objetivo"]: r for r in read_rows(out_dir / "evaluacion.csv")}
    assert rows["estancia_ingresados"]["destino"] == "ingreso"
    # Las réplicas del CSV llevan los recuentos y, por objetivo, cuántos entran con su cota.
    replicas = read_rows(out_dir / "evaluacion_replicas.csv")
    abandono = [r for r in replicas if r["objetivo"] == "abandono"]
    assert len(abandono) == 2 and all(int(r["se_van"]) > 0 for r in abandono)
    bounded = sum(int(r["acotados"]) for r in replicas if r["objetivo"] == "estancia_ingresados")
    assert (rows["estancia_ingresados"]["cota"] == "True") == (bounded > 0)
    # El porcentaje de llegadas no tiene desglose por nivel.
    assert {r["objetivo"] for r in read_rows(out_dir / "evaluacion_niveles.csv")} == {
        "porcentaje_sobre_manchester"
    }


def test_evaluar_el_hito_4_con_objetivos_del_hito_5_no_los_mide(tmp_path, capsys):
    targets = h5_targets_file(tmp_path / "objetivos.toml")
    code = main(
        ["calibracion", "evaluar", *EXAMPLE, "--objetivos", str(targets), *SHORT]
        + ["--salida", str(tmp_path / "salida")]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert (
        "No aplican (el modelo no tiene el bloque del hito 5: sin abandono ni sus destinos;"
        " no se miden, no son un 0 %): abandono, estancia_ingresados"
    ) in out
    # La estancia de todos sí existe en el hito 4; sin abandono ni camas, sin sus recuentos.
    assert "estancia_atendidos" in out
    assert "Se van sin ser vistos" not in out and "Cuello de botella" not in out
    rows = {r["objetivo"] for r in read_rows(tmp_path / "salida" / "evaluacion.csv")}
    assert "abandono" not in rows and "estancia_atendidos" in rows


def test_evaluar_con_el_bloque_del_hito_5_en_un_solo_fichero_es_un_error_de_uso(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.setattr(evaluate, "simulate_ed", lambda *a, **k: pytest.fail("simuló"))
    centro = str(DATA / "centro_h5_ejemplo.toml")
    with pytest.raises(SystemExit) as exit_info:
        main(
            ["calibracion", "evaluar", *EXAMPLE, "--centro", centro, *SHORT]
            + ["--objetivos", str(targets_file(tmp_path / "o.toml"))]
            + ["--salida", str(tmp_path / "salida")]
        )
    assert exit_info.value.code == 2
    assert "missing [abandono], [destinos] and ingreso in the reasons" in capsys.readouterr().err


# --- sensibilidad de los mandos del hito 5 (tarea 5.6) -------------------------------------


def test_sensibilidad_de_la_espera_de_cama_con_sus_valores(tmp_path, capsys):
    targets = h5_targets_file(tmp_path / "objetivos.toml")
    out_dir = tmp_path / "salida"
    code = main(
        ["calibracion", "sensibilidad", "--mando", "espera_cama", "--valores", "180,240"]
        + [*H5, "--objetivos", str(targets), *SHORT, "--salida", str(out_dir)]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert (
        "Sensibilidad del mando espera_cama (mediana de la espera de cama (min; p90 = 3 ·"
        " mediana)) en 180, 240"
    ) in out
    assert "mediana (min)" in out and "box / médico (2 a 5)" in out
    assert "Elección (entre los que pasan estancia_ingresados" in out
    rows = read_rows(out_dir / "sensibilidad_espera_cama.csv")
    assert {r["valor"] for r in rows} == {"180.0", "240.0"}
    assert {r["manana"] for r in rows} == {""}
    # Más espera de cama, más estancia de los ingresados, con los mismos pacientes.
    stay = {r["valor"]: float(r["media"]) for r in rows if r["objetivo"] == "estancia_ingresados"}
    assert stay["240.0"] > stay["180.0"]


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (
            ["--mando", "paciencia", *EXAMPLE],
            "the knob paciencia needs the milestone 5 model",
        ),
        (
            ["--mando", "espera_cama", "--u-min", "0.6", *H5],
            "--u-min: la rejilla de u es de los mandos de plantilla; con espera_cama, --valores",
        ),
        (["--mando", "medicos", "--valores", "2", *H5], "--valores es de espera_cama y paciencia"),
        (["--mando", "paciencia", "--valores", "0", *H5], "a value of paciencia must be in"),
        (["--mando", "paciencia", "--valores", "1,x", *H5], "no son números separados por comas"),
    ],
    ids=["hito_4", "u_con_un_valor", "valores_con_plantilla", "valor_cero", "no_numeros"],
)
def test_sensibilidad_de_los_mandos_del_hito_5_errores_de_uso(
    argv, message, tmp_path, capsys, monkeypatch
):
    monkeypatch.setattr(evaluate, "simulate_ed", lambda *a, **k: pytest.fail("simuló"))
    targets = h5_targets_file(tmp_path / "objetivos.toml")
    with pytest.raises(SystemExit) as exit_info:
        main(
            ["calibracion", "sensibilidad", *argv, "--objetivos", str(targets), *SHORT]
            + ["--salida", str(tmp_path / "salida")]
        )
    assert exit_info.value.code == 2
    assert message in capsys.readouterr().err
