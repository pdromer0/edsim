{% docs paciente %}
Uno por paciente: (`run_id`, `patient_id`). Imita la tabla de pacientes de un HIS.

**Sale de todos los `patient_id` de los eventos de pacientes**, no solo de `patient_registered` (D1 de la 8.3). Un olvido de admisión no deja huérfano a su episodio: el paciente existe igual, con la edad y el sexo vacíos. Así, el test `relacion` de episodio a paciente no tumba el `dbt build` del hospital por un despiste del registro. El despiste se sigue viendo en las columnas vacías.

Paciente y episodio son 1:N (decisión 104, H8-5). Hoy los datos son 1:1, porque el motor no simula reingresos. Con 1:N, la edad y el sexo saldrían del primer registro del paciente.
{% enddocs %}

{% docs episodio %}
Uno por episodio: (`run_id`, `episode_id`), con su paciente (`patient_id`).

**Sale de todos los `episode_id` de los eventos de pacientes** (D1 de la 8.3): ninguna tabla hija queda colgando. Las columnas salen del primer evento de cada tipo, por orden de anotación.

Señales, que no arreglan nada: dejan el defecto a la vista (decisión 103, H8-4).

- `sin_llegada`: no hay `patient_arrived`, porque se olvidó.
- `sin_salida`: no hay `patient_departed` ni `patient_left_wbs`. La salida se olvidó o el episodio sigue en curso al acabar la ejecución; con el registro solo, no se distinguen.
{% enddocs %}

{% docs triaje %}
Uno por episodio: (`run_id`, `episode_id`). El motor hace un solo triaje por episodio, en la puerta o con enfermera.

`nivel` y `motivo` salen del `triage_completed`, con la última corrección aplicada en `registros_vigentes`. `corregido` dice si se aplicó alguna.

`tiempo_negativo`: el fin del triaje es anterior a la llegada. Solo puede darlo un reloj desajustado. Con los perfiles de EDsim no salta, porque el reloj del triaje va siempre por delante del de admisión. Es una señal defensiva, para un HIS real.
{% enddocs %}

{% docs emparejamiento %}
`valoracion` y `ubicacion` no tienen un identificador propio: un inicio y su fin son dos registros sueltos, y hay que emparejarlos (macro `emparejar`).

**Por tiempo, dentro del episodio y sin mirar el tipo** (D2 de la 8.3). Los eventos se ordenan por `event_time`, `recorded_time` y `event_id`, y cada fin se empareja con la apertura abierta justo antes. Funciona porque las valoraciones de un paciente no se solapan, y tampoco sus estancias en box. Además, las dos fichas son del mismo sistema (HIS), con el mismo reloj.

Por qué no por orden: con un inicio olvidado al principio (fin a las 17:55, inicio a las 19:05, fin a las 19:20), emparejar el primer inicio con el primer fin junta el de las 19:05 con el de las 17:55, y la duración sale negativa. Por tiempo, el fin de las 17:55 queda suelto y el resto, bien.

**`sin_pareja`** marca una fila que sale de un emparejamiento roto:

- un fin sin una apertura justo antes: su fila tiene el inicio vacío;
- una apertura seguida de otra apertura: su fin se olvidó;
- la última apertura sin fin, si el episodio tiene salida: el fin se olvidó. Si el episodio sigue en curso, el fin vacío es legítimo y no lleva la señal.

`n` numera las filas del episodio por la hora de su primer evento: el inicio o, si falta, el fin.

**En `ubicacion`**, una estancia va de `box_assigned` a su cierre, con cuatro motivos (D3 de la 8.3):

- `espera_resultados` (`box_released`);
- `desplazado` (`patient_displaced`);
- `salida` (`patient_departed`);
- `abandono` (`patient_left_wbs`: se va desde el box antes de verle el médico).

Las dos salidas solo cierran una estancia abierta. Sin estancia, no dan fila: quien es desplazado mientras espera cama sale desde el pasillo.
{% enddocs %}

{% docs prueba %}
Una por prueba y ronda: (`run_id`, `episode_id`, `ronda`, `prueba`).

Una ronda es un `test_ordered` con su `test_resulted`, emparejados por tiempo como las valoraciones. En EDsim hay como mucho una por episodio, así que `ronda` vale 1. La clave la lleva por generalidad.

**Las pruebas salen de la lista pedida y de las claves del resultado, juntas** (D4 de la 8.3): cada prueba de la ronda sale una vez.

- `sin_resultado`: la prueba no tiene resultado, porque se olvidó, llegó vacío o sigue pendiente.
- `sin_peticion`: la prueba no está en la lista pedida, porque la petición se olvidó o su lista llegó vacía. Sin esta regla, una lista vacía haría desaparecer la ronda y sus resultados.

Si la lista y el resultado faltan los dos, no hay ninguna prueba que nombrar, y la ronda no da filas.
{% enddocs %}

{% docs destino %}
Uno por episodio: (`run_id`, `episode_id`). La decisión del destino, la petición y la asignación de cama (con su servicio) y el destino real de la salida. Cada columna sale del primer evento de su tipo.

Quien se va sin ser visto no tiene fila, y por eso la relación con `episodio` es 1 : 0..1.
{% enddocs %}

{% docs plantilla %}
Un tramo por recurso: (`run_id`, `recurso`, `desde`). Viene del sistema `rrhh`, no del HIS: `staffing_changed` es el único evento de recursos. No pasa por los despistes, así que llega limpia.

Cada cambio abre un tramo con la plantilla nueva (`numero`), que dura hasta el cambio siguiente del mismo recurso (`hasta`). El último tramo queda abierto.
{% enddocs %}
