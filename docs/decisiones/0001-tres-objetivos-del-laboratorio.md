# 0001. El laboratorio sirve a tres objetivos a la vez

- **Estado:** Aceptada
- **Fecha:** 2026-10-27

## Contexto

EDsim genera datos sintéticos de urgencias hospitalarias para un laboratorio de analítica. Se construye desde cero con un objetivo doble: obtener el sistema y aprender sus fundamentos ([diseño](../diseno.md#visión-y-objetivos)).

## Decisión

El laboratorio sirve a la vez a tres objetivos:

1. Analítica, docencia y desarrollo de producto, con datos en streaming y en base de datos.
2. Entrenar y validar modelos: estado del sistema, alertas, predicción de esperas y llegadas, robustez ante cambios.
3. Análisis de escenarios: experimentos que modifican variables y se comparan con rigor estadístico.

Motivo: es el alcance pedido.

## Alternativas consideradas

No se documentaron alternativas.

## Consecuencias

- El mismo motor necesita varios modos de reloj: directo, batch y replay.
- Hay dos caminos de datos: el directo alimenta Grafana desde Postgres, y el batch alimenta experimentos y modelos desde Parquet.
- Los modelos requieren separar el ground truth ([0006](0006-log-de-eventos-y-ground-truth.md)), y los experimentos requieren números aleatorios comunes ([0007](0007-un-flujo-aleatorio-por-fuente.md)).
