"""Keep the simulation core independent of the web interface."""

import ast
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

FORBIDDEN_PACKAGES = {"streamlit", "pandas", "edsim_app"}
CORE = Path(__file__).resolve().parents[1] / "src" / "edsim"


def test_core_imports_without_ui_dependencies():
    script = dedent("""\
        import importlib
        import pkgutil
        import sys

        import edsim

        visited = {"edsim"}
        for module in pkgutil.walk_packages(edsim.__path__, prefix="edsim."):
            importlib.import_module(module.name)
            visited.add(module.name)

        assert "edsim.engine" in visited, sorted(visited)
        assert "edsim.engine.engine" in visited, sorted(visited)
        forbidden = FORBIDDEN_PLACEHOLDER
        loaded = sorted(name for name in sys.modules if name.split(".")[0] in forbidden)
        assert not loaded, f"UI dependencies loaded by the core: {loaded}"
    """)
    script = script.replace("FORBIDDEN_PLACEHOLDER", repr(sorted(FORBIDDEN_PACKAGES)))
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_core_has_no_ui_imports_including_inside_functions():
    visited = set()
    violations = []
    for path in sorted(CORE.rglob("*.py")):
        relative = path.relative_to(CORE)
        visited.add(relative.as_posix())
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                if name.split(".")[0] in FORBIDDEN_PACKAGES:
                    violations.append(f"{relative}:{node.lineno}: {name}")

    assert "engine/__init__.py" in visited, sorted(visited)
    assert "engine/engine.py" in visited, sorted(visited)
    assert not violations, "UI imports in the core:\n" + "\n".join(violations)
