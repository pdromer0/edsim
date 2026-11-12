# 0075. Calibración del hito 5 en orden, con un mando por objetivo

- **Estado:** Aceptada
- **Fecha:** 2026-11-10

## Contexto

El hito 5 añade cinco objetivos del SAS a los del hito 4. Sus mandos se influyen entre sí:

- la paciencia se ajusta mirando cuánta gente se va, y eso depende de la espera;
- la espera depende de los médicos y de los boxes bloqueados por la espera de cama;
- el tiempo hasta el médico lo baja el abandono y lo sube la espera de cama.

Un modelo con abandono y boarding, pero calibrado como si no los tuviera, señalaría el problema equivocado ([pieza 5](../specs/hito-5.md#pieza-5--calibrar-con-mandos-acoplados)).

## Decisión

- **Derivados y escritos, sin simular:** ingreso, traslado y exitus.
- **De ajuste**, con un mando cada uno:
  - el abandono (1–4 %), con la paciencia;
  - la estancia media de los ingresados (360–600 min), con la espera de cama.
- **De comprobación:** los ingresados de más de 4 h, la estancia de los atendidos y el ingreso observado.
- **En orden:**
  1. los destinos;
  2. con la plantilla de la 4.6c fija, la paciencia y la cama;
  3. los objetivos del hito 4, medidos de nuevo;
  4. la plantilla cambia solo si sale de su horquilla, con una vuelta como máximo;
  5. el cumplidor vuelve a elegir sus médicos.
- Las reglas de la decisión 41 no cambian: ventana anual, semilla 2026 para elegir, 2027 que puede vetar y 2028 para confirmar.

## Alternativas consideradas

- **Ajustar todos los mandos a la vez:** con mandos acoplados, varias combinaciones dan los mismos objetivos, y la elección no sería identificable.
- **Ajustar también la estancia de todos:** su único mando serían las duraciones, fijas por criterio, y moverlas obligaría a repetir la calibración de los médicos del hito 4.

## Consecuencias

- Cada valor elegido se escribe en `config/` con el comando que lo calcula, y el [registro de calibración](../calibracion/registro.md) gana la sección de la 5.6.
- La 5.6 es la tarea que pone los bloques del hito 5 en `config/`: desde su PR, el modelo por defecto es el del hito 5.

## Qué cambió al implementarla

- **5.6, los boxes, un derivado** (decisión de Pedro del 12 de noviembre, tras parar por el cuello de botella):
  - con los 30 boxes de la decisión 41, ningún k de la rejilla pasaba el abandono, y la espera de box (52 min) superaba a la de médico (16);
  - el hito 4 se calibró sin boxes ocupados por ingresados, así que los boxes pasan a ser los 30 del hito 4 más los que ocupa de media la espera de cama, por la ley de Little (L = λ · W), redondeado: 30 + 6,44 = 36,44, es decir **36**;
  - se mide con la semilla de ajuste (2026); con la de comprobación (2027), λ · W = 6,56 daría 37;
  - las copias del hito 4 de `tests/data` se quedan en 30.
- **5.6, valores elegidos:**
  - la cama, [210, 630] ([ADR 0072](0072-espera-de-cama-lognormal-con-factor-de-turno.md));
  - la paciencia, k = 4, una discrepancia estructural escrita ([ADR 0070](0070-paciencia-lognormal-por-nivel-real.md));
  - la plantilla de la 4.6c y el cumplidor no cambian.
- **5.6, la semana del 19 al 25 de enero** (el pendiente del hito 4): reloj A de los niveles 2 a 5 de 101,0 min, frente a 306,0 en la 4.6c, con 240 abandonos de 2.549 llegadas (9,42 %).
- **5.6:** `calibration/` aplica las reglas de la 5.4 (los censurados son los que siguen dentro; el pretriaje, de los triados; los relojes, con la censura del cumplimiento). `DRAIN_DAYS` sigue en 1: cambiarlo movería las cifras del hito 4.
