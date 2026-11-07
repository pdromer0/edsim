# 0036. Perfiles clínicos en `config/perfiles.toml`, aparte del centro

- **Estado:** Aceptada
- **Fecha:** 2026-11-07

## Contexto

El hito 4 describe a cada paciente con decenas de parámetros: población, 17 motivos con sus factores, gravedad, triaje, pruebas y duraciones. El hito 3 tenía su modelo clínico provisional dentro de `config/centro.toml` (`[triaje]`, `[duraciones]` y `[pruebas]`). Pero el hospital (turnos, plantilla, boxes) y la población que llega son preguntas distintas, y la v3 quiere perfiles de centro intercambiables ([especificación, «Ficheros de configuración»](../specs/hito-4.md#ficheros-de-configuración)).

## Decisión

- `config/perfiles.toml` describe a los pacientes y `centro.toml`, el hospital.
- Los perfiles llevan una tabla por motivo, unidades clínicas (porcentajes, minutos, factores, odds ratios), factores opcionales que valen 1 si faltan, claves desconocidas prohibidas y franjas propias, independientes de los turnos. El código calcula los pesos normalizados, los interceptos y μ y σ: ningún número derivado se escribe a mano.
- En el cierre (tarea 4.9), `centro.toml` pierde `[triaje]`, `[duraciones]` y `[pruebas]`, y conserva `[destino]` hasta el hito 5. Esas tres tablas forman el bloque provisional del centro: las tres o ninguna. Con el bloque, el centro se lee como siempre; sin él, sus seis campos valen `None`; con una parte, es un error que nombra cada clave que falta. `tests/data/centro_ejemplo.toml` es el centro del modelo provisional.

Motivo: hospital y población son preguntas distintas; perfiles intercambiables en la v3; nada derivado a mano.

## Alternativas consideradas

- Ampliar `centro.toml` con los perfiles: mezclaría hospital y población, y cambiar de población obligaría a copiar el hospital.
- Usar los turnos del centro como franjas del contexto: mover un cambio de turno movería a los pacientes. La versión incorrecta V5b de la tarea 4.2 (franjas de `centro.toml`) hizo fallar los tests de franjas `[7, 14, 21]` y `[0, 12, 23]` ([anexo, tarea 4.2](../specs/hito-4.md#tarea-42-perfiles-contexto-población-y-motivo)).
- Al quitar el bloque provisional (tarea 4.9), darle valores por defecto escondidos: un centro sin bloque simularía el provisional con valores que nadie escribió. Se descartó también renombrar o mover `centro_ejemplo.toml`: sus bytes están en las huellas de los CSV provisionales.

## Consecuencias

- `perfiles validar` prueba el muestreador sin el motor, y una ejecución clínica guarda la copia de `perfiles.toml` y su huella ([nota de la ADR 0032](0032-ejecuciones-en-carpetas-reproducibles.md)).
- La app muestra y elige los perfiles, pero no los edita ([APP-0004](../../app/docs/decisiones/APP-0004-perfiles-de-solo-lectura.md)).
- Las copias de `centro.toml` de las ejecuciones guardadas, las variantes y `tests/data/centro_ejemplo.toml` se leen exactamente como antes del cierre. `write_variant` no añade ni quita claves de su base, tampoco las del bloque.
- El modelo provisional exige el bloque y falla pronto, antes de escribir nada, con un mensaje que nombra las tres tablas. Con el modelo clínico, el bloque no cambia ningún sorteo: dos ejecuciones iguales salvo el bloque dan el mismo log y se emparejan como «plantilla».
