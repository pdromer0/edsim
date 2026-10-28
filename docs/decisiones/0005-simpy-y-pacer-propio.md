# 0005. Simulación de eventos discretos con SimPy y pacer propio

- **Estado:** Aceptada
- **Fecha:** 2026-10-27

## Contexto

El principio "un solo motor, varios modos de reloj" pide que el mismo núcleo corra en modo directo (tiempo real o acelerado) y en modo batch (máxima velocidad, muchas réplicas) ([diseño](../diseno.md#motor-de-simulación-y-reloj)).

## Decisión

El motor es una simulación de eventos discretos con SimPy que corre siempre en tiempo virtual (minutos). Cada paciente es un proceso, y los pools son recursos con prioridad. Un marcapasos (pacer) propio convierte el tiempo virtual en tiempo real cuando hace falta.

Motivo: poder ajustar la velocidad en caliente.

## Alternativas consideradas

- Salabim, como librería de simulación (tabla del stack).

## Consecuencias

- El pacer permite cambiar la velocidad (×1, ×10, ×60), pausar y anclar el reloj al calendario real.
- Hay tres modos de uso: directo (con pacer), batch (sin pacer, réplicas en paralelo) y replay.
- Una API FastAPI controla pausa, velocidad, plantilla y shocks, y cada orden queda registrada como evento.
- SimPy se introduce en el hito 1 y el pacer en el hito 6.
