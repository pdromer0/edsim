# 0040. Tres relojes hasta el médico y cumplimiento Manchester desde la clasificación

- **Estado:** Aceptada
- **Fecha:** 2026-11-07

## Contexto

Entre la llegada y el primer médico hay tres tramos: pretriaje, triaje y espera de box y médico. En España se usan tres relojes distintos: el TPAM del SAS cuenta desde la llegada, el TEA desde el inicio del triaje y Manchester, desde la clasificación. El hito 3 medía el cumplimiento con el reloj A, desde la llegada: con un triaje de p90 de 10 minutos, solo el 90 % de los triajes acaba en 10 minutos, así que el nivel 2 no podía cumplir nunca ([especificación, «Relojes y cumplimiento»](../specs/hito-4.md#relojes-y-cumplimiento)).

## Decisión

- `EpisodeRecord` tiene los tres relojes con nombre propio: A (`door_to_doctor`), B (`triage_start_to_doctor`) y C (`classified_to_doctor`).
- El cumplimiento Manchester usa C: `manchester_compliance` recibe la medida como parámetro, con C por defecto. Desde la tarea 4.9, también `runs/` (`APP_COMPLIANCE_MEASURE` y `RunResults.compliance`).
- El pretriaje tiene su indicador por día: porcentaje con 10 minutos o menos (estándar del 85 %) y por encima de 5 minutos (el TECLA del SAS), sin el nivel 1.
- El nivel 1 se informa con su tiempo (mediana y p90), sin porcentaje.
- El cumplimiento por nivel real es una función aparte que exige el ground truth.

Motivo: antes del triaje no hay nivel; C separa la cola de triaje de la de médicos; con el reloj A el nivel 2 no podía cumplir.

## Alternativas consideradas

- Seguir con el reloj A: el incumplimiento del nivel 2 era del reloj, no del centro. En el mes del notebook 03 pasa de 25 de 26 días fuera con A a 0 de 26 con C ([anexo, tarea 4.1](../specs/hito-4.md#tarea-41-relojes-pretriaje-y-nivel-1-en-la-puerta)). En el notebook 04, el 45,5 % de los niveles 2 ya pasa de su máximo al clasificarse: con A queda fuera los 89 días; con C, 14.
- Un porcentaje para el nivel 1: su máximo es 0 y el porcentaje sería siempre 0 %.
- Calcular el cumplimiento por nivel real desde el log: el nivel real no está en el log. La función aparte recibe el ground truth para que no se pueda calcular sin él ([anexo, tarea 4.7](../specs/hito-4.md#tarea-47-notebook-04-de-perfiles-clínicos)).

## Consecuencias

- Un fallo de pretriaje es de la enfermería de triaje y un fallo de C, de boxes y médicos: la calibración tiene un mando para cada uno ([ADR 0041](0041-centro-realista-calibrado-con-dos-mandos.md)). Los objetivos de calibración del SAS siguen en el reloj A, porque el TPAM cuenta desde la llegada; las normas solo puntúan.
- El cambio de valor por defecto no cambió nada sin querer: quien usaba A (la app hasta la 4.8b y el notebook 03) lo pidió de forma explícita. La app pasa C desde la 4.8b; `runs/`, desde la 4.9; el notebook 03 sigue pidiendo A para comparar con el hito 3.
- `classified_late` da la proporción de cada nivel que ya pasa de su máximo al clasificarse: ningún médico puede hacerlos cumplir con el reloj A.
