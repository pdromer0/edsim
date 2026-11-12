# 0077. «Esperando cama», con una marca de pasillo, y el abandono contado aparte

- **Estado:** Aceptada
- **Fecha:** 2026-11-10

## Contexto

El consumidor del directo y el Replay de la app derivan del log dónde está cada paciente. Con el hito 5 hay dos situaciones nuevas:

- un ingresado que espera cama, en su box o en el pasillo tras un desalojo;
- un paciente que se va sin ser visto, que no es una salida ([especificación, «Decisiones del hito»](../specs/hito-5.md#decisiones-del-hito), H5-11).

## Decisión

- **Un estado nuevo, «esperando cama»**, con una marca «en el pasillo».
- **El abandono** es un cierre contado aparte de las salidas.

## Alternativas consideradas

- **Una zona «pasillo» con su propio estado:** el estado tendría que decir a la vez qué hace el paciente y dónde está. Es la misma elección que la sala de resultados (4.8a): el estado dice qué hace y la marca, dónde está.
- **El abandono como una salida más:** escondería el indicador de calidad que vigila todo servicio de urgencias.

## Consecuencias

- El Replay enseña «Esperando cama» en el box, el pasillo y, en la última hora, los que se van sin ser vistos.
- Los boxes bloqueados por ingresados y el pasillo son dos curvas nuevas.

## Qué cambió al implementarla

- **5.4:** las curvas de la cama van fuera de `CURVES`, para que sus lectores (`WindowMetrics`, `ReplayCounts`, la app) sigan igual con los logs antiguos. `ReplayCounts` gana `boxes_waiting_bed` y `hallway` con valor por defecto.
- **5.4:** el notebook 06, otro lector de las ubicaciones, emparejaba siete colores con ellas. La primera N3 lo vio, y ahora tiene «espera cama».
- **5.5:** las curvas de la cama, en `curve_blocks` y `curve_steps`. La app no vuelve a filtrar los abandonos que el núcleo ya recorta a la última hora.
- **5.7:** `bed_little` suma los boxes y el pasillo, todos los que esperan cama, que es lo que cuenta λ · W: λ · W = 7,484 frente a 7,495 por las curvas (7,494 en su box y 0,0008 en el pasillo) en la ejecución del notebook.
