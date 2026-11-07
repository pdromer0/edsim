# 0045. Con el modelo clínico, los niveles 4 y 5 esperan los resultados fuera del box

- **Estado:** Aceptada
- **Fecha:** 2026-11-07

## Contexto

Con el modelo clínico de la tarea 4.5a, en 14 días con `config/`, el 64 % del tiempo de box (91,2 minutos por paciente) era esperar resultados: los 30 boxes llegaban al pico mientras los médicos estaban a unos 7 de 12 de media. La plantilla de médicos, el mando de la calibración, no habría podido mover las esperas de los niveles 4 y 5. En las urgencias reales, los pacientes leves esperan los resultados fuera del box ([especificación, «Calibración»](../specs/hito-4.md#calibración) y [anexo, tarea 4.5a](../specs/hito-4.md#tarea-45a-el-clinicalsampler-en-el-motor)).

## Decisión

Con el modelo clínico, un paciente cuyo nivel *asignado* está en `recursos.espera_resultados_fuera` (`centro.toml`, `[4, 5]` en el centro base) deja el box al pedir las pruebas: emite `test_ordered` y, en el mismo instante, `box_released`. Espera los resultados en una sala sin límite de capacidad y, con el `test_resulted`, vuelve a pedir box con su clave de siempre, `priority_key(nivel, llegada)`, como un paciente desalojado, para la reevaluación. `box_released` es el evento nuevo del catálogo versión 3. La clave es opcional y vale `[]` si falta. El modelo provisional no cambia.

Motivo: el 64 % del tiempo de box era espera de resultados y saturaba los 30 boxes; en las urgencias reales los leves esperan fuera; la plantilla de médicos no puede calibrar una cola de boxes.

## Alternativas consideradas

- Calibrar también los boxes: con objetivos de tiempo hasta el médico, plantilla y boxes no son identificables ([ADR 0041](0041-centro-realista-calibrado-con-dos-mandos.md)).
- Revisar a la baja los porcentajes orientativos de pruebas (72,8 % frente al 55,4 % del provisional): era una de las opciones abiertas tras la 4.5a, pero no habría cambiado que el box se ocupe durante toda la ronda ([anexo, tarea 4.5a](../specs/hito-4.md#tarea-45a-el-clinicalsampler-en-el-motor)).
- Decidir la sala con el nivel real: el hospital no lo ve. Con el asignado, un infratriado de nivel real 3 asignado como 4 sale del box, y un sobretriado de nivel real 4 asignado como 3, no.
- Volver de la sala con una clave nueva: «nadie se cuela» la detecta, porque reconstruye la clave (nivel, llegada) desde el log. La versión incorrecta V4 de la tarea 4.6a dio 1.735 violaciones en 14 días ([anexo, tarea 4.6a](../specs/hito-4.md#tarea-46a-paradas-y-espera-de-resultados-fuera-del-box)).
- `[4, 5]` como valor por defecto de la clave: la copia de `centro.toml` de una ejecución anterior a la 4.6a cambiaría de significado.

## Consecuencias

- Con la sala (14 días, `config/`, semilla 2026, plantilla `[12, 12, 7]`), el tiempo de box por paciente sin esperas de médico baja de 91,0 a 69,8 minutos y los boxes ocupados, de 21,0 a 16,5 de media; la espera de box de los niveles 4 y 5 pasa de 35,3 y 85,4 a 12,8 y 20,4 minutos, y el reloj C del nivel 4, del 82,7 % con 5 días fuera de 12 al 95,4 % con 2. Los médicos siguen en 7,0 de media (cifras de «Calibración»; el anexo de la 4.6a tiene su propia medida, con 36,0 y 87,5 minutos antes).
- El cuello de botella vuelve a los médicos: la plantilla es el mando que mueve los tiempos, y los boxes quedan fijos (30) en la calibración.
- El modelo clínico escribe siempre el catálogo versión 3, también con `espera_resultados_fuera = []`: una versión por modelo, no por configuración. La invariante `results_wait` exige que dejen el box exactamente los niveles de la clave.
- `tests/data/centro_sala_ejemplo.toml` caracteriza la sala; `centro_ejemplo.toml` no lleva la clave, para que no cambien las huellas del provisional. La app muestra la sala y las dos esperas de box, pero no edita la clave.
