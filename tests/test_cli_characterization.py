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
