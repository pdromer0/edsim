# 0104. Ocho tablas en plata, paciente–episodio 1:N, todas las ejecuciones

- **Estado:** Aceptada
- **Fecha:** 2026-11-16

## Contexto

En un hospital, analítica casi nunca recibe eventos, sino una extracción de las tablas del HIS (decisión 94). Plata imita esas tablas para que los ejercicios del laboratorio se parezcan al trabajo real ([pieza 3](../specs/hito-8.md#pieza-3--el-modelo-de-un-his-grano-claves-y-relaciones)).

## Decisión

- Ocho tablas: las seis de la decisión 94 (`paciente`, `episodio`, `triaje`, `valoracion`, `prueba` y `destino`) más `ubicacion` y `plantilla`.
- Paciente–episodio, 1:N (a pregunta de Pedro), aunque hoy los datos sean 1:1 porque el motor no simula reingresos.
- Todas las ejecuciones de bronce, con `run_id` en cada clave.
- Valoraciones, pruebas y ubicaciones se emparejan por tiempo dentro del episodio, con la señal `sin_pareja`.

## Alternativas consideradas

- **Solo las seis de la decisión 94:** sin `ubicacion` ni `plantilla` no hay KPIs de boxes ni de recursos.
- **Paciente–episodio 1:1:** más simple hoy, pero los reingresos (para después) obligarían a cambiar claves y tests.
- **Emparejar por orden:** con un inicio olvidado al principio, junta un inicio con un fin anterior y la duración sale negativa.

## Consecuencias

- Cada grano tiene su test de clave y cada flecha su `relacion`.
- Los reingresos y el retorno en 72 h quedan para versiones posteriores.

## Qué cambió al implementarla

- **8.3** (#151, `b63edad`). Lo que el plan interpretó, porque las D2 a D4 de las notas no lo cubrían:
  - la última apertura sin cierre lleva `sin_pareja` si el episodio tiene salida, y no si sigue en curso;
  - en `ubicacion`, las salidas solo cierran una estancia abierta (en `h8demo`, un desplazado que esperaba cama sale desde el pasillo);
  - una ronda de pruebas sin lista ni resultado no da filas;
  - el `event_time` de una fila es el menor de sus eventos, y su `recorded_time`, el mayor.
- **8.3:** las macros `primero(tipo)` y `emparejar`; esta empareja con `lag` y `lead`, y la usan `valoracion`, `ubicacion` y `prueba`, así que las tres siguen la misma regla. `episodio` agrupa también por `patient_id`.
- **8.3, la revisión** (`c4ca5cc`, `ebb90c2`): un solo booleano para el cierre en `emparejar`, y el unit test de `prueba`.
- **8.5** (#153, `3817ac0`): el box de una salida olvidada.
