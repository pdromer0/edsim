# 0073. Catálogo versión 4: abandono, cama y cuatro destinos

- **Estado:** Aceptada
- **Fecha:** 2026-11-10

## Contexto

El abandono, la espera de cama y los destinos nuevos tienen que verse en el log, que es la única salida del motor (decisión 6). El catálogo de la versión 3 no tiene cómo decir que alguien se fue sin ser visto, ni que un ingresado espera cama, y su destino solo admite alta e ingreso ([especificación, «Catálogo v4»](../specs/hito-5.md#especificación-catálogo-v4-y-máquina-de-estados)).

## Decisión

- **La versión 4**, que escribe solo el modelo del hito 5, es la 3 más:
  - `patient_left_wbs` (con `espera`: `triaje`, `box` o `medico`);
  - `bed_requested` y `bed_assigned` (con `servicio`, que solo vale `planta`);
  - los destinos `traslado` y `exitus` en `disposition_decided` y `patient_departed`.
- **`TERMINAL_EVENTS[4]`** = {`patient_departed`, `patient_left_wbs`}.
- **Traslado y exitus** salen al decidirse, sin espera.
- **El ingreso:** `bed_requested` sale en el instante de la decisión, y `bed_assigned` y `patient_departed`, juntos, al acabar la espera.
- **Un ingresado desalojado** por un nivel 1 espera la cama en el pasillo, sin volver a pedir box.

## Alternativas consideradas

- **El abandono como un `patient_departed` con destino `abandono`:** mezclaría un hecho del paciente con una decisión del médico. Un evento por hecho.
- **Que el ingresado desalojado vuelva a pedir box:** un atendido competiría por un box con quien aún no lo está.

## Consecuencias

- El censo del directo funciona sin tocarlo: «abierto» se decide con `TERMINAL_EVENTS` de su versión (decisión 58).
- `schemas/eventos-v4.schema.json` sale del generador de la 6.4. Los logs de las versiones 1 a 3 se siguen leyendo y validando con su catálogo.
- Dos invariantes nuevas, `abandonment` y `outcome`, y las de transiciones, conservación, tiempo, capacidad y desalojo ampliadas, solo con logs de la versión 4. Las versiones 1 a 3 dan exactamente las mismas violaciones que antes.

## Qué cambió al implementarla

- **5.1:** el empate del abandono es un evento propio de prioridad `LATE` ([ADR 0070](0070-paciencia-lognormal-por-nivel-real.md)), y la cama, un `timeout` del propio paciente ([ADR 0072](0072-espera-de-cama-lognormal-con-factor-de-turno.md)). Los tests que usaban la 4 como versión desconocida pasaron a la 5.
- **5.4:** el directo y el consumidor trabajan con la versión 4. «Directo = batch» gana su caso, y quien se fue antes del arranque está cerrado y no entra en el censo.
- **5.6, la invariante `nobody_jumps_the_queue`:** ya no cuenta como salto dos concesiones del mismo recurso en el mismo instante. Con el hito 5, quien espera con su plazo (`request | deadline`) se reanuda un paso después que una reevaluación, y su `assessment_started` puede salir detrás en el log aunque SimPy le concediera el médico antes (comprobado en el orden de concesión). Pedro eligió corregir la invariante y no el motor, así que las huellas no cambiaron. Va en este ADR porque es la regla del orden de los eventos de un mismo instante.
