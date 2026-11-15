# 0084. El simulador del registro clínico: la verdad y lo registrado

- **Estado:** Aceptada
- **Fecha:** 2026-11-13

## Contexto

El diseño preveía una «capa de observación» que metiera defectos en los datos. Hacía falta un nombre que dijera quién se equivoca y que se equivoca a propósito, y que no se confundiera con la admisión ni con los registros de calibración y de decisiones del proyecto ([especificación, pieza 1](../specs/hito-7.md#pieza-1--el-simulador-del-registro-clínico)).

## Decisión

- La pieza que mete los despistes se llama **simulador del registro clínico** («el registro clínico»), en el paquete `edsim.clinical_record`.
- Sus datos son **lo registrado**, frente a **la verdad** que escribe el motor. Un **registro** es cada fila de lo registrado.
- Sustituye a «capa de observación» en el diseño. El nombre lo eligió Pedro.

## Alternativas consideradas

- **«Capa de observación»**, el nombre del diseño: dice que algo mira, no que alguien teclea. Tendría sentido si la pieza modelara sensores pasivos (horas tomadas sin intervención humana) en lugar de personal anotando.
- **«Registro» a secas:** choca con el registro de calibración, el registro de decisiones y la admisión («la registran»).

## Consecuencias

- La documentación habla de «la verdad» y «lo registrado», también en el notebook 07 y en la CLI (`edsim registro …`).
- El código usa el nombre en inglés (`clinical_record`, `Record`), como manda la convención de idiomas (ADR 0015).
- La [ADR 0006](0006-log-de-eventos-y-ground-truth.md), que nombraba la «capa de observación», lleva una nota de actualización con el nombre nuevo.

## Qué cambió al implementarla

- **7.1:** `edsim.clinical_record.record` es la función, no el módulo: el paquete exporta `record` con el nombre de su módulo, y quien necesite el módulo usa `importlib.import_module`.
- **7.7:** el diseño cambia «capa de observación» por «simulador del registro clínico» en el diagrama del motor, el modelo de datos y la sección que la describía.
