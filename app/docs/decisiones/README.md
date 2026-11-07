# Registro de decisiones de la app (ADR)

Un ADR (*Architecture Decision Record*) registra el contexto, la decisión, las
alternativas descartadas y sus consecuencias. Explica por qué se eligió una
solución cuando había otras razonables.

Un ADR aceptado no se reescribe. Si cambia la decisión, se escribe otro y se marca
el antiguo como `Sustituida por APP-NNNN`.

## Cuándo escribir uno

Cuando una decisión es difícil de revertir o afecta a varias partes de la app.
Las decisiones candidatas están en [fase-1.md](../specs/fase-1.md#decisiones-candidatas)
y se convierten en ADR en A.8. Si una decisión obliga al núcleo, pertenece a
[su serie de ADR](../../../docs/decisiones/README.md).

## Nombres

`APP-NNNN-titulo-en-minusculas.md`, numerados de forma correlativa:
`APP-0001-interfaz-streamlit-sin-api.md`, `APP-0002-...`.

## Plantilla

```markdown
# APP-NNNN. Título de la decisión

- **Estado:** Propuesta | Aceptada | Sustituida por APP-NNNN
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

## Índice

- [APP-0001. Interfaz Streamlit sin API](APP-0001-interfaz-streamlit-sin-api.md)
- [APP-0002. Paquete de app en un workspace de uv](APP-0002-paquete-app-en-workspace-uv.md)
- [APP-0003. Codex para la fase 1](APP-0003-codex-para-la-fase-1.md)
- [APP-0004. Perfiles de solo lectura en la app](APP-0004-perfiles-de-solo-lectura.md)
- [APP-0005. Simular solo crea ejecuciones clínicas](APP-0005-simular-solo-clinico.md)
