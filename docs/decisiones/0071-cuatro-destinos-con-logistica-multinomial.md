# 0071. Cuatro destinos con una logística multinomial sobre la gravedad real

- **Estado:** Aceptada
- **Fecha:** 2026-11-10

## Contexto

El destino provisional del hito 3 solo miraba el nivel asignado, con una probabilidad de ingreso por nivel en `[destino]` de `centro.toml`. El caso de uso «predecir el ingreso desde el triaje» necesita un ingreso que dependa de lo que de verdad lo causa, y que el triaje solo ve en parte. Además, el resultado de las pruebas se sortea desde el hito 4 sin tener efecto ([pieza 2](../specs/hito-5.md#pieza-2--destinos-con-logística-multinomial)).

## Decisión

- Cuatro destinos: alta, ingreso, traslado y exitus. La UCI va dentro del ingreso.
- Una logística multinomial con el alta como referencia, sobre:
  - la gravedad real G;
  - ser mayor (65 años o más);
  - el motivo, solo en el ingreso;
  - el número de pruebas alteradas.
- Se sortea con Gumbel-max en el flujo 4 (cuatro Gumbel por paciente).
- Los parámetros van en `perfiles.toml` (`[destinos]` e `ingreso` por motivo). `[destino]` sale de `config/centro.toml`, aunque se sigue leyendo en los centros antiguos.

## Alternativas consideradas

- **Por nivel asignado, como el provisional:** el médico atiende al paciente que tiene delante; la regla del hito 4 es el nivel asignado para la prioridad y la gravedad real para la clínica (decisión 38).
- **Probabilidades binarias independientes:** no suman 100 %, y subir una no bajaría las otras.
- **La UCI como destino aparte:** necesitaría camas propias sin datos (v2).

## Consecuencias

- Un nivel 2 infratriado como 4 espera como un 4 e ingresa como un 2.
- Las pruebas alteradas añaden información: de dos pacientes igual de graves, ingresa más el que tiene la analítica alterada.
- El ingreso global, el traslado y el exitus se derivan sin simular y se escriben ([ADR 0075](0075-calibracion-en-orden-con-un-mando-por-objetivo.md)). Al cambiar un odds ratio, solo cambian los pacientes que entran o salen de ese destino.

## Qué cambió al implementarla

- **5.2, los odds ratios de la gravedad** (decisión de Pedro en el plan): el del ingreso, de 2,0 a 1,5, y el del exitus, de 6,0 a 15. Con los de partida, la tabla exacta no cuadraba con el SAS ni concentraba el exitus en las paradas.
- **5.2:** las bases, con 4 cifras significativas (la del exitus es del 0,001937 %), y el factor común se aplica a las odds binarias de la partida (`100 · expit(logit(partida/100) + λ)`), no a las odds frente al alta. La partida del ingreso vive en el código (`ADMISSION_CATALOG`).
- **5.2:** el destino es el máximo de log odds + Gumbel, sin pasar por `exp` y `log`. La misma función sirve para lo exacto y para el muestreador.
- **5.6, medida:** el ingreso observado se comprueba en la simulación. Lo rebajan los que habrían ingresado y se fueron: 23 de los 729 que se fueron en el año de la semilla 2026.
