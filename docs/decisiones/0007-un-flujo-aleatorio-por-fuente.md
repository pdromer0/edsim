# 0007. Un flujo aleatorio por fuente de azar

- **Estado:** Aceptada
- **Fecha:** 2026-10-27

## Contexto

Un experimento compara variantes de un escenario, cada una con N réplicas emparejadas por semilla, mediante intervalos de confianza sobre las diferencias ([diseño](../diseno.md#diseño-de-experimentos)).

## Decisión

Llegadas, motivos, tiempos y paciencia tienen flujos aleatorios independientes, derivados de la semilla con `SeedSequence` de NumPy.

Motivo: poder usar números aleatorios comunes en los experimentos.

## Alternativas consideradas

No se documentaron alternativas.

## Consecuencias

- Las comparaciones entre variantes son emparejadas.
- Es la base de los tests de regresión con semilla fija.
