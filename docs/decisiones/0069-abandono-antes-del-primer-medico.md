# 0069. Abandono solo antes del primer médico, desde tres sitios

- **Estado:** Aceptada
- **Fecha:** 2026-11-10

## Contexto

Sin abandono, una cola que crece no se corta nunca: en la peor semana de enero de la semilla 2026, el nivel 5 llegaba a 3.897 min de espera (4.6c). SEMES mide dos indicadores: las fugas antes del triaje y las fugas antes de ser visitados por el médico, con un estándar de como mucho el 2 % ([pieza 1](../specs/hito-5.md#pieza-1--abandono-y-paciencia)).

## Decisión

- Un paciente solo puede irse antes de ser visto, es decir, antes de su primer `assessment_started` de tipo `inicial`.
- Se puede ir desde tres sitios, que el evento `patient_left_wbs` lleva en `espera`:
  - `triaje`: esperando enfermera;
  - `box`: triado y esperando box, también tras un desalojo antes de ser visto;
  - `medico`: en un box, esperando la valoración inicial.
- Si se va desde un box, lo libera en ese instante.
- No se va durante el triaje ni durante una valoración.
- El nivel 1 asignado nunca abandona.
- El alta voluntaria (irse después de ser visto) va a la v2.

## Alternativas consideradas

- **Abandonar también después de ser visto:** en el Aljarafe, las altas voluntarias son de 0,7 a 1,7 por 1.000 urgencias, frente a 22 a 36 fugas, y piden su propia regla clínica.
- **Un solo sitio (la sala de espera):** con los médicos de cuello de botella, la cola está dentro del box, y SEMES separa antes y después del triaje.

## Consecuencias

- El bucle «saturación → abandono» sale solo de las colas, sin programarlo, y es una realimentación negativa: irse acorta la cola.
- Los relojes de quien se va quedan vacíos, y las métricas necesitan la regla de la censura ([ADR 0074](0074-metricas-con-censura-del-abandono.md)).

## Qué cambió al implementarla

- **5.3, «tercera regla de Pedro»:** nadie sigue esperando sin ser visto al final con su instante de abandono antes del horizonte. Lo comprueba la invariante `abandonment`.
- **5.3:** el plazo vencido *antes* de empezar el triaje no espera a su fin (`0c20622`). Con la regla «max(plazo, fin del triaje)» siempre, un motor que ignorase el plazo esperando enfermera la pasaba. La regla del triaje está en el [ADR 0070](0070-paciencia-lognormal-por-nivel-real.md).
- **5.6, medida:** en el año de la semilla 2026 se va el 0 / 0 / 0,08 / 2,87 / 10,92 % por nivel asignado. Ningún grave de verdad se fue.
