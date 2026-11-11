# 0080. El repositorio es la fuente de verdad de la documentación

- **Estado:** Aceptada
- **Fecha:** 2026-11-11

## Contexto

El diseño, las especificaciones de los hitos, sus anexos y el diario nacieron en un documento online de diez pestañas, mantenido por el chat y copiado a mano al repositorio. Había dos copias que podían divergir, y el agente que implementa una tarea no podía escribir en la del documento online: cada anexo se redactaba en un sitio y se pegaba en otro. Al empezar la P.2, el chat exportó las pestañas y las comparó con el repositorio: eran idénticas el diseño, los hitos 1 a 4 e incrementos; faltaban en el repositorio el anexo del hito 0, el anexo de la 6.6 y el cierre del hito 6, y el hito 5 solo existía online ([anexo de la P.2, tarea A1](../proceso/p2.md)).

## Decisión

Desde el 10 de noviembre de 2026 el repositorio es la fuente de verdad de la documentación: diseño, especificaciones, anexos, decisiones y diario. Todo cambio entra por pull request, en el mismo PR que el código que lo motiva. Las pestañas del documento online quedan como archivo, con una nota que enlaza al fichero en `main`, y no se editan.

## Alternativas consideradas

- Seguir con el documento online como fuente y exportarlo al repositorio al cerrar cada tarea: obliga a exportar y comparar cada vez, y el agente sigue sin poder escribir en él.
- Mantener las dos copias sincronizadas: la sincronización es la tarea que falla sin que nadie lo vea.
- Dejar solo el diseño en el repositorio y las especificaciones online: parte los anexos de las tareas de su código.

## Consecuencias

- Una sola copia que los agentes escriben y los PR revisan. No hay nada que exportar ni comparar.
- La migración se hizo con un diff normalizado (sin firma, cabecera, diagramas ni escapes): 0 diferencias en el hito 0, el hito 5, la fase 1 e incrementos; en el diseño, solo la decisión 80; en el hito 6, solo los enlaces a las ADR.
- Los diagramas pasan a Mermaid, que se versiona y se revisa como texto.
- Las especificaciones de los últimos hitos son grandes (hasta 250 KB): se leen por secciones ([docs/README.md](../README.md)) y los ficheros grandes los escribe un script, no el modelo.
- Nada del documento online se edita ya: si una pestaña y el repositorio difieren, vale el repositorio.
