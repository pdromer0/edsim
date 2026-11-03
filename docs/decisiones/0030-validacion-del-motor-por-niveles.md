# 0030. Validación del motor por niveles, al nivel 0,01

- **Estado:** Aceptada
- **Fecha:** 2026-11-03

## Contexto

Un servicio con λ(t), tres pools, prioridades, desalojo y turnos no tiene fórmula cerrada con la que compararse, como la M/M/1 del hito 1. Hay que comprobar a la vez que el log no se contradice y que sus números son correctos donde existe teoría ([especificación](../specs/hito-3.md#validación-del-motor)).

## Decisión

Se valida por niveles, cada uno ciego a algo:

1. **Invariantes** sobre el log en cada ejecución: conservación, capacidad, tiempo, transiciones, nadie se cuela y desalojo. Cero violaciones.
2. **Leyes operacionales:** Little global y por etapa (2 %) y área de ocupados = suma de las atenciones (10⁻⁹).
3. **Casos de referencia:** a. el triaje con una enfermera y λ constante es una M/G/1, frente a Pollaczek–Khinchine; b. con capacidad infinita, el censo es Mₜ/G/∞, de media m(t).
4. **Condiciones extremas:** capacidad infinita exacta, sin nivel 1, todos del mismo nivel, el escenario a mano de tres boxes y más médicos con la misma semilla.
5. **Regresión:** huella SHA-256 del log y del ground truth.

Las pruebas estadísticas van al nivel 0,01, como en el hito 2 ([ADR 0023](0023-validacion-con-cinco-pruebas.md)); la teoría sale siempre de la configuración.

Motivo: sin fórmula cerrada, cada tipo de comprobación cubre errores que los otros no ven.

## Alternativas consideradas

- Solo invariantes: ven la forma del log, no las duraciones ni el origen de un evento. No detectaron un `test_resulted` adelantado (3.3 C), una valoración reiniciada (3.4 C) ni las pruebas como `timeout` del paciente (3.4 E) ([anexo](../specs/hito-3.md#anexo-guía-de-referencia-del-hito-3)).
- 5 réplicas en la prueba de potencia de la M/G/1: con ρ = 0,77 la espera media varía mucho entre réplicas y la t de Student con 4 grados de libertad y Bonferroni vale 6,25; un efecto del 49 % no se veía. Se usan 10 ([anexo, tarea 3.6](../specs/hito-3.md#tarea-36-estado-métricas-y-validación-del-motor)). La de la Mₜ/G/∞ sí basta con 5.
- Una muestra de 20.000 estancias para m(t): su error sería un 17 % de la semianchura del IC de cada hora; con 200.000, un 5,4 %.
- Tomar la teoría de lo que escribió el motor: el motor se compararía consigo mismo. Un test cambia la mediana del triaje y comprueba que la teoría cambia.

## Consecuencias

- `validate_engine` pasa sus 11 comprobaciones con `config/centro.toml` y semilla 2026 en unos 100 s; las pruebas largas van marcadas `slow` ([ADR 0017](0017-tests-estadisticos-marcados-slow.md)) y comparten una sola ejecución en un *fixture* de sesión.
- Cada tarea comprobó con versiones incorrectas temporales qué tests las detectan, con predicción previa.
- Un sesgo multiplicativo solo lo ve la comprobación con el IC más estrecho para esa magnitud, y Little en una ventana finita puede pasar con errores que se compensan a medianoche: hacen falta tests a mano con episodios que cruzan la frontera.
- El nivel 6 de la especificación, la lectura de trazas en el notebook, queda para la revisión de Pedro.
