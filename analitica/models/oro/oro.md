{% docs censo %}
Una fila por hora en punto de la ventana: (`run_id`, `hora`). Son las horas `k` con W ≤ 60 k < fin del dato (`preparacion.parametros`), y `hora` = origen + k horas. En una ejecución completa, el fin del dato es el horizonte, como `_hours` de `compare.py`; en un directo, su última anotación, y las horas aún por llegar no salen (D1 de la 8.7).

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

{% docs cohorte %}
Una fila por episodio: (`run_id`, `episode_id`), con su hora y su turno de llegada (decisión 106, H8-7).

**La cohorte de llegada.** Cada espera se apunta a la hora en que llegó el paciente: «los que llegaron a las 16:00 esperaron tanto». Quien llega a las 16:58 y se tria a las 17:04 cuenta en la hora de las 16, no en la de las 17. `kpi_hora` y `kpi_turno` agrupan por la hora y el turno de aquí.

«El primero» de cada tipo se toma por orden de anotación, con todos los registros. Hay fila para todos los episodios, también los del calentamiento (que `kpi_hora` no enseña) y los que no tienen llegada (sin hora ni turno), porque `calidad` la usa.

**El turno.** Los turnos empiezan a las horas de la semilla `turnos`. La noche pertenece a la fecha en que empieza: las 03:00 del día 6 son la noche del día 5. La hora y la fecha salen de aritmética entera sobre `k`, las horas desde el origen, que es una medianoche: no dependen de la zona horaria de la sesión de Postgres.

**Sigue dentro o salida olvidada.** `sin_salida` de plata junta dos cosas que el registro solo no separa: el paciente que sigue dentro al acabar (o en el directo) y la salida que se olvidó anotar. Aquí se reparten con una regla: un episodio sin salida **sigue dentro** si su última anotación (`recorded_time`) es de las últimas 24 h de la ejecución (`margen_sin_salida_min`); si no, su **salida se olvidó**. El ahora de la ejecución es su fin del dato (`preparacion.parametros`), el mismo en que acaban las horas del censo: en un directo, su última anotación; en una ejecución acabada, su `fin` (hasta la 8.7 era la última anotación también en las acabadas, unos minutos antes del horizonte).

Ningún margen separa del todo, porque una espera de cama deja días sin anotar nada. Medido en el plan de la 8.5, con 14 días de `config/` y el perfil realista: con 24 h, de 79 episodios sin salida, 22 salen como olvidados (1 seguía dentro de verdad) y 57 como dentro (6 ya habían salido). Con la verdad, que no olvida nada, 1 episodio sale como olvidado: una espera de cama de más de 24 h sin anotaciones.

Los **pendientes** de `kpi_hora` y `kpi_turno` son los que siguen dentro sin el registro que se espera: quien se fue sin ser visto, o tiene el registro olvidado, no está pendiente.
{% enddocs %}

{% docs kpi_hora %}
Una fila por hora en punto de la ventana: (`run_id`, `hora`), las series de Grafana. Cada columna se apunta a una hora de una de tres maneras:

- **el instante de la hora en punto:** el censo, los boxes ocupados y los médicos de la plantilla. Quien llega o entra justo a la hora en punto cuenta; quien sale justo, ya no;
- **la hora de llegada** (la cohorte): las medianas hasta el triaje, hasta el médico y de la estancia, con sus pendientes, y los que se van sin ser vistos;
- **el intervalo** [hora, hora + 1 h): las llegadas (registros, como en `kpi_ejecucion`: en la hoja `ingenuo`, con los duplicados), los triajes por nivel (`sin_nivel`, una categoría más), las estancias en box por su entrada y las que acaban desplazadas o liberadas para esperar resultados, por su salida.

**La mediana de la última hora sale mejor de lo que será.** En el directo, de los que llegaron en la hora en curso solo han pasado por el triaje los rápidos. Por eso cada mediana lleva al lado sus pendientes.

**Los boxes** son los de la semilla `maestro_boxes`, y se cuentan boxes distintos: dos estancias solapadas en el mismo box por un cierre anotado tarde no pasan de 36. Una estancia abierta solo cuenta como ocupada si su episodio sigue dentro (`oro.cohorte`): si se olvidó su cierre (`sin_pareja`) o la salida del episodio, el box contaría ocupado para siempre, y en un año de registro realista las salidas olvidadas llenarían los 36. El precio es el de la regla de quien sigue dentro: un paciente de verdad en un box, esperando cama más de 24 h sin que se anote nada, deja de contar (en la ejecución de 3 días de la punta a punta, un box de 36 en la verdad).

Las horas son las de `oro.censo`: en un directo, hasta su última anotación, sin las que aún no han llegado (D1 de la 8.7, el contrato con los paneles de la 8.6).
{% enddocs %}

{% docs kpi_turno %}
Una fila por turno: (`run_id`, `fecha`, `turno`), el informe de dirección.

Los turnos empiezan a las 8, a las 15 y a las 22 (la semilla `turnos`), y la noche es de la fecha en que empieza. Solo cuentan las horas de la ventana: el turno que corta W (con W a medianoche, la noche del día anterior) o el fin del dato (el horizonte, o en un directo el turno en curso) sale con menos `horas` y con `completo` falso, para no compararlo con uno entero.

Las sumas y las medias salen de las horas de `kpi_hora`; las medianas, de las filas de la cohorte y de las estancias del turno (no de las medianas de cada hora, que no se pueden promediar).
{% enddocs %}

{% docs calidad %}
Una fila por ejecución: (`run_id`), los avisos de calidad del dato, con la ejecución entera.

Es la única tabla de oro con todas las ejecuciones que tienen registros, tengan o no parámetros. Una ejecución sin un `inicio` utilizable (el consumidor empezó tarde, o la retención del topic se llevó el mensaje) no tiene origen ni ventana y no sale en el resto de oro; aquí aparece con `sin_parametros`.

- De plata: los episodios sin llegada y sin salida, las valoraciones y las ubicaciones sin pareja y los triajes con tiempo negativo.
- De la cohorte: los sin salida repartidos entre `siguen_dentro` y `salidas_olvidadas` (ver «cohorte»).
- De la preparación: los campos vacíos (en total y por campo), los registros corregidos, los duplicados quitados y las **correcciones sin registro**: las que no encuentran su registro en `registros_vigentes` (D3 de la 8.1). Se cuentan contra `registros_vigentes`, no contra `registros`: una corrección a una copia que la limpieza quitó tampoco se aplica, y así queda a la vista.
{% enddocs %}
