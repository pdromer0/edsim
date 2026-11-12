# 0072. Espera de cama lognormal con un factor del turno del pedido

- **Estado:** Aceptada
- **Fecha:** 2026-11-10

## Contexto

Un ingresado no se va al decidirse: espera cama en su box y lo bloquea (*boarding* o *access block*, la causa más citada de la saturación). En el SAS de 2013, un ingresado pasaba de media 472,5 min en urgencias, y el 49,69 % más de 4 horas ([pieza 3](../specs/hito-5.md#pieza-3--la-espera-de-cama-y-los-boxes-bloqueados)).

## Decisión

- La espera de cama es `c_turno · c_estación · e^(μ + σz)`, con:
  - `[mediana, p90]` en `[camas]` de `centro.toml`;
  - un factor por turno del pedido (`factor_turno`);
  - un factor opcional por estación (`factor_estacion`, que vale 1 si no se escribe).
- Su z sale del flujo 9, una normal por paciente, ingrese o no.
- El ingresado espera en su box, con su clave de prioridad. Si un nivel 1 lo desaloja, espera en el pasillo ([ADR 0073](0073-catalogo-version-4.md)).

## Alternativas consideradas

- **Camas de planta finitas:** una planta de N camas con estancias de unos 7 días arranca vacía y tarda semanas en llenarse. El calentamiento pasaría de 2 días a unas 4 semanas y cada evaluación de la calibración costaría más del triple. Faltarían además los ingresos programados y la hora de las altas de planta. Es el boarding realista de la v2.
- **Una espera fija:** no se calibra contra la estancia de los ingresados ni da la cola larga que se observa.

## Consecuencias

- La espera es del hospital, no del paciente: el factor es el del turno en que se pide la cama. Multiplicar una lognormal por un factor multiplica su mediana, así que el paciente conserva su percentil.
- La ley de Little dice cuántos boxes bloquea de media: L = λ · W ([ADR 0075](0075-calibracion-en-orden-con-un-mando-por-objetivo.md)).

## Qué cambió al implementarla

- **5.1, el `timeout` del propio paciente** (ajuste de la aprobación): la espera es un `timeout` del paciente, no un proceso aparte como el del laboratorio. Al acabar, `bed_assigned` y `patient_departed` salen en el mismo paso de SimPy, sin que entre los dos se cuele ningún evento. Tras un desalojo, el mismo `timeout` se espera en el pasillo.
- **5.6, calibrada a [210, 630]**: la mediana es el mando de la estancia media de los ingresados (horquilla 360–600 min). El p90 = 3 × mediana es la forma de partida, de criterio.
- **5.6, la forma, de criterio:** con [210, 630], el 78,7 % de los ingresados pasa más de 4 h, frente al 49,69 % del SAS, fuera de la horquilla 35–65 % de ese objetivo de comprobación. Para cuadrar a la vez la media y el porcentaje haría falta otra forma: está en el Backlog (#109).
