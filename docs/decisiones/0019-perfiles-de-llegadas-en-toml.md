# 0019. Perfiles de llegadas en TOML normalizados a media 1

- **Estado:** Aceptada
- **Fecha:** 2026-10-29

## Contexto

La tasa de llegadas es una base diaria multiplicada por un factor horario, uno semanal y uno mensual ([especificación](../specs/hito-2.md#modelo-de-llegadas)). Quien calibra un centro piensa en porcentajes ("el lunes llega el 16 % de la semana"), no en factores de tasa. Y si los factores no tienen media 1, la base deja de ser las urgencias al día de media anual.

## Decisión

- El perfil vive en `config/llegadas.toml`, con claves en español, y se lee con `tomllib`.
- Los repartos horario y semanal se escriben en porcentaje; los meses, como factores de tasa diaria.
- `ArrivalProfile` los valida y normaliza en `__post_init__`: h y d a media 1, y el factor mensual a media 1 ponderada por los días de cada mes.

Motivo: parámetros en los términos que entiende un clínico, sin dependencias nuevas, y una base que conserva su significado.

## Alternativas consideradas

- Porcentajes también para los meses: un 9,31 % del año en un mes de 31 días es un factor 1,10, no 9,31/8,33. Mezclar la duración del mes con la tasa es una trampa.
- Usar los valores tal como se escriben, sin normalizar: la media anual dejaría de ser la base cuando los valores no cuadran del todo (la de los meses daba 1,0007).

## Consecuencias

- No puede existir un perfil inválido: los errores nombran la clave TOML y la posición, por ejemplo `reparto_horario[3] must be positive`.
- Los repartos no tienen que sumar exactamente 100, y normalizar dos veces no cambia nada.
- Los tests usan su propio perfil (`tests/data/llegadas_ejemplo.toml`) y un test aparte comprueba que el fichero real es válido: recalibrar el centro no rompe los valores calculados a mano.
- `dataclasses.replace` vuelve a normalizar y puede cambiar el último bit de los factores; los tests que necesitan otra variante cargan una copia del TOML.
