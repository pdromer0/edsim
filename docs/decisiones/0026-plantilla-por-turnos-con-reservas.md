# 0026. Plantilla por turnos con reservas de capacidad

- **Estado:** Aceptada
- **Fecha:** 2026-11-03

## Contexto

La plantilla de un servicio de urgencias cambia por turnos, y el dimensionado provisional del hito 3 se hizo por turno con la curva de carga ofrecida ([especificación](../specs/hito-3.md#turnos-calentamiento-y-horizonte)). El evento `staffing_changed` y la plantilla por turno ya están en la v0 del diseño. Pero la capacidad de un `Resource` de SimPy no se puede cambiar una vez creado, y en la realidad el profesional que sale acaba lo que tiene entre manos.

## Decisión

- Tres turnos al día, que empiezan a las 8, 15 y 22 h (configurables), con plantilla de enfermería y de médicos por turno; los boxes no cambian.
- Cada pool se crea con su plantilla máxima. Las plazas que sobran en un turno las ocupan **reservas**: peticiones del motor con prioridad mejor que cualquier paciente y sin desalojo, que esperan a que un profesional termine. Al subir la plantilla se cancelan primero las reservas que esperan y después se liberan las concedidas.
- En el minuto 0 se emite un `staffing_changed` por pool con `anterior` 0; después, solo cuando la plantilla cambia de verdad.

Motivo: la plantilla por turno está en la v0; un `Resource` no cambia de capacidad; y así nadie deja a un paciente a medias.

## Alternativas consideradas

- Cambiar la capacidad del `Resource`: SimPy no lo permite ([anexo, tarea 3.5](../specs/hito-3.md#tarea-35-turnos-y-calentamiento)).
- Reservas que desalojan: interrumpirían una atención en curso, algo que no pasa en un cambio de turno real.
- Plantilla máxima fija todo el día: es lo que esconde la noche. Con 12 médicos fijos, la espera media de médico de noche sería de 0,36 min; con 7, es de 7,15 min, y de 18,4 entre las 22 y las 23 h.

## Consecuencias

- La plantilla vigente cuenta las reservas que aún esperan: a las 22 h ya es 7, aunque 5 reservas esperen a que alguien termine.
- Tras una bajada puede haber más ocupados que la plantilla. La invariante de capacidad comprueba que ninguna atención empieza con el pool ya ocupado al nivel de la plantilla vigente, leída de `staffing_changed`, no de la configuración.
- Liberar una reserva que espera no hace nada y la deja en la cola (una reserva fantasma): la plantilla se quedaría corta sin que ninguna invariante de máximos lo viera. Lo detecta un escenario a mano con el número de ocupados esperado tras una subida.
- Cada cambio de turno es el primer evento de su instante, por construcción: los `timeout` de todos los cambios se crean en el minuto 0.
- La enfermería de triaje pasa a `PriorityResource` para admitir reservas; los pacientes piden todos con la misma prioridad, así que el triaje sigue FIFO (la huella no cambió).
