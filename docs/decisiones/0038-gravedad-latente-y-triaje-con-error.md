# 0038. Gravedad latente y triaje ordinal con ruido y sesgo

- **Estado:** Aceptada
- **Fecha:** 2026-11-07

## Contexto

El modelo provisional del hito 3 sorteaba el nivel de triaje directamente: el nivel era la verdad. En un servicio real, la enfermera clasifica con error, y los estudios publican cuánto: un 10,1 % de infratriaje y un 6,3 % de sobretriaje en la concordancia Manchester de Asturias. El infratriaje es peligroso porque el paciente espera como su nivel asignado y necesita lo de su gravedad real ([especificación, «Gravedad latente y triaje»](../specs/hito-4.md#gravedad-latente-y-triaje)).

## Decisión

- Cada paciente tiene una gravedad real G = media del motivo + ajuste por edad + desviación del motivo × z, normal y oculta, medida en desviaciones de la población de referencia.
- La enfermera clasifica G + ε, con ε = sesgo + ruido × zₑ, cortada por cuatro umbrales: es el nivel asignado. El nivel real es G cortada por los mismos umbrales.
- Los umbrales se derivan una vez para dar el reparto asignado de adultos (0,4 / 12,1 / 33,6 / 52,6 / 1,4 %) y se escriben en el TOML; no se recalculan al cargar. Ruido y sesgo se calibran contra Asturias con `triage_error_for`.
- La prioridad de box y médico usa el nivel asignado; las duraciones y las pruebas, la gravedad real.

Motivo: es el modelo del diseño; reproduce el infra y el sobretriaje publicados; hace medible el daño del infratriaje; un escenario con más gravedad da más niveles urgentes.

## Alternativas consideradas

- Recalcular los umbrales al cargar los perfiles: el reparto volvería siempre al objetivo y un shock desaparecería. Con los umbrales escritos, la disnea ×1,5 sube el nivel 2 asignado del 12,10 % al 13,13 %. Recalcular también rompe perfiles degenerados: con el reparto `[0, 0, 100, 0, 0]`, dos umbrales coinciden y el perfil no carga ([anexo, tarea 4.3](../specs/hito-4.md#tarea-43-gravedad-latente-y-triaje)).
- Un ruido simétrico sin sesgo: daría más sobretriaje que infratriaje, al revés que los datos.
- Duraciones y pruebas con el nivel asignado: el infratriado recibiría lo de su nivel asignado, y el daño del infratriaje desaparecería del modelo. La versión incorrecta V2 de la tarea 4.4 lo comprobó ([anexo, tarea 4.4](../specs/hito-4.md#tarea-44-pruebas-por-tipo-y-duraciones-por-nivel-real-y-motivo)).

## Consecuencias

- Con la mezcla real, ruido 0,334 y sesgo −0,081 dan un 10,10 % de infratriaje y un 6,29 % de sobretriaje; los umbrales son \[3,341; 1,130; −0,047; −2,164\] (tarea 4.6a). El reparto real (0,39 / 12,51 / 35,82 / 50,62 / 0,65 %) es más estrecho que el asignado: el ruido «inventa» niveles 1 y 5.
- G, nivel real, calidad del triaje y salto van al ground truth, nunca al log ni a los KPIs observables.
- El cumplimiento por nivel real mide el coste del infratriaje en tiempo: en el notebook 04 (89 días, reloj C), el nivel 2 cumple en el 94,6 % por nivel asignado y en el 93,3 % por nivel real, con 14 y 21 días fuera ([«Relojes y cumplimiento»](../specs/hito-4.md#relojes-y-cumplimiento)).
- Un desplazamiento y una escala comunes de G no cambian ningún nivel, pero fijan la unidad del ruido y de los odds ratios de las pruebas.
