# 0092. Migraciones SQL numeradas, con un aplicador propio

- **Estado:** Aceptada
- **Fecha:** 2026-11-13

## Contexto

El Postgres del portátil, el del CI y el de los tests tienen que tener siempre las mismas tablas, y cambiarlas más adelante no debe obligar a borrar datos ([especificación, pieza 5](../specs/hito-7.md#pieza-5--migraciones)).

## Decisión

- **Migraciones SQL numeradas** dentro del paquete (`src/edsim/store/sql/001_bronce.sql`, …).
- **Un aplicador propio**, `edsim almacen preparar`, con una tabla de versiones (`public.migraciones`) y una transacción por migración: solo aplica las que faltan.
- En este hito, solo el esquema `bronce`. Las tablas de plata y oro del hito 8 las crea dbt, no son migraciones.

## Alternativas consideradas

- **Alembic**, el estándar en Python: va ligado a SQLAlchemy, un ORM que el núcleo no usa. Tendría sentido si las migraciones crecieran y hiciera falta generarlas desde modelos.
- **Flyway o Sqitch**, herramientas externas: otra pieza que instalar para tres tablas. Tendrían sentido con varios equipos tocando el esquema.

## Consecuencias

- Pocas tablas y el SQL a la vista, sin ORM en el núcleo.
- `edsim almacen preparar` hace con las tablas lo que `edsim directo preparar` con los topics.

## Qué cambió al implementarla

- **7.5:** el aplicador está en `migrations.py`. V19 (no registrar la migración aplicada) hace fallar 3 tests.
- **7.5:** `001_bronce.sql` empieza con `CREATE EXTENSION IF NOT EXISTS timescaledb`, como cuenta la [ADR 0089](0089-postgres-con-timescaledb-en-compose.md). Por lo demás, nada.
