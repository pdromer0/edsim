# 0102. Preparación en dos pasos y reconstrucción completa

- **Estado:** Aceptada
- **Fecha:** 2026-11-16

## Contexto

La limpieza tiene que vivir en un solo sitio, para que las ocho tablas de plata y los KPIs de oro no la repitan con matices distintos. Un modelo incremental ahorra tiempo, pero obliga a pensar en ventanas de revisión antes de saber si hace falta ([pieza 1](../specs/hito-8.md#pieza-1--dbt-la-transformación-como-código) y [preparación y limpieza](../specs/hito-8.md#especificación-preparación-y-limpieza)).

## Decisión

- `preparacion.registros` (vista) → `preparacion.registros_vigentes` (tabla, la limpieza) → plata y oro (tablas), con reconstrucción completa en cada `dbt build`.
- La macro `generate_schema_name`, para que los esquemas se llamen exactamente `preparacion`, `plata` y `oro`.
- Lo incremental, a versiones posteriores, por interés didáctico de Pedro.

## Alternativas consideradas

- **Incremental desde el principio:** las correcciones llegan de 120 a 720 min después, así que la ventana de revisión debe cubrir al menos 12 h. Tendrá sentido con un test que demuestre lo que se pierde con una ventana más corta, y como plan B del tiempo real (#156).
- **La limpieza repartida por modelos:** cada tabla de plata con su regla de duplicados; las diferencias entre ellas serían difíciles de ver.

## Consecuencias

- Medir antes de optimizar: la 8.7 midió la vuelta con un año (decisión 109).
- Cada regla lleva su «por qué» en la documentación del modelo.

## Qué cambió al implementarla

- **8.1** (#149, `ed62608`):
  - **desempates:** en duplicados, el menor `event_id`; en correcciones con el mismo `recorded_time`, el mayor (la especificación no lo cubría). Los `event_id` se comparan como texto, que equivale a compararlos como número porque llevan nueve dígitos con ceros;
  - **los recursos se apartan por `episode_id is null`,** porque en un `PARTITION BY` los nulos caen en un mismo grupo;
  - `schema_version` y `sim_time` se quedan fuera de `registros`;
  - el esquema del destino es `public`, para un modelo sin esquema propio (hoy ninguno).
- **8.1, la revisión** (`e3caf26`): la vista se leía dos veces; queda una sola lectura y la macro `columnas_registro`.
- **8.3** (#151): todos los modelos de plata leen solo `registros_vigentes`, con un CTE `vigentes`, así que el grafo de plata es plano.
- **8.7** (#155): con un año en bronce, `registros_vigentes` es el paso más caro de la vuelta (24 s de 60,1 s).
