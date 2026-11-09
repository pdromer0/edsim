# 0050. Tres capas de tests: rápidos sin broker, slow e integración aparte

- **Estado:** Aceptada
- **Fecha:** 2026-11-06

## Contexto

Un sistema en tiempo real tiene tres enemigos de los tests: el tiempo (no se puede esperar un día), el azar del entorno (hilos, red, planificador) y las dependencias externas (un broker). El hook `Stop` ejecuta `pytest -m "not slow"`, y un `-m` en la línea de comandos sustituye al de la configuración ([especificación, pieza 7](../specs/hito-6.md#pieza-7--cómo-se-prueba-un-sistema-en-tiempo-real)).

## Decisión

- **Rápidos**, en `tests/`, sin broker: reloj falso (`FakeClock`), órdenes programadas (`ScriptedControl`), sumidero en memoria y productor falso. Un día entero a ×1 se comprueba en milisegundos.
- **Slow**, marcados como hasta ahora.
- **Integración**, en `tests_integracion/`, fuera de `testpaths`, contra el Kafka de `compose.yaml`, con `scripts/tests-integracion.sh`.

## Alternativas consideradas

- Una marca `kafka` excluida en la configuración: el `-m "not slow"` del hook la anularía y ejecutaría los tests de Kafka sin broker.
- Testcontainers: otra dependencia, y un Kafka distinto del del portátil.
- Probar el pacer con el reloj del sistema: lento y con resultados que dependen del planificador.

## Consecuencias

- La validación del hito es exacta, no estadística: «directo = batch» compara bytes y el pacer se comprueba al nanosegundo.
- `scripts/sello.sh` clasifica `compose.yaml` y `tests_integracion/` como rutas que no afectan a la rápida; las prueba el script de integración.

## Qué cambió al implementarla

- 6.1: la fixture `bootstrap` comprueba en tres pasos el arranque, los metadatos y que cada dirección anunciada se alcanza. Con un listener mal anunciado, el resultado dependía de una carrera de librdkafka (de 10 s a 3 min 30 s); con la comprobación, falla en menos de 1 s y dice la causa.
- 6.3: el reloj falso guarda el tiempo en nanosegundos enteros: en coma flotante, 150 tramos de 0,2 s sumaban 29,999999999999925 s.
- 6.4: los tests de integración usan los topics reales, aislados por un `run_id` único y por los offsets altos anotados antes de publicar.
- 6.5: un módulo `confluent_kafka` falso deja probar sin el extra lo que crea clientes reales.
- 6.6: el vigilante de la conexión se prueba con errores, estadísticas y líneas de librdkafka pasados a mano, y el lector, con un consumidor falso que da mensajes con topic, partición, offset y marca.
