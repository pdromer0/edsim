# 0023. Validación de las llegadas con cinco pruebas al nivel 0,01

- **Estado:** Aceptada
- **Fecha:** 2026-10-29

## Contexto

Las llegadas no tienen una fórmula cerrada con la que compararse, como la M/M/1 del hito 1. Hay que comprobar que son un Poisson no homogéneo con la λ(t) configurada, y cada tipo de error (escala, forma, huecos, dispersión) se ve con una herramienta distinta ([especificación](../specs/hito-2.md#validación-estadística)).

## Decisión

- Cinco pruebas: a. volumen, b. chi-cuadrado horario, c. Kolmogórov–Smirnov de los huecos reescalados, d. dispersión de Pearson con réplicas y e. uniformidad de los p-valores.
- Todas al nivel 0,01. Bonferroni dentro de a (8 intervalos: total y cada día de la semana) y dentro de d (Pearson sin Z y condicional, cada uno al 99,5 %); los dos Pearson cuentan para decidir.
- La hipótesis sale del perfil contra el que se valida. De los registros solo se toman los hechos y Z, que es *ground truth*.
- Pruebas de potencia: base 330 frente a 300, perfil desplazado una hora y CV ignorado.

Motivo: cada prueba busca un error distinto, el nivel limita las falsas alarmas al combinarlas, y sin una hipótesis independiente no hay potencia.

## Alternativas consideradas

- Nivel 0,05: un generador correcto daría alguna falsa alarma en el 23 % de las validaciones (1 − 0,95⁵); al 0,01, en el 5 %.
- Pearson condicional solo informativo: es el que distingue un error en Z de un error en el Poisson de cada día.
- Tomar lo esperado de `DayRecord.expected`: lo escribió el generador con su propio perfil, así que la prueba compararía el generador consigo mismo y ninguna prueba de potencia podría fallar. Un test lo impide.

## Consecuencias

- Cada prueba está ciega a algo: b no ve el volumen porque reescala al total, c no ve la sobredispersión y el Pearson condicional pasa con el CV mal especificado. Solo el conjunto cubre los errores importantes.
- Un error pequeño y localizado, como C′ (la medianoche), tiene una potencia de alrededor del 13 % en b (12 % medido en 50 semillas). Para esos errores hacen falta tests de regresión, como la huella de las llegadas.
- `validate_arrivals(..., hypothesis=...)` genera con un perfil y valida contra otro, para la tabla de potencia del notebook.
- Las pruebas largas se marcan `slow` ([ADR 0017](0017-tests-estadisticos-marcados-slow.md)) y la semilla fija no se cambia si una falla.
