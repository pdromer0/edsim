# 0057. JSON Schema 2020-12 generado del catálogo, un fichero por versión

- **Estado:** Aceptada
- **Fecha:** 2026-11-06

## Contexto

Otros programas (Redpanda Console, los consumidores de los hitos 7 y 8) tienen que saber la forma exacta de cada mensaje sin leer el código de EDsim, y el contrato cambia con cada versión del catálogo ([especificación, pieza 4](../specs/hito-6.md#pieza-4--contratos-json-schema-y-versiones-del-catálogo)).

## Decisión

- Un JSON Schema 2020-12 por versión del catálogo, generado de `CATALOGS` y escrito en `schemas/eventos-vN.schema.json`, con un test «escritos = generados» (`uv run python -m edsim.live.schemas` los regenera).
- Esquemas escritos a mano para `ed.runs` y `ed.control`.
- Sin registro de esquemas.

## Alternativas consideradas

- Avro con registro de esquemas: más maquinaria y otro servicio; queda para la v1 (caso de uso «evolución de esquemas»).
- Escribir los esquemas de los eventos a mano: se desincronizarían del catálogo.

## Consecuencias

- El contrato es legible y versionado, y sigue el patrón «derivado y escrito» del proyecto.
- `jsonschema` solo está en el grupo `dev`: el paquete no lo importa.

## Qué cambió al implementarla

- 6.4: un refactor previo convirtió las comprobaciones del catálogo en objetos que validan y describen su esquema (`Check`); 1.947 comprobaciones dieron el mismo resultado antes y después.
- 6.4: el esquema dice lo mismo que `Event`, salvo lo que JSON Schema no puede expresar, escrito en `KNOWN_DIFFERENCES` y probado en los dos sentidos. Dos huecos que sí se podían expresar se cerraron: `maxLength: 9` en los identificadores (el `$` de `re.search` admite un salto final) y `maximum` = el mayor double (`1e400` se lee como infinito).
- 6.4: `parse_control` y `ed-control-v1` se contrastan con una misma colección de 32 órdenes, con una sola diferencia (`KNOWN_CONTROL_DIFFERENCES`).
