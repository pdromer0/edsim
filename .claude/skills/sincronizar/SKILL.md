---
name: sincronizar
description: Tras la fusión de un PR de EDsim, comprueba que está fusionado, actualiza main, borra la rama local, revisa el tablero y muestra lo próximo.
argument-hint: "[N del PR]"
disable-model-invocation: true
---

# /sincronizar

Argumentos: `$ARGUMENTS`

No necesita contexto: se lanza tras `/clear`.

## Reglas

- Si cualquier comprobación falla, para y dilo sin seguir con los pasos siguientes.
- Nunca `git push`, `gh pr merge` ni borrar ramas remotas (las borra GitHub). Nunca borres `main`.
- Los id del tablero se leen en cada uso con el procedimiento de abajo, nunca de memoria.

## Pasos

0. **El PR.** Si los argumentos traen un número, ese es N. Si no, mira la primera línea de `git status`. En `main`, pregunta qué PR sincronizar. En otra rama, N es el PR de esa rama: el paso 2 usa `gh pr view` sin número, y si la rama no tiene PR, para. Anota la rama en la que arrancaste.
1. **Árbol limpio.** `git status`: si hay cambios o ficheros sin seguimiento, para.
2. **Fusionado.** `gh pr view N --json number,state,mergedAt,mergeCommit,headRefName,headRefOid,closingIssuesReferences`. Si `state` no es `MERGED` o `mergeCommit` es nulo, para sin tocar nada.
3. **main al día.** `git switch main && git pull --ff-only`.
4. **La fusión está en main.** `git merge-base --is-ancestor <mergeCommit.oid> HEAD`. Si falla, para.
5. **Borrar la rama local `<headRefName>`.**
   - `git log -1 --format=%H refs/heads/<headRefName>` (con `refs/heads/`, para no confundirla con `origin/<headRefName>` ni con una etiqueta). Si la rama no existe, dilo y sigue con el paso 6.
   - `git fetch origin pull/N/head`: trae la punta del PR aunque GitHub ya haya borrado la rama remota.
   - `git merge-base --is-ancestor <punta local> <headRefOid>`. Si la punta local está contenida en el PR (igual o por detrás, por ejemplo si `@claude` metió commits desde GitHub), `git branch -D <headRefName>`. Es `-D` porque, con la fusión squash, `-d` avisa aunque la rama esté fusionada.
   - Si no está contenida, la rama tiene commits que no entraron: para sin borrar y enséñalos con `git log --oneline <headRefOid>..<headRefName>`.
6. **Ramas remotas.** `git fetch --prune`.
7. **Dependencias.** `git diff --name-only <mergeCommit.oid>^ <mergeCommit.oid> -- uv.lock pyproject.toml app/pyproject.toml`. Si sale algún fichero, `uv sync --all-packages --extra kafka`.
8. **Issues cerrados.** Para cada issue M de `closingIssuesReferences`: `gh issue view M --json state,projectItems`.
   - Cerrado y en «Hecho»: bien.
   - Cerrado y fuera de «Hecho» (o sin ficha): muévelo a «Hecho» (procedimiento del tablero) y avisa de que el workflow del tablero falló.
   - Abierto: avisa y no lo cierres; lo decide Pedro.
9. **Resumen.** `git status`, `git log --oneline -3` y las fichas de «Próximo»: `gh project item-list <número> --owner pdromer0 --format json --limit 500 --jq '.items[] | select(.status=="Próximo") | "#\(.content.number) \(.content.title)"'`. Si arrancaste en una rama distinta de `main` y de `<headRefName>`, recuerda a Pedro que vuelva con `git switch <esa rama>`.

## Procedimiento del tablero

Para mover la ficha del issue M a la columna C:

1. `gh project list --owner pdromer0 --format json --jq '.projects[] | select(.title=="EDsim") | {number, id}'`: el número y el id del proyecto. Si no sale exactamente uno, para.
2. `gh project field-list <número> --owner pdromer0 --format json --jq '.fields[] | select(.name=="Status")'`: el id del campo y el de la opción C, buscada por nombre. Si C no existe, para.
3. `gh project item-list <número> --owner pdromer0 --format json --limit 500 --jq '.items[] | select(.content.type=="Issue" and .content.number==M and .content.repository=="pdromer0/edsim") | {id, status}'`: la ficha.
4. Si no sale: `gh project item-add <número> --owner pdromer0 --url https://github.com/pdromer0/edsim/issues/M --format json --jq .id`. Si falla con «Content already exists» (el añadido automático llegó antes), repite el paso 3.
5. `gh project item-edit --id <ficha> --project-id <id del proyecto> --field-id <campo> --single-select-option-id <opción>`.
6. Comprueba con `gh issue view M --json projectItems` que la ficha está en C.
