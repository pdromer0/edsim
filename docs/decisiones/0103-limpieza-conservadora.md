# 0103. Limpieza conservadora: arreglar lo seguro, señalar lo detectable, no inventar

- **Estado:** Aceptada
- **Fecha:** 2026-11-16

## Contexto

Un analista de hospital no tiene la verdad: ante cada despiste del registro clínico solo puede arreglarlo con una regla segura, señalarlo o dejarlo pasar porque no lo detecta. La tabla de tres columnas mide cuánto recupera la limpieza ([pieza 2](../specs/hito-8.md#pieza-2--la-limpieza-qué-se-arregla-y-qué-no)).

## Decisión

- **Se arreglan** los duplicados (las dos clases: relectura de Kafka y doble clic) y las correcciones tardías; el desorden y el retraso se arreglan por diseño, porque plata usa `event_time`.
- **Se señalan** los campos vacíos, los olvidos (episodios sin salida o sin llegada) y los tiempos negativos.
- **No se tocan** el reloj desajustado ni los valores erróneos sin corregir.

## Alternativas consideradas

- **Limpieza agresiva** (rellenar vacíos con la moda o la mediana, cerrar fantasmas pasadas X horas, estimar el desfase de cada reloj): quizá acerque algún KPI, pero inventa datos. Tiene sentido como ejercicio del laboratorio.
- **Limpieza mínima** (solo duplicados y correcciones): pierde la mitad de la lección.

## Consecuencias

- La lección es lo que no se puede arreglar: el notebook 08 lo enseña regla a regla frente a la libreta.

## Qué cambió al implementarla

- **8.1** (#149): la medida previa de la clave de duplicados, en `r2026` con esquema 4, dio 0 pares de hechos reales iguales. La corrección se aplica con `payload || coalesce(campos, '{}')`, y un registro sin corrección queda con `corregido = false`, no `NULL`.
- **8.3** (#151): `tiempo_negativo` no compensa los relojes, como quiere esta decisión.
- **8.8** (#157), **el resultado en 14 días:** la limpieza conservadora apenas mueve los indicadores del flujo.
  - El censo y las medianas salen iguales en ingenuo y limpio, porque los fantasmas y los relojes se señalan, pero no se arreglan.
  - En las llegadas, el ingenuo sale +3 por casualidad, porque los dobles clics de admisión compensan los olvidos; el limpio, −15, las olvidadas en la ventana.
  - Lo único que mejora un poco es el reparto por nivel, con las correcciones.
- **8.8:** las correcciones sin registro son 0 por construcción, porque una corrección apunta al original y la regla de duplicados se queda con él.
