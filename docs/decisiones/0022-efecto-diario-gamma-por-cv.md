# 0022. Sobredispersión con un efecto diario gamma parametrizado por el CV

- **Estado:** Aceptada
- **Fecha:** 2026-10-29

## Contexto

Los recuentos diarios de urgencias varían más de lo que da un Poisson: Whitt y Zhang miden un índice de dispersión de 1,2 a 1,5 con unas 134 urgencias al día ([especificación](../specs/hito-2.md#modelo-de-llegadas)). Un modelo que más adelante intente predecir la demanda necesita saber cuánta de esa variación es ruido.

## Decisión

- Cada día lleva un efecto Z gamma de media 1, con forma k = 1/CV² y escala θ = CV², que multiplica la tasa de todo el día.
- El parámetro es `cv_diario`, 0,06 por defecto; con 0, Z = 1 sin sortear.
- Z sale de su propio flujo aleatorio y se guarda en `DayRecord.day_effect` como *ground truth*.

Motivo: el CV se puede trasladar entre centros, a diferencia del índice de dispersión, y Z queda disponible para validar modelos.

## Alternativas consideradas

- Parametrizar con el índice de dispersión: el índice vale 1 + CV²·μ y crece con el volumen. El 1,2–1,5 medido con 134 urgencias equivale a 2,1 con 300; el mismo CV sirve para centros de cualquier tamaño.

## Consecuencias

- Conocida Z, el día es un Poisson de media Z·e; sin conocerla, el recuento es una binomial negativa de media e y varianza e + (CV·e)².
- La Z de cada día depende solo de la semilla y del CV, no del perfil ni de las candidatas. Activar Z sí cambia las candidatas, porque la cota se multiplica por Z.
- `draw_day_effects(daily_cv, days, seed)` da las Z de un run sin simularlo.
- El arreglo de `SeedSequence.spawn`, que modifica el objeto que recibe, vive en `src/edsim/seeds.py` (`child_streams`); se usa en todo el paquete, también en `simulate_mm1` desde el cierre del hito 2.
- El efecto es independiente de un día a otro; la dependencia entre días consecutivos queda fuera del alcance.
