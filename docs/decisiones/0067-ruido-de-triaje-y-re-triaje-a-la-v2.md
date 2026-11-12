# 0067. El ruido de triaje que crece con la saturación y el re-triaje van a la v2

- **Estado:** Aceptada
- **Fecha:** 2026-11-10

## Contexto

El diseño tiene tres bucles de saturación: más cola trae más abandono, más ingresos esperando cama dejan menos boxes libres, y la saturación empeora el triaje. El hito 4 aplazó los tres al hito 5 ([decisión 34](../diseno.md#registro-de-decisiones-y-preguntas-abiertas)). Para los dos primeros hay datos con los que calibrar: el abandono del SAS y la estancia de los ingresados. Para el tercero, la evidencia es mixta y no da un coeficiente ([especificación del hito 5](../specs/hito-5.md#decisiones-del-hito), H5-1).

## Decisión

El ruido de triaje que crece con la saturación va a la v2, junto al re-triaje de quien supera el tiempo máximo de su nivel. El hito 5 se queda con los dos bucles que tienen dato: el abandono y la espera de cama.

## Alternativas consideradas

- **Un coeficiente elegido a mano** (por ejemplo, σ del triaje proporcional a la cola): no se calibraría contra nada, se decidiría, y movería el reparto de niveles que calibró el hito 4.
- **El re-triaje en el hito 5:** cambia cuándo se fija el nivel (hoy, al acabar el triaje, con los sorteos del paciente hechos al llegar) y pide una regla clínica sin fuente.

## Consecuencias

- El nivel asignado sigue dependiendo solo del paciente, nunca del estado del servicio: los números aleatorios comunes del hito 4 siguen valiendo.
- La v2 tendrá que fijar el nivel al empezar el triaje, no al llegar ([«Para versiones posteriores»](../specs/hito-5.md#para-versiones-posteriores)).

## Qué cambió al implementarla

Nada: ninguna tarea del hito 5 tocó el triaje.
