# 0029. Calentamiento y horizonte en días completos

- **Estado:** Aceptada
- **Fecha:** 2026-11-03

## Contexto

El motor empieza vacío el día 0 a las 0:00. Con λ(t) variable no hay estado estacionario, sino un régimen periódico, y las métricas no deben arrastrar el sesgo del arranque ([especificación](../specs/hito-3.md#turnos-calentamiento-y-horizonte)). En el hito 1 las métricas ya se calculaban en una ventana \[calentamiento, horizonte\].

## Decisión

- Calentamiento y horizonte se miden en días completos: 2 y 14 por defecto (12 días observados). El horizonte incluye el calentamiento.
- En el modo batch del hito 3 el log es completo, incluido el calentamiento; las métricas usan la ventana, con las reglas de recorte de `mm1_metrics`.
- Los pacientes que siguen dentro al final no tienen `patient_departed`: no se inventa nada para ellos.

Motivo: con un régimen periódico no se mezclan horas del ciclo diario, y las invariantes valen en todo el fichero.

## Alternativas consideradas

- Calentamiento en horas, dentro del rango de 24–48 h del diseño: una ventana que empieza a media tarde mezcla horas del ciclo diario.
- Recortar el log al calentamiento: aparecerían pacientes "ya dentro" sin `patient_arrived`, y las invariantes de conservación y transiciones dejarían de valer en el fichero.
- Medir el calentamiento frente a la media de la semana: confunde el efecto del lunes con el del arranque vacío. Se mide frente al mismo día de la semana siguiente, d + 7 ([anexo, tarea 3.5](../specs/hito-3.md#tarea-35-turnos-y-calentamiento)).

## Consecuencias

- Con 20 semillas, el arranque vacío solo se nota en las horas 0, 1 y 2 del día 0: bastan 2 días, con margen. `check_warmup` lo comprueba con Bonferroni entre las 24 horas.
- `warmup_days` es un entero de 0 a días − 1, y `simulate_ed` lo devuelve en el resultado para que el análisis use la misma ventana.
- El modo directo del hito 6 empezará a publicar al acabar el calentamiento, con un evento de censo inicial.
