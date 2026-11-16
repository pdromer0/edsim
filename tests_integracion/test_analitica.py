"""El proyecto dbt de `analitica/` contra un Postgres real (tarea 8.1, decisión 111, H8-12).

`dbt build --select preparacion` sobre la base de la sesión, la que prepara
`edsim almacen preparar`: construye la vista `preparacion.registros` y la tabla
`preparacion.registros_vigentes`, y pasa los seis unit tests de la limpieza en orden de linaje.
Pilla lo que no pilla ningún test de Python: un error de SQL o de Jinja en los modelos, una
regla de limpieza que no da lo calculado en el plan (los unit tests) y un esquema con otro
nombre que el de su capa.

dbt vive en otro entorno (`analitica/.venv`, con su propio `uv.lock`): se lanza con
`uv run --locked` desde `analitica/`, que lo sincroniza si hace falta, y sin el `VIRTUAL_ENV`
del núcleo. La conexión sale de la URL de la base de la sesión, en las variables de
`profiles.yml`: dbt nunca prueba contra la base `edsim`.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from edsim.store.postgres import connect

ANALITICA = Path(__file__).resolve().parents[1] / "analitica"

DBT_TIMEOUT = 150.0
"""Segundos para `uv run dbt build`, con la sincronización de `analitica/.venv` si falta: unos
2 min en frío en el portátil (la descarga de dbt), 5 s con el entorno ya hecho."""

UNIT_TESTS = {
    "l_escenario_completo",
    "d_duplicado_del_corregido",
    "c_dos_correcciones",
    "h_mismo_instante_distinto_payload",
    "k_relectura_de_kafka",
    "i_hoja_ingenua",
}


def dbt_env(url: str) -> dict[str, str]:
    """El entorno de dbt: el del proceso sin `VIRTUAL_ENV` y con la conexión de `url`."""
    parts = urlsplit(url)
    env = {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}
    env.update(
        EDSIM_PG_HOST=parts.hostname or "localhost",
        EDSIM_PG_PUERTO=str(parts.port or 5432),
        EDSIM_PG_USUARIO=unquote(parts.username or ""),
        EDSIM_PG_CLAVE=unquote(parts.password or ""),
        EDSIM_PG_BASE=parts.path.lstrip("/"),
    )
    return env


def test_dbt_construye_la_preparacion_y_pasa_los_seis_unit_tests(bronze_url, tmp_path):
    uv = shutil.which("uv")
    if uv is None:
        pytest.fail("No se encuentra uv en el PATH: dbt se lanza con «uv run».", pytrace=False)
    target = tmp_path / "target"
    result = subprocess.run(
        [uv, "run", "--locked", "dbt", "build", "--select", "preparacion"]
        + ["--target-path", str(target), "--log-path", str(tmp_path / "logs")],
        cwd=ANALITICA,
        env=dbt_env(bronze_url),
        capture_output=True,
        text=True,
        check=False,
        timeout=DBT_TIMEOUT,
    )

    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    # El código de salida no basta: con un selector o un nombre mal escritos, dbt no ejecuta
    # nada y sale con 0. Los seis unit tests y los dos modelos tienen que estar en el informe.
    results = json.loads((target / "run_results.json").read_text())["results"]
    status = {r["unique_id"]: r["status"] for r in results}
    unit = {uid.rsplit(".", 1)[1]: s for uid, s in status.items() if uid.startswith("unit_test.")}
    assert unit == dict.fromkeys(UNIT_TESTS, "pass")
    assert status["model.edsim_analitica.registros"] == "success"
    assert status["model.edsim_analitica.registros_vigentes"] == "success"
    # Cada modelo, en el esquema exacto de su capa y con su materialización.
    with connect(bronze_url) as connection:
        tables = connection.execute(
            "SELECT table_name, table_type FROM information_schema.tables "
            "WHERE table_schema = 'preparacion' ORDER BY table_name"
        )
    assert tables == [("registros", "VIEW"), ("registros_vigentes", "BASE TABLE")]
