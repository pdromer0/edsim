# Ciclo de una tarea

Cada tarea de EDsim sale de su issue de GitHub y sigue siempre estos pasos, la haga el agente que la haga. Claude Code los ejecuta con la skill `/tarea-edsim N`; Codex los lee desde [AGENTS.md](../../AGENTS.md). El manual del flujo para personas (tablero, papeles y diagramas) está en [flujo.md](flujo.md).

Los niveles de tests N1, N2 y N3 son los de la sección «Workflow» de [docs/diseno.md](../diseno.md#workflow).

## 1. Arranque

- Lee el issue: `gh issue view N --json number,title,state,body,labels,milestone,blockedBy`. Si está cerrado, para.
- Dependencias: **manda la nativa** (`blockedBy`, la relación «blocked by» de GitHub). Si algún issue que la bloquea sigue abierto, para y dilo. La sección «Depende de» del cuerpo guarda el motivo; si las dos no coinciden, avisa del descuadre, pero decide por la nativa.
- Con el árbol limpio, `git switch main && git pull --ff-only` y crea la rama que indica el issue. Si ya existe (un PR que junta varias tareas), cambia a ella. Si el agente arranca en modo plan, que no deja escribir, la rama se crea al aprobar el plan, como primer paso de la implementación.
- Lee solo las secciones de la especificación que enlaza el issue, y por secciones: primero los encabezados (`grep -n '^#' fichero`) y después los rangos de líneas que interesan. Ver «Cómo leer las especificaciones grandes» en [docs/README.md](../README.md).
- Si las notas del chat precisan algo del issue, mandan las notas.

## 2. Plan

El plan tiene siempre estos apartados:

1. **Contexto y qué cambia.**
2. **Valores a mano**: cada uno con su cálculo escrito, con aritmética o con código independiente de la función probada, nunca de memoria.
3. **Casos límite**, como lista explícita. Como mínimo, se piensa en:
   - enteros enormes;
   - NaN e infinitos;
   - `date` frente a `datetime`;
   - empates y orden de los eventos del mismo instante;
   - listas de distinta longitud;
   - vacíos;
   - el primer y el último elemento.
4. **Versiones incorrectas**, cada una con su predicción firme: qué tests fallan y cuáles siguen pasando.
5. **Comprobaciones**: tests, medidas y comprobaciones a mano.
6. **Cuándo parar y preguntar.**

El plan lo revisan Pedro y el chat; la implementación empieza cuando Pedro lo aprueba.

## 3. Implementación

- Un commit por paso lógico, sin esperar revisión entre pasos. Mensajes con heredoc (`<<'EOF'`) y `git add` de los ficheros por nombre.
- **N1** antes de cada commit: ruff y los ficheros de test del área tocada.
- **N2** al final de cada turno: la rápida con sello (`scripts/tests-rapidos.sh`). En Claude Code y en Codex la ejecuta el hook Stop.

## 4. Antes del push

- **N3**: `scripts/tests-completos.sh`, con Docker parado (`docker compose stop` si Kafka está en marcha), en segundo plano mientras se redacta el PR. El push solo va cuando la N3 termina en verde.
- **Revisión adversaria del propio diff.** En Claude Code, `/code-review` sobre `main...<rama>`, con esfuerzo medio en general y alto en las tareas con la etiqueta `critica`. Lo que encuentre se corrige o se explica en el PR.
- Si las correcciones tocan código o tests, se repite la N3; si solo tocan documentación, no.

## 5. Documentación en el mismo PR

- Una entrada en la sección «Anexo» del documento que enlaza el issue: la especificación del hito o, en las tareas de proceso, `docs/proceso/<tarea>.md`.
- La entrada sigue el formato de las anteriores del anexo (por ejemplo, las de [docs/specs/hito-6.md](../specs/hito-6.md)): **Qué se hizo** (PR, rama, agente, commits), **Decisiones del diff**, **Medidas**, **Versiones incorrectas** (predicción frente a observado), **Revisión** y **Pendiente**.
- Además, lo que la tarea cambie en el diseño o en las especificaciones.

## 6. Pull request

- Con la plantilla [.github/pull_request_template.md](../../.github/pull_request_template.md) y «Closes #N».
- Métricas: el agente pone las que conoce (hora de aprobación del plan y hora de apertura del PR); el resto lo completa el chat.
- El push: Claude Code lo hace con el plan aprobado (su excepción en [CLAUDE.md](../../CLAUDE.md)); Codex pide permiso a Pedro.
- Si la tarea tiene la etiqueta `critica`, recuerda a Pedro que escriba `@codex review` en el PR.
- Recuerda a Pedro que haga `/clear` antes de la siguiente tarea.

## 7. Ajustes de la revisión

- Commits nuevos en la misma rama, con N1, N2 y, antes del push, N3.
- La sección «Ajustes de la revisión» del PR, al día.
- La entrada del anexo, al día.

Tras la fusión, que siempre hace Pedro, `/sincronizar` comprueba la fusión, actualiza `main`, borra la rama local y revisa el tablero ([flujo.md](flujo.md)).
