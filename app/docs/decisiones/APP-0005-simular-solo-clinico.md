# APP-0005. Simular solo crea ejecuciones clínicas

- **Estado:** Aceptada
- **Fecha:** 2026-11-07

## Contexto

La 4.8b dejó la opción Provisional en Simular. El cierre del hito 4 hace del
clínico el modelo por defecto del núcleo y retira de `centro.toml` las secciones
`[triaje]`, `[duraciones]` y `[pruebas]`. El provisional se conserva para validar
el motor, como establece la decisión 44 del [hito 4](../../../docs/specs/hito-4.md).

## Decisión

Simular solo crea ejecuciones clínicas. La tarea 4.8c prepara la app antes de la
separación de configuración de la 4.9.

## Alternativas consideradas

- Mantener la opción con un centro que conserve las secciones provisionales:
  prolonga en la app un modelo que queda para la validación del motor.
- Adaptar la app dentro de la 4.9 con una excepción de zonas: mezcla el cierre
  del núcleo con los cambios y las pruebas de las páginas.

## Consecuencias

Desaparece el selector de modelo. Los perfiles siguen siendo seleccionables y
de solo lectura; el editor del centro muestra turnos, plantilla, boxes y destino.
Las variantes conservan las claves que la app no edita.

Las ejecuciones provisionales existentes se siguen abriendo en Ejecuciones,
Resultados, Episodios, Comparar y Replay. Los tests de Simular pasan al clínico;
un test con un centro sin las tres secciones queda como `xfail` estricto hasta
que la 4.9 haga opcionales sus campos en el núcleo.

El alcance está en la [preparación del cierre](../specs/incrementos.md#preparación-del-cierre-tarea-48c-codex).
