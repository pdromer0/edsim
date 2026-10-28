# 0009. Librerías directamente, sin reimplementar fundamentos

- **Estado:** Aceptada
- **Fecha:** 2026-10-27

## Contexto

Uno de los objetivos del proyecto es aprender los fundamentos: simulación, estadística, ingeniería de datos y desarrollo con IA ([diseño](../diseno.md#visión-y-objetivos)).

## Decisión

Se usan las librerías directamente, sin reimplementar los fundamentos a mano. Los conceptos se explican en la sesión conceptual y se profundiza bajo demanda.

Motivo: es el modo de aprendizaje elegido.

## Alternativas consideradas

- Reimplementar los fundamentos a mano: descartado en la [metodología](../diseno.md#metodología-de-trabajo-con-claude-code-y-cursor).

## Consecuencias

- El stack se apoya en piezas estándar (SimPy, NumPy/SciPy, Pydantic, FastAPI…), que se introducen de una en una a lo largo de los hitos.
- Lo aprendido se comprueba validando contra la teoría; por ejemplo, la cola M/M/1 y la ley de Little en el hito 1.
