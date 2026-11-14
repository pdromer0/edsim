"""El almacén contra un Kafka y un Postgres reales (tarea 7.5, H7-10).

Cada test dice qué pilla que no pille un rápido:

- `preparar`: que el SQL de la 001 funciona con la versión fijada de TimescaleDB, que la
  tabla es una hypertable por `ingest_time` y que la segunda vez no se aplica nada.
- `PostgresBronze`: el `ON CONFLICT` de verdad y su recuento, y que la red de seguridad recibe
  el error de datos de Postgres y no solo el del almacén falso.
- Parar y relanzar: que Kafka recuerda de verdad dónde se quedó el grupo, y que bronce acaba
  con lo publicado, byte a byte. Es también el de extremo a extremo del hito.

Se publica con `edsim directo lanzar --velocidad max`, no con `reemitir`: no hace falta una
carpeta de ejecución y el productor es el mismo. Cada consumo usa un grupo propio
(`edsim-bronce-test-<8 hex>`): con `edsim-bronce`, el test movería los offsets del grupo de
Pedro.
"""

import json
import re
import subprocess
import time
from dataclasses import replace
from datetime import UTC, datetime

import confluent_kafka
from kafka_testing import TIMEOUT
from test_cli_directo import EDSIM, LAUNCH, expected_of
from test_kafka_edsim import unique

from edsim.engine.events import to_json
from edsim.live.kafka import connect_bronze_consumer
from edsim.store.bronze import LOG_APPEND_TIME, KafkaMessage, to_row
from edsim.store.consumer import run_consumer, save_batch
from edsim.store.postgres import PostgresBronze, connect, read_bronze_lines

RUN_LIMIT = 60.0
"""Segundos para consumir una ejecución, fijados antes de medir."""


def test_la_constante_de_la_marca_es_la_de_confluent_kafka():
    assert LOG_APPEND_TIME == confluent_kafka.TIMESTAMP_LOG_APPEND_TIME


def test_preparar_aplica_la_001_una_vez_y_la_tabla_es_una_hypertable(bronze_database):
    url, first = bronze_database
    second = subprocess.run(
        [EDSIM, "almacen", "preparar", "--postgres", url],
        capture_output=True,
        text=True,
        check=False,
        timeout=TIMEOUT,
    )

    assert first.endswith("Migraciones aplicadas: 001_bronce.sql\n")
    assert second.returncode == 0, second.stderr
    assert second.stdout.endswith("ninguna (la base de datos ya estaba al día)\n")
    with connect(url) as connection:
        assert connection.execute("SELECT version, nombre FROM public.migraciones") == [
            (1, "bronce")
        ]
        assert connection.execute(
            "SELECT hypertable_schema, hypertable_name, column_name"
            " FROM timescaledb_information.dimensions"
        ) == [("bronce", "eventos", "ingest_time")]


def message(run_id: str, number: int, payload: str = "{}") -> KafkaMessage:
    value = (
        f'{{"event_id": "{run_id}-{number:09d}", "event_type": "patient_arrived", '
        f'"schema_version": 4, "run_id": "{run_id}", "episode_id": null, "patient_id": null, '
        f'"source_system": "admision", "sim_time": {number}, '
        f'"event_time": "2026-01-05T00:00:00.000+01:00", '
        f'"recorded_time": "2026-01-05T00:00:00.000+01:00", "ingest_time": null, '
        f'"payload": {payload}}}'
    )
    return KafkaMessage(
        "ed.patient.events", 0, number, LOG_APPEND_TIME, 1_767_225_600_123, value.encode()
    )


def test_postgres_bronze_ignora_lo_repetido_y_la_red_recibe_el_error_de_postgres(bronze_url):
    run_id = unique("test-almacen")
    batch = [(m, to_row(m)) for m in (message(run_id, n) for n in range(3))]
    with connect(bronze_url) as connection:
        store = PostgresBronze(connection)
        first = save_batch(store, batch)
        again = save_batch(store, batch)
        # Un payload que bronze.py dejaría pasar si no lo conociera: \u0000 escrito como texto
        # en el JSON de la fila. Postgres lo rechaza al convertirlo a jsonb.
        bad_message = message(run_id, 3)
        bad = (bad_message, replace(to_row(bad_message), payload='{"x": "\\u0000"}'))
        good = (message(run_id, 4), to_row(message(run_id, 4)))
        netted = save_batch(store, [bad, good])
        stored = connection.execute(
            "SELECT event_id FROM bronce.eventos WHERE run_id = %s ORDER BY event_id", (run_id,)
        )
        rejected = connection.execute(
            "SELECT kafka_offset, motivo FROM bronce.rechazados"
            " WHERE valor LIKE %s ORDER BY kafka_offset",
            (f"%{run_id}%",),
        )

    assert (first.saved, first.repeated) == (3, 0)
    assert (again.saved, again.repeated) == (0, 3)
    assert (netted.saved, netted.rejected, netted.retried) == (1, 1, True)
    assert [event_id for (event_id,) in stored] == [f"{run_id}-{n:09d}" for n in (0, 1, 2, 4)]
    [(offset, reason)] = rejected
    assert offset == 3
    assert reason.startswith("Postgres lo rechaza: unsupported Unicode escape sequence")


def published_count(out: str) -> int:
    """`publicados` del resumen de `edsim directo lanzar` («Fin · motivo … · N publicados»)."""
    match = re.search(r"Fin · motivo horizonte · (\d+) publicados", out)
    assert match, out
    return int(match[1])


def test_parar_y_relanzar_el_consumidor_no_pierde_ni_repite_nada(
    bootstrap, edsim_topics, bronze_url
):
    run_id = unique("test-bronce")
    before = datetime.now(UTC)
    launch = subprocess.run(
        [EDSIM, *LAUNCH, "--velocidad", "max", "--run-id", run_id, "--kafka", bootstrap],
        capture_output=True,
        text=True,
        check=False,
        timeout=TIMEOUT,
    )
    assert launch.returncode == 0, launch.stdout + launch.stderr
    published = published_count(launch.stdout)
    group = unique("edsim-bronce-test")

    with connect(bronze_url) as connection:
        store = PostgresBronze(connection)

        # Primera pasada: lotes de 50 y parar en cuanto bronce tenga algo de esta ejecución.
        # Los topics tienen también lo de otros tests: se guarda en esta base de datos y no
        # importa. Se cuentan los eventos sin más, no con progress: progress no cuenta nada
        # hasta leer el inicio, que está en ed.runs, detrás de los de otros tests, y la parada
        # podría llegar con toda la ejecución ya guardada.
        def stored() -> int:
            ((count,),) = connection.execute(
                "SELECT count(DISTINCT event_id) FROM bronce.eventos WHERE run_id = %s",
                (run_id,),
            )
            return count

        limit = time.monotonic() + RUN_LIMIT
        consumer = connect_bronze_consumer(bootstrap, group_id=group)
        try:
            first = run_consumer(
                consumer,
                store,
                batch_size=50,
                should_stop=lambda: stored() > 0 or time.monotonic() > limit,
            )
        finally:
            consumer.close()
        stored_first = stored()
        # Si la parada no cayó a mitad de la ejecución, el relanzamiento no probaría nada.
        assert 0 < stored_first < published, (stored_first, published, first)

        consumer = connect_bronze_consumer(bootstrap, group_id=group)
        try:
            second = run_consumer(consumer, store, run_id=run_id, timeout=RUN_LIMIT)
        finally:
            consumer.close()
        runs = connection.execute(
            "SELECT tipo, mensaje FROM bronce.ejecuciones WHERE run_id = %s ORDER BY ingest_time",
            (run_id,),
        )
        times = connection.execute(
            "SELECT count(*), min(ingest_time), max(ingest_time), bool_and(recibido >= ingest_time)"
            " FROM bronce.eventos WHERE run_id = %s",
            (run_id,),
        )
    after = datetime.now(UTC)

    assert second.complete, second
    # Kafka recordó dónde se quedó el grupo: nada se volvió a leer.
    assert second.repeated == 0
    assert [kind for kind, _ in runs] == ["inicio", "fin"]
    assert runs[1][1]["publicados"] == published
    [(rows, first_ingest, last_ingest, received_after)] = times
    assert rows == published  # una publicación: ni repetidos ni perdidos
    assert before <= first_ingest <= last_ingest <= after
    assert received_after
    # Lo de bronce es lo publicado, byte a byte: cada valor es la línea del batch.
    expected = {event.event_id: to_json(event) for event in expected_of(run_id)}
    lines = read_bronze_lines(bronze_url, run_id)
    assert len(lines) == published
    assert all(line == expected[json.loads(line)["event_id"]] for line in lines)
