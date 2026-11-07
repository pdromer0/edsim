# 0042. Pruebas de cuatro tipos en una sola ronda

- **Estado:** Aceptada
- **Fecha:** 2026-11-07

## Contexto

El modelo provisional decidía si un paciente tenía pruebas con una probabilidad por nivel y sorteaba un único tiempo de respuesta. Con perfiles clínicos, qué pruebas se piden depende del motivo, de la gravedad y de la edad, y cada tipo tiene su propio tiempo. El contrato del log (`test_ordered` y `test_resulted`) lo comparten el motor, el Replay y la app ([especificación, «Pruebas y duraciones»](../specs/hito-4.md#pruebas-y-duraciones)).

## Decisión

- Cuatro tipos de prueba (analítica, radiografía, ECG e imagen), en una sola ronda. Cada tipo se pide con una probabilidad logística sobre la gravedad real, el motivo y la edad (mayores de 65 años). El TOML da el porcentaje de un adulto de menos de 65 años con G = 0 y dos odds ratios por tipo; el código calcula el intercepto.
- Cada tipo sortea siempre su resultado (normal o alterado, otra logística sobre G) y su respuesta base (lognormal, factor 1), en un consumo fijo de 12 sorteos por paciente.
- La ronda dura lo que la prueba más lenta de las pedidas. El factor de la franja se aplica al pedir, con la franja del instante del `test_ordered`.
- Un solo `test_ordered`, con la lista `pruebas`, y un solo `test_resulted`, con `resultados`.

Motivo: el paciente se comporta igual sin cambiar el contrato del log; un evento por tipo queda para versiones posteriores.

## Alternativas consideradas

- Un `test_ordered` y un `test_resulted` por tipo de prueba, cada uno a su hora (opción 1): cambia el contrato del log que comparten el motor, el Replay y la app, y el paciente se comporta igual. Queda para cuando la analítica de servicios (laboratorio frente a radiología) lo necesite ([«Para versiones posteriores»](../specs/hito-4.md#para-versiones-posteriores)).
- Aplicar el factor de la franja de la llegada al sortear: la respuesta depende de cuándo se pide, que no se conoce al llegar. La versión incorrecta V8 de la tarea 4.4 lo comprobó ([anexo, tarea 4.4](../specs/hito-4.md#tarea-44-pruebas-por-tipo-y-duraciones-por-nivel-real-y-motivo)).
- Sortear resultado y respuesta solo de las pruebas pedidas: el número de sorteos dependería de lo que salga, y cambiar un porcentaje movería los valores de los demás pacientes ([ADR 0043](0043-sorteos-sincronizados-con-gumbel-max.md)).

## Consecuencias

- En un año, el 72,75 % de los pacientes tiene alguna prueba (55,41 % en el provisional), y la carga del médico por paciente es de 32,37 minutos, frente a 30,84: la valoración baja un poco y toda la subida viene de la reevaluación ([«Pruebas y duraciones»](../specs/hito-4.md#pruebas-y-duraciones)).
- Con el modelo clínico, `PatientDraws.test_turnaround` es `None`: la respuesta de la ronda no se conoce en la llegada, y el motor la calcula al pedir. La invariante `clinical` comprueba cada ronda contra la franja de su pedido a 1e-8 minutos.
- El catálogo de eventos versión 2 añade `pruebas` y `resultados`; el tiempo de respuesta de cada tipo va al ground truth.
- La ronda saturaba los boxes, porque se esperaba dentro: el 64 % del tiempo de box era espera de resultados ([ADR 0045](0045-espera-de-resultados-fuera-del-box.md)).
