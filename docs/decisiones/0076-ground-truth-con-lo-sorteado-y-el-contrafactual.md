# 0076. El ground truth guarda todo lo sorteado, también el destino contrafactual

- **Estado:** Aceptada
- **Fecha:** 2026-11-10

## Contexto

Todo lo aleatorio del paciente se sortea al llegar, en orden fijo (decisión 24): la paciencia, el destino y la espera de cama existen para todos, aunque luego solo se use una parte. Ningún hospital sabe a dónde habría ido quien se fue, porque no vuelve a pasar por la decisión; el simulador sí lo sabe ([pieza 7](../specs/hito-5.md#pieza-7--el-ground-truth-contrafactual)).

## Decisión

- **El ground truth guarda todo lo sorteado**, también lo que no se usó:
  - la paciencia y su z;
  - las cuatro Gumbel del destino y el destino sorteado, que para quien se fue es el contrafactual;
  - la z de la cama y la espera base.
- **El CSV del ground truth clínico** gana sus columnas al final.
- **`run.json`** registra el modelo.
- **Los ficheros antiguos** se leen como hoy.
- **Nada de esto va al log** (decisión 28).

## Alternativas consideradas

- **Guardar solo lo usado:** no se podría reconstruir cada paciente bit a bit ni medir el daño oculto del abandono.
- **Un fichero aparte para el hito 5:** dos ficheros de verdad por ejecución, y el lector tendría que juntarlos.

## Consecuencias

- Se puede contar cuántos de los que se fueron habrían ingresado, y evaluar un modelo de «predecir el ingreso» también con ellos.
- El emparejamiento de la 4.8a sigue funcionando: dos ejecuciones de modelos distintos no son los mismos pacientes.

## Qué cambió al implementarla

- **5.3, la huella del hito 4** (decisión de Pedro): la verdad del desenlace va en `OutcomeDraws.truth`, y la línea de la huella omite `outcome` solo cuando vale `None`, así que `CLINICAL_TRUTH_FINGERPRINT` no cambió.
- **5.3, el CSV lo decide el modelo, no los episodios:** un run del hito 5 sin episodios tiene igualmente sus 65 columnas.
- **5.3, `run.json` versión 3:** la versión 2 más `schema_version` (4). El modelo sigue siendo `clinico`, y la versión del catálogo dice cuál.
- **5.4 y 5.5, las filas «no usado» de quien se va** (#105): en «Ver la verdad», lo que quien se va nunca alcanza (valoración, pruebas y destino) salía `pending` para siempre. Pasó a `unused`, también el nivel y el triaje de quien se va antes del triaje.
- **5.6, medida:** en el año de la semilla 2026, 23 de los 729 que se fueron habrían ingresado, y ningún grave de verdad se fue.
- **5.7, medida:** en los 89 días del notebook, 55 de los 1.061 que se fueron habrían ingresado (5,2 %), y uno era grave de verdad.
