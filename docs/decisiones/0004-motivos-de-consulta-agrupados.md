# 0004. Motivos de consulta agrupados

- **Estado:** Aceptada
- **Fecha:** 2026-10-27

## Contexto

Cada motivo de consulta es un perfil configurable: peso base, modificadores por edad, hora, estación y día, distribución de gravedad latente, probabilidad de cada prueba, modificadores de duración y probabilidades de destino. Todo eso hay que calibrarlo con datos públicos ([diseño](../diseno.md#catálogo-de-motivos-de-consulta)).

## Decisión

Se usan unos 17 motivos agrupados, alineados con los diagramas de Manchester.

Motivo: el coste de calibración.

## Alternativas consideradas

- Diagnóstico CIE-10: queda como atributo opcional para versiones posteriores.

## Consecuencias

- Los pesos del catálogo son orientativos hasta la calibración, que empieza en el hito 4.
- Incorporar CIE-10 más adelante supone añadir un atributo, no cambiar el catálogo.
