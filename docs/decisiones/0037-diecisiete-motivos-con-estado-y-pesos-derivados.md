# 0037. Los 17 motivos desde el principio, cada valor con su estado y pesos base derivados

- **Estado:** Aceptada
- **Fecha:** 2026-11-07

## Contexto

El catálogo del diseño tiene 17 motivos de consulta con un peso aproximado y una gravedad típica. No hay una fuente española pública con el reparto de diagramas de Manchester, así que muchos números son juicio clínico. Además, el «peso aprox.» del catálogo es un reparto global: el reparto que sale de la mezcla es la media de los contextos ponderada por las llegadas, no el peso de un contexto de referencia ([especificación, «Motivos de consulta»](../specs/hito-4.md#motivos-de-consulta)).

## Decisión

- Los 17 motivos existen desde la tarea 4.2, cada uno como un perfil de `config/perfiles.toml`.
- El peso de un motivo es `peso_base × f_edad × f_franja × f_dia × f_estacion`, renormalizado; un factor solo se escribe si hay una razón clínica, al lado en un comentario.
- Cada valor lleva su estado: calibrado (ajustado a un objetivo público con horquilla), derivado (lo calcula el código) u orientativo (juicio clínico razonado).
- Los pesos base se derivan con `base_weights_for` para que el reparto global de un año coincida con el catálogo, se escriben en el TOML con el comando en un comentario y un test comprueba que siguen siendo los recalculados.

Motivo: no hay fuente pública por motivo; el estado dice qué respaldo tiene cada número; los shocks no se renormalizan.

## Alternativas consideradas

- Usar el reparto del catálogo como peso base: el reparto global no saldría el del catálogo. Sin derivar los pesos, la intoxicación saldría en un 2,99 % en lugar del 2,01 % ([anexo, tarea 4.2](../specs/hito-4.md#tarea-42-perfiles-contexto-población-y-motivo)).
- Recalcular los pesos al cargar para mantener el reparto global: un shock como «disnea ×1,5» se renormalizaría de vuelta y desaparecería. El peso base es el punto fijo y los factores mandan.
- Sumar los factores en lugar de multiplicarlos: un factor multiplica, no suma puntos. La versión incorrecta V1 de la tarea 4.2 (factores sumados) rompió el ejemplo a mano y «escritos = recalculados».

## Consecuencias

- `base_weights_for` converge en 9 vueltas, y los pesos escritos dejan el reparto global a 0,00065 puntos del catálogo como máximo; un test exige ±0,5 puntos y otro, «escritos = recalculados» a 1e-3 ([anexo, tarea 4.2](../specs/hito-4.md#tarea-42-perfiles-contexto-población-y-motivo)).
- El orden clínico de gravedad del catálogo se convierte en una comprobación: la gravedad media de los motivos debe respetarlo ([ADR 0038](0038-gravedad-latente-y-triaje-con-error.md)).
- Desde la tarea 4.6a, los derivados se rederivan en cascada (`derive_written_values`: pesos base, ruido y sesgo, umbrales), y un test comprueba que la cascada entera reproduce el fichero ([ADR 0046](0046-parada-a-la-puerta.md)).
