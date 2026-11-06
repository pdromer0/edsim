# 0015. Idiomas del proyecto

- **Estado:** Aceptada
- **Fecha:** 2026-10-27

## Contexto

El proyecto mezcla código, configuración y documentación pensada para el aprendizaje de Pedro ([diseño](../diseno.md#metodología-de-trabajo-con-claude-code-y-cursor)).

## Decisión

- Código, nombres y docstrings en inglés.
- Documentación, especificaciones y mensajes de commit en español.
- Claves de configuración en español.

Motivo: el inglés es el estándar del código, y la documentación sirve al aprendizaje en el idioma de Pedro.

## Alternativas consideradas

No se documentaron alternativas.

## Consecuencias

- Conviven nombres en inglés, como los eventos (`patient_arrived`), con claves de configuración en español, como `peso_base` o `replicas`.
- La convención está recogida en [CLAUDE.md](../../CLAUDE.md).

## Nota de actualización (2026-11-06)

La regla del inglés es para el código del paquete: `src/` y `app/src/`. Los tests siguen, cada zona, la práctica que tienen desde que existen, y la nota la escribe sin cambiar ningún test:

- **Tests del núcleo (`tests/`) en español**: nombres de los tests (`test_…`), docstrings y comentarios, desde el hito 1; las funciones auxiliares y las fixtures pueden ir en inglés, como los identificadores del paquete que usan (`center`, `simulate`, `run_hand`, `make_profiles`, en muchos ficheros). Son material de aprendizaje: cada test cuenta en el idioma de Pedro qué comprueba y por qué, con los valores a mano de la especificación.
- **Tests de la app (`app/tests/`) en inglés**, como el código de la app que acompañan, que escribe Codex.
- En las dos zonas, los identificadores que un test importa del paquete siguen en inglés.

Motivo: la práctica no estaba escrita, y en el PR #44 (tarea 4.5a) Codex marcó como P1 los tests nuevos del núcleo, en español, por la regla «código, nombres y docstrings en inglés». La regla P1 de [AGENTS.md](../../AGENTS.md) dice ahora que romper la convención es usar en una zona el idioma de la otra. La decisión no cambia para el código.

Precisión de la misma fecha, por el P1 de Codex en el PR #46 (tarea 4.6a), que marcó los auxiliares nuevos en inglés de un test del núcleo (`room_log`, `run_hand`): en `tests/` lo que va en español son los nombres de los tests, los docstrings y los comentarios; los auxiliares y las fixtures ya iban en inglés en toda la carpeta, y renombrar solo los nuevos dejaría ese fichero distinto del resto.
