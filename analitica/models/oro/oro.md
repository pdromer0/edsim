{% docs censo %}
Una fila por hora en punto de la ventana: (`run_id`, `hora`). Son las horas `k` con W ≤ 60 k < horizonte, como `_hours` de `compare.py`, y `hora` = origen + k horas.

**Quién está dentro**, con las definiciones de `compare.py` (decisión 96): cada episodio, desde su primera llegada hasta su primera salida (`patient_departed` o `patient_left_wbs`), por orden de anotación.

- Quien llega justo a la hora en punto ya está; quien sale justo, ya no.
- Una salida anterior a la llegada, por los relojes, cuenta como salida en la llegada: el episodio no llega a estar dentro.
- Un episodio sin llegada no está nunca; uno sin salida está hasta el final.
- Cuenta con todos los registros, no solo con los de la ventana: quien llegó en el calentamiento y sigue dentro está en el censo (en una reemisión, por el censo inicial del directo).

**Cómo se cuenta: un torniquete.** Cada llegada suma 1 en la primera hora en punto que la ve, y cada salida resta 1 en la primera hora en punto en la que ya no está; el censo de cada hora es la suma acumulada. Da lo mismo que cruzar cada hora con cada estancia, pero con un año serían miles de millones de comparaciones.
{% enddocs %}

{% docs kpi_ejecucion %}
Una fila por ejecución: (`run_id`). Los cinco indicadores del hito 7 en su ventana, para la tabla de tres columnas y la comprobación con Python.

**Las definiciones son las de `compare.py`** (`_naive_indicators`, decisión 96), para que el SQL y el Python den lo mismo (H8-12). La prueba de punta a punta lo comprueba en las hojas `verdad` e `ingenuo`.

**La ventana** (D1 de la 8.5): un registro cuenta si su `event_time` es ≥ origen + W. Una reemisión solo deja en bronce, de antes de W, los eventos de los episodios abiertos en W: sin la ventana, las llegadas del calentamiento faltarían en lo registrado y estarían en la verdad, y «limpio − verdad» mezclaría los despistes con ese hueco.

- **Llegadas:** los registros `patient_arrived` de la ventana. Son registros, no episodios: en la hoja `ingenuo`, un doble clic cuenta dos veces, como en Python.
- **Medianas hasta el triaje y hasta el médico:** de la primera llegada al primer `triage_completed` (o al primer `assessment_started` de tipo `inicial`) de cada episodio, con los dos registros en la ventana. «El primero» se toma por orden de anotación. Se calculan en milisegundos enteros y se pasan a minutos al final: con un número par de valores, la mediana es la media de los dos centrales, como `statistics.median`.
- **Reparto por nivel:** el porcentaje de cada nivel entre los `triage_completed` de la ventana con un nivel legible, un entero del 1 al 5. Un nivel vacío no cuenta.
- **Censo medio:** la media de `oro.censo`, que usa todos los registros.
{% enddocs %}
