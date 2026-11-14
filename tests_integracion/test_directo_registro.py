"""Reemitir con `--registro` y consumir, contra un Kafka y un Postgres reales (tarea 7.4, H7-10).

El camino real del hito: `edsim directo reemitir --registro` publica lo registrado con el
`run_id` derivado, y el consumidor de bronce (`run_consumer` con `run_id`, lo que hace
`edsim almacen consumir --run`) lo guarda hasta tener esa ejecución. Cada test dice qué pilla
que no pille un rápido:

- **Limpio, de punta a punta:** lo que hay en bronce es la verdad salvo los identificadores,
  emparejados con la libreta. Pilla lo que solo se ve con el broker y Postgres de verdad: que
  `--run` encuentra el `inicio` del derivado (y no espera hasta el `timeout`) y que los
  registros cruzan Kafka y el `INSERT` sin cambiar un campo.
- **Realista:** la cuenta cuadra con lo leído de bronce (`read_bronze_records` y la
  comparación), y da lo mismo que con ficheros: con olvidos, desorden, duplicados y
  correcciones, bronce tiene exactamente lo registrado, en su orden.

Se reemite con `--calentamiento 0` (W = 0, sin censo): así bronce tiene la grabación entera y
la cuenta se puede reconciliar. Cada consumo usa un grupo propio (`edsim-bronce-test-<8 hex>`),
como los de la 7.5, y cada ejecución un `run_id` único.
"""

import json
import subprocess
from pathlib import Path

import pytest
from kafka_testing import TIMEOUT
from test_cli_directo import EDSIM
from test_kafka_edsim import unique

from edsim.engine.events import to_json
from edsim.live.kafka import connect_bronze_consumer
from edsim.runs import (
    RunStore,
    read_recorded_records,
    read_recorded_run,
    record_run,
    simulate_run,
)
from edsim.store.consumer import run_consumer
from edsim.store.postgres import PostgresBronze, connect, read_bronze_lines, read_bronze_records

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data"
PROFILES_FILE = ROOT / "config" / "registro_clinico.toml"
SEED = 7
RUN_LIMIT = 60.0
"""Segundos para consumir una ejecución, como en test_almacen.py."""


@pytest.fixture(scope="module")
def saved(tmp_path_factory) -> tuple[RunStore, str]:
    """Una ejecución de 2 días con los ejemplos del hito 5, con lo registrado limpio y realista."""
    root = tmp_path_factory.mktemp("directo-registro")
    run_id = unique("treg")
    simulate_run(
        DATA / "centro_h5_ejemplo.toml",
        DATA / "llegadas_ejemplo.toml",
        2,
        SEED,
        output_dir=root / run_id,
        run_id=run_id,
        warmup_days=1,
        origin="cli",
        profiles=DATA / "perfiles_h5_ejemplo.toml",
    )
    store = RunStore(root)
    for profile in ("limpio", "realista"):
        record_run(store, run_id, profile, profiles_file=PROFILES_FILE)
    return store, run_id


def publish_and_consume(saved, profile: str, bootstrap: str, bronze_url: str) -> str:
    """Reemite lo registrado con `profile` y lo consume hasta tener el derivado; su `run_id`."""
    store, run_id = saved
    launch = subprocess.run(
        [EDSIM, "directo", "reemitir", run_id, "--ejecuciones", str(store.root),
         "--calentamiento", "0", "--velocidad", "max", "--registro", profile,
         "--registros", str(PROFILES_FILE), "--kafka", bootstrap],
        capture_output=True,
        text=True,
        check=False,
        timeout=TIMEOUT,
    )  # fmt: skip
    assert launch.returncode == 0, launch.stdout + launch.stderr
    derived = f"{run_id}_{profile}_s{SEED}"
    assert f"Replay · run_id {derived} · " in launch.stdout
    assert "Coincide, byte a byte, con " in launch.stdout

    with connect(bronze_url) as connection:
        consumer = connect_bronze_consumer(bootstrap, group_id=unique("edsim-bronce-test"))
        try:
            report = run_consumer(
                consumer, PostgresBronze(connection), run_id=derived, timeout=RUN_LIMIT
            )
        finally:
            consumer.close()
        runs = connection.execute(
            "SELECT tipo, mensaje FROM bronce.ejecuciones WHERE run_id = %s ORDER BY ingest_time",
            (derived,),
        ).fetchall()
    assert report.complete, report
    assert [kind for kind, _ in runs] == ["inicio", "fin"]
    assert runs[0][1]["registro"] == {"origen": run_id, "perfil": profile, "semilla": SEED}
    return derived


def test_con_el_perfil_limpio_bronce_es_la_verdad_salvo_los_identificadores(
    saved, bootstrap, edsim_topics, bronze_url
):
    store, run_id = saved
    derived = publish_and_consume(saved, "limpio", bootstrap, bronze_url)

    run = read_recorded_run(store, run_id, "limpio")
    truth = {event.event_id: event for event in run.truth}
    fact_of = {row.record_id: row.fact_id for row in run.notebook if row.record_id is not None}
    lines = read_bronze_lines(bronze_url, derived)

    assert len(lines) == len(run.truth) > 1000  # con W = 0, todo; y no es un test vacío
    for line in lines:
        written = json.loads(line)
        expected = json.loads(to_json(truth[fact_of[written["event_id"]]]))
        assert written.pop("run_id") == derived
        assert written.pop("event_id").startswith(f"{derived}-")
        del expected["run_id"], expected["event_id"]
        assert written == expected
    # Cada hecho, una vez: la libreta empareja uno a uno.
    assert sorted(fact_of[json.loads(line)["event_id"]] for line in lines) == sorted(truth)


def test_con_el_perfil_realista_la_cuenta_cuadra_con_lo_leido_de_bronce(
    saved, bootstrap, edsim_topics, bronze_url
):
    store, run_id = saved
    derived = publish_and_consume(saved, "realista", bootstrap, bronze_url)

    run = read_recorded_run(store, run_id, "realista")
    from_files = read_recorded_records(run)
    from_bronze = read_bronze_records(bronze_url, derived)

    assert from_bronze == list(from_files)
    # compare lanza ReconciliationError si la cuenta no cuadra: aquí cuadra, y como con ficheros.
    assert run.compare(from_bronze) == run.compare(from_files)
    # Guardas: lo realista tiene despistes de verdad en esta ejecución.
    kinds = {row.kind for row in run.notebook}
    assert {"perdido", "duplicado", "con_despistes"} <= kinds
