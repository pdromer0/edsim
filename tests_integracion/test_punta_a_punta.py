"""La prueba de punta a punta del hito 8 (tarea 8.5, decisión 111, H8-12).

Una ejecución de 3 días, lo registrado con los perfiles `limpio` y `realista` en bronce, la
verdad cargada y las cuatro construcciones (la fixture `analitica` de `conftest.py`, una vez por
sesión). Cada test dice qué pilla que no pille otro:

- las construcciones: que los tests de datos de plata y de oro pasan con datos de verdad, no
  solo sobre una base vacía;
- oro del perfil `limpio` = oro de la verdad, salvo `run_id`: una regla de la limpieza que
  estropea datos limpios;
- `kpi_ejecucion` de la hoja `verdad` = los indicadores de `compare.py` sobre la verdad: una
  definición que se separa entre el SQL y el Python;
- `kpi_ejecucion` de la hoja `ingenuo` con el perfil `realista` = los de `compare.py` sobre lo
  registrado: lo mismo por el camino sin limpieza, con duplicados de verdad (V11);
- los duplicados quitados = las filas `duplicado` de la libreta: una limpieza que quita de más o
  de menos con datos realistas;
- `tres_columnas`: el enlace de las tres hojas por `registro.origen`;
- los permisos: que `hospital` lee su hoja y no la verdad ni el laboratorio.

La referencia de Python usa las funciones de `edsim.clinical_record.compare` con la ventana de
D1 de la 8.5: las llegadas, las medianas y el reparto por nivel, con los registros de
`event_time` >= origen + W; el censo, con todos. `compare.py` no cambia (sus funciones son
privadas: el test las usa porque la definición que se comprueba es justo la suya).
"""

from collections import Counter

import psycopg
import pytest
from dbt_testing import ORO, RUN_ID, SEED, derived
from test_verdad import with_user

from edsim.clinical_record.compare import _hours, _ms, _naive_indicators, _origin
from edsim.clinical_record.notebook import CORRECTION, DUPLICATE
from edsim.runs import read_recorded_records, read_recorded_run
from edsim.store.postgres import connect

# La fixture de sesión hace la ejecución, la carga y las cuatro construcciones en el primer test
# que la pide: 39 s medidos en el portátil. El límite de la carpeta (180 s) sería justo en un
# runner del CI más lento; cada orden de dbt tiene además su propio límite (DBT_TIMEOUT).
pytestmark = pytest.mark.timeout(400)

KPIS = (
    "llegadas",
    "censo_medio",
    "mediana_triaje_min",
    "mediana_medico_min",
    *(f"pct_nivel_{n}" for n in range(1, 6)),
)


def reference(items, truth, horizon: float, warmup: float) -> dict[str, float | None]:
    """Los cinco indicadores de `compare.py` en la ventana, por el nombre de su columna en oro."""
    origin = _origin(truth)
    hours = _hours(horizon, warmup)
    start = origin + round(warmup * 60_000)
    window = [item for item in items if _ms(item, "event_time") >= start]
    everything = _naive_indicators(items, origin, hours)
    inside = _naive_indicators(window, origin, hours)
    return {
        "llegadas": inside.arrivals,
        "censo_medio": everything.mean_in_department,
        "mediana_triaje_min": inside.time_to_triage,
        "mediana_medico_min": inside.time_to_doctor,
        **{f"pct_nivel_{n}": inside.level_shares[n] for n in range(1, 6)},
    }


def kpi_ejecucion(url: str, schema: str, run_id: str) -> dict[str, float | None]:
    with connect(url) as connection:
        rows = connection.execute(
            f"SELECT {', '.join(KPIS)} FROM {schema}.kpi_ejecucion WHERE run_id = %s", (run_id,)
        )
    assert len(rows) == 1, f"{schema}.kpi_ejecucion tiene {len(rows)} filas de {run_id}"
    return dict(zip(KPIS, rows[0], strict=True))


def assert_same_kpis(sql: dict, python: dict) -> None:
    """Los recuentos, exactos; lo demás, con 1e-9 de tolerancia, solo por la representación
    (D3 de la 8.5): una mediana que se separe medio milisegundo son 8e-6 min."""
    assert sql["llegadas"] == python["llegadas"]
    for kpi in KPIS[1:]:
        assert python[kpi] is not None, f"{kpi}: la referencia está vacía, el test no compara"
        assert sql[kpi] == pytest.approx(python[kpi], rel=0, abs=1e-9), kpi


def test_las_cuatro_construcciones_pasan_sus_tests_de_datos(analitica):
    """El código de salida no basta: con un selector mal escrito, dbt no ejecuta nada y sale con
    0. Cada hoja construye sus modelos y sus semillas y pasa sus tests de datos, con datos."""
    for name in ("hospital", "verdad", "ingenuo"):
        build = analitica.builds[name]
        assert len(build.of("model")) == 17, name
        assert set(build.of("model").values()) == {"success"}, name
        assert build.of("seed") == {"maestro_boxes": "success", "turnos": "success"}, name
        assert len(build.of("test")) > 40, name
        assert set(build.of("test").values()) == {"pass"}, name
        assert build.of("unit_test") == {}, name
    laboratorio = analitica.builds["laboratorio"]
    assert laboratorio.of("model") == {"tres_columnas": "success"}
    assert set(laboratorio.of("test").values()) == {"pass"}


def columns(connection, schema: str, table: str) -> list[str]:
    return [
        name
        for (name,) in connection.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
            (schema, table),
        )
    ]


def test_oro_del_perfil_limpio_es_el_de_la_verdad(analitica):
    """Con el perfil `limpio`, lo registrado es la verdad con otro `run_id`: la limpieza no tiene
    nada que hacer, y las seis tablas de oro del hospital salen fila a fila como las de la
    verdad. Pilla una regla que estropea datos limpios."""
    with connect(analitica.url) as connection:
        for table in ORO:
            names = columns(connection, "oro", table)
            assert names == columns(connection, "verdad_oro", table), table
            kept = ", ".join(name for name in names if name != "run_id")
            order = ", ".join(str(i) for i in range(1, len(names)))
            query = "SELECT {kept} FROM {schema}.{table} WHERE run_id = %s ORDER BY {order}"
            clean = connection.execute(
                query.format(kept=kept, schema="oro", table=table, order=order),
                (derived("limpio"),),
            )
            truth = connection.execute(
                query.format(kept=kept, schema="verdad_oro", table=table, order=order), (RUN_ID,)
            )
            assert clean, f"oro.{table} no tiene filas del perfil limpio"
            assert clean == truth, table


def test_kpi_ejecucion_de_la_verdad_es_el_de_compare(analitica):
    """Pilla que una definición de los cinco se separe entre el SQL y el Python (H8-12)."""
    run = read_recorded_run(analitica.store, RUN_ID, "limpio", SEED)

    python = reference(run.truth, run.truth, run.horizon, run.warmup)

    assert python["llegadas"] > 500  # no es un test vacío: hay una ejecución de verdad
    assert_same_kpis(kpi_ejecucion(analitica.url, "verdad_oro", RUN_ID), python)


def test_kpi_ejecucion_ingenua_es_la_de_compare_con_el_perfil_realista(analitica):
    """Lo mismo por el camino sin limpieza: la hoja `ingenuo` cuenta como `compare.py`, con los
    duplicados y sin correcciones. Lo registrado tiene llegadas duplicadas en la ventana (la
    semilla 2026 del registro se eligió en el plan para que las tuviera): contar episodios en vez
    de registros (V11) daría tres llegadas menos."""
    run = read_recorded_run(analitica.store, RUN_ID, "realista", SEED)
    records = read_recorded_records(run)
    start = _origin(run.truth) + round(run.warmup * 60_000)
    arrivals = Counter(
        r.episode_id
        for r in records
        if r.event_type == "patient_arrived" and _ms(r, "event_time") >= start
    )
    assert sum(arrivals.values()) > len(arrivals), "sin llegadas duplicadas, V11 no se vería"

    python = reference(records, run.truth, run.horizon, run.warmup)

    assert_same_kpis(kpi_ejecucion(analitica.url, "ingenuo_oro", derived("realista")), python)


def test_los_duplicados_quitados_son_los_de_la_libreta(analitica):
    """La limpieza quita exactamente los dobles clics que apuntó el registro clínico: ni uno de
    más (un hecho real borrado) ni uno de menos. También aplica todas las correcciones: cada fila
    `correccion` de la libreta corrige un registro distinto."""
    run = read_recorded_run(analitica.store, RUN_ID, "realista", SEED)
    kinds = Counter(row.kind for row in run.notebook)
    assert kinds[DUPLICATE] > 0 and kinds[CORRECTION] > 0

    with connect(analitica.url) as connection:
        [(removed, corrected)] = connection.execute(
            "SELECT duplicados_quitados, registros_corregidos FROM oro.calidad WHERE run_id = %s",
            (derived("realista"),),
        )

    assert removed == kinds[DUPLICATE]
    assert corrected == kinds[CORRECTION]


def test_tres_columnas_une_las_tres_hojas(analitica):
    """Nueve KPI por perfil, enlazados con la verdad por `registro.origen`: la columna `verdad`
    es la misma para los dos perfiles, y con el perfil `limpio` las dos diferencias son 0."""
    with connect(analitica.url) as connection:
        rows = connection.execute(
            "SELECT perfil, semilla, run_id_registrado, kpi, verdad, ingenuo, limpio,"
            " ingenuo_menos_verdad, limpio_menos_verdad FROM laboratorio.tres_columnas"
            " WHERE run_id = %s ORDER BY perfil, orden",
            (RUN_ID,),
        )
    truth = kpi_ejecucion(analitica.url, "verdad_oro", RUN_ID)

    assert [(r[0], r[1], r[2], r[3]) for r in rows] == [
        (profile, SEED, derived(profile), kpi) for profile in ("limpio", "realista") for kpi in KPIS
    ]
    for profile, _, _, kpi, verdad, ingenuo, limpio, ingenuo_diff, limpio_diff in rows:
        assert verdad == pytest.approx(truth[kpi], rel=0, abs=1e-12), kpi
        assert ingenuo_diff == pytest.approx(ingenuo - verdad, rel=0, abs=1e-12)
        assert limpio_diff == pytest.approx(limpio - verdad, rel=0, abs=1e-12)
        if profile == "limpio":
            assert (ingenuo_diff, limpio_diff) == (0, 0), kpi
    clean = kpi_ejecucion(analitica.url, "oro", derived("realista"))
    assert [r[6] for r in rows if r[0] == "realista"] == [clean[kpi] for kpi in KPIS]


def read(url: str, role: str, table: str) -> int | str:
    """Las filas de `table` que ve `role`, o «denegado»."""
    with psycopg.connect(with_user(url, role), autocommit=True) as session:
        try:
            return session.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        except psycopg.errors.InsufficientPrivilege:
            return "denegado"


def test_hospital_lee_su_hoja_y_no_la_verdad(analitica):
    """Pilla un esquema sin USAGE (los grants de dbt solo dan SELECT en las tablas), una tabla
    reconstruida sin su permiso y una hoja de la verdad o del laboratorio legible por `hospital`.
    Cada tabla tiene filas: un SELECT que funcione no cuenta cero.

    El SELECT de cada tabla se mira también aparte del USAGE de su esquema: sin él, un `grants`
    que diera SELECT de más a `hospital` en la verdad pasaría inadvertido, porque el USAGE que
    falta ya le deniega la lectura."""
    hospital_sheet = ("preparacion.registros", "plata.episodio", "oro.kpi_hora", "oro.turnos")
    hidden = (
        "verdad_preparacion.registros",
        "verdad_oro.kpi_ejecucion",
        "verdad_oro.turnos",
        "ingenuo_oro.kpi_ejecucion",
        "laboratorio.tres_columnas",
    )

    seen = {
        (role, t): read(analitica.url, role, t)
        for role in ("hospital", "laboratorio")
        for t in (*hospital_sheet, *hidden)
    }
    with connect(analitica.url) as connection:
        granted = {
            (role, t): connection.execute(
                "SELECT has_table_privilege(%s, %s, 'SELECT')", (role, t)
            )[0][0]
            for role in ("hospital", "laboratorio")
            for t in (*hospital_sheet, *hidden)
        }

    for table in hospital_sheet:
        assert isinstance(seen["hospital", table], int) and seen["hospital", table] > 0, table
        assert granted["hospital", table], table
    for table in hidden:
        assert seen["hospital", table] == "denegado", table
        assert not granted["hospital", table], table
    for table in (*hospital_sheet, *hidden):
        count = seen["laboratorio", table]
        assert isinstance(count, int) and count > 0, table
        assert granted["laboratorio", table], table
