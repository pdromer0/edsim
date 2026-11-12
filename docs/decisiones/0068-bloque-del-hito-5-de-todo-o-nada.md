# 0068. El modelo del hito 5 lo elige un bloque de todo o nada en los ficheros

- **Estado:** Aceptada
- **Fecha:** 2026-11-10

## Contexto

El hito 5 añade abandono, destinos y espera de cama sobre el modelo clínico del hito 4. Con el modelo del hito 4 ya hay tres cosas escritas: las huellas SHA-256 de los tests, las ejecuciones guardadas en `resultados/ejecuciones/` (con sus copias de `centro.toml` y `perfiles.toml`) y las variantes de la app en `resultados/variantes/`. Si lo nuevo cambiara el significado de esos ficheros, las tres dejarían de valer ([pieza 6](../specs/hito-5.md#pieza-6--versiones-de-un-modelo)).

## Decisión

- Un bloque del hito 5 de todo o nada en dos ficheros: `[abandono]`, `[destinos]` e `ingreso` en los 17 motivos de `perfiles.toml`, y `[camas]` en lugar de `[destino]` en `centro.toml`.
- **Con el bloque**, el modelo del hito 5, que escribe la versión 4 del catálogo y usa `child_streams(seed, 10)`. **Sin él**, el modelo clínico del hito 4 byte a byte (versión 3).
- Un bloque a medias, o perfiles del hito 5 con un centro del hito 4, es un error que dice qué falta y en qué fichero.

## Alternativas consideradas

- **Una opción de la CLI o un campo `modelo` en el centro:** el modelo dependería de cómo se lanza y no de los ficheros, y una ejecución guardada no se reproduciría con sus copias.
- **Valores por defecto para lo que falte:** un fichero del hito 4 se leería como del hito 5 con parámetros inventados, y las huellas cambiarían.

## Consecuencias

- Es la tercera vez que se aplica la regla «escribir lo nuevo y leer lo antiguo con su significado», después de `espera_resultados_fuera` y del bloque provisional (tarea 4.9).
- Los flujos 0 a 7 no cambian ni un bit al pasar al hito 5: cada hijo de `child_streams` depende solo de su índice.
- El motor tiene una rama explícita por modelo, como ya la tenía para el provisional.

## Qué cambió al implementarla

- **5.2:** los perfiles del hito 5 de ejemplo (`tests/data/perfiles_h5_ejemplo.toml`) se crearon ya en la 5.2, para que el test «escritos = recalculados» tuviera dónde vivir.
- **5.5:** `patient_model` expone la elección a la app como el enum `PatientModel`. Simular lo pregunta antes de calcular la carga prevista.
- **5.6:** antes de poner los bloques en `config/`, los ficheros del hito 4 se congelaron en `tests/data/` (`centro_h4.toml`, `centro_cumplidor_h4.toml`, `perfiles_h4.toml` y `objetivos_h4.toml`), iguales byte a byte. Los lectores que afirman el significado del hito 4 pasaron a esas copias: el diff demuestra que ninguna huella ni cifra del hito 4 cambia. Desde entonces, `config/` es el modelo del hito 5.
