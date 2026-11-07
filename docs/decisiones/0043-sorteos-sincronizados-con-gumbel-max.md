# 0043. Sorteos sincronizados: Gumbel-max, z estándar transformadas y ocho flujos

- **Estado:** Aceptada
- **Fecha:** 2026-11-07

## Contexto

Desde el hito 3, cada fuente de azar tiene su flujo y cada paciente hace todos sus sorteos al llegar, en orden fijo ([ADR 0007](0007-un-flujo-aleatorio-por-fuente.md) y [ADR 0024](0024-paciente-como-proceso-con-sorteos-al-llegar.md)): así el paciente k es el mismo con otra plantilla. El hito 4 quiere lo mismo para los escenarios clínicos (un brote de gripe, otra gravedad): con otro parámetro clínico, deben cambiar solo los pacientes que el cambio afecta ([especificación, «El muestreador clínico en el motor»](../specs/hito-4.md#el-muestreador-clínico-en-el-motor)).

## Decisión

- Las categorías (banda de edad, motivo) se sortean con Gumbel-max: un sorteo de Gumbel por categoría y gana el mayor log w + g.
- Las variables continuas se sortean como z estándar (o uniformes) y los parámetros las transforman después: al cambiar un parámetro, el paciente conserva su percentil.
- Consumo fijo por flujo, salga lo que salga, y un flujo por fuente: `child_streams(seed, 8)`. El flujo 0 son las llegadas; el 1, el error de la enfermera (1 normal); el 2, las duraciones (3 normales); el 3, las pruebas (12 sorteos); el 4, el destino (1 uniforme); el 5, la población (4 Gumbel y 3 uniformes); el 6, el motivo (17 Gumbel); el 7, la gravedad (1 normal).

Motivo: números aleatorios comunes también para escenarios clínicos: con la gripe cambia el 3,37 % de los pacientes, el mínimo posible, y no el 15,55 %.

## Alternativas consideradas

- La CDF inversa para las categorías: con la disnea ×1,5 cambia el 15,55 % de los pacientes de un año, también entre motivos que nadie ha tocado, porque depende del orden de las categorías. Con Gumbel-max cambia el 3,37 %, exactamente el mínimo (la distancia de variación total), y todos van hacia la disnea ([«Motivos de consulta»](../specs/hito-4.md#motivos-de-consulta)).
- Un flujo compartido para la gravedad y el error del triaje: cambiar el ruido movería la gravedad. La versión incorrecta V5 de la tarea 4.3 lo comprobó ([anexo, tarea 4.3](../specs/hito-4.md#tarea-43-gravedad-latente-y-triaje)).
- Un número de sorteos que depende de lo que salga (por ejemplo, sortear la respuesta solo si se pide la prueba): cambiar un porcentaje desplazaría los valores de todos los pacientes siguientes.

## Consecuencias

- `child_streams(seed, 8)` da los mismos cinco primeros hijos que `child_streams(seed, 5)`: las llegadas no cambian ni un bit entre los dos modelos.
- La comparación de ejecuciones tiene tres tipos de emparejamiento (tarea 4.8a): plantilla (mismos perfiles, la verdad clínica entera igual), clínico (perfiles distintos: los mismos sorteos estándar con otros valores) y sin emparejar (modelos distintos). Con la gripe en 3 días de enero cambian de motivo 43 de 1101 pacientes, todos hacia la disnea (48,4 esperados).
- El ground truth guarda la z de la gravedad y los 12 sorteos de las pruebas; los de persona, motivo y duraciones se reconstruyen con la semilla.
- El paciente clínico cuesta unos 486–522 µs frente a 252–264 µs del provisional (14 días, `config/`; [anexo, tarea 4.5a](../specs/hito-4.md#tarea-45a-el-clinicalsampler-en-el-motor)).
- Los sorteos comunes no implican resultados idénticos: si con otra plantilla el pedido de pruebas cruza un cambio de franja, la ronda dura otra cosa, y eso es correcto.
