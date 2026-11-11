"""Freeze the pre-refactor CLI artifacts with portable input paths."""

import hashlib
import math
from datetime import datetime, time, timedelta
from pathlib import Path

from edsim.arrivals.profile import load_profile
from edsim.cli import main
from edsim.engine.events import TIMEZONE, read_events


def test_simulate_cli_characterization(tmp_path, monkeypatch):
    # El modelo provisional: desde la tarea 4.9, con --provisional (el clínico es el de por
    # defecto). Mismas huellas que antes.
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    output = tmp_path / "salida"
    assert not output.exists()
    assert (
        main(
            [
                "motor",
                "simular",
                "--provisional",
                "--centro",
                "tests/data/centro_ejemplo.toml",
                "--llegadas",
                "tests/data/llegadas_ejemplo.toml",
                "--dias",
                "2",
                "--calentamiento",
                "1",
                "--semilla",
                "7",
                "--run-id",
                "caracterizacion-a2a",
                "--salida",
                str(output),
            ]
        )
        == 0
    )
    assert output.is_dir()
    expected = {
        "eventos.jsonl": "220eb8c619ba9b90b33dc666610b75dd3dae65d24035e0ba26fc87b9028c80a2",
        "ground_truth_episodios.csv": (
            "55a623b9532566fa7de183e580b4a60e798c80fcb9ddbc6b33ea3d50162697f9"
        ),
        "ground_truth_dias.csv": "af940fff1593570fc8c127a21cbe3fcf72e3686d0a7771bcc33521cc545a21c8",
    }
    for name, digest in expected.items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest

    raw = (output / "eventos.jsonl").read_text()
    assert str(tmp_path) not in raw
    assert str(Path.cwd()) not in raw
    assert "tests/data" not in raw
    events = list(read_events(output / "eventos.jsonl"))
    assert events
    start = datetime.combine(
        load_profile("tests/data/llegadas_ejemplo.toml").start_date, time(), tzinfo=TIMEZONE
    )
    for event in events:
        expected_time = start + timedelta(milliseconds=math.floor(event.sim_time * 60_000))
        assert event.event_time == expected_time.isoformat(timespec="milliseconds")
        assert event.recorded_time == event.event_time
        assert event.ingest_time is None


# --- Modelo clínico (tarea 4.5b) --------------------------------------------------------

# Huellas SHA-256 de motor simular --perfiles con el centro, las llegadas y los perfiles
# de ejemplo y los mismos argumentos que la caracterización del provisional, también el
# run_id. Generadas en la tarea 4.5b (306392fe… y 3f59dd25…); se regeneran solo con un
# cambio a propósito de los muestreadores, del catálogo o del CSV clínico, nunca para que
# un test pase. Fase A de la 4.6a: los perfiles de ejemplo, con la parada al 0,3 % y la
# cascada rederivada, cambian el log y el CSV de episodios (también su huella_perfiles).
# Fase B: solo el log (f7cb3225… → 2a8df1e8…), por el schema_version 3; el centro de
# ejemplo no tiene sala y los CSV no cambian.
CLINICAL_CHARACTERIZATION = {
    "eventos.jsonl": "2a8df1e89bf8b2ec240c9a167d721fc82343dc7b09161bd2a5c365e6a39ff7d4",
    "ground_truth_episodios.csv": (
        "0d18f0a06be4a7bcc78fe141b042ed2564e7bfc8dc4a61959ebd81a5444b6e40"
    ),
    # El de los días es el del provisional: las llegadas no dependen de los perfiles.
    "ground_truth_dias.csv": "af940fff1593570fc8c127a21cbe3fcf72e3686d0a7771bcc33521cc545a21c8",
}


def test_simulate_cli_characterization_clinico(tmp_path, monkeypatch):
    from edsim.engine.center import load_center
    from edsim.engine.engine import simulate_ed
    from edsim.engine.events import JsonlSink
    from edsim.profiles.config import load_profiles

    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    output = tmp_path / "salida"
    assert (
        main(
            [
                "motor",
                "simular",
                "--centro",
                "tests/data/centro_ejemplo.toml",
                "--llegadas",
                "tests/data/llegadas_ejemplo.toml",
                "--perfiles",
                "tests/data/perfiles_ejemplo.toml",
                "--dias",
                "2",
                "--calentamiento",
                "1",
                "--semilla",
                "7",
                "--run-id",
                "caracterizacion-a2a",
                "--salida",
                str(output),
            ]
        )
        == 0
    )
    for name, digest in CLINICAL_CHARACTERIZATION.items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest, name

    # El log es, byte a byte, el de simulate_ed con los mismos argumentos.
    path = tmp_path / "eventos.jsonl"
    with JsonlSink(path) as sink:
        simulate_ed(
            load_center("tests/data/centro_ejemplo.toml"),
            load_profile("tests/data/llegadas_ejemplo.toml"),
            2,
            7,
            sink=sink,
            warmup_days=1,
            run_id="caracterizacion-a2a",
            profiles=load_profiles("tests/data/perfiles_ejemplo.toml"),
        )
    assert (output / "eventos.jsonl").read_bytes() == path.read_bytes()
    # Guarda: es un log clínico (versión 3 desde la tarea 4.6a), no el del provisional.
    events = list(read_events(output / "eventos.jsonl"))
    assert {e.schema_version for e in events} == {3}
    assert all("medio" in e.payload for e in events if e.event_type == "patient_arrived")


# --- Con la sala de resultados (tarea 4.6a) ------------------------------------------

# motor simular --perfiles con tests/data/centro_sala_ejemplo.toml (el centro de ejemplo más
# espera_resultados_fuera = [4, 5]) y los mismos argumentos. Los CSV llevan otra huella del
# centro, pero sus datos son los de la caracterización sin sala: la sala solo cambia el flujo.
ROOM_CHARACTERIZATION = {
    "eventos.jsonl": "d033762dc0f684cd4c1a2131977bc9d24c54d5bfb4fc5c8f09343ba9c8a6e585",
    "ground_truth_episodios.csv": (
        "0b367ec0d854a38d7a14daef267ef6206604628a24fd797298402a1c29b9a8af"
    ),
    "ground_truth_dias.csv": "ab36965715cafbe27cf94f120bba1f3e08aee44df7d07f73c64d0428a4f6a19f",
}


def _simulate_clinical(output: Path, center: str) -> None:
    arguments = [
        "motor",
        "simular",
        "--centro",
        center,
        "--llegadas",
        "tests/data/llegadas_ejemplo.toml",
        "--perfiles",
        "tests/data/perfiles_ejemplo.toml",
        "--dias",
        "2",
        "--calentamiento",
        "1",
        "--semilla",
        "7",
        "--run-id",
        "caracterizacion-a2a",
        "--salida",
        str(output),
    ]
    assert main(arguments) == 0


def _rows_without_center(path: Path) -> list[dict[str, str]]:
    import csv

    with path.open(encoding="utf-8", newline="") as f:
        return [
            {k: v for k, v in row.items() if k not in ("centro", "huella_centro")}
            for row in csv.DictReader(f)
        ]


def test_simulate_cli_characterization_clinico_con_sala(tmp_path, monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    room, plain = tmp_path / "sala", tmp_path / "sin_sala"
    _simulate_clinical(room, "tests/data/centro_sala_ejemplo.toml")
    _simulate_clinical(plain, "tests/data/centro_ejemplo.toml")

    for name, digest in ROOM_CHARACTERIZATION.items():
        assert hashlib.sha256((room / name).read_bytes()).hexdigest() == digest, name
    events = list(read_events(room / "eventos.jsonl"))
    assert {e.schema_version for e in events} == {3}
    assert sum(e.event_type == "box_released" for e in events) == 223
    # Los mismos pacientes y sorteos: solo cambian el nombre y la huella del centro.
    for name in ("ground_truth_episodios.csv", "ground_truth_dias.csv"):
        assert _rows_without_center(room / name) == _rows_without_center(plain / name)


# --- El modelo del hito 5 (tarea 5.3) ---------------------------------------------------------

# motor simular con los ejemplos del hito 5 (tests/data/perfiles_h5_ejemplo.toml y
# centro_h5_ejemplo.toml) y los mismos argumentos que las demás caracterizaciones. Huellas de
# los tres ficheros y de la salida estándar, con la carpeta de salida en lugar de su ruta.
# Generadas en la tarea 5.3; la de la salida cambia con la 5.4, que trae el resumen completo
# del hito 5 en lugar de los recuentos.
H5_CHARACTERIZATION = {
    "eventos.jsonl": "db45aee1cf8bbec7d17da389e3cb409d8a1c70a6415c4511522acc97c3024686",
    "ground_truth_episodios.csv": (
        "bbeedfec9b2fa67c0ede4eedac4f3daa83ee5d02b3e561804564068072f7da5b"
    ),
    "ground_truth_dias.csv": "8e11a7d6e1d6a3fa99bfecb59e04dd153dad58155ec5655fa184684e3b9df4c1",
}
H5_STDOUT = "4e8398f7c33ecf61c5281a2f579c7d325dae9eef8d78e0204fb4153aa95faa36"


def test_simulate_cli_characterization_hito_5(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    output = tmp_path / "salida"
    arguments = [
        "motor",
        "simular",
        "--centro",
        "tests/data/centro_h5_ejemplo.toml",
        "--llegadas",
        "tests/data/llegadas_ejemplo.toml",
        "--perfiles",
        "tests/data/perfiles_h5_ejemplo.toml",
        "--dias",
        "2",
        "--calentamiento",
        "1",
        "--semilla",
        "7",
        "--run-id",
        "caracterizacion-a2a",
        "--salida",
        str(output),
    ]
    assert main(arguments) == 0
    stdout = capsys.readouterr().out.replace(str(output), "SALIDA")

    for name, digest in H5_CHARACTERIZATION.items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest, name
    assert hashlib.sha256(stdout.encode("utf-8")).hexdigest() == H5_STDOUT
    # Guarda: es el modelo del hito 5, con su línea de modelo y sus recuentos, no el resumen.
    assert "Modelo del hito 5 (abandono, destinos y espera de cama)" in stdout
    assert "Se van sin ser vistos: 16 (5.2 %): triaje 0, box 13, médico 3" in stdout
    assert "Las métricas con abandono y espera de cama llegan con la tarea 5.4." in stdout
    assert "Esperas y estancia por nivel" not in stdout
    events = list(read_events(output / "eventos.jsonl"))
    assert {e.schema_version for e in events} == {4}
