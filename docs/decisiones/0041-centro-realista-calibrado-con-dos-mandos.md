# 0041. Centro base realista, calibrado a lo observado con dos mandos de objetivos separados

- **Estado:** Aceptada
- **Fecha:** 2026-11-07

## Contexto

Hasta el hito 3, la plantilla del centro base era provisional. Un laboratorio de analítica necesita un centro que se parezca a los reales, y los reales incumplen a veces: un centro que nunca incumple no sirve. Los datos españoles observados son pocos y anchos (el CMBD del SAS es de 2013 e incluye niños), y algunos parámetros no se pueden distinguir con los objetivos disponibles ([especificación, «Calibración»](../specs/hito-4.md#calibración)).

## Decisión

- **Se calibra a lo observado, no a la norma.** Cada objetivo vive en `config/objetivos.toml` con su horquilla y su fuente, y es de ajuste o de comprobación. Las normas (máximos de Manchester, pretriaje de 10 minutos, PAUE) se informan, pero no son objetivos.
- **Dos mandos con objetivos separados, en este orden:** primero la enfermería de triaje contra el pretriaje medio (6–15 min, referencia 12,4 del SAS); con ella fija, los médicos contra el tiempo medio hasta el médico de los niveles 2 a 5 (reloj A, 35–70 min, centro 52,5). Los boxes quedan fijos (30) y las duraciones, fijas por criterio clínico.
- **Plantilla equivalente.** Personal del turno = ⌈carga del turno / u⌉, con una ocupación objetivo u por mando, de 0,55 a 0,99 en pasos de 0,0025. No se buscan combinaciones fuera de la regla.
- **Reglas contra el sobreajuste:** pocos mandos, documentados en un registro; objetivos de ajuste y de comprobación separados; semillas distintas; horquillas, no puntos (un objetivo pasa si la media entre réplicas cae dentro y su IC no es más ancho que la horquilla); sensibilidad antes de ajustar.
- **Elección:** entre las plantillas que pasan los objetivos de ajuste, la más cercana a la referencia del objetivo que decide o, sin ella, al centro de la horquilla.

**Revisión del 6 de noviembre (tarea 4.6b).** La decisión del 5 de noviembre tenía un solo mando, los médicos. Con la enfermería de antes (`[3, 3, 2]`), ocupada en torno al 40 % del tiempo, el pretriaje medio era de 1,4 minutos, y ningún cambio de médicos podía acercarlo a su horquilla: la enfermería de triaje entra como segundo mando, ajustado solo al pretriaje. En la misma tarea, el reloj A del nivel 3 pasa de ajuste a comprobación después de medir la sensibilidad: con prioridad estricta en un solo grupo de médicos, ninguna plantilla de la regla lo lleva por encima de 22,9 min (horquilla 45–75), una discrepancia estructural.

**Revisión de la tarea 4.6c.** Cada candidato se mide con la ventana anual: 12 réplicas de 14 días, una por mes, cada una desde el primer lunes del mes y con el hijo m de la semilla, con 2 días de calentamiento y uno de vaciado. Y la semilla de comprobación puede vetar la elección, no hacerla: si la elegida con 2026 falla un objetivo de ajuste con 2027, se toma la siguiente candidata que pase con las dos, y la comprobación independiente pasa a la semilla 2028. El centro cumplidor se decide con días enteros.

Motivo: un laboratorio que nunca incumple no sirve; plantilla y duraciones no son identificables sin la estancia, y plantilla y boxes tampoco con objetivos de tiempo hasta el médico; los médicos no mueven el pretriaje; los objetivos del SAS son medias anuales, y una plantilla elegida con una semilla que falla con otra está en el borde por azar.

## Alternativas consideradas

- Calibrar a la norma: un centro calibrado a la norma cumpliría por diseño.
- Calibrar también las duraciones: menos médicos y valoraciones más largas alargan igual el tiempo hasta el médico, y en el hito 4 ningún objetivo los distingue (la estancia se calibra en el hito 5). Sería un problema no identificable.
- Calibrar también los boxes: con objetivos de tiempo hasta el médico, plantilla y boxes no son identificables ([ADR 0045](0045-espera-de-resultados-fuera-del-box.md)).
- Un solo mando, los médicos: no mueven el pretriaje (1,4 min con la enfermería de antes).
- Medir los candidatos desde `fecha_inicio`, como en la 4.6b: era la primera quincena de enero, el mes de más carga. Con la ventana anual, el centro de la 4.6b da un reloj A de 27,75 min, por debajo de 35–70 ([anexo, tarea 4.6c](../specs/hito-4.md#tarea-46c-recalibración-con-la-ventana-anual)).
- Dejar que la semilla de comprobación elija: dejaría de comprobar. Por eso solo veta, y tras un veto se confirma con otra semilla.
- Decidir el cumplidor con la media de las proporciones: el cumplidor de la 4.6b estaba justo en el borde (10,0 % de días fuera), y la media de decimales podía salir 0,1000000001 en unos 3 de cada 10.000 repartos ([anexo, tarea 4.6b](../specs/hito-4.md#tarea-46b-calibración-de-la-enfermería-de-triaje-y-de-los-médicos)).

## Consecuencias

- El centro base queda con la enfermería de triaje `[3, 2, 1]` y los médicos `[12, 11, 4]`. En la enfermería, la regla eligió `[2, 2, 1]` (13,21 min, la más cercana a 12,4), pero con 2027 su pretriaje salió de la horquilla (15,16 \[10,61; 19,71\]) y el veto dejó `[3, 2, 1]`: pretriaje de 6,78 \[5,49; 8,06\] con 2026, 7,86 con 2027 y 7,76 con 2028. Con esa enfermería, solo `[12, 11, 4]` pasa el reloj A de los niveles 2 a 5 (u = 0,85): 42,10 \[28,02; 56,18\], 43,29 y 41,20 ([«Calibración»](../specs/hito-4.md#calibración)).
- Comprobaciones con 2027: un 16,79 % de pacientes por encima de Manchester (10–30 %), un 32,91 % con más de 5 minutos de pretriaje (30–60 %) y el reloj A del nivel 3 en 20,13 min, fuera, por la discrepancia.
- `config/centro_cumplidor.toml` (médicos `[14, 14, 6]`) es la variante que cumple Manchester: 1/144, 0/144, 2/144 y 6/142 días fuera con el reloj C en los niveles 2 a 5.
- La plantilla es la misma todo el año, así que enero queda cerca de la saturación: con 2026, el reloj A de los niveles 2 a 5 va de 105,2 min en enero a 24,6 en agosto, y quedan 8 pacientes de enero censurados (0,20 %). El refuerzo de invierno queda para versiones posteriores.
- El registro de calibración ([docs/calibracion/registro.md](../calibracion/registro.md)) guarda cada cambio con su comando. Los comentarios de `config/centro.toml` citan los comandos que reproducen cada valor.
- Pendiente: circuitos separados para los niveles 4 y 5 permitirían calibrar el reloj A del nivel 3.
