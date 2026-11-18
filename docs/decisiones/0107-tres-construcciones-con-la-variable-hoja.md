# 0107. Tres construcciones del mismo proyecto con la variable `hoja`

- **Estado:** Aceptada
- **Fecha:** 2026-11-16

## Contexto

La tabla de tres columnas pone al lado de cada KPI su valor en la verdad, en lo registrado sin limpiar y en lo limpiado. Si cada hoja tuviera su código, las diferencias podrían venir de haber programado dos veces; y el hospital no debe poder leer la verdad por error ([pieza 5](../specs/hito-8.md#pieza-5--oro-y-la-tabla-de-tres-columnas)).

## Decisión

- Tres construcciones del mismo proyecto con la variable `hoja`: `hospital` (por defecto), `verdad` e `ingenuo`, cada una en sus esquemas (`plata`, `verdad_plata`, `ingenuo_plata`…).
- La tabla de tres columnas, en el esquema `laboratorio`, con `tag:laboratorio`.

## Alternativas consideradas

- **Una columna `hoja` con seguridad por filas:** una sola tabla por modelo y una política por rol. Un olvido en una política deja al hospital ver la verdad; con esquemas separados, el rol ni siquiera tiene `USAGE`.
- **La verdad solo en Python:** se compararía sin pasar la verdad por los mismos modelos, que es justo lo que se quiere probar.

## Consecuencias

- El mismo código corrige las tres hojas: las diferencias de la tabla vienen de los datos.
- Los unit tests son de la hoja del hospital; las otras dos se construyen con `--exclude-resource-type unit_test`.

## Qué cambió al implementarla

- **8.1** (#149): las hojas tienen la misma forma. `ingenuo` lleva `corregido` falso y `duplicados_quitados` a 0, y `verdad` no lleva `ingest_time` ni la ventana de la relectura. Cada unit test fija su hoja con `overrides`, porque con `--vars '{hoja: ingenuo}'` fallaban los del hospital.
- **8.4** (#152): sin `--exclude-resource-type unit_test`, el unit test `l_escenario_completo` falla en la hoja `verdad` («column ingest_time does not exist»).
- **8.5** (#153, `e54be5f`): `tres_columnas` es una tabla larga de nueve KPI, con `run_id_registrado`, que lee las tres hojas como fuentes.
- **8.6** (#154, `df9cb7d`): `preparacion.parametros` gana la columna `registrado`, falsa en la hoja `verdad`, para que Urgencias ofrezca solo lo registrado.
