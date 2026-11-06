"""Freeze the pre-refactor CLI artifacts with portable input paths."""

import hashlib
import math
from datetime import datetime, time, timedelta
from pathlib import Path

from edsim.arrivals.profile import load_profile
from edsim.cli import main
from edsim.engine.events import TIMEZONE, read_events


def test_simulate_cli_characterization(tmp_path, monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    output = tmp_path / "salida"
    assert not output.exists()
    assert (
        main(
            [
                "motor",
                "simular",
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
# run_id. Generadas en la tarea 4.5b; se regeneran solo con un cambio a propósito de los
# muestreadores, del catálogo 2 o del CSV clínico, nunca para que un test pase.
CLINICAL_CHARACTERIZATION = {
    "eventos.jsonl": "306392fe5e0cf8b9e65a5a87858f374f0e370054ddee18ccaa72c20f7bc4afc8",
    "ground_truth_episodios.csv": (
        "3f59dd25ee90e4214f6c8640fe50220d28490ed57b249de353cedcf76e1784c0"
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
    # Guarda: es un log clínico de la versión 2, no el del provisional.
    events = list(read_events(output / "eventos.jsonl"))
    assert {e.schema_version for e in events} == {2}
    assert all("medio" in e.payload for e in events if e.event_type == "patient_arrived")
