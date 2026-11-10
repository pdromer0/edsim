---
name: tarea-edsim
description: Lleva una tarea de EDsim desde su issue de GitHub hasta el pull request, siguiendo docs/proceso/tarea.md (dependencias, plan, rama, commits, N1 a N3, /code-review, PR y tablero).
argument-hint: N [notas del chat]
disable-model-invocation: true
---

# /tarea-edsim

Argumentos: `$ARGUMENTS`

El primer número es el issue N. El resto son las notas del chat: si precisan algo del issue, mandan las notas. Si no hay número, para y pide N.

## Reglas de toda la tarea

- Lee ahora [docs/proceso/tarea.md](../../../docs/proceso/tarea.md) entero y síguelo paso a paso. Esta skill solo añade lo propio de Claude Code.
- Si un paso necesita algo que no puedes hacer (un permiso denegado, un comando que falla, el tablero inaccesible), para y dilo. No lo rodees.
- Los id del tablero (proyecto, campo Status y sus opciones) se leen en cada uso con el procedimiento de abajo, nunca de memoria.
- Nunca `gh pr merge`. El push solo con el plan aprobado y la N3 en verde.

## Fase 1: en modo plan (solo lectura)

1. `gh issue view N --json number,title,state,body,labels,milestone,blockedBy`. Si no existe o está cerrado, para.
2. Dependencias. Cada nodo de `blockedBy` trae su `state`: si alguno es `OPEN`, para y di cuáles, con su título. No crees el plan ni toques git o el tablero. Compara los números de `blockedBy` con los `#n` de la sección «Depende de» del cuerpo: si no coinciden, avisa del descuadre, pero decide por `blockedBy`.
3. Especificación: la que enlaza la sección «Enlace a la especificación» del issue.
   - Si es un fichero de más de unos 50 KB (`wc -c`), lanza un subagente Explore que, a partir de `grep -n '^#'`, resuma las secciones enlazadas y dé sus rangos de líneas. Después lee tú esos rangos, sobre todo los que dan valores para el plan.
   - Si es más pequeño, léelo por secciones igualmente.
   - Si el enlace no es un fichero (por ejemplo, «Prompt de la P.2»), las notas del chat son la especificación. Sin notas, pregunta.
4. Plan con los seis apartados de `tarea.md`, más tres datos al principio: la rama, que la ficha pasará a «En curso» al aprobarlo, y el esfuerzo de `/code-review` (`high` si el issue tiene la etiqueta `critica`; `medium` si no).
5. Presenta el plan para su aprobación.

## Fase 2: con el plan aprobado

1. Anota la hora de aprobación (`date '+%Y-%m-%d %H:%M'`) para las métricas del PR.
2. Con `git status` limpio: `git switch main && git pull --ff-only`. Después `git switch <rama>`; si dice que la rama no existe, `git switch -c <rama>`. Si la rama ya existía y `git log --oneline <rama>..main` no está vacío, dilo antes de seguir.
3. Mueve la ficha del issue a «En curso» (procedimiento del tablero).
4. Implementa según `tarea.md` (pasos 3 y 5): un commit por paso lógico con N1; la N2 la ejecuta el hook Stop.

## Antes del push

1. `docker compose ps`: si Kafka está en marcha, `docker compose stop`.
2. Avisa de que la N3 suele tardar unos 14 minutos y lánzala con `run_in_background`: `scripts/tests-completos.sh`.
3. A la vez, lanza `/code-review` con la herramienta Skill: skill `code-review`, argumentos `medium main...<rama>`, o `high main...<rama>` si el issue tiene la etiqueta `critica`. Pasa siempre el nivel (sin él, reutiliza el último que se tecleó) y el destino (sin él, compara solo con el *upstream* de la rama).
4. Mientras las dos corren, escribe la entrada del anexo y la descripción del PR en un fichero del *scratchpad*, con la plantilla `.github/pull_request_template.md`, «Closes #N» y la hora de aprobación.
5. Cada hallazgo de la revisión: se corrige (commit con N1) o se explica en el PR. Si las correcciones tocan código o tests, repite la N3.

## Pull request

1. `git push -u origin <rama>`, en una llamada propia.
2. `gh pr create --title "…" --body-file <fichero>`, en otra llamada. Anota la hora de apertura en las métricas (`gh pr edit --body-file` si hace falta).
3. La ficha la lleva a «En revisión» el workflow «Pull request linked to issue» del tablero. Comprueba la columna con `gh issue view N --json projectItems`. Si no está en «En revisión», muévela (procedimiento del tablero) y avisa de que el workflow falló.
4. Mensaje final: el enlace del PR; si el issue tiene la etiqueta `critica`, recuerda a Pedro que escriba `@codex review` en el PR; y recuérdale que haga `/clear` antes de la siguiente tarea.

## Ajustes de la revisión

Commits nuevos en la misma rama, con N1 y, antes del push, N3. Pon al día la sección «Ajustes de la revisión» del PR y la entrada del anexo.

## Procedimiento del tablero

Para mover la ficha del issue N a la columna C:

1. `gh project list --owner pdromer0 --format json --jq '.projects[] | select(.title=="EDsim") | {number, id}'`: el número y el id del proyecto. Si no sale exactamente uno, para.
2. `gh project field-list <número> --owner pdromer0 --format json --jq '.fields[] | select(.name=="Status")'`: el id del campo y el de la opción C, buscada por nombre. Si C no existe, para.
3. `gh project item-list <número> --owner pdromer0 --format json --limit 500 --jq '.items[] | select(.content.type=="Issue" and .content.number==N and .content.repository=="pdromer0/edsim") | {id, status}'`: la ficha.
4. Si no sale: `gh project item-add <número> --owner pdromer0 --url https://github.com/pdromer0/edsim/issues/N --format json --jq .id`. Si falla con «Content already exists» (el añadido automático llegó antes), repite el paso 3.
5. `gh project item-edit --id <ficha> --project-id <id del proyecto> --field-id <campo> --single-select-option-id <opción>`.
6. Comprueba con `gh issue view N --json projectItems` que la ficha está en C.
