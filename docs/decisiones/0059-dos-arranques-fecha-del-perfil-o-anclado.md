# 0059. Dos arranques: con la fecha del perfil o anclado al calendario

- **Estado:** Aceptada
- **Fecha:** 2026-11-06

## Contexto

Los tests necesitan un directo reproducible; el panel del hito 8 querrá un directo que corra «ahora», con las horas del día de verdad ([especificación, «Anclaje al calendario»](../specs/hito-6.md#anclaje-al-calendario)).

## Decisión

- Por defecto, el directo empieza en la `fecha_inicio` del perfil de llegadas: reproducible.
- Con `--anclar`, empieza `--calentamiento` días antes de hoy a las 0:00 y calienta hasta ahora, en `+01:00`.
- Se mantiene el desfase fijo `+01:00` de `event_time` (decisión 20).

## Alternativas consideradas

- Solo anclado: los tests dependerían del reloj de pared.
- Usar la zona horaria con cambio de hora: rompería la decisión 20 sin necesidad; el instante sigue siendo correcto.

## Consecuencias

- «Directo = batch» se prueba también anclado, con un reloj falso en una fecha fija.

## Qué cambió al implementarla

- 6.3: `dataclasses.replace` sobre el perfil volvía a normalizar los factores, cambiaba 16 de ellos en el último bit y, con la misma fecha, el log desde el minuto 3.324. De ahí `ArrivalProfile.with_start_date`, que cambia la fecha sin renormalizar, comprobado bit a bit contra un TOML con esa fecha.
- 6.3: `anchored_start` toma el día en `+01:00`, no en UTC: a las 23:30 UTC ya es el día siguiente.
