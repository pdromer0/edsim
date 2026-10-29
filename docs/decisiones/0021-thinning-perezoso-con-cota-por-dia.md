# 0021. *Thinning* de Lewis–Shedler perezoso, con cota por día comprobada

- **Estado:** Aceptada
- **Fecha:** 2026-10-29

## Contexto

Hay que generar un proceso de Poisson no homogéneo con la λ(t) del perfil, de forma exacta, reproducible por semilla y que pueda funcionar en vivo cuando haya *pacer* y *shocks* ([especificación](../specs/hito-2.md#generación-por-thinning)).

## Decisión

- Las llegadas se generan día a día con el algoritmo de Lewis–Shedler: candidatas a tasa constante λ\* y aceptación con probabilidad λ(t)/λ\*.
- La cota de cada día es Z · escala del día · máx(h), el pico del día. La candidata que pasa de medianoche se descarta y el día siguiente empieza a las 0:00 con su propia cota.
- Cada candidata comprueba que λ(t) ≤ λ\* (con un margen relativo de 10⁻¹²); si no, `RuntimeError`.
- `iter_arrivals` es un generador perezoso; `simulate_arrivals` lo consume entero y `arrival_source` es el proceso SimPy que lo entrega en el motor.

Motivo: exacto sin integrar ni invertir Λ, funciona en vivo, y la comprobación evita que una cota baja recorte los picos sin avisar.

## Alternativas consideradas

- Invertir Λ (reescalado temporal) o integrarla numéricamente: más código y sin la sencillez del *thinning*.
- Una cota global para todo el horizonte: también es exacta, pero desperdicia más candidatas en los días de poca afluencia.

## Consecuencias

- La aceptación es 1/máx(h) = 1/1,68 ≈ 59,5 % cualquier día, porque d, m y Z afectan igual a λ y a la cota. Medido en un año: 0,5957.
- Reiniciar a medianoche es exacto porque la exponencial no tiene memoria. Arrancar el día siguiente en el instante de la candidata descartada (versión C′) pierde unas 0,44 llegadas al día, casi invisibles para las pruebas globales.
- El orden de los sorteos (primero el hueco, después la uniforme) queda fijado y una huella SHA-256 de las llegadas lo protege. Sortear por bloques cambiaría la secuencia y tendría que ser una decisión consciente.
- Los ganchos `on_day` (registros diarios) y `on_candidate` (candidatas aceptadas y descartadas) dejan observar el algoritmo sin una segunda implementación.
- La comprobación de la cota atrapó en la tarea 2.3 un error que ningún test buscaba: Z en λ pero no en la cota.
