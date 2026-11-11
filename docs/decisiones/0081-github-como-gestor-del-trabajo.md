# 0081. GitHub como gestor del trabajo: issues, milestones, tablero y dependencias nativas

- **Estado:** Aceptada
- **Fecha:** 2026-11-11

## Contexto

Hasta la P.2 el trabajo vivía en la especificación de cada hito (una tabla de tareas) y en un prompt largo que se pegaba al agente en cada tarea. El estado de cada tarea se actualizaba a mano, las dependencias estaban en prosa y lo que se decidía en el chat se perdía si no se copiaba al prompt siguiente. Con el repositorio ya como fuente de verdad de la documentación ([ADR 0080](0080-repositorio-fuente-de-verdad-de-la-documentacion.md)), faltaba lo mismo para el estado del trabajo.

## Decisión

El trabajo vive en GitHub ([flujo.md](../proceso/flujo.md)):

- **Un issue por tarea**, con la plantilla «Tarea» (objetivo, contenido, criterios, enlace a la especificación, rama, quién, si es crítica y de qué depende). El PR lo cierra con «Closes #N».
- **Etiquetas** en tres grupos con prefijo (`tipo:`, `area:`, `quien:`) más `critica`.
- **Milestones**: uno por hito y uno por tarea de proceso con nombre (P.2, P.3), más un Backlog.
- **Tablero «EDsim»** con cinco columnas (Backlog, Próximo, En curso, En revisión, Hecho). El añadido automático y el workflow «Pull request linked to issue» mueven las fichas; la skill solo corrige lo que falte.
- **Dependencias nativas** (*blocked-by*). Manda la nativa; la sección «Depende de» del cuerpo guarda el motivo. Si no coinciden, se avisa del descuadre.
- **Las notas del chat duraderas van como comentario «Notas del chat»** del issue; el argumento de la skill queda para lo efímero de la sesión.
- Las decisiones se citan «decisión 69 (H5-3)», sin almohadilla, para no confundirlas con los issues.

## Alternativas consideradas

- Seguir con la tabla de tareas de la especificación y el prompt por tarea: el estado se actualiza a mano y el prompt se desfasa.
- Un tablero sin issues (solo tarjetas): sin dependencias nativas ni cierre automático desde el PR.
- Dependencias solo en el cuerpo del issue: ningún agente puede consultarlas con una orden ni se pueden comprobar.

## Consecuencias

- El estado se actualiza solo, junto al código: el PR enlazado lleva la ficha a «En revisión» y la fusión la cierra.
- 32 issues (#63 a #94) en cuatro milestones y 15 dependencias en 9 issues al cerrar la A4.
- Las automatizaciones compiten con los scripts: el añadido automático llegó antes que `gh project item-add` («Content already exists»). Los id del tablero se leen en cada uso, nunca de memoria, y la skill comprueba el estado antes de actuar.
- Una dependencia prevista pudo perderse al crear el issue (el #66 perdió la del #64); la prueba en seco del flujo lo destapó. Por eso la prueba en seco va antes del primer uso real.
- Si una nota del chat contradice a otra, manda la más reciente.
