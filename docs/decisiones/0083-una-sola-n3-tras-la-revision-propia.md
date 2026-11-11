# 0083. Una sola N3, después de la revisión propia

- **Estado:** Aceptada
- **Fecha:** 2026-11-11

## Contexto

La [ADR 0082](0082-ciclo-de-cada-tarea-en-tarea-md-y-skills.md) lanzaba la N3 y `/code-review` en paralelo antes del push, y repetía la N3 si las correcciones tocaban algo que la N3 ejecuta. La revisión casi siempre encuentra algo, así que la primera N3 casi nunca es la que sube.

En la 5.2 ([anexo](../specs/hito-5.md#tarea-52-perfiles-del-abandono-los-destinos-y-la-espera-de-cama)), `/code-review medium` dio diez hallazgos: cinco corregidos en un commit y cinco explicados. Hubo dos N3 en verde, de 14:00 y 18:03, en total 32 min 3 s. La primera, en paralelo con la revisión, probó un árbol que no llegó a subir: el 43,7 % del tiempo de N3 de la tarea se perdió (840 s de 1.923 s).

## Decisión

Antes del push, en este orden ([tarea.md](../proceso/tarea.md#4-antes-del-push)):

1. `/code-review` con su nivel y su destino (`main...<rama>`), sin la N3 en marcha.
2. Se clasifican todos los hallazgos antes de tocar nada: se corrige (un error, o un arreglo de coste pequeño), se explica (se queda como está) o va a «Pendiente» del PR con su tarea de destino.
3. Las correcciones, cada una en su commit con N1; la N2, en el Stop.
4. Una sola N3 (`scripts/tests-completos.sh`, con Docker parado), en segundo plano mientras se escriben la entrada del anexo y el PR.
5. Push con la N3 en verde. Si la N3 falla, se corrige con N1 y se repite una vez, no una por corrección.

Lo mismo en «Ajustes de la revisión» (Codex y el chat): todas las correcciones de la ronda, cada una con N1, y después una sola N3 antes del push. Si las correcciones de una ronda de ajustes solo tocan documentación o scripts de los hooks, no hay N3: la anterior en verde sigue valiendo. Sigue la excepción de la 0082 para un push que solo lleva documentación, plantillas o una skill.

## Alternativas consideradas

- Mantener el paralelo, con una sola N3 final tras las correcciones: la primera N3 se pierde casi siempre, porque la revisión casi siempre encuentra algo.
- La N3 antes de la revisión: ya descartada en la 0082, porque la revisión espera 14 minutos de tests que no necesita, y un hallazgo corregido obliga a repetirla igual.
- Sin N3 local, solo el CI: se pierde el «verde antes del push», que evita subir un árbol en rojo, y la medida de tiempos de cada tarea en este portátil.

## Consecuencias

- Si la revisión no encuentra nada que corregir, se pierden sus minutos: la N3 empieza más tarde que en paralelo.
- Si encuentra algo, se ahorra al menos una N3, unos 14 minutos, y la N3 que queda prueba y mide el árbol que sube.
- Una regla de repetición dice ahora cuándo: una vez por ronda, no por corrección ([lecciones](../proceso/lecciones.md#proceso-y-agentes)).
- Cambian `tarea.md` (§4 y §7), la skill `/tarea-edsim`, [flujo.md](../proceso/flujo.md), [portabilidad.md](../proceso/portabilidad.md), la sección «Workflow» del [diseño](../diseno.md#workflow), `AGENTS.md` y la plantilla del PR.
