# 0100. Alcance del hito 8: dbt, la verdad con permisos, Grafana y el registro por defecto

- **Estado:** Aceptada
- **Fecha:** 2026-11-16

## Contexto

El hito 7 dejó lo registrado en bronce, tal como llega, y midió cuánto se desvían los indicadores calculados sin limpiar. Para cerrar la fase 3 de la hoja de ruta («KPIs en Grafana en tiempo real») faltaban la capa con la que trabaja un analista, un cuadro de mando y la medida de cuánto recupera la limpieza ([especificación, «Objetivo y alcance»](../specs/hito-8.md#objetivo-y-alcance)).

## Decisión

- **Dentro:** dbt con plata y oro, la verdad en Postgres con permisos, Grafana y el registro realista por defecto en el directo.
- **Fuera:** Quix Streams, la retención y la compresión de Timescale, Parquet y DuckDB (hito 9) y la app.

## Alternativas consideradas

- **Quix Streams para los KPIs por ventana con el tiempo del evento.** Se eligió dentro y, a pregunta de Pedro, se reconsideró: su `main` pide `confluent-kafka<2.12` y EDsim fija la 2.16, y su valor es una lección (ventanas y eventos tardíos), no una pieza que el producto necesite. Tendría sentido cuando admita `confluent-kafka` 2.16, para medir qué fracción de registros cae fuera del margen según la ventana.
- **Retención y compresión de Timescale:** con datos simulados no enseñan nada (una reemisión de un año cae en un solo trozo de 7 días). Con un directo de semanas a velocidad real.
- **Parquet y DuckDB para el camino por lotes:** al hito 9, con las réplicas.
- **La app:** las piezas nuevas atan la app a Docker; va a la fase 2 (#122).

## Consecuencias

- El criterio de la fase 3 se cumple con dbt por micro-lotes (decisión 109), sin otro motor.
- Lo aplazado está en «Para versiones posteriores» de la especificación y en la [hoja de ruta](../diseno.md#hoja-de-ruta).

## Qué cambió al implementarla

Nada. El alcance se cumplió tal cual: de la 8.1 a la 8.8, PR #149 a #157. La vuelta del tiempo real con un año (60,1 s) es de la decisión 109.
