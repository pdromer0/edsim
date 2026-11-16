{% docs tres_columnas %}
Una fila por (`run_id` de la verdad, `perfil`, `semilla`, `kpi`): cada uno de los cinco indicadores del hito 7 (nueve filas, con el reparto por nivel en cinco) en tres columnas.

- **verdad:** la hoja `verdad`, lo que pasó;
- **ingenuo:** la hoja `ingenuo`, lo registrado sin limpiar, como `compare.py`;
- **limpio:** la hoja `hospital`, lo registrado después de la limpieza.

Y dos diferencias: `ingenuo_menos_verdad`, el sesgo de lo registrado, y `limpio_menos_verdad`, lo que la limpieza no puede arreglar (el reloj, los olvidos, los valores erróneos sin corregir). El mismo código construye las tres hojas, así que las diferencias vienen de los datos, no de haber programado dos veces (decisión 107, H8-8).

**El enlace.** Cada ejecución registrada publica en `bronce.ejecuciones` un `inicio` con el bloque `registro`: `origen` (el `run_id` de la verdad), `perfil` y `semilla`. De ahí sale cada fila: su `run_id_registrado` es el de las hojas `ingenuo` y `hospital`, y su `run_id`, el de la hoja `verdad`. Una ejecución que falte en una hoja (una verdad sin cargar, por ejemplo) deja su columna vacía sin quitar la fila. Las tres hojas, en cambio, tienen que estar construidas: si falta una, su `kpi_ejecucion` no existe y la construcción falla.

**Se construye aparte**, con la hoja `hospital` y después de las tres: `dbt build --select tag:laboratorio`. Lee las tres hojas como fuentes, no con `ref()`, porque `ref()` apuntaría a la hoja que se construye. Solo la lee el rol `laboratorio`.
{% enddocs %}
