"""Verify the launcher without starting a server."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from edsim_app import launcher


@pytest.mark.parametrize("returncode", [0, 7])
def test_launcher_arguments_and_exit_code(monkeypatch, tmp_path, returncode):
    runner = Mock(return_value=subprocess.CompletedProcess([], returncode))
    monkeypatch.setattr(launcher.subprocess, "run", runner)
    monkeypatch.chdir(tmp_path)

    assert launcher.main() == returncode

    runner.assert_called_once_with(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(Path(launcher.__file__).resolve().with_name("main.py")),
            "--server.address",
            "localhost",
            "--server.port",
            "8501",
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
        ],
        check=False,
    )


def test_launcher_interrupt_has_no_traceback(monkeypatch, capsys):
    runner = Mock(side_effect=KeyboardInterrupt)
    monkeypatch.setattr(launcher.subprocess, "run", runner)

    assert launcher.main() == 130
    runner.assert_called_once()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
