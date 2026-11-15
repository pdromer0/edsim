# 0096. Una sola comparación con la verdad, en Python, en el paquete

- **Estado:** Aceptada
- **Fecha:** 2026-11-13

## Contexto

Hay dos preguntas que ningún hospital puede responder: qué le pasó a cada hecho y cuánto se equivocan los indicadores por culpa de los despistes. Las respuestas las quieren la CLI, el notebook, los tests y la fase 2 de la app ([especificación, «La comparación»](../specs/hito-7.md#especificación-la-comparación)).

## Decisión

- Una sola comparación, en Python, en el paquete (`edsim.clinical_record.compare`), con tres partes:
  - la **conciliación** exacta;
  - la **distribución del retraso** por sistema;
  - los **indicadores ingenuos**: el tiempo hasta el triaje y hasta el médico, los pacientes en urgencias, las llegadas y el reparto por nivel.
- Da lo mismo con ficheros que con bronce: recibe la verdad y lo registrado como listas.
- Los indicadores ingenuos no reutilizan las métricas de `edsim.runs`, que esperan datos limpios.

## Alternativas consideradas

- **Vistas SQL en Postgres:** obligarían a cargar la verdad (decisión 95) y a mantener dos implementaciones. Tendrían sentido en el hito 8, si Grafana tuviera que enseñar el sesgo en vivo.
- **Más indicadores** (los del hito 5, por nivel real): más superficie sin una lección nueva; los cinco elegidos ya enseñan cada despiste.

## Consecuencias

- La CLI, el notebook y los tests usan la misma función; la fase 2 de la app la tiene lista (#122).
- La conciliación es un error si no cuadra, no un número.

## Qué cambió al implementarla

- **7.3, `--postgres` lee la última publicación** (propuesta del chat del 14 de noviembre): las filas de la ejecución desde su último `inicio` de `bronce.ejecuciones`, una por `event_id`, la más reciente; sin `inicio`, todas. Cambia lo que daba `read_bronze_lines`, que era la primera publicación (V31). Una republicación a medias da una cuenta que no cuadra, no el hueco rellenado con la publicación anterior.
- **7.3, la cuenta, un error:** `ReconciliationError` (un `ValueError`) junta todos los problemas.
- **7.3:** `compare` recibe `horizon` y `warmup` en minutos, porque los necesita el censo medio. El origen del reloj se deduce del primer evento de la verdad, con la fórmula de `event_time()`.
- **7.3, los indicadores ingenuos:**
  - el primer registro de cada tipo de cada episodio, en el orden de emisión (V26);
  - `assessment_started` solo con `tipo == "inicial"`;
  - el censo cuenta `llegada <= H < salida` en cada hora en punto de `[calentamiento, horizonte)` (V29 y V30);
  - el reparto por nivel incluye los duplicados;
  - los `record_corrected` no se leen (V10).
- **7.3, el retraso por sistema:** `recorded_time - event_time` de los registros `bien` y `con_despistes`, sin duplicados ni correcciones (V28). El desfase se cancela, porque se suma a las dos horas.
- **7.3, `con_despistes` desglosado** (nota del chat): con reloj, con retraso, con valor erróneo y con campo vacío (se solapan), y solo reloj.
- **7.3, las cifras** con 14 días de `config/` y la semilla 2026:
  - el censo medio sale 39,37 en la verdad, 50,74 en el realista y 155,83 en el hostil: es el indicador que más se estropea, por los fantasmas;
  - el tiempo hasta el médico del hostil sale 7,06 frente a 14,89, porque los relojes del HIS (−5) y de admisión (+3) restan 8 minutos.
