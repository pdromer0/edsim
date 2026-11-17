"""El proyecto dbt de `analitica/` contra un Postgres real (tareas 8.1, 8.3 y 8.5; H8-12).

`dbt build --exclude tag:laboratorio` sobre la base de la sesión, la que prepara
`edsim almacen preparar`: construye la hoja del hospital entera (la preparación, plata, oro y
sus semillas), pasa los unit tests de la limpieza (8.1), de plata (8.3) y de oro (8.5) en orden
de linaje, y los tests de datos. Pilla lo que no pilla ningún test de Python: un error de SQL o
de Jinja en los modelos, una regla que no da lo calculado en el plan (los unit tests) y un
esquema con otro nombre que el de su capa. Sobre esta base los tests de datos apenas comprueban
nada: los ejercita con datos `test_punta_a_punta.py`.

dbt se lanza con `run_dbt` de `dbt_testing.py`, en su propio entorno (`analitica/.venv`).
"""

import pytest
from dbt_testing import ORO, run_dbt

from edsim.store.postgres import connect

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
    "censo_a_la_hora_en_punto",
    "cohorte_de_llegada",
    "cohorte_sigue_dentro",
    "ocupacion_de_boxes",
}

PREPARACION = ("parametros", "registros", "registros_vigentes")

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

SEMILLAS = ("maestro_boxes", "turnos")
"""Las semillas, en el esquema oro."""


# Por encima del límite de la carpeta (180 s): el sync en frío y la fixture de sesión, si este
# test es el primero, caben aquí.
@pytest.mark.timeout(300)
def test_dbt_construye_la_hoja_del_hospital_y_pasa_sus_tests(bronze_url, tmp_path):
    result = run_dbt(bronze_url, ["build", "--exclude", "tag:laboratorio"], tmp_path)

    assert result.returncode == 0, result.output
    # El código de salida no basta: con un selector o un nombre mal escritos, dbt no ejecuta
    # nada y sale con 0. Los unit tests y los modelos tienen que estar en el informe, y los tests
    # de datos, en verde.
    assert result.of("unit_test") == dict.fromkeys(UNIT_TESTS, "pass")
    assert result.of("model") == dict.fromkeys((*PREPARACION, *PLATA, *ORO), "success")
    assert result.of("seed") == dict.fromkeys(SEMILLAS, "success")
    data = result.of("test")
    assert data, "ningún test de datos en el informe"
    assert set(data.values()) == {"pass"}
    # Cada modelo, en el esquema exacto de su capa y con su materialización.
    with connect(bronze_url) as connection:
        tables = connection.execute(
            "SELECT table_schema, table_name, table_type FROM information_schema.tables "
            "WHERE table_schema IN ('preparacion', 'plata', 'oro') "
            "ORDER BY table_schema, table_name"
        )
    assert tables == [
        *(("oro", name, "BASE TABLE") for name in sorted((*ORO, *SEMILLAS))),
        *(("plata", name, "BASE TABLE") for name in PLATA),
        ("preparacion", "parametros", "BASE TABLE"),
        ("preparacion", "registros", "VIEW"),
        ("preparacion", "registros_vigentes", "BASE TABLE"),
    ]
