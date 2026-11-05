# 0031. App web incremental

- **Estado:** Aceptada
- **Fecha:** 2026-11-04

## Contexto

El motor del hito 3 ya produce un servicio que se puede explorar, pero los hitos
siguientes cambiarán el paciente, el flujo y la arquitectura. Ver sus resultados
pronto ayuda a detectar problemas del modelo; construir ahora una aplicación
completa añadiría otro stack mientras esos contratos siguen cambiando
([estrategia de la app](../../app/docs/specs/fase-1.md#decisión-y-estrategia)).

## Decisión

La app crece con el modelo: fase 1 local en Streamlit al cerrar el hito 3,
incrementos como tareas de los hitos siguientes y aplicación completa con API y
frontend propio después del hito 6 o de la v0. Esta decisión obliga a la hoja de
ruta del proyecto; la tecnología de la primera interfaz se registra en
[APP-0001](../../app/docs/decisiones/APP-0001-interfaz-streamlit-sin-api.md).

## Alternativas consideradas

- Esperar a terminar la v0: retrasa la exploración visual del servicio y la
  comprobación de que el núcleo ofrece lo que necesita una interfaz.
- Construir ya el frontend propio, WebSockets y la sala de control: desvía el
  trabajo de simulación y estadística y obliga a rehacer partes cuando lleguen
  los perfiles clínicos, el cierre del flujo y el modo directo.

## Consecuencias

- La primera fase ha dejado las seis páginas sobre los servicios públicos del
  núcleo, manteniendo la CLI y la app sobre el mismo formato de ejecución
  ([anexo A.0–A.7](../../app/docs/specs/fase-1.md#anexo-guía-de-referencia-de-la-fase-1)).
- Los incrementos se especificarán con su hito, como los notebooks; la app
  batch sigue siendo útil cuando llegue la sala de control en vivo.
- La fase 1 queda limitada a uso local por un usuario. El alcance de la fase 2
  y su frontend se decidirán con el modo directo; no se anticipan contratos de
  control que el motor todavía no tiene.
