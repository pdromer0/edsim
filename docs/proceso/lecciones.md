# Lecciones transversales

> **Estado:** documento vivo. Recoge lo aprendido en los hitos 1 a 6, la app y las tareas de proceso que vale más allá de la tarea en la que salió. Se añade una lección al cerrar la tarea que la enseña; el detalle sigue en su anexo y en su diario. Las de proceso (P.2) vienen de [p2.md](p2.md).

Cada lección dice qué se aprendió y, entre paréntesis, dónde salió cuando importa.

## Simulación y colas

- Las esperas se disparan de forma no lineal cerca de la saturación. Un servicio se juzga por sus días malos, no por la media.
- Una réplica es una sola historia: hacen falta calentamiento, varias réplicas e intervalos de confianza.
- Separar simular de medir: se guardan hechos (el log de eventos) y los estados se derivan de ellos.
- Al quitar un cuello de botella, el siguiente pasa a mandar (boxes → médicos).
- Lo que depende del instante de la simulación se sortea estándar y se transforma cuando se conoce el instante. Los sorteos comunes no implican resultados idénticos.
- Lo observado de quien se va (cuánto esperó) no es su paciencia: solo se van los impacientes. Se calibra al porcentaje, no se copia (sesión del hito 5).
- Quitar de una métrica de espera a los que se van la mejora justo cuando el servicio empeora: se usan las medias de los atendidos (como la fuente) y el cumplimiento con censura (sesión del hito 5).

## Calibración y modelos

- Antes de corregir un modelo, se comprueba qué mide el indicador. Antes de calibrar, se mide la sensibilidad de cada mando. Un objetivo que ningún mando mueve no se calibra: se decide, y pasa a comprobación con su causa escrita.
- Una comprobación que decide el ajuste deja de comprobar.
- La ventana de una calibración tiene que representar lo que mide el objetivo. Una cifra que crece con el horizonte se descompone antes de corregirla.
- Un objetivo que solo depende de los atributos del paciente se deriva sin simular; uno que depende de las colas se ajusta con un mando propio (sesión del hito 5).
- Lo que se recalcula al cargar absorbe los shocks: se deriva una vez y se escribe (patrón «derivado y escrito»).
- Pasar todos los tests no es ser clínicamente creíble. Dos valores orientativos pueden ser incompatibles entre sí, y un valor orientativo sin dato se elige por un criterio escrito.
- Partir una tarea con cambios de modelo y calibración en dos PR deja cada uno revisable.

## Tests y verificación

- Valores a mano: la autoconsistencia no basta. Una referencia de test que usa la función probada hereda su error (el cálculo se escribe en el plan, como pide [tarea.md](tarea.md#2-plan); P.2).
- Validar al validador: una versión incorrecta solo valida si falla por la razón prevista. Las predicciones de «pasa» fallan más que las de «falla».
- Un error compartido por lo exacto y el muestreador solo lo ven los valores a mano y los literales.
- Un test de detección sin potencia no demuestra nada; un mínimo con recuentos aleatorios necesita margen calculado.
- La igualdad bit a bit con el muestreador directo prueba el cableado mejor que un χ².
- Un test que comprueba dos cosas puede esconder una versión incorrecta. Se empareja por id, no por posición.
- Un valor recalculado puede no ser idempotente: para comparar bit a bit, no se reconstruye. Un test que compara una función con la misma llamada que hace ella no prueba nada.
- Un test que compara dos lados que comparten un paso no ve los errores de ese paso; los ven los tests contra referencias independientes (6.3).
- Los errores que la ejecución de referencia no ejercita (evento en el horizonte, salida justo en el límite, orden del censo) solo los ve un test construido para ellos (6.2).
- Antes de predecir sobre una invariante, se mira qué reconstruye del log: no ve las claves internas del motor.
- Un error de configuración se prueba con una comprobación que lo nombra, no esperando a que venza un tiempo límite (6.1).
- Una comprobación en vivo ve lo que ningún test mira, como el ruido de una biblioteca con el servicio caído (6.5).
- Dos validadores del mismo contrato comparados con una colección de casos encuentran huecos que nadie buscaba (6.4).
- Una carrera aparece en pocos intentos de muchos: se mide muchas veces antes de dar algo por estable (6.4).

## Datos, formatos y código

- Cambiar el tipo de una constante con el mismo nombre rompe en silencio.
- Un formato en disco se versiona escribiendo lo nuevo y leyendo lo antiguo con su significado. Una clave opcional nueva conserva, si falta, el significado antiguo.
- Un supuesto implícito se rompe cuando entra una clave de otro tipo: se releen los escritores y lectores que la tocan.
- Un núcleo que otra parte ya usa cambia de forma aditiva. Se separa lo lento de lo que cambia.
- Una promesa de la especificación se comprueba en el código al cerrar, buscando quién lee lo que se va a quitar. Al cambiar un valor por defecto, se busca lo que dependía del antiguo sin decirlo. Los valores por defecto van en los puntos de entrada, no en la biblioteca.
- Los enteros de Python no tienen límite: toda comprobación de «número finito» tiene que convertir antes de preguntar (6.4).
- Un reloj de test en coma flotante acumula error: se cuenta en enteros, como `time.monotonic_ns` (6.3).
- Una función «inocua» de la biblioteca estándar puede volver a ejecutar una normalización: se compara bit a bit con la fuente antes de usarla (6.3).
- Una equivalencia que el diseño da por hecha se comprueba en el código de la biblioteca antes de apoyarse en ella (6.2). Antes de cambiar un parámetro, se lee en ese código de dónde sale el comportamiento (6.6).
- Estado persistente y widgets son capas distintas; los formatos compartidos viven en un solo sitio; la clave de una caché es lo que cambia la respuesta (app).
- Antes de cambiar un fichero que leen muchos, como `config/`, primero el inventario de sus lectores y las copias congeladas de lo antiguo. Los lectores que afirman el significado antiguo pasan a las copias, y el diff demuestra que sus cifras no cambian. Los notebooks también son lectores (5.4, 5.6).

## Tiempo real y servicios

- Un mensaje de fin no puede adelantarse a las confirmaciones: lo publicado no es lo entregado hasta el `flush` (6.4).
- Un contador que lee el estado de una biblioteca asíncrona incluye lo que la biblioteca ya sabe y nadie ha servido: se sirve antes de contar (6.5).
- Un temporizador que se reprograma desde «ahora» acumula el retraso de cada disparo: rejilla fija desde el ancla (6.5).
- Contar con una herramienta que no es la nuestra cierra el círculo: lo que dice el `fin` es lo que hay en el broker (6.5).
- El ruido de una biblioteca se desvía, no se silencia: resumen siempre, detalle a demanda, y los errores reales por su camino de siempre (6.6).
- «Caído» se decide con el estado, no con un error suelto (6.6).
- Un lector de un topic compartido filtra antes de validar: un mensaje roto de otro no puede tumbarlo (6.6).
- Una imagen configurada solo con variables puede perder sus valores por defecto: se lee su código antes de fiarse del ejemplo (6.1).

## Rendimiento de los tests

- La mayor ganancia de tiempo está en no ejecutar lo que no hace falta, no en paralelizar. Un sello por contenido, comparado con el último verde (P.1).
- Las máquinas del CI varían hasta el doble: una comparación limpia mide las dos variantes en el mismo job (P.1).
- Un tiempo de la suite se mide en las mismas condiciones que el anterior; se compara la parte que cambia, no el total (6.2, 6.4).

## Proceso y agentes

- Los ajustes que no llegan al agente no existen. Un cambio local ajeno se pregunta, no se pisa.
- Un revisor automático aplica las reglas al pie de la letra: se escribe la práctica real, comprobando todas las zonas.
- Antes de mover documentación, se compara (P.2).
- Los ficheros grandes los escribe un script, no la salida del modelo (P.2).
- Las instrucciones se contradicen solas con el tiempo; una regla que relaja otra nombra la excepción en los dos sitios (P.2).
- Las automatizaciones de GitHub compiten con los scripts: se comprueba el estado y se actúa solo si falta (P.2).
- Un dato del plan puede perderse al ejecutarlo: la prueba en seco va antes del primer uso real (P.2).
- Números con el mismo formato se confunden: issues y decisiones necesitan notación distinta (P.2).
- Lo que vale más allá de una sesión no se pasa como argumento: va al issue (P.2).
- Una regla que dice que algo se repite tiene que decir cuándo: «si las correcciones tocan código, repite la N3» se leyó como «tras cada corrección» (5.2).
- Los errores de los planes están en lo que interpretan sin que lo diga la especificación, no en la aritmética. Los tests no los ven, porque nacen de la misma interpretación: la ven Pedro y el chat al revisar el plan (5.4 a 5.7).
- En una sesión en la nube, GitHub solo responde por REST: `gh issue view` y `gh project` usan GraphQL y el proxy los rechaza. El issue se lee con `gh api` y el tablero lo mueve Pedro o el workflow (5.7).
- Dos skills con un número cada una se confunden: `/tarea-edsim` lleva el del issue y `/sincronizar`, el del PR (5.7).

El porqué de las seis lecciones de la P.2 está en [portabilidad.md, sección 13](portabilidad.md#13-lecciones-de-la-implantación-p2) y la regla del issue, en [tarea.md](tarea.md#1-arranque). El de la lección de la 5.2, en la [ADR 0083](../decisiones/0083-una-sola-n3-tras-la-revision-propia.md); el de las del hito 5, en el [balance del hito](../specs/hito-5.md#balance-del-hito).
