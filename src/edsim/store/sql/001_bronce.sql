-- 001_bronce: la capa bronce, lo que llega de Kafka tal cual (docs/specs/hito-7.md, H7-7).
--
-- Comprobada con timescale/timescaledb:2.31.0-pg17 (Postgres 17.11) en la tarea 7.5.

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE SCHEMA IF NOT EXISTS bronce;

-- Un registro o un evento por fila. Las columnas del sobre llevan los nombres del mensaje (el
-- contrato); las de bronce, en español.
CREATE TABLE bronce.eventos (
    event_id        text        NOT NULL,
    event_type      text        NOT NULL,
    schema_version  integer     NOT NULL,
    run_id          text        NOT NULL,
    episode_id      text,
    patient_id      text,
    source_system   text        NOT NULL,
    sim_time        double precision NOT NULL,
    event_time      timestamptz NOT NULL,
    recorded_time   timestamptz NOT NULL,
    ingest_time     timestamptz NOT NULL,   -- marca LogAppendTime del mensaje
    payload         jsonb       NOT NULL,
    kafka_topic     text        NOT NULL,
    kafka_particion integer     NOT NULL,
    kafka_offset    bigint      NOT NULL,
    valor           text        NOT NULL,   -- el mensaje tal cual
    recibido        timestamptz NOT NULL DEFAULT now(),
    -- Timescale exige la columna de partición en toda clave única. Las coordenadas de Kafka no
    -- sirven: un broker sin volumen vuelve a empezar los offsets en 0 (V14).
    UNIQUE (event_id, ingest_time)
);
-- Partida por la hora de llegada, que pone Kafka: siempre existe y su reloj es fiable.
SELECT create_hypertable('bronce.eventos', by_range('ingest_time'));
CREATE INDEX ON bronce.eventos (event_time);
CREATE INDEX ON bronce.eventos (run_id, episode_id);

-- Los mensajes de ed.runs: el inicio y el fin de cada publicación.
CREATE TABLE bronce.ejecuciones (
    run_id       text        NOT NULL,
    tipo         text        NOT NULL,
    mensaje      jsonb       NOT NULL,
    ingest_time  timestamptz NOT NULL,
    kafka_offset bigint      NOT NULL,
    UNIQUE (run_id, tipo, ingest_time)
);

-- Los mensajes que no se pueden leer, con el motivo.
CREATE TABLE bronce.rechazados (
    valor           text        NOT NULL,
    motivo          text        NOT NULL,
    kafka_topic     text        NOT NULL,
    kafka_particion integer     NOT NULL,
    kafka_offset    bigint      NOT NULL,
    ingest_time     timestamptz NOT NULL,
    UNIQUE (kafka_topic, kafka_particion, kafka_offset, ingest_time)
);
