# 0052. Pacer síncrono con objetivos absolutos y reloj inyectable

- **Estado:** Aceptada
- **Fecha:** 2026-11-06

## Contexto

SimPy salta de evento en evento. Para emitir en vivo hay que esperar hasta el instante real de cada evento, cambiar de velocidad, pausar y atender órdenes sin acumular error ([especificación, pieza 1](../specs/hito-6.md#pieza-1--tiempo-virtual-y-tiempo-real-el-pacer)).

## Decisión

- Pacer síncrono, en un solo hilo, con un reloj inyectable: monótono para esperar y de pared solo para anclar.
- Objetivos absolutos desde un ancla (w₀, s₀): el evento del minuto t se espera hasta w₀ + (t − s₀)·60/v. Al cambiar de velocidad o reanudar, se reancla en el minuto simulado de ese instante.
- Esperas en tramos de 0,2 s como máximo, mirando las órdenes entre tramo y tramo.
- Nunca salta eventos: si se queda atrás, publica enseguida y mide el retraso.

## Alternativas consideradas

- Dormir la diferencia con el evento anterior: los excesos de cada `sleep` se suman (3,8 s de deriva en un día a ×60, frente a 2 ms).
- Hilos o `asyncio`: más cosas que sincronizar, sin ganar nada con un solo productor.

## Consecuencias

- El pacer se prueba con un reloj falso: instantes, reanclajes, pausas y deriva calculados a mano.
- Responde a una orden en menos de 0,2 s.

## Qué cambió al implementarla

- 6.3: el reloj falso cuenta en nanosegundos enteros, porque en coma flotante una orden «a los 30 s» se veía a los 30,2 s. `wait_until` pide una orden en cada vuelta, también a velocidad máxima. Desde la velocidad máxima, el minuto actual es el del último evento liberado.
- 6.3: con el reloj del sistema, un día de `config/` a ×3.600 tardó 24,7 s, con 0,09 ms de retraso final.
- 6.5: los tramos de 0,2 s empiezan en el último evento liberado, y la línea de estado va en una rejilla fija desde el ancla, enganchada a la fuente de órdenes, sin tocar el pacer.
