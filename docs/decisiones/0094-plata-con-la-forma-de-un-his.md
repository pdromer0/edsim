# 0094. En el hito 8, plata con la forma de las tablas de un HIS

- **Estado:** Aceptada
- **Fecha:** 2026-11-13

## Contexto

Pedro preguntó en la sesión conceptual cómo llegan los datos a analítica en un hospital. Un HIS guarda tablas de estado que se sobrescriben; EDsim guarda un registro de eventos. En un hospital real, analítica casi nunca recibe eventos, sino una extracción de las tablas del HIS ([especificación, pieza 3](../specs/hito-7.md#pieza-3--postgres-timescaledb-y-la-capa-bronce)).

## Decisión

- En el hito 8, la capa **plata** imita las tablas de un HIS (`paciente`, `episodio`, `triaje`, `prueba`, `valoracion` y `destino`), con las correcciones aplicadas.
- **Un HIS simulado** con su base de datos transaccional y CDC va al Backlog (#123).
- El hito 7 se queda en bronce.

## Alternativas consideradas

- **Plata como tablas de eventos limpios:** más fácil de derivar, pero no se parece a lo que recibe un analista. Tendría sentido si el laboratorio solo enseñara *streaming*.
- **Un HIS simulado ya en el hito 7:** una base de datos más y Debezium. Es el escenario más realista de extracción, pero no cabe en este hito; tendría sentido después de la v0, como caso de uso propio.

## Consecuencias

- El diseño tiene las dos formas, en capas: los eventos en bronce y las tablas tipo HIS en plata, derivadas de los eventos (decisión 6).

## Qué cambió al implementarla

Nada: se aplica en el hito 8.
