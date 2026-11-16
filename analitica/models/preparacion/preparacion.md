{% docs registros %}
Una fila por registro, con los tipos puestos y sin las columnas de Kafka: lo que anotó el hospital, sin limpiar.

**La única regla: una fila por (`run_id`, `event_id`), la de menor `ingest_time`.** Hay dos clases de duplicados (notebook 07), y esta es la de la tubería: una relectura de Kafka o una reemisión repetida dejan en bronce el mismo `event_id` dos veces, con distinta `ingest_time`. Quedarse con la primera llegada no cambia nada del registro, que es el mismo; solo quita la copia. La otra clase, el doble clic del hospital, son dos registros con distinto `event_id`: no se tocan aquí, sino en `registros_vigentes`.

En la hoja `verdad` lee de `verdad.eventos`, que no pasa por Kafka: no tiene `ingest_time` ni relecturas que quitar.
{% enddocs %}

{% docs registros_vigentes %}
La limpieza conservadora (decisión 103, H8-4), en un solo modelo: las ocho tablas de plata leen de aquí. Arregla lo que se puede arreglar con una regla segura y deja el resto como llegó, porque un analista de hospital no tiene la verdad, y cualquier otra cosa sería inventar datos.

En las hojas `hospital` y `verdad`, tres reglas, **en este orden**:

1. **Los `record_corrected` no son hechos.** Una corrección no es algo que pasó al paciente: dice que un registro anterior estaba mal. Solo sirve al paso 3 y no pasa a la salida.
2. **Duplicados (el doble clic).** Entre los registros con la misma clave (`run_id`, `episode_id`, `event_type`, `event_time`, `payload`) se queda el de menor `recorded_time` y, si empatan, el de menor `event_id`. La columna `duplicados_quitados` dice cuántos se quitaron de su grupo.
   - *Por qué el anotado primero:* el registro clínico (`record.py`) crea el duplicado como una copia del registro tal como se anotó, de 0,5 a 2 min después **de la anotación del original**. La corrección enlaza con el `event_id` del original. Si se quedara la copia, la corrección no encontraría su registro y el valor erróneo se quedaría.
   - *Por qué el payload va en la clave:* dos hechos reales del mismo episodio, del mismo tipo y en el mismo instante pueden diferir solo en el payload, como dos peticiones de pruebas distintas. Sin el payload, la regla borraría uno. Medido en la 8.1 sobre la verdad de `r2026`: con la clave completa, ningún par de hechos reales coincide.
   - *Por qué los eventos de recursos quedan fuera:* `staffing_changed` no tiene `episode_id`, y en un `PARTITION BY` los nulos caen todos en el mismo grupo. Pasan tal cual: no tienen despistes.
   - *Lo que cuenta:* `duplicados_quitados` cuenta solo los dobles clics, los registros con distinto `event_id`. Las relecturas, con el mismo `event_id`, ya las quitó `registros`.
3. **Correcciones (la última gana).** Para cada registro al que apunta algún `corrige`, se aplican los `campos` de la corrección con mayor `recorded_time` (si empatan, la de mayor `event_id`) sobre el payload, con `payload || campos`: los campos corregibles (`nivel`, `edad`, `motivo` y `destino`) son de primer nivel en el payload. La columna `corregido` dice si se aplicó alguna.

**Lo que no cubre:**

- Una corrección que apunta a un registro que no está (porque se olvidó, por ejemplo) no casa con ninguna fila. Se cuenta como aviso de calidad en `oro.calidad` (8.5), desde `registros`. Con datos de EDsim siempre da 0, porque un hecho olvidado no recibe corrección. La cuenta es para un HIS real.
- Los campos vacíos se quedan `NULL`. Un olvido sin salida deja el episodio abierto, y un olvido sin llegada lo deja sin hora de llegada. Plata y oro lo señalan.
- El reloj desajustado de un sistema no se arregla: solo deja rastro cuando un tiempo sale negativo.
- Un valor erróneo que nadie corrigió no se detecta: el registro clínico elige valores verosímiles.

En la hoja `ingenuo`, como los indicadores ingenuos del hito 7, solo se aplica la regla 1: ni se quitan duplicados ni se aplican correcciones. Las columnas son las mismas, con `corregido` falso y `duplicados_quitados` a 0.
{% enddocs %}
