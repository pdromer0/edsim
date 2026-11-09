# 0061. Horizonte finito y un `fin` que dice por qué terminó

- **Estado:** Aceptada
- **Fecha:** 2026-11-06

## Contexto

Un directo puede acabar por llegar al horizonte, por una orden, por Ctrl+C o por un mensaje que no se entrega. El consumidor tiene que saber cuál, y cuántos eventos esperar ([especificación, «Mensajes de ed.runs»](../specs/hito-6.md#mensajes-de-edruns)).

## Decisión

Horizonte finito (`--dias`). Al llegar, con `parar` o con Ctrl+C, el directo publica el mensaje `fin` en `ed.runs`, con el motivo (`horizonte`, `parar`, `interrupcion` o `error`), el minuto, el último `event_id` y los publicados, y hace `flush`.

## Alternativas consideradas

- Un directo sin horizonte: no terminaría limpio, y «directo = batch» no tendría con qué compararse.

## Consecuencias

- El consumidor sabe cuándo ha terminado: cuando ha visto el `fin` y tantos eventos distintos como dice.

## Qué cambió al implementarla

- 6.3: con Ctrl+C, un solo `fin` (durante el censo, con `sim_time` = W) y la interrupción sigue.
- 6.4: el `SinkError` de `end` sale de `run_live` también tras Ctrl+C, con la interrupción como contexto: una ejecución incompleta importa más que cómo se paró.
- 6.5: códigos de salida 0 (`horizonte` o `parar`), 130 (Ctrl+C, tras publicar el `fin`), 1 (sumidero que falla, topics, extra o broker) y 2 (errores de uso, antes de conectar).
- 6.6: el `fin` puede leerse antes que los últimos eventos, porque va en otro topic; la lectura espera a los publicados (V2 de la 6.6). El resumen de librdkafka se imprime al final también tras Ctrl+C o un error.
