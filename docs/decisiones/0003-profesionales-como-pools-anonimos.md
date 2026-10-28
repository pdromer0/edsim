# 0003. Profesionales como pools anónimos en la v0

- **Estado:** Aceptada
- **Fecha:** 2026-10-27

## Contexto

Los recursos humanos del modelo son médicos, enfermería, técnicos y celadores. En el motor, cada pool es un recurso de SimPy con prioridad (nivel de triaje y orden de llegada) y desalojo para el nivel 1 ([diseño](../diseno.md#entidades)).

## Decisión

En la v0, los profesionales se modelan como pools anónimos, sin identidad individual.

Motivo: simplicidad del motor. Los identificadores quedan preparados para la v3.

## Alternativas consideradas

- Profesionales individuales: se aplazan a la v3.

## Consecuencias

- La dimensión "responsable" del estado del paciente registra el pool que lo atiende.
- Los cambios de plantilla se expresan por pool y turno, por ejemplo `recursos.medicos.turnos.tarde: +1` o el evento `staffing_changed`.
