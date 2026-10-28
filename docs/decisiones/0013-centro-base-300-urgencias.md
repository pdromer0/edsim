# 0013. Centro base de 300 urgencias al día

- **Estado:** Aceptada
- **Fecha:** 2026-10-27

## Contexto

Se empieza por un hospital general de tamaño medio ([0002](0002-centro-parametrizable.md)). Hace falta fijar su volumen ([diseño](../diseno.md#preguntas-resueltas)).

## Decisión

El centro base atiende 300 urgencias al día por defecto, parametrizable en el rango 200–400.

Motivo: corresponde a un hospital general de tamaño medio.

## Alternativas consideradas

No se documentaron alternativas. El rango 200–400 es un parámetro, no una alternativa.

## Consecuencias

- Fija la tasa base de llegadas: λ(t) = base × perfil horario × día × estación × evento.
- Plantilla y tiempos de servicio se ajustan iterando la simulación hasta que los KPIs emergentes se parezcan a los objetivos de calibración.
