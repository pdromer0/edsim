# 0111. Unit tests de dbt por regla, tests de datos y una sola prueba de punta a punta

- **Estado:** Aceptada
- **Fecha:** 2026-11-16

## Contexto

dbt trae dos clases de tests: los de datos, que miran la tabla construida, y los unit tests, que dan unas pocas filas inventadas y comparan la salida. El job `tests` del CI es el camino crítico y no debe crecer ([tests y validación](../specs/hito-8.md#tests-y-validación)).

## Decisión

- Un unit test de dbt por regla de limpieza y de emparejamiento.
- Tests de datos (grano, claves y relaciones) en cada construcción.
- Todo dbt en el job `tests-integracion`: los unit tests desde la 8.1 y nada nuevo en el job `tests`.
- Una sola prueba de punta a punta, con cuatro comprobaciones:
  - limpio frente a verdad con el perfil limpio;
  - verdad SQL frente a verdad Python;
  - ingenuo SQL frente a ingenuo Python;
  - los duplicados frente a la libreta.
- Los paneles y el arranque de Grafana, también en `tests-integracion`.
- `analitica/*` cuenta como código en el job `cambios`.

## Alternativas consideradas

- **Un job aparte para dbt:** otro arranque de Postgres, para unos segundos de tests.
- **Sin punta a punta:** los unit tests no ven la traducción de Python a SQL, que es donde estuvieron los errores (por ejemplo, `greatest` en la 8.5).
- **`dbt parse` en el job `tests`:** alarga el camino crítico y no prueba nada que la integración no pruebe.

## Consecuencias

- Cada test pilla un error que otro no pilla, y el caro se ejecuta una sola vez.
- Los tests de dbt no están en la N3: corren en `scripts/tests-integracion.sh`.

## Qué cambió al implementarla

- **8.1** (#149, `ddc9458`), **D1:** dbt no entra en el job `tests`, el camino crítico del CI (de 16 a 24 min). `tests-integracion` corre en paralelo y dura de 1 a 2 min, así que lo que se le añade no alarga la espera, y un `dbt build` hace también el parse. La tabla de decisiones de la especificación ya lo recoge.
- **8.1** (`5e047ac`): los unit tests corren desde un pytest de `tests_integracion/` que reutiliza la base de la sesión. Como dbt sale con 0 si no ejecuta nada, el test lee `run_results.json` y exige el número de unit tests y de modelos. `sello.sh` no lanza la rápida por `analitica/`.
- **8.3** (#151): los 40 tests de datos de plata comprueban la forma, no la lógica: con una versión incorrecta, siguen en verde.
- **8.5** (#153, `cdad75d`): la prueba de punta a punta, con siete tests. `tests_integracion/dbt_testing.py` reúne lo común.
- **8.6** (#154, `216c9e5`): el test de los paneles ejecuta el SQL de cada panel con el rol de su fuente y exige filas y las 24 horas simuladas.
- **Lección de dbt:** en un `dbt build`, todo lo que cuelga de un unit test que falla queda como SKIP, y el informe solo enseña el primer fallo.
