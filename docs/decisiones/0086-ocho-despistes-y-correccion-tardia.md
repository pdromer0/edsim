# 0086. Los ocho despistes, con la corrección tardía como evento propio

- **Estado:** Aceptada
- **Fecha:** 2026-11-13

## Contexto

El diseño enumeraba ocho defectos (retraso, desorden, duplicado, campo vacío, valor erróneo, olvido, reloj desajustado y corrección tardía). Había que decidir cómo se ve cada uno en los datos, dónde se aplica y hasta dónde llega, sin que el coste se disparara ([especificación, «Los despistes, uno a uno»](../specs/hito-7.md#los-despistes-uno-a-uno)).

## Decisión

- Los ocho despistes del diseño, con un **retraso** y un **reloj** propios de cada sistema (admisión, triaje, HIS y laboratorio).
- La **corrección tardía** es un evento `record_corrected`, en esquemas propios del registro (`registro-v1` a `registro-v4`), y solo corrige valores erróneos.
- Los **valores erróneos**, solo en nivel, edad, motivo y destino.
- Un **duplicado** es otro registro, con su propio número.
- Solo en los **eventos de pacientes**, y con cualquier versión del catálogo.

## Alternativas consideradas

- **Dejar la corrección para el hito 8:** un error sin su corrección cuenta media historia, y la limpieza del hito 8 necesita las dos cosas para aprender a aplicarla. Tendría sentido si el hito 7 hubiera tenido que recortar alcance.
- **Valores erróneos en todos los campos:** más trabajo de esquema y de comparación, sin una lección nueva.
- **Despistes también en los eventos de recursos:** la plantilla no se teclea a mano; queda en «Para versiones posteriores».

## Consecuencias

- Lo registrado no son `Event`: un campo vacío no cumple el catálogo. Es un tipo propio, `Record`, con el mismo sobre y el `payload` sin validar.
- El desorden no tiene parámetro: sale solo del retraso.

## Qué cambió al implementarla

- **7.1, el dado:** `Roll` tiene 13 números con nombre, en el orden de la especificación, y hay una tirada por evento verdadero de paciente aunque se olvide o el perfil sea limpio. Los recursos no tiran.
- **7.1, el cuantil** es `mediana · exp(sigma · z)`, que con z = 0 da la mediana exacta: `exp(log 7)` da 6,999999999999999.
- **7.1:** los desfases van en milisegundos enteros. Las horas registradas se calculan al numerar, y solo de lo escrito: una z enorme lleva un duplicado más allá de cualquier fecha, y no se escribe.
- **7.1, la clase sale de lo escrito:** un hecho es `con_despistes` si cambia `sim_time`, el desfase, un valor o un campo. Un duplicado o una corrección no cambian la clase del original.
- **7.1, `retraso_min`** (decisión de Pedro): `sim_time` del registro menos `sim_time` verdadero de su hecho, en todas las filas escritas.
- **7.1, la edad se invierte literalmente** (decisión de Pedro): de 20 … 90 se pasa a 2 … 9, y 99 pasa a 100. Son errores inverosímiles a propósito, material para la limpieza del hito 8.
- **7.1, los esquemas** salen de las ramas de `event_schema`, con el payload anulable; `record_corrected` es la rama de un evento de paciente con su propio tipo, sistema y payload.
