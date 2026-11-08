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
        assert "edsim.runs" in visited, sorted(visited)
        assert "edsim.runs.service" in visited, sorted(visited)
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
    assert "runs/service.py" in visited, sorted(visited)
    assert not violations, "UI imports in the core:\n" + "\n".join(violations)


TASK_4_8A_API = (
    "load_profiles",
    "ClinicalProfiles",
    "ObservedProfile",
    "observed_profiles",
    "ClockStatistics",
    "LevelClockSummary",
    "LevelClocks",
    "window_clocks",
    "level_one_clocks",
    "Pretriage",
    "PretriageGroup",
    "WindowPretriage",
    "window_pretriage",
    "APP_COMPLIANCE_MEASURE",
    "DiagnosticTestTruth",
    "ClinicalTruthView",
    "episode_clinical_truth",
    "true_level_window_compliance",
    "ProfilesSummary",
    "summarize_profiles",
    "PairingCategory",
    "pairing_category",
    "ClinicalField",
    "ClinicalDifference",
    "CLINICAL_DRAW_EFFECTS",
)
"""Lo que la tarea 4.8b (las páginas de la app) usa del núcleo clínico de runs/."""


def test_la_api_de_la_tarea_4_8a_es_publica():
    import edsim.runs as runs

    missing = [name for name in TASK_4_8A_API if name not in runs.__all__]
    assert not missing, missing
    assert all(hasattr(runs, name) for name in runs.__all__)
    assert len(set(runs.__all__)) == len(runs.__all__)


KAFKA_CLIENT = "confluent_kafka"
KAFKA_MODULE = "live/kafka.py"
"""El único módulo del núcleo que puede importar el cliente de Kafka (H6-2)."""


def test_importar_todo_edsim_no_carga_confluent_kafka():
    """Importar todos los módulos, incluido edsim.live.kafka, no carga el cliente de Kafka."""
    script = dedent("""\
        import importlib
        import pkgutil
        import sys

        import edsim

        visited = {"edsim"}
        for module in pkgutil.walk_packages(edsim.__path__, prefix="edsim."):
            importlib.import_module(module.name)
            visited.add(module.name)

        assert "edsim.live" in visited, sorted(visited)
        assert "edsim.live.kafka" in visited, sorted(visited)
        loaded = sorted(name for name in sys.modules if name.split(".")[0] == "confluent_kafka")
        assert not loaded, f"El núcleo carga el cliente de Kafka al importarse: {loaded}"
    """)
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def _is_kafka_client(name: object) -> bool:
    return isinstance(name, str) and name.split(".")[0] == KAFKA_CLIENT


def _kafka_client_imports(tree: ast.AST):
    """Los nodos que importan el cliente: import, from … import e import_module("…")."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(_is_kafka_client(alias.name) for alias in node.names):
                yield node
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and _is_kafka_client(node.module):
                yield node
        elif isinstance(node, ast.Call) and node.args:
            function = node.func
            dynamic = (
                isinstance(function, ast.Attribute)
                and function.attr == "import_module"
                and isinstance(function.value, ast.Name)
                and function.value.id == "importlib"
            ) or (isinstance(function, ast.Name) and function.id in {"import_module", "__import__"})
            argument = node.args[0]
            if dynamic and isinstance(argument, ast.Constant) and _is_kafka_client(argument.value):
                yield node


def test_confluent_kafka_solo_se_importa_en_live_kafka_y_dentro_de_funciones():
    """Solo live/kafka.py importa el cliente, y siempre dentro de una función (import perezoso).

    Se buscan imports en el árbol sintáctico, no el texto: un docstring o un mensaje que nombre
    el paquete en otro módulo no cuenta.
    """
    found = []
    outside_module = []
    at_module_level = []
    for path in sorted(CORE.rglob("*.py")):
        relative = path.relative_to(CORE).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in _kafka_client_imports(tree):
            where = f"{relative}:{node.lineno}"
            found.append(where)
            if relative != KAFKA_MODULE:
                outside_module.append(where)
            ancestor = parents.get(node)
            while ancestor is not None and not isinstance(
                ancestor, ast.FunctionDef | ast.AsyncFunctionDef
            ):
                ancestor = parents.get(ancestor)
            if ancestor is None:
                at_module_level.append(where)

    assert found, "No se encontró ningún import del cliente: el test no comprobaría nada"
    assert not outside_module, f"Imports del cliente fuera de {KAFKA_MODULE}: {outside_module}"
    assert not at_module_level, f"Imports del cliente fuera de una función: {at_module_level}"


def test_el_detector_ve_las_formas_de_importar_el_cliente_y_no_los_textos():
    """El detector del test anterior reconoce cada forma de import y no confunde un texto."""
    source = dedent('''\
        """Este módulo no importa confluent_kafka: solo lo nombra."""
        import importlib
        from importlib import import_module

        import confluent_kafka
        import confluent_kafka.admin as admin
        from confluent_kafka import Producer
        from confluent_kafka.admin import AdminClient

        MESSAGE = "instala confluent_kafka"
        import confluent_kafkaesque
        from . import confluent_kafka as relative


        def lazy():
            importlib.import_module("confluent_kafka")
            import_module("confluent_kafka.admin")
            __import__("confluent_kafka")
            importlib.import_module("json")
    ''')

    lines = sorted(node.lineno for node in _kafka_client_imports(ast.parse(source)))

    # Las líneas 5 a 8 (imports estáticos) y 16 a 18 (dinámicos). No cuentan el docstring, el
    # mensaje, otro paquete con prefijo parecido, un import relativo ni import_module("json").
    assert lines == [5, 6, 7, 8, 16, 17, 18]


def test_census_no_carga_simpy_ni_el_motor():
    """El censo son funciones puras sobre eventos (tarea 6.2): sin SimPy, motor ni Kafka."""
    script = (
        "import sys, edsim.live.census\n"
        "assert 'edsim.engine.events' in sys.modules\n"
        "bad = sorted(n for n in sys.modules if n.split('.')[0] in ('simpy', 'confluent_kafka')"
        " or n == 'edsim.engine.engine')\n"
        "assert not bad, bad\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False, timeout=60
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_reloj_ordenes_y_pacer_no_cargan_simpy_ni_el_motor():
    """El pacer no sabe nada del motor (H6-5): reloj, órdenes y pacer, sin SimPy ni motor."""
    script = (
        "import sys, edsim.live.clock, edsim.live.control, edsim.live.pacer\n"
        "assert 'edsim.live.pacer' in sys.modules\n"
        "bad = sorted(n for n in sys.modules if n.split('.')[0] in ('simpy', 'confluent_kafka')"
        " or n == 'edsim.engine' or n.startswith('edsim.engine.'))\n"
        "assert not bad, bad\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False, timeout=60
    )

    assert result.returncode == 0, result.stdout + result.stderr
