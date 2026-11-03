# 0025. Tres pools con prioridad `(nivel, llegada)` y desalojo solo del nivel 1

- **Estado:** Aceptada
- **Fecha:** 2026-11-03

## Contexto

El diseño fija las reglas de flujo de urgencias: el triaje se hace en orden de llegada, porque antes no se conoce la prioridad; después, boxes y médicos atienden por nivel, y un crítico no espera ([especificación](../specs/hito-3.md#recursos-prioridad-y-desalojo)). Los profesionales son pools anónimos ([ADR 0003](0003-profesionales-como-pools-anonimos.md)). Un paciente vuelve a pedir recursos más tarde (reevaluación, vuelta tras un desalojo), y su lugar en la cola no debería depender de cuándo los pide.

## Decisión

- **Enfermería de triaje:** FIFO.
- **Boxes:** `PreemptiveResource` con prioridad `(nivel, llegada)`. El nivel 1 desaloja solo a pacientes de nivel mayor, nunca a otro nivel 1. El desalojado vuelve a la cola con su misma clave y reanuda el tiempo pendiente. El box del desalojado pasa al nivel 1 que lo desaloja.
- **Médicos:** `PriorityResource` con la misma clave, sin desalojo.
- **Laboratorio:** un proceso propio de cada paciente, que sigue corriendo si el paciente es desalojado.
- El box se retiene toda la estancia; el médico, solo en cada valoración.

Motivo: son las reglas de flujo del diseño; con la tupla, el orden no depende de cuándo se pide el recurso; y retener el box toda la estancia lo convierte en el cuello de botella realista.

## Alternativas consideradas

- Prioridad solo por nivel: quien pide tarde se coloca detrás de los de su nivel que pidieron antes, aunque llegara antes. Falló "nadie se cuela" incluso en colas normales ([anexo, tarea 3.4](../specs/hito-3.md#tarea-34-prioridad-y-desalojo)).
- Boxes FIFO, sin prioridad ni desalojo: con la configuración real la media de espera de box casi no cambia (unos 3,5 min), pero el nivel 1 espera 3,1 min en lugar de 0. La prioridad no reduce la espera: la reparte.
- Que el nivel 1 pida siempre con `preempt=True`: con la tupla sola, un nivel 1 que llegó antes desalojaría a otro que llegó después. `should_displace` decide al pedir, mirando `boxes.users`, porque SimPy solo desaloja en el instante de la petición.
- Dar al nivel 1 el box de número más bajo que se libere en el mismo instante: SimPy le entrega la plaza del desalojado en la misma llamada, y otros eventos del instante caben entre la interrupción y la concesión. El traspaso sigue lo que hace SimPy, fijado en su contrato.
- Reiniciar la valoración interrumpida: ninguna invariante lo ve, pero cambia los instantes del escenario a mano.
- Pruebas como `timeout` del propio paciente: un desalojo detendría el reloj del laboratorio.

## Consecuencias

- `tests/test_simpy_contract.py` fija el comportamiento de SimPy 4.1.2 del que depende la decisión: la clave `(priority, instante, not preempt)`, a quién desaloja, el orden de interrupción y concesión, y que solo se intenta la cabeza de la cola.
- Dos invariantes nuevas, "nadie se cuela" y "desalojo". "Nadie se cuela" solo compara con quien esperaba desde un instante estrictamente anterior, porque dentro de un instante el orden del fichero no es el de las concesiones.
- Con la configuración real hubo 4 desalojos en 14 días: el desalojo se ejercita con escenarios a mano y una prueba de estrés con mínimos exigidos.
- Hallazgo para el hito 4: con un triaje FIFO para todos, el nivel 1 tarda unos 9 min hasta el médico, frente al "inmediato" de Manchester.
