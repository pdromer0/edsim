"""Grafana y sus tres cuadros (tarea 8.6, decisiones 108 y 109; H8-12).

Cada test dice qué pilla que no pille otro:

- los cuadros: los `uid`, el refresco, el selector de tiempo oculto, la fuente de cada panel y
  que ninguna consulta use el rango de tiempo del cuadro (`$__timeFilter`), sin arrancar nada;
- las consultas de todos los paneles y de las variables, con las variables sustituidas, sobre la
  base de la prueba de punta a punta (la fixture `analitica` de `conftest.py`) y conectado como
  el rol de la fuente del cuadro (D3): una columna o una tabla mal escrita, un panel del hospital
  que lee del laboratorio y un reloj que no da las 24 horas simuladas;
- la variable `ejecucion`: una verdad publicada en bronce no aparece en Urgencias ni en Calidad
  (D2), y `preparacion.parametros.registrado` en las hojas del hospital y de la verdad;
- Grafana arranca con el perfil `analitica` y su API lista las dos fuentes, que conectan, y los
  tres cuadros: un aprovisionamiento roto o mal montado;
- sin el perfil, compose no tiene Grafana: que se pierda el perfil.

Grafana inserta una variable de un solo valor tal cual, sin comillas: las consultas la llevan
entre comillas (`'${ejecucion}'`), y el test la sustituye igual.
"""

import base64
import json
import os
import subprocess
import time
import urllib.error
import urllib.request

import psycopg
import pytest
from dbt_testing import ROOT, RUN_ID, derived
from kafka_testing import TIMEOUT
from test_verdad import with_user

from edsim.store.postgres import connect

DASHBOARDS = ROOT / "grafana" / "dashboards"

BOARDS = {
    "urgencias": ("edsim-urgencias", "Urgencias", "edsim-hospital"),
    "calidad": ("edsim-calidad", "Calidad del dato", "edsim-hospital"),
    "laboratorio": ("edsim-laboratorio", "Laboratorio", "edsim-laboratorio"),
}
"""Cada cuadro, por su fichero: su `uid`, su título y el `uid` de su fuente."""

SOURCES = {
    "edsim-hospital": ("Hospital", "hospital"),
    "edsim-laboratorio": ("Laboratorio", "laboratorio"),
}
"""Cada fuente, por su `uid`: su nombre y el rol con el que se conecta."""

POSTGRES_PLUGIN = ("grafana-postgresql-datasource", "13.0.7")
"""El plugin de PostgreSQL que trae `grafana/grafana:13.3.1`, comprobado en la 8.6: sin
actualizarlo al arrancar, la versión solo cambia con la imagen (D1)."""

RECORDED = derived("realista")
"""La ejecución que se elige en los cuadros."""

HOURS = [f"07/01 {hour:02d}h" for hour in range(24)]
"""Las últimas 24 horas simuladas de la ejecución de 3 días con W = 1 día, calculadas en el plan:
las horas k de la ventana van de 24 a 71 (1440 <= 60 k < 4320), las 24 últimas de 48 a 71 y la
etiqueta es la fecha de origen (5 de enero) más k // 24 días, a las k % 24 horas."""

GRAFANA = os.environ.get("EDSIM_GRAFANA", "http://127.0.0.1:3000")
ADMIN = "Basic " + base64.b64encode(b"admin:admin").decode()
"""El administrador de fábrica de Grafana, como `edsim`/`edsim` en Postgres: es local."""


def board(name: str) -> dict:
    return json.loads((DASHBOARDS / f"{name}.json").read_text(encoding="utf-8"))


def panels(dashboard: dict) -> list[dict]:
    """Los paneles del cuadro, también los de dentro de una fila plegada."""
    found = []
    for panel in dashboard["panels"]:
        found.append(panel)
        found.extend(panel.get("panels", []))
    return [panel for panel in found if panel["type"] != "row"]


def variable(dashboard: dict) -> dict:
    [ejecucion] = dashboard["templating"]["list"]
    assert ejecucion["name"] == "ejecucion"
    return ejecucion


def substitute(query: str, ejecucion: str) -> str:
    """La consulta con la variable sustituida, como la deja Grafana; no debe quedar otra."""
    sql = query.replace("${ejecucion}", ejecucion).replace("$ejecucion", ejecucion)
    assert "$" not in sql, f"queda una variable o una macro de Grafana sin sustituir:\n{sql}"
    return sql


def run_as(url: str, role: str, sql: str) -> tuple[list[str], list[tuple]]:
    """Las columnas y las filas de `sql`, conectado como `role`."""
    with psycopg.connect(with_user(url, role), autocommit=True) as session:
        cursor = session.execute(sql)
        return [column.name for column in cursor.description], cursor.fetchall()


@pytest.mark.parametrize("name", BOARDS)
def test_cada_cuadro_vive_en_el_reloj_de_la_ejecucion(name):
    """Pilla un `uid` cambiado (los enlaces y el test de arranque lo usan), un cuadro sin el
    refresco de 30 s o con el selector de tiempo a la vista, un panel con otra fuente que la de
    su cuadro y una consulta que use el rango de tiempo del cuadro en vez del de la ejecución."""
    uid, title, source = BOARDS[name]
    dashboard = board(name)

    assert (dashboard["uid"], dashboard["title"]) == (uid, title)
    assert dashboard["refresh"] == "30s"
    assert dashboard["timepicker"]["hidden"] is True
    assert variable(dashboard)["datasource"]["uid"] == source
    found = panels(dashboard)
    assert found
    for panel in found:
        assert panel["datasource"]["uid"] == source, panel["title"]
        assert panel["targets"], panel["title"]
        for target in panel["targets"]:
            assert target["datasource"]["uid"] == source, panel["title"]
            assert "$__" not in target["rawSql"], panel["title"]
            assert "'${ejecucion}'" in target["rawSql"], panel["title"]


@pytest.mark.parametrize("name", BOARDS)
def test_las_consultas_de_los_paneles_se_ejecutan_con_el_rol_de_su_fuente(analitica, name):
    """Cada consulta, con la variable sustituida y el rol de la fuente del cuadro (D3). Todas
    devuelven filas (un filtro mal escrito daría cero) y las de barras, las 24 horas simuladas
    de la ejecución, de la primera a la última: con `>=` serían 25, y con el reloj de la pared,
    ninguna. En Laboratorio, la columna de la verdad tiene valores: un enlace roto con la verdad
    la deja vacía entera. Una hora suelta sin valor es legítima: en la cohorte de las 23 h del
    último día nadie llegó a triarse antes del horizonte, en ninguna de las tres hojas."""
    _, _, source = BOARDS[name]
    _, role = SOURCES[source]
    dashboard = board(name)

    _, options = run_as(analitica.url, role, substitute(variable(dashboard)["query"], RECORDED))
    assert (RECORDED,) in options

    for panel in panels(dashboard):
        for target in panel["targets"]:
            sql = substitute(target["rawSql"], RECORDED)
            try:
                columns, rows = run_as(analitica.url, role, sql)
            except psycopg.Error as error:
                pytest.fail(f"{name}, «{panel['title']}» como {role}: {error}")
            assert rows, f"{name}, «{panel['title']}»: sin filas"
            if panel["type"] == "barchart":
                assert columns[0] == "Hora", panel["title"]
                assert [row[0] for row in rows] == HOURS, panel["title"]
                if "Verdad" in columns:
                    truth = columns.index("Verdad")
                    assert any(row[truth] is not None for row in rows), panel["title"]


def options(url: str, name: str) -> set[str]:
    """Lo que ofrece la variable `ejecucion` del cuadro, con el rol de su fuente."""
    _, _, source = BOARDS[name]
    _, rows = run_as(url, SOURCES[source][1], variable(board(name))["query"])
    return {run_id for (run_id,) in rows}


def test_una_verdad_publicada_no_sale_en_urgencias_ni_en_calidad(analitica):
    """D2: la hoja del hospital construye oro también con la verdad publicada como con
    `--verdad` (el `run_id` `e2e`), pero las variables de Urgencias y de Calidad solo ofrecen lo
    registrado. Sin la verdad en oro, el test no probaría nada."""
    registered = {derived("limpio"), derived("realista")}
    with connect(analitica.url) as connection:
        in_gold = {
            table: {
                run_id
                for (run_id,) in connection.execute(f"SELECT DISTINCT run_id FROM oro.{table}")
            }
            for table in ("kpi_hora", "calidad")
        }

    assert in_gold == {"kpi_hora": registered | {RUN_ID}, "calidad": registered | {RUN_ID}}
    assert options(analitica.url, "urgencias") == registered
    assert options(analitica.url, "calidad") == registered


def test_parametros_dice_que_ejecuciones_son_lo_registrado(analitica):
    """`registrado` sale del bloque `registro` del `inicio`: verdadero en lo registrado con los
    dos perfiles, falso en la verdad publicada y en la hoja de la verdad, que es la verdad."""
    with connect(analitica.url) as connection:
        hospital = dict(connection.execute("SELECT run_id, registrado FROM preparacion.parametros"))
        truth = dict(
            connection.execute("SELECT run_id, registrado FROM verdad_preparacion.parametros")
        )

    assert hospital == {RUN_ID: False, derived("limpio"): True, derived("realista"): True}
    assert truth == {RUN_ID: False}


def get(path: str, admin: bool = False):
    """La respuesta JSON de la API de Grafana; anónima, salvo con `admin`."""
    request = urllib.request.Request(GRAFANA + path)
    if admin:
        request.add_header("Authorization", ADMIN)
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read())


@pytest.fixture(scope="module")
def grafana() -> str:
    """La URL de Grafana (`EDSIM_GRAFANA` o la de `compose.yaml`), comprobada: si no responde,
    los tests fallan (no se saltan) con un mensaje que dice cómo levantarlo."""
    try:
        get("/api/health")
    except (urllib.error.URLError, OSError) as exc:
        pytest.fail(
            f"No responde Grafana en {GRAFANA} ({exc}). Levántalo con «docker compose --profile "
            "analitica up --wait» o ejecuta scripts/tests-integracion.sh; para otro, "
            "EDSIM_GRAFANA=URL.",
            pytrace=False,
        )
    return GRAFANA


def test_grafana_arranca_con_sus_dos_fuentes_y_sus_tres_cuadros(grafana, bronze_url):
    """Pilla un aprovisionamiento roto o mal montado: un cuadro que no se carga o con otro
    `uid`, una fuente con otro rol o que no conecta (otro host u otra contraseña), un plugin de
    PostgreSQL que no es el de la imagen, un cuadro que no viene del aprovisionamiento y un
    visitante anónimo que no puede abrir los cuadros o que puede guardarlos (otro rol que Viewer;
    `allowUiUpdates` no se ve así: un administrador recibe `canSave` igual). La
    salud de las fuentes conecta a la base `edsim` con los roles de la 002, que son del servidor
    y ya los creó la base de la sesión (`bronze_url`)."""
    expected = {uid: title for uid, title, _ in BOARDS.values()}
    deadline = time.monotonic() + TIMEOUT
    while True:
        found = get("/api/search?type=dash-db")
        listed = {item["uid"]: item["title"] for item in found}
        if listed == expected or time.monotonic() > deadline:
            break
        time.sleep(1)

    assert listed == expected
    assert {item["folderTitle"] for item in found} == {"EDsim"}
    for uid in expected:
        meta = get(f"/api/dashboards/uid/{uid}")["meta"]
        assert (meta["provisioned"], meta["canSave"]) == (True, False), uid
    sources = {
        source["uid"]: (source["name"], source["user"], source["jsonData"]["database"])
        for source in get("/api/datasources", admin=True)
    }
    assert sources == {uid: (name, role, "edsim") for uid, (name, role) in SOURCES.items()}
    for uid in SOURCES:
        try:
            health = get(f"/api/datasources/uid/{uid}/health", admin=True)["status"]
        except urllib.error.HTTPError as error:  # una fuente que no conecta da 400
            health = error.read().decode()
        assert health == "OK", uid
    plugin, version = POSTGRES_PLUGIN
    assert get(f"/api/plugins/{plugin}/settings", admin=True)["info"]["version"] == version


def test_sin_el_perfil_compose_no_tiene_grafana():
    """Grafana va con el perfil `analitica`: el `docker compose up` de la integración y del
    notebook 06 no lo arranca. Sin `COMPOSE_PROFILES`, que `scripts/tests-integracion.sh`
    exporta."""
    env = {key: value for key, value in os.environ.items() if key != "COMPOSE_PROFILES"}

    def services(*args: str) -> set[str]:
        result = subprocess.run(
            ["docker", "compose", *args, "config", "--services"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
            timeout=TIMEOUT,
        )
        return set(result.stdout.split())

    assert services() == {"kafka", "console", "postgres"}
    assert services("--profile", "analitica") == {"kafka", "console", "postgres", "grafana"}
