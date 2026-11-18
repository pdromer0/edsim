# 0106. Oro: tres familias de KPIs por hora y por turno, con las definiciones de `compare.py`

- **Estado:** Aceptada
- **Fecha:** 2026-11-16

## Contexto

Oro es la hoja que querría ver el jefe de guardia cada hora y el informe de dirección de cada turno. Para comprobar el SQL contra algo, los indicadores del hito 7 tienen que llevar las mismas definiciones que `edsim.clinical_record.compare` (decisión 96) ([pieza 5](../specs/hito-8.md#pieza-5--oro-y-la-tabla-de-tres-columnas)).

## Decisión

- Tres familias de KPIs, por hora y por turno: flujo, boxes y recursos, y calidad del dato.
- Los cinco indicadores del hito 7, con las definiciones de `compare.py`.
- La cohorte de llegada, con los pendientes al lado.
- El maestro de boxes y los turnos, como semillas de dbt, con un test frente a `config/centro.toml`.

## Alternativas consideradas

- **El informe realista por nivel (opción C):** esperas por nivel y su percentil 90 frente al tiempo objetivo de cada nivel. Lo pidió Pedro para después: Python no tiene su comparación. Versiones posteriores.
- **La capacidad leída de cada ejecución:** importará cuando los experimentos cambien los boxes. Hito 9.

## Consecuencias

- «Verdad SQL = verdad Python» e «ingenuo SQL = ingenuo Python» son comprobables en la punta a punta (decisión 111).

## Qué cambió al implementarla

- **8.5** (#153), las decisiones del diff:
  - **la ventana:** los cinco indicadores cuentan los registros con `event_time` ≥ origen + W, y el censo, todos. Sin ella, el calentamiento, que una reemisión no deja en bronce, sesgaría «limpio − verdad»;
  - **el censo como un torniquete:** una suma acumulada de llegadas y salidas, y no un cruce de cada hora con cada estancia, que con un año serían unos 10⁹ pares;
  - **quien sigue dentro:** sin salida, sigue dentro si su última anotación es de las últimas 24 h. Esto cuesta 1 en la ocupación máxima (de 36 a 35);
  - las medias, con aritmética exacta, porque un `avg` de `double precision` depende del orden de las filas (`32f62ce`).
- **8.5, la comparación con Python** lo cazó: `greatest` ignora los nulos en Postgres, así que quien no tenía salida salía al llegar (censo medio de 62,4 frente a 67,375).
- **8.7** (#155): las horas acaban en el **fin del dato** (el `fin` de la ejecución o su última anotación, nunca más que el horizonte), y quien sigue dentro se cuenta desde ese fin.
