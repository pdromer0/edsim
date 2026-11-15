# 0085. El registro clínico es una función pura de la verdad; con `--registro`, por Kafka solo viaja lo registrado

- **Estado:** Aceptada
- **Fecha:** 2026-11-13

## Contexto

Lo registrado tiene que salir igual por lotes, en el directo y en la reemisión, y nadie debería poder leer la verdad desde el broker cuando el ejercicio es trabajar con datos sucios. El hito 6 ya comprueba «directo = batch» byte a byte ([especificación, «Directo y reemisión con el registro clínico»](../specs/hito-7.md#especificación-directo-y-reemisión-con-el-registro-clínico)).

## Decisión

- El registro clínico es una **función pura de la verdad** (`record`), dentro del simulador, entre el motor y la salida. No usa SimPy ni el motor, y sirve para lotes, directo y reemisión.
- Con `--registro PERFIL`, **la verdad nunca viaja por Kafka**: solo lo registrado, con el `run_id` derivado.
- Lo registrado en directo es igual, byte a byte, a lo registrado por lotes.

## Alternativas consideradas

- **Un procesador aparte que lea la verdad de Kafka y publique lo registrado:** la verdad pasaría por el broker, y un retraso obligaría a dormir mensajes. Tendría sentido si el registro clínico tuviera que aplicarse a un flujo que EDsim no genera, por ejemplo eventos de otro simulador.
- **El registro clínico dentro del motor:** mezclaría la verdad con sus errores y rompería las huellas de los hitos 3 a 6.

## Consecuencias

- Un solo código para los tres caminos, con la comprobación «directo = lotes» del hito 6 extendida a lo registrado.
- El directo necesita una sala de espera: el registro de un hecho con 7 min de retraso no puede salir antes de que el motor llegue a ese minuto.
- `LiveTracker` y `read_run` siguen siendo para la verdad; lo registrado lo consume bronce.

## Qué cambió al implementarla

- **7.1:** `validate_run_id` pasa a un módulo neutro, `edsim.identifiers`, porque importar `edsim.runs.identifiers` cargaba el motor y SimPy.
- **7.4, la sala de espera** (`RecordStream`, `1c1609e`): suelta un registro cuando `s ≤ peek()`, con un montículo ordenado por la clave de emisión completa `(s, posición, orden)`. Además comprueba que no llega un hecho anterior a una cota ya soltada. V36 (ordenar por `(s, llegada)`, la propuesta del revisor del plan) la descartó: rompe el empate de un duplicado y una corrección a la misma hora.
- **7.4, lotes y directo comparten los despistes, no la ordenación:** `record` ordena todo de una vez y la sala, con el montículo. Así «directo = lotes» compara dos ordenaciones distintas (`d41f849`, `_event_drafts` y `_finish` salen de `record` sin cambiar un byte).
- **7.4, la reemisión usa `record`**, no la sala: `RecordedLog` suelta los registros ya ordenados con la misma regla. Si la carpeta ya tiene lo registrado con ese perfil y esa semilla, tiene que coincidir byte a byte (V35).
- **7.4, el `inicio` con registro** (`89b2b51`): un bloque `registro` con `origen`, `perfil` y `semilla`, detrás de `censo`; todo lleva el `run_id` derivado. `censo.episodios` cuenta los episodios con registros en el censo, no los abiertos de la verdad.
- **7.4:** el lento «directo = lotes» de lo registrado pasa con las versiones 1 a 4 del catálogo, de 1,1 s (v2) a 2,3 s (v3) por caso.
