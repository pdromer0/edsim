# 0034. El hito 4 cubre el paciente clínico; destino, abandono y boarding van al hito 5

- **Estado:** Aceptada
- **Fecha:** 2026-11-07

## Contexto

La cadena generativa del diseño va del contexto de la llegada al destino del paciente, pasando por la edad, el motivo, la gravedad, el triaje, las pruebas y las duraciones, y el diseño añade bucles de saturación (ruido de triaje y abandono que crecen con la cola). Hacerlo todo en un hito mezclaría piezas que dependen unas de otras. Además, los objetivos observados de ingreso, estancia y cola de los días punta dependen del destino, del boarding y del abandono ([especificación, «Objetivo y alcance»](../specs/hito-4.md#objetivo-y-alcance) y [«Calibración»](../specs/hito-4.md#calibración)).

## Decisión

El hito 4 cubre población, motivo, gravedad, triaje con error, pruebas, duraciones, relojes y una primera calibración. El destino provisional del hito 3 no cambia. Abandono, destino real, boarding y bucles de saturación van al hito 5.

Motivo: sin destino, boarding ni abandono, el ingreso, la estancia y la cola en días punta saldrían mal por construcción, y los bucles necesitan el estado del servicio en el paciente.

## Alternativas consideradas

- Incluir el destino real, el abandono y el boarding en el hito 4: dependen unos de otros y de la gravedad, que este hito construye ([«Para versiones posteriores»](../specs/hito-4.md#para-versiones-posteriores)).
- Calibrar ya el porcentaje de ingreso, la estancia y la cola de los niveles 4 y 5 en días punta: sin destino, boarding ni abandono saldrían mal por construcción, y ajustarlos ahora sobredimensionaría la plantilla ([«Calibración», objetivos indirectos](../specs/hito-4.md#calibración)).

## Consecuencias

- La calibración del hito 4 solo usa el pretriaje y el tiempo hasta el médico ([ADR 0041](0041-centro-realista-calibrado-con-dos-mandos.md)). El destino sigue siendo el provisional, ahora con el nivel asignado.
- Sin abandono, las colas largas no se cortan: en la peor semana de enero de la semilla 2026, el nivel 5 llega a 3897 min de espera, que no es realista ([anexo, tarea 4.6c](../specs/hito-4.md#tarea-46c-recalibración-con-la-ventana-anual)). El hito 5 vuelve a mirar esa semana.
- El resultado de cada prueba (normal o alterado) ya se sortea, aunque nadie lo use todavía: lo usará el destino del hito 5, y así el flujo de pruebas no cambia de consumo entre hitos ([«Pruebas y duraciones»](../specs/hito-4.md#pruebas-y-duraciones)).
- `[destino]` sigue en `config/centro.toml` hasta el hito 5, con los dos modelos.
