# 0099. Ocho tareas en dos pistas y la etiqueta `v0.7-hito7`

- **Estado:** Aceptada
- **Fecha:** 2026-11-13

## Contexto

El registro clínico y la persistencia apenas comparten código: `clinical_record/` y `live/` frente a `store/`, `compose.yaml` y el CI. Una parte puede ir en la nube y la otra necesita Docker en local ([especificación, «Tareas»](../specs/hito-7.md#tareas-ramas-y-orden-de-ejecución)).

## Decisión

- **Ocho tareas** (7.0 a 7.7), en **dos pistas** tras la 7.0:
  - A: 7.1 → 7.2 → 7.3 → 7.4;
  - B: 7.5.
- Como mucho **dos ramas abiertas**, una por pista.
- **`@codex review`** en la 7.1, la 7.4 y la 7.5, las tareas con la etiqueta `critica`.
- La etiqueta de cierre es **`v0.7-hito7`**.
- Parquet y DuckDB, fuera del hito.

## Alternativas consideradas

- **Una sola pista, en orden:** más lenta, sin ganancia, porque las dos pistas no se tocan. Tendría sentido si compartieran ficheros.
- **Paralelizar también la 7.2 con la 7.3, o la 7.4 con la 7.5:** poco ahorro y tres sesiones que revisar; la 7.4 y la 7.5 necesitan Docker las dos.

## Consecuencias

- Si al fusionar una pista la otra tiene conflictos, su agente trae `main` con un merge, no con un rebase, porque el push forzado está prohibido.

## Qué cambió al implementarla

- **7.5 en paralelo con la 7.1:** la 7.1 se fusionó antes, y la rama de la 7.5 trajo `main` con un merge (`5b8fef4`).
- **7.5, en dos sitios:** la sesión local se interrumpió tres veces porque WSL se quedaba sin memoria durante las versiones incorrectas. Lo que faltaba (el merge, las versiones incorrectas, la revisión y la N3) se hizo en la nube.
- **7.3:** `read_bronze_records` y `registro comparar --postgres` pasaron de la 7.5 a la 7.3, sobre el `read_bronze_lines` de la 7.5 (reparto del chat del 14 de noviembre).
- **Entre medias, dos tareas de la P.3:** el #81 (PR #127, saltar los tests cuando un PR solo cambia documentación) y el #131 (PR #132, el límite de tiempo por test).
- **`@codex review`:** en la 7.1 y en la 7.4, sin hallazgos importantes; en la 7.5, dos fallos ciertos, corregidos en el mismo PR.
- **La etiqueta `v0.7-hito7`** la crea Pedro sobre la fusión del cierre (7.7).
