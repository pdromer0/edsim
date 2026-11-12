---
name: cerrar-hito
description: Cierra un hito de EDsim desde el issue de su tarea de cierre — ADR con lo que cambió al implementarlos, diario, diseño, manual de la app, balance, lecciones, README y AGENTS.md — y, tras la etiqueta de Pedro, publica la Release.
argument-hint: N [notas efímeras de esta sesión]
disable-model-invocation: true
---

# /cerrar-hito

Argumentos: `$ARGUMENTS`

N es el número del **issue** de la tarea de cierre (por ejemplo, el #75 cerró el hito 5), no el del PR. El resto es lo efímero de esta sesión. Si no hay número, para y pide N.

## Reglas de toda la tarea

- El cierre es una tarea más: sigue **entera** [la skill `/tarea-edsim`](../tarea-edsim/SKILL.md) con este N (modo plan, dependencias, plan, rama, tablero, commits con N1, `/code-review`, N3, PR). Esta skill solo añade lo que hay que escribir al cerrar un hito y la Release.
- En local, no en la nube: el proxy de la nube rechaza GraphQL (tablero) y las etiquetas.
- Cada cifra que escribas sale del anexo, del registro de calibración o de un comando (`gh pr view`, `wc -c`, un script en el scratchpad), nunca de memoria. Si dos fuentes no coinciden, para y pregunta.
- Lo que digas de la app (un botón, a qué página lleva, en qué orden salen las secciones) se comprueba en su código antes de escribirlo.
- Nada de lo que propone el balance se implanta en el cierre.

## Fase 1: el inventario del plan

Además de lo que pide `/tarea-edsim`, el plan lleva estas listas, sacadas de la especificación del hito (léela por secciones):

1. **Las decisiones:** la tabla «Decisiones del hito», una fila por ADR (número = 66 + n en el hito 5; en otros hitos, el que diga la especificación). Para cada una, lo que no puede faltar en «Qué cambió al implementarla». Sale de las secciones de cada tarea del anexo: «Decisiones del diff», los ajustes de la aprobación, «Revisión» y «Pendiente».
2. **Lo que el anexo dejó para el cierre:** las líneas del anexo que nombran la tarea de cierre (en el hito 5, `grep -n '5\.8' docs/specs/hito-5.md`). Cada pendiente, con su destino en el plan.
3. **Los pendientes que ya son issues:** `gh issue list --state all --search "<palabras del pendiente>"`. Si el anexo dice «sin tarea» o «issue redactado en el PR» y el issue existe, la especificación pasa a citarlo.
4. **Los motivos que el anexo desmiente:** si la revisión de una tarea corrigió una afirmación de la especificación (un motivo, una garantía), el ADR la escribe bien y la especificación se corrige en los dos sitios donde aparezca.
5. **El manual de la app:** una tabla «lo que ganó la app en el hito → dónde lo cuenta `app/README.md` → dónde lo cuenta la ayuda «¿Qué estoy viendo?»». Lo que falte se escribe. Si algo no se puede explicar sin un cambio en la app, se le pregunta a Pedro.
6. **Los cambios del diseño**, para el visto bueno de Pedro: catálogo de eventos, objetivos de calibración, hoja de ruta (el hito cerrado y la tabla «Para versiones posteriores») y registro de decisiones.
7. **«Pedro sabe explicar»:** los conceptos de los criterios de aceptación del hito, más los que pidan las notas del chat.

## Fase 2: lo que se escribe

Un commit por bloque. Los ficheros de código de la app llevan N1 con sus tests; la documentación, ruff y nada más.

1. **ADR** en `docs/decisiones/`, con la plantilla de su README:
   - estado «Aceptada» y fecha de la sesión conceptual;
   - «Qué cambió al implementarla», con la tarea y el commit de cada cambio, como el [ADR 0066](../../../docs/decisiones/0066-run-id-del-directo.md);
   - un ADR sin cambios lo dice («Nada»);
   - el índice de `docs/decisiones/README.md`, en su orden numérico.
2. **Especificación del hito:**
   - las correcciones de la fase 1;
   - la sección `## Balance del hito`, antes del anexo, con «Qué se entregó y dónde», las cifras (PR, commits y minutos de la apertura a la fusión, calculados con un script; issues que salieron; N3; paradas) y las propuestas de velocidad, numeradas y sin implantar.
3. **Diseño** (`docs/diseno.md`), lo aprobado en la fase 1:
   - las filas nuevas del registro de decisiones, cada una con su ADR;
   - el párrafo de arriba del registro, al día.
4. **Diario** `docs/diario/hito-N.md`:
   - una entrada por tarea, con el formato de `docs/diario/README.md` y la fecha de fusión de su PR;
   - la sección «Pedro sabe explicar», una viñeta por concepto con las cifras del hito;
   - «Reflexiones de Pedro», vacía.
5. **App:**
   - `app/README.md` y las ayudas, según la tabla de la fase 1;
   - en `app/docs/specs/incrementos.md`, el incremento del hito pasa a cerrado, con su etiqueta `app-v…` y el commit al que apunta (`git log -1 <etiqueta>`).
6. **Proceso:**
   - las lecciones nuevas en `docs/proceso/lecciones.md`, cada una en su sección y con la tarea entre paréntesis;
   - la sección 14 de `docs/proceso/portabilidad.md`, con el resultado de cada pieza probada en el hito;
   - `docs/proceso/flujo.md`, si cambió una práctica.
7. **Portada:**
   - `AGENTS.md`: «Hito en curso» (el siguiente, con su especificación o, si aún no existe, la hoja de ruta) y «Último hito cerrado»;
   - `README.md`: el estado;
   - `docs/README.md`: la tabla de tamaños, con `wc -c`.
8. **La entrada de la tarea de cierre** en el anexo, y el PR.

**N3:**
- si la rama toca código (la app, el paquete), una N3 como en cualquier tarea;
- si solo toca documentación y skills, sin N3, con el permiso de Pedro (`tarea.md` §4).

## Después de la fusión: la Release

1. Pedro crea la etiqueta del hito (`vX.Y-hitoN`) sobre la fusión del cierre. No la crees tú.
2. Comprueba que existe en GitHub: `gh api repos/pdromer0/edsim/git/refs/tags/<etiqueta>`.
3. Escribe las notas en un fichero del scratchpad:
   - qué trae el hito, en tres o cuatro frases;
   - las decisiones, con enlace a sus ADR;
   - el balance, en resumen;
   - lo que queda en el Backlog.

   Enséñaselas a Pedro.
4. Con su visto bueno: `gh release create <etiqueta> --title "Hito N — <título>" --notes-file <fichero>`.
5. Comprueba con `gh release view <etiqueta>` y dale el enlace.
