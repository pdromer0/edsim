# Ciclo de una tarea

Cada tarea de EDsim sale de su issue de GitHub y sigue siempre estos pasos, la haga el agente que la haga. Claude Code los ejecuta con la skill `/tarea-edsim N`; Codex los lee desde [AGENTS.md](../../AGENTS.md). El manual del flujo para personas (tablero, papeles y diagramas) está en [flujo.md](flujo.md).

Los niveles de tests N1, N2 y N3 son los de la sección «Workflow» de [docs/diseno.md](../diseno.md#workflow).

## 1. Arranque

- Lee el issue con sus comentarios, por REST, que funciona en local y en la nube (GraphQL da 403 en la nube): `gh api repos/pdromer0/edsim/issues/N` y `gh api repos/pdromer0/edsim/issues/N/comments --paginate`. Si está cerrado o es un PR (trae la clave `pull_request`), para.
- Dependencias: **manda la nativa** (`gh api repos/pdromer0/edsim/issues/N/dependencies/blocked_by --paginate`, la relación «blocked by» de GitHub). Si algún issue que la bloquea sigue abierto, para y dilo. La sección «Depende de» del cuerpo guarda el motivo; si las dos no coinciden, avisa del descuadre, pero decide por la nativa.
- Dónde corre: lo dice el issue en «Dónde y modelo». Por defecto, en la nube; en local, lo que necesita Docker, la app en el navegador o ficheros del portátil ([flujo.md](flujo.md#dónde-corre-cada-tarea)). En la nube, la rama es la del issue, no la `claude/*` que propone la sesión.
- Con el árbol limpio, `git switch main && git pull --ff-only` y crea la rama que indica el issue. Si ya existe (un PR que junta varias tareas), cambia a ella. Si el agente arranca en modo plan, que no deja escribir, la rama se crea al aprobar el plan, como primer paso de la implementación.
- Lee solo las secciones de la especificación que enlaza el issue, y por secciones: primero los encabezados (`grep -n '^#' fichero`) y después los rangos de líneas que interesan. Ver «Cómo leer las especificaciones grandes» en [docs/README.md](../README.md).
- Las notas del chat van como comentario «Notas del chat» del issue; el argumento de la skill queda para lo efímero de esa sesión. Si un comentario o el argumento precisan algo del cuerpo, mandan ellos; entre dos comentarios que se contradicen, el más reciente.
- Si la tarea no tiene fichero de especificación (el enlace no es un fichero o está vacío), la especificación son el cuerpo y los comentarios del issue. Si no basta, se pregunta.

## 2. Plan

El plan tiene siempre estos apartados:

1. **Contexto y qué cambia.**
2. **Lo que el plan interpreta**: todo lo que no está literalmente en la especificación ni en las notas del chat (un nombre, una población, un orden, un caso que la especificación no cubre). Es donde estuvieron los errores de los planes del hito 5, y lo que mira primero quien revisa.
3. **Diferencias con las notas del chat**: lo que el plan hace distinto de lo que dicen las notas, y por qué. Si no hay, se dice.
4. **Valores a mano**: cada uno con su cálculo **ejecutado**, con código independiente de la función probada (un script temporal; en Claude Code, en el *scratchpad*), y su salida pegada. Nunca de memoria ni con aritmética de cabeza.
5. **Casos límite**, como lista explícita. Como mínimo, se piensa en:
   - enteros enormes;
   - NaN e infinitos;
   - `date` frente a `datetime`;
   - empates y orden de los eventos del mismo instante;
   - listas de distinta longitud;
   - vacíos;
   - el primer y el último elemento.
6. **Versiones incorrectas**, cada una con su predicción firme: qué tests fallan y cuáles siguen pasando.
7. **Comprobaciones**: tests, medidas y comprobaciones a mano.
8. **Cuándo parar y preguntar.**

El plan es corto y se lee de un vistazo: el detalle (tablas largas, listas de ficheros, salidas completas de los cálculos) va al PR, no al plan.

En las tareas con la etiqueta `critica`, antes de enseñar el plan lo revisa con un contexto limpio el subagente `revisor-plan` de Claude Code ([.claude/agents/revisor-plan.md](../../.claude/agents/revisor-plan.md)): recalcula los valores a mano y devuelve lo que el plan interpreta, sus diferencias con las notas y los valores que no cuadran. Su informe va al principio del plan.

El plan lo aprueba Pedro, y la implementación empieza entonces. El chat lo revisa antes en las tareas críticas o con conceptos nuevos, más lo que marque el revisor del plan ([flujo.md](flujo.md#papeles)).

## 3. Implementación

- Un commit por paso lógico, sin esperar revisión entre pasos. Mensajes con heredoc (`<<'EOF'`) y `git add` de los ficheros por nombre.
- **N1** antes de cada commit: ruff y los ficheros de test del área tocada.
- **N2** al final de cada turno: la rápida con sello (`scripts/tests-rapidos.sh`). En Claude Code y en Codex la ejecuta el hook Stop.

## 4. Antes del push

Primero la revisión y sus correcciones; después, **una sola N3** ([ADR 0083](../decisiones/0083-una-sola-n3-tras-la-revision-propia.md)):

1. **Revisión adversaria del propio diff**, sin la N3 en marcha. En Claude Code, `/code-review` sobre `main...<rama>`, con esfuerzo medio en general y alto en las tareas con la etiqueta `critica`.
2. **Se clasifican todos los hallazgos antes de tocar nada:** se corrige (un error, o un arreglo de coste pequeño), se explica (se queda como está) o va a «Pendiente» del PR con su tarea de destino. Cada uno va a la sección «Revisión propia (/code-review)» del PR con su destino.
3. **Las correcciones**, cada una en su commit con N1; la N2, en el Stop.
4. **Una sola N3**: `scripts/tests-completos.sh`, con Docker parado (`docker compose down` si Kafka está en marcha), en segundo plano mientras se escriben la entrada del anexo y el PR. En las tareas que tocan Kafka, `scripts/tests-integracion.sh` va después de la N3, no a la vez: levanta el Kafka de `compose.yaml`, y la N3 se mide con Docker parado.
5. **El push, con la N3 en verde.** Si la N3 falla, se corrige con N1 y se repite una vez, no una por corrección. Si vuelve a fallar, el agente para y lo dice.

Cuándo no hay N3:

- **En el primer push**, solo si toda la rama es documentación, plantillas o una skill, y con la autorización de Pedro, porque el CI lo comprueba igual ([ADR 0082](../decisiones/0082-ciclo-de-cada-tarea-en-tarea-md-y-skills.md)). Que las correcciones de la revisión solo toquen documentación no basta: esta es la primera N3 sobre el código de la rama.
- **En una ronda de ajustes** (§7), si sus correcciones solo tocan documentación o scripts de los hooks: la última N3 en verde sigue valiendo para todo lo que la N3 ejecuta.

La N3 no ejecuta los scripts de los hooks (`.claude/hooks/`, `.codex/`): se verifican a mano, anotando la comprobación en el PR. Una rama que los cambia no es «solo documentación».

## 5. Documentación en el mismo PR

- Una entrada en la sección «Anexo» del documento que enlaza el issue: la especificación del hito o, en las tareas de proceso, `docs/proceso/<tarea>.md`.
- La entrada sigue el formato de las anteriores del anexo (por ejemplo, las de [docs/specs/hito-6.md](../specs/hito-6.md)): **Qué se hizo** (issue, rama, agente, commits; el número del PR no, porque la entrada se escribe antes de abrirlo), **Decisiones del diff**, **Medidas**, **Versiones incorrectas** (predicción frente a observado), **Revisión** y **Pendiente**.
- Además, lo que la tarea cambie en el diseño o en las especificaciones.

## 6. Pull request

- Con la plantilla [.github/pull_request_template.md](../../.github/pull_request_template.md) y «Closes #N».
- Métricas: el agente pone las que conoce (hora de aprobación del plan y hora de apertura del PR); el resto lo completa el chat.
- El push: Claude Code lo hace con el plan aprobado (su excepción en [CLAUDE.md](../../CLAUDE.md)); Codex pide permiso a Pedro.
- Si la tarea tiene la etiqueta `critica`, recuerda a Pedro que escriba `@codex review` en el PR.
- Recuerda a Pedro que haga `/clear` antes de la siguiente tarea.

## 7. Ajustes de la revisión

- Las mismas reglas que antes del push: primero se clasifican todos los ajustes de la ronda; después, las correcciones en commits nuevos en la misma rama, cada uno con N1 (y la N2 en el Stop), y al final una sola N3 antes del push. Si las correcciones de la ronda solo tocan documentación o scripts de los hooks, no hay N3: la última en verde sigue valiendo para todo lo que la N3 ejecuta (§4, «Cuándo no hay N3»).
- La sección «Ajustes de la revisión» del PR, al día.
- La entrada del anexo, al día.

Tras la fusión, que siempre hace Pedro, `/sincronizar` comprueba la fusión, actualiza `main`, borra la rama local y revisa el tablero ([flujo.md](flujo.md)).
