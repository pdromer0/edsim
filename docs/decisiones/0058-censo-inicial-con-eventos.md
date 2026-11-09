# 0058. El censo inicial son eventos del log, no una foto del estado

- **Estado:** Aceptada
- **Fecha:** 2026-11-06

## Contexto

Un directo calienta sin publicar hasta W. Un consumidor que empezara en W vería pacientes dentro sin su llegada. Había que darle el estado de partida sin inventar un contrato nuevo ([especificación, pieza 6](../specs/hito-6.md#pieza-6--el-modo-directo-calentamiento-censo-inicial-control-y-replay)).

## Decisión

El censo son los eventos del calentamiento de los episodios abiertos en W más todos los de recursos, en su orden original. «Abierto» se decide con `TERMINAL_EVENTS` de la versión de cada evento, y se contrasta con los procesos de paciente vivos del motor.

## Alternativas consideradas

- Una foto del estado (un mensaje `system_snapshot`): un contrato nuevo por versión del catálogo, y el consumidor necesitaría dos códigos, uno para la foto y otro para los eventos.

## Consecuencias

- El consumidor deriva el estado con el mismo código para el censo y para el directo (*event sourcing*).
- Vale para cualquier catálogo: el 4 solo añadirá su abandono a `TERMINAL_EVENTS`.

## Qué cambió al implementarla

- 6.2: `open_episodes`, `census` y `live_events` en `edsim.live.census` (no `live`, que es el nombre del subpaquete); un paciente que sale justo en W está abierto y su salida es del directo. Con `config/` y W = 2 días: 113 abiertos, iguales a los procesos vivos, y 520 eventos de censo, el 6,03 % del calentamiento.
- 6.3: `run_live` comprueba abiertos = vivos antes de publicar el `inicio`.
- 6.6: el consumidor (`LiveTracker`) aplica el censo y el directo con `LocationState`, el reductor del Replay de la app, y su estado final es el del batch filtrado («consumidor = batch»).
