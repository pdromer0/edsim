"""El bucle de micro-lotes de `edsim analitica refrescar` (tarea 8.7, decisión 109).

Con un reloj y una construcción falsos: la construcción adelanta el reloj lo que «dura» cada
vuelta, y el reloj apunta cada espera. Los valores esperados salen del plan de la 8.7, con un
script independiente del bucle (la salida, en el PR). Los dos dobles llevan tope (`RunawayLoop`):
un bucle que no para falla en 20 llamadas, no a los 60 s del límite por test.
"""

import os
import signal
import threading
import time
from pathlib import Path

import pytest
from runaway import check_calls

from edsim.analytics import (
    DBT_BUILD,
    BuildResult,
    RefreshSummary,
    dbt_builder,
    dbt_command,
    dbt_environment,
    refresh,
)

LIMIT = 20
EVERY = 60.0


class FakeClock:
    """Un reloj que solo avanza cuando la construcción trabaja o el bucle espera."""

    def __init__(self, interrupt_on_sleep: int | None = None) -> None:
        self.time = 0.0
        self.sleeps: list[float] = []
        self.interrupt_on_sleep = interrupt_on_sleep

    def monotonic(self) -> float:
        return self.time

    def sleep(self, seconds: float) -> None:
        check_calls(len(self.sleeps) + 1, LIMIT, "FakeClock.sleep")
        if self.interrupt_on_sleep == len(self.sleeps) + 1:
            raise KeyboardInterrupt
        self.sleeps.append(seconds)
        self.time += seconds


class FakeBuild:
    """Una construcción por vuelta: dura lo que dice el guion y devuelve su resultado. Al
    acabarse el guion, la siguiente vuelta recibe Ctrl+C."""

    def __init__(self, clock: FakeClock, script: list[tuple[float, BuildResult]]) -> None:
        self.clock = clock
        self.script = list(script)
        self.starts: list[float] = []

    def __call__(self) -> BuildResult:
        check_calls(len(self.starts) + 1, LIMIT, "FakeBuild")
        self.starts.append(self.clock.time)
        if not self.script:
            raise KeyboardInterrupt
        seconds, result = self.script.pop(0)
        self.clock.time += seconds
        return result


OK = BuildResult(0, "Done. PASS=40 WARN=0 ERROR=0 SKIP=0 TOTAL=40\n")


def run(durations: list[float], clock: FakeClock | None = None):
    clock = clock or FakeClock()
    build = FakeBuild(clock, [(d, OK) for d in durations])
    lines: list[str] = []
    summary = refresh(build, clock, EVERY, lines.append)
    return build, clock, lines, summary


def test_las_vueltas_cortas_esperan_hasta_el_intervalo():
    """Vueltas de 10 s: cada una espera 50 s, porque el intervalo cuenta desde su inicio.
    Pilla esperar 60 s después de cada vuelta (V18)."""
    build, clock, lines, _ = run([10, 10, 10])

    assert build.starts == [0, 60, 120, 180]
    assert clock.sleeps == [50, 50, 50]
    assert lines[:3] == ["Vuelta 1: 10.0 s", "Vuelta 2: 10.0 s", "Vuelta 3: 10.0 s"]
    assert not any(line.startswith("Aviso") for line in lines)


def test_una_vuelta_larga_avisa_y_la_siguiente_empieza_al_acabar():
    """Una vuelta de 75 s avisa y la siguiente empieza en 135 s, sin esperar; las demás esperan
    50 s. Pilla una espera negativa o el aviso que falta (V19)."""
    build, clock, lines, _ = run([10, 75, 10])

    assert build.starts == [0, 60, 135, 195]
    assert clock.sleeps == [50, 50]
    avisos = [line for line in lines if line.startswith("Aviso")]
    assert avisos == [
        "Aviso: la vuelta 2 tardó 75.0 s, más que el intervalo de 60 s; la siguiente empieza ya"
    ]


def test_una_vuelta_de_justo_el_intervalo_ni_avisa_ni_espera():
    """La frontera: 60 s no pasa del intervalo. La siguiente empieza en 60 s, sin aviso y sin
    una espera de 0 s."""
    build, clock, lines, _ = run([60, 10])

    assert build.starts == [0, 60, 120]
    assert clock.sleeps == [50]
    assert not any(line.startswith("Aviso") for line in lines)


def test_ctrl_c_dentro_de_una_vuelta_sale_con_un_resumen():
    """Ctrl+C en la tercera vuelta: la cortada no cuenta; el resumen dice las dos acabadas y
    la más larga."""
    _, _, lines, summary = run([10, 30])

    assert summary == RefreshSummary(rounds=2, failures=0, longest=30.0)
    assert lines[-1] == "Parado con Ctrl+C: 2 vueltas, ninguna con error; la más larga, 30.0 s"


def test_ctrl_c_durante_la_espera_sale_con_un_resumen():
    """Ctrl+C en la segunda espera: dos vueltas acabadas, y no se lanza una tercera."""
    clock = FakeClock(interrupt_on_sleep=2)
    build, _, lines, summary = run([10, 20, 30], clock)

    assert build.starts == [0, 60]
    assert summary == RefreshSummary(rounds=2, failures=0, longest=20.0)
    assert lines[-1].startswith("Parado con Ctrl+C: 2 vueltas")


def test_el_resumen_de_una_sola_vuelta_va_en_singular():
    _, _, lines, _ = run([12])

    assert lines[-1] == "Parado con Ctrl+C: 1 vuelta, ninguna con error; la más larga, 12.0 s"


def test_ctrl_c_antes_de_acabar_la_primera_vuelta():
    """Sin ninguna vuelta acabada, el resumen no tiene una «más larga»."""
    _, _, lines, summary = run([])

    assert summary == RefreshSummary(rounds=0, failures=0, longest=None)
    assert lines == ["Parado con Ctrl+C antes de acabar la primera vuelta"]


def test_una_vuelta_que_falla_avisa_y_la_siguiente_se_lanza():
    """D3: la vuelta 2 falla con código 2. Se ve el código y las 20 últimas líneas de dbt (la
    11 a la 30), la vuelta 3 se lanza a su hora y el resumen cuenta el fallo. Pilla un fallo
    que para el bucle (V20)."""
    clock = FakeClock()
    output = "".join(f"línea {n}\n" for n in range(1, 31))
    build = FakeBuild(clock, [(10, OK), (5, BuildResult(2, output)), (10, OK)])
    lines: list[str] = []

    summary = refresh(build, clock, EVERY, lines.append)

    assert build.starts == [0, 60, 120, 180]
    fallo = lines[1].splitlines()
    assert fallo[0] == (
        "Vuelta 2: falló con código 2 en 5.0 s; se intenta en la siguiente. Lo último de dbt:"
    )
    assert fallo[1:] == [f"  línea {n}" for n in range(11, 31)]
    assert summary == RefreshSummary(rounds=3, failures=1, longest=10.0)
    assert lines[-1] == "Parado con Ctrl+C: 3 vueltas, 1 con error; la más larga, 10.0 s"


@pytest.mark.parametrize("every", [0, -1, float("nan"), float("inf")])
def test_un_intervalo_que_no_es_positivo_es_un_error(every):
    with pytest.raises(ValueError, match="every"):
        refresh(FakeBuild(FakeClock(), []), FakeClock(), every, print)


def test_la_orden_construye_el_hospital_sin_tests():
    """D2: `dbt build` (carga también las semillas), la hoja del hospital, sin la tabla de tres
    columnas ni tests de datos ni unit tests, en el entorno de `analitica/`."""
    folder = Path("/repo/analitica")

    assert dbt_command("/bin/uv", folder) == [
        "/bin/uv",
        "run",
        "--locked",
        "--project",
        "/repo/analitica",
        "dbt",
        "build",
        "--vars",
        "{hoja: hospital}",
        "--exclude",
        "tag:laboratorio",
        "--exclude-resource-type",
        "test",
        "unit_test",
    ]
    assert DBT_BUILD[0] == "build"


def test_el_entorno_de_dbt_no_lleva_el_virtual_env_del_nucleo():
    """Sin `VIRTUAL_ENV` (uv avisaría y lo ignoraría); las `EDSIM_PG_*` pasan: eligen la base."""
    environ = {"VIRTUAL_ENV": "/repo/.venv", "EDSIM_PG_BASE": "edsim_h87", "PATH": "/bin"}

    assert dbt_environment(environ) == {"EDSIM_PG_BASE": "edsim_h87", "PATH": "/bin"}


def test_la_construccion_lanza_la_orden_en_la_carpeta_de_dbt(tmp_path, monkeypatch):
    """El subproceso de verdad, con un `uv` falso que imprime sus argumentos, su carpeta y su
    `VIRTUAL_ENV`, y sale con 3: el código y la salida llegan al bucle. Pilla lanzar dbt desde
    otra carpeta (no encontraría `dbt_project.yml`) o con el entorno del núcleo."""
    folder = tmp_path / "analitica"
    folder.mkdir()
    uv = tmp_path / "uv"
    uv.write_text('#!/bin/sh\necho "$@"\npwd\necho "venv=${VIRTUAL_ENV:-ninguno}"\nexit 3\n')
    uv.chmod(0o755)
    monkeypatch.setenv("VIRTUAL_ENV", "/repo/.venv")

    result = dbt_builder(str(uv), folder)()

    assert result.returncode == 3
    assert result.output.splitlines() == [
        " ".join(dbt_command(str(uv), folder)[1:]),
        os.path.realpath(folder),
        "venv=ninguno",
    ]


def test_ctrl_c_en_una_vuelta_espera_a_que_dbt_acabe(tmp_path):
    """Un SIGINT que solo le llega a Python, a los 0,2 s de una vuelta de 1 s: la construcción
    espera a que el `uv` falso acabe y escriba su marca, y después lanza KeyboardInterrupt.
    Pilla matar a uv a los 0,25 s, como `subprocess.run`, y dejar a dbt a medias."""
    marca = tmp_path / "acabado"
    uv = tmp_path / "uv"
    uv.write_text(f'#!/bin/sh\nsleep 1\necho hecho > "{marca}"\n')
    uv.chmod(0o755)
    build = dbt_builder(str(uv), tmp_path)
    threading.Timer(0.2, os.kill, (os.getpid(), signal.SIGINT)).start()
    inicio = time.monotonic()

    with pytest.raises(KeyboardInterrupt):
        build()

    assert marca.read_text() == "hecho\n"
    assert time.monotonic() - inicio >= 1
