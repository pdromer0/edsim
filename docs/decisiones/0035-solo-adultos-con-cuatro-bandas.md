# 0035. Solo adultos de 15 años o más, con cuatro bandas de edad

- **Estado:** Aceptada
- **Fecha:** 2026-11-07

## Contexto

El paciente del hito 4 necesita una edad, porque la edad cambia el motivo, la gravedad, las pruebas y el medio de llegada. Los objetivos de triaje disponibles son de adultos (Emergencias 2013 y la concordancia de Asturias), y el SAS separa a los menores con el corte de los 15 años. La pediatría tiene sus propios motivos y su propia gravedad ([especificación, «Población y contexto»](../specs/hito-4.md#población-y-contexto)).

## Decisión

El centro atiende solo a adultos de 15 años o más. La edad sale de cuatro bandas (15–44, 45–64, 65–79 y 80–99), sorteadas con una categórica log-lineal condicionada al contexto, y es uniforme dentro de la banda. Sexo y medio de llegada tienen un porcentaje por banda. Las 300 urgencias al día del hito 2 pasan a ser 300 urgencias de adultos.

Motivo: los objetivos de triaje son de adultos; la pediatría pide su propio catálogo (v3).

## Alternativas consideradas

- Población de todas las edades (centro mixto): pide un catálogo y una gravedad propios. Queda para los perfiles de centro de la v3 ([«Para versiones posteriores»](../specs/hito-4.md#para-versiones-posteriores)).
- Usar los objetivos de edad tal como se publican, sobre todas las edades: entre el 27 y el 35 % de urgencias de mayores de 65 años. Comparados con una población de adultos, quedarían por debajo. Si los menores son una de cada cinco urgencias (SAS, 2013), sobre adultos son un 34–44 %. Un objetivo se convierte siempre a la población que se simula antes de usarlo.

## Consecuencias

- Con `config/`, el 38,6 % de los pacientes de un año tiene 65 años o más (horquilla del 34–44 %), y el 26,9 % de ellos llega en ambulancia, frente al 27 % de la cohorte EDEN; con `[20, 32]` en las dos bandas mayores salía un 25,4 % ([anexo, tarea 4.2](../specs/hito-4.md#tarea-42-perfiles-contexto-población-y-motivo)).
- El reparto del SAS en adultos se obtiene quitando los menores nivel a nivel, no restando puntos al reparto con niños: 1,15 / 7,32 / 34,44 / 38,86 / 18,22 % ([anexo, tarea 4.7](../specs/hito-4.md#tarea-47-notebook-04-de-perfiles-clínicos)).
- El CMBD del SAS incluye niños: sus cifras dan el orden de magnitud y las horquillas de calibración son anchas ([ADR 0041](0041-centro-realista-calibrado-con-dos-mandos.md)).
