# 0027. Log de eventos JSONL con sobre común, `sim_time` y `event_id` determinista

- **Estado:** Aceptada
- **Fecha:** 2026-11-03

## Contexto

El log de eventos es la fuente de verdad ([ADR 0006](0006-log-de-eventos-y-ground-truth.md)) y la única salida del motor: estado, métricas y validación se derivan de él ([especificación](../specs/hito-3.md#log-de-eventos-ground-truth-y-derivados)). Tiene que ser reproducible bit a bit, permitir cálculos exactos y bastar para reconstruir la ocupación de boxes y médicos. El diseño ya definía un sobre común y un catálogo v0.

## Decisión

- Una línea JSON por evento (JSONL), con el sobre del diseño más `sim_time` (minutos de simulación) y un `payload` propio de cada tipo.
- `event_id` determinista: el `run_id`, un guion y el número de orden con nueve cifras.
- `event_time` en ISO 8601 con milisegundos truncados y desfase fijo `+01:00`; `recorded_time` igual y `ingest_time` nulo hasta los hitos 6 y 7.
- Se añaden `box_assigned` y `patient_displaced` al catálogo, y la reevaluación usa `assessment_started` y `assessment_ended` con `tipo: reevaluacion`, en lugar de `reassessment_done`.
- El catálogo es la única definición de los tipos: valida cada evento al emitirlo y pone el `source_system`.

Motivo: reproducibilidad bit a bit; cálculos con `sim_time`, sin redondeos de reloj; y la ocupación de boxes y médicos se puede derivar del log.

## Alternativas consideradas

- `event_id` con `uuid4`: rompe la reproducibilidad y la huella; fallaron 7 tests en la tarea 3.2 ([anexo, tarea 3.2](../specs/hito-3.md#tarea-32-log-de-eventos-sobre-catálogo-y-jsonl)).
- Redondear los milisegundos en lugar de truncar: 1.439,9999999 min pasaría al día siguiente.
- `reassessment_done` como evento único: sin inicio y fin no se puede derivar la ocupación de los médicos.
- Hora local con cambio de hora: el reloj del simulador no tiene cambio de hora ([ADR 0020](0020-tasa-continua-interpolada.md)).

## Consecuencias

- Un tipo desconocido, una clave de más o un valor de tipo incorrecto falla en el primer evento, no en un log de 100.000 líneas.
- El log se lleva la mayor parte del tiempo de una ejecución: unos 18 µs por evento frente a 4 de SimPy. Si hace falta velocidad, el sitio a mirar es el log.
- Las réplicas de la validación se reducen a números una a una, sin acumular millones de eventos en memoria.
- `patient_arrived` lleva `env.now`, que puede diferir en 1 ulp del instante de `iter_arrivals`; el ground truth guarda el instante exacto.
- `MappingProxyType` hace el `payload` de solo lectura, y `__reduce__` permite serializarlo con `pickle` para las réplicas en paralelo de los hitos 9 y 10.
