# APP-0004. Perfiles de solo lectura en la app

- **Estado:** Aceptada
- **Fecha:** 2026-11-05

## Contexto

El incremento del hito 4 permite elegir perfiles clínicos y consultar su resumen.
Editar los 17 motivos con validación en vivo es una tarea grande, que encaja con
la fase 2. La decisión figuraba como APP-0003 en la especificación, pero ese número
ya correspondía a «Codex para la fase 1»; su número definitivo es APP-0004.

## Decisión

Los perfiles se eligen y se consultan en la app, pero no se editan. El editor de
perfiles queda para la fase 2.

## Alternativas consideradas

- Editor en la app: añade formularios y validación en vivo para 17 motivos y
  amplía demasiado el incremento del hito 4.

## Consecuencias

Simular permite elegir la ruta del fichero y muestra su huella y su resumen de
solo lectura. Para cambiar los perfiles hay que editar el TOML fuera de la app;
la app valida el fichero al cargarlo. Las ejecuciones clínicas conservan una
copia de sus perfiles y su huella.

La implementación está en el [PR #53](https://github.com/pdromer0/edsim/pull/53)
y la decisión, en la [especificación de incrementos](../specs/incrementos.md#decisiones).
