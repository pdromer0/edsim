# 0046. La parada / crítico pesa un 0,3 % con una gravedad alta y poco dispersa

- **Estado:** Aceptada
- **Fecha:** 2026-11-07

## Contexto

Con el nivel 1 en la puerta ([ADR 0039](0039-nivel-1-en-la-puerta.md)), una parada solo va directo al box si recibe nivel 1 asignado. La parada / crítico pesaba un 0,54 % con una gravedad media de 3,38 y desviación 0,38, justo por encima del umbral del nivel 1 (3,26): solo el 62 % eran nivel real 1, y el 44 % recibía nivel 2 y esperaba en la cola del triaje hasta 32 minutos. El nivel 1 asignado es un 0,4 % de los pacientes, y no había sitio para todas ([especificación, «Calibración», paradas](../specs/hito-4.md#calibración) y [«Gravedad latente y triaje», paradas a la puerta](../specs/hito-4.md#gravedad-latente-y-triaje)).

## Decisión

La parada pesa un 0,3 % del catálogo (sigue siendo «< 1 %»), con desviación 0,25 y la menor media de una rejilla de 0,01 con la que, en un año, al menos el 99 % de las paradas es nivel real 1 y al menos el 97 % recibe nivel 1 asignado: 4,21. Su estado es «orientativa, elegida por criterio» (`severity_mean_for`). Los pesos base, el ruido y el sesgo, los umbrales y las marginales de pruebas se rederivan en cascada y se escriben.

Motivo: con el 0,54 % y la gravedad en el umbral, el 44 % de las paradas recibía nivel 2 y esperaba en la cola del triaje; el nivel 1 asignado del 0,4 % no dejaba sitio para todas.

## Alternativas consideradas

- Aceptarlo como límite conocido hasta el circuito de críticos de la v1, o mandar a la puerta por motivo: eran las otras dos opciones abiertas tras la tarea 4.5a ([anexo, tarea 4.5a](../specs/hito-4.md#tarea-45a-el-clinicalsampler-en-el-motor)). Se eligió cambiar la gravedad y el peso de la parada, sin tocar la regla de la puerta.
- Otra desviación: con 0,20 la media sería 4,16, y con 0,30, 4,27 ([anexo, tarea 4.6a](../specs/hito-4.md#tarea-46a-paradas-y-espera-de-resultados-fuera-del-box)).
- Una media de 4,20: deja el nivel 1 asignado en el 96,91 %, por debajo del 97 %. Manda el asignado, porque el ruido del triaje (0,334) dispersa más que la propia parada.

## Consecuencias

- En un año, el 99,975 % de las paradas es nivel real 1 y el 97,05 % va a la puerta. Aportan 0,293 puntos del 0,4 % de nivel 1 asignado (el 73,4 %), y son el 77,8 % del nivel real 1 ([«Gravedad latente y triaje»](../specs/hito-4.md#gravedad-latente-y-triaje)).
- En 60 días de enero y febrero con `config/`, de 120 paradas (67,5 % de nivel real 1, 55,8 % a la puerta) se pasa a 78 (100 % y 98,7 %), con una sola por enfermería.
- Valores rederivados: peso base 0,324, ruido 0,334, sesgo −0,081 y umbrales \[3,341; 1,130; −0,047; −2,164\]. `derive_written_values` ejecuta la cascada y un test comprueba que reproduce el fichero; otra guarda comprueba la condición de la parada con Φ a mano.
- Las huellas clínicas se regeneraron una vez en la tarea 4.6a; `DEFAULT_MIXING_PATIENTS` sube de 20 000 a 25 000, porque con la parada al 0,3 % la validación de la mezcla necesita 21 379 pacientes por contexto ([«Salidas: CLI»](../specs/hito-4.md#salidas-cli)).
