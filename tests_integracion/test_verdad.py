"""La verdad en Postgres y sus roles, contra un Postgres real (tarea 8.4, H8-6).

Cada test dice qué error pilla que no pille un rápido (`tests/test_store_truth.py` ya prueba las
filas sin conectar):

- cargar dos veces: que la segunda carga borra antes de escribir (la clave primaria de `eventos`
  la haría fallar; la libreta, sin clave, se duplicaría) y que los recuentos son los de los
  ficheros, contados aquí con `csv` y `open`, no con el código que se prueba;
- cargar otra ejecución: que el `DELETE` va con su `run_id` y no vacía la tabla;
- una carga que falla: que las cuatro tablas van en una sola transacción;
- los permisos: las cuatro combinaciones de rol y esquema, con filas de verdad y de bronce para que
  ninguna pase de forma vacía, y que lo nuevo que cree `edsim` nazca legible para `laboratorio`;
- dos bases en el mismo servidor: que crear los roles dos veces no falla;
- los tipos de `verdad.eventos`: los de `bronce.eventos`, el contrato con el proyecto dbt.

Cada test usa su propia base de datos (`edsim_test_<8 hex>`), preparada con la CLI y borrada al
acabar: los roles son de todo el servidor, pero lo que se carga y se cuenta es de la base.
"""

import csv
import shutil
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from kafka_testing import TIMEOUT
from psycopg import sql
from test_almacen import message
from test_cli_directo import EDSIM

from edsim.runs import RunStore, record_run, simulate_run
from edsim.store.bronze import to_row
from edsim.store.consumer import save_batch
from edsim.store.postgres import PostgresBronze, connect

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "tests" / "data"
PROFILES = ROOT / "config" / "registro_clinico.toml"


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    """Dos ejecuciones del hito 5 de 2 días: `v1` con dos registros (`realista` y `limpio`) y
    `v2` sin ninguno. La carpeta de las ejecuciones, de solo lectura."""
    root = tmp_path_factory.mktemp("verdad")
    for run_id, seed in (("v1", 7), ("v2", 8)):
        simulate_run(
            DATA / "centro_h5_ejemplo.toml",
            DATA / "llegadas_ejemplo.toml",
            2,
            seed,
            output_dir=root / run_id,
            run_id=run_id,
            warmup_days=1,
            origin="cli",
            profiles=DATA / "perfiles_h5_ejemplo.toml",
        )
    store = RunStore(root)
    record_run(store, "v1", "realista", profiles_file=PROFILES)
    record_run(store, "v1", "limpio", 3, profiles_file=PROFILES)
    return root


def database_url(url: str, name: str) -> str:
    """`url` con otra base de datos: la ruta de la URL es su nombre."""
    return urlunsplit(urlsplit(url)._replace(path=f"/{name}"))


def cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [EDSIM, *args], capture_output=True, text=True, check=False, timeout=TIMEOUT
    )


@pytest.fixture
def database(postgres_admin):
    """Una base de datos nueva para el test, preparada con la CLI; se borra al acabar."""
    name = f"edsim_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(postgres_admin, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = database_url(postgres_admin, name)
    try:
        prepared = cli("almacen", "preparar", "--postgres", url)
        assert prepared.returncode == 0, prepared.stdout + prepared.stderr
        yield url
    finally:
        with psycopg.connect(postgres_admin, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )


def load(url: str, root: Path, run_id: str) -> subprocess.CompletedProcess:
    return cli("almacen", "cargar-verdad", run_id, "--ejecuciones", str(root), "--postgres", url)


def rows_of(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.reader(source))[1:]


def expected_counts(root: Path, run_id: str) -> dict[str, int]:
    """Lo que debe haber de una ejecución en cada tabla, contado en sus ficheros con `csv` y
    `open`: las líneas no vacías de los eventos y las filas de cada CSV."""
    folder = root / run_id
    events = [line for line in (folder / "eventos.jsonl").read_text("utf-8").split("\n") if line]
    ledger = sum(
        len(rows_of(recording / "defectos.csv"))
        for recording in sorted((folder / "registros").glob("*-s*"))
    )
    return {
        "eventos": len(events),
        "episodios": len(rows_of(folder / "ground_truth_episodios.csv")),
        "dias": len(rows_of(folder / "ground_truth_dias.csv")),
        "libreta": ledger,
    }


def counts_in(url: str, run_id: str) -> dict[str, int]:
    """Lo que hay de una ejecución en cada tabla de `verdad`."""
    with connect(url) as connection:
        return {
            table: connection.execute(
                f"SELECT count(*) FROM verdad.{table} WHERE {column} = %s", (run_id,)
            )[0][0]
            for table, column in (
                ("eventos", "run_id"),
                ("episodios", "run_id"),
                ("dias", "run_id"),
                ("libreta", "run_id_origen"),
            )
        }


def digest(url: str, run_id: str) -> list:
    """Una huella del contenido de la ejecución en las cuatro tablas."""
    queries = (
        "SELECT md5(string_agg(event_id || payload::text, ',' ORDER BY event_id))"
        " FROM verdad.eventos WHERE run_id = %s",
        "SELECT md5(string_agg(episodio || destino, ',' ORDER BY episodio))"
        " FROM verdad.episodios WHERE run_id = %s",
        "SELECT md5(string_agg(dia::text || fecha::text, ',' ORDER BY dia))"
        " FROM verdad.dias WHERE run_id = %s",
        "SELECT md5(string_agg(coalesce(registro, '') || hecho || clase, ',' "
        "ORDER BY run_id, hecho, registro, clase)) FROM verdad.libreta WHERE run_id_origen = %s",
    )
    with connect(url) as connection:
        return [connection.execute(query, (run_id,))[0][0] for query in queries]


def test_cargar_verdad_dos_veces_deja_lo_mismo(database, runs):
    """Pilla una carga que no borre antes de escribir (V7): con la clave de `eventos`, la segunda
    sale con error; con la libreta, sin clave, quedaría doble. Los recuentos son los de los
    ficheros y el contenido, el mismo después de las dos cargas."""
    expected = expected_counts(runs, "v1")

    first = load(database, runs, "v1")
    after_first = (counts_in(database, "v1"), digest(database, "v1"))
    second = load(database, runs, "v1")

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert expected["eventos"] > 100 and expected["libreta"] > expected["eventos"] // 2
    assert after_first[0] == expected
    assert (counts_in(database, "v1"), digest(database, "v1")) == after_first
    assert f"{expected['eventos']} eventos · {expected['episodios']} episodios" in second.stdout
    assert "Libreta de: limpio-s3, realista-s7" in second.stdout


def test_cargar_otra_ejecucion_no_borra_la_primera(database, runs):
    """Pilla un `DELETE` sin el `run_id` de la ejecución (M4), que vaciaría la tabla de las demás,
    también la libreta, que se borra por `run_id_origen`."""
    assert load(database, runs, "v1").returncode == 0
    v1 = digest(database, "v1")

    assert load(database, runs, "v2").returncode == 0
    assert counts_in(database, "v1") == expected_counts(runs, "v1")
    assert counts_in(database, "v2") == expected_counts(runs, "v2")
    assert counts_in(database, "v2")["libreta"] == 0
    assert digest(database, "v1") == v1

    assert load(database, runs, "v1").returncode == 0
    assert counts_in(database, "v2") == expected_counts(runs, "v2")


def test_una_carga_que_falla_no_deja_nada_a_medias(database, runs, tmp_path):
    """Pilla tablas cargadas cada una en su transacción: una libreta rota, la última en cargarse,
    deja los eventos, los episodios y los días de la carga anterior, no los de la rota."""
    assert load(database, runs, "v1").returncode == 0
    before = (counts_in(database, "v1"), digest(database, "v1"))
    broken = tmp_path / "rota"
    shutil.copytree(runs / "v1", broken / "v1")
    events = broken / "v1" / "eventos.jsonl"
    events.write_text("".join(events.read_text("utf-8").splitlines(keepends=True)[10:]), "utf-8")
    notebook = broken / "v1" / "registros" / "realista-s7" / "defectos.csv"
    notebook.write_text(notebook.read_text("utf-8") + "solo,tres,celdas\n", encoding="utf-8")

    failed = load(database, broken, "v1")

    assert failed.returncode == 1
    assert "defectos.csv" in failed.stderr and "3 celdas" in failed.stderr
    assert (counts_in(database, "v1"), digest(database, "v1")) == before


def with_user(url: str, role: str) -> str:
    """`url` con el rol `role` y su contraseña de desarrollo, que es su nombre."""
    parts = urlsplit(url)
    return urlunsplit(parts._replace(netloc=f"{role}:{role}@{parts.hostname}:{parts.port}"))


def test_permisos_de_hospital_y_laboratorio(database, runs):
    """Pilla un `hospital` que lea `verdad` (V8) o `bronce`, un `laboratorio` que no lea alguno de
    los dos o que escriba, y una tabla nueva de `edsim` que nazca sin permiso (M5). Hay filas en
    `bronce.eventos` y en `verdad.eventos`: un `SELECT` que funcione no cuenta cero."""
    assert load(database, runs, "v1").returncode == 0
    msg = message(f"perm-{uuid.uuid4().hex[:8]}", 1)
    with connect(database) as connection:
        assert save_batch(PostgresBronze(connection), [(msg, to_row(msg))]).saved == 1
        connection.execute("CREATE TABLE verdad.nueva (x integer)")
        connection.execute("INSERT INTO verdad.nueva VALUES (1)")

    reads = {}
    for role in ("hospital", "laboratorio"):
        for table in ("bronce.eventos", "verdad.eventos", "verdad.nueva"):
            with psycopg.connect(with_user(database, role), autocommit=True) as session:
                try:
                    reads[role, table] = session.execute(
                        f"SELECT count(*) FROM {table}"
                    ).fetchone()[0]
                except psycopg.errors.InsufficientPrivilege:
                    reads[role, table] = "denegado"

    assert reads == {
        ("hospital", "bronce.eventos"): "denegado",
        ("hospital", "verdad.eventos"): "denegado",
        ("hospital", "verdad.nueva"): "denegado",
        ("laboratorio", "bronce.eventos"): 1,
        ("laboratorio", "verdad.eventos"): expected_counts(runs, "v1")["eventos"],
        ("laboratorio", "verdad.nueva"): 1,
    }
    with psycopg.connect(with_user(database, "laboratorio"), autocommit=True) as session:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            session.execute("DELETE FROM verdad.eventos")
    with connect(database) as connection:
        assert connection.execute(
            "SELECT has_schema_privilege('hospital', 'bronce', 'USAGE'),"
            " has_schema_privilege('hospital', 'verdad', 'USAGE')"
        ) == [(False, False)]


def test_dos_bases_comparten_los_roles(database, bronze_url):
    """Pilla un `CREATE ROLE` sin proteger (M6): `database` y la base de la sesión están en el mismo
    servidor, que ya tenía los roles cuando la segunda se preparó; la migración no falla y los
    roles existen una sola vez, con sus contraseñas de desarrollo."""
    with connect(database) as connection:
        roles = connection.execute(
            "SELECT rolname, rolcanlogin, rolsuper FROM pg_roles"
            " WHERE rolname IN ('hospital', 'laboratorio') ORDER BY rolname"
        )

    assert roles == [("hospital", True, False), ("laboratorio", True, False)]
    for url in (database, bronze_url):
        for role in ("hospital", "laboratorio"):
            psycopg.connect(with_user(url, role)).close()


def test_verdad_eventos_tiene_los_tipos_de_bronce(database):
    """El contrato con la 8.1: las once columnas de `verdad.eventos` son las de `bronce.eventos`
    con sus tipos. Pilla un tipo cambiado (un `text` donde bronce tiene `timestamptz`) que dbt no
    notaría hasta tener datos."""
    query = (
        "SELECT column_name, data_type, is_nullable FROM information_schema.columns"
        " WHERE table_schema = %s AND table_name = 'eventos' AND column_name = ANY(%s)"
        " ORDER BY column_name"
    )
    names = [
        "event_id",
        "event_type",
        "schema_version",
        "run_id",
        "episode_id",
        "patient_id",
        "source_system",
        "sim_time",
        "event_time",
        "recorded_time",
        "payload",
    ]
    with connect(database) as connection:
        bronze = connection.execute(query, ("bronce", names))
        truth = connection.execute(query, ("verdad", names))
        every_column = connection.execute(
            "SELECT count(*) FROM information_schema.columns"
            " WHERE table_schema = 'verdad' AND table_name = 'eventos'"
        )

    assert every_column == [(11,)]  # y ninguna más: ni las de Kafka ni `valor`
    assert len(truth) == 11
    assert truth == bronze
