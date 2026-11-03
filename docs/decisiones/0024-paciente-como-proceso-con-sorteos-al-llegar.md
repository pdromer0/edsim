# 0024. El paciente como proceso SimPy, con todos sus sorteos al llegar

- **Estado:** Aceptada
- **Fecha:** 2026-11-03

## Contexto

El motor del hito 3 tiene que recorrer la máquina de estados del diseño con cada paciente: triaje, box, médico, pruebas, reevaluación y salida ([especificación](../specs/hito-3.md#el-paciente-como-proceso)). Las esperas dependen de la plantilla y de la cola, pero lo que le pasa al paciente (su nivel, sus duraciones, si tiene pruebas, su destino) no debería depender de ellas: es la base para comparar dos plantillas con los mismos pacientes. Además, el hito 4 sustituirá el modelo clínico provisional por motivos y gravedad latente.

## Decisión

- Cada paciente es un proceso SimPy: los estados son los `yield` y cada transición emite su evento.
- Todo lo aleatorio del paciente se sortea al llegar, en orden fijo y aunque no se use: nivel; duraciones de triaje, valoración y reevaluación; si tendrá pruebas y su tiempo de respuesta; y destino.
- Cada fuente tiene su flujo, de `child_streams(seed, 5)` ([ADR 0007](0007-un-flujo-aleatorio-por-fuente.md)): llegadas, nivel, duraciones, pruebas y destino.
- El muestreo va detrás de una función inyectable que recibe la llegada: `sampler(arrival)`.

Motivo: el paciente k es el mismo con cualquier plantilla (números aleatorios comunes), y el hito 4 cambia el muestreo sin tocar el motor.

## Alternativas consideradas

- Sortear cuando se necesita, por ejemplo al asignar el box: el orden de asignación cambia con la plantilla, y con él los valores de cada paciente. Fallaron 7 tests en la tarea 3.3, entre ellos "otra plantilla" y la capacidad infinita ([anexo, tarea 3.3](../specs/hito-3.md#tarea-33-el-paciente-como-proceso)).
- Sortear solo lo que se usa (el tiempo de respuesta solo si hay pruebas): aunque cada fuente tenga su flujo, el número de sorteos depende de lo que salga, y cambiar una probabilidad desplaza los valores de todos los pacientes siguientes. Separar los flujos no basta ([anexo, tarea 3.1](../specs/hito-3.md#tarea-31-configuración-del-centro-y-sorteos-del-paciente)).
- Un muestreador que no recibe la llegada: hoy no la usa, pero la mezcla de casos del hito 4 dependerá de la hora y de la estación, y habría que cambiar la interfaz del motor.

## Consecuencias

- Cambiar la plantilla no cambia ningún valor del ground truth de los episodios, y un test lo comprueba. "Más médicos" se valida con una diferencia emparejada que ve un efecto de 3,7 min con 10 réplicas.
- Cada paciente consume siempre los mismos números de cada flujo: 1 uniforme de nivel, 3 lognormales, 1 uniforme y 1 lognormal de pruebas y 1 uniforme de destino.
- Los tests y los escenarios didácticos construyen pacientes exactos a mano con un muestreador propio (`engine/scenarios.py`).
- Las invariantes no ven si los sorteos se hacen en el momento correcto: solo lo detectan los tests que fuerzan colas o conocen un orden ([anexo, tarea 3.3](../specs/hito-3.md#tarea-33-el-paciente-como-proceso)).
