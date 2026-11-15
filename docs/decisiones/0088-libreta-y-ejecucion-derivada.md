# 0088. La libreta `defectos.csv` y lo registrado como ejecución derivada, renumerada

- **Estado:** Aceptada
- **Fecha:** 2026-11-13

## Contexto

El laboratorio tiene que poder decir qué le pasó a cada hecho, pero las soluciones no pueden ir dentro del examen. Si lo registrado conservara la numeración de la verdad, un hueco delataría un olvido y una marca, un duplicado: es la fuga que evitó la decisión 28 con el ground truth ([especificación, «La libreta»](../specs/hito-7.md#la-libreta-defectoscsv)).

## Decisión

- **La libreta** `defectos.csv` tiene una fila por registro y otra por cada hecho no escrito, con su clase.
- **Lo registrado con un perfil y una semilla es una ejecución derivada**, con su propio `run_id` (`r2026_realista_s2026`). Sus registros se renumeran en orden de anotación, y su `inicio` dice el origen, el perfil y la semilla.
- **El corte:** lo que se anotaría después del horizonte no se escribe; queda «pendiente al corte».
- **La cuenta que cuadra** (hechos y registros por clase) es una invariante: si no cuadra, es un error.

## Alternativas consideradas

- **Conservar los `event_id` de la verdad:** delataría los olvidos y los duplicados (V1 de la 7.1 hace fallar 10 tests). Tendría sentido solo en un ejercicio de enseñar los despistes, no de buscarlos.
- **Marcar los defectos dentro de lo registrado** (una columna «es duplicado»): regala las soluciones.
- **Escribir lo pendiente al corte con su hora futura:** una extracción real se hace a una hora concreta y no ve el futuro.

## Consecuencias

- Dos registros de la misma verdad (otro perfil u otra semilla) no se mezclan en el archivo: cada uno tiene su `run_id`.
- La comparación con la verdad necesita la libreta, que vive en la carpeta de lo registrado, nunca en lo publicado.

## Qué cambió al implementarla

- **7.1, la cuenta tiene cinco igualdades:** las tres de la especificación; una de recursos (pasan como `bien`); y «registros, contados por `event_id` distintos, = filas con registro», que es la que pilla un `event_id` repetido (V4). `record` la comprueba al final.
- **7.2, `record_run`** (`9be4508`):
  - hace las comprobaciones previas sin tocar el disco;
  - escribe en una carpeta temporal oculta dentro de la ejecución, con la copia de los perfiles, y la renombra al final (V24);
  - `registro.json` no lleva fecha, así que la misma verdad, perfil y semilla dan los mismos bytes;
  - devuelve también la `huella` de la copia;
  - si lo registrado ya existe, da `FileExistsError`. No hay `--forzar`.
- **7.3:** la tercera igualdad (correcciones escritas + pendientes = erróneos con corrección) necesita lo sorteado, que solo está en `registro.json`. La comprueba `generar`, no `comparar`.
- **7.2, las cifras con 14 días de `config/` y la semilla 2026:** la cuenta cuadra con los tres perfiles. El realista da 55.118 registros, con 263 duplicados, 79 correcciones, 262 perdidos y 16 pendientes.
