# 0028. Ground truth del motor en ficheros aparte del log

- **Estado:** Aceptada
- **Fecha:** 2026-11-03

## Contexto

El simulador separa la verdad oculta de los datos observados (principio 3 del [diseño](../diseno.md) y [ADR 0006](0006-log-de-eventos-y-ground-truth.md)). El motor del hito 3 sortea al llegar valores que el hospital no ve, y el efecto diario Z del hito 2 tampoco es observable. La validación los necesita, y el laboratorio de analítica no debe poder usarlos sin querer ([especificación](../specs/hito-3.md#log-de-eventos-ground-truth-y-derivados)).

## Decisión

- El ground truth va en dos CSV *tidy*, aparte del log: `ground_truth_episodios.csv` (lo sorteado al llegar, una fila por episodio) y `ground_truth_dias.csv` (los `DayRecord` del hito 2, una fila por día).
- Cada fila lleva la configuración, su huella, la semilla y el `run_id`, como los CSV del hito 2.
- El log no lleva ningún campo fuera del catálogo, y un test compara las claves de cada `payload` con las del catálogo.

Motivo: mantener la verdad oculta separada, evitar el *data leakage* y validar con valores conocidos.

## Alternativas consideradas

- Guardar la verdad en el propio log: cualquier modelo entrenado con el log podría usarla. El test del catálogo lo impide.
- Parquet desde ya: llega con la persistencia del hito 7; en el hito 3 basta con CSV, sin dependencias nuevas.

## Consecuencias

- En el hito 3 el nivel y el destino del log coinciden con los del ground truth, porque el triaje no tiene error. En el hito 4 aparecerán la gravedad latente y la calidad del triaje, y en el hito 5, la paciencia.
- La condición extrema de capacidad infinita compara cada estancia del log con la suma de sus duraciones del ground truth: es exacta.
- La conservación se comprueba contra fuentes independientes: cada episodio del ground truth tiene exactamente un `patient_arrived`.
- Los floats van con `repr` y se leen bit a bit; se añadió el calentamiento a las columnas porque sin él no se sabe qué ventana usa el resumen ([anexo, tarea 3.7](../specs/hito-3.md#tarea-37-cli-edsim-motor-simular-y-edsim-motor-validar)).
