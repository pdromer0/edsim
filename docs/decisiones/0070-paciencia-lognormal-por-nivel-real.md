# 0070. Paciencia lognormal por nivel real, contada desde la llegada

- **Estado:** Aceptada
- **Fecha:** 2026-11-10

## Contexto

Para que un paciente se vaya hace falta una paciencia: los minutos que está dispuesto a esperar al médico, que nadie ve. Lo que publican los estudios es cuánto esperaron los que se fueron (medianas de 70 min en Florencia y de 103 en Ontario). Pero solo se van los que tenían poca paciencia, así que la de todos es mayor y no se puede copiar de un estudio: se calibra contra el porcentaje de abandono ([pieza 1](../specs/hito-5.md#pieza-1--abandono-y-paciencia)).

## Decisión

- **La forma:** paciencia lognormal `[mediana, p90]` por nivel real, en `[abandono]` de `perfiles.toml`, con un factor opcional por banda de edad (`paciencia_edad`).
- **El sorteo:** se sortea al llegar con una normal del flujo 8 y se cuenta desde la llegada.
- **Cada espera antes de ser visto** es «el recurso o el plazo (llegada + paciencia), lo que llegue antes».
- **El empate:** si el plazo vence en el mismo instante en que se concede el recurso, el paciente se queda.

## Alternativas consideradas

- **Por nivel asignado:** antes del triaje no existe, y el paciente nota cómo está, no qué nivel le pusieron. Con el nivel real, un grave infratriado espera como un 4 y casi nunca se va.
- **Contada desde el triaje:** la gente cuenta desde que cruza la puerta.
- **Una exponencial:** sin forma propia para la cola; la lognormal es la de todas las duraciones de EDsim.

## Consecuencias

- Los que se van son los leves y los jóvenes.
- El ground truth guarda la paciencia y su z ([ADR 0076](0076-ground-truth-con-lo-sorteado-y-el-contrafactual.md)), y la invariante `abandonment` comprueba que cada abandono ocurre en su instante.

## Qué cambió al implementarla

- **5.1, el empate:** en SimPy 4.1.2 un `timeout` normal haría depender el empate del orden de creación de los eventos. El plazo es un evento propio, `Deadline`, de prioridad `LATE` (2), que se procesa después de todo lo demás de su instante. Hay un solo plazo por paciente, creado al llegar.
- **5.1, el plazo vencido durante el triaje** (ajuste de la aprobación): nadie abandona durante el triaje, pero el plazo sigue corriendo. Si vence durante él, al acabarlo el paciente se va en ese mismo instante, salvo que reciba box y médico en ese instante. El abandono ocurre en max(llegada + paciencia, fin del triaje).
- **5.3:** si el plazo vence *antes* de empezar el triaje, el paciente no espera a su fin (`0c20622`).
- **5.6, k = 4, una discrepancia estructural** (decisión de Pedro tras parar en k ≥ 4 y un diagnóstico):
  - La paciencia calibrada es la de partida con las medianas y los p90 multiplicados por 4. Da medianas de 10 h en el nivel 4 y de 8 h en el 5, frente a las 2 h que declara la mitad de los pacientes en la encuesta de Shaikh.
  - Se acepta porque el abandono (1,68 %) y el reloj A de los niveles 2 a 5 piden los dos una paciencia larga: con k = 2 el abandono ya pasa, pero el reloj A cae a 27,31 min, fuera de su horquilla. Además, Shaikh mide lo que se declara, en EE. UU., y el 1,82 % del SAS mezcla fugas, abandonos y altas voluntarias.
  - **El diagnóstico** ([registro](../calibracion/registro.md), «Tarea 5.6»; [script](../calibracion/tarea-5-6/diagnostico_paciencia.py)): los que se van no son los de paciencia corta que se van pronto, sino los que esperan mucho (con k = 4, p50 de 191 min hasta irse). Con p90 = 2 × mediana, el abandono apenas cambia (5,11 % frente a 5,49 %): la forma (σ) no explica la discrepancia.
  - k = 4 compensa las esperas de invierno de una plantilla anual: si llega el refuerzo de invierno, hay que recalibrarlo (#108).
- **5.7, el Kaplan–Meier:** de los que se van solo se ve la cola izquierda de la paciencia. Con k = 4 la mediana del nivel 4 es de 600 min y casi nadie espera tanto, así que por encima del mayor tiempo observado el estimador no dice nada. Por eso la 5.6 necesitó k = 4 sin que ningún dato lo contradijera. El KM toma como evento a quien se va al acabar el triaje con el plazo vencido, sin corregirlo: 7 de 1.061 (0,7 %).
