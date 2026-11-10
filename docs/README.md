# Documentación de EDsim

Desde el 10 de noviembre de 2026, este repositorio es la fuente de verdad de la documentación de EDsim: diseño, especificaciones, anexos, decisiones y diario (decisión candidata 80, tarea de proceso P.2). El documento online donde nacieron el diseño y las especificaciones queda como archivo: no se actualiza, y sus pestañas solo se consultan por los diagramas originales.

- Todo cambio de documentación entra por pull request, como el código.
- La documentación de una tarea (su anexo, sus decisiones, su entrada del diario) va en el mismo PR que su código.

## Dónde vive cada cosa

| Qué | Dónde |
| --- | --- |
| Diseño: visión, modelo, hoja de ruta, metodología y registro de decisiones | [diseno.md](diseno.md) |
| Especificación de cada hito, con su anexo (lo que se hizo en cada tarea) | [specs/](specs/): [hito 0](specs/hito-0.md), [1](specs/hito-1.md), [2](specs/hito-2.md), [3](specs/hito-3.md), [4](specs/hito-4.md), [5](specs/hito-5.md) y [6](specs/hito-6.md) |
| App web: fase 1 e incrementos de cada hito | [app/docs/specs/fase-1.md](../app/docs/specs/fase-1.md) e [incrementos.md](../app/docs/specs/incrementos.md) |
| Decisiones (ADR) del núcleo | [decisiones/](decisiones/README.md) |
| Decisiones (ADR) de la app | [app/docs/decisiones/](../app/docs/decisiones/README.md) |
| Diario de aprendizaje del núcleo y de las tareas de proceso | [diario/](diario/README.md) |
| Diario de la app | [app/docs/diario/](../app/docs/diario/README.md) |
| Instrucciones de los agentes | [AGENTS.md](../AGENTS.md), [CLAUDE.md](../CLAUDE.md) y [app/AGENTS.md](../app/AGENTS.md) |
| Proceso de trabajo | `docs/proceso/`, que llega en los PR siguientes de la P.2 |
| Tareas y estado | [issues de GitHub](https://github.com/pdromer0/edsim/issues) y el tablero del proyecto, desde la P.2 |

## Cómo leer las especificaciones grandes

Las especificaciones de los últimos hitos son largas: no se leen enteras, sino por secciones. Primero los encabezados, con sus números de línea (`grep -n '^#' docs/specs/hito-6.md`), y después solo el rango de líneas de la sección que interesa.

| Fichero | Tamaño aproximado |
| --- | --- |
| [specs/hito-4.md](specs/hito-4.md) | 250 KB |
| [specs/hito-6.md](specs/hito-6.md) | 190 KB |
| [app/docs/specs/fase-1.md](../app/docs/specs/fase-1.md) | 140 KB |
| [specs/hito-3.md](specs/hito-3.md) | 110 KB |
| [specs/hito-5.md](specs/hito-5.md) | 95 KB |
| [diseno.md](diseno.md) | 75 KB |
| [specs/hito-2.md](specs/hito-2.md) | 60 KB |
