# 0078. La app enseña el hito 5 entero

- **Estado:** Aceptada
- **Fecha:** 2026-11-10

## Contexto

EDsim Lab crece con cada hito: una tarea de núcleo en `edsim.runs` y otra de páginas (decisión 31). El hito 4 dejó cinco pendientes pequeños en la app ([incrementos](../../app/docs/specs/incrementos.md#hito-5--abandono-destinos-y-espera-de-cama)).

## Decisión

- La app enseña el hito 5 entero:
  - estados, filtros e indicadores, con la censura del abandono;
  - «Ver la verdad» con el desenlace sorteado y los indicadores de nivel real, siempre aparte de los KPI observables;
  - la espera de cama editable en Simular.
- La misma tarea resuelve los cinco pendientes del hito 4.
- El núcleo de la app (5.4) lo hace Claude Code, y las páginas (5.5), Codex.
- El rendimiento de la app y la edición de perfiles quedan fuera.

## Alternativas consideradas

- **Una tarea con el rendimiento o la edición de perfiles:** una tarea con dos temas se revisa peor.
- **Solo el núcleo, sin páginas:** el modelo no se vería en la app hasta otro hito.

## Consecuencias

- Todo lo del hito 5 aparece solo con un log de la versión 4: con el hito 4, las páginas son las de antes.
- La app va antes de la calibración: el modelo nuevo no pasa a ser el de por defecto hasta que la app lo soporta (decisión 44).

## Qué cambió al implementarla

- **Las páginas las hizo Claude Code, no Codex** (decisión de Pedro del 12 de noviembre). Codex siguió en el hito con `@codex review` en la 5.6.
- **5.5:** `app-v0.3.0`, sobre la fusión de la 5.5 (`f3cca25`). Los cinco pendientes del hito 4 quedaron cerrados.
- **5.5:** `patient_model` devuelve el enum `PatientModel`, no un `Literal` en español, y la app no vuelve a filtrar lo que trae el núcleo (ajustes de Pedro al plan).
- **5.5, fuera:** la carga prevista del modelo del hito 5 (#103). Simular lo avisa y sigue funcionando.
- **5.8:**
  - la columna «Modelo» de Ejecuciones distingue el hito 4 del 5 por la versión del catálogo;
  - Replay tiene una sola ayuda;
  - el manual gana «Primeros pasos con el hito 5».
