# 0006. Log de eventos como fuente de verdad y ground truth separado

- **Estado:** Aceptada
- **Fecha:** 2026-10-27

## Contexto

Dos principios del diseño: el log de eventos es la fuente de verdad, y la verdad oculta va separada de los datos observados. Hay que poder reconstruir qué se sabía en cada instante y evitar el *data leakage* ([diseño](../diseno.md#principios-de-diseño)).

## Decisión

El log de eventos es la única salida del motor. Los eventos son inmutables y los estados se derivan de ellos. El ground truth se guarda aparte, con una fila por episodio: gravedad latente, paciencia, calidad del triaje, tiempos reales, causa del abandono y defectos inyectados.

Motivo: docencia, modelos de ML sin leakage y validación.

## Alternativas consideradas

No se documentaron alternativas.

## Consecuencias

- Todos los eventos comparten un sobre común y llevan tres tiempos: `event_time`, `recorded_time` e `ingest_time`. Con ellos se construyen features "a fecha de".
- La capa de observación se deriva del log e inyecta defectos configurables, con tres perfiles: limpio, realista y hostil.
- El modo replay puede re-emitir una ejecución guardada de forma determinista.
