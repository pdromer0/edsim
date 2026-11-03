"""Launch the local app using Streamlit's public CLI."""

import subprocess
import sys
from pathlib import Path


def main() -> int:
    """Run Streamlit and return its exit code without a traceback on interruption."""
    script = Path(__file__).resolve().with_name("main.py")
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(script),
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
    except KeyboardInterrupt:
        return 130
    return result.returncode
