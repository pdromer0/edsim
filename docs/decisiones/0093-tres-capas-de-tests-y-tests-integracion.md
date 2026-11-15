# 0093. Tres capas de tests y el job `tests-integracion`, con Kafka y Postgres

- **Estado:** Aceptada
- **Fecha:** 2026-11-13

## Contexto

El registro clínico se prueba sin servicios, pero el consumidor necesita un Kafka y un Postgres reales. Pedro pidió no repetir tests caros que no aportan: cada test tiene que pillar un error que no pille ningún otro ([especificación, «Tests y validación»](../specs/hito-7.md#tests-y-validación)).

## Decisión

- **Tres capas:** rápidos sin Docker, lentos e integración, contra Kafka y Postgres reales. Es la decisión 50, con la regla de Pedro.
- **Cada test dice qué error pilla** que no pille ningún otro.
- **Una base de datos de prueba por sesión.**
- El job `tests-kafka` pasa a **`tests-integracion`**, con Kafka y Postgres, y sigue siendo obligatorio.

## Alternativas consideradas

- **Un job aparte para Postgres:** dos arranques de servicios, cuando el consumidor necesita los dos a la vez. Tendría sentido si una suite solo de Postgres creciera mucho.
- **Probar el consumidor solo con dobles:** no vería `ON CONFLICT`, su recuento ni el error real de Postgres.

## Consecuencias

- La integración no depende de que alguien la ejecute en local.
- `scripts/tests-integracion.sh` espera a que los dos servicios estén sanos.

## Qué cambió al implementarla

- **7.5:** la base de datos de cada sesión es `edsim_test_<8 hex>`, y se borra al acabar. El job conserva `needs: cambios` y su `if` (V20). Al fusionar la 7.5, `main` exige `tests-integracion` en lugar de `tests-kafka`.
- **7.5, las medidas:** el job pasó de 1:30 (`tests-kafka`) a 1:46, con 28 tests en 60 s. En local, la 7.4 midió 33 tests en 1:47.
- **7.3:** los tres tests de `registro comparar --postgres` se probaron en local contra un Postgres 16 sin TimescaleDB, con una extensión de mentira que solo admite las dos llamadas de la migración; en el CI, contra la imagen fijada.
- **7.5, sin la integración en local** (decisión de Pedro tras los cuelgues de WSL): la hizo el job del CI del PR, y Pedro comprobó a mano `almacen preparar` y `consumir`.
- **Fuera del hito, por lo que pasó en la 7.5:** con V16, un test de la CLI giraba sin fin contra un doble que guardaba cada llamada, y agotó la memoria de WSL. De ahí salió el #131 (PR #132): `pytest-timeout` con 60 s por defecto, y `RunawayLoop` con `check_calls` en los dobles que se llaman en bucle.
