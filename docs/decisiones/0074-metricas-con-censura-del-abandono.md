# 0074. Métricas con abandono: medias de los atendidos y cumplimiento con censura

- **Estado:** Aceptada
- **Fecha:** 2026-11-10

## Contexto

Con abandono, los pacientes que más esperan son los que se van. Quitarlos de las métricas haría parecer mejor un servicio que va peor (sesgo de supervivencia). Contarlos como si los hubieran visto inventaría un dato. Hace falta una regla por métrica ([pieza 4](../specs/hito-5.md#pieza-4--medir-con-abandono-supervivencia-y-censura)).

## Decisión

- **Las medias de los relojes A, B y C**, de los atendidos, como el TPAM del SAS.
- **El cumplimiento Manchester** (reloj C) lleva censura:
  - quien se va después de su máximo, o justo en él, es un incumplimiento;
  - quien se va antes no cuenta: está censurado.
- **Indicadores propios** para el abandono, la cama y el destino.
- **Los de nivel real**, solo con el ground truth.

## Alternativas consideradas

- **Quitar a todos los que se van del cumplimiento:** con tres pacientes de nivel 4 (máximo 120 min) vistos a los 30 y a los 90 y uno que se va a los 150, el cumplimiento saldría 2 de 2, un 100 %, en lugar de 2 de 3, el 66,7 %.
- **Contar a todos los que se van como incumplimiento:** quien se va a los 20 min quizá habría sido visto antes de los 120; contarlo inventaría un incumplimiento.

## Consecuencias

- **Lo que garantiza la regla:** irse nunca esconde un incumplimiento seguro. Quien se va con su reloj en su máximo o por encima habría esperado más que el máximo, y cuenta como incumplimiento.
- **Lo que no garantiza:** que más abandono nunca mejore el cumplimiento. Si el tercer paciente se va a los 20 min, queda censurado y el cumplimiento sube del 66,7 % al 100 % (2 de 2): un censurado que se habría visto tarde puede subir el porcentaje.
- Con el modelo del hito 4 (sin abandono), las funciones dan exactamente lo de antes.

## Qué cambió al implementarla

- **El motivo, corregido en el cierre (5.8):** la especificación decía «más abandono nunca mejora el cumplimiento», y el ejemplo de su propia pieza 4 lo desmiente. El motivo es el de «Consecuencias»: irse nunca esconde un incumplimiento seguro. Lo vio la revisión de la 5.4, que corrigió el docstring (`2a68045`). La 5.8 corrige la pieza 4 y la tabla de decisiones.
- **5.4, el máximo exacto** (ajuste de Pedro al plan): quien se va con su reloj justo en el máximo incumple. Quien se va en el instante t no fue visto en t (con el empate, se habría quedado), así que su espera hasta el médico habría sido mayor. La app lo marca con «≥».
- **5.4, el reloj de quien se va depende de la medida:** con C, desde la clasificación; con B, desde el inicio del triaje, y con A, desde la llegada.
- **5.4, medias y cuantiles con censurados** (la espera de cama y la estancia de quien sigue dentro en el horizonte):
  - con los censurados en su cota sale el mínimo posible, y con ellos por encima de todos, el máximo; si coinciden, el valor es exacto, y si no, se da la cota («≥»);
  - la media con censurados es siempre una cota;
  - en un umbral, el censurado que ya lo pasó cuenta por encima y el que no, como desconocido.
- **5.4, los denominadores:** el abandono y los destinos globales, sobre las llegadas; por nivel asignado, sobre los clasificados de ese nivel.
- **5.6, el pretriaje es de los triados, no de los atendidos** (ajuste de Pedro al plan): la calibración reutiliza `triaged_in_window`. Las medias de los relojes, de los atendidos; sus porcentajes, con la censura (`compliance_cases`).
