"""El proyecto dbt de `analitica/` contra un Postgres real (tareas 8.1 y 8.3, decisión 111, H8-12).

`dbt build --select preparacion plata` sobre la base de la sesión, la que prepara
`edsim almacen preparar`: construye la vista `preparacion.registros`, la tabla
`preparacion.registros_vigentes` y las ocho tablas de plata, pasa los unit tests de la limpieza
(8.1) y de plata (8.3) en orden de linaje, y los tests de datos de plata. Pilla lo que no pilla
ningún test de Python: un error de SQL o de Jinja en los modelos, una regla de limpieza o un
emparejamiento que no dan lo calculado en el plan (los unit tests) y un esquema con otro nombre
que el de su capa. Sobre una base vacía, los tests de datos pasan sin comprobar nada: la 8.3 los
midió con datos reales (anexo de hito-8.md).

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

DBT_TIMEOUT = 240.0
"""Segundos para `uv run dbt build`, con la sincronización de `analitica/.venv` si falta: 121 s
medidos en frío en el portátil (la descarga de dbt) y 5 s con el entorno ya hecho.
`scripts/tests-integracion.sh` sincroniza antes; el margen es para lanzar el test solo."""

UNIT_TESTS = {
    "l_escenario_completo",
    "d_duplicado_del_corregido",
    "c_dos_correcciones",
    "h_mismo_instante_distinto_payload",
    "k_relectura_de_kafka",
    "i_hoja_ingenua",
    "e_empates",
    "r_recursos_tal_cual",
    "valoracion_inicio_olvidado_al_final",
    "valoracion_inicio_olvidado_al_principio",
    "ubicacion_estancias_en_box",
    "plantilla_tramos",
    "prueba_lista_y_resultado_juntos",
}

PLATA = (
    "destino",
    "episodio",
    "paciente",
    "plantilla",
    "prueba",
    "triaje",
    "ubicacion",
    "valoracion",
)
"""Las ocho tablas de plata (decisión 104, H8-5), en orden alfabético."""


def dbt_env(url: str) -> dict[str, str]:
    """El entorno de dbt: el del proceso, sin `VIRTUAL_ENV` ni las variables `DBT_*` (un
    `DBT_PROFILES_DIR` o un `DBT_TARGET` heredados llevarían dbt a otro perfil o a otra base), y
    con la conexión de `url`."""
    parts = urlsplit(url)
    env = {
        key: value
        for key, value in os.environ.items()
        if key != "VIRTUAL_ENV" and not key.startswith("DBT_")
    }
    env.update(
        EDSIM_PG_HOST=parts.hostname or "localhost",
        EDSIM_PG_PUERTO=str(parts.port or 5432),
        EDSIM_PG_USUARIO=unquote(parts.username or ""),
        EDSIM_PG_CLAVE=unquote(parts.password or ""),
        EDSIM_PG_BASE=parts.path.lstrip("/"),
    )
    return env


# Por encima del límite de la carpeta (180 s): el sync en frío y la fixture de sesión, si este
# test es el primero, caben aquí.
@pytest.mark.timeout(300)
def test_dbt_construye_la_preparacion_y_plata_y_pasa_sus_tests(bronze_url, tmp_path):
    uv = shutil.which("uv")
    if uv is None:
        pytest.fail("No se encuentra uv en el PATH: dbt se lanza con «uv run».", pytrace=False)
    target = tmp_path / "target"
    result = subprocess.run(
        [uv, "run", "--locked", "dbt", "build", "--select", "preparacion", "plata"]
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
    # nada y sale con 0. Los trece unit tests y los diez modelos tienen que estar en el informe,
    # y los tests de datos de plata, en verde.
    results = json.loads((target / "run_results.json").read_text())["results"]
    status = {r["unique_id"]: r["status"] for r in results}
    unit = {uid.rsplit(".", 1)[1]: s for uid, s in status.items() if uid.startswith("unit_test.")}
    assert unit == dict.fromkeys(UNIT_TESTS, "pass")
    models = {uid.rsplit(".", 1)[1]: s for uid, s in status.items() if uid.startswith("model.")}
    assert models == dict.fromkeys(("registros", "registros_vigentes", *PLATA), "success")
    data = [s for uid, s in status.items() if uid.startswith("test.")]
    assert data, "ningún test de datos en el informe"
    assert set(data) == {"pass"}
    # Cada modelo, en el esquema exacto de su capa y con su materialización.
    with connect(bronze_url) as connection:
        tables = connection.execute(
            "SELECT table_schema, table_name, table_type FROM information_schema.tables "
            "WHERE table_schema IN ('preparacion', 'plata') ORDER BY table_schema, table_name"
        )
    assert tables == [
        *(("plata", name, "BASE TABLE") for name in PLATA),
        ("preparacion", "registros", "VIEW"),
        ("preparacion", "registros_vigentes", "BASE TABLE"),
    ]
