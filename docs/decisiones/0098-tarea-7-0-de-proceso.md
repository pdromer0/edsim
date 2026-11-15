# 0098. Una tarea 7.0 de proceso con siete mejoras del flujo

- **Estado:** Aceptada
- **Fecha:** 2026-11-13

## Contexto

El balance del hito 5 propuso seis mejoras de velocidad, y el piloto de `@claude` en el PR quedó pospuesto. Los errores de los planes del hito 5 estaban en lo que interpretaban, no en la aritmética ([balance del hito 5](../specs/hito-5.md#propuestas-de-velocidad)).

## Decisión

Una tarea 7.0 de proceso, antes de las de código, con siete mejoras:

1. el formato del plan: ocho apartados, con «Lo que el plan interpreta» y «Diferencias con las notas del chat», y los valores a mano con su cálculo ejecutado;
2. el subagente «revisor del plan» (#110), en las tareas con la etiqueta `critica`;
3. las skills con `gh api` REST, que funciona en local y en la nube;
4. la nube por defecto, salvo lo que necesita Docker o el navegador;
5. la revisión del chat a la medida;
6. la Release lanzable sola;
7. el piloto `@claude` en el PR.

## Alternativas consideradas

- **Repartir las mejoras entre las tareas del hito:** cada tarea mezclaría su contenido con un cambio de proceso, y la primera tarea crítica (7.1) no tendría el revisor. Tendría sentido con una o dos mejoras pequeñas.
- **Una tarea de proceso fuera del hito (serie P):** las mejoras se estrenan en este hito, así que van con él.

## Consecuencias

- La 7.1 estrena el revisor del plan, y las tareas de la pista A van en la nube.
- El tablero sigue en GraphQL (`gh project`): en la nube lo mueve Pedro.

## Qué cambió al implementarla

- **7.0, los permisos de `gh api` en tres niveles** (ajuste del chat): las lecturas, con la ruta justo detrás de `gh api`, pasan sin aviso; las escrituras llevan `-X` delante, y solo abrir y editar el PR pasan sin aviso; la fusión y `DELETE`, denegadas. La denegación de la fusión no puede ser `*merge*`, que denegaba también las lecturas que piden `merged` en el `--jq` (`d3973eb`).
- **7.0:** «fusionado» es `merged == true`, porque un PR abierto también trae `merge_commit_sha`. Los issues que cierra un PR salen de una regex sobre su cuerpo, que coincide con GraphQL en 40 de 40 PR.
- **7.0:** la etiqueta de la Release se construye (`v0.H-hitoH`); un grep daba varias por especificación.
- **7.0, el piloto `@claude`**, con un comentario normal, porque la acción solo se ejecuta con el `claude.yml` de `main`: 43 s del comentario al commit, un commit en un fichero y el CI en verde. La condición nueva (autor `pdromer0` y texto que empieza por la mención) se comprobó tras la fusión, el 14 de noviembre, con dos comentarios en el #114: el que empezaba por la mención se ejecutó, y la respuesta del bot y el que solo la nombraba salieron *skipped*.
- **7.1, el primer uso del revisor del plan:** encontró los seis puntos que cambiaron el plan, incluido el único error de hecho, y el chat no añadió nada que lo cambiara. En la 7.4, dos dudas, las dos aplicadas.
- **Hito 7, la nube:** la 7.1, la 7.2, la 7.3 y la 7.6, y la segunda mitad de la 7.5 tras los cuelgues de WSL. Sus N3 en la nube tardaron entre 12:52 y 17:18, y la de la 7.4, en local, 13:50. El balance del hito tiene la comparación.
