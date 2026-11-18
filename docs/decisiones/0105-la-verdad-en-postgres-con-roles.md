# 0105. La verdad en Postgres, en su esquema, con tres roles

- **Estado:** Aceptada
- **Fecha:** 2026-11-16

## Contexto

Para poner nota hacen falta el examen y el solucionario en la misma mesa, pero el «hospital» no debe ver el solucionario. En el hito 7 la verdad se quedó en disco (decisión 95). La ficha de cada episodio no trae los tiempos vividos, que solo están en los eventos; la libreta dice qué hizo el registro clínico con cada hecho ([pieza 4](../specs/hito-8.md#pieza-4--la-verdad-en-postgres-y-los-permisos-por-capa)).

## Decisión

- Cuatro tablas en el esquema `verdad` (eventos, episodios, días y libreta), cargadas con `edsim almacen cargar-verdad RUN_ID`; ejecutarlo dos veces deja lo mismo.
- La migración `002_verdad.sql`.
- Tres roles: `edsim` (dueño), `hospital` (lee preparación, plata y oro de lo registrado) y `laboratorio` (lo lee todo).
- Los permisos de preparación, plata y oro, con `grants` de dbt, que los vuelve a dar en cada construcción.
- Es un candado contra mirar la solución sin querer, no seguridad: las contraseñas de desarrollo están en el repositorio.

## Alternativas consideradas

- **Solo los eventos:** sin la ficha (`nivel_real` frente a `nivel`) ni la libreta, no se evalúa cada regla de limpieza.
- **La verdad como semillas de dbt:** las semillas son para tablas pequeñas y fijas, y una ejecución de un año tiene 1,4 millones de eventos.

## Consecuencias

- La verdad no pasa por Kafka (H7-2).
- Una ejecución de un año ocupa 577 MB en `verdad` (medido en la 8.4).

## Qué cambió al implementarla

- **8.4** (#152, `88ee95d`, `45f8f8e`):
  - **la libreta lleva `run_id_origen`**: con solo el `run_id` derivado que daba la especificación, recargar no sabría qué filas borrar si desaparece una carpeta de `registros/`;
  - una ejecución de otro esquema es un `TruthError` antes de conectar;
  - `ALTER DEFAULT PRIVILEGES` para que lo que cree `edsim` después nazca legible para `laboratorio`;
  - se captura también `unique_violation`, el error de dos `CREATE ROLE` cruzados;
  - el `GRANT` sobre la hypertable de bronce llega a sus chunks.
- **8.4, la revisión** (`f792a67`): un byte que no es UTF-8 durante la carga es un `TruthError` y código 1.
- **8.5** (#153, `a68fc24`): **`grants` de dbt no basta**, porque da `SELECT` sobre las tablas pero no `USAGE` sobre los esquemas. Lo da la macro `dar_uso_de_esquemas` en el `on-run-end` de cada construcción. `+grants` en `dbt_project.yml` necesita `var('hoja', 'hospital')` con su valor por defecto, porque el fichero se lee antes que sus propias `vars`.
- **8.4, la medida de un año:** 1.386.002 eventos, 109.910 episodios y 1.395.175 filas de libreta; cargarla, 56,6 s y 153 MiB.
