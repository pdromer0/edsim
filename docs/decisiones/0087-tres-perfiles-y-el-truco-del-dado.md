# 0087. Tres perfiles y el truco del dado: el perfil es solo el umbral

- **Estado:** Aceptada
- **Fecha:** 2026-11-13

## Contexto

Comparar un hospital cuidadoso con uno desastroso sobre el mismo día solo sirve si la diferencia viene del perfil y no de la suerte. Es el problema que resolvieron los números comunes del hito 4 (decisión 43) ([especificación, pieza 2](../specs/hito-7.md#pieza-2--perfiles-y-azar-el-truco-del-dado)).

## Decisión

- **Tres perfiles** (limpio, realista y hostil) en `config/registro_clinico.toml`, con el estado de cada valor (calibrado, derivado u orientativo), como los perfiles clínicos (decisión 37).
- **Un dado por evento y despiste**, con consumo fijo, sea cual sea el perfil. El perfil solo pone el umbral, así que lo que falla en el realista también falla en el hostil.
- **Semilla propia**, por defecto la de la ejecución, en un flujo que no comparte con el motor.

## Alternativas consideradas

- **Sortear cada perfil por separado:** la diferencia entre perfiles mezclaría el perfil con el azar. Tendría sentido si se quisiera medir la variabilidad entre hospitales distintos con el mismo perfil, no el efecto del perfil.
- **Un parámetro de «suciedad» único:** más simple, pero no deja ajustar cada despiste ni cada sistema.

## Consecuencias

- Comparar perfiles mide el perfil: con la semilla 2026, los olvidos del realista están todos dentro de los del hostil (7.6).
- Ninguna fuente da tasas de despiste de un servicio de urgencias: todas quedan como «orientativo».

## Qué cambió al implementarla

- **7.2, el flujo** (`c96c247`): `StreamDice(seed)` usa el hijo 10 de `child_streams(semilla, 11)` y una llamada `random(13)` por tirada. Las `z` son la inversa de la normal de su uniforme, con `max(u, 2⁻⁵³)`. No se usa `standard_normal` porque el *ziggurat* gasta un número variable de bits y su flujo puede cambiar entre versiones de numpy: con uniformes, el consumo es fijo de verdad.
- **7.2, la inclusión «realista ⊂ hostil»** se cumple con dos salvedades que salen de las tasas:
  - la corrección va al revés: el hostil corrige menos, 0,3 frente a 0,5;
  - el vacío se une al erróneo, porque `destino` es el único campo de `disposition_decided` y `patient_departed`.

  V7 (un dado distinto por perfil) hace fallar 15 tests.
- **7.2, los valores:** ninguno cambió en la búsqueda de fuentes. Gordon 2008, Ward 2013 y un estudio de 1994 sobre relojes dan órdenes de magnitud de los tiempos; ninguna fuente da tasas de olvido, vacío, erróneo, duplicado o corrección.
- **7.6, lo que pesa en la clase `con_despistes`:** la 7.2 escribió que era «sobre todo el reloj», y no es así. Con 14 días de `config/` y la semilla 2026, la clase es el 66,7 % de lo escrito con el realista y el 99,8 % con el hostil. Dentro de ella, en el realista manda el **retraso** (en el 81,7 % de las filas, por las tasas de 0,60 del triaje y 0,70 del HIS; el reloj, en el 32,6 %), y en el hostil, el **reloj** (en el 100 %). La 7.6 corrigió la especificación y la 7.7, el comentario del TOML.
