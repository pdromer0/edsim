# 0016. Métricas derivadas de los registros por cliente

- **Estado:** Aceptada
- **Fecha:** 2026-10-28

## Contexto

La M/M/1 del hito 1 mide dos tipos de media ([especificación](../specs/hito-1.md#diseño-del-modelo-mm1)):

- **por cliente:** Wq y W;
- **en el tiempo:** Lq, L y ρ, que son el área bajo una escalera dividida por la duración.

Las dos se calculan en la ventana \[warmup, horizon\]. De cada estancia solo cuenta la parte que cae dentro de la ventana, incluidos los clientes que ya estaban antes de empezar o que siguen al final.

El diseño del modelo en la especificación preveía dos registros: uno por cliente y una traza del sistema con cada cambio en el número de clientes en cola y en el sistema.

## Decisión

Las métricas se calculan a partir de los registros por cliente (llegada, servicio asignado, inicio y fin). El modelo no guarda una traza aparte.

Motivo: una única fuente de verdad, con hechos registrados y estados derivados, como en el log de eventos ([0006](0006-log-de-eventos-y-ground-truth.md)).

## Alternativas consideradas

- Una traza del sistema guardada por el modelo, como preveía la especificación. Se sustituye por el estado derivado de los registros; no se documentaron otros motivos.

## Consecuencias

- `mm1_metrics(records, warmup, horizon)` recorta cada intervalo a la ventana con la función privada `_time_in_window`.
  - Un ejemplo pequeño calculado a mano detecta una versión que no recorta.
- El número de clientes en el sistema se reconstruye de los registros: los que han llegado menos los que han salido.
- La ley de Little sirve de control cruzado entre métricas calculadas por caminos distintos. En una réplica de la tarea 1.3, λ_obs·W = 4,702 frente a L = 4,703.
- En la tarea 1.6, `occupancy` construye la escalera de cola y de sistema a partir de los mismos registros. Sus medias en el tiempo coinciden con las de `mm1_metrics` con una tolerancia relativa de 10⁻⁹ en los tests.
