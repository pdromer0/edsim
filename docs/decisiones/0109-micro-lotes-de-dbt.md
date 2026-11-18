# 0109. Tiempo real por micro-lotes de dbt, con los paneles en el reloj de la ejecución

- **Estado:** Aceptada
- **Fecha:** 2026-11-16

## Contexto

Hasta bronce, el directo ya llega en segundos (hito 7), pero plata y oro solo cambian cuando alguien construye. El directo ancla `event_time` al reloj de pared, así que a ×60 el tiempo simulado se adelanta y una reemisión de `r2026` cae en enero ([pieza 7](../specs/hito-8.md#pieza-7--tiempo-real-por-micro-lotes)).

## Decisión

- `edsim analitica refrescar` construye la hoja del hospital cada 60 s, y Grafana refresca cada 30 s.
- Los paneles usan el reloj de la ejecución, no el de la pared.
- Se mide la vuelta con un año en bronce; si pasa del intervalo, se decide el plan B, un incremental por ejecución.
- El orquestador, al hito 9 (a pregunta de Pedro).

## Alternativas consideradas

- **Quix Streams:** choca con la versión de `confluent-kafka` (decisión 100).
- **Agregados continuos de Timescale:** buenos para KPIs de una tabla, pero no limpian.
- **Bases de datos de flujo** (Materialize, RisingWave): otro motor.
- **Un orquestador** (Airflow 3, Dagster o Prefect): brilla con lotes, no con una reconstrucción cada minuto, y el consumidor es un servicio que no termina. Airflow 3 pide al menos 4 GB en su Docker Compose. Encaja en el hito 9, con réplicas en paralelo.

## Consecuencias

- El criterio de la fase 3 se cumple sin otro motor.
- Cada paso es un comando que deja lo mismo si se repite: listo para orquestar.

## Qué cambió al implementarla

- **8.6** (#154): **barras por hora con la hora simulada como etiqueta**, a propuesta de Pedro en el plan. En Grafana 13, un panel *time series* ata su eje al rango de tiempo del cuadro y no pintaría una reemisión de enero.
- **8.7** (#155, `6e341f1`): **el fin del dato.** Es el `sim_time` del `fin` si es el último mensaje de `ed.runs`; si no, la última anotación; y nunca más que el horizonte. Así, oro no tiene horas aún por llegar con un censo congelado.
- **8.7** (`c1ffd59`, `cdef1e2`, `bd9e58d`): `dbt build` sin tests, no `dbt run`, porque así carga también las semillas. Una vuelta que pasa del intervalo no se solapa con la siguiente: esta empieza al acabar, con un aviso. Una vuelta que falla no para el bucle, y Ctrl+C espera a que acabe dbt.
- **8.7, la medida:** con un año en bronce (`r365` y el directo, 1.391.949 registros), **la vuelta tarda 60,1 s**: pasa del intervalo. Pedro lo acepta para el hito 8, porque el caso de uso (un directo y pocas reemisiones) queda muy por debajo: 3,8 s de mediana con un directo de una hora. **El plan B pasa al #156** y no se implanta.
- **8.7:** el consumidor se frena con bronce grande, de ~840 a ~180 eventos/s (#156).
