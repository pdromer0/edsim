# Registro de decisiones (ADR)

Un ADR (*Architecture Decision Record*) es un documento corto que registra una decisión importante: el contexto en que se tomó, qué se decidió, qué alternativas se descartaron y qué consecuencias tiene. Sirve para que, meses después, se entienda por qué el sistema es como es.

Un ADR aceptado no se reescribe. Si la decisión cambia, se escribe un ADR nuevo que la sustituye y se marca el antiguo como `Sustituida por NNNN`.

## Cuándo escribir uno

Cuando una decisión es difícil de revertir, afecta a varias partes del sistema o hubo alternativas razonables. Las decisiones del brainstorming están en [diseno.md](../diseno.md#registro-de-decisiones-y-preguntas-abiertas) y se convierten en ADRs al cerrar el hito 0.

## Nombres

`NNNN-titulo-en-minusculas.md`, numerados de forma correlativa: `0001-simpy-como-motor.md`, `0002-...`.

## Plantilla

```markdown
# NNNN. Título de la decisión

- **Estado:** Propuesta | Aceptada | Sustituida por NNNN
- **Fecha:** AAAA-MM-DD

## Contexto

Qué problema hay que resolver y qué restricciones existen.

## Decisión

Qué se decide, en una o dos frases.

## Alternativas consideradas

- Alternativa A: por qué no.
- Alternativa B: por qué no.

## Consecuencias

Qué se gana, qué se pierde y qué queda pendiente.
```
