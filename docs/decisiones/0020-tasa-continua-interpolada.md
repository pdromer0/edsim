# 0020. Tasa λ(t) continua con interpolación lineal periódica

- **Estado:** Aceptada
- **Fecha:** 2026-10-29

## Contexto

El perfil da un valor por hora, pero la afluencia no salta a las en punto. Además, la validación y el generador necesitan la intensidad acumulada Λ(t) de forma exacta ([especificación](../specs/hito-2.md#modelo-de-llegadas)).

## Decisión

- Cada valor horario es el del centro de su hora (h:30), y entre centros consecutivos se interpola linealmente, de forma periódica: las 23:30 enlazan con las 0:30.
- El día de la semana, el mes y el efecto diario Z cambian a medianoche. El reloj no tiene cambio de hora: todos los días duran 1.440 minutos.
- Λ(t) se calcula de forma exacta: con λ lineal a trozos, el área de cada tramo es un trapecio.

Motivo: sin saltos artificiales a las en punto, con el mismo área diaria y Λ exacta.

## Alternativas consideradas

- Escalones, con un valor constante por hora: λ salta a las en punto. En la tarea 2.1, esta versión pasó los tests de autoconsistencia (`quad`, derivada) y solo la detectaron los valores calculados a mano y los tests de continuidad.

## Consecuencias

- λ = escala del día (B/1440 · d · m · Z) × forma horaria. Z entró en la tarea 2.3 como un factor más de la escala, sin reescribir `rate.py`.
- Λ usa una tabla de 26 nodos con las áreas acumuladas; `scipy.integrate.quad` sirve como comprobación independiente en los tests, integrando día a día.
- La forma horaria es la misma todos los días. Una forma distinta en fin de semana es posible, pero no está en el alcance.
- Festivos y cambio de hora quedan para hitos posteriores.
