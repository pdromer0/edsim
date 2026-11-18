# 0101. dbt-core 1.12 y dbt-postgres 1.11 en `analitica/`, un proyecto uv aparte

- **Estado:** Aceptada
- **Fecha:** 2026-11-16

## Contexto

dbt arrastra muchas dependencias (psycopg2-binary, agate, protobuf…) que no deben tocar el lock del núcleo. dbt v2 (Rust) no admite Postgres sin `DBT_ALLOW_EXPERIMENTAL_ADAPTERS`, y dbt-postgres 1.11 exige dbt-core < 2.0 ([pieza 1](../specs/hito-8.md#pieza-1--dbt-la-transformación-como-código)).

## Decisión

- dbt-core 1.12 y dbt-postgres 1.11 en `analitica/`: un proyecto uv con su propio `pyproject.toml` y su propio `uv.lock`, fuera del workspace y en el mismo repositorio.
- Sin paquetes de dbt Hub (ni `dbt deps` ni red al ejecutar).
- `profiles.yml` versionado, con `env_var()` y los valores de compose por defecto.

## Alternativas consideradas

- **dbt en el lock común:** mezcla sus dependencias con las del núcleo, y subir dbt arrastra lo demás.
- **`uvx` sin lock:** versiones sin fijar, sin reproducibilidad.
- **Un repositorio aparte:** los cambios que cruzan capas (catálogo de eventos y staging) irían en dos PR, y la punta a punta en dos CI. Tendría sentido si otro equipo se hiciera cargo o contra un HIS real.
- **SQLMesh:** técnicamente atractivo, con un ecosistema menor. **SQL con migraciones:** sin grafo, tests de datos ni linaje.

## Consecuencias

- Aislar las dependencias no exige separar repositorios.
- Las órdenes de dbt se lanzan desde `analitica/`, con su entorno (`cd analitica && uv sync --locked`).
- Sus tests corren en `tests-integracion`, no en la rápida ni en la completa (decisión 111).

## Qué cambió al implementarla

- **8.1** (#149, `ba67148`): versiones fijadas en el lock, dbt-core 1.12.7, dbt-postgres 1.11.0, dbt-adapters 1.24.5 y psycopg2-binary 2.9.13 (62 paquetes, Python 3.13). El `uv.lock` raíz no cambia. El entorno ocupa 279 MB y tarda 121 s en frío.
- **8.1, la revisión:** `exclude = ["analitica"]` en el workspace raíz, porque uv trata `analitica/` como proyecto aparte y `members` es una lista fija.
- **8.3** (#151): sin `dbt_utils`, `unique` y `relationships` solo admiten una columna; plata lleva sus propios tests de clave compuesta (`clave_unica` y `relacion`).
