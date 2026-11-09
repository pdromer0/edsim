# 0051. Motor por pasos con `peek()` y `step()`, sin cambiar las huellas

- **Estado:** Aceptada
- **Fecha:** 2026-11-06

## Contexto

El directo necesita intercalar esperas entre los eventos del motor sin cambiar su resultado: el log en vivo tiene que ser, byte a byte, el del batch ([especificación, «Tests obligatorios por bloque»](../specs/hito-6.md#tests-obligatorios-por-bloque)).

## Decisión

`start_engine` devuelve un `SteppedEngine` con `peek()` (instante del siguiente evento, o infinito), `step()`, `advance_until(t)`, `alive_episodes()` y `finish()`; `start_ed` devuelve un `SteppedED`. `run_engine` y `simulate_ed` no cambian de firma: son `start_*`, `advance_until(horizonte)` y `finish()`. Las huellas SHA-256 del batch no cambian.

## Alternativas consideradas

- `simpy.rt.RealtimeEnvironment`: un factor de tiempo fijo, sin pausa ni cambio de velocidad en caliente, y la espera dentro de SimPy, donde no se puede inyectar un reloj falso.
- `env.run(until=t)` por trozos: cada llamada mete un evento de parada en la cola de SimPy.

## Consecuencias

- El batch también avanza paso a paso; ningún byte del log cambió (huellas comprobadas con la suite completa).
- `alive_episodes()` permite contrastar el censo con la verdad del motor: los episodios abiertos en W son exactamente los procesos de paciente vivos.

## Qué cambió al implementarla

- `peek()` da infinito si el siguiente evento está en el horizonte o después, y `step()` falla entonces. Un evento justo en el horizonte no ocurre, como en `simulate_mm1`.
- `advance_until(t)` usa `min(t, horizonte)` y rechaza NaN; `finish()` falla si queda algún evento antes del horizonte.
- `SteppedED` delega en el `SteppedEngine` en vez de heredar.
- `simulate_ed` de 14 días: 1,755 s antes y 1,781 s después (mejor de 5), dentro del ruido.
