# 0089. Postgres con TimescaleDB en `compose.yaml`; `psycopg` 3 en un extra y en un solo módulo

- **Estado:** Aceptada
- **Fecha:** 2026-11-13

## Contexto

Kafka transporta mensajes, pero no es un archivo donde buscar con SQL. Hace falta una base de datos donde guardar lo registrado y que el hito 8 (dbt y Grafana) pueda leer ([especificación, pieza 3](../specs/hito-7.md#pieza-3--postgres-timescaledb-y-la-capa-bronce)).

## Decisión

- **Postgres con TimescaleDB** en `compose.yaml`:
  - la imagen, con versión exacta fijada en la 7.5;
  - sin perfil, como Kafka y la consola;
  - con un volumen con nombre;
  - solo en `127.0.0.1`.
- **`psycopg` 3** como extra `edsim[postgres]`, importado en un solo módulo, como `confluent-kafka` (decisión 49).
- **El consumidor corre fuera de Docker**, en WSL2, como el simulador (decisión 65).

## Alternativas consideradas

- **Postgres solo:** menos piezas, pero las funciones de tiempo a mano, y la tabla habría que migrarla a hypertable en el hito 8. Tendría sentido si Timescale diera problemas de licencia o de versión.
- **ClickHouse:** de columnas, muy rápido para analítica y lee de Kafka, pero corrige registros peor y tiene un dialecto propio. Tendría sentido para la analítica pesada, si Postgres se queda corto.
- **DuckDB con Parquet:** analítica en un fichero, sin servidor, pero no admite muchos escritores a la vez. Tiene sentido en el camino por lotes (hito 8 o 9).
- **InfluxDB y similares:** pensadas para métricas numéricas; los eventos con su `payload` encajan mal.
- **MongoDB:** guarda el JSON tal cual, pero sin SQL estándar; dbt y Grafana encajan peor.

## Consecuencias

- SQL estándar con funciones de tiempo (`time_bucket`), y la tabla nace partida por tiempo.
- El patrón de las decisiones 49, 62 y 65: versión fijada, cliente opcional en un solo módulo y servicios en Compose.

## Qué cambió al implementarla

- **7.5, la imagen es `2.31.0-pg17`** (Postgres 17.11), no la `2.32.0-pg17` publicada dos días antes, con el mismo criterio que la consola v3.14.0 en la 6.1.
- **7.5, el healthcheck va por TCP** (`pg_isready -h 127.0.0.1`): sin `-h`, daba por sano el servidor temporal del init.
- **7.5:** `001_bronce.sql` empieza con `CREATE EXTENSION IF NOT EXISTS timescaledb`, porque la base de datos de los tests se crea con `CREATE DATABASE` y no la trae.
- **7.5, el extra:** `psycopg[binary]>=3.3.9,<3.4`. El test de frontera pasa a una tabla de clientes opcionales, cada uno con su único módulo: `confluent_kafka` en `live/kafka.py` y `psycopg` en `store/postgres.py`, los dos dentro de funciones.
- **7.5:** la consola de Redpanda pasa también a `127.0.0.1:8080` (cierra el #91).
