# 0095. La verdad no se carga en Postgres en el hito 7

- **Estado:** Aceptada
- **Fecha:** 2026-11-13

## Contexto

La comparación con la verdad podía hacerse en SQL, con la verdad cargada en Postgres, o en Python, leyendo la verdad de los ficheros de la ejecución ([especificación, pieza 6](../specs/hito-7.md#pieza-6--comparar-con-la-verdad)).

## Decisión

- La verdad no se carga en Postgres en este hito.
- El esquema `verdad`, cargado desde los ficheros y con permisos separados de los de bronce, llega en el hito 8 con dbt.

## Alternativas consideradas

- **Cargar la verdad ya en el hito 7:** obligaría a duplicar la comparación en SQL, o dejaría un esquema que nadie usa. Tendrá sentido en el hito 8, para los tests de datos validados con el ground truth.
- **La verdad en el mismo esquema que bronce:** cualquiera que lea bronce leería también las soluciones.

## Consecuencias

- Una sola comparación, en Python (decisión 96). La verdad y la libreta se leen siempre de ficheros; lo registrado, de ficheros o de bronce.

## Qué cambió al implementarla

Nada.
