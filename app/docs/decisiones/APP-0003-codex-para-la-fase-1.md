# APP-0003. Codex para la fase 1

- **Estado:** Aceptada
- **Fecha:** 2026-11-04

## Contexto

Tras el hito 3, implementado con Claude Code, Pedro quiso aprender otra
herramienta de agentes y usar los créditos de su suscripción de ChatGPT. La fase
1 permite probarla sin cambiar el método de explicación, plan, tests y revisión
([implementación con Codex](../specs/fase-1.md#implementación-con-codex)).

## Decisión

Codex implementa la fase 1 con `AGENTS.md` como fuente única de instrucciones
compartidas y configuración versionada en `.codex/`. Cada tarea empieza con un
plan aprobado; Pedro dirige, revisa y fusiona, y cualquier push requiere su
permiso explícito.

## Alternativas consideradas

- Continuar esta fase solo con Claude Code: mantiene la herramienta conocida,
  pero no permite aprender y contrastar la otra dentro del mismo método
  ([decisiones candidatas](../specs/fase-1.md#decisiones-candidatas)).
- Mantener dos copias de las instrucciones: podrían divergir. `CLAUDE.md`
  importa `AGENTS.md` y conserva únicamente lo específico de Claude Code
  ([PR #28](https://github.com/pdromer0/edsim/pull/28)).
- Ejecutar sin las restricciones del sandbox: se descartó en la especificación;
  la configuración conserva `workspace-write` y aprobación `on-request`
  ([implementación con Codex](../specs/fase-1.md#implementación-con-codex)).

## Consecuencias

- En A.0 se versionaron reglas para las operaciones habituales, con ejemplos
  `match` y `not_match`. Las reglas autorizan la salida del sandbox; no vuelven
  escribibles `.git` ni `.codex/` dentro de él. `git push` y `uv sync` exigen
  aprobación; `gh pr merge` se prohíbe y la prueba en vivo fue rechazada antes
  de ejecutarse. La confianza en el proyecto y aprobación del hook se hacen en
  cada máquina ([PR #28](https://github.com/pdromer0/edsim/pull/28)).
- El hook Stop de Codex formatea y prueba núcleo y app; el de Claude Code
  mantiene los tests rápidos del núcleo. En A.7, las marcas `slow` redujeron la
  suite rápida de la app de 116,66 s a 30,23 s en las medidas publicadas. Las
  suites completas siguen en CI
  ([PR #29](https://github.com/pdromer0/edsim/pull/29),
  [#38](https://github.com/pdromer0/edsim/pull/38)).
- El sandbox produjo costes concretos: acceso a la caché externa de uv y
  operaciones de Git con escalada; Jupyter necesitó salir para abrir sockets.
  Las tareas posteriores usaron caché temporal y el entorno ya instalado cuando
  no cambiaban dependencias
  ([PR #29](https://github.com/pdromer0/edsim/pull/29),
  [#36](https://github.com/pdromer0/edsim/pull/36),
  [#38](https://github.com/pdromer0/edsim/pull/38)).
- La segunda opinión con `@codex review` quedó para contratos críticos y tareas
  elegidas por Pedro. No sustituye la revisión del chat: en A.2a no encontró
  problemas importantes, pero el chat detectó errores de clasificación,
  cabecera y permisos ([anexo A.2a](../specs/fase-1.md#tarea-a2a-núcleo-de-ejecuciones)).
- La comparación factual, las ausencias de datos de consumo y los aprendizajes
  se registran una sola vez en el
  [diario de la fase](../diario/fase-1.md#codex-frente-a-claude-code). Las
  reflexiones personales quedan para Pedro.
