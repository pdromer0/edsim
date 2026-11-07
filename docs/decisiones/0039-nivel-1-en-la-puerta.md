# 0039. El nivel 1 asignado se clasifica en la puerta y va directo al box

- **Estado:** Aceptada
- **Fecha:** 2026-11-07

## Contexto

En el hito 3, el nivel 1 hacía la cola FIFO del triaje, de unos 6 minutos, como cualquier otro paciente. En el mes del notebook 03, su puerta-médico medio era de 9,6 minutos y quedaba fuera de su máximo «inmediato» los 17 días con pacientes de nivel 1 ([anexo, tarea 4.1](../specs/hito-4.md#tarea-41-relojes-pretriaje-y-nivel-1-en-la-puerta)). Un crítico no hace cola de triaje.

## Decisión

Si el nivel asignado es 1, el paciente no pide enfermera: emite `triage_started` (con `circuito: "puerta"`) y `triage_completed` en el instante de la llegada, y pide box con desalojo. El orden de los eventos no cambia. Los demás siguen en FIFO con `circuito: "enfermeria"`. Los médicos no se desalojan ([ADR 0025](0025-tres-pools-con-prioridad-y-desalojo-del-nivel-1.md)).

Motivo: el crítico no hace cola de triaje sin cambiar el orden de los eventos; el desalojo de médicos ahorraría un minuto a un paciente al día con una regla clínica sin datos (v1).

## Alternativas consideradas

- Triaje dentro del box para el nivel 1: cambia el orden de los eventos en 11 módulos y en la app. Queda para el circuito de críticos de la v1 ([«Para versiones posteriores»](../specs/hito-4.md#para-versiones-posteriores)).
- Desalojo de médicos por un nivel 1: ahorra alrededor de 1 minuto a un paciente al día, con una regla clínica sin datos (¿a quién deja el médico?). Circuito de críticos de la v1, con equipo propio.
- Reconocimiento en la puerta por la gravedad real, con su propio error: un segundo juicio que calibrar sin datos. Por decidir.

## Consecuencias

- En el mes del notebook 03, el puerta-médico medio del nivel 1 baja de 9,6 a 0,6 minutos y los días fuera, de 17 a 8 de 17. Lo que queda es la espera de médico: 10 de sus 26 pacientes esperan, hasta 5,3 minutos ([anexo, tarea 4.1](../specs/hito-4.md#tarea-41-relojes-pretriaje-y-nivel-1-en-la-puerta)).
- La enfermería, su escalera de capacidad y la identidad de utilización no cuentan los triajes de puerta. La teoría de la M/G/1 del triaje usa λ · (1 − p₁): su Wq teórica pasa de 13,10 a 12,93 minutos en el centro de ejemplo.
- Los críticos infratriados como 2 hacen cola como cualquier otro; el ground truth lo mide. Con las paradas en el umbral eran casi la mitad, y la [ADR 0046](0046-parada-a-la-puerta.md) lo corrige.
- La invariante `door` exige que puerta y nivel 1 asignado vayan juntos. Los logs anteriores a la tarea 4.1 se leen con `circuito: "enfermeria"`, también en sus niveles 1.
- Las huellas del modelo provisional cambiaron una sola vez en el hito, en la tarea 4.1, por la puerta y el campo `circuito`.
