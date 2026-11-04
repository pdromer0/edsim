# APP-0002. Paquete de app en un workspace de uv

- **Estado:** Aceptada
- **Fecha:** 2026-11-04

## Contexto

La app necesita Streamlit y herramientas de presentación que no deben formar
parte del núcleo. A la vez, sus cambios y los servicios que necesita evolucionan
juntos. La frontera debe seguir siendo comprobable aunque se trabaje en el mismo
entorno ([anexo A.1](../specs/fase-1.md#tarea-a1-esqueleto-de-la-app-y-workspace-de-uv)).

## Decisión

`edsim-app` es un paquete aparte en `app/`, miembro del workspace de uv del
repositorio: depende de `edsim`, con fuente `workspace`, y comparte un solo
`.venv` y `uv.lock`. Tiene sus dependencias, documentación, ADR y etiquetas.

## Alternativas consideradas

- Incluir Streamlit en el paquete del núcleo: haría instalar la interfaz a quien
  solo usa el simulador y borraría la dirección declarada de dependencias
  ([frontera](../specs/fase-1.md#frontera-versiones-y-agente)).
- Separar ya la app en otro repositorio o entorno: los servicios y las páginas
  cambian juntos; el workspace prueba la app contra el núcleo de la rama. Si el
  frontend pasa a JavaScript, una ADR decidirá su ubicación
  ([stack](../specs/fase-1.md#stack),
  [frontera](../specs/fase-1.md#frontera-versiones-y-agente)).

## Consecuencias

- La sincronización habitual es `uv sync --all-packages`. En A.1 se comprobó que
  `uv sync` simple retiraba 24 paquetes, incluida la app y sus dependencias.
  El arranque desde la raíz selecciona el miembro explícitamente con
  `uv run --package edsim-app edsim-app`
  ([PR #29](https://github.com/pdromer0/edsim/pull/29)).
- El entorno compartido no impide por sí mismo un import indebido. Un test
  dinámico en un intérprete nuevo y otro estático con AST comprueban la frontera.
  El job `tests` instala solo el núcleo, sin Streamlit ni pandas; `tests-app`
  instala todo el workspace. Ambos se ejecutan sin filtros por ruta
  ([PR #29](https://github.com/pdromer0/edsim/pull/29)).
- pandas, Jinja2 y Altair se declararon como dependencias directas de la app al
  importarlos. tomlkit pertenece al núcleo porque escribe variantes para sus
  servicios ([PR #31](https://github.com/pdromer0/edsim/pull/31),
  [#32](https://github.com/pdromer0/edsim/pull/32),
  [#33](https://github.com/pdromer0/edsim/pull/33)).
- La serie `APP-0001` registra lo que obliga solo a la app. Las decisiones sobre
  el formato de ejecución o la escritura de variantes pertenecen al núcleo;
  las etiquetas `app-v…` identifican el cierre de la app por separado
  ([documentación](../specs/fase-1.md#documentación-y-decisiones),
  [versiones](../specs/fase-1.md#frontera-versiones-y-agente)).
