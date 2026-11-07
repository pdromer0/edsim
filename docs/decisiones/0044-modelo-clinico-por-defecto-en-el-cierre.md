# 0044. Modelo clínico opcional durante el hito y por defecto en el cierre

- **Estado:** Aceptada
- **Fecha:** 2026-11-07

## Contexto

El modelo clínico se construyó en el núcleo tarea a tarea (4.2 a 4.6), y la app solo trabajó con él desde las tareas 4.8a a 4.8c. Durante el hito, `main` tenía que seguir estable, con el job `tests-app` obligatorio en el CI. Por otro lado, la validación del motor (M/G/1, el escenario de tres boxes) necesita un modelo sencillo con teoría conocida ([especificación, «Modelo opcional durante el hito»](../specs/hito-4.md#el-muestreador-clínico-en-el-motor)).

## Decisión

**Durante el hito.** `simulate_ed(..., profiles=...)` y, desde la tarea 4.5b, la CLI aceptan unos perfiles. Con ellos usan el `ClinicalSampler` y un log clínico; sin ellos (`profiles=None`), el `ProvisionalSampler` del hito 3, exactamente como antes.

**En el cierre (tarea 4.9), forma final:**

- `edsim motor simular` sin opciones simula el modelo clínico con `config/perfiles.toml`: copia, huella y catálogo versión 3, como con `--perfiles`.
- `--provisional` pide el modelo provisional y es incompatible con `--perfiles` (error de argparse). Necesita un centro con el bloque provisional ([ADR 0036](0036-perfiles-clinicos-aparte-del-centro.md)), como `tests/data/centro_ejemplo.toml`; con uno sin él, termina con código 2 y un mensaje en español que nombra las tres tablas, antes de escribir nada.
- `edsim motor validar` sigue con el modelo provisional, y su `--centro` por defecto pasa a ser `tests/data/centro_ejemplo.toml`, porque `config/centro.toml` ya no tiene el bloque.
- `simulate_ed` y `simulate_run` no cambian de firma: los perfiles se pasan de forma explícita y `None` sigue siendo el provisional. La app pasa siempre los perfiles y solo crea ejecuciones clínicas ([APP-0005](../../app/docs/decisiones/APP-0005-simular-solo-clinico.md)).
- El cumplimiento de `runs/` usa el reloj C por defecto ([ADR 0040](0040-tres-relojes-y-cumplimiento-desde-la-clasificacion.md)).

El `ProvisionalSampler` se queda para la validación del motor y para quien lo pida con su centro.

Motivo: `main` estable y `tests-app` obligatorio en todo el hito; la app no se rompe a mitad de camino.

## Alternativas consideradas

- Hacer el clínico el modelo por defecto en cuanto llegó al motor (tarea 4.5a): la app y `runs/` seguían usando el provisional, y `tests-app` se habría roto a mitad del hito.
- Dar a `simulate_ed` y `simulate_run` unos perfiles por defecto (`config/perfiles.toml`): el núcleo dependería de una ruta del repositorio, y cada llamada sin perfiles cambiaría de modelo sin decirlo. Con los perfiles explícitos, el modelo de cada llamada se ve en el código, y los tests y la validación del motor que llaman sin perfiles siguen dando las mismas huellas.
- Retirar el `ProvisionalSampler`: la validación del motor perdería su modelo con teoría conocida.
- Mantener `config/centro.toml` como centro por defecto de `motor validar`: sin el bloque provisional, `edsim motor validar` sin opciones terminaría con un error de uso.

## Consecuencias

- Ninguna huella cambia: la caracterización del provisional pasa `--provisional --centro tests/data/centro_ejemplo.toml` y da las de siempre. `edsim motor simular` sin opciones en la tarea 4.9 da el mismo log, byte a byte, que `--perfiles config/perfiles.toml` en `main` antes del cierre.
- La [ADR 0030](0030-validacion-del-motor-por-niveles.md) dice que `validate_engine` se valida con `config/centro.toml`: desde la tarea 4.9 es `tests/data/centro_ejemplo.toml`, el centro del provisional (la misma plantilla del hito 3).
- Las ejecuciones provisionales guardadas se siguen abriendo y reproduciendo: sus copias de `centro.toml` tienen el bloque.
